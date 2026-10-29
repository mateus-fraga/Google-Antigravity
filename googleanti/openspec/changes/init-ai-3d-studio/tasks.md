# Tasks: Implementação do AI 3D Studio (Fase Inicial & MVP Funcional)

## 1. Fundação e Estrutura do Projeto

- [x] 1.1 Criar a estrutura de diretórios (`backend/`, `frontend/`, `projects/`, `models/`, `docs/`, `scripts/`) e `.env.example` e verificar a existência das pastas
- [x] 1.2 Configurar o ambiente backend com `requirements.txt` (FastAPI, Uvicorn, Trimesh, NumPy, Pydantic, SQLAlchemy, pytest) e verificar a instalação das dependências
- [x] 1.3 Configurar o ambiente frontend com Vite, React, TypeScript e Three.js em `frontend/` e verificar `npm run build` ou inicialização sem erros

## 2. Motor Geométrico e Geração Procedural (Backend)

- [x] 2.1 Implementar schemas Pydantic para representação intermediária e parâmetros geométricos em `backend/app/schemas/` e verificar com testes unitários
- [x] 2.2 Implementar gerador procedural de primitivas e objetos paramétricos (cilindro, cubo, engrenagem, mesa simples) com Trimesh em `backend/app/procedural/` e verificar com testes de integridade e normais
- [x] 2.3 Implementar serviço de exportação e validação de malhas em GLB, OBJ e STL em `backend/app/exporters/` e verificar que arquivos gerados são reimportados com sucesso por testes automatizados

## 3. Persistência, Tarefas e API FastAPI (Backend)

- [x] 3.1 Implementar camada de banco de dados SQLite com SQLAlchemy e models para Projetos e Tarefas em `backend/app/storage/` e verificar migração/criação das tabelas
- [x] 3.2 Implementar orquestrador de tarefas em segundo plano com máquina de estados (Pendente, Em Execução, Concluída, Falhou, Cancelada) em `backend/app/jobs/` e verificar transições via pytest
- [x] 3.3 Implementar endpoints REST para criação de projetos, disparo de tarefas de geração procedural, consulta de status e download de arquivos em `backend/app/api/` e verificar com testes de integração via TestClient

## 4. Visualizador 3D e Interface do Usuário (Frontend)

- [x] 4.1 Implementar visualizador Three.js interativo (câmera orbital, iluminação, grid, modos sólido/wireframe, enquadramento automático) em `frontend/src/viewer/` e verificar renderização de malha de teste
- [x] 4.2 Implementar painel de parâmetros e envio de solicitações em português brasileiro com tratamento de erros em `frontend/src/features/generation/` e verificar conexão com a API
- [x] 4.3 Implementar acompanhamento de estado de tarefas, telemetria de malha (vértices, triângulos, dimensões) e opções de exportação/download no frontend e verificar ciclo completo de geração a download

## 5. Scripts de Inicialização e Verificação de Sistema

- [x] 5.1 Criar scripts multiplataforma para Windows (`scripts/run_windows.bat`), Linux/macOS (`scripts/run.sh`) verificando dependências e iniciando frontend e backend em `127.0.0.1`
- [x] 5.2 Executar teste de aceitação de ponta a ponta (E2E local): criar projeto -> gerar objeto procedural -> inspecionar no Three.js -> exportar GLB -> validar arquivo gerado

## Workflow follow-up

- Revisar e arquivar o OpenSpec change após conclusão e validação do MVP funcional.
- Planejar as fases subsequentes de IA Multimodal e integração de provedores conforme a especificação do documento mestre.
