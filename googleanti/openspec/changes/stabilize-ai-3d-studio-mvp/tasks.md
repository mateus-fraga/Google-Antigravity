# Tasks: Estabilização e Conclusão do MVP do AI 3D Studio

## 1. Segurança de Arquivos e Armazenamento Transacional (R1, R4 / SEC-001, STORE-001)

- [x] 1.1 Substituir rota `/files/download` por endpoint contextual seguro `/api/v1/projects/{project_id}/artifacts/{filename}` com sanitização de nome base, verificação estrita via `os.path.commonpath`, rejeição de symlinks e validação de registro na lista de artefatos do projeto
- [x] 1.2 Implementar protocolo de exclusão recuperável em duas fases para `DELETE /projects/{id}`: marcação do projeto como `DELETING`, isolamento físico atômico da pasta do projeto em quarentena (`storage/.quarantine/`), commit SQLite e remoção assíncrona da quarentena
- [x] 1.3 Implementar rotina de inicialização no lifespan do FastAPI para reconciliação automática de pastas órfãs deixadas em quarentena por reinicialização
- [x] 1.4 Criar suite de testes de segurança e persistência em `backend/tests/test_security.py` cobrindo tentativas de path traversal (`../`, caminhos absolutos, caracteres ilegais), symlinks, acesso cruzado entre projetos e reversão em falha de exclusão

## 2. Orquestração, Não-Bloqueio e Cancelamento Efetivo (R2 / ASYNC-001)

- [x] 2.1 Refatorar `JobOrchestrator` para descarregar rotinas intensivas de geometria (`ProceduralGenerator` e `ModelExporter`) para worker threads via `asyncio.to_thread`, limitadas por semáforo de concorrência (`asyncio.Semaphore(max_workers=2)`)
- [x] 2.2 Implementar cancelamento cooperativo com `threading.Event` integrado aos pontos de controle do pipeline procedural e descarte imediato de arquivos parciais/temporários gerados
- [x] 2.3 Implementar rotina de reconciliação no lifespan do FastAPI em `backend/app/main.py` para transitar tarefas não-terminais (`Pendente`, `Preparando`, `Em Execução`) para `Cancelada` no reinício do servidor
- [x] 2.4 Criar suite de testes de concorrência e recuperação em `backend/tests/test_recovery.py` validando não-bloqueio de requisições HTTP durante jobs pesados, cancelamento efetivo e recuperação pós-reboot

## 3. Validação Paramétrica, Alinhamento Y-up e Compatibilidade (R3 / GEO-001)

- [x] 3.1 Reforçar validação de limites e tipos nos schemas `ProceduralParams` e `IntermediateObjectRepresentation` (Pydantic V2) rejeitando dimensões $\le 0$, valores não finitos, infinitos e NaN
- [x] 3.2 Adequar todas as primitivas procedurais (`create_box`, `create_cylinder`, `create_gear`, `create_table`) em `backend/app/procedural/engine.py` para convenção Y-up nativa (assentamento no solo XZ em $Y=0$ com altura positiva em Y e normais externas corretas)
- [x] 3.3 Implementar suporte a metadado de orientação nos projetos para identificar modelos legados Z-up e prevenir dupla conversão no carregamento
- [x] 3.4 Atualizar testes existentes e criar `backend/tests/test_coordinates.py` validando bounding boxes, normais orientadas, malhas assimétricas e conformidade Y-up

## 4. Visualizador Three.js e Interface do Usuário (R4, R6 / MEM-001, UI-001)

- [x] 4.1 Implementar método recursivo de descarte profundo (`disposeHierarchy`) em `frontend/src/viewer/ThreeViewer.ts` liberando geometrias, materiais e texturas ao substituir modelos ou desmontar componente
- [x] 4.2 Adicionar indicador de eixos orientados com convenção Y-up visível e grade no plano de solo XZ no `ThreeViewer.ts`
- [x] 4.3 Adicionar seletor de exportação multiformato (GLB, OBJ, STL) com verificação de artefatos disponíveis e botão de cancelamento de tarefa na interface em `frontend/src/App.tsx`
- [x] 4.4 Atualizar `frontend/src/services/api.ts` para consumir o novo endpoint contextual seguro de artefatos e suporte a cancelamento de tarefas

## 5. Verificação Completa e Integração Contínua (R4, R6)

- [ ] 5.1 Atualizar `backend/tests/test_api.py` e `backend/tests/test_e2e.py` para refletir as rotas contextuais seguras de artefatos e convenção Y-up
- [ ] 5.2 Executar a suite completa de testes automatizados do backend (`pytest backend/tests -v`) garantindo 100% de aprovação sem regressões
- [ ] 5.3 Executar build de produção do frontend (`npm run build`) validando tipos TypeScript e ausência de erros de compilação
- [ ] 5.4 Documentar e validar o roteiro de testes de aceitação visual e interativa no navegador para o Three.js cobrindo órbita, inspeção, troca de modelo e exportação multiformato
