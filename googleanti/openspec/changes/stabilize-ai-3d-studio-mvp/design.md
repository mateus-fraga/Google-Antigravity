# Design: Estabilização Técnica e Arquitetura Robusta do MVP

## Context

O AI 3D Studio foi inicializado na mudança `init-ai-3d-studio` com foco em demonstrar a capacidade de gerar geometria procedural offline, exportar para GLB e visualizá-la no navegador com Three.js. A auditoria técnica aprofundada confrontando a base de código com o Prompt Mestre (`AI_3D_Studio_Prompt_Universal_v2.1.md`) e com o guia de revisão técnica final revelou que, para garantir estabilidade, segurança e precisão geométrica em ambiente real de uso, são necessárias correções de arquitetura de execução, resiliência no armazenamento, alinhamento de coordenadas, isolamento de segurança e ciclo de vida de recursos.

A geração procedural existente constitui a infraestrutura base de suporte (Fase 1 do Prompt Mestre), e deve ser estabilizada de modo a servir de alicerce para as fases universais futuras: **Text-to-3D** (Fase 2) e **Image-to-3D** (Fase 3).

## Goals / Non-Goals

**Goals:**
- **R1 — Protocolo Recuperável de Exclusão de Projetos**:
  - Reconhecer que SQLite e o filesystem local **não compartilham transação atômica distribuída**.
  - Implementar protocolo em 2 fases baseado em estado persistente: marcar projeto no SQLite como `deleting` (bloqueando novas tarefas e requisições), mover diretório para quarentena temporária interna (`storage/.quarantine/{project_id}`), executar commit no banco, remover a quarentena em background e reconciliar na inicialização caso haja interrupção no meio do processo.
  - Proteger rigorosamente contra remoção fora de `STORAGE_DIR` e rejeitar symlinks maliciosos.
- **R2 — Isolamento CPU-bound, Concorrência e Cancelamento Real**:
  - Isolar cálculos pesados (Trimesh, Shapely, triangulação Earcut, serialização) em worker threads (`asyncio.to_thread`) sob semáforo assíncrono de concorrência (`asyncio.Semaphore(max_workers=2)`).
  - Reconhecer que cancelar a coroutine assíncrona **não mata a thread síncrona subjacente**; implementar `threading.Event` de cancelamento cooperativo consultado entre etapas (geração 2D, extrusão, exportação, validação) e descarte imediato de arquivos parciais/temporários gerados antes da conclusão.
  - Reconciliar jobs órfãos no lifespan do FastAPI, transitando tarefas não-terminais (`Pendente`, `Preparando`, `Em Execução`) para `Cancelada` (com motivo de reinício de serviço).
- **R3 — Convenção Geométrica Y-up e Compatibilidade**:
  - Harmonizar todo o pipeline (Trimesh, Three.js, glTF 2.0) adotando Y como eixo vertical: primitivas assentadas no solo (plano XZ) com $Y \ge 0$.
  - Preservar compatibilidade de leitura com projetos/modelos gerados anteriormente em Z-up sem dupla conversão (inspeção de metadados de orientação no projeto ou detecção de convenção).
  - Validar orientação de normais, winding e testes com objetos assimétricos.
- **R4 — Cobertura Abrangente de Testes e Segurança**:
  - Testes unitários de schemas com validação finita (Pydantic V2 com `gt=0`, rejeição de NaN/infinito).
  - Testes de segurança de artefatos com tentativas de path traversal codificado (`%2e%2e`), symlinks, acesso cruzado entre projetos e nomes inválidos.
  - Testes de falha induzida (permissão de arquivo, crash de processo).
  - Plano de teste E2E manual reproduzível para o Three.js em tempo de execução no navegador.
- **R5 — Preservação da Arquitetura Futura Text-to-3D e Image-to-3D**:
  - Manter o contrato canônico `IntermediateObjectRepresentation` (IOR) e orquestrador polimórfico por `operation_type`.
  - Registrar explicitamente no planejamento o que é implementado, o que é schema/placeholder e o que é planejado.
- **R6 / MEM-001 / UI-001 — Descarte WebGL e Interface Multiformato**:
  - Descarte profundo e recursivo de geometrias, materiais e texturas em `ThreeViewer.ts`.
  - Exibição de seletor multiformato (GLB, OBJ, STL) na UI com descoberta dos artefatos validados e botão de cancelamento de tarefas ativas.

**Non-Goals:**
- Implementação de modelos generativos neurais locais com pesos (Fase 4 do Prompt Mestre).
- Integração de APIs comerciais externas nesta etapa.
- Reescrita ou migração de banco para Celery/Redis ou PostgreSQL.

## Architecture & System Changes

### 1. Protocolo de Exclusão de Projeto em 2 Fases com Quarentena (R1)
Para resolver a impossibilidade de rollback de filesystem por transação SQLite:
```
[Requisição DELETE /projects/{id}]
                 |
                 v
1. Atualiza status do Projeto no SQLite: status = 'DELETING' (bloqueia novos jobs)
                 |
                 v
2. Move atomicamente a pasta:
   storage/projects/{id}  -->  storage/.quarantine/{id}_{timestamp}
                 |
                 v
3. Executa DELETE no SQLite (Jobs e Projeto) + db.commit()
   - Se commit falhar: restaura pasta da quarentena e reverte status para 'ACTIVE'
                 |
                 v
4. Remove pasta da quarentena em background (shutil.rmtree seguro)
   - Se servidor cair durante o passo 4: rotina de lifespan na inicialização
     varre storage/.quarantine/ e limpa pastas residuais com segurança.
```

### 2. Modelo de Execução de Tarefas em Threadpool e Cancelamento Cooperativo (R2)
Como `asyncio.to_thread` não encerra a thread de forma preemptiva em caso de cancelamento da coroutine:
- Cada job possui um `threading.Event` associado em memória (`cls._cancellation_events[job_id]`).
- O pipeline procedural possui pontos de checagem cooperativos:
  1. *Check 1*: Pré-geração de geometria 2D / parâmetros.
  2. *Check 2*: Pós-extrusão / criação do mesh Trimesh.
  3. *Check 3*: Antes da exportação e validação de arquivos em disco.
- Ao solicitar cancelamento:
  - Marca `cancel_requested` e dispara `event.set()`.
  - Se a tarefa estava no threadpool, o próximo checkpoint detecta o sinal, aborta o processamento, descarta arquivos temporários em disco (`.tmp.glb`) e transita o status para `Cancelada`.
  - Se a tarefa já tiver concluído antes da detecção, a idempotência preserva o estado final `Concluída`.

```
+-----------------------------------------------------------------------------------------+
|                                    FastAPI Event Loop                                   |
|  POST /jobs -> JobOrchestrator.dispatch_job()                                           |
|                     |                                                                   |
|      asyncio.Semaphore(max_concurrent=2)                                                |
|                     |                                                                   |
|         asyncio.to_thread(worker_fn, job_id, cancel_event)                              |
|                     |                                                                   |
|                     +-----------------------------------+                               |
|                     |      Threadpool Worker (Sync)     |                               |
|                     | 1. if cancel_event.is_set(): abort|                               |
|                     | 2. ProceduralGenerator.generate() |                               |
|                     | 3. if cancel_event.is_set(): abort|                               |
|                     | 4. ModelExporter.export_atomic()  |                               |
|                     +-----------------------------------+                               |
|                                     |                                                   |
|       Atualiza Status no SQLite -> CONCLUIDO / FALHOU / CANCELADO                       |
+-----------------------------------------------------------------------------------------+
```

### 3. Convenção de Coordenadas (Y-up e Mão Direita) e Compatibilidade (R3)
- Todas as geometrias procedurais são geradas sob a convenção:
  - **Y**: Vertical (Altura / Para cima, solo em $Y=0$)
  - **X**: Horizontal (Largura)
  - **Z**: Profundidade (Frente / Trás)
- *Compatibilidade*: Projetos existentes sem flag de coordenadas são identificados com metadado `"coordinate_system": "legacy_z_up"`. O ThreeViewer inspeciona esse metadado ao carregar para não aplicar rotações indevidas duplicadas.
- Testes com malhas assimétricas (ex: mesa com pernas deslocadas) garantem que normais e orientação de faces (winding counter-clockwise) continuam estanques e voltadas para fora.

### 4. Segurança de Downloads e Isolamento de Artefatos (R4 / SEC-001)
- Novo endpoint: `GET /api/v1/projects/{project_id}/artifacts/{filename}`
- Regras de validação estritas:
  1. O `project_id` deve existir e estar em status ativo (não `DELETING`).
  2. O `filename` é validado contra regex de caracteres seguros (`^[a-zA-Z0-9_\-\.]+$`), sem barras ou `..`.
  3. Resolução via `os.path.commonpath`:
     ```python
     project_dir = (settings.STORAGE_DIR / project_id).resolve()
     target_path = (project_dir / filename).resolve()
     if os.path.commonpath([project_dir, target_path]) != str(project_dir):
         raise HTTPException(status_code=403, detail="Acesso não autorizado")
     if not target_path.is_file() or target_path.is_symlink():
         raise HTTPException(status_code=404, detail="Artefato não encontrado")
     ```
  4. O artefato solicitado deve constar na lista de arquivos registrados do projeto (`result_files` dos jobs).

### 5. Gestão de Recursos Three.js no Frontend (MEM-001)
Função de descarte profundo recursivo (`disposeHierarchy`) no `ThreeViewer`:
```typescript
private disposeHierarchy(obj: THREE.Object3D) {
  obj.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      const mesh = child as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      if (Array.isArray(mesh.material)) {
        mesh.material.forEach((m) => {
          if (m.map) m.map.dispose();
          m.dispose();
        });
      } else if (mesh.material) {
        if (mesh.material.map) mesh.material.map.dispose();
        mesh.material.dispose();
      }
    }
  });
}
```

### 6. Preservação do Alinhamento Arquitetural com Text-to-3D e Image-to-3D (R5)
- **`IntermediateObjectRepresentation` (IOR)**: Permanece como contrato canônico v2.1 em `backend/app/schemas/geometry.py`.
- **Status Atual no Repositório**:
  - *Procedural Generation*: Implementado e funcional (Fase 1).
  - *IOR & Enums*: Schemas estruturados e validados em testes unitários (placeholder funcional para integração).
  - *Text-to-3D Interpreter*: Planejado para Fase 2 (processamento de linguagem natural PT-BR -> IOR).
  - *Image-to-3D Estimator*: Planejado para Fase 3 (visão computacional -> IOR / malha).
  - *Mesh AI Generativo*: Planejado para Fase 4 (redes neurais locais e provedores externos opcionais).

## Risks & Mitigations

- **Risco**: Falha no disco durante a exclusão da quarentena.
  - *Mitigação*: A rotina de reconciliação no startup limpa diretórios órfãos em `storage/.quarantine/` com logging de auditoria.
- **Risco**: Tarefa demorada bloqueando cancelamento imediato.
  - *Mitigação*: Checkpoints cooperativos em múltiplos estágios garantem aborto rápido, e arquivos parciais são excluídos do disco.
- **Risco**: Modelo legado aparecer deitado após migração.
  - *Mitigação*: Versionamento do sistema de coordenadas gravado no JSON do projeto impede dupla rotação.
