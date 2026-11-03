# Design: Estabilização Técnica e Arquitetura Robusta do MVP

## Context

O AI 3D Studio foi inicializado na mudança `init-ai-3d-studio` com foco em demonstrar a capacidade de gerar geometria procedural offline, exportar para GLB e visualizá-la no navegador com Three.js. A auditoria técnica realizada contra o documento mestre (`AI_3D_Studio_Prompt_Universal_v2.1.md`) e os requisitos de estabilização do MVP revelou que, para garantir estabilidade, segurança e precisão geométrica em ambiente real de uso, são necessárias correções profundas de arquitetura de execução, alinhamento de coordenadas, isolamento de segurança e ciclo de vida de recursos.

A geração procedural existente constitui a infraestrutura base de suporte (Fase 1 do Prompt Mestre), e deve ser estabilizada de modo a servir de alicerce para as fases universais futuras: **Text-to-3D** (Fase 2) e **Image-to-3D** (Fase 3).

## Goals / Non-Goals

**Goals:**
- **Isolamento de Concorrência e Não-Bloqueio**: Isolar cálculos intensivos de geometria (Trimesh, Shapely, earcut) e IO em threads dedicadas (`asyncio.to_thread`) sob semáforo assíncrono de concorrência (`asyncio.Semaphore`), liberando o event loop do FastAPI.
- **Cancelamento Efetivo e Limpeza de Tarefas**: Implementar cancelamento cooperativo com verificação periódica de tokens e limpeza imediata de arquivos parciais/temporários gerados antes da conclusão.
- **Recuperação de Falhas e Transações SQLite**:
  - Reconciliar tarefas órfãs durante o lifespan handler da aplicação, marcando jobs `Pendente`, `Preparando` ou `Em Execução` como `Cancelada` (interrompida por reinício) com timestamp de término.
  - Assegurar transações SQLite seguras e exclusão de pastas físicas com verificação estrita antes do commit do banco.
- **Segurança Hermética de Arquivos**: Restringir endpoints de download exclusivamente ao diretório do projeto solicitado (`/api/v1/projects/{project_id}/artifacts/{filename}`), rejeitando `..`, caminhos absolutos e caracteres inválidos via `os.path.commonpath`.
- **Conformidade Geométrica Y-up & Validação Paramétrica**:
  - Harmonizar todo o pipeline (Trimesh, Three.js, glTF 2.0) adotando Y como eixo vertical: primitivas assentadas no solo (plano XZ) com $Y \ge 0$.
  - Aplicar validação rigorosa de parâmetros nos schemas (Pydantic com `Field(gt=0, le=...)`, rejeição de NaN/infinitos).
- **Ciclo de Vida Limpo de Recursos WebGL**:
  - Liberação recursiva e explícita de geometrias, materiais e texturas WebGL no frontend (`ThreeViewer.ts`) ao carregar novos modelos ou desmontar componente.
- **Exportação Multiformato e Telemetria Real na Interface**:
  - Permitir seleção e download de GLB, OBJ e STL na interface.
  - Adicionar botão de cancelamento de tarefa na barra de status.
  - Exibir eixos visuais (X=Vermelho, Y=Verde/Vertical, Z=Azul) e dimensões reais da malha.

**Non-Goals:**
- Implementação de modelos generativos neurais locais com pesos (Fase 7 do Prompt Mestre).
- Integração de APIs comerciais externas nesta etapa (Fase 4 do Prompt Mestre).
- Implementação de rigging automático ou engines pesadas como Celery/Redis.

## Architecture & System Changes

### 1. Modelo de Execução de Tarefas em Threadpool e Cancelamento Cooperativo
Atualmente, `run_procedural_job_async` roda código intensivo de CPU (Trimesh + Shapely + triangulação Earcut) diretamente na task assíncrona, bloqueando o loop do FastAPI.

```
+--------------------------------------------------------------------------------+
|                             FastAPI Event Loop                                 |
|  POST /jobs -> dispatch_job() -> Task gerenciada com Semaphore(max_concurrent) |
|                                         |                                      |
|                            asyncio.to_thread()                                 |
|                                         v                                      |
|             +----------------------------------------------------+             |
|             |        Threadpool Worker (NumPy/Trimesh)           |             |
|             | - ProceduralGenerator.generate_by_params()         |             |
|             | - ModelExporter.export_and_validate()              |             |
|             +----------------------------------------------------+             |
|                                         |                                      |
|                 Verificação de flag de cancelamento                    |
|                                         v                                      |
|  Atualiza Status no SQLite -> CONCLUIDO / FALHOU / CANCELADO                   |
+--------------------------------------------------------------------------------+
```

### 2. Tratamento de Tarefas Interrompidas na Inicialização
Ao inicializar o servidor em `backend/app/main.py` (via `lifespan` handler do FastAPI):
```python
def reconcile_orphaned_jobs():
    db = SessionLocal()
    try:
        orphans = db.query(JobModel).filter(
            JobModel.status.in_([JobStatus.PENDING.value, JobStatus.PREPARING.value, JobStatus.RUNNING.value])
        ).all()
        for job in orphans:
            job.status = JobStatus.CANCELLED.value
            job.error_message = "Tarefa interrompida devido ao reinício do servidor."
            job.completed_at = get_utc_now()
        db.commit()
    finally:
        db.close()
```

### 3. Convenção de Coordenadas (Y-up e Mão Direita)
- Trimesh padrão cria primitivas com centro em [0, 0, 0] ou alinhadas em Z.
- O AI 3D Studio adota o padrão universal WebGL / glTF:
  - **Y**: Vertical (Altura / Para cima, solo em $Y=0$)
  - **X**: Horizontal (Largura)
  - **Z**: Profundidade (Frente / Trás)
- Todas as operações de criação geométrica, extrusão de polígonos 2D e posicionamento de pernas/componentes são construídas nativamente no plano XZ com altura positiva em Y.

### 4. Segurança de Downloads e Isolamento de Diretórios
- Novo endpoint: `GET /api/v1/projects/{project_id}/artifacts/{filename}`
- Regras de validação estritas:
  1. O `project_id` deve existir no banco de dados.
  2. O `filename` deve ser apenas o nome base (sanitizado contra separadores de caminho).
  3. Resolução segura via:
     ```python
     target_path = (settings.STORAGE_DIR / project_id / filename).resolve()
     project_dir = (settings.STORAGE_DIR / project_id).resolve()
     if not str(target_path).startswith(str(project_dir)) or not target_path.is_file():
         raise HTTPException(status_code=403, detail="Acesso não autorizado")
     ```

### 5. Gestão de Recursos Three.js no Frontend
Função de descarte profundo (`disposeHierarchy`) no `ThreeViewer`:
```typescript
private disposeHierarchy(obj: THREE.Object3D) {
  obj.traverse((child) => {
    if ((child as THREE.Mesh).isMesh) {
      const mesh = child as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      if (Array.isArray(mesh.material)) {
        mesh.material.forEach((m) => m.dispose());
      } else if (mesh.material) {
        mesh.material.dispose();
      }
    }
  });
}
```

### 6. Preservação do Alinhamento Arquitetural com Text-to-3D e Image-to-3D
Para assegurar que o AI 3D Studio evolua sem refatorações estruturais ou reescritas:
- **`IntermediateObjectRepresentation` (IOR)**: A estrutura definida em `backend/app/schemas/geometry.py` mantém campos para `category`, `components`, `transformation`, `user_inputs`, `inferred_data` e `assumed_defaults`. Ela serve como o contrato canônico entre o interpretador de linguagem natural (Text-to-3D) ou o estimador visual (Image-to-3D) e os motores de geração geométrica.
- **Orquestrador Polimórfico**: O `JobOrchestrator` é desacoplado do tipo de operação através do parâmetro `operation_type` (`procedural_generation`, e futuramente `text_to_3d`, `image_to_3d`, `mesh_repair`).

## Risks & Mitigations

- **Risco**: Rotação de coordenadas quebrar modelos salvos anteriormente.
  - *Mitigação*: Apenas os geradores procedurais são atualizados para produzir malhas com base em $Y=0$. O visualizador carrega qualquer glTF padrão sem aplicar transformações forçadas globais.
- **Risco**: Exclusão acidental de arquivos na remoção do projeto.
  - *Mitigação*: Validação estrita de que o diretório a ser removido está contido dentro de `settings.STORAGE_DIR` e corresponde exatamente ao `id` do projeto validado no banco.
