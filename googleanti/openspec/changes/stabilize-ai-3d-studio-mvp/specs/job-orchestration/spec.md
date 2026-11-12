# Delta Spec: Job Orchestration Robustness & Recovery

## ADDED Requirements

### Requirement: Isolamento de Computação Fora do Event Loop
The system SHALL executar rotinas computacionalmente pesadas de geração de malha, processamento geométrico e exportação em worker threads dedicadas (`asyncio.to_thread`) limitadas por semáforo assíncrono (`asyncio.Semaphore`), garantindo que o servidor permaneça responsivo durante a modelagem.

#### Scenario: Responsividade durante processamento pesado
- **WHEN** uma tarefa de geração procedural é disparada
- **THEN** o servidor responde imediatamente a requisições concorrentes de consulta e cancelamento sem bloqueio perceptível

### Requirement: Cancelamento Efetivo Cooperativo e Limpeza de Temporários
The system SHALL implementar cancelamento cooperativo via `threading.Event` integrado aos pontos de controle do pipeline, descartar arquivos temporários parciais em disco e transitar o status para `Cancelada` de forma idempotente, diferenciando tarefas canceladas daquelas já concluídas.

#### Scenario: Cancelamento cooperativo de tarefa ativa
- **WHEN** uma requisição de cancelamento é recebida para uma tarefa em execução
- **THEN** o backend sinaliza o cancelamento cooperativo, limpa quaisquer arquivos parciais não validados e transita o status para `Cancelada` com timestamp de conclusão

#### Scenario: Cancelamento solicitado para tarefa já finalizada
- **WHEN** uma requisição de cancelamento é recebida para uma tarefa que já completou seu processamento
- **THEN** o sistema mantém o estado final `Concluída` sem corromper o histórico ou os artefatos gerados

### Requirement: Reconciliação de Tarefas Interrompidas na Inicialização
The system SHALL inspecionar a base de dados de tarefas durante o lifespan handler de inicialização e transitar automaticamente qualquer tarefa em estado não terminal (`Pendente`, `Preparando` ou `Em Execução`) para o estado `Cancelada` com justificativa de interrupção por reinício do servidor.

#### Scenario: Reinicialização inesperada do servidor
- **WHEN** o servidor reinicia enquanto tarefas estavam ativas
- **THEN** as tarefas pendentes/em execução são marcadas com estado terminal de encerramento e não ficam bloqueadas indefinidamente no sistema
