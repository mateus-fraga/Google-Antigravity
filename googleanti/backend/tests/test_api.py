import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["local_only"] is True

def test_project_and_job_api_lifecycle():
    # 1. Criar projeto
    proj_resp = client.post(
        "/api/v1/projects",
        json={
            "name": "API Test Project",
            "description": "Criado via teste de integração",
            "category": "mechanical",
            "purpose": "visualization"
        }
    )
    assert proj_resp.status_code == 200
    proj_data = proj_resp.json()
    proj_id = proj_data["id"]

    # 2. Listar projetos
    list_resp = client.get("/api/v1/projects")
    assert list_resp.status_code == 200
    assert any(p["id"] == proj_id for p in list_resp.json())

    # 3. Disparar geração de Job procedural
    job_resp = client.post(
        "/api/v1/jobs",
        json={
            "project_id": proj_id,
            "operation_type": "procedural_generation",
            "params": {"shape_type": "box", "width": 1.5, "height": 0.5, "depth": 1.0}
        }
    )
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    job_id = job_data["id"]

    # 4. Consultar status do Job
    status_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == job_id

    # 5. Excluir projeto
    del_resp = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_resp.status_code == 200
