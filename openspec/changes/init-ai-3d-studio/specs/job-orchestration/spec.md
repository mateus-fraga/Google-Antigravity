# Spec Delta

## Purpose

Orquestra e monitora tarefas assíncronas locais e externas através de máquina de estados persistente para operações de longa duração.

## ADDED Requirements

### Requirement: Máquina de Estados de Tarefas
O sistema DEVE gerenciar tarefas com estados explícitos: Pendente, Preparando, Em Execução, Concluída, Falhou e Cancelada, proibindo transições inválidas.

#### Scenario: Transição de tarefa durante processamento
- **WHEN** uma tarefa de geração é iniciada em segundo plano
- **THEN** seu status transita de Pendente para Em Execução e posteriormente para Concluída ou Falhou com registro de timestamp

#### Scenario: Falha de execução de tarefa
- **WHEN** uma operação de geração encontra uma exceção não recuperável
- **THEN** a tarefa é marcada como Falhou e a mensagem de erro estruturada é registrada sem derrubar o servidor

### Requirement: Consulta de Progresso e Cancelamento
O sistema DEVE permitir a consulta periódica do estado da tarefa e suportar solicitação de cancelamento de operações em andamento.

#### Scenario: Cancelamento de tarefa ativa
- **WHEN** uma solicitação de cancelamento é enviada para uma tarefa em execução
- **THEN** o trabalhador interrompe o processamento e atualiza o estado para Cancelada, liberando recursos temporários
