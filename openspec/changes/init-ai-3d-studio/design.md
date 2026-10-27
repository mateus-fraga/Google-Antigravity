# Design: AI 3D Studio Architecture & Technical Blueprint

## Context

O AI 3D Studio é projetado para operar localmente na máquina do usuário, combinando um frontend reativo (Vite/React/TypeScript) com visualizador WebGL (Three.js) e um backend assíncrono (FastAPI/Python/SQLite) com processamento de malhas 3D (Trimesh/NumPy). O sistema deve ser completamente independente do Blender ou de dependências proprietárias de nuvem para seu fluxo central de geometria e visualização. Para detalhes de motivação, consulte [proposal.md](file:///C:/Users/User-teste/Documents/googleantigravity/openspec/changes/init-ai-3d-studio/proposal.md).

## Goals / Non-Goals

**Goals:**
- Estabelecer uma arquitetura modular desacoplada: Frontend SPA, Backend API, Motor Procedural, Camada de Armazenamento e Orquestrador de Tarefas.
- Implementar geração procedural pura com primitivas e componentes paramétricos funcionais offline via Trimesh e NumPy.
- Oferecer visualizador Three.js de alto desempenho no navegador com controles de câmera, modos de renderização (sólido, wireframe), grid e telemetria de malha (vértices, faces, dimensões).
- Garantir exportação para GLB/glTF 2.0 (com validação pós-exportação), STL e OBJ.
- Persistir projetos e histórico em SQLite local de forma atômica e segura.
- Adotar um executor de tarefas assíncronas local em memória/banco de dados leve, sem dependência pesada de Redis ou Celery.

**Non-Goals:**
- Rigging automático completo, blend shapes ou pesos de animação esquelética avançada neste incremento inicial (classificado como objetivo futuro Fase 6).
- Integração forçada ou dependência de GPUs dedicadas ou de APIs pagas de IA externas no fluxo básico (devem ser estritamente plugáveis e opcionais).
- Dependência de CLI ou scripts internos do Blender.

## Decisions

### 1. Stack Tecnológica: FastAPI (Backend) + React / Vite / Three.js (Frontend)
- **Decisão**: Utilizar FastAPI no backend e React + Vite + Three.js no frontend.
- **Racional**: FastAPI oferece tipagem estrita com Pydantic, documentação OpenAPI automática e suporte nativo assíncrono (`asyncio`). React com Vite oferece compilação ultrarrápida e ecossistema maduro para integração com Three.js (gerenciamento direto de WebGL Canvas e lifecycle de cena).
- **Alternativas consideradas**: Flask/Django (menos performáticos e sem OpenAPI/Pydantic nativo); Electron/Tauri (adicionariam sobrecarga de empacotamento antes do amadurecimento da API web local).

### 2. Motor de Geometria: Trimesh + NumPy
- **Decisão**: Utilizar `trimesh` e `numpy` para operações geométricas, geração procedural e conversão de formatos.
- **Racional**: `trimesh` é puro Python/NumPy, possui suporte nativo e robusto para exportação/importação de GLB/glTF, OBJ e STL, além de cálculo de normais, fechamento (watertight), e bounding boxes sem requerer binários proprietários ou compilação C++ complexa.
- **Alternativas consideradas**: Blender headless subprocess (rejeitado por violar o princípio de independência do Blender); OpenCASCADE / FreeCAD Python bindings (complexidade de instalação excessiva para execução multiplataforma leve).

### 3. Orquestração de Tarefas: BackgroundTasks com SQLite State Machine
- **Decisão**: Implementar fila de tarefas baseada em `asyncio.create_task` ou `FastAPI.BackgroundTasks` com sincronização de estados no SQLite.
- **Racional**: Evita a necessidade de gerenciar daemons externos como Redis, RabbitMQ e workers Celery na máquina do usuário, mantendo a instalação simples ("zero-friction local run").
- **Alternativas consideradas**: Celery + Redis (muito complexo para uso desktop/local); Threads puras sem persistência (arriscado caso o backend reinicie).

### 4. Sistema de Coordenadas e Formato Primário
- **Decisão**: Adotar o padrão glTF 2.0 (Y-up, escala métrica padrão em metros/unidades consistentes, mão direita) e GLB como formato binário padrão.
- **Racional**: Compatibilidade direta e sem atrito entre o Three.js no frontend e o Trimesh no backend, além de ser o padrão de fato da indústria para modelos web e engines modernas.
- **Alternativas consideradas**: OBJ como padrão (perde hierarquias e é ineficiente em texto); FBX (especificação proprietária e complexa de exportar sem Blender).

## Risks / Trade-offs

- **[Risco] Uso excessivo de memória em geometrias de alta densidade poligonal** → *Mitigação*: Definir limites de subdivisão paramétrica no backend e exibir avisos de contagem de polígonos no frontend antes da renderização.
- **[Risco] Erros de permissão de execução em scripts PowerShell no Windows (ExecutionPolicy)** → *Mitigação*: Fornecer scripts de inicialização que invoquem o Python diretamente ou usem `-ExecutionPolicy Bypass` e arquivo `.bat` compatível com prompt padrão `cmd.exe`.
- **[Risco] Travamento do visualizador 3D em WebGL por falta de aceleração de hardware** → *Mitigação*: Adicionar detecção de suporte WebGL com mensagens de orientação e fallback para renderizador de baixa fidelidade sem sombras pesadas.

## Migration Plan

1. Criação do scaffolding do projeto com separação estrita `frontend/` e `backend/`.
2. Criação do ambiente virtual Python (`requirements.txt`) e instalação das dependências frontend (`package.json`).
3. Verificação automatizada dos endpoints da API e da renderização no Three.js antes da expansão de funcionalidades.
