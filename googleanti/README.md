# AI 3D Studio

> **AI 3D Studio** – Conjunto de ferramentas para modelagem procedural e processamento 3D local assistido por IA.

## Inicialização Rápida (Comando Único)

Você pode subir todo o ambiente de desenvolvimento (Backend FastAPI + Frontend React/Vite) com um único comando através dos scripts facilitadores em `execs/` (ou `scripts/`):

### Windows
```powershell
.\execs\start_dev.bat
```
*(Ou dê duplo clique em `execs\start_dev.bat` pelo Windows Explorer. Também disponível em `.\scripts\start_dev.bat`.)*

### Linux / macOS / Git Bash
```bash
chmod +x ./execs/start_dev.sh
./execs/start_dev.sh
```
*(Também disponível em `./scripts/start_dev.sh`.)*

### O que os scripts fazem automaticamente:
1. Verificam se o ambiente virtual Python (`backend/venv`) existe; caso não exista, criam o `venv` e instalam as dependências de `backend/requirements.txt`.
2. Verificam se as dependências do frontend (`frontend/node_modules`) estão instaladas; caso não estejam, executam `npm install`.
3. Iniciam simultaneamente:
   - **Backend FastAPI**: `http://127.0.0.1:8000` (Documentação Swagger: `http://127.0.0.1:8000/docs`)
   - **Frontend Vite**: `http://127.0.0.1:5173`
4. Permitem encerrar ambos os servidores de forma limpa (`CTRL+C` no terminal ou pressionando qualquer tecla na janela controladora do `.bat`).

---

## Execução da Suíte de Testes

Para rodar a suíte completa de testes automatizados do Backend (`pytest`) e validação de build/lint do Frontend com um único comando no Windows:

```powershell
.\execs\run_tests.bat
```

Ou manualmente:
```powershell
# Backend (62 testes automatizados)
.\backend\venv\Scripts\python.exe -m pytest backend/tests -v

# Frontend (TypeScript + Vite build e lint)
cd frontend
npm run build
npm run lint
```

---

## Estrutura do Projeto

```text
googleanti/
├─ backend/          # API FastAPI, motor procedural Y-up, exportadores e testes
├─ frontend/         # Aplicação React + TypeScript + Three.js (Vite)
├─ execs/            # Executáveis facilitadores (start_dev.bat, start_dev.sh, run_tests.bat)
├─ scripts/          # Scripts utilitários e espelho de inicialização
├─ docs/             # Documentação técnica e STABILIZATION_CHANGELOG.md
└─ openspec/         # Especificações e artefatos OpenSpec
```
