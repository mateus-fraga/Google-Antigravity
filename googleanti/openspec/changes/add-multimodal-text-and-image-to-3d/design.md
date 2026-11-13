# Design: Motor Text-to-3D, Composição Multi-Componente e Image-to-3D Local

## Context

O AI 3D Studio opera de forma 100% local e autossuficiente sobre FastAPI, Trimesh, NumPy, Shapely e Three.js. Após a estabilização completa dos Blocos 1 a 5 (`stabilize-ai-3d-studio-mvp`), o sistema já possui a estrutura de dados `IntermediateObjectRepresentation` (IOR) em `backend/app/schemas/geometry.py`, contendo `Component`, `Transformation` (`position`, `rotation`, `scale`) e `MaterialDef` (`color`, `roughness`, `metalness`).

Para habilitar a modelagem multimodal local sem depender de GPUs dedicadas ou APIs externas pagas, a arquitetura adota um pipeline em duas camadas:
1. **Camada Semântica / Extração Multimodal**:
   - **Text-to-3D (`TextTo3DGenerator`)**: Analisa prompts em português e inglês identificando a classe do objeto (simples ou composto), extraindo medidas explícitas com conversão automática de unidades (`mm` $\to \times 0.001$, `cm` $\to \times 0.01$, `m` $\to \times 1.0`), atributos inteiros (ex.: número de dentes de engrenagem), cores nomeadas/hexadecimais e propriedades de material, produzindo uma `IntermediateObjectRepresentation` validada.
   - **Image-to-3D (`ImageTo3DGenerator` — Bloco 7)**: Processa imagens 2D locais extraindo silhueta ou mapa de luminância/altura para gerar malhas 3D fechadas em Y-up.
2. **Camada de Síntese e Composição Geométrica (`ProceduralGenerator.generate_from_ir`)**:
   - Recebe qualquer `IntermediateObjectRepresentation` válida, instancia cada `Component` (e eventuais subcomponentes recursivos em `children`) utilizando as primitivas nativas Y-up (`box`, `cylinder`, `sphere`, `cone`, `torus`, `gear`, `table`), aplica escala, rotação Euler (graus $\to$ radianos, matriz 4x4) e translação em metros, atribui `vertex_colors` RGBA com base na cor do material e concatena todas as partes em um `trimesh.Trimesh` unificado com base assentada em $Y = 0.0$.

## Goals / Non-Goals

**Goals:**
- Implementar `ProceduralGenerator.generate_from_ir(ir, align_to_ground=True)` com suporte completo a múltiplos componentes, hierarquia `children`, transformações 4x4 determinísticas e cores de material (`base_color` / `color`).
- Implementar `TextTo3DGenerator` em `backend/app/procedural/text_to_3d.py` com suporte bilíngue (PT-BR e EN), conversão de unidades (`m`, `cm`, `mm`), detecção de cores e síntese de objetos simples e compostos (ex.: torre com corpo cilíndrico e teto cônico, haltere com eixo e pesos nas extremidades, pilar com base, coluna e capitel, mesa parametrizada, engrenagem com dentes e raio especificados).
- Integrar `operation_type="text_to_3d"` ao `JobOrchestrator` preservando `asyncio.to_thread`, semáforo de concorrência (`MAX_CONCURRENT_JOBS = 2`), checkpoints de cancelamento cooperativo e segurança contextual de artefatos.

**Non-Goals:**
- Não introduzir dependências de LLMs em nuvem ou serviços externos que quebrem o requisito `local_only: True`.
- Não alterar as garantias de segurança de caminhos e quarentena transacional estabelecidas no Bloco 1.

## Decisions

### 1. Transformação Espacial de Componentes em `generate_from_ir`
Cada primitiva gerada por `ProceduralGenerator` nasce alinhada em Y-up com base em $Y = 0.0$ e centrada em $X = 0, Z = 0$. Ao compor um `Component`:
1. **Escala (`scale = [sx, sy, sz]`)**: Aplicada via matriz diagonal 4x4 antes da rotação/translação.
2. **Rotação (`rotation = [rx, ry, rz]` em graus)**: Convertida para radianos e aplicada via `trimesh.transformations.euler_matrix(rx, ry, rz, axes="sxyz")` em torno do centro geométrico ou origem local do componente.
3. **Translação (`position = [tx, ty, tz]` em metros)**: Aplicada via `apply_translation([tx, ty, tz])`.
4. **Cor (`MaterialDef.color` / `base_color`)**: Convertida de string hexadecimal (`#RRGGBB`) para `[R, G, B, 255]` (`uint8`) e atribuída a `mesh.visual.vertex_colors` e `mesh.visual.face_colors`.
5. **Assentamento Global (`align_to_ground=True`)**: Após concatenar todos os componentes, se `align_to_ground` estiver ativo, a malha unificada é transladada verticalmente caso `bounds[0][1] != 0.0` para garantir $Y_{\min} = 0.0$ no plano XZ.

### 2. Gramática e Heurísticas Determinísticas do `TextTo3DGenerator`
O parser semântico opera em pipeline determinístico:
1. **Validação Léxica Inicial**: Rejeita prompts vazios, compostos apenas por espaços, maiores que 2000 caracteres ou contendo números explícitos negativos para dimensões geométricas (ex.: `-5m`, `raio -2`, `altura de -10cm`).
2. **Extração de Medidas e Unidades**: Expressões regulares capturam padrões dimensionais (`1.5m x 0.8m`, `largura 2m`, `altura de 75cm`, `raio externo 1.2m`, `diâmetro 40cm`, `espessura 50mm`, `20 dentes`) convertendo sempre para metros (`m`).
3. **Extração de Cores e Materiais**: Mapeamento de termos em PT-BR e EN (`vermelho`/`red`, `azul`/`blue`, `verde`/`green`, `amarelo`/`yellow`, `dourado`/`gold`, `prata`/`silver`, `metálico`/`metallic`, `madeira`/`wood`, `preto`/`black`, `branco`/`white`, `laranja`/`orange`, `roxo`/`purple`, além de códigos hexadecimais `#RRGGBB`).
4. **Classificação de Intenção (`parsed_intent`) e Decomposição Multi-Componente**:
   - **Objetos Compostos Arquitetônicos/Mecânicos**:
     - `tower` (*torre*): Cilindro de corpo principal + cone de cobertura posicionado no topo ($Y = H_{\text{corpo}}$) + base opcional.
     - `dumbbell` (*haltere / eixo com esferas ou cilindros nas pontas*): Eixo cilíndrico central rotacionado horizontalmente + 2 esferas ou discos cilíndricos simétricos nas extremidades.
     - `pillar` (*pilar / coluna clássica*): Base quadrada (`box`) + fuste cilíndrico (`cylinder`) + capitel/topo (`box`).
     - `table` (*mesa*): Tampo superior (`box`) + 4 pernas (`box` ou `cylinder`) posicionadas nos cantos.
     - `snowman` / `totem` (*boneco / totem empilhado*): Múltiplas esferas ou blocos empilhados verticalmente em Y.
   - **Primitivas Parametrizadas**: `gear` (*engrenagem*), `box`/`wall` (*caixa, cubo, bloco, parede*), `cylinder` (*cilindro, tubo, cano*), `sphere` (*esfera, bola*), `cone` (*cone, pirâmide circular*), `torus` (*anel, argola, rosquinha, torus*).
