# Delta Spec: Procedural Coordinate Alignment & Parameter Validation

## ADDED Requirements

### Requirement: Alinhamento Estrito com Convenção Y-up
The system SHALL gerar primitivas e geometrias alinhadas à convenção glTF 2.0 / WebGL com eixo **Y** orientado para cima, assentando a base do objeto no plano XZ em $Y = 0$, com normais voltadas para o exterior e orientação anti-horária de faces, preservando leitura de modelos legados via metadados.

#### Scenario: Geração de primitiva com base no plano XZ
- **WHEN** uma caixa, cilindro, engrenagem ou mesa é gerada com altura $H$
- **THEN** a coordenada mínima em Y da malha resultante é $0.0$ e a coordenada máxima em Y é igual a $H$, com normais orientadas corretamente para o exterior

#### Scenario: Leitura de modelo de projeto legado
- **WHEN** um projeto anterior sem flag Y-up é carregado
- **THEN** o sistema lê os metadados de orientação legada e preserva a geometria original sem inversões espaciais acidentais

### Requirement: Validação Rigorosa de Parâmetros e Bounds Finitos
The system SHALL validar rigorosamente todos os parâmetros de entrada procedurais antes da geração geométrica, rejeitando valores negativos, nulos, infinitos ou NaN, impondo limites mínimos e máximos documentados e assegurando que malhas degeneradas não sejam geradas.

#### Scenario: Entrada de parâmetros geométricos fora dos limites
- **WHEN** uma requisição de geração procedural contém dimensões <= 0 ou valores não finitos
- **THEN** o sistema rejeita a operação com erro de validação descritivo sem disparar falhas de motor geométrico
