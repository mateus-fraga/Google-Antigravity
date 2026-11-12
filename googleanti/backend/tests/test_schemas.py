import pytest
from pydantic import ValidationError
from backend.app.schemas.geometry import (
    IntermediateObjectRepresentation,
    Component,
    Transformation,
    MaterialDef,
    ObjectCategory,
    ObjectPurpose,
    GenerationStrategy,
    ProceduralParams,
    validate_procedural_parameters_dict,
)
from backend.app.schemas.jobs import JobStatus, JobCreate, ProjectResponse


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
    assert rep.coordinate_system == "Y-up"
    assert rep.geometry_schema_version == 2
    assert len(rep.components) == 0


def test_component_hierarchy():
    comp_child = Component(
        id="c2",
        name="Dente",
        type="box",
        parameters={"width": 0.1, "height": 0.2, "depth": 0.1}
    )
    comp_parent = Component(
        id="c1",
        name="Corpo",
        type="cylinder",
        parameters={"radius": 0.5, "height": 1.0},
        children=[comp_child]
    )
    assert len(comp_parent.children) == 1
    assert comp_parent.children[0].name == "Dente"


def test_job_status_enum():
    assert JobStatus.RUNNING.value == "Em Execução"
    assert JobStatus.COMPLETED.value == "Concluída"
    assert JobStatus.FAILED.value == "Falhou"


@pytest.mark.parametrize(
    "bad_value",
    [
        0.0,
        -1.0,
        -0.0001,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        "invalid_str",
    ],
)
def test_procedural_params_rejects_invalid_and_non_finite_dimensions(bad_value):
    """
    Task 3.1: Verifica que `ProceduralParams` e `JobCreate` rejeitam explicitamente
    valores <= 0, NaN, Infinity, -Infinity, booleanos disfarçados de números e strings inválidas.
    """
    with pytest.raises((ValidationError, ValueError)):
        ProceduralParams(shape_type="box", dimensions={"width": bad_value, "height": 1.0, "depth": 1.0})

    with pytest.raises((ValidationError, ValueError)):
        JobCreate(
            project_id="proj-test",
            operation_type="procedural_generation",
            params={"shape_type": "box", "width": bad_value, "height": 1.0, "depth": 1.0},
        )


def test_procedural_validation_domain_and_relational_bounds():
    """
    Task 3.1: Verifica limites de domínio (contagem de dentes, subdivisões, dimensões máximas)
    e restrições relacionais (inner_radius < outer_radius, bore_radius < inner_radius, top_thickness < height).
    """
    # Engrenagem com número de dentes fora dos limites [4, 128]
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("gear", {"num_teeth": 2})
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("gear", {"num_teeth": 500})
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("gear", {"num_teeth": True})

    # Engrenagem com inner_radius >= outer_radius ou bore_radius >= inner_radius
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("gear", {"outer_radius": 1.0, "inner_radius": 1.0})
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("gear", {"outer_radius": 1.0, "inner_radius": 0.8, "bore_radius": 0.85})

    # Mesa com tampo maior ou igual à altura total
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("table", {"width": 1.2, "depth": 0.8, "height": 0.5, "top_thickness": 0.5})

    # Cilindro com sections fora de [4, 256]
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("cylinder", {"radius": 0.5, "height": 1.0, "sections": 2})
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("cylinder", {"radius": 0.5, "height": 1.0, "sections": 1024})

    # Forma desconhecida não deve cair em fallback silencioso
    with pytest.raises((ValidationError, ValueError)):
        validate_procedural_parameters_dict("unknown_shape_xyz", {"width": 1.0})


def test_ior_and_transformation_reject_non_finite_and_invalid_scales():
    """
    Task 3.1: Verifica que `Transformation`, `MaterialDef` e `Component` dentro de
    `IntermediateObjectRepresentation` rejeitam NaN/Inf, vetores de tamanho != 3 e escalas <= 0.
    """
    with pytest.raises(ValidationError):
        Transformation(position=[0.0, float("nan"), 0.0])

    with pytest.raises(ValidationError):
        Transformation(scale=[1.0, 0.0, 1.0])

    with pytest.raises(ValidationError):
        Transformation(scale=[1.0, -2.0, 1.0])

    with pytest.raises(ValidationError):
        MaterialDef(roughness=float("inf"))

    with pytest.raises(ValidationError):
        Component(id="c1", name="Invalid", type="box", parameters={"width": float("nan")})

    with pytest.raises(ValidationError):
        IntermediateObjectRepresentation(id="obj-1", name="Bad Coord", coordinate_system="invalid_axis")

