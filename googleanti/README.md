# AI 3D Studio

> **AI 3D Studio** – um conjunto de ferramentas para modelagem procedural e processamento 3‑D impulsionado por IA.

## Visão geral
Este repositório contém a implementação completa de um _studio_ de modelagem 3‑D baseado em inteligência artificial. Ele está dividido em três partes principais:

- **Backend** – API em FastAPI que expõe funcionalidades de geração e manipulação procedural de geometria, além de serviços auxiliares (persistência, validação, etc.).
- **Frontend** – Aplicação React + TypeScript (Vite) que fornece a interface de usuário para criar, visualizar e exportar modelos.
- **Documentação** – Guia de arquitetura, tutoriais de uso e relatórios de validação geométrica (`docs/`).

O objetivo é oferecer um fluxo de trabalho inteiro, desde a criação automática de objetos 3‑D até a sua inspeção e exportação, tudo controlado por chamadas de API e uma UI responsiva.

## Estrutura do repositório
```
googleanti/
├─ backend/          # Código FastAPI
│   └─ app/          # Rotas, configuração, inicialização
├─ frontend/         # Aplicação React + Vite
│   ├─ src/          # Componentes, hooks, estilos
│   └─ public/       # Arquivos estáticos
├─ docs/              # Documentação do projeto
├─ .agents/          # Agentes Antigravity (skills, workflows)
├─ .env.example      # Exemplo de variáveis de ambiente
└─ README.md         # Este arquivo
```

## Pré‑requisitos
- **Python ≥ 3.10** (recomendado 3.11)
- **Node.js ≥ 18** e **npm** ou **pnpm**
- **Poetry** (gerenciador de dependências Python) – opcional, mas recomendado
- Sistema operacional Windows (conforme ambiente atual)

## Configuração e execução
### Backend
```bash
# Crie um ambiente virtual (ex.: venv)
python -m venv backend/venv
source backend/venv/Scripts/activate   # PowerShell: .\backend\venv\Scripts\Activate.ps1

# Instale as dependências
pip install -r backend/requirements.txt

# Copie as variáveis de ambiente
copy .env.example .env
# Ajuste .env conforme necessário (por ex., portas, chaves de API)

# Inicie a API
uvicorn backend.app.main:app --reload
```
A API ficará disponível em `http://localhost:8000`. A documentação automática pode ser acessada em `http://localhost:8000/docs` (Swagger) ou `http://localhost:8000/redoc`.

### Frontend
```bash
cd frontend
npm install   # ou pnpm install
npm run dev   # inicia Vite dev server
```
O cliente será servido em `http://localhost:5173` (ou outra porta indicada).

## Documentação
A pasta `docs/` contém:
- **Visão da arquitetura** – diagramas de componentes e fluxos de dados.
- **Guia de usuário** – como usar a UI, gerar modelos, exportar arquivos.
- **Relatórios de validação** – testes de integridade geométrica.

Visite `docs/README.md` para mais detalhes.

## Contribuição
1. Fork este repositório.
2. Crie uma branch para sua feature ou correção (`git checkout -b feature/xyz`).
3. Teste as mudanças localmente (backend + frontend).
4. Abra um Pull Request descrevendo a mudança.

Para questões de estilo e lint, o backend usa **flake8** e o frontend **oxlint**/ESLint. Os scripts de CI podem ser encontrados em `.github/workflows/` (se houver).

## Licença
Este projeto está licenciado sob a **MIT License** – veja o arquivo `LICENSE` para detalhes.
