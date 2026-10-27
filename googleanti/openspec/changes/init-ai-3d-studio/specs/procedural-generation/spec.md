# Spec Delta

## Purpose

Fornece recursos de criação e manipulação geométrica paramétrica e procedural local offline sem dependência de softwares externos de modelagem.

## ADDED Requirements

### Requirement: Primitivas e Objetos Paramétricos
O sistema DEVE permitir a criação procedural determinística de primitivas geométricas e objetos paramétricos (como engrenagens, tubos, cilindros, suportes e mesas simples) a partir de parâmetros numéricos válidos.

#### Scenario: Geração bem-sucedida de objeto paramétrico
- **WHEN** uma solicitação com tipo de objeto e dimensões válidas for submetida ao gerador procedural
- **THEN** o sistema gera uma malha geométrica com vértices e faces válidos, calculando dimensões reais e contagem de polígonos

#### Scenario: Parâmetros geométricos inválidos
- **WHEN** parâmetros contendo valores negativos, nulos ou geometricamente incoerentes forem fornecidos
- **THEN** o sistema rejeita a operação com erro estruturado e não produz malhas corrompidas

### Requirement: Validação de Integridade Geométrica
O sistema DEVE inspecionar malhas produzidas proceduralmente, verificando limites geométricos, normais de superfície e detecção de faces degeneradas.

#### Scenario: Detecção de malha íntegra
- **WHEN** a malha gerada possui orientação de normais consistente e ausência de triângulos degenerados
- **THEN** o relatório de integridade marca a malha como válida para renderização e exportação

### Requirement: Operação Totalmente Offline
O mecanismo de geração procedural DEVE operar sem exigir conexão de internet, chaves de API externas ou dependência do Blender.

#### Scenario: Execução em ambiente isolado
- **WHEN** a aplicação executa sem conexão à internet e sem credenciais de terceiros configuradas
- **THEN** todas as funções de geração procedural permanecem ativas e funcionais
