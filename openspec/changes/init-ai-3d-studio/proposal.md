# Proposal: AI 3D Studio Architecture & Initial Implementation

## Why

Atualmente, não existe uma ferramenta local, independente e universal para geração e manipulação de modelos tridimensionais que una geometria procedural offline, renderização 3D interativa em navegador e orquestração controlada de serviços e modelos de inteligência artificial generativa sem dependência obrigatória de softwares externos como o Blender ou serviços proprietários restritos.

O **AI 3D Studio** resolve este problema estabelecendo uma arquitetura modular moderna (Frontend React/Three.js + Backend FastAPI/Python/SQLite + Trimesh/NumPy), priorizando geração procedural local sem credenciais e permitindo integrações futuras com IA multimodal e modelos locais de forma segura, verificável e transparente.

## What Changes

- Criação da fundação completa do ecossistema AI 3D Studio.
- Implementação de backend em FastAPI com gestão de tarefas, projetos em SQLite e validação rigorosa de schemas via Pydantic.
- Implementação de motor de geometria procedural local (sem dependência do Blender) usando Trimesh e NumPy, gerando primitivas e objetos paramétricos com cálculo real de dimensões, normais e integridade de malha.
- Implementação de pipeline de exportação e validação de malhas em GLB/glTF 2.0 (primário), OBJ e STL.
- Implementação de frontend SPA reativo (Vite + React + TypeScript) com visualizador 3D interativo Three.js (órbita, zoom, pan, vistas predefinidas, wireframe, modo sólido, iluminação e grade configuráveis).
- Implementação de painel de controle em português brasileiro com upload de referências, especificação de parâmetros/prompt determinístico, acompanhamento de tarefas e exportação verificável.
- Implementação de camada de segurança local (CORS restrito a localhost, proteção contra path traversal em uploads/downloads, limites de tamanho e validação de arquivos).
- Scripts multiplataforma para inicialização e ambiente (Windows PowerShell/cmd, Linux, macOS).

## Capabilities

### New Capabilities
- `procedural-generation`: Criação e manipulação geométrica paramétrica e procedural local offline (primitivas, extrusão, revolução, componentes mecânicos e arquiteturais) com Trimesh/NumPy sem dependência de ferramentas externas.
- `model-viewer`: Visualizador tridimensional interativo no navegador usando Three.js, com navegação orbital, modos de exibição (sólido, aramado, materiais), enquadramento automático e inspeção de vértices/triângulos/dimensões.
- `project-management`: Gerenciamento de projetos, metadados, parâmetros e persistência com banco de dados SQLite local e armazenamento seguro de arquivos gerados em diretórios controlados.
- `job-orchestration`: Fila e máquina de estados de tarefas assíncronas (Pendente, Em Execução, Concluída, Falhou, Cancelada) para operações computacionalmente pesadas, com histórico e recuperação resiliente.
- `model-export`: Exportação, validação estrutural e verificação de arquivos tridimensionais nos formatos GLB/glTF 2.0, OBJ e STL, garantindo reimportação e integridade da malha.

### Modified Capabilities
<!-- None: Este é um projeto greenfield -->

## Impact

- **Código e Estrutura**: Criação das pastas `frontend/`, `backend/`, `projects/`, `models/`, `docs/` e `scripts/`.
- **Dependências Backend**: FastAPI, Uvicorn, Pydantic, SQLAlchemy, Trimesh, NumPy, SciPy.
- **Dependências Frontend**: React, TypeScript, Vite, Three.js, Lucide-React / Tailwind CSS ou biblioteca de UI leve.
- **Ambiente**: Requer Python 3.10+ e Node.js 18+ instalados localmente. Execução 100% local em `127.0.0.1`.
