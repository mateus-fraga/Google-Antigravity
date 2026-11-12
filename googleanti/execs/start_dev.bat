@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

echo ===================================================
echo   AI 3D Studio - Inicializador de Desenvolvimento
echo ===================================================

:: Resolve a raiz do projeto (um nivel acima de execs/ ou scripts/)
cd /d "%~dp0\.."
set "ROOT_DIR=%CD%"
echo [INFO] Diretorio raiz do projeto: %ROOT_DIR%

:: 1. Verificar pre-requisitos (Python e Node.js)
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERRO] Python nao encontrado no PATH. Instale o Python 3.10+ antes de continuar.
    pause
    exit /b 1
)

where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERRO] Node.js nao encontrado no PATH. Instale o Node.js 18+ antes de continuar.
    pause
    exit /b 1
)

:: 2. Verificar/Criar ambiente virtual Python (backend/venv)
if not exist "%ROOT_DIR%\backend\venv\Scripts\python.exe" (
    echo [SETUP] Ambiente virtual Python nao encontrado em backend\venv. Criando...
    python -m venv "%ROOT_DIR%\backend\venv"
    if %ERRORLEVEL% neq 0 (
        echo [ERRO] Falha ao criar ambiente virtual Python.
        pause
        exit /b 1
    )
    echo [SETUP] Instalando dependencias do Backend ^(backend\requirements.txt^)...
    "%ROOT_DIR%\backend\venv\Scripts\python.exe" -m pip install --upgrade pip
    "%ROOT_DIR%\backend\venv\Scripts\pip.exe" install -r "%ROOT_DIR%\backend\requirements.txt"
    if %ERRORLEVEL% neq 0 (
        echo [ERRO] Falha ao instalar dependencias do Backend.
        pause
        exit /b 1
    )
) else (
    echo [OK] Ambiente virtual Python detectado em backend\venv.
)

:: 3. Verificar/Instalar dependencias do Frontend (frontend/node_modules)
if not exist "%ROOT_DIR%\frontend\node_modules" (
    echo [SETUP] Dependencias do Frontend nao encontradas em frontend\node_modules. Executando npm install...
    pushd "%ROOT_DIR%\frontend"
    call npm install
    if !ERRORLEVEL! neq 0 (
        popd
        echo [ERRO] Falha ao instalar dependencias do Frontend.
        pause
        exit /b 1
    )
    popd
) else (
    echo [OK] Dependencias do Frontend detectadas em frontend\node_modules.
)

:: 4. Garantir diretorios de dados e workspace
if not exist "%ROOT_DIR%\workspace\projects" mkdir "%ROOT_DIR%\workspace\projects"
if not exist "%ROOT_DIR%\data" mkdir "%ROOT_DIR%\data"

:: 5. Iniciar Backend (FastAPI na porta 8000) e Frontend (Vite na porta 5173)
echo.
echo [START] Iniciando Backend FastAPI em http://127.0.0.1:8000 ...
start "AI 3D Studio - Backend (FastAPI :8000)" cmd /k "cd /d ""%ROOT_DIR%"" && set PYTHONPATH=%ROOT_DIR% && ""%ROOT_DIR%\backend\venv\Scripts\python.exe"" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

echo [START] Iniciando Frontend Vite em http://127.0.0.1:5173 ...
start "AI 3D Studio - Frontend (Vite :5173)" cmd /k "cd /d ""%ROOT_DIR%\frontend"" && npm run dev -- --host 127.0.0.1 --port 5173"

echo.
echo ===================================================
echo   Servidores iniciados com sucesso!
echo   - Frontend (UI):      http://127.0.0.1:5173
echo   - Backend (API):      http://127.0.0.1:8000
echo   - Swagger Docs:       http://127.0.0.1:8000/docs
echo   - Health Check:       http://127.0.0.1:8000/health
echo.
echo   Para encerrar os servidores:
echo   - Pressione CTRL+C ou feche as janelas abertas do
echo     Backend e do Frontend, OU
echo   - Pressione qualquer tecla nesta janela para
echo     encerrar ambos os servicos automaticamente.
echo ===================================================
pause >nul

echo.
echo [STOP] Encerrando janelas do Backend e Frontend...
taskkill /FI "WINDOWTITLE eq AI 3D Studio - Backend (FastAPI :8000)*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq AI 3D Studio - Frontend (Vite :5173)*" /T /F >nul 2>&1
echo [OK] Ambiente de desenvolvimento encerrado.
endlocal
