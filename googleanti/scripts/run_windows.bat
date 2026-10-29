@echo off
setlocal enabledelayedexpansion

REM Fixar diretorio de trabalho sempre na raiz do projeto (um nivel acima de scripts\)
cd /d "%~dp0\.."
set "ROOT_DIR=%CD%"

echo ========================================================
echo        INICIALIZADOR LOCAL DO AI 3D STUDIO
echo  100%% Local (127.0.0.1) - Sem dependencia do Blender
echo  Diretorio raiz: %ROOT_DIR%
echo ========================================================

REM 1. Verificar Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao foi encontrado no PATH. Instale o Python 3.10+ para prosseguir.
    pause
    exit /b 1
)

REM 2. Verificar Node.js
node --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Node.js nao foi encontrado no PATH. Instale o Node.js 18+ para prosseguir.
    pause
    exit /b 1
)

REM 3. Preparar venv do backend se necessario
if not exist "%ROOT_DIR%\backend\venv\Scripts\python.exe" (
    echo [INFO] Criando ambiente virtual Python...
    python -m venv "%ROOT_DIR%\backend\venv"
    call "%ROOT_DIR%\backend\venv\Scripts\pip.exe" install -r "%ROOT_DIR%\backend\requirements.txt"
)

REM 4. Iniciar Backend em uma nova janela
echo [INFO] Iniciando Backend FastAPI em http://127.0.0.1:8000...
start "AI 3D Studio - Backend" cmd /k "cd /d "%ROOT_DIR%" && set PYTHONPATH=. && "%ROOT_DIR%\backend\venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

REM 5. Iniciar Frontend em uma nova janela
echo [INFO] Iniciando Frontend Vite em http://127.0.0.1:5173...
cd /d "%ROOT_DIR%\frontend"
if not exist "node_modules" (
    echo [INFO] Instalando dependencias do frontend...
    call npm install
)
start "AI 3D Studio - Frontend" cmd /k "cd /d "%ROOT_DIR%\frontend" && npm run dev -- --host 127.0.0.1"
cd /d "%ROOT_DIR%"

echo ========================================================
echo AI 3D Studio iniciado com sucesso!
echo Backend:  http://127.0.0.1:8000/docs
echo Frontend: http://127.0.0.1:5173
echo ========================================================
pause
