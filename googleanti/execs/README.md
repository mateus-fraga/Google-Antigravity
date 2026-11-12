# Executáveis Facilitadores — AI 3D Studio (`execs/`)

Esta pasta contém os scripts de inicialização rápida para subir todo o ambiente de desenvolvimento e testes do **AI 3D Studio** com um único comando.

## 1. Inicialização com um Único Comando

### Windows (`start_dev.bat`)

No PowerShell, Prompt de Comando (CMD) ou com duplo clique no Windows Explorer:

```powershell
.\execs\start_dev.bat
```

O que o script faz automaticamente:
1. Verifica se `python` e `node` estão disponíveis no `PATH`.
2. Verifica se o ambiente virtual Python (`backend/venv`) existe; caso não exista, cria-o e instala todas as dependências de `backend/requirements.txt`.
3. Verifica se as dependências do frontend (`frontend/node_modules`) estão instaladas; caso não estejam, executa `npm install`.
4. Inicia simultaneamente em janelas dedicadas:
   - **Backend (FastAPI/Uvicorn)**: `http://127.0.0.1:8000` (Swagger UI em `http://127.0.0.1:8000/docs`)
   - **Frontend (React + Vite)**: `http://127.0.0.1:5173`
5. Para encerrar ambos os servidores de uma só vez, basta pressionar qualquer tecla na janela principal do inicializador (ou fechar cada janela individualmente / pressionar `CTRL+C`).

---

### Linux / macOS / Git Bash (`start_dev.sh`)

```bash
chmod +x ./execs/start_dev.sh
./execs/start_dev.sh
```

O que o script faz automaticamente:
1. Verifica `backend/venv` e `frontend/node_modules`, instalando dependências caso necessário.
2. Inicia o Backend (`127.0.0.1:8000`) e o Frontend (`127.0.0.1:5173`) em paralelo.
3. Captura `SIGINT`/`SIGTERM` (`trap`) para encerrar ambos os processos de forma limpa ao pressionar `CTRL+C`.

---

## 2. Execução Automatizada da Suíte de Testes (`run_tests.bat`)

Para rodar toda a suíte de testes do Backend (`pytest backend/tests -v`), o build de produção (`npm run build`) e o linter (`npm run lint`) do Frontend com um único comando no Windows:

```powershell
.\execs\run_tests.bat
```
