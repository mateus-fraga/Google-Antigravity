#!/usr/bin/env bash
set -euo pipefail

echo "==================================================="
echo "  AI 3D Studio - Inicializador de Desenvolvimento"
echo "==================================================="

# Resolve a raiz do projeto (um nivel acima de execs/ ou scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
echo "[INFO] Diretorio raiz do projeto: ${ROOT_DIR}"

# 1. Verificar pre-requisitos (Python e Node.js)
PYTHON_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERRO] Python nao encontrado no PATH. Instale o Python 3.10+ antes de continuar."
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    echo "[ERRO] Node.js nao encontrado no PATH. Instale o Node.js 18+ antes de continuar."
    exit 1
fi

# 2. Verificar/Criar ambiente virtual Python (backend/venv)
VENV_DIR="${ROOT_DIR}/backend/venv"
if [ -f "${VENV_DIR}/bin/python" ]; then
    VENV_PYTHON="${VENV_DIR}/bin/python"
    VENV_PIP="${VENV_DIR}/bin/pip"
elif [ -f "${VENV_DIR}/Scripts/python.exe" ]; then
    VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
    VENV_PIP="${VENV_DIR}/Scripts/pip.exe"
else
    echo "[SETUP] Ambiente virtual Python nao encontrado em backend/venv. Criando..."
    "${PYTHON_CMD}" -m venv "${VENV_DIR}"
    if [ -f "${VENV_DIR}/bin/python" ]; then
        VENV_PYTHON="${VENV_DIR}/bin/python"
        VENV_PIP="${VENV_DIR}/bin/pip"
    else
        VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
        VENV_PIP="${VENV_DIR}/Scripts/pip.exe"
    fi
    echo "[SETUP] Instalando dependencias do Backend (backend/requirements.txt)..."
    "${VENV_PYTHON}" -m pip install --upgrade pip
    "${VENV_PIP}" install -r "${ROOT_DIR}/backend/requirements.txt"
fi
echo "[OK] Ambiente virtual Python pronto em backend/venv."

# 3. Verificar/Instalar dependencias do Frontend (frontend/node_modules)
if [ ! -d "${ROOT_DIR}/frontend/node_modules" ]; then
    echo "[SETUP] Dependencias do Frontend nao encontradas em frontend/node_modules. Executando npm install..."
    (cd "${ROOT_DIR}/frontend" && npm install)
else
    echo "[OK] Dependencias do Frontend detectadas em frontend/node_modules."
fi

# 4. Garantir diretorios de dados e workspace
mkdir -p "${ROOT_DIR}/workspace/projects" "${ROOT_DIR}/data"

# 5. Gerenciamento de encerramento seguro (trap)
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
    echo ""
    echo "[STOP] Encerrando servidores de desenvolvimento..."
    if [ -n "${BACKEND_PID}" ] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        kill -TERM "${BACKEND_PID}" 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID}" ] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
        kill -TERM "${FRONTEND_PID}" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    echo "[OK] Ambiente de desenvolvimento encerrado."
}

trap cleanup INT TERM EXIT

# 6. Iniciar Backend (FastAPI na porta 8000) e Frontend (Vite na porta 5173) em paralelo
echo "[START] Iniciando Backend FastAPI em http://127.0.0.1:8000 ..."
(
    cd "${ROOT_DIR}"
    export PYTHONPATH="${ROOT_DIR}"
    "${VENV_PYTHON}" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

echo "[START] Iniciando Frontend Vite em http://127.0.0.1:5173 ..."
(
    cd "${ROOT_DIR}/frontend"
    npm run dev -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

echo "==================================================="
echo "  Servidores rodando!"
echo "  - Frontend (UI):  http://127.0.0.1:5173"
echo "  - Backend (API):  http://127.0.0.1:8000"
echo "  - Swagger Docs:   http://127.0.0.1:8000/docs"
echo "  - Health Check:   http://127.0.0.1:8000/health"
echo "  Pressione CTRL+C para encerrar ambos os servicos."
echo "==================================================="

wait "${BACKEND_PID}" "${FRONTEND_PID}"
