# Design: AI 3D Studio Architecture & Technical Blueprint

## Context

O **AI 3D Studio** é projetado rigorosamente a partir da especificação `AI_3D_Studio_Prompt_Universal_v2.1.md` para operar localmente na máquina do usuário sem exigir Blender, conexão de internet ou chaves de terceiros em suas operações essenciais. O sistema é composto por um frontend reativo (Vite/React/TypeScript) com visualizador WebGL interativo (Three.js) e um backend assíncrono (FastAPI/Python/SQLite) com processamento e validação geométrica de malhas 3D (Trimesh/NumPy). Para contexto detalhado, consulte [proposal.md](file:///C:/Users/User-teste/Documents/googleantigravity/googleanti/openspec/changes/init-ai-3d-studio/proposal.md).

## Goals / Non-Goals

**Goals:**
- **Arquitetura Modular Desacoplada**: Apresentação (Frontend SPA), Processamento (Backend API e Motor Geométrico), Armazenamento (SQLite + Diretórios de Arquivos isolados) e Orquestração (State Machine de Tarefas).
- **Representação Intermediária Validada**: Schemas Pydantic (`IntermediateObjectRepresentation`) separando dados fornecidos pelo usuário, observados, inferidos e assumidos por padrão.
- **Motor Procedural Puro & Offline**: Geração geométrica paramétrica (cilindros, engrenagens, parafusos, tubos, mesas, caixas) com Trimesh e NumPy, calculando reais normais, integridade (watertight/manifold), faces e vértices.
- **Visualizador 3D Three.js Completo**: Câmera orbital, vistas ortogonais/isométrica (frente, topo, lateral, etc.), enquadramento automático, grid, modos de renderização (sólido, aramado, materiais) e telemetria (polígonos, vértices, dimensões métricas).
- **Pipeline de Exportação Verificável**: Exportação para GLB/glTF 2.0 (padrão principal), OBJ e STL, com verificação pós-exportação (reimportação e conferência de integridade).
- **Segurança e Privacidade Local**: Execução restrita a `127.0.0.1`, prevenção contra Path Traversal, validação de MIME type e tamanho de arquivos, e isolamento de diretórios temporários.
- **Scripts de Inicialização com Diagnóstico**: Verificação automática de Python e Node.js e execução resiliente no Windows (tratando políticas de execução do PowerShell via `.bat`/bypass) e Linux/macOS.

**Non-Goals:**
- Rigging automático completo, blend shapes ou pesos de deformação esquelética avançada neste incremento inicial (reservado para Fase 6 conforme especificação).
- Download e carregamento automático de pesos massivos de IA local sem autorização expressa do usuário (Fase 7).
- Dependência oculta de serviços externos ou APIs proprietárias no fluxo essencial.
- Dependência de CLI, scripts internos ou binários do Blender.

## Architecture & System Components

```
+------------------------------------------------------------------------+
|                          AI 3D Studio Frontend                         |
|  (React 18+ / TypeScript / Vite / Three.js OrbitControls & Renderers)  |
+-----------------------------------+------------------------------------+
                                    | REST API / JSON + Binary Blobs (GLB)
                                    v
+------------------------------------------------------------------------+
|                          AI 3D Studio Backend                          |
|                       (FastAPI / Uvicorn / 127.0.0.1)                  |
|                                                                        |
| +--------------------+  +----------------------+  +------------------+ |
| | API Routers        |  | Intermediate Repr    |  | Job Orchestrator | |
| | (/api/v1/projects, |  | (Pydantic Schemas    |  | (SQLite State    | |
| |  /api/v1/jobs,     |  |  Versioned)          |  |  Machine)        | |
| |  /api/v1/export)   |  +----------------------+  +------------------+ |
| +--------------------+                                                 |
|                                                                        |
| +------------------------------------+  +----------------------------+ |
| | Procedural Geometry Engine         |  | Storage & Export Service   | |
| | (Trimesh / NumPy: primitives,      |  | (SQLite DB, projects/,     | |
| |  parametric parts, mesh repair)    |  |  GLB/OBJ/STL exporters)   | |
| +------------------------------------+  +----------------------------+ |
+------------------------------------------------------------------------+
```

## Decisions

### 1. Stack Tecnológica: FastAPI (Backend) + React / Vite / Three.js (Frontend)
- **Decisão**: Utilizar FastAPI no backend e React + Vite + Three.js no frontend.
- **Racional**: FastAPI oferece tipagem estrita com Pydantic, documentação OpenAPI automática e suporte assíncrono nativo. React com Vite e Three.js proporciona compilação veloz, renderização WebGL direta e fluida, além de suporte robusto a controles de câmera e shaders padrão.
- **Alternativas consideradas**: Flask/Django (ausência de tipagem e async nativos de ponta a ponta); Tauri/Electron (adicionaria overhead de distribuição antes da estabilização da arquitetura web local).

### 2. Motor de Geometria: Trimesh + NumPy
- **Decisão**: Utilizar `trimesh` e `numpy` para operações geométricas, geração procedural e conversão/validação de formatos.
- **Racional**: `trimesh` é puro Python/NumPy, possui suporte maduro para importação/exportação de GLB/glTF 2.0, OBJ e STL, cálculo de propriedades físicas, detecção de malhas não-estanques (non-watertight) e faces degeneradas sem requerer binários proprietários ou compilação C++ instável.
- **Alternativas consideradas**: Subprocessos com Blender (rejeitado expressamente pela regra fundamental do projeto); OpenCASCADE / FreeCAD Python (complexidade excessiva de instalação e risco de quebra de ambiente).

### 3. Orquestração de Tarefas: BackgroundTasks com SQLite State Machine
- **Decisão**: Implementar fila de tarefas assíncronas no backend utilizando `asyncio` e máquina de estados persistida no SQLite.
- **Racional**: Permite estados explícitos (`Pendente`, `Preparando`, `Em Execução`, `Concluída`, `Falhou`, `Cancelada`), controle de cancelamento e histórico resiliente sem introduzir Redis ou Celery na máquina do usuário.
- **Alternativas consideradas**: Celery + RabbitMQ/Redis (infraestrutura muito pesada para execução desktop local); Threads sem persistência (perda de rastreabilidade se o servidor for reiniciado).

### 4. Sistema de Coordenadas e Formato Primário
- **Decisão**: Adotar glTF 2.0 / GLB como formato binário padrão (mão direita, Y-up, unidades em metros/milímetros definidos).
- **Racional**: Compatibilidade direta e sem overhead de conversão com o Three.js no frontend e com engines modernas.

## Risks / Trade-offs

- **[Risco] Restrição de Scripts no Windows (ExecutionPolicy)** → *Mitigação*: Criar `run_windows.bat` que invoca o Python diretamente e scripts PowerShell com `-ExecutionPolicy Bypass`.
- **[Risco] Consumo excessivo de memória em geometrias densas** → *Mitigação*: Limites de subdivisão paramétrica no backend e validação da contagem de triângulos antes de enviar malhas grandes ao visualizador.
- **[Risco] Falha de suporte WebGL no navegador** → *Mitigação*: Detecção graciosa de WebGL no frontend com mensagens de orientação claras.
