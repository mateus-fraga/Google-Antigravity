# Roteiro de Testes de Aceitação Visual e Interativa no Navegador (Three.js)

Este documento detalha o roteiro padronizado de validação interativa e visual do visualizador Three.js do **AI 3D Studio**, conforme estipulado pela tarefa **5.4** da mudança OpenSpec `stabilize-ai-3d-studio-mvp`.

---

## 1. Pré-Requisitos e Inicialização

1. No terminal do Windows, inicie o ambiente com o script facilitador:
   ```powershell
   .\execs\start_dev.bat
   ```
2. Verifique se o backend está acessível em `http://127.0.0.1:8000/health` e o frontend em `http://127.0.0.1:5173`.
3. Abra `http://127.0.0.1:5173` no Google Chrome, Microsoft Edge ou Firefox.

---

## 2. Cenários de Teste de Aceitação Visual

### Cenário 1: Órbita, Pan e Zoom na Cena Three.js
- **Ação**:
  - Arraste o ponteiro do mouse com o botão esquerdo pressionado sobre o viewport 3D.
  - Arraste com o botão direito (ou Shift + clique esquerdo) para fazer Pan.
  - Role a roda do mouse (scroll) para aproximar e afastar a câmera.
- **Resultado Esperado**:
  - A rotação de órbita deve ser suave (60 FPS), sem travamentos ou saltos.
  - O ponto de foco orbital deve permanecer centralizado no modelo carregado.
  - Os limites de aproximação (minDistance) e afastamento (maxDistance) devem impedir que a câmera atravesse a origem ou se perca no infinito.

### Cenário 2: Inspeção de Eixos Orientados Y-up e Plano de Solo
- **Ação**:
  - Observe o canto inferior do visualizador e o centro da cena.
- **Resultado Esperado**:
  - O gizmo de eixos deve exibir nitidamente as 3 direções com convenção Y-up:
    - **Eixo X** (Vermelho, Horizontal)
    - **Eixo Y (Cima)** (Verde, apontando verticalmente para cima)
    - **Eixo Z** (Azul, Profundidade)
  - A grade (Grid) deve estar estritamente no plano $Y=0.0$ (plano de solo XZ).
  - O modelo procedural deve estar apoiado perfeitamente sobre a grade ($Y_{\text{min}} \approx 0.0$), sem afundar no solo.

### Cenário 3: Controles de Câmera Predefinidos
- **Ação**:
  - No painel do visualizador, clique em cada um dos botões de predefinição de câmera:
    - **Frente**
    - **Atrás**
    - **Esquerda**
    - **Direita**
    - **Topo**
    - **Base**
    - **Isométrica**
- **Resultado Esperado**:
  - A câmera transita suavemente para a orientação exata selecionada.
  - Na visualização **Topo**, a câmera deve olhar de cima para baixo no eixo Y.
  - Na visualização **Frente**, a câmera deve visualizar o objeto ao longo do eixo Z com o topo em +Y.

### Cenário 4: Troca de Modelo e Descarte Profundo de Memória (disposeHierarchy)
- **Ação**:
  - Abra o DevTools do navegador (`F12`), aba **Memory** ou **Performance/Rendering**.
  - No painel lateral, gere sucessivamente modelos diferentes:
    1. Caixa (`box`)
    2. Engrenagem (`gear`)
    3. Cilindro (`cylinder`)
    4. Mesa (`table`)
- **Resultado Esperado**:
  - A cada substituição de modelo, o modelo anterior é removido do grafo de cena imediatamente.
  - Não deve haver sobreposição de geometrias ou resíduos do modelo antigo.
  - O consumo de memória WebGL/Geometrias (`gl.getParameter(gl.RENDERER)`) deve se manter estável sem vazamento de buffers GPU.
  - Helpers permanentes (grade e eixos) são preservados sem recriação redundante (`userData.permanentHelper == true`).

### Cenário 5: Exportação Multiformato e Download Seguro
- **Ação**:
  - Com um modelo gerado na tela, localize a seção **Exportar Modelo**.
  - Selecione o formato desejado (`GLB`, `OBJ` ou `STL`) e clique em **Exportar**.
  - Após a geração do artefato, clique no botão de download.
- **Resultado Esperado**:
  - O navegador inicia o download com o nome correto do arquivo (ex.: `model_xxx.obj` ou `model_xxx.stl`).
  - O cabeçalho `Content-Disposition: attachment` é respeitado.
  - O arquivo baixado pode ser aberto em visualizadores 3D externos (Blender, MeshLab, 3D Builder) mantendo a orientação e proporções idênticas.

### Cenário 6: Cancelamento Cooperativo de Tarefa
- **Ação**:
  - Dispare a geração de um modelo de alta complexidade.
  - Clique imediatamente no botão **Cancelar Geração**.
- **Resultado Esperado**:
  - O status da tarefa muda para `Cancelada`.
  - A interface exibe aviso claro em português.
  - Nenhum arquivo corrompido ou parcial substitui o modelo visualizado anteriormente.
