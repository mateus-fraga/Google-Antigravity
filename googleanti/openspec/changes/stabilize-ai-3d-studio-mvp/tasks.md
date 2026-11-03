# Tasks: Estabilização e Conclusão do MVP do AI 3D Studio

## 1. Segurança de Arquivos e Armazenamento Transacional

- [ ] 1.1 Substituir rota de download livre por endpoint contextual seguro `/api/v1/projects/{project_id}/artifacts/{filename}` com sanitização de caminho e verificação estrita via `commonpath`
- [ ] 1.2 Implementar remoção física atômica da pasta `projects/{project_id}` sincronizada com a transação de exclusão de projeto (`DELETE /projects/{id}`)
- [ ] 1.3 Criar suite de testes de segurança em `backend/tests/test_security.py` cobrindo tentativas de path traversal (`../`, caminhos absolutos, caracteres ilegais) e exclusão controlada

## 2. Orquestração, Não-Bloqueio e Cancelamento Efetivo

- [ ] 2.1 Refatorar `JobOrchestrator` para descarregar rotinas intensivas de geometria (`ProceduralGenerator` e `ModelExporter`) para threadpool via `asyncio.to_thread` com controle de concorrência (`asyncio.Semaphore`)
- [ ] 2.2 Implementar cancelamento efetivo e cooperativo de tarefas em execução, interrompendo o processamento e limpando arquivos parciais não validados
- [ ] 2.3 Implementar rotina de reconciliação no lifespan do FastAPI em `backend/app/main.py` para marcar tarefas pendentes/em execução órfãs como finalizadas no reinício do servidor
- [ ] 2.4 Criar suite de testes de recuperação e concorrência em `backend/tests/test_recovery.py` validando não-bloqueio, cancelamento e transições pós-reinicialização

## 3. Validação Paramétrica e Alinhamento Geométrico (Y-up)

- [ ] 3.1 Reforçar validação de limites e tipos nos schemas `ProceduralParams` e `IntermediateObjectRepresentation` (Pydantic V2) rejeitando dimensões não positivas, infinitos ou NaN
- [ ] 3.2 Adequar todas as primitivas procedurais (`create_box`, `create_cylinder`, `create_gear`, `create_table`) em `backend/app/procedural/engine.py` para assentamento no plano de solo XZ em $Y=0$ com altura positiva ao longo do eixo Y
- [ ] 3.3 Atualizar testes geométricos existentes e criar `backend/tests/test_coordinates.py` validando bounding boxes, normais orientadas e conformidade Y-up

## 4. Visualizador Three.js e Interface do Usuário

- [ ] 4.1 Implementar método recursivo de descarte profundo (`disposeHierarchy`) em `frontend/src/viewer/ThreeViewer.ts` para liberar geometrias, materiais e texturas ao substituir modelos ou desmontar componente
- [ ] 4.2 Adicionar indicador de eixos orientados com convenção Y-up visível e grade no plano de solo XZ no `ThreeViewer.ts`
- [ ] 4.3 Adicionar seletor de exportação multiformato (GLB, OBJ, STL) e botão de cancelamento de tarefa na interface em `frontend/src/App.tsx`
- [ ] 4.4 Atualizar `frontend/src/services/api.ts` para consumir o novo endpoint contextual seguro de artefatos e suporte a cancelamento

## 5. Verificação Completa e Integração Contínua

- [ ] 5.1 Atualizar `backend/tests/test_api.py` e `backend/tests/test_e2e.py` para refletir as rotas contextuais seguras e convenção Y-up
- [ ] 5.2 Executar a suite completa de testes automatizados do backend (`pytest backend/tests -v`) garantindo 100% de aprovação sem regressões
- [ ] 5.3 Executar build de produção do frontend (`npm run build`) validando tipos TypeScript e ausência de erros de compilação
- [ ] 5.4 Validar o script de inicialização multiplataforma (`scripts/run_windows.bat` e `scripts/run.sh`) garantindo prontidão operacional local
