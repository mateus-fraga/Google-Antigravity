# AI 3D Studio

> **AI 3D Studio** – Plataforma 100% local para geração, reconstrução e inspeção 3D multimodal (**Procedural**, **Text-to-3D** e **Image-to-3D / TripoSR**) em convenção nativa **Y-up** (`glTF 2.0` / `Three.js`).

---

## Principais Funcionalidades

1. **Geração Procedural Paramétrica (`procedural_generation`):**
   - Primitivas e objetos mecânicos/mobiliário (`gear`, `box`, `cylinder`, `table`, `sphere`, `cone`, `torus`) com validação numérica estrita e alinhamento no plano de solo $XZ$ ($Y_{\min} = 0.0$).
2. **Motor Semântico Text-to-3D (`text_to_3d`):**
   - Interpretador bilíngue (PT-BR / EN) com conversão automática de unidades métricas (`m`, `cm`, `mm`), detecção de materiais/cores e composição multi-componente hierárquica (`IntermediateObjectRepresentation`).
3. **Motor Image-to-3D Local (`image_to_3d`):**
   - **Extrusão de Silhueta 2D (`silhouette`):** Extração de contornos e furos internos via OpenCV (`RETR_CCOMP`) + Shapely.
   - **Mapa de Relevo (`heightmap`):** Malha 3D estanque (`watertight`) gerada por luminância com base sólida e paredes fechadas.
   - **Reconstrução Orgânica Neural (`triposr`):** Integração nativa com o **TripoSR (`stabilityai/TripoSR`)**, remoção automática de fundo (`rembg`), extração por Marching Cubes com cores de vértice e higienização topológica/normais via Trimesh.
4. **Visualizador 3D WebGL (Three.js) e Exportação Multiformato:**
   - 7 vistas de câmera predefinidas, modo sólido/aramado, indicadores de eixos Y-up, telemetria em tempo real, cancelamento cooperativo de tarefas e exportação validada em **`.GLB`**, **`.OBJ`** e **`.STL`**.

---

## Inicialização Rápida (Comando Único)

Você pode subir todo o ambiente de desenvolvimento (Backend FastAPI + Frontend React/Vite) com um único comando através dos scripts facilitadores em `execs/` (ou `scripts/`):

### Linux / macOS / Git Bash
```bash
chmod +x ./execs/start_dev.sh
./execs/start_dev.sh
```
*(Também disponível em `./scripts/start_dev.sh`.)*

### Windows
```powershell
.\execs\start_dev.bat
```
*(Ou dê duplo clique em `execs\start_dev.bat` pelo Windows Explorer. Também disponível em `.\scripts\start_dev.bat`.)*

### O que os scripts fazem automaticamente:
1. Verificam se o ambiente virtual Python (`backend/venv`) existe; caso não exista, criam o `venv` e instalam as dependências de `backend/requirements.txt`.
2. Verificam se as dependências do frontend (`frontend/node_modules`) estão instaladas; caso não estejam, executam `npm install`.
3. Iniciam simultaneamente:
   - **Backend FastAPI**: `http://127.0.0.1:8000` (Documentação Swagger: `http://127.0.0.1:8000/docs`)
   - **Frontend Vite**: `http://127.0.0.1:5173`
4. Permitem encerrar ambos os servidores de forma limpa (`CTRL+C` no terminal ou pressionando qualquer tecla na janela controladora do `.bat`).

---

## Configuração da Aceleração GPU para o TripoSR (Opcional)

A arquitetura `tsr` do TripoSR já está integrada diretamente ao repositório em `backend/app/lrm/tsr/` com fallback automático para `PyMCubes`. Para instalar o PyTorch com suporte a **CUDA 12.8** (incluindo GPUs série RTX 50 / Blackwell) em uma nova máquina:

```bash
source backend/venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r backend/requirements.txt
```
Consulte o guia detalhado em [`docs/TRIPOSR_INSTALL.md`](docs/TRIPOSR_INSTALL.md).

---

## Execução da Suíte de Testes

### Linux / macOS
```bash
# Backend (83 testes automatizados)
PYTHONPATH=. ./backend/venv/bin/pytest backend/tests -v

# Frontend (Linter + TypeScript + Vite build)
cd frontend && npm run lint && npm run build
```

### Windows
```powershell
.\execs\run_tests.bat
```
Ou manualmente no PowerShell:
```powershell
$env:PYTHONPATH="."; .\backend\venv\Scripts\python.exe -m pytest backend/tests -v
cd frontend; npm run lint; npm run build
```

---

## Estrutura do Projeto

```text
googleanti/
├─ backend/
│  ├─ app/
│  │  ├─ api/          # Rotas FastAPI, upload/download contextual seguro e quarentena
│  │  ├─ exporters/    # Exportação e validação round-trip (GLB, OBJ, STL)
│  │  ├─ jobs/         # JobOrchestrator assíncrono e cancelamento cooperativo
│  │  ├─ lrm/          # Motor neural TripoSR (triposr_engine.py + pacote tsr embarcado)
│  │  ├─ procedural/   # Motores geométricos Y-up, Text-to-3D e Image-to-3D (silhueta/relevo)
│  │  ├─ schemas/      # Contratos e validações Pydantic
│  │  └─ storage/      # Persistência SQLite (SQLAlchemy)
│  └─ tests/           # Suíte completa de 83 testes automatizados (pytest)
├─ frontend/           # Aplicação React + TypeScript + Three.js (Vite)
├─ execs/              # Scripts facilitadores (start_dev.sh, start_dev.bat, run_tests.bat)
├─ scripts/            # Espelho de scripts utilitários
├─ docs/               # STABILIZATION_CHANGELOG.md, TRIPOSR_INSTALL.md e testes visuais
└─ openspec/           # Especificações e artefatos OpenSpec
```
