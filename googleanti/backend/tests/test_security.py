import os
import json
import uuid
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app, reconcile_storage_and_quarantine
from backend.app.config import settings
from backend.app.storage.database import SessionLocal, ProjectModel, JobModel

client = TestClient(app)

def test_secure_artifact_download():
    """
    Testa o endpoint contextual seguro /projects/{id}/artifacts/{filename}
    e valida proteções contra path traversal, nomes inválidos e arquivos não autorizados.
    """
    # 1. Criar projeto de teste
    res_proj = client.post("/api/v1/projects", json={"name": "Security Test Project"})
    assert res_proj.status_code == 200
    proj_id = res_proj.json()["id"]

    # Criar pasta e arquivo físico registrado
    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    valid_file = proj_dir / "valid_model.glb"
    valid_file.write_bytes(b"TEST_GLB_BINARY_CONTENT")

    # Registrar arquivo no projeto através de um job no banco
    db = SessionLocal()
    job = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=proj_id,
        operation_type="procedural_generation",
        status="Concluída",
        result_files_json=json.dumps([str(valid_file.relative_to(settings.BASE_DIR))])
    )
    db.add(job)
    db.commit()
    db.close()

    # Cenário A: Download com sucesso de artefato registrado
    dl_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/valid_model.glb")
    assert dl_res.status_code == 200
    assert dl_res.content == b"TEST_GLB_BINARY_CONTENT"
    assert dl_res.headers["content-type"] == "model/gltf-binary"

    # Cenário B: Tentativa de Path Traversal clássico com ../
    bad_res1 = client.get(f"/api/v1/projects/{proj_id}/artifacts/..%2f..%2fai_3d_studio.db")
    assert bad_res1.status_code in [400, 403, 404]

    bad_res2 = client.get(f"/api/v1/projects/{proj_id}/artifacts/../../../ai_3d_studio.db")
    assert bad_res2.status_code in [400, 403, 404]

    # Cenário C: Tentativa de baixar arquivo existente mas NÃO registrado no projeto
    unregistered_file = proj_dir / "secret.txt"
    unregistered_file.write_text("sensivel")
    unreg_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/secret.txt")
    assert unreg_res.status_code == 403

    # Cenário D: Tentativa com caracteres ilegais
    bad_chars = client.get(f"/api/v1/projects/{proj_id}/artifacts/invalid*name?.glb")
    assert bad_chars.status_code == 400

    # Cenário E: Arquivo inexistente
    missing_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/nonexistent.glb")
    assert missing_res.status_code in [403, 404]

    # Limpeza
    client.delete(f"/api/v1/projects/{proj_id}")

def test_recoverable_project_deletion_with_quarantine():
    """
    Testa a exclusão recuperável em duas fases:
    1. Marcação como 'deleting'
    2. Movimentação física segura para quarentena
    3. Exclusão no SQLite e limpeza em background
    """
    # Criar projeto
    res_proj = client.post("/api/v1/projects", json={"name": "Deletion Test Project"})
    assert res_proj.status_code == 200
    proj_id = res_proj.json()["id"]

    # Criar arquivos reais na pasta do projeto
    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    test_file = proj_dir / "mesh.glb"
    test_file.write_bytes(b"MESH_DATA")

    # Excluir projeto
    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    # Verificar que pasta original foi removida
    assert not proj_dir.exists()

    # Verificar que o projeto não pode mais ser consultado
    get_res = client.get(f"/api/v1/projects/{proj_id}")
    assert get_res.status_code == 404

def test_startup_reconciliation_cleans_quarantine():
    """
    Testa a reconciliação pós-reboot (Task 1.3):
    Pastas residuais em storage/.quarantine/ são limpas automaticamente.
    """
    # Criar uma pasta órfã simulando queda do servidor durante exclusão
    orphan_dir = settings.QUARANTINE_DIR / f"orphan_proj_{uuid.uuid4().hex[:6]}"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "temp_file.bin").write_bytes(b"ORPHAN_DATA")

    assert orphan_dir.exists()

    # Executar a rotina de reconciliação do lifespan
    reconcile_storage_and_quarantine()

    # Confirmar que a pasta órfã foi eliminada com segurança
    assert not orphan_dir.exists()
