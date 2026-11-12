# Delta Spec: Multiformat Model Export UI

## ADDED Requirements

### Requirement: Suporte a Exportação Multiformato na Interface
The system SHALL permitir ao usuário selecionar o formato de exportação desejado (GLB, OBJ ou STL) a partir da interface web e disponibilizar o arquivo correspondente validado para download através do endpoint seguro de artefatos.

#### Scenario: Exportação para formato OBJ ou STL a partir da UI
- **WHEN** o usuário seleciona o formato OBJ ou STL para o modelo ativo do projeto
- **THEN** o sistema gera o arquivo no formato escolhido, valida a integridade pós-exportação e disponibiliza o download correspondente
