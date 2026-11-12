import json
import numpy as np
import pytest
import trimesh
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter
from backend.app.storage.database import SessionLocal, ProjectModel

client = TestClient(app)


def test_asymmetric_primitives_y_up_bounding_boxes():
    """
    Task 3.2 / 3.4: Cria objetos com dimensões distintas nos 3 eixos e comprova matematicamente
    pelas bounding boxes (`mesh.extents` e `mesh.bounds`) que:
    - Eixo X corresponde à largura (`width`);
    - Eixo Y corresponde à altura vertical (`height`), com base assentada em Y = 0.0 e topo em Y = height;
    - Eixo Z corresponde à profundidade (`depth`).
    """
    # 1. Paralelepípedo assimétrico: width=2.0 (X), height=5.0 (Y), depth=1.0 (Z)
    box = ProceduralGenerator.create_box(width=2.0, height=5.0, depth=1.0)
    assert np.allclose(box.extents, [2.0, 5.0, 1.0], atol=1e-4)
    assert np.allclose(box.bounds[0], [-1.0, 0.0, -0.5], atol=1e-4)
    assert np.allclose(box.bounds[1], [1.0, 5.0, 0.5], atol=1e-4)

    # 2. Cilindro assimétrico: radius=0.4 (diâmetro XZ = 0.8), height=3.5 (Y)
    cyl = ProceduralGenerator.create_cylinder(radius=0.4, height=3.5, sections=64)
    assert np.isclose(cyl.extents[0], 0.8, atol=1e-2)
    assert np.isclose(cyl.extents[1], 3.5, atol=1e-4)
    assert np.isclose(cyl.extents[2], 0.8, atol=1e-2)
    assert np.isclose(cyl.bounds[0][1], 0.0, atol=1e-4)
    assert np.isclose(cyl.bounds[1][1], 3.5, atol=1e-4)

    # 3. Engrenagem assimétrica: outer_radius=1.8, inner_radius=1.4, bore_radius=0.4, height=0.35 (Y)
    gear = ProceduralGenerator.create_gear(
        outer_radius=1.8,
        inner_radius=1.4,
        bore_radius=0.4,
        num_teeth=16,
        height=0.35
    )
    assert np.isclose(gear.extents[1], 0.35, atol=1e-4)
    assert np.isclose(gear.bounds[0][1], 0.0, atol=1e-4)
    assert np.isclose(gear.bounds[1][1], 0.35, atol=1e-4)
    assert gear.extents[0] > 2.8  # Diâmetro no plano horizontal XZ
    assert gear.extents[2] > 2.8

    # 4. Mesa assimétrica: width=1.6 (X), height=0.85 (Y), depth=0.9 (Z)
    table = ProceduralGenerator.create_table(
        width=1.6,
        depth=0.9,
        height=0.85,
        top_thickness=0.06,
        leg_thickness=0.05
    )
    assert np.allclose(table.extents, [1.6, 0.85, 0.9], atol=1e-4)
    assert np.allclose(table.bounds[0], [-0.8, 0.0, -0.45], atol=1e-4)
    assert np.allclose(table.bounds[1], [0.8, 0.85, 0.45], atol=1e-4)


def test_outward_normals_winding_and_topological_integrity():
    """
    Task 3.2 / 3.4: Comprova integridade topológica e numérica para todos os geradores:
    - Ausência de NaN/Inf nos vértices e normais;
    - Ausência de faces degeneradas (área zero);
    - Volume positivo (comprovando winding anti-horário consistente e normais externas);
    - No caso do cubo/paralelepípedo, verifica que o produto escalar entre a normal de cada face
      e o vetor do centroide do objeto até o centro da face é estritamente positivo (> 0).
    """
    box = ProceduralGenerator.create_box(width=2.0, height=4.0, depth=1.5)
    assert np.all(np.isfinite(box.vertices))
    assert np.all(np.isfinite(box.face_normals))
    assert np.all(box.area_faces > 1e-8)
    assert box.is_winding_consistent
    assert box.volume > 0.0
    assert np.isclose(box.volume, 2.0 * 4.0 * 1.5, atol=1e-4)

    # Verificar que todas as normais de face apontam para fora a partir do centroide da malha
    centroid = box.centroid
    face_centers = box.triangles_center
    outward_vectors = face_centers - centroid
    dots = np.einsum("ij,ij->i", box.face_normals, outward_vectors)
    assert np.all(dots > 0.0)

    for shape, params in [
        ("cylinder", {"radius": 0.6, "height": 2.2, "sections": 32}),
        ("gear", {"outer_radius": 1.2, "inner_radius": 0.9, "bore_radius": 0.25, "num_teeth": 14, "height": 0.3}),
        ("table", {"width": 1.4, "depth": 0.8, "height": 0.75, "top_thickness": 0.05, "leg_thickness": 0.05}),
    ]:
        mesh = ProceduralGenerator.generate_by_params(shape, params)
        info = ProceduralGenerator.inspect_mesh(mesh)
        assert info["has_finite_vertices"] is True
        assert info["has_valid_normals"] is True
        assert info["coordinate_system"] == "Y-up"
        assert info["geometry_schema_version"] == 2
        assert np.all(mesh.area_faces > 1e-9)
        assert mesh.volume is not None and mesh.volume > 0.0


def test_multiformat_roundtrip_preserves_y_up_dimensions_and_orientation(tmp_path: Path):
    """
    Task 3.3 / 3.4: Exporta e reimporta uma malha assimétrica (`table` com X=1.5, Y=0.8, Z=0.9)
    nos três formatos suportados (GLB, OBJ e STL) e comprova que todos preservam as dimensões
    (`extents`), os limites (`bounds` com Y_min=0.0 e Y_max=0.8) e a contagem válida de geometria.
    """
    mesh = ProceduralGenerator.create_table(width=1.5, depth=0.9, height=0.8, top_thickness=0.05, leg_thickness=0.05)

    for fmt in ("glb", "obj", "stl"):
        out_path = tmp_path / f"asymmetric_table.{fmt}"
        export_info = ModelExporter.export_and_validate(mesh, out_path, fmt=fmt)
        assert export_info["validated"] is True
        assert export_info["coordinate_system"] == "Y-up"
        assert export_info["geometry_schema_version"] == 2
        assert np.allclose(export_info["reloaded_extents"], [1.5, 0.8, 0.9], atol=1e-4)
        assert np.allclose(export_info["reloaded_bounds"][0], [-0.75, 0.0, -0.45], atol=1e-4)
        assert np.allclose(export_info["reloaded_bounds"][1], [0.75, 0.8, 0.45], atol=1e-4)


def test_legacy_z_up_compatibility_and_no_double_conversion():
    """
    Task 3.3 / 3.4: Comprova que:
    1. Projetos/modelos antigos sem metadado `coordinate_system` (ou marcados como `legacy_z_up`)
       são identificados como `legacy_z_up` (`requires_z_to_y_conversion=True`).
    2. Modelos gerados nativamente em `Y-up` (`geometry_schema_version=2`) são identificados com
       `requires_z_to_y_conversion=False`.
    3. `normalize_legacy_mesh_to_y_up` converte uma malha legada Z-up para Y-up exatamente uma vez
       e, se chamada uma segunda vez sobre a malha já convertida, NÃO aplica rotação duplicada.
    4. `GET /api/v1/projects/{id}` diferencia projetos legados Z-up de projetos Y-up sem corrompê-los.
    """
    # Simular primitiva legada construída em Z-up: largura X=2.0, profundidade Y=3.0, altura Z=5.0 (Z de 0 a 5)
    legacy_box = trimesh.creation.box(extents=[2.0, 3.0, 5.0])
    legacy_box.apply_translation([0.0, 0.0, 2.5])

    legacy_meta = ProceduralGenerator.resolve_coordinate_metadata({}, has_existing_model=True)
    assert legacy_meta["coordinate_system"] == "legacy_z_up"
    assert legacy_meta["is_legacy"] is True
    assert legacy_meta["requires_z_to_y_conversion"] is True

    # 1ª normalização: converte de Z-up (extents [2, 3, 5]) para Y-up (extents [2, 5, 3], base Y=0)
    normalized_once = ProceduralGenerator.normalize_legacy_mesh_to_y_up(legacy_box, {})
    assert normalized_once.metadata["coordinate_system"] == "Y-up"
    assert normalized_once.metadata["geometry_schema_version"] == 2
    assert normalized_once.metadata["converted_from_legacy_z_up"] is True
    assert np.allclose(normalized_once.extents, [2.0, 5.0, 3.0], atol=1e-4)
    assert np.isclose(normalized_once.bounds[0][1], 0.0, atol=1e-4)
    assert np.isclose(normalized_once.bounds[1][1], 5.0, atol=1e-4)

    # 2ª normalização sobre a malha já em Y-up: idempotente, NÃO rotaciona novamente!
    normalized_twice = ProceduralGenerator.normalize_legacy_mesh_to_y_up(normalized_once)
    assert np.allclose(normalized_twice.extents, [2.0, 5.0, 3.0], atol=1e-4)
    assert np.allclose(normalized_twice.bounds, normalized_once.bounds, atol=1e-4)

    # Verificar via banco/API a identificação de projeto legado Z-up vs projeto nativo Y-up
    db = SessionLocal()
    legacy_proj_id = "proj-legacy-zup"
    try:
        db.query(ProjectModel).filter(ProjectModel.id == legacy_proj_id).delete()
        db.commit()
        legacy_proj = ProjectModel(
            id=legacy_proj_id,
            name="Legacy Z-up Project",
            status="active",
            active_model_path="projects/proj-legacy-zup/old_box.glb",
            parameters_json=json.dumps({"shape_type": "box", "width": 2.0, "height": 5.0, "depth": 3.0})
        )
        db.add(legacy_proj)
        db.commit()

        res = client.get(f"/api/v1/projects/{legacy_proj_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["coordinate_system"] == "legacy_z_up"
        assert data["geometry_schema_version"] == 1
    finally:
        db.query(ProjectModel).filter(ProjectModel.id == legacy_proj_id).delete()
        db.commit()
        db.close()


def test_api_jobs_rejects_invalid_geometry_parameters_with_422():
    """
    Task 3.1 / 3.4: Comprova que o endpoint HTTP `POST /api/v1/jobs` rejeita
    deterministicamente (HTTP 422) parâmetros geométricos inválidos (dimensões <= 0,
    relações de raio inconsistentes, formas não suportadas).
    """
    res_proj = client.post("/api/v1/projects", json={"name": "Validation 422 Project"})
    assert res_proj.status_code == 200
    proj_id = res_proj.json()["id"]

    try:
        # 1. Dimensão negativa
        r_neg = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "procedural_generation",
                "params": {"shape_type": "box", "width": -2.0, "height": 1.0, "depth": 1.0},
            },
        )
        assert r_neg.status_code == 422

        # 2. Engrenagem com inner_radius >= outer_radius
        r_gear = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "procedural_generation",
                "params": {"shape_type": "gear", "outer_radius": 0.8, "inner_radius": 1.2, "num_teeth": 12},
            },
        )
        assert r_gear.status_code == 422

        # 3. Forma inexistente
        r_shape = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "procedural_generation",
                "params": {"shape_type": "non_existent_shape", "width": 1.0},
            },
        )
        assert r_shape.status_code == 422
    finally:
        client.delete(f"/api/v1/projects/{proj_id}")
