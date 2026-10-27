# Spec Delta

## Purpose

Gerencia a persistência de projetos, parâmetros, metadados, versões e referências em banco de dados local SQLite e sistema de arquivos controlado.

## ADDED Requirements

### Requirement: CRUD de Projetos Locais
O sistema DEVE permitir criar, listar, obter detalhes, atualizar e excluir projetos locais, armazenando metadados estruturados em banco SQLite.

#### Scenario: Criação de novo projeto
- **WHEN** o usuário cria um novo projeto com nome e parâmetros de modelagem
- **THEN** o projeto é registrado com identificador único, data de criação e diretório isolado de trabalho

#### Scenario: Exclusão segura de projeto
- **WHEN** o usuário solicita a exclusão de um projeto
- **THEN** os metadados do projeto e seus arquivos internos são removidos sem afetar arquivos de outros projetos ou do sistema

### Requirement: Persistência de Referências e Parâmetros
O sistema DEVE armazenar e recuperar o estado completo dos parâmetros utilizados para geração do modelo, garantindo reprodutibilidade local.

#### Scenario: Reabertura de projeto existente
- **WHEN** o usuário seleciona e reabre um projeto existente
- **THEN** os parâmetros, referências associadas e modelo 3D ativo são recarregados com exatidão
