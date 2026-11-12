import numpy as np
import pytest
from pathlib import Path
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter


def test_export_and_validate_glb(tmp_path: Path):
    """
    Task 3.3 / 3.4: Exporta e reimporta modelo assimétrico em GLB, comprovando
    preservação exata das dimensões [width=2.0, height=5.0, depth=1.0] e bounds Y-up.
    """
    mesh = ProceduralGenerator.create_box(width=2.0, height=5.0, depth=1.0)
    out_file = tmp_path / "test_box.glb"

    result = ModelExporter.export_and_validate(mesh, out_file, fmt="glb")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert result["coordinate_system"] == "Y-up"
    assert np.allclose(result["reloaded_extents"], [2.0, 5.0, 1.0], atol=1e-4)
    assert np.allclose(result["reloaded_bounds"][0], [-1.0, 0.0, -0.5], atol=1e-4)
    assert np.allclose(result["reloaded_bounds"][1], [1.0, 5.0, 0.5], atol=1e-4)
    assert out_file.exists()


def test_export_and_validate_obj(tmp_path: Path):
    """
    Task 3.3 / 3.4: Exporta e reimporta cilindro assimétrico (radius=0.6, height=3.2) em OBJ,
    comprovando preservação das dimensões Y-up.
    """
    mesh = ProceduralGenerator.create_cylinder(radius=0.6, height=3.2, sections=32)
    out_file = tmp_path / "test_cyl.obj"

    result = ModelExporter.export_and_validate(mesh, out_file, fmt="obj")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert np.isclose(result["reloaded_extents"][1], 3.2, atol=1e-4)
    assert np.isclose(result["reloaded_bounds"][0][1], 0.0, atol=1e-4)
    assert np.isclose(result["reloaded_bounds"][1][1], 3.2, atol=1e-4)
    assert out_file.exists()


def test_export_and_validate_stl(tmp_path: Path):
    """
    Task 3.3 / 3.4: Exporta e reimporta mesa assimétrica (width=1.4, depth=0.7, height=0.85) em STL,
    comprovando preservação de extents [1.4, 0.85, 0.7] e base em Y=0.0.
    """
    mesh = ProceduralGenerator.create_table(width=1.4, depth=0.7, height=0.85)
    out_file = tmp_path / "test_table.stl"

    result = ModelExporter.export_and_validate(mesh, out_file, fmt="stl")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert np.allclose(result["reloaded_extents"], [1.4, 0.85, 0.7], atol=1e-4)
    assert np.isclose(result["reloaded_bounds"][0][1], 0.0, atol=1e-4)
    assert np.isclose(result["reloaded_bounds"][1][1], 0.85, atol=1e-4)
    assert out_file.exists()


def test_contextual_multiformat_export_and_secure_download_api():
    """
    Task 4.3 / 4.4 (UI-001 / SEC-001):
    Verifica o fluxo completo de descoberta e exportação multiformato (GLB, OBJ e STL)
    para o modelo ativo do projeto e download através da rota contextual segura
    `/api/v1/projects/{project_id}/artifacts/{filename}`:
    1. Cria projeto e conclui geração procedural (gera .glb inicial).
    2. Lista artefatos (`GET /api/v1/projects/{id}/artifacts`) e confirma `glb` disponível.
    3. Solicita exportação sob demanda para `obj` e `stl` (`POST /api/v1/projects/{id}/export/{fmt}`),
       validando que os arquivos são gerados, validados pelo `ModelExporter` e registrados no projeto.
    4. Baixa os três formatos via `/api/v1/projects/{id}/artifacts/{filename}` com status 200 OK e bytes > 0.
    5. Rejeita formato inválido (ex: `fbx`) com HTTP 400.
    """
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)

    proj_res = client.post("/api/v1/projects", json={"name": "Multiformat UI Export Project"})
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    try:
        job_res = client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "procedural_generation",
                "params": {"shape_type": "box", "width": 1.2, "height": 2.4, "depth": 0.8},
            },
        )
        assert job_res.status_code == 200
        job_id = job_res.json()["id"]

        status_res = client.get(f"/api/v1/jobs/{job_id}")
        assert status_res.status_code == 200
        assert status_res.json()["status"] == "Concluída"

        # 1. Inspecionar artefatos disponíveis inicialmente (GLB)
        list_res = client.get(f"/api/v1/projects/{proj_id}/artifacts")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert "glb" in list_data["active_formats"]

        # 2. Exportar e baixar nos 3 formatos (GLB, OBJ, STL) via endpoint contextual seguro
        for fmt in ("glb", "obj", "stl"):
            exp_res = client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
            assert exp_res.status_code == 200
            exp_data = exp_res.json()
            assert exp_data["format"] == fmt
            assert exp_data["validated"] is True
            assert exp_data["filename"].endswith(f".{fmt}")

            dl_res = client.get(exp_data["download_url"])
            assert dl_res.status_code == 200
            assert len(dl_res.content) > 0

        # 3. Confirmar que todos os 3 formatos agora constam em active_formats
        list_after = client.get(f"/api/v1/projects/{proj_id}/artifacts").json()
        assert set(list_after["active_formats"].keys()) == {"glb", "obj", "stl"}

        # 4. Formato não suportado deve retornar HTTP 400
        bad_fmt = client.post(f"/api/v1/projects/{proj_id}/export/fbx")
        assert bad_fmt.status_code == 400
    finally:
        client.delete(f"/api/v1/projects/{proj_id}")


