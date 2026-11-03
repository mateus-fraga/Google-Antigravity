# Delta Spec: Project Management & Storage Security

## ADDED Requirements

### Requirement: Exclusão Atômica e Limpeza de Disco
The system SHALL realizar a exclusão atômica dos registros do projeto no banco de dados e remover fisicamente o diretório correspondente em `projects/{project_id}` de forma segura e síncrona com rollback em falha de transação, garantindo que nenhum arquivo órfão permaneça no disco e proibindo terminantemente a remoção de caminhos fora do diretório de armazenamento local configurado.

#### Scenario: Exclusão completa de projeto
- **WHEN** uma requisição de exclusão de projeto válida é processada
- **THEN** os metadados do projeto, as tarefas vinculadas e todo o diretório de arquivos físicos associados ao projeto são completamente removidos do disco

### Requirement: Download Seguro Contextual de Artefatos
The system SHALL fornecer download de arquivos exclusivamente através de rota contextual associada ao projeto (`/api/v1/projects/{project_id}/artifacts/{filename}`), validando estritamente que o arquivo solicitado existe dentro da pasta do projeto e rejeitando sequências de escape de caminho (`../`), caminhos absolutos, caracteres de controle ou solicitações para arquivos internos do sistema.

#### Scenario: Tentativa de download malicioso com path traversal
- **WHEN** um cliente solicita download contendo sequências `..` ou caminhos absolutos
- **THEN** o sistema rejeita a solicitação com código HTTP 400 ou 403 e impede o acesso a arquivos do sistema
