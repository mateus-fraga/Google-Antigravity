import pytest
from backend.app.schemas.geometry import (
    IntermediateObjectRepresentation,
    Component,
    ObjectCategory,
    ObjectPurpose,
    GenerationStrategy,
    ProceduralParams
)
from backend.app.schemas.jobs import JobStatus, JobCreate

def test_intermediate_representation_schema():
    rep = IntermediateObjectRepresentation(
        id="obj-123",
        name="Engrenagem Simples",
        category=ObjectCategory.MECHANICAL,
        purpose=ObjectPurpose.TECHNICAL,
        strategy=GenerationStrategy.PROCEDURAL,
        description="Engrenagem de teste paramétrico"
    )
    assert rep.id == "obj-123"
    assert rep.category == ObjectCategory.MECHANICAL
    assert rep.schema_version == "2.1.0"
    assert len(rep.components) == 0

def test_component_hierarchy():
    comp_child = Component(
        id="c2",
        name="Dente",
        type="box"
    )
    comp_parent = Component(
        id="c1",
        name="Corpo",
        type="cylinder",
        children=[comp_child]
    )
    assert len(comp_parent.children) == 1
    assert comp_parent.children[0].name == "Dente"

def test_job_status_enum():
    assert JobStatus.RUNNING.value == "Em Execução"
    assert JobStatus.COMPLETED.value == "Concluída"
    assert JobStatus.FAILED.value == "Falhou"
