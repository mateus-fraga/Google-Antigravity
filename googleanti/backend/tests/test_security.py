import os
import json
import uuid
import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.app.main import (
    app,
    reconcile_storage_and_quarantine,
    validate_quarantine_manifest,
    parse_quarantine_folder_name,
    find_project_quarantine_dirs
)
import backend.app.main as main_mod
import backend.app.api.routes as routes_mod
import backend.app.storage.database as db_mod
from backend.app.config import settings
from backend.app.storage.database import Base, get_db, ProjectModel, JobModel, init_db
from backend.app.jobs.orchestrator import JobOrchestrator

@pytest.fixture(autouse=True)
def isolated_storage_and_db(tmp_path, monkeypatch):
    """
    Fixture autouse que isola completamente STORAGE_DIR, QUARANTINE_DIR, BASE_DIR e o banco SQLite
    em um diretório temporário exclusivo (tmp_path) para cada teste.
    Garante que nenhum teste modifique ou destrua dados reais do projeto.
    """
    test_base_dir = tmp_path / "workspace"
    test_storage_dir = test_base_dir / "projects"
    test_quarantine_dir = test_storage_dir / ".quarantine"
    test_models_dir = test_base_dir / "models"
    test_db_path = test_base_dir / "test_ai_3d_studio.db"

    test_storage_dir.mkdir(parents=True, exist_ok=True)
    test_quarantine_dir.mkdir(parents=True, exist_ok=True)
    test_models_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "BASE_DIR", test_base_dir)
    monkeypatch.setattr(settings, "STORAGE_DIR", test_storage_dir)
    monkeypatch.setattr(settings, "QUARANTINE_DIR", test_quarantine_dir)
    monkeypatch.setattr(settings, "MODELS_DIR", test_models_dir)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{test_db_path}")

    test_engine = create_engine(
        f"sqlite:///{test_db_path}",
        connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(db_mod, "engine", test_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(main_mod, "SessionLocal", TestingSessionLocal)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestingSessionLocal
    app.dependency_overrides.clear()
    test_engine.dispose()

client = TestClient(app)

def test_secure_artifact_download(isolated_storage_and_db):
    """
    Testa o endpoint contextual seguro /projects/{id}/artifacts/{filename}
    e valida proteções contra path traversal, nomes inválidos e arquivos não autorizados.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Security Test Project"})
    assert res_proj.status_code == 200
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    valid_file = proj_dir / "valid_model.glb"
    valid_file.write_bytes(b"TEST_GLB_BINARY_CONTENT")

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

    client.delete(f"/api/v1/projects/{proj_id}")

def test_cross_project_artifact_access_denied(isolated_storage_and_db):
    """
    Testa que um artefato existente no Projeto A NÃO pode ser acessado pelo endpoint do Projeto B.
    """
    SessionLocal = isolated_storage_and_db
    res_a = client.post("/api/v1/projects", json={"name": "Project A"})
    proj_a = res_a.json()["id"]

    res_b = client.post("/api/v1/projects", json={"name": "Project B"})
    proj_b = res_b.json()["id"]

    dir_a = settings.STORAGE_DIR / proj_a
    dir_a.mkdir(parents=True, exist_ok=True)
    file_a = dir_a / "model_a.glb"
    file_a.write_bytes(b"DATA_A")

    db = SessionLocal()
    job_a = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=proj_a,
        operation_type="procedural_generation",
        status="Concluída",
        result_files_json=json.dumps([str(file_a.relative_to(settings.BASE_DIR))])
    )
    db.add(job_a)
    db.commit()
    db.close()

    cross_res = client.get(f"/api/v1/projects/{proj_b}/artifacts/model_a.glb")
    assert cross_res.status_code in [403, 404]

    client.delete(f"/api/v1/projects/{proj_a}")
    client.delete(f"/api/v1/projects/{proj_b}")

def test_symlink_download_blocked_even_within_same_project(isolated_storage_and_db, monkeypatch):
    """
    SEC-001: Impede downloads por links simbólicos, inclusive quando o symlink
    aponta para um arquivo real existente e registrado dentro do mesmo projeto,
    tanto na rota contextual quanto na rota legada.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Symlink Test Project"})
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    real_file = proj_dir / "real_model.glb"
    real_file.write_bytes(b"REAL_MODEL_DATA")

    symlink_file = proj_dir / "linked_model.glb"

    # Tentar criar symlink real; se o Windows bloquear por falta de privilégio de admin,
    # criamos o arquivo e simulamos a detecção de symlink no caminho antes do resolve().
    symlink_created = False
    try:
        os.symlink(str(real_file), str(symlink_file))
        symlink_created = True
    except OSError:
        symlink_file.write_bytes(b"REAL_MODEL_DATA")
        orig_islink = os.path.islink
        def mock_islink(p):
            if Path(p).name == "linked_model.glb":
                return True
            return orig_islink(p)
        monkeypatch.setattr(os.path, "islink", mock_islink)

    # Registrar AMBOS os nomes no banco para provar que mesmo registrado o symlink é bloqueado!
    db = SessionLocal()
    job = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=proj_id,
        operation_type="procedural_generation",
        status="Concluída",
        result_files_json=json.dumps([
            str(real_file.relative_to(settings.BASE_DIR)),
            str(symlink_file.relative_to(settings.BASE_DIR))
        ])
    )
    db.add(job)
    db.commit()
    db.close()

    # O arquivo real deve ser baixado normalmente (200)
    ok_ctx = client.get(f"/api/v1/projects/{proj_id}/artifacts/real_model.glb")
    assert ok_ctx.status_code == 200

    # O symlink (mesmo apontando para real_model.glb dentro do mesmo projeto e registrado) DEVE ser bloqueado (403)
    sym_ctx = client.get(f"/api/v1/projects/{proj_id}/artifacts/linked_model.glb")
    assert sym_ctx.status_code == 403

    # Na rota legada, o symlink também DEVE ser bloqueado (403)
    rel_sym = f"{proj_id}/linked_model.glb"
    sym_leg = client.get(f"/api/v1/files/download?path={rel_sym}")
    assert sym_leg.status_code == 403

def test_legacy_download_endpoint_security_and_authorization(isolated_storage_and_db):
    """
    SEC-001: Valida o endpoint legado /files/download.
    Garante que não é permitido download arbitrário de outros projetos,
    arquivos internos, bancos SQLite, projetos em exclusão ou arquivos não registrados.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Legacy DL Project"})
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    valid_file = proj_dir / "legacy_model.glb"
    valid_file.write_bytes(b"LEGACY_GLB_DATA")

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

    # 1. Download legítimo do arquivo registrado pelo caminho relativo a STORAGE_DIR e BASE_DIR
    rel_storage = str(valid_file.relative_to(settings.STORAGE_DIR))
    ok_res1 = client.get(f"/api/v1/files/download?path={rel_storage}")
    assert ok_res1.status_code == 200
    assert ok_res1.content == b"LEGACY_GLB_DATA"

    rel_base = str(valid_file.relative_to(settings.BASE_DIR))
    ok_res2 = client.get(f"/api/v1/files/download?path={rel_base}")
    assert ok_res2.status_code == 200
    assert ok_res2.content == b"LEGACY_GLB_DATA"

    # 2. Tentativa de traversal para banco SQLite
    db_res = client.get("/api/v1/files/download?path=../test_ai_3d_studio.db")
    assert db_res.status_code in [400, 403, 404]

    # 3. Tentativa de baixar arquivo existente mas não registrado
    secret_file = proj_dir / "unregistered.txt"
    secret_file.write_text("secret")
    unreg_res = client.get(f"/api/v1/files/download?path={str(secret_file.relative_to(settings.STORAGE_DIR))}")
    assert unreg_res.status_code == 403

    # 4. Tentativa de acessar arquivo de quarentena ou subdiretório
    quarantine_res = client.get("/api/v1/files/download?path=.quarantine/some_file.glb")
    assert quarantine_res.status_code in [400, 403, 404]

    # 5. Projeto em estado 'deleting' deve negar download em ambas as rotas
    db = SessionLocal()
    p = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    p.status = "deleting"
    db.commit()
    db.close()

    del_state_legacy = client.get(f"/api/v1/files/download?path={rel_storage}")
    assert del_state_legacy.status_code == 404
    del_state_ctx = client.get(f"/api/v1/projects/{proj_id}/artifacts/legacy_model.glb")
    assert del_state_ctx.status_code == 404

def test_recoverable_project_deletion_with_quarantine(isolated_storage_and_db):
    """
    Testa a exclusão recuperável em duas fases com quarentena, escrita atômica do manifesto e expurgo.
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

def test_delete_project_aborts_and_restores_when_manifest_write_fails(isolated_storage_and_db, monkeypatch):
    """
    STORE-002 / STORE-003: Se a gravação/sincronização do manifesto atômico falhar durante DELETE /projects/{id},
    a operação NÃO pode ser apresentada como concluída com sucesso:
    - Deve retornar HTTP 500
    - Deve restaurar os arquivos da quarentena de volta para STORAGE_DIR/{project_id}
    - Deve reverter o status do projeto no SQLite para 'active' sem perda de dados.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Manifest Fail Project"})
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    model_file = proj_dir / "important.glb"
    model_file.write_bytes(b"CRITICAL_3D_DATA")

    # Simular falha de fsync durante a escrita do manifesto
    monkeypatch.setattr(routes_mod, "write_atomic_quarantine_manifest", lambda *args, **kwargs: False)

    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 500

    # Arquivos devem ter sido restaurados intactos para a pasta do projeto
    assert proj_dir.exists()
    assert model_file.exists()
    assert model_file.read_bytes() == b"CRITICAL_3D_DATA"

    # Projeto deve continuar ativo no banco de dados
    db = SessionLocal()
    proj = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert proj is not None
    assert proj.status == "active"
    db.close()

def test_delete_project_rolls_back_and_removes_manifest_on_sqlite_commit_failure(isolated_storage_and_db, monkeypatch):
    """
    STORE-003: Simula falha no commit SQLite durante DELETE /projects/{id} após o manifesto ter sido escrito.
    Verifica que:
    - O manifesto é removido para evitar expurgo acidental futuro
    - A pasta é devolvida da quarentena para STORAGE_DIR/{project_id}
    - O projeto permanece íntegro e ativo no banco e no filesystem.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Commit Fail Delete Project"})
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    model_file = proj_dir / "asset.glb"
    model_file.write_bytes(b"ASSET_BINARY")

    # Interceptar commit na sessão para falhar na segunda chamada (a 1ª marca 'deleting', a 2ª faz o delete final)
    commit_count = {"n": 0}
    orig_session_cls = SessionLocal

    def faulty_get_db():
        db = orig_session_cls()
        orig_commit = db.commit
        def custom_commit():
            commit_count["n"] += 1
            if commit_count["n"] == 2:
                raise RuntimeError("Simulated SQLite disk full on delete commit")
            return orig_commit()
        db.commit = custom_commit
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = faulty_get_db
    try:
        del_res = client.delete(f"/api/v1/projects/{proj_id}")
        assert del_res.status_code == 500
    finally:
        # Restaurar override normal da fixture
        def normal_get_db():
            db = orig_session_cls()
            try:
                yield db
            finally:
                db.close()
        app.dependency_overrides[get_db] = normal_get_db

    # Verificar que a pasta e o arquivo voltaram para STORAGE_DIR e não há manifesto residual
    assert proj_dir.exists()
    assert model_file.exists()
    assert model_file.read_bytes() == b"ASSET_BINARY"
    assert not (proj_dir / ".quarantine_meta.json").exists()

    # Verificar que o projeto continua ativo no banco
    db = SessionLocal()
    proj = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert proj is not None
    assert proj.status == "active"
    db.close()

def test_deletion_cancels_active_jobs(isolated_storage_and_db):
    """
    Testa que ao excluir um projeto com jobs ativos, os jobs são cancelados e removidos.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "Job Cancel Test"})
    proj_id = res_proj.json()["id"]

    db = SessionLocal()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    job = JobModel(
        id=job_id,
        project_id=proj_id,
        operation_type="procedural_generation",
        status="Em Execução"
    )
    db.add(job)
    db.commit()
    db.close()

    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    db = SessionLocal()
    persisted_job = db.query(JobModel).filter(JobModel.id == job_id).first()
    assert persisted_job is None
    db.close()

def test_reconciliation_restores_quarantined_project_on_failed_delete(isolated_storage_and_db):
    """
    Testa que projeto em 'deleting' com pasta em quarentena SEM manifesto é restaurado
    para STORAGE_DIR e reativado para 'active', resistindo a múltiplas execuções repetidas.
    """
    SessionLocal = isolated_storage_and_db
    proj_id = f"proj-fail-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    proj = ProjectModel(id=proj_id, name="Interrupted Delete Project", status="deleting")
    db.add(proj)
    db.commit()
    db.close()

    quarantine_folder = settings.QUARANTINE_DIR / f"{proj_id}_20261104120000123456"
    quarantine_folder.mkdir(parents=True, exist_ok=True)
    (quarantine_folder / "saved_model.glb").write_bytes(b"RECOVERABLE_CONTENT")

    # Executar reconciliação repetidas vezes para validar idempotência
    reconcile_storage_and_quarantine()
    reconcile_storage_and_quarantine()
    reconcile_storage_and_quarantine()

    restored_dir = settings.STORAGE_DIR / proj_id
    assert restored_dir.exists()
    assert (restored_dir / "saved_model.glb").read_bytes() == b"RECOVERABLE_CONTENT"
    assert not quarantine_folder.exists()

    db = SessionLocal()
    recovered_proj = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert recovered_proj is not None
    assert recovered_proj.status == "active"
    db.close()

def test_reconciliation_handles_sqlite_commit_failure_without_data_loss(isolated_storage_and_db, monkeypatch):
    """
    STORE-003: Testa falha no commit SQLite DURANTE a reconciliação:
    1) Para um projeto com manifesto confirmado: se o commit do banco falhar, a pasta na quarentena
       NÃO deve ter sido apagada antes do commit; na execução seguinte (quando o banco volta a funcionar),
       tanto o registro quanto a pasta são limpos com consistência.
    2) Para um projeto sem manifesto (recuperável): se o commit após restaurar a pasta falhar,
       os arquivos permanecem seguros em STORAGE_DIR e na execução seguinte o status volta para 'active'.
    """
    SessionLocal = isolated_storage_and_db
    proj_confirmed = f"proj-conf-{uuid.uuid4().hex[:6]}"
    proj_recover = f"proj-rec-{uuid.uuid4().hex[:6]}"
    ts_str = "20261109120000123456"

    db = SessionLocal()
    db.add(ProjectModel(id=proj_confirmed, name="Confirmed Delete", status="deleting"))
    db.add(ProjectModel(id=proj_recover, name="Recoverable Delete", status="deleting"))
    db.commit()
    db.close()

    # Criar pasta confirmada com manifesto válido
    q_conf = settings.QUARANTINE_DIR / f"{proj_confirmed}_{ts_str}"
    q_conf.mkdir(parents=True, exist_ok=True)
    routes_mod.write_atomic_quarantine_manifest(q_conf, proj_confirmed, ts_str)
    (q_conf / "mesh.glb").write_bytes(b"TO_BE_DELETED_AFTER_DB_COMMIT")

    # Criar pasta recuperável sem manifesto
    q_rec = settings.QUARANTINE_DIR / f"{proj_recover}_{ts_str}"
    q_rec.mkdir(parents=True, exist_ok=True)
    (q_rec / "keep.glb").write_bytes(b"MUST_SURVIVE_DB_FAILURE")

    # Simular falha em todos os commits durante a 1ª execução da reconciliação
    orig_session_local = main_mod.SessionLocal
    def failing_session_factory():
        s = orig_session_local()
        def fail_commit():
            raise RuntimeError("Simulated SQLite Failure During Reconciliation")
        s.commit = fail_commit
        return s

    monkeypatch.setattr(main_mod, "SessionLocal", failing_session_factory)
    reconcile_storage_and_quarantine()

    # Como o commit falhou para proj_confirmed, a pasta q_conf AINDA deve existir (não foi destruída antes do commit!)
    assert q_conf.exists()
    # Os arquivos de proj_recover já foram movidos para STORAGE_DIR e estão seguros
    assert (settings.STORAGE_DIR / proj_recover / "keep.glb").read_bytes() == b"MUST_SURVIVE_DB_FAILURE"

    # Restaurar SessionLocal normal e rodar a 2ª reconciliação
    monkeypatch.setattr(main_mod, "SessionLocal", orig_session_local)
    reconcile_storage_and_quarantine()

    # Agora proj_confirmed foi removido do banco e sua pasta q_conf foi purgada
    assert not q_conf.exists()
    # E proj_recover está 'active' no banco com seus arquivos intactos em STORAGE_DIR
    db = orig_session_local()
    assert db.query(ProjectModel).filter(ProjectModel.id == proj_confirmed).first() is None
    rec_obj = db.query(ProjectModel).filter(ProjectModel.id == proj_recover).first()
    assert rec_obj is not None
    assert rec_obj.status == "active"
    db.close()
    assert (settings.STORAGE_DIR / proj_recover / "keep.glb").read_bytes() == b"MUST_SURVIVE_DB_FAILURE"

def test_reconciliation_finalizes_delete_when_files_already_gone(isolated_storage_and_db):
    """
    Testa o cenário onde os arquivos já foram removidos da quarentena e do storage,
    mas o processo caiu antes do commit no banco. A reconciliação deve finalizar a remoção do SQLite.
    """
    SessionLocal = isolated_storage_and_db
    proj_id = f"proj-ghost-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    proj = ProjectModel(id=proj_id, name="Ghost Project", status="deleting")
    db.add(proj)
    db.commit()
    db.close()

    assert not (settings.STORAGE_DIR / proj_id).exists()

    reconcile_storage_and_quarantine()

    db = SessionLocal()
    ghost = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert ghost is None
    db.close()

def test_sqlite_status_migration_idempotent(isolated_storage_and_db):
    """
    Testa que a inicialização do banco e a migração da coluna status são idempotentes.
    """
    SessionLocal = isolated_storage_and_db
    init_db()
    init_db()

    db = SessionLocal()
    p = ProjectModel(id=f"proj-mig-{uuid.uuid4().hex[:6]}", name="Mig Test", status="active")
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.status == "active"
    db.delete(p)
    db.commit()
    db.close()

def test_quarantine_preserves_files_on_shutil_move_failure(isolated_storage_and_db, monkeypatch):
    """
    STORE-003: Falha simulada de shutil.move durante a restauração na reconciliação.
    Garante que os arquivos na quarentena NÃO são removidos e que o projeto permanece em 'deleting',
    mesmo após repetidas execuções com falha, e se recupera assim que a falha de I/O cessa.
    """
    SessionLocal = isolated_storage_and_db
    proj_id = f"proj-failmove-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    proj = ProjectModel(id=proj_id, name="Failed Move Project", status="deleting")
    db.add(proj)
    db.commit()
    db.close()

    quarantine_folder = settings.QUARANTINE_DIR / f"{proj_id}_20261109120000123456"
    quarantine_folder.mkdir(parents=True, exist_ok=True)
    test_file = quarantine_folder / "crucial_data.bin"
    test_file.write_bytes(b"PRESERVED_CONTENT")

    orig_move = shutil.move
    def fake_move(src, dst):
        raise OSError("Simulated Permission Denied on Move")

    monkeypatch.setattr(shutil, "move", fake_move)

    # Executar duas vezes com falha de I/O
    reconcile_storage_and_quarantine()
    reconcile_storage_and_quarantine()

    assert quarantine_folder.exists()
    assert test_file.exists()
    assert test_file.read_bytes() == b"PRESERVED_CONTENT"

    db = SessionLocal()
    proj_check = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert proj_check is not None
    assert proj_check.status == "deleting"
    db.close()

    # Agora restaurar shutil.move normal e verificar que a reconciliação recupera o projeto!
    monkeypatch.setattr(shutil, "move", orig_move)
    reconcile_storage_and_quarantine()

    assert not quarantine_folder.exists()
    assert (settings.STORAGE_DIR / proj_id / "crucial_data.bin").read_bytes() == b"PRESERVED_CONTENT"
    db = SessionLocal()
    proj_recovered = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
    assert proj_recovered.status == "active"
    db.close()

def test_quarantine_orphan_preservation_without_manifest(isolated_storage_and_db):
    """
    STORE-004: Diretório na quarentena sem manifesto de exclusão confirmada
    e sem registro no banco deve ser preservado preventivamente em múltiplas execuções.
    """
    orphan_dir = settings.QUARANTINE_DIR / f"proj-orphan-{uuid.uuid4().hex[:6]}_20261109120000"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "unconfirmed.glb").write_bytes(b"DO_NOT_DELETE")

    reconcile_storage_and_quarantine()
    reconcile_storage_and_quarantine()

    assert orphan_dir.exists()
    assert (orphan_dir / "unconfirmed.glb").exists()

def test_quarantine_deletes_confirmed_manifest(isolated_storage_and_db):
    """
    STORE-004: Diretório na quarentena com manifesto formal estruturado completo
    (version=1, project_id exato da pasta, delete_confirmed=True, timestamp exato da pasta)
    deve ser expurgado com segurança.
    """
    proj_id = f"proj-confirmed-{uuid.uuid4().hex[:6]}"
    ts_str = "20261109120000123456"
    confirmed_dir = settings.QUARANTINE_DIR / f"{proj_id}_{ts_str}"
    confirmed_dir.mkdir(parents=True, exist_ok=True)

    assert routes_mod.write_atomic_quarantine_manifest(confirmed_dir, proj_id, ts_str) is True
    (confirmed_dir / "old.glb").write_bytes(b"SAFE_TO_DELETE")

    reconcile_storage_and_quarantine()

    assert not confirmed_dir.exists()

def test_quarantine_strict_manifest_validation_edge_cases(isolated_storage_and_db):
    """
    STORE-004: Valida que manifestos incompletos, com tipos incorretos, booleanos disfarçados de version,
    timestamps inválidos ou associados a outro projeto (divergência entre manifesto e nome da pasta)
    resultam SEMPRE na preservação dos arquivos.
    Também verifica ausência de colisão de prefixo (ex: proj-1 vs proj-10).
    """
    ts_str = "20261109120000123456"

    # Caso 1: Manifesto pertencente a outro projeto (project_id != folder project_id)
    dir_mismatch = settings.QUARANTINE_DIR / f"proj-real_{ts_str}"
    dir_mismatch.mkdir(parents=True, exist_ok=True)
    (dir_mismatch / ".quarantine_meta.json").write_text(json.dumps({
        "version": 1,
        "project_id": "proj-other",
        "delete_confirmed": True,
        "timestamp": ts_str
    }))
    (dir_mismatch / "data.glb").write_bytes(b"KEEP_1")

    # Caso 2: Timestamp do manifesto diverge do timestamp da pasta
    dir_ts_diff = settings.QUARANTINE_DIR / f"proj-ts_{ts_str}"
    dir_ts_diff.mkdir(parents=True, exist_ok=True)
    (dir_ts_diff / ".quarantine_meta.json").write_text(json.dumps({
        "version": 1,
        "project_id": "proj-ts",
        "delete_confirmed": True,
        "timestamp": "20261109120000999999"
    }))
    (dir_ts_diff / "data.glb").write_bytes(b"KEEP_2")

    # Caso 3: Tipos inválidos (delete_confirmed="true" string, ou version=True booleano)
    dir_bad_types = settings.QUARANTINE_DIR / f"proj-types_{ts_str}"
    dir_bad_types.mkdir(parents=True, exist_ok=True)
    (dir_bad_types / ".quarantine_meta.json").write_text(json.dumps({
        "version": True,
        "project_id": "proj-types",
        "delete_confirmed": True,
        "timestamp": ts_str
    }))
    (dir_bad_types / "data.glb").write_bytes(b"KEEP_3")

    # Caso 4: Colisão de prefixo entre proj-1 e proj-10
    dir_p10 = settings.QUARANTINE_DIR / f"proj-10_{ts_str}"
    dir_p10.mkdir(parents=True, exist_ok=True)
    assert find_project_quarantine_dirs(settings.QUARANTINE_DIR, "proj-1") == []
    assert len(find_project_quarantine_dirs(settings.QUARANTINE_DIR, "proj-10")) == 1

    reconcile_storage_and_quarantine()

    # Todos os diretórios com manifestos inválidos/divergentes DEVEM ter sido preservados!
    assert (dir_mismatch / "data.glb").read_bytes() == b"KEEP_1"
    assert (dir_ts_diff / "data.glb").read_bytes() == b"KEEP_2"
    assert (dir_bad_types / "data.glb").read_bytes() == b"KEEP_3"


def test_remove_quarantine_path_validates_manifest_and_blocks_unauthorized_dirs(isolated_storage_and_db):
    """
    STORE-003 / STORE-004: Testa diretamente `remove_quarantine_path()` contra:
    - Diretório fora de QUARANTINE_DIR (ex: pasta ativa em STORAGE_DIR ou o próprio QUARANTINE_DIR)
    - Pasta sem manifesto .quarantine_meta.json
    - Pasta com manifesto inválido (sem version ou delete_confirmed=False)
    - Pasta com manifesto associado a outro projeto (divergência com o nome da pasta ou expected_project_id)
    - Pasta com manifesto válido e íntegro (único caso em que a purga é autorizada).
    """
    ts_str = "20261109120000123456"

    # 1. Tentativa de purgar diretório fora de QUARANTINE_DIR (pasta ativa de projeto em STORAGE_DIR)
    active_proj_dir = settings.STORAGE_DIR / "proj-active-1"
    active_proj_dir.mkdir(parents=True, exist_ok=True)
    (active_proj_dir / "active.glb").write_bytes(b"ACTIVE_DATA")
    assert routes_mod.remove_quarantine_path(active_proj_dir) is False
    assert (active_proj_dir / "active.glb").exists()

    # 2. Tentativa de purgar o próprio QUARANTINE_DIR raiz
    assert routes_mod.remove_quarantine_path(settings.QUARANTINE_DIR) is False
    assert settings.QUARANTINE_DIR.exists()

    # 3. Pasta em quarentena SEM manifesto
    q_no_meta = settings.QUARANTINE_DIR / f"proj-nometa_{ts_str}"
    q_no_meta.mkdir(parents=True, exist_ok=True)
    (q_no_meta / "file.glb").write_bytes(b"NO_META_DATA")
    assert routes_mod.remove_quarantine_path(q_no_meta) is False
    assert (q_no_meta / "file.glb").exists()

    # 4. Pasta em quarentena com manifesto de OUTRO projeto (divergente do nome da pasta)
    q_wrong_proj = settings.QUARANTINE_DIR / f"proj-alpha_{ts_str}"
    q_wrong_proj.mkdir(parents=True, exist_ok=True)
    (q_wrong_proj / ".quarantine_meta.json").write_text(json.dumps({
        "version": 1,
        "project_id": "proj-beta",
        "delete_confirmed": True,
        "timestamp": ts_str,
        "folder_name": q_wrong_proj.name
    }))
    (q_wrong_proj / "file.glb").write_bytes(b"WRONG_PROJ_DATA")
    assert routes_mod.remove_quarantine_path(q_wrong_proj) is False
    assert (q_wrong_proj / "file.glb").exists()

    # 5. Pasta em quarentena com manifesto válido para proj-gamma, mas chamada esperando proj-delta
    q_gamma = settings.QUARANTINE_DIR / f"proj-gamma_{ts_str}"
    q_gamma.mkdir(parents=True, exist_ok=True)
    assert routes_mod.write_atomic_quarantine_manifest(q_gamma, "proj-gamma", ts_str) is True
    (q_gamma / "file.glb").write_bytes(b"GAMMA_DATA")
    assert routes_mod.remove_quarantine_path(q_gamma, expected_project_id="proj-delta") is False
    assert (q_gamma / "file.glb").exists()

    # 6. Agora chamada legítima com expected_project_id="proj-gamma" -> purga autorizada!
    assert routes_mod.remove_quarantine_path(q_gamma, expected_project_id="proj-gamma") is True
    assert not q_gamma.exists()

def test_download_prevents_file_replacement_between_validation_and_streaming(isolated_storage_and_db, monkeypatch):
    """
    SEC-001: Verifica que o download vincula o conteúdo enviado ao descritor de arquivo
    efetivamente validado (_open_verified_regular_file + _stream_from_verified_fd),
    impedindo que a substituição do arquivo entre a validação e a transmissão envie dados não autorizados
    ou permita ataques TOCTOU.
    """
    SessionLocal = isolated_storage_and_db
    res_proj = client.post("/api/v1/projects", json={"name": "TOCTOU Test Project"})
    proj_id = res_proj.json()["id"]

    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    target_file = proj_dir / "model.glb"
    target_file.write_bytes(b"AUTHENTIC_VALIDATED_GLB_BYTES")

    db = SessionLocal()
    job = JobModel(
        id=f"job-{uuid.uuid4().hex[:8]}",
        project_id=proj_id,
        operation_type="procedural_generation",
        status="Concluída",
        result_files_json=json.dumps([str(target_file.relative_to(settings.BASE_DIR))])
    )
    db.add(job)
    db.commit()
    db.close()

    # Parte A: Simular substituição do arquivo no disco IMEDIATAMENTE APÓS `_open_verified_regular_file`
    # retornar o descritor validado, mas ANTES de `_stream_from_verified_fd` começar a ler os chunks.
    # Se o código usasse FileResponse(target_path), FileResponse abriria o novo arquivo no caminho `target_file`
    # e enviaria "TAMPERED_MALICIOUS_PAYLOAD". Como vinculamos ao descritor `fd` já aberto,
    # mesmo que o nome do arquivo seja desvinculado/renomeado e substituído por outro arquivo,
    # o cliente recebe exclusivamente "AUTHENTIC_VALIDATED_GLB_BYTES".
    orig_stream = routes_mod._stream_from_verified_fd
    def stream_after_tampering(fd: int, chunk_size: int = 64 * 1024):
        renamed_old = proj_dir / "model_old_unlinked.glb"
        try:
            # Em Windows e POSIX, um arquivo aberto pode ser renomeado e um novo arquivo criado no mesmo caminho!
            os.rename(str(target_file), str(renamed_old))
            target_file.write_bytes(b"TAMPERED_MALICIOUS_PAYLOAD")
        except OSError:
            pass
        try:
            yield from orig_stream(fd, chunk_size)
        finally:
            if renamed_old.exists():
                try:
                    os.replace(str(renamed_old), str(target_file))
                except OSError:
                    pass

    monkeypatch.setattr(routes_mod, "_stream_from_verified_fd", stream_after_tampering)

    res_ok = client.get(f"/api/v1/projects/{proj_id}/artifacts/model.glb")
    assert res_ok.status_code == 200
    assert res_ok.content == b"AUTHENTIC_VALIDATED_GLB_BYTES"

    # Parte B: Simular condição de corrida durante a própria abertura (inodes divergentes entre lstat inicial e fstat do fd)
    monkeypatch.setattr(routes_mod, "_stream_from_verified_fd", orig_stream)
    target_file.write_bytes(b"AUTHENTIC_VALIDATED_GLB_BYTES")

    orig_fstat = os.fstat
    def spoofed_fstat(fd):
        st = orig_fstat(fd)
        # Simular que o descritor aberto tem st_ino diferente do caminho verificado por lstat
        class FakeStat:
            st_mode = st.st_mode
            st_ino = st.st_ino + 999999
            st_dev = st.st_dev
            st_size = st.st_size
        return FakeStat()

    monkeypatch.setattr(os, "fstat", spoofed_fstat)
    res_race = client.get(f"/api/v1/projects/{proj_id}/artifacts/model.glb")
    assert res_race.status_code == 403

    res_race_legacy = client.get(f"/api/v1/files/download?path={proj_id}/model.glb")
    assert res_race_legacy.status_code == 403


def test_stream_from_verified_fd_closes_descriptor_only_once(isolated_storage_and_db, monkeypatch):
    """
    SEC-001 (Achado A): Verifica que `_stream_from_verified_fd` fecha o descritor `fd`
    uma única vez (via `os.fdopen(..., closefd=True)`) sem invocar `os.close(fd)` redundantemente
    no bloco `finally`, evitando o risco de fechar outro descritor caso o sistema operacional
    reutilize o mesmo inteiro `fd` concorrentemente.
    Também comprova que caso `os.fdopen` falhe antes de assumir a posse do descritor,
    o bloco `finally` executa `os.close(fd)` exatamente uma vez para evitar vazamento.
    """
    sample_file = settings.STORAGE_DIR / "fd_ownership_test.bin"
    sample_file.write_bytes(b"VERIFIED_STREAM_PAYLOAD")

    fd = os.open(str(sample_file), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    close_calls = []
    orig_close = os.close

    def tracked_close(target_fd):
        close_calls.append(target_fd)
        return orig_close(target_fd)

    monkeypatch.setattr(os, "close", tracked_close)

    chunks = list(routes_mod._stream_from_verified_fd(fd))
    assert b"".join(chunks) == b"VERIFIED_STREAM_PAYLOAD"
    # `os.fdopen(..., closefd=True)` fecha o descritor internamente em C ao sair do bloco `with`,
    # portanto `os.close(fd)` em Python NÃO pode ter sido chamado redundantemente no `finally`!
    assert close_calls == []

    # Caso de falha antes de `os.fdopen` assumir posse: `os.close(fd)` DEVE ser chamado exatamente 1 vez
    fd2 = os.open(str(sample_file), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    def failing_fdopen(*args, **kwargs):
        raise OSError("Simulated fdopen failure before ownership transfer")

    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    with pytest.raises(OSError, match="Simulated fdopen failure"):
        list(routes_mod._stream_from_verified_fd(fd2))

    assert close_calls == [fd2]

