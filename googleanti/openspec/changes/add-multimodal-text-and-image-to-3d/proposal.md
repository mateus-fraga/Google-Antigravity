# Proposal: Motor Text-to-3D, Composição Multi-Componente e Image-to-3D Local

## Why

Com a conclusão integral da mudança `stabilize-ai-3d-studio-mvp` (Blocos 1 a 5), o AI 3D Studio dispõe de uma base sólida, segura e determinística: armazenamento transacional com quarentena, download contextual seguro de artefatos, orquestração não-bloqueante em worker threads com semáforo de concorrência, cancelamento cooperativo, validação numérica estrita, alinhamento geométrico nativo **Y-up** e visualizador Three.js livre de vazamentos de memória WebGL.

O próximo passo arquitetural previsto no plano evolutivo do projeto é habilitar as capacidades multimodais locais:
1. **Bloco 6 — Motor Text-to-3D e Composição Multi-Componente**: Traduzir descrições textuais em linguagem natural (português e inglês) contendo dimensões explícitas (`m`, `cm`, `mm`), quantidades (`dentes`, `pernas`, `andares`), cores/materiais e estruturas compostas em uma instância validada de `IntermediateObjectRepresentation` (IOR), sintetizando a malha 3D unificada em convenção Y-up através do compositor multi-componente (`ProceduralGenerator.generate_from_ir`).
2. **Bloco 7 — Motor Image-to-3D Local (Extrusão de Silhueta / Mapa de Altura e Reconstrução Volumétrica)**: Permitir a geração de modelos 3D a partir de imagens 2D de referência processadas localmente, convertendo contornos/mapas de profundidade em malhas sólidas Y-up fechadas (`watertight`).
3. **Bloco 8 — Interface Multimodal Integrada (Text-to-3D e Image-to-3D no Frontend)**: Expor as abas e controles interativos de geração por texto e imagem na UI React/Three.js, mantendo telemetria semântica, cancelamento cooperativo e exportação multiformato (`GLB`, `OBJ`, `STL`).

## What Changes

- **Compositor Geométrico Multi-Componente Y-up (`ProceduralGenerator.generate_from_ir`)**:
  - Construção determinística de árvores/listas de `Component` definidas na `IntermediateObjectRepresentation` (`box`, `cylinder`, `sphere`, `cone`, `torus`, `gear`, `table`).
  - Aplicação de transformações espaciais completas (`scale`, `rotation` Euler em graus para matriz 4x4, `position`/`translation` em metros) e cores por vértice/face (`MaterialDef`).
  - Concatenação em malha única com assentamento opcional no plano XZ ($Y_{\min} = 0.0$), validação topológica/numérica e metadados `coordinate_system: "Y-up"`, `geometry_schema_version: 2`.
- **Interpretador Semântico Text-to-3D (`backend/app/procedural/text_to_3d.py`)**:
  - Parser semântico determinístico bilíngue (PT-BR / EN) capaz de extrair intenção (`parsed_intent`), unidades métricas (`m`, `cm`, `mm`), parâmetros específicos (raios, dentes, espessuras), cores/materiais e decompor objetos compostos (ex.: mesas, engrenagens, torres, pilares, halteres/eixos, paredes, caixas, cilindros, esferas, cones, anéis/torus) em múltiplos `Component`s estruturados na `IntermediateObjectRepresentation`.
  - Validação rigorosa de entrada rejeitando prompts vazios, excessivamente longos (> 2000 caracteres) ou com dimensões negativas/inválidas com erro descritivo em português (HTTP 422).
- **Integração Assíncrona no `JobOrchestrator` e Rotas (`operation_type="text_to_3d"`)**:
  - Suporte nativo a `operation_type="text_to_3d"` em `JobCreate` e no pipeline síncrono executado via `asyncio.to_thread`, respeitando todos os checkpoints de cancelamento cooperativo (`check_cancel`) e persistindo os metadados semânticos no job e no projeto.
- **Pipeline Image-to-3D Local (Bloco 7)** e **Interface Multimodal (Bloco 8)** estruturados nas fases subsequentes desta mudança.

## Capabilities

### New Capabilities
- `text-to-3d`: Interpretador semântico de linguagem natural (PT-BR e EN) para `IntermediateObjectRepresentation` e composição geométrica multi-componente Y-up integrada ao `JobOrchestrator`.
- `image-to-3d`: Geração local de malhas 3D Y-up a partir de imagens de referência (extrusão de silhueta / mapa de relevo).

### Modified Capabilities
- `procedural-generation`: Adição do compositor `generate_from_ir` para sintetizar objetos compostos multi-componente a partir de `IntermediateObjectRepresentation` com transformações 4x4 e cores por vértice.
- `job-orchestration`: Suporte aos novos tipos de operação multimodal (`text_to_3d` e `image_to_3d`) preservando isolamento em worker threads, semáforo de concorrência e cancelamento cooperativo.

## Impact

- **Backend**: Novos módulos `backend/app/procedural/text_to_3d.py` (Bloco 6) e `backend/app/procedural/image_to_3d.py` (Bloco 7); evolução de `backend/app/procedural/engine.py`, `backend/app/schemas/geometry.py`, `backend/app/schemas/jobs.py`, `backend/app/jobs/orchestrator.py` e `backend/app/api/routes.py`.
- **Frontend**: Evolução do painel de geração em `frontend/src/features/generation/GenerationPanel.tsx`, `frontend/src/services/api.ts` e `frontend/src/App.tsx` (Bloco 8).
- **Testes**: Nova suíte `backend/tests/test_text_to_3d.py` (Bloco 6) e testes subsequentes para Image-to-3D e E2E multimodal.
