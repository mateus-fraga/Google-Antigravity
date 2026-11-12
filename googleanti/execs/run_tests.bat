@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

echo ===================================================
echo   AI 3D Studio - Executor da Suite de Testes
echo ===================================================

cd /d "%~dp0\.."
set "ROOT_DIR=%CD%"
set "PYTHONPATH=%ROOT_DIR%"
set "PYTEST_DEBUG_TEMPROOT=%ROOT_DIR%\data\pytest_tmp"

if not exist "%PYTEST_DEBUG_TEMPROOT%" mkdir "%PYTEST_DEBUG_TEMPROOT%"

echo.
echo [1/3] Executando suite completa de testes do Backend (Pytest)...
if exist "%ROOT_DIR%\backend\venv\Scripts\python.exe" (
    "%ROOT_DIR%\backend\venv\Scripts\python.exe" -m pytest "%ROOT_DIR%\backend\tests" -v
) else (
    python -m pytest "%ROOT_DIR%\backend\tests" -v
)
if %ERRORLEVEL% neq 0 (
    echo [ERRO] Falha nos testes do Backend.
    pause
    exit /b 1
)

echo.
echo [2/3] Executando build TypeScript + Vite do Frontend...
pushd "%ROOT_DIR%\frontend"
call npm run build
if !ERRORLEVEL! neq 0 (
    popd
    echo [ERRO] Falha no build do Frontend.
    pause
    exit /b 1
)

echo.
echo [3/3] Executando linter do Frontend...
call npm run lint
if !ERRORLEVEL! neq 0 (
    popd
    echo [ERRO] Falha no lint do Frontend.
    pause
    exit /b 1
)
popd

echo.
echo ===================================================
echo   [SUCESSO] Todos os testes e validacoes passaram!
echo ===================================================
pause
endlocal
