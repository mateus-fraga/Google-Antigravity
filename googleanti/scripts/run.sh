#!/bin/bash
set -e

# Garantir diretorio raiz
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================================"
echo "       INICIALIZADOR LOCAL DO AI 3D STUDIO"
echo " 100% Local (127.0.0.1) - Sem dependência do Blender"
echo " Diretório raiz: $ROOT_DIR"
echo "========================================================"

if ! command -v python3 &> /dev/null; then
    echo "[ERRO] python3 não encontrado. Instale Python 3.10+."
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "[ERRO] node não encontrado. Instale Node.js 18+."
    exit 1
fi

if [ ! -d "backend/venv" ]; then
    echo "[INFO] Criando venv e instalando dependências backend..."
    python3 -m venv backend/venv
    backend/venv/bin/pip install -r backend/requirements.txt
fi

echo "[INFO] Iniciando backend em http://127.0.0.1:8000..."
export PYTHONPATH=.
backend/venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

echo "[INFO] Iniciando frontend em http://127.0.0.1:5173..."
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
fi
npm run dev -- --host 127.0.0.1 &
FRONTEND_PID=$!
cd "$ROOT_DIR"

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

echo "AI 3D Studio rodando! Acesse http://127.0.0.1:5173"
wait
