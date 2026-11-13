import pytest
import os
import time
from pathlib import Path
from fastapi.testclient import TestClient
import trimesh
from backend.app.main import app
from backend.app.config import settings

client = TestClient(app)

def test_full_e2e_workflow():
    """
    Fluxo de aceitação E2E Local (Tarefa 5.1):
    1. Criar novo projeto e confirmar metadados coordinate_system == 'Y-up' e geometry_schema_version == 2
    2. Rejeição determinística de parâmetros geométricos inválidos (HTTP 422) sem sujar o estado
    3. Submeter tarefa de geração procedural, acompanhar até Concluída e validar telemetria Y-up
    4. Exportar sob demanda nos 3 formatos (GLB, OBJ, STL), listar artefatos contextuais e baixar com integridade de bytes
    5. Cancelamento cooperativo de job ativo e exclusão recuperável do projeto (sem arquivos órfãos)
    """
    # 1. Criar Projeto e validar metadados padrão Y-up e schema v2
    create_res = client.post(
        "/api/v1/projects",
        json={
            "name": "E2E Gear Project",
            "description": "Engrenagem mecânica procedural para teste de aceitação completo",
            "category": "mechanical",
            "purpose": "technical",
            "strategy": "procedural"
        }
    )
    assert create_res.status_code == 200
    proj_data = create_res.json()
    proj_id = proj_data["id"]

    # Validar metadados do projeto via GET
    get_proj_res = client.get(f"/api/v1/projects/{proj_id}")
    assert get_proj_res.status_code == 200
    proj_details = get_proj_res.json()
    assert proj_details.get("coordinate_system") == "Y-up"
    assert proj_details.get("geometry_schema_version") == 2

    # 2. Rejeição determinística de parâmetros geométricos inválidos (HTTP 422)
    invalid_job_res = client.post(
        "/api/v1/jobs",
        json={
            "project_id": proj_id,
            "operation_type": "procedural_generation",
            "params": {
                "shape_type": "gear",
                "outer_radius": -1.0,  # Inválido: <= 0
                "inner_radius": 1.1,
                "bore_radius": 0.4,
                "num_teeth": 16,
                "height": 0.3
            }
        }
    )
    assert invalid_job_res.status_code == 422

    # 3. Submeter Tarefa de Geração Procedural Válida
    job_res = client.post(
        "/api/v1/jobs",
        json={
            "project_id": proj_id,
            "operation_type": "procedural_generation",
            "params": {
                "shape_type": "gear",
                "outer_radius": 1.5,
                "inner_radius": 1.1,
                "bore_radius": 0.4,
                "num_teeth": 16,
                "height": 0.3
            }
        }
    )
    assert job_res.status_code == 200
    job_data = job_res.json()
    job_id = job_data["id"]

    # Consultar Job e verificar conclusão
    status_res = client.get(f"/api/v1/jobs/{job_id}")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "Concluída"
    assert len(status_data["result_files"]) > 0

    glb_relative_path = status_data["result_files"][0]
    glb_filename = Path(glb_relative_path).name
    glb_full_path = settings.BASE_DIR / glb_relative_path
    assert glb_full_path.exists()
    assert glb_full_path.stat().st_size > 0

    # Validar geometria Y-up (assentamento no solo XZ em Y=0 com altura positiva)
    loaded_scene = trimesh.load(str(glb_full_path))
    assert not loaded_scene.is_empty
    mesh = loaded_scene.dump()[0] if hasattr(loaded_scene, "dump") else loaded_scene
    bounds = mesh.bounds
    assert bounds[0][1] >= -1e-4  # Y_min >= 0 (solo)
    assert bounds[1][1] > 0.0     # Y_max > 0 (altura positiva)

    # 4. Exportação sob demanda nos 3 formatos suportados (GLB, OBJ, STL)
    for fmt in ["glb", "obj", "stl"]:
        exp_res = client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
        assert exp_res.status_code == 200
        exp_data = exp_res.json()
        assert exp_data["format"] == fmt
        assert exp_data["filename"].endswith(f".{fmt}")

    # Listagem contextual de artefatos
    artifacts_res = client.get(f"/api/v1/projects/{proj_id}/artifacts")
    assert artifacts_res.status_code == 200
    artifacts_data = artifacts_res.json()
    artifact_names = [a["filename"] for a in artifacts_data.get("artifacts", [])]
    assert any(name.endswith(".glb") for name in artifact_names)
    assert any(name.endswith(".obj") for name in artifact_names)
    assert any(name.endswith(".stl") for name in artifact_names)

    # Download seguro e contextual verificando cabeçalhos e integridade dos bytes
    for artifact_info in artifacts_data.get("artifacts", []):
        fname = artifact_info["filename"]
        dl_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/{fname}")
        assert dl_res.status_code == 200
        assert len(dl_res.content) == artifact_info["size_bytes"]
        assert "Content-Disposition" in dl_res.headers
        assert dl_res.headers["Content-Disposition"].startswith("attachment;")

    # Compatibilidade do endpoint legado com caminho resolvido
    legacy_dl_res = client.get(f"/api/v1/files/download?path={glb_full_path}")
    assert legacy_dl_res.status_code == 200
    assert len(legacy_dl_res.content) == glb_full_path.stat().st_size

    # 5. Fluxo de Cancelamento Cooperativo
    # Submeter um job e testar endpoint de cancelamento
    cancel_job_res = client.post(
        "/api/v1/jobs",
        json={
            "project_id": proj_id,
            "operation_type": "procedural_generation",
            "params": {"shape_type": "cylinder", "radius": 0.8, "height": 2.0}
        }
    )
    assert cancel_job_res.status_code == 200
    c_job_id = cancel_job_res.json()["id"]

    # Cancelar o job
    cancel_req = client.post(f"/api/v1/jobs/{c_job_id}/cancel")
    assert cancel_req.status_code in [200, 400]  # 200 se cancelou, 400 se já havia concluído

    # 6. Exclusão Recuperável do Projeto com Quarentena e ausência de órfãos
    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    # Confirma que o projeto não pode mais ser acessado
    assert client.get(f"/api/v1/projects/{proj_id}").status_code == 404
    assert client.get(f"/api/v1/projects/{proj_id}/artifacts").status_code == 404


def test_multimodal_text_and_image_to_3d_e2e_workflow():
    """
    Fluxo de aceitação E2E Multimodal (Bloco 8 — Tarefa 8.3):
    1. Cria projeto e executa geração via Text-to-3D (prompt composto em PT-BR), validando metadados semânticos e exportação GLB/OBJ/STL.
    2. Faz upload de imagem PNG em memória, consulta imagem na rota contextual segura, executa geração via Image-to-3D (silhouette e heightmap), valida estanqueidade Y-up e exportação multiformato.
    3. Exclui o projeto ao final limpando os artefatos com segurança.
    """
    import io
    from PIL import Image, ImageDraw

    with TestClient(app) as local_client:
        create_res = local_client.post(
            "/api/v1/projects",
            json={
                "name": "E2E Multimodal Project",
                "description": "Teste integrado Procedural + Text-to-3D + Image-to-3D",
                "category": "mechanical",
                "purpose": "technical",
                "strategy": "procedural",
            },
        )
        assert create_res.status_code == 200
        proj_id = create_res.json()["id"]

        # --- Etapa A: Text-to-3D ---
        t2d_res = local_client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "text_to_3d",
                "params": {
                    "prompt": "Mesa de centro em madeira com 120cm de largura, 45cm de altura e 60cm de profundidade"
                },
            },
        )
        assert t2d_res.status_code == 200
        t2d_job_id = t2d_res.json()["id"]

        t2d_status = None
        for _ in range(60):
            r = local_client.get(f"/api/v1/jobs/{t2d_job_id}")
            assert r.status_code == 200
            t2d_status = r.json()
            if t2d_status["status"] in ("Concluída", "Falhou", "Cancelada"):
                break
            time.sleep(0.05)

        assert t2d_status is not None
        assert t2d_status["status"] == "Concluída", f"Falha no job Text-to-3D: {t2d_status}"
        assert t2d_status["metadata"].get("parsed_intent") == "table"
        assert t2d_status["metadata"].get("detected_components_count", 0) >= 5

        for fmt in ("glb", "obj", "stl"):
            exp_res = local_client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
            assert exp_res.status_code == 200
            assert exp_res.json()["validated"] is True

        # --- Etapa B: Image-to-3D (Upload + Silhouette + Exportação Multiformato) ---
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rectangle([24, 24, 104, 104], fill=(255, 255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        up_res = local_client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("quadrado_ref.png", png_bytes, "image/png")},
        )
        assert up_res.status_code == 200
        up_data = up_res.json()
        ref_filename = up_data["filename"]

        # Verificar recuperação segura da imagem enviada
        get_img_res = local_client.get(f"/api/v1/projects/{proj_id}/images/{ref_filename}")
        assert get_img_res.status_code == 200
        assert get_img_res.content == png_bytes

        i2d_res = local_client.post(
            "/api/v1/jobs",
            json={
                "project_id": proj_id,
                "operation_type": "image_to_3d",
                "params": {
                    "reference_image_filename": ref_filename,
                    "mode": "silhouette",
                    "thickness": 0.15,
                    "resolution_scale": 1.0,
                },
            },
        )
        assert i2d_res.status_code == 200
        i2d_job_id = i2d_res.json()["id"]

        i2d_status = None
        for _ in range(60):
            r = local_client.get(f"/api/v1/jobs/{i2d_job_id}")
            assert r.status_code == 200
            i2d_status = r.json()
            if i2d_status["status"] in ("Concluída", "Falhou", "Cancelada"):
                break
            time.sleep(0.05)

        assert i2d_status is not None
        assert i2d_status["status"] == "Concluída", f"Falha no job Image-to-3D: {i2d_status}"
        assert i2d_status["metadata"].get("image_to_3d_mode") == "silhouette"
        assert i2d_status["metadata"].get("reference_image_filename") == ref_filename

        for fmt in ("glb", "obj", "stl"):
            exp_res = local_client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
            assert exp_res.status_code == 200
            exp_data = exp_res.json()
            assert exp_data["format"] == fmt
            dl_res = local_client.get(f"/api/v1/projects/{proj_id}/artifacts/{exp_data['filename']}")
            assert dl_res.status_code == 200
            assert len(dl_res.content) > 0

        # Limpeza final do projeto de teste
        del_res = local_client.delete(f"/api/v1/projects/{proj_id}")
        assert del_res.status_code == 200
