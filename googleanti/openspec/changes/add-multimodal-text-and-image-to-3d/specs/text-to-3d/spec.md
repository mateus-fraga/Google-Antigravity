# Delta Spec: Text-to-3D Semantic Parsing & Multi-Component Composition

## ADDED Requirements

### Requirement: Composição Geométrica Multi-Componente em Convenção Y-up
The system SHALL sintetizar malhas 3D unificadas a partir de `IntermediateObjectRepresentation`, aplicando transformações (`scale`, `rotation` Euler em graus e `position` em metros) e cores (`MaterialDef`), assentando a malha no plano XZ ($Y_{\min} = 0.0$ quando `align_to_ground=True`) com metadados `coordinate_system: "Y-up"` e `geometry_schema_version: 2`.

#### Scenario: Composição de objeto multi-componente com transformações e materiais
- **WHEN** `ProceduralGenerator.generate_from_ir` recebe uma `IntermediateObjectRepresentation` com múltiplos componentes (ex.: base cilíndrica e topo cônico) e `align_to_ground=True`
- **THEN** o gerador retorna uma malha `trimesh.Trimesh` unificada com vértices e normais finitos, $Y_{\min} = 0.0$, $Y_{\max}$ correspondente à altura total composta e metadados `coordinate_system == "Y-up"`

### Requirement: Interpretação Semântica Bilíngue Text-to-3D
The system SHALL interpretar prompts textuais em português e inglês via `TextTo3DGenerator`, extraindo intenção (`parsed_intent`), dimensões com conversão de unidades (`m`, `cm`, `mm`), contagens inteiras e cores/materiais para produzir uma `IntermediateObjectRepresentation` validada.

#### Scenario: Prompt em português com unidades variadas e objeto composto
- **WHEN** o usuário submete um prompt como `"mesa com tampo de 1.5m x 0.8m e 75cm de altura"` ou `"torre com cilindro e topo cônico"`
- **THEN** o `TextTo3DGenerator` converte todas as unidades para metros, instancia os componentes correspondentes na `IntermediateObjectRepresentation` e expõe os metadados semânticos (`parsed_intent`, `detected_components_count`, `extracted_dimensions`, `prompt`)

#### Scenario: Rejeição de prompts vazios ou com dimensões inválidas
- **WHEN** um job `text_to_3d` é submetido com prompt vazio, maior que 2000 caracteres ou contendo medidas negativas/inválidas
- **THEN** o sistema rejeita a requisição com erro de validação descritivo em português (`HTTP 422`) sem iniciar processamento assíncrono nem alterar o estado do projeto

### Requirement: Execução Assíncrona Não-Bloqueante de Jobs Text-to-3D
The system SHALL executar jobs `operation_type="text_to_3d"` no `JobOrchestrator` em worker threads (`asyncio.to_thread`) limitadas por semáforo, respeitando cancelamento cooperativo, exportando o artefato `.glb` validado e persistindo os metadados semânticos no job e no projeto.

#### Scenario: Ciclo completo de job Text-to-3D e exportação multiformato
- **WHEN** um cliente envia `POST /api/v1/jobs` com `operation_type="text_to_3d"` e um prompt válido
- **THEN** o job conclui com status `Concluída`, gera o artefato `.glb` em `Y-up`, permite exportação sob demanda em `GLB`, `OBJ` e `STL` e disponibiliza download contextual seguro
