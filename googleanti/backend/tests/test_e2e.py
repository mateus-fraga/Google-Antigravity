import pytest
import os
from pathlib import Path
from fastapi.testclient import TestClient
import trimesh
from backend.app.main import app
from backend.app.config import settings

client = TestClient(app)

def test_full_e2e_workflow():
    """
    Fluxo de aceitação E2E Local:
    1. Criar novo projeto
    2. Submeter tarefa de geração de engrenagem paramétrica
    3. Aguardar conclusão e verificar modelo GLB gerado em disco
    4. Validar que o GLB pode ser carregado e inspecionado com sucesso (Three.js / Trimesh)
    5. Fazer download do arquivo através do endpoint de arquivos
    6. Excluir o projeto e verificar integridade
    """
    # 1. Criar Projeto
    create_res = client.post(
        "/api/v1/projects",
        json={
            "name": "E2E Gear Project",
            "description": "Engrenagem mecânica procedural para teste de aceitação",
            "category": "mechanical",
            "purpose": "technical",
            "strategy": "procedural"
        }
    )
    assert create_res.status_code == 200
    proj_data = create_res.json()
    proj_id = proj_data["id"]

    # 2. Submeter Tarefa de Geração Procedural
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

    # 3. Consultar Job e verificar conclusão
    status_res = client.get(f"/api/v1/jobs/{job_id}")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["status"] == "Concluída"
    assert len(status_data["result_files"]) > 0

    glb_relative_path = status_data["result_files"][0]
    glb_full_path = settings.BASE_DIR / glb_relative_path
    assert glb_full_path.exists()
    assert glb_full_path.stat().st_size > 0

    # 4. Validar geometria reimportada
    loaded_scene = trimesh.load(str(glb_full_path))
    assert not loaded_scene.is_empty

    # 5. Download via API
    dl_res = client.get(f"/api/v1/files/download?path={glb_full_path}")
    assert dl_res.status_code == 200
    assert len(dl_res.content) == glb_full_path.stat().st_size

    # 6. Limpeza e Exclusão
    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200
