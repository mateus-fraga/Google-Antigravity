# Tasks: Motor Text-to-3D, Composição Multi-Componente e Image-to-3D Local

## 6. Bloco 6 — Motor Text-to-3D e Composição Geométrica Multi-Componente

- [x] 6.1 Estruturar a mudança OpenSpec `add-multimodal-text-and-image-to-3d` com `proposal.md`, `design.md`, `tasks.md` e especificações delta (`specs/text-to-3d/spec.md` e `specs/image-to-3d/spec.md`), validando com `openspec validate --strict`
- [x] 6.2 Implementar o compositor multi-componente Y-up `ProceduralGenerator.generate_from_ir(ir, align_to_ground=True)` em `backend/app/procedural/engine.py` com suporte a transformações (`scale`, `rotation` Euler em graus para matriz 4x4, `position`/`translation` em metros), cores de material (`MaterialDef.base_color` / `color` aplicadas em `visual.vertex_colors`), concatenação e validação numérica/topológica
- [x] 6.3 Implementar o interpretador semântico `TextTo3DGenerator` em `backend/app/procedural/text_to_3d.py` com suporte a prompts em português e inglês, unidades métricas (`m`, `cm`, `mm`), quantidades (`dentes`), cores/materiais e objetos compostos (`tower`, `dumbbell`, `pillar`, `table`, `gear`, etc.), rejeitando prompts vazios ou inválidos com `ValueError` descritivo
- [x] 6.4 Integrar `operation_type="text_to_3d"` em `backend/app/schemas/jobs.py` e `backend/app/jobs/orchestrator.py` (com checkpoints de cancelamento cooperativo e persistência de metadados semânticos) e criar a suíte `backend/tests/test_text_to_3d.py`

## 7. Bloco 7 — Motor Image-to-3D Local (Silhueta / Mapa de Relevo para Malha Y-up)

- [x] 7.1 Implementar o processador `ImageTo3DGenerator` em `backend/app/procedural/image_to_3d.py` para converter imagens 2D locais (silhueta e/ou mapa de altura/luminância) em malhas 3D fechadas (`watertight`) alinhadas à convenção Y-up
- [x] 7.2 Adicionar endpoint seguro de upload/submissão de imagem de referência contextualizado por projeto e validação estrita de formato/tamanho de imagem
- [x] 7.3 Integrar `operation_type="image_to_3d"` ao `JobOrchestrator` em worker thread (`asyncio.to_thread`) com suporte a cancelamento cooperativo e exportação `.glb`
- [x] 7.4 Criar suíte de testes automatizados `backend/tests/test_image_to_3d.py` validando extrusão de silhueta, mapa de relevo, rejeição de arquivos inválidos e ciclo assíncrono completo

## 8. Bloco 8 — Interface Multimodal Integrada (Text-to-3D e Image-to-3D no Frontend) e Aceitação E2E

- [x] 8.1 Atualizar `frontend/src/features/generation/GenerationPanel.tsx`, `frontend/src/services/api.ts` e `frontend/src/App.tsx` adicionando seletores de modo (**Procedural**, **Text-to-3D**, **Image-to-3D**), campo de prompt semântico com sugestões e upload de imagem de referência
- [x] 8.2 Exibir telemetria semântica (`parsed_intent`, `detected_components_count`, dimensões extraídas) no painel de inspeção do modelo gerado
- [x] 8.3 Ampliar `backend/tests/test_e2e.py` cobrindo os três fluxos integrados (Procedural, Text-to-3D e Image-to-3D) com exportação multiformato (`GLB`, `OBJ`, `STL`)
- [x] 8.4 Executar bateria final de testes automatizados (`pytest`), linter (`npm run lint`), build de produção (`npm run build`) e validação estrita OpenSpec
