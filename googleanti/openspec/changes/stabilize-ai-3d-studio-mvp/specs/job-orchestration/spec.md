# Delta Spec: Job Orchestration Robustness & Recovery

## ADDED Requirements

### Requirement: Isolamento de Computação Fora do Event Loop
The system SHALL execute rotinas computacionalmente pesadas de geração de malha, processamento geométrico e exportação em segundo plano fora do event loop principal do FastAPI (utilizando threadpool com `asyncio.to_thread`), garantindo que o servidor permaneça responsivo a requisições HTTP e solicitações de cancelamento durante a modelagem.

#### Scenario: Responsividade durante processamento pesado
- **WHEN** uma tarefa de geração procedural é disparada
- **THEN** o servidor responde imediatamente a requisições concorrentes de consulta e cancelamento sem bloqueio perceptível

### Requirement: Cancelamento Efetivo e Concorrência Controlada
The system SHALL garantir cancelamento efetivo e seguro de tarefas em execução, interrompendo operações em andamento sem corromper arquivos parciais em disco nem deixar registros de jobs em estado inconsistente, mantendo controle de concorrência local por meio de semáforo assíncrono para limitar execuções pesadas simultâneas.

#### Scenario: Cancelamento cooperativo de tarefa ativa
- **WHEN** uma requisição de cancelamento é recebida para uma tarefa em execução
- **THEN** o backend sinaliza o cancelamento, limpa quaisquer arquivos parciais não validados e transita o status para `Cancelada` com timestamp de conclusão

### Requirement: Reconciliação de Tarefas Interrompidas na Inicialização
The system SHALL inspecionar a base de dados de tarefas durante a inicialização do backend e transitar automaticamente qualquer tarefa que tenha permanecido em estado não terminal (`Pendente`, `Preparando` ou `Em Execução`) para o estado `Falhou` ou `Cancelada` (com detalhe indicando interrupção por reinicialização do serviço), registrando o timestamp de conclusão e liberando recursos pendentes.

#### Scenario: Reinicialização inesperada do servidor
- **WHEN** o servidor reinicia enquanto tarefas estavam ativas
- **THEN** as tarefas pendentes/em execução são marcadas com estado terminal de encerramento e não ficam bloqueadas indefinidamente no sistema
