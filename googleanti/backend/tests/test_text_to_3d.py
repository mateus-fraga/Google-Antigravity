import math
from pathlib import Path
import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.config import settings
from backend.app.schemas.geometry import (
    Component,
    Transformation,
    MaterialDef,
    IntermediateObjectRepresentation,
    ObjectCategory,
)
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.procedural.text_to_3d import TextTo3DGenerator

client = TestClient(app)


def test_semantic_parsing_pt_br_units_teeth_and_colors():
    """
    Task 6.3 / 6.4 (1): Valida parsing de prompts em PT-BR e EN com unidades (m, cm, mm),
    quantidades de dentes e cores/materiais.
    """
    # 1. Mesa com unidades mistas (m e cm) e cor madeira
    ir_table, meta_table = TextTo3DGenerator.parse_prompt_to_ir(
        "mesa de madeira com tampo de 1.5m x 0.8m e 75cm de altura com espessura do tampo 50mm"
    )
    assert meta_table["parsed_intent"] == "table"
    assert meta_table["detected_components_count"] == 5  # 1 tampo + 4 pernas
    assert len(ir_table.components) == 5
    dims_t = meta_table["extracted_dimensions"]
    assert math.isclose(dims_t["width"], 1.5, rel_tol=1e-5)
    assert math.isclose(dims_t["depth"], 0.8, rel_tol=1e-5)
    assert math.isclose(dims_t["height"], 0.75, rel_tol=1e-5)
    assert math.isclose(dims_t["top_thickness"], 0.05, rel_tol=1e-5)
    assert meta_table["detected_color"] == "#8b5a2b"

    # 2. Engrenagem com dentes, raio externo em metros, espessura em mm e cor dourada/metálica
    ir_gear, meta_gear = TextTo3DGenerator.parse_prompt_to_ir(
        "engrenagem dourada metálica de 20 dentes com raio externo 1.2m e altura de 300mm"
    )
    assert meta_gear["parsed_intent"] == "gear"
    assert meta_gear["detected_components_count"] == 1
    dims_g = meta_gear["extracted_dimensions"]
    assert dims_g["num_teeth"] == 20
    assert math.isclose(dims_g["outer_radius"], 1.2, rel_tol=1e-5)
    assert math.isclose(dims_g["height"], 0.3, rel_tol=1e-5)
    assert meta_gear["detected_color"] == "#d4af37"
    assert ir_gear.components[0].material.metalness >= 0.8


def test_composite_objects_and_ir_multi_component_y_up():
    """
    Task 6.2 / 6.3 / 6.4 (2): Valida geração de objetos compostos multi-componente
    (torre, haltere, pilar e IOR manual com transformações 4x4 e vertex_colors)
    e verifica bounds em Y-up (Y_min == 0.0).
    """
    prompts_and_expectations = [
        ("torre azul com cilindro e topo cônico com 4m de altura e raio 1m", "tower", 2, 4.0),
        ("haltere vermelho com eixo de 80cm e duas esferas nas pontas com raio 20cm", "dumbbell", 3, 0.4),
        ("pilar com base quadrada, coluna cilíndrica e topo com altura de 3m", "pillar", 3, 3.0),
    ]

    for prompt, expected_intent, min_components, expected_height in prompts_and_expectations:
        mesh, ir, meta = TextTo3DGenerator.generate_from_prompt(prompt)
        assert meta["parsed_intent"] == expected_intent
        assert meta["detected_components_count"] >= min_components
        assert len(ir.components) >= min_components
        assert not mesh.is_empty
        assert np.all(np.isfinite(mesh.vertices))
        assert np.all(np.isfinite(mesh.face_normals))
        assert mesh.metadata["coordinate_system"] == "Y-up"
        assert mesh.metadata["geometry_schema_version"] == 2

        bounds = mesh.bounds
        # Base assentada no plano XZ (Y_min = 0.0)
        assert abs(bounds[0][1]) < 1e-4
        # Altura total em Y corresponde à altura esperada
        assert math.isclose(bounds[1][1] - bounds[0][1], expected_height, rel_tol=0.05)
        # Cores de vértices presentes
        assert mesh.visual.vertex_colors is not None
        assert len(mesh.visual.vertex_colors) == len(mesh.vertices)

    # Testar diretamente ProceduralGenerator.generate_from_ir com scale, rotation, translation e base_color
    custom_ir = IntermediateObjectRepresentation(
        id="ir-custom-test",
        name="custom_monument",
        category=ObjectCategory.ARCHITECTURE,
        align_to_ground=True,
        components=[
            Component(
                id="base_pedestal",
                name="Base",
                type="box",
                parameters={"width": 2.0, "height": 0.5, "depth": 2.0},
                transformation=Transformation(
                    translation=[0.0, 0.0, 0.0],
                    rotation=[0.0, 45.0, 0.0],
                    scale=[1.0, 1.0, 1.0],
                ),
                material=MaterialDef(base_color="#ef4444", roughness=0.4, metalness=0.2),
            ),
            Component(
                id="upper_sphere",
                name="Globo Superior",
                type="sphere",
                parameters={"radius": 0.5, "subdivisions": 24},
                transformation=Transformation(
                    position=[0.0, 0.5, 0.0],
                    rotation=[0.0, 0.0, 0.0],
                    scale=[1.0, 1.5, 1.0],  # Elipsoide vertical de altura 1.0 * 1.5 = 1.5m
                ),
                material=MaterialDef(base_color="#d4af37", roughness=0.2, metalness=0.9),
            ),
        ],
    )
    custom_mesh = ProceduralGenerator.generate_from_ir(custom_ir)
    assert abs(custom_mesh.bounds[0][1]) < 1e-4
    # Altura total = 0.5m (base) + 1.5m (esfera escalada 1.5x em Y) = 2.0m
    assert math.isclose(custom_mesh.bounds[1][1], 2.0, rel_tol=1e-2)
    assert custom_mesh.metadata["component_count"] == 2


@pytest.mark.parametrize(
    "invalid_prompt",
    [
        "",
        "   ",
        "a" * 2005,
        "caixa com largura -2m e altura 1m",
        "engrenagem com raio externo de -1.5m",
        "cilindro com 0m de altura",
        "engrenagem de 2 dentes com raio 1m",  # < MIN_GEAR_TEETH (4)
        "engrenagem com raio externo 0.5m e raio interno 0.9m",  # inner > outer
    ],
)
def test_rejects_invalid_prompts_with_422(invalid_prompt):
    """
    Task 6.3 / 6.4 (3): Valida rejeição determinística (ValueError e HTTP 422 na API)
    para prompts vazios, muito longos ou com medidas negativas/inválidas.
    """
    with pytest.raises(ValueError):
        TextTo3DGenerator.parse_prompt_to_ir(invalid_prompt)

    proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Invalid TextTo3D Test", "category": "mechanical"},
    )
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    try:
        job_res = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "text_to_3d",
                "params": {"prompt": invalid_prompt},
            },
        )
        assert job_res.status_code == 422
    finally:
        client.delete(f"/api/v1/projects/{proj_id}")


def test_full_async_text_to_3d_job_export_and_secure_download():
    """
    Task 6.4 (4): Valida o ciclo completo assíncrono via POST /api/v1/jobs com
    operation_type='text_to_3d', persistência de metadados semânticos,
    exportação nos 3 formatos (GLB, OBJ, STL) e download contextual seguro.
    """
    # 1. Criar projeto
    proj_res = client.post(
        "/api/v1/projects",
        json={
            "name": "Text-to-3D Tower Project",
            "description": "Projeto de teste para pipeline Text-to-3D completo",
            "category": "architecture",
        },
    )
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    try:
        # 2. Submeter job text_to_3d
        prompt_str = "torre dourada com base, cilindro e topo cônico com 3.5m de altura e raio 80cm"
        job_res = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "text_to_3d",
                "params": {"prompt": prompt_str},
            },
        )
        assert job_res.status_code == 200
        job_id = job_res.json()["id"]

        # 3. Consultar conclusão do job e metadados semânticos + geométricos Y-up
        status_res = client.get(f"/api/v1/jobs/{job_id}")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["status"] == "Concluída"
        assert len(status_data["result_files"]) == 1

        meta = status_data["metadata"]
        assert meta["coordinate_system"] == "Y-up"
        assert meta["geometry_schema_version"] == 2
        assert meta["parsed_intent"] == "tower"
        assert meta["detected_components_count"] == 3  # base + corpo + teto cônico
        assert math.isclose(meta["extracted_dimensions"]["height"], 3.5, rel_tol=1e-5)
        assert math.isclose(meta["extracted_dimensions"]["radius"], 0.8, rel_tol=1e-5)

        inspect = meta["inspection"]
        assert inspect["is_empty"] is False
        assert inspect["bounds"][0][1] >= -1e-4
        assert math.isclose(inspect["bounds"][1][1], 3.5, rel_tol=0.05)

        # 4. Exportar sob demanda em GLB, OBJ e STL
        for fmt in ("glb", "obj", "stl"):
            exp_res = client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
            assert exp_res.status_code == 200
            exp_json = exp_res.json()
            assert exp_json["format"] == fmt
            assert exp_json["filename"].endswith(f".{fmt}")

        # 5. Listar artefatos e realizar download contextual seguro
        art_res = client.get(f"/api/v1/projects/{proj_id}/artifacts")
        assert art_res.status_code == 200
        artifacts = art_res.json()["artifacts"]
        assert len(artifacts) >= 3

        for art in artifacts:
            fname = art["filename"]
            dl_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/{fname}")
            assert dl_res.status_code == 200
            assert len(dl_res.content) == art["size_bytes"]
            assert dl_res.headers.get("Content-Disposition", "").startswith("attachment;")
    finally:
        del_res = client.delete(f"/api/v1/projects/{proj_id}")
        assert del_res.status_code == 200
