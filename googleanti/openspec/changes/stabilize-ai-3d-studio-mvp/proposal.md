# Proposal: Estabilização, Robustez e Conclusão do MVP do AI 3D Studio

## Why

A implementação inicial realizada na mudança `init-ai-3d-studio` estabeleceu com sucesso a base funcional do AI 3D Studio (backend FastAPI, visualizador Three.js, motor procedural com Trimesh/NumPy/Shapely, persistência SQLite e scripts de execução).

No entanto, uma auditoria técnica profunda baseada em evidências reais confrontando a base de código com o Prompt Mestre (`AI_3D_Studio_Prompt_Universal_v2.1.md`) e com as diretrizes de estabilização identificou lacunas críticas de robustez, concorrência, segurança e convenção geométrica que impedem o MVP de operar em nível de produção local:

1. **Bloqueio de Event Loop e Falta de Concorrência Controlada**: Em `backend/app/api/routes.py` e `backend/app/jobs/orchestrator.py`, a execução de Trimesh e Shapely dentro da coroutine assíncrona sem isolamento em threadpool bloqueia o event loop principal, impedindo consultas simultâneas e inviabilizando cancelamentos instantâneos. Falta também controle de concorrência simultânea para evitar exaustão de CPU.
2. **Vulnerabilidade de Acesso a Arquivos (Path Traversal Relativo)**: O endpoint `/files/download` recebe um parâmetro de consulta arbitrário `path`. Embora resolva o caminho, permite que qualquer arquivo dentro da árvore do projeto (como o banco de dados `ai_3d_studio.db` ou código `.py`) seja baixado pelo navegador. O download DEVE ser feito por rota contextual restrita (`/api/v1/projects/{project_id}/artifacts/{filename}`).
3. **Inconsistência de Coordenadas e Eixos (Z-up vs Y-up)**: O motor procedural cria geometrias no plano XY com altura em Z (`mesh.apply_translation([0, 0, height / 2.0])`). O visualizador Three.js e a especificação padrão glTF 2.0 adotam **Y-up** como convenção vertical. Atualmente, os modelos aparecem deitados no visualizador e em softwares 3D externos.
4. **Ciclo de Vida de Projetos e Arquivos Órfãos**: A exclusão de um projeto (`DELETE /projects/{id}`) limpa os registros no SQLite, mas não exclui os arquivos físicos gerados no diretório `projects/{id}`, acumulando lixo em disco e violando a consistência transacional do armazenamento.
5. **Recuperação de Tarefas e Limpeza de Recursos WebGL**:
   - Se o servidor for reiniciado durante o processamento de uma tarefa, os jobs permanecem indefinidamente em `Pendente` ou `Em Execução` no SQLite. É necessária reconciliação no startup do FastAPI.
   - No frontend (`ThreeViewer.ts`), a substituição de modelos não descarta geometrias (`geometry.dispose()`) e materiais (`material.dispose()`), causando vazamento de memória GPU.
6. **Formulários, Validação e Exportações Incompletas na Interface**:
   - A interface só oferece download do formato GLB, embora o backend já suporte OBJ e STL.
   - Não há controle de cancelamento de tarefas ativas na UI.
   - Parâmetros procedurais aceitam valores que podem gerar geometrias degeneradas se não forem estritamente delimitados.

Importante: A infraestrutura procedural existente é o alicerce técnico da Fase 1, não o objetivo final. Esta estabilização prepara e preserva a evolução para **Text-to-3D** (Fase 2) e **Image-to-3D** (Fase 3), assegurando contratos de dados estáveis (como a representação intermediária IOR).

## What Changes

- **Isolamento de CPU, Concorrência e Cancelamento Efetivo**:
  - Migrar a computação pesada do Trimesh e exportadores para threadpool via `asyncio.to_thread` com limite de concorrência (`asyncio.Semaphore`).
  - Implementar cancelamento cooperativo com verificação periódica e limpeza de arquivos parciais.
  - Implementar verificação e marcação automática no lifespan do FastAPI para tarefas órfãs decorrentes de reinicialização.
- **Segurança Reforçada no Download de Artefatos**:
  - Substituir download livre por rota contextual protegida: `/api/v1/projects/{project_id}/artifacts/{filename}` com validação de caminho relativo estrito via `os.path.commonpath`.
- **Harmonização de Coordenadas e Orientação (Y-up)**:
  - Adotar Y-up nativamente no motor procedural e exportador: extrusão e posicionamento das primitivas apoiadas no solo (plano XZ, Y positivo para cima), mantendo consistência estrita com Three.js e glTF 2.0.
- **Validação Rigorosa de Parâmetros**:
  - Validação de entrada nos schemas Pydantic e métodos procedurais para impedir dimensões $\le 0$, valores não finitos ou malhas degeneradas.
- **Gerenciamento de Armazenamento e Limpeza Atômica**:
  - Na exclusão do projeto, realizar a limpeza segura e atômica da pasta física `projects/{project_id}` com garantias transacionais.
- **Prevenção de Memory Leak no Three.js**:
  - Implementar descarte completo e recursivo de `geometry.dispose()`, `material.dispose()` e texturas associadas no `ThreeViewer.ts`.
- **Aprimoramento da Interface do Usuário**:
  - Adicionar suporte na interface para exportação e download nos três formatos suportados (GLB, OBJ, STL).
  - Adicionar botão de cancelamento de tarefa na interface do frontend.
  - Exibir indicador visual de orientação de eixos no visualizador (X=Vermelho, Y=Verde/Cima, Z=Azul).
- **Cobertura Abrangente de Testes**:
  - Testes de segurança para rejeição de caminhos maliciosos (`../`, caminhos absolutos, arquivos fora do projeto).
  - Testes de recuperação pós-reboot e cancelamento de tarefas.
  - Testes de consistência Y-up nas caixas delimitadoras e normais.
  - Teste de aceitação E2E cobrindo cancelamento e exportação multiformato.

## Capabilities

### New Capabilities
<!-- Nenhuma capacidade totalmente nova; o escopo visa estabilização e robustez -->

### Modified Capabilities
- `job-orchestration`: Requisitos para recuperação pós-reinicialização, cancelamento efetivo, concorrência controlada e isolamento obrigatório de computação pesada fora do loop de eventos.
- `model-export`: Requisitos para exportação e download seguro e contextual de múltiplos formatos (GLB, OBJ, STL) diretamente pela interface.
- `model-viewer`: Requisitos para descarte explícito de recursos WebGL (`dispose`) e conformidade estrita com coordenadas Y-up.
- `project-management`: Requisitos para exclusão atômica de arquivos em disco sincronizada com o banco de dados e downloads restritos ao contexto do projeto.
- `procedural-generation`: Requisitos de alinhamento com a convenção Y-up métrica em todas as primitivas procedurais e validação rigorosa de parâmetros.

## Impact

- **Backend**: Alterações em `backend/app/api/routes.py`, `backend/app/jobs/orchestrator.py`, `backend/app/procedural/engine.py`, `backend/app/schemas/geometry.py`, `backend/app/schemas/jobs.py` e `backend/app/main.py`.
- **Frontend**: Alterações em `frontend/src/viewer/ThreeViewer.ts`, `frontend/src/features/generation/GenerationPanel.tsx`, `frontend/src/services/api.ts` e `frontend/src/App.tsx`.
- **Testes**: Adição de novos testes em `backend/tests/test_security.py`, `backend/tests/test_recovery.py`, `backend/tests/test_coordinates.py` e atualização da suite existente.
- **Compatibilidade**: Total compatibilidade com a arquitetura definida no Prompt Mestre v2.1, sem introdução de dependências pesadas externas (sem Redis/Celery, sem Blender). Preservação da IOR para Text-to-3D e Image-to-3D.
