import os
import json
import uuid
import shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.app.main import app, reconcile_storage_and_quarantine
from backend.app.config import settings
from backend.app.storage.database import SessionLocal, ProjectModel, JobModel, init_db, engine
from backend.app.jobs.orchestrator import JobOrchestrator

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

def test_cross_project_artifact_access_denied():
    """
    Testa acesso indevido entre projetos diferentes:
    O projeto A não pode baixar artefatos do projeto B mesmo que forneça o nome correto.
    """
    res_a = client.post("/api/v1/projects", json={"name": "Project A"})
    res_b = client.post("/api/v1/projects", json={"name": "Project B"})
    id_a = res_a.json()["id"]
    id_b = res_b.json()["id"]

    dir_b = settings.STORAGE_DIR / id_b
    dir_b.mkdir(parents=True, exist_ok=True)
    file_b = dir_b / "project_b_model.glb"
    file_b.write_bytes(b"PROJECT_B_CONTENT")

    # Registrar arquivo no projeto B
    db = SessionLocal()
    job_b = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=id_b,
        operation_type="procedural_generation",
        status="Concluída",
        result_files_json=json.dumps([str(file_b.relative_to(settings.BASE_DIR))])
    )
    db.add(job_b)
    db.commit()
    db.close()

    # Tentativa de baixar artefato de B através da rota de A
    cross_res = client.get(f"/api/v1/projects/{id_a}/artifacts/project_b_model.glb")
    assert cross_res.status_code in [403, 404]

    # Limpeza
    client.delete(f"/api/v1/projects/{id_a}")
    client.delete(f"/api/v1/projects/{id_b}")

def test_recoverable_project_deletion_with_quarantine():
    """
    Testa a exclusão recuperável em duas fases:
    1. Marcação como 'deleting'
    2. Movimentação física segura para quarentena
    3. Exclusão no SQLite e limpeza em background
    """
    res_proj = client.post("/api/v1/projects", json={"name": "Deletion Test Project"})
    assert res_proj.status_code == 200
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    test_file = proj_dir / "mesh.glb"
    test_file.write_bytes(b"MESH_DATA")

    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    assert not proj_dir.exists()
    get_res = client.get(f"/api/v1/projects/{proj_id}")
    assert get_res.status_code == 404

def test_deletion_cancels_active_jobs():
    """
    Testa que ao excluir um projeto com jobs ativos,
    os jobs são cancelados antes da exclusão.
    """
    res_proj = client.post("/api/v1/projects", json={"name": "Job Cancel Test"})
    proj_id = res_proj.json()["id"]

    db = SessionLocal()
    job = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=proj_id,
        operation_type="procedural_generation",
        status="Em Execução"
    )
    db.add(job)
    db.commit()
    db.close()

    # Deletar projeto
    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    # Confirmar que o job foi cancelado e/ou removido com o projeto
    db = SessionLocal()
    persisted_job = db.query(JobModel).filter(JobModel.id == job.id).first()
    assert persisted_job is None
    db.close()

def test_reconciliation_restores_quarantined_project_on_failed_delete():
    """
    Testa o cenário crítico de falha:
    O servidor caiu logo após mover para quarentena, mas o projeto AINDA existe no banco com status 'deleting'.
    A reconciliação deve restaurar a pasta da quarentena de volta ao storage e reativar o projeto para 'active'.
    """
    proj_id = f"proj-fail-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    proj = ProjectModel(
        id=proj_id,
        name="Interrupted Delete Project",
        status="deleting"
    )
    db.add(proj)
    db.commit()
    db.close()

    # Criar pasta correspondente na quarentena
    quarantine_folder = settings.QUARANTINE_DIR / f"{proj_id}_20261104120000123456"
    quarantine_folder.mkdir(parents=True, exist_ok=True)
    (quarantine_folder / "saved_model.glb").write_bytes(b"RECOVERABLE_CONTENT")

    # Executar reconciliação de startup
    reconcile_storage_and_quarantine()

    # Verificar que a pasta foi restaurada para storage/projects/{id}
    restored_dir = settings.STORAGE_DIR / proj_id
    assert restored_dir.exists()
    assert (restored_dir / "saved_model.glb").exists()
    assert not quarantine_folder.exists()

    # Verificar que o projeto foi reativado para 'active'
    db = SessionLocal()
    recovered_proj = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert recovered_proj is not None
    assert recovered_proj.status == "active"
    db.close()

    # Limpeza
    client.delete(f"/api/v1/projects/{proj_id}")

def test_reconciliation_finalizes_delete_when_files_already_gone():
    """
    Testa o cenário onde os arquivos já foram removidos da quarentena e do storage,
    mas o processo caiu antes do commit no banco. A reconciliação deve finalizar a remoção do SQLite.
    """
    proj_id = f"proj-ghost-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    proj = ProjectModel(
        id=proj_id,
        name="Ghost Project",
        status="deleting"
    )
    db.add(proj)
    db.commit()
    db.close()

    # Garantir que não existe pasta em lugar nenhum
    assert not (settings.STORAGE_DIR / proj_id).exists()

    reconcile_storage_and_quarantine()

    db = SessionLocal()
    ghost = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert ghost is None
    db.close()

def test_sqlite_status_migration_idempotent():
    """
    Testa que a inicialização do banco e a migração da coluna status
    são idempotentes e funcionam repetidamente sem erros.
    """
    # Executar init_db múltiplas vezes consecutivas
    init_db()
    init_db()
    init_db()

    # Validar que a coluna status permanece acessível e funcional
    db = SessionLocal()
    p = ProjectModel(id=f"proj-mig-{uuid.uuid4().hex[:6]}", name="Mig Test", status="active")
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.status == "active"
    db.delete(p)
    db.commit()
    db.close()
