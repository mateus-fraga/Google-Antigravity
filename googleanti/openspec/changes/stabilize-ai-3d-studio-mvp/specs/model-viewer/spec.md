# Delta Spec: Model Viewer Resource Lifecycle

## ADDED Requirements

### Requirement: Descarte Recursivo de Recursos WebGL
The system SHALL implementar descarte explícito e recursivo de geometrias (`BufferGeometry.dispose()`), materiais (`Material.dispose()`) e texturas associadas no visualizador Three.js sempre que um novo modelo for carregado ou quando o componente for desmontado, impedindo vazamentos de memória na GPU e no navegador.

#### Scenario: Carregamento consecutivo de múltiplos modelos
- **WHEN** o usuário gera ou seleciona sucessivos modelos 3D na interface
- **THEN** as geometrias e materiais do modelo anterior são descartados da memória de vídeo antes da alocação da nova geometria

### Requirement: Orientação Clara de Eixos e Grade
The system SHALL exibir a grade de referência horizontal posicionada no plano de solo XZ ($Y = 0$) e manter um indicador de eixos visíveis em que o eixo Y represente a direção vertical (cima), correspondendo à orientação real dos modelos exportados.

#### Scenario: Inspeção visual de orientação
- **WHEN** o modelo é exibido no visualizador Three.js
- **THEN** o modelo repousa diretamente sobre a grade do solo e a câmera mantém orientação consistente com a convenção Y-up
