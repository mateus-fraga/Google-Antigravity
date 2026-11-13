# Delta Spec: Local Image-to-3D Reconstruction

## ADDED Requirements

### Requirement: Geração Local de Malhas 3D a partir de Imagens 2D
The system SHALL converter imagens 2D de referência em malhas 3D sólidas alinhadas à convenção Y-up por meio de extrusão de silhueta ou mapa de altura/relevo local, garantindo geometria com vértices finitos e base assentada no plano XZ ($Y_{\min} = 0.0$).

#### Scenario: Geração de modelo 3D a partir de imagem válida
- **WHEN** uma imagem de referência válida é submetida para geração `image_to_3d`
- **THEN** o sistema extrai o contorno ou relevo 2D, reconstrói a malha 3D em convenção Y-up e exporta o artefato `.glb` validado no diretório contextual do projeto

#### Scenario: Rejeição de arquivo de imagem inválido ou corrompido
- **WHEN** um arquivo não suportado, vazio ou corrompido é enviado para `image_to_3d`
- **THEN** o sistema rejeita a entrada com mensagem de erro clara em português sem corromper o projeto ativo
