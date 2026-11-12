# Delta Spec: Project Management & Storage Security

## ADDED Requirements

### Requirement: Exclusão Recuperável de Projetos e Isolamento de Quarentena
The system SHALL executar a exclusão de projetos através de protocolo em duas fases com quarentena (`storage/.quarantine/`), marcando o projeto como `DELETING` no SQLite para bloquear novas tarefas, movendo o diretório físico para quarentena antes do commit e descartando a quarentena após o sucesso da transação, com suporte a reconciliação pós-reboot e proibição de remoção fora de `STORAGE_DIR`.

#### Scenario: Exclusão de projeto com sucesso em duas fases
- **WHEN** uma requisição `DELETE /api/v1/projects/{project_id}` é processada
- **THEN** o projeto é marcado como em exclusão, seus arquivos são movidos para quarentena, o registro é removido do SQLite e a quarentena é descartada de forma limpa

#### Scenario: Falha transacional antes do commit no banco
- **WHEN** ocorre uma falha no banco de dados durante a transação de exclusão
- **THEN** a operação de banco sofre rollback, a pasta em quarentena é restaurada para a pasta original do projeto e o projeto volta ao estado ativo sem perda de dados

#### Scenario: Interrupção do servidor com arquivos em quarentena
- **WHEN** o servidor reinicia e detecta pastas órfãs no diretório de quarentena
- **THEN** o sistema reconcilia os diretórios pendentes de forma segura garantindo consistência com a base de dados

### Requirement: Download Seguro Contextual de Artefatos
The system SHALL fornecer download de arquivos exclusivamente via rota `/api/v1/projects/{project_id}/artifacts/{filename}`, validando que o caminho resolve dentro da pasta do projeto via `os.path.commonpath`, rejeitando symlinks, validando nome alfanumérico seguro (`^[a-zA-Z0-9_\-\.]+$`) e confirmando que o artefato consta na lista de arquivos registrados do projeto.

#### Scenario: Tentativa de download malicioso com path traversal
- **WHEN** um cliente solicita download contendo sequências `..` ou caminhos absolutos
- **THEN** o sistema rejeita a solicitação com código HTTP 400 ou 403 e impede o acesso a arquivos do sistema

#### Scenario: Tentativa de download via symlink ou arquivo não registrado
- **WHEN** um cliente solicita download de um symlink ou arquivo não pertencente aos artefatos registrados do projeto
- **THEN** o sistema rejeita a solicitação com código HTTP 403 ou 404
