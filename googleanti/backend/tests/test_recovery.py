import os
import json
import uuid
import asyncio
import threading
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.app.main import (
    app,
    reconcile_storage_and_quarantine,
    reconcile_interrupted_jobs
)
import backend.app.main as main_mod
import backend.app.storage.database as db_mod
import backend.app.jobs.orchestrator as orch_mod
from backend.app.config import settings
from backend.app.storage.database import Base, get_db, ProjectModel, JobModel
from backend.app.schemas.jobs import JobStatus
from backend.app.jobs.orchestrator import JobOrchestrator
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter

@pytest.fixture(autouse=True)
def isolated_recovery_env(tmp_path, monkeypatch):
    """
    Fixture autouse que isola completamente BASE_DIR, STORAGE_DIR, QUARANTINE_DIR e o banco SQLite
    em um diretório temporário exclusivo (tmp_path) para cada teste do Bloco 2.
    """
    test_base_dir = tmp_path / "workspace"
    test_storage_dir = test_base_dir / "projects"
    test_quarantine_dir = test_storage_dir / ".quarantine"
    test_models_dir = test_base_dir / "models"
    test_db_path = test_base_dir / "test_recovery.db"

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
    monkeypatch.setattr(orch_mod, "SessionLocal", TestingSessionLocal)

    # Resetar estado interno do JobOrchestrator entre testes
    JobOrchestrator._running_tasks.clear()
    JobOrchestrator._cancellation_events.clear()
    JobOrchestrator._semaphore = None
    JobOrchestrator._semaphore_loop = None

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

@pytest.mark.anyio
async def test_event_loop_non_blocking_during_heavy_cpu_job(isolated_recovery_env, monkeypatch):
    """
    Task 2.1: Comprova que o trabalho CPU-bound roda em worker thread (`asyncio.to_thread`)
    sem bloquear o event loop principal.
    Enquanto a geração procedural está bloqueada em uma barreira de sincronização na worker thread,
    o event loop principal continua processando coroutines concorrentes imediatamente.
    """
    SessionLocal = isolated_recovery_env
    db = SessionLocal()
    proj = ProjectModel(id="proj-nonblock", name="Non-Blocking Project", status="active")
    db.add(proj)
    db.commit()
    job = JobOrchestrator.create_job(db, proj.id, "procedural_generation", {"shape_type": "box"})
    job_id = job.id
    db.close()

    worker_entered = threading.Event()
    release_worker = threading.Event()
    main_thread_id = threading.get_ident()
    worker_thread_ids = []

    orig_generate = ProceduralGenerator.generate_by_params
    def controlled_generate(shape_type, params):
        worker_thread_ids.append(threading.get_ident())
        worker_entered.set()
        release_worker.wait(timeout=5.0)
        return orig_generate(shape_type, params)

    monkeypatch.setattr(ProceduralGenerator, "generate_by_params", controlled_generate)

    task = asyncio.create_task(JobOrchestrator.run_procedural_job_async(job_id, "proj-nonblock", {"shape_type": "box"}))

    # Aguardar de forma não-bloqueante até que a worker thread entre em `generate_by_params`
    while not worker_entered.is_set():
        await asyncio.sleep(0.005)

    # Comprovar que a worker thread NÃO é a thread do event loop principal
    assert len(worker_thread_ids) == 1
    assert worker_thread_ids[0] != main_thread_id

    # Comprovar que o event loop responde imediatamente enquanto a worker thread está bloqueada em `release_worker.wait`
    ping_completed = False
    async def concurrent_ping():
        nonlocal ping_completed
        await asyncio.sleep(0.001)
        ping_completed = True

    await asyncio.wait_for(concurrent_ping(), timeout=0.5)
    assert ping_completed is True

    # Liberar worker e aguardar conclusão limpa
    release_worker.set()
    await task

    db = SessionLocal()
    finished = db.query(JobModel).filter(JobModel.id == job_id).first()
    assert finished.status == JobStatus.COMPLETED.value
    db.close()

@pytest.mark.anyio
async def test_concurrency_semaphore_limits_active_workers_to_max(isolated_recovery_env, monkeypatch):
    """
    Task 2.1: Verifica de forma determinística que o semáforo (`MAX_CONCURRENT_JOBS = 2`)
    impede que mais de 2 jobs executem simultaneamente em worker threads.
    """
    SessionLocal = isolated_recovery_env
    db = SessionLocal()
    proj = ProjectModel(id="proj-sem", name="Semaphore Test Project", status="active")
    db.add(proj)
    db.commit()

    jobs = [
        JobOrchestrator.create_job(db, proj.id, "procedural_generation", {"shape_type": "box"})
        for _ in range(4)
    ]
    job_ids = [j.id for j in jobs]
    db.close()

    lock = threading.Lock()
    active_count = 0
    max_observed = 0
    two_workers_running = threading.Event()
    release_gate = threading.Event()

    orig_generate = ProceduralGenerator.generate_by_params
    def gated_generate(shape_type, params):
        nonlocal active_count, max_observed
        with lock:
            active_count += 1
            if active_count > max_observed:
                max_observed = active_count
            if active_count == JobOrchestrator.MAX_CONCURRENT_JOBS:
                two_workers_running.set()
        try:
            release_gate.wait(timeout=5.0)
            return orig_generate(shape_type, params)
        finally:
            with lock:
                active_count -= 1

    monkeypatch.setattr(ProceduralGenerator, "generate_by_params", gated_generate)

    tasks = [
        asyncio.create_task(JobOrchestrator.run_procedural_job_async(jid, "proj-sem", {"shape_type": "box"}))
        for jid in job_ids
    ]

    while not two_workers_running.is_set():
        await asyncio.sleep(0.005)

    # Dar oportunidade ao event loop para tentar agendar o 3º e 4º jobs (devem ficar retidos no semáforo)
    await asyncio.sleep(0.03)
    with lock:
        assert active_count == 2
        assert max_observed == 2

    # Verificar no banco que apenas 2 estão em RUNNING/PREPARING e os outros 2 ainda estão PENDING
    db = SessionLocal()
    statuses = [db.query(JobModel).filter(JobModel.id == jid).first().status for jid in job_ids]
    db.close()
    assert statuses.count(JobStatus.RUNNING.value) == 2
    assert statuses.count(JobStatus.PENDING.value) == 2

    # Liberar todas as workers
    release_gate.set()
    await asyncio.gather(*tasks)

    assert max_observed == JobOrchestrator.MAX_CONCURRENT_JOBS
    db = SessionLocal()
    final_statuses = [db.query(JobModel).filter(JobModel.id == jid).first().status for jid in job_ids]
    db.close()
    assert all(s == JobStatus.COMPLETED.value for s in final_statuses)

@pytest.mark.anyio
async def test_cooperative_cancellation_during_generation_and_export_cleans_partials(isolated_recovery_env, monkeypatch):
    """
    Task 2.2: Valida o cancelamento cooperativo em diferentes fases:
    1. Fase de geração geométrica: cancelar enquanto a worker thread está gerando a malha aborta antes da exportação,
       marca o job como 'Cancelada' com `completed_at` preenchido, não publica `result_files` nem `active_model_path`.
    2. Fase de exportação: cancelar durante `ModelExporter.export_and_validate` (após o arquivo `.tmp.glb` ter sido
       escrito no disco, mas antes da promoção final) remove imediatamente o arquivo temporário parcial e preserva
       qualquer modelo ativo anterior do projeto.
    """
    SessionLocal = isolated_recovery_env
    db = SessionLocal()
    proj = ProjectModel(
        id="proj-cancel",
        name="Cancel Phases Project",
        status="active",
        active_model_path="projects/proj-cancel/previous_valid.glb"
    )
    db.add(proj)
    db.commit()

    # Criar arquivo válido anterior que NÃO deve ser tocado pelo cancelamento do novo job
    proj_dir = settings.STORAGE_DIR / "proj-cancel"
    proj_dir.mkdir(parents=True, exist_ok=True)
    prev_file = proj_dir / "previous_valid.glb"
    prev_file.write_bytes(b"PREVIOUS_VALID_GLB")

    job1 = JobOrchestrator.create_job(db, proj.id, "procedural_generation", {"shape_type": "box"})
    job1_id = job1.id
    job2 = JobOrchestrator.create_job(db, proj.id, "procedural_generation", {"shape_type": "cylinder"})
    job2_id = job2.id
    db.close()

    # --- Fase 1: Cancelamento durante `generate_by_params` ---
    in_gen = threading.Event()
    resume_gen = threading.Event()
    orig_gen = ProceduralGenerator.generate_by_params

    def hooked_gen(shape_type, params):
        in_gen.set()
        resume_gen.wait(timeout=5.0)
        return orig_gen(shape_type, params)

    monkeypatch.setattr(ProceduralGenerator, "generate_by_params", hooked_gen)
    task1 = asyncio.create_task(JobOrchestrator.run_procedural_job_async(job1_id, "proj-cancel", {"shape_type": "box"}))

    while not in_gen.is_set():
        await asyncio.sleep(0.005)

    # Solicitar cancelamento enquanto a thread está dentro de `generate_by_params`
    assert JobOrchestrator.cancel_job(job1_id) is True
    resume_gen.set()
    await task1

    db = SessionLocal()
    j1_db = db.query(JobModel).filter(JobModel.id == job1_id).first()
    assert j1_db.status == JobStatus.CANCELLED.value
    assert j1_db.completed_at is not None
    assert json.loads(j1_db.result_files_json) == []
    meta1 = json.loads(j1_db.metadata_json)
    assert meta1.get("cancel_requested") is True
    db.close()

    # --- Fase 2: Cancelamento no meio da exportação (com arquivo .tmp.glb em disco) ---
    monkeypatch.setattr(ProceduralGenerator, "generate_by_params", orig_gen)

    # Criar um arquivo temporário parcial simulado na pasta do projeto e cancelar no checkpoint do exporter
    partial_tmp = proj_dir / ".cylinder_partial.tmp.glb"
    partial_tmp.write_bytes(b"PARTIAL_UNVALIDATED_BYTES")

    orig_export = ModelExporter.export_and_validate
    def cancel_inside_exporter(cls_or_mesh, output_path, fmt="glb", cancel_check=None):
        # Disparar o cancelamento exatamente durante a exportação antes do último cancel_check
        JobOrchestrator.cancel_job(job2_id)
        return orig_export(cls_or_mesh, output_path, fmt=fmt, cancel_check=cancel_check)

    monkeypatch.setattr(ModelExporter, "export_and_validate", cancel_inside_exporter)
    await JobOrchestrator.run_procedural_job_async(job2_id, "proj-cancel", {"shape_type": "cylinder"})

    # O arquivo temporário parcial e qualquer novo .glb não validado devem ter sido removidos!
    assert not partial_tmp.exists()
    remaining_files = [p.name for p in proj_dir.iterdir()]
    assert remaining_files == ["previous_valid.glb"]

    # O projeto deve continuar apontando para o modelo válido anterior (`previous_valid.glb`)
    db = SessionLocal()
    j2_db = db.query(JobModel).filter(JobModel.id == job2_id).first()
    proj_db = db.query(ProjectModel).filter(ProjectModel.id == "proj-cancel").first()
    assert j2_db.status == JobStatus.CANCELLED.value
    assert json.loads(j2_db.result_files_json) == []
    assert proj_db.active_model_path == "projects/proj-cancel/previous_valid.glb"
    db.close()

@pytest.mark.anyio
async def test_cancel_already_completed_job_is_idempotent_and_preserves_completed(isolated_recovery_env):
    """
    Task 2.2 (Scenario: Cancelamento solicitado para tarefa já finalizada):
    Quando o cancelamento é solicitado para uma tarefa que já completou seu processamento,
    o sistema mantém o estado final `Concluída` sem corromper o histórico ou os artefatos gerados.
    """
    SessionLocal = isolated_recovery_env
    db = SessionLocal()
    proj = ProjectModel(id="proj-idem", name="Idempotent Cancel Project", status="active")
    db.add(proj)
    db.commit()
    job = JobOrchestrator.create_job(db, proj.id, "procedural_generation", {"shape_type": "box"})
    job_id = job.id
    db.close()

    await JobOrchestrator.run_procedural_job_async(job_id, "proj-idem", {"shape_type": "box"})

    # Agora solicitar cancelamento via API e via JobOrchestrator após a tarefa já estar Concluída
    cancel_res = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel_res.status_code == 200

    db = SessionLocal()
    job_after = db.query(JobModel).filter(JobModel.id == job_id).first()
    assert job_after.status == JobStatus.COMPLETED.value
    result_files = json.loads(job_after.result_files_json)
    assert len(result_files) == 1
    assert (settings.BASE_DIR / result_files[0]).exists()
    db.close()

def test_reconcile_interrupted_jobs_on_startup_and_preserve_completed_artifacts(isolated_recovery_env):
    """
    Task 2.3: Verifica a reconciliação de tarefas órfãs na inicialização do backend:
    - Tarefas em `Pendente`, `Preparando` e `Em Execução` são transitadas deterministicamente para `Cancelada`
      com `completed_at` preenchido, `error_message` explicativo e metadado `reconciled_on_startup: True`.
    - Tarefas já `Concluída` ou `Falhou` permanecem intactas.
    - Arquivos temporários parciais (`.tmp.glb`) são removidos, enquanto artefatos válidos (`.glb`) são preservados.
    - Execuções repetidas de `reconcile_interrupted_jobs()` são idempotentes.
    """
    SessionLocal = isolated_recovery_env
    proj_id = "proj-reboot"
    proj_dir = settings.STORAGE_DIR / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    valid_artifact = proj_dir / "box_valid.glb"
    valid_artifact.write_bytes(b"VALID_COMPLETED_MODEL")
    orphan_tmp = proj_dir / ".gear_interrupted.tmp.glb"
    orphan_tmp.write_bytes(b"INCOMPLETE_CRASH_BYTES")

    db = SessionLocal()
    db.add(ProjectModel(id=proj_id, name="Reboot Project", status="active", active_model_path=f"projects/{proj_id}/box_valid.glb"))
    j_pending = JobModel(id="job-pend", project_id=proj_id, operation_type="procedural_generation", status=JobStatus.PENDING.value)
    j_prep = JobModel(id="job-prep", project_id=proj_id, operation_type="procedural_generation", status=JobStatus.PREPARING.value)
    j_run = JobModel(id="job-run", project_id=proj_id, operation_type="procedural_generation", status=JobStatus.RUNNING.value)
    j_done = JobModel(
        id="job-done",
        project_id=proj_id,
        operation_type="procedural_generation",
        status=JobStatus.COMPLETED.value,
        result_files_json=json.dumps([f"projects/{proj_id}/box_valid.glb"])
    )
    db.add_all([j_pending, j_prep, j_run, j_done])
    db.commit()
    db.close()

    # Executar reconciliação múltiplas vezes para comprovar idempotência
    reconcile_interrupted_jobs()
    reconcile_interrupted_jobs()

    db = SessionLocal()
    for jid, expected_prev in [
        ("job-pend", JobStatus.PENDING.value),
        ("job-prep", JobStatus.PREPARING.value),
        ("job-run", JobStatus.RUNNING.value),
    ]:
        j = db.query(JobModel).filter(JobModel.id == jid).first()
        assert j.status == JobStatus.CANCELLED.value
        assert j.completed_at is not None
        assert "reinicialização" in (j.error_message or "")
        meta = json.loads(j.metadata_json)
        assert meta["reconciled_on_startup"] is True
        assert meta["interrupted_from_status"] == expected_prev

    # A tarefa concluída e seu artefato válido devem estar 100% preservados
    j_completed = db.query(JobModel).filter(JobModel.id == "job-done").first()
    assert j_completed.status == JobStatus.COMPLETED.value
    db.close()

    assert valid_artifact.exists()
    assert valid_artifact.read_bytes() == b"VALID_COMPLETED_MODEL"
    assert not orphan_tmp.exists()

@pytest.mark.anyio
async def test_project_deletion_while_job_running_in_threadpool_prevents_resurrection(isolated_recovery_env, monkeypatch):
    """
    Task 2.4 (Integração Bloco 1 + Bloco 2):
    Verifica que se um projeto for excluído (`DELETE /projects/{id}`) enquanto uma worker thread
    está executando um job daquele projeto:
    - O job ativo recebe sinal de cancelamento cooperativo.
    - A worker thread aborta no próximo checkpoint e limpa qualquer arquivo parcial,
      nunca recriando a pasta `STORAGE_DIR/{project_id}` após a exclusão do projeto!
    """
    SessionLocal = isolated_recovery_env
    res_proj = client.post("/api/v1/projects", json={"name": "Delete During Active Thread Job"})
    proj_id = res_proj.json()["id"]

    db = SessionLocal()
    job = JobOrchestrator.create_job(db, proj_id, "procedural_generation", {"shape_type": "box"})
    job_id = job.id
    db.close()

    worker_started = threading.Event()
    allow_worker_continue = threading.Event()
    orig_gen = ProceduralGenerator.generate_by_params

    def slow_gen(shape_type, params):
        worker_started.set()
        allow_worker_continue.wait(timeout=5.0)
        return orig_gen(shape_type, params)

    monkeypatch.setattr(ProceduralGenerator, "generate_by_params", slow_gen)

    job_task = asyncio.create_task(JobOrchestrator.run_procedural_job_async(job_id, proj_id, {"shape_type": "box"}))

    while not worker_started.is_set():
        await asyncio.sleep(0.005)

    # Executar DELETE /projects/{proj_id} enquanto a worker thread está em execução
    del_res = client.delete(f"/api/v1/projects/{proj_id}")
    assert del_res.status_code == 200

    # Liberar a worker thread e aguardar seu término
    allow_worker_continue.set()
    await job_task

    # A pasta do projeto NÃO pode ter sido recriada pela worker thread!
    assert not (settings.STORAGE_DIR / proj_id).exists()
