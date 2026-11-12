import asyncio
import json
import uuid
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from backend.app.schemas.jobs import JobStatus
from backend.app.storage.database import SessionLocal, JobModel, ProjectModel
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter
from backend.app.config import settings

logger = logging.getLogger("ai_3d_studio.orchestrator")

def get_now():
    return datetime.now(timezone.utc)

class JobCancelledException(Exception):
    """Exceção interna disparada nos checkpoints cooperativos quando um job é cancelado."""
    pass

class JobOrchestrator:
    """
    Máquina de estados e executor assíncrono não-bloqueante para tarefas de modelagem e processamento.
    Estados: Pendente -> Preparando -> Em Execução -> Concluída / Falhou / Cancelada.
    Implementa (Bloco 2 / R2 / ASYNC-001):
    - Descarregamento de processamento CPU-bound (Trimesh/Shapely/ModelExporter) via `asyncio.to_thread`.
    - Limite explícito de concorrência por semáforo assíncrono (`MAX_CONCURRENT_JOBS = 2`).
    - Cancelamento cooperativo real via `threading.Event` integrado aos checkpoints do pipeline,
      diferenciando pedido de cancelamento (`cancel_requested` em metadata) do estado terminal `Cancelada`,
      preservando idempotência para tarefas já concluídas e descartando arquivos temporários/parciais.
    """

    MAX_CONCURRENT_JOBS: int = 2

    # Estados terminais imutáveis
    TERMINAL_STATUSES = {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED
    }

    # Transições válidas
    VALID_TRANSITIONS = {
        JobStatus.PENDING: [JobStatus.PREPARING, JobStatus.CANCELLED, JobStatus.FAILED],
        JobStatus.PREPARING: [JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED],
        JobStatus.RUNNING: [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
        JobStatus.COMPLETED: [],
        JobStatus.FAILED: [],
        JobStatus.CANCELLED: []
    }

    _running_tasks: Dict[str, asyncio.Task] = {}
    _cancellation_events: Dict[str, threading.Event] = {}
    _state_lock: threading.Lock = threading.Lock()
    _semaphore: Optional[asyncio.Semaphore] = None
    _semaphore_loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """
        Retorna um `asyncio.Semaphore(cls.MAX_CONCURRENT_JOBS)` vinculado ao event loop atual.
        Recria automaticamente se o event loop mudou (ex: entre testes ou reinicializações).
        """
        loop = asyncio.get_running_loop()
        if cls._semaphore is None or cls._semaphore_loop is not loop:
            cls._semaphore = asyncio.Semaphore(cls.MAX_CONCURRENT_JOBS)
            cls._semaphore_loop = loop
        return cls._semaphore

    @classmethod
    def validate_transition(cls, current: JobStatus, target: JobStatus):
        if target not in cls.VALID_TRANSITIONS.get(current, []):
            raise ValueError(f"Transição de estado inválida de '{current.value}' para '{target.value}'")

    @classmethod
    def create_job(cls, db: Session, project_id: str, operation_type: str, params: Dict[str, Any]) -> JobModel:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = JobModel(
            id=job_id,
            project_id=project_id,
            operation_type=operation_type,
            status=JobStatus.PENDING.value,
            params_json=json.dumps(params),
            created_at=get_now()
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        with cls._state_lock:
            cls._cancellation_events[job_id] = threading.Event()
        return job

    @classmethod
    def is_cancel_requested(cls, job_id: str) -> bool:
        """
        Verifica se o cancelamento foi sinalizado em memória (`threading.Event`)
        ou persistido no banco de dados (status `Cancelada` ou `cancel_requested` no metadata,
        ou se o projeto pai entrou em status `deleting`).
        """
        with cls._state_lock:
            ev = cls._cancellation_events.get(job_id)
            if ev is not None and ev.is_set():
                return True

        db = SessionLocal()
        try:
            job = db.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return True
            if job.status == JobStatus.CANCELLED.value:
                return True
            try:
                meta = json.loads(job.metadata_json or "{}")
                if isinstance(meta, dict) and meta.get("cancel_requested") is True:
                    return True
            except Exception:
                pass
            proj = db.query(ProjectModel).filter(ProjectModel.id == job.project_id).first()
            if not proj or proj.status == "deleting":
                return True
            return False
        finally:
            db.close()

    @classmethod
    def _cleanup_partial_files(cls, project_id: str, candidate_paths: Optional[List[Path]] = None):
        """
        Remove arquivos parciais/temporários gerados por uma tarefa cancelada ou interrompida,
        nunca tocando em artefatos já validados e registrados por tarefas concluídas anteriormente.
        """
        if candidate_paths:
            for p in candidate_paths:
                try:
                    if p and p.exists() and not p.is_dir():
                        p.unlink(missing_ok=True)
                except OSError:
                    pass

        project_dir = settings.STORAGE_DIR / project_id
        if project_dir.exists() and project_dir.is_dir():
            for item in project_dir.iterdir():
                if ".tmp." in item.name or item.name.endswith(".tmp"):
                    try:
                        item.unlink(missing_ok=True)
                    except OSError:
                        pass

    @classmethod
    def update_job_status(
        cls,
        job_id: str,
        target_status: JobStatus,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        result_files: Optional[list] = None,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Atualiza o estado do job no SQLite respeitando a máquina de estados e a idempotência:
        - Se o job já atingiu um estado terminal (`Concluída`, `Falhou`, `Cancelada`),
          não permite sobrescrevê-lo por outro estado conflitante (ex: cancelar um job já concluído,
          ou concluir um job que já foi cancelado).
        Retorna True se a atualização foi aplicada, False se ignorada por estado terminal prévio.
        """
        with cls._state_lock:
            db = SessionLocal()
            try:
                job = db.query(JobModel).filter(JobModel.id == job_id).first()
                if not job:
                    return False

                current_status = JobStatus(job.status)

                # Proteção de idempotência para estados terminais:
                # Uma tarefa já Concluída, Falhou ou Cancelada nunca muda para outro estado.
                if current_status in cls.TERMINAL_STATUSES and current_status != target_status:
                    return False

                if current_status != target_status:
                    cls.validate_transition(current_status, target_status)
                    job.status = target_status.value

                now = get_now()
                if target_status == JobStatus.RUNNING and not job.started_at:
                    job.started_at = now
                elif target_status in cls.TERMINAL_STATUSES and not job.completed_at:
                    job.completed_at = now

                if progress is not None:
                    job.progress = progress
                if error_message is not None:
                    job.error_message = error_message
                if result_files is not None:
                    job.result_files_json = json.dumps(result_files)
                if metadata is not None:
                    try:
                        existing_meta = json.loads(job.metadata_json or "{}")
                        if not isinstance(existing_meta, dict):
                            existing_meta = {}
                    except Exception:
                        existing_meta = {}
                    existing_meta.update(metadata)
                    job.metadata_json = json.dumps(existing_meta)

                db.commit()
                return True
            finally:
                db.close()

    @classmethod
    def cancel_job(cls, job_id: str, reason: str = "Cancelado pelo usuário.") -> bool:
        """
        Solicita e aplica o cancelamento cooperativo de uma tarefa (Task 2.2):
        - Se a tarefa já estiver em estado terminal (`Concluída` ou `Falhou`), mantém o estado final
          intacto (idempotência estrita) e retorna False.
        - Se já estiver `Cancelada`, mantém `Cancelada` de forma idempotente e retorna True.
        - Caso esteja `Pendente`, `Preparando` ou `Em Execução`:
          1. Sinaliza o `threading.Event` em `_cancellation_events[job_id]` para interromper imediatamente
             o worker no próximo checkpoint cooperativo.
          2. Registra `cancel_requested: True` e `cancel_requested_at` nos metadados e transita o status
             para `Cancelada` com `completed_at` preenchido.
          3. Cancela a `asyncio.Task` se ainda estiver aguardando semáforo/agendamento.
        """
        with cls._state_lock:
            ev = cls._cancellation_events.setdefault(job_id, threading.Event())
            ev.set()

            db = SessionLocal()
            try:
                job = db.query(JobModel).filter(JobModel.id == job_id).first()
                if not job:
                    return False

                current_status = JobStatus(job.status)
                if current_status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    # Não corrompe tarefa já finalizada
                    return False

                now = get_now()
                try:
                    meta = json.loads(job.metadata_json or "{}")
                    if not isinstance(meta, dict):
                        meta = {}
                except Exception:
                    meta = {}

                meta["cancel_requested"] = True
                meta.setdefault("cancel_requested_at", now.isoformat())

                if current_status != JobStatus.CANCELLED:
                    cls.validate_transition(current_status, JobStatus.CANCELLED)
                    job.status = JobStatus.CANCELLED.value
                    job.completed_at = now
                    job.error_message = reason

                job.metadata_json = json.dumps(meta)
                db.commit()
            finally:
                db.close()

            task = cls._running_tasks.get(job_id)
            if task is not None and not task.done():
                task.cancel()

        return True

    @classmethod
    def _execute_procedural_pipeline_sync(
        cls,
        job_id: str,
        project_id: str,
        params: Dict[str, Any],
        cancel_event: threading.Event
    ) -> Dict[str, Any]:
        """
        Worker síncrono executado fora do event loop principal via `asyncio.to_thread` (Task 2.1 / 2.2).
        Possui pontos de controle cooperativos (`check_cancel`) antes e depois de cada etapa CPU-bound:
        - Checkpoint 1: Antes da geração geométrica 2D/3D (`ProceduralGenerator.generate_by_params`).
        - Checkpoint 2: Após a geração do mesh e antes da inspeção geométrica.
        - Checkpoint 3: Antes e durante a exportação/validação atômica (`ModelExporter.export_and_validate`).
        - Checkpoint 4: Após a exportação, antes de autorizar a publicação no projeto/job.
        Se cancelado em qualquer ponto, limpa imediatamente quaisquer arquivos temporários ou parciais.
        """
        model_path: Optional[Path] = None

        def check_cancel():
            if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                cls._cleanup_partial_files(project_id, [model_path] if model_path else None)
                raise JobCancelledException("Execução interrompida por solicitação de cancelamento.")

        try:
            # Checkpoint 1: Pré-geração geométrica
            check_cancel()
            shape_type = str(params.get("shape_type", "box"))
            mesh = ProceduralGenerator.generate_by_params(shape_type, params)

            # Checkpoint 2: Pós-geração do mesh / pré-inspeção
            check_cancel()
            inspect_info = ProceduralGenerator.inspect_mesh(mesh)

            # Checkpoint 3: Preparação de diretório e exportação atômica validada
            check_cancel()
            project_dir = settings.STORAGE_DIR / project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            model_filename = f"{shape_type}_{uuid.uuid4().hex[:6]}.glb"
            model_path = project_dir / model_filename

            export_meta = ModelExporter.export_and_validate(
                mesh,
                model_path,
                fmt="glb",
                cancel_check=check_cancel
            )

            # Checkpoint 4: Pós-exportação, antes de publicar resultado
            check_cancel()

            return {
                "model_path": model_path,
                "rel_path": str(model_path.relative_to(settings.BASE_DIR)),
                "inspect_info": inspect_info,
                "export_meta": export_meta
            }
        except JobCancelledException:
            cls._cleanup_partial_files(project_id, [model_path] if model_path else None)
            raise
        except BaseException:
            cls._cleanup_partial_files(project_id, [model_path] if model_path else None)
            raise

    @classmethod
    async def run_procedural_job_async(cls, job_id: str, project_id: str, params: Dict[str, Any]):
        """
        Orquestra o ciclo de vida assíncrono do job respeitando o semáforo de concorrência
        (`MAX_CONCURRENT_JOBS = 2`) e isolando o processamento pesado em worker thread (`asyncio.to_thread`).
        """
        with cls._state_lock:
            cancel_event = cls._cancellation_events.setdefault(job_id, threading.Event())

        semaphore = cls._get_semaphore()
        model_path: Optional[Path] = None

        try:
            # Verificar cancelamento antes mesmo de adquirir o semáforo
            if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                cls.update_job_status(
                    job_id,
                    JobStatus.CANCELLED,
                    error_message="Cancelado antes do início da execução.",
                    metadata={"cancel_acknowledged": True}
                )
                return

            async with semaphore:
                if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                    cls.update_job_status(
                        job_id,
                        JobStatus.CANCELLED,
                        error_message="Cancelado na fila antes da preparação.",
                        metadata={"cancel_acknowledged": True}
                    )
                    return

                if not cls.update_job_status(job_id, JobStatus.PREPARING, progress=0.1):
                    return

                # Ceder controle brevemente ao event loop para permitir observação do estado PREPARING e consultas HTTP
                await asyncio.sleep(0.01)

                if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                    cls.update_job_status(
                        job_id,
                        JobStatus.CANCELLED,
                        error_message="Cancelado durante a preparação.",
                        metadata={"cancel_acknowledged": True}
                    )
                    return

                if not cls.update_job_status(job_id, JobStatus.RUNNING, progress=0.3):
                    return

                # Executar o pipeline pesado em worker thread fora do event loop principal
                worker_result = await asyncio.to_thread(
                    cls._execute_procedural_pipeline_sync,
                    job_id,
                    project_id,
                    params,
                    cancel_event
                )
                model_path = worker_result["model_path"]
                rel_path = worker_result["rel_path"]
                inspect_info = worker_result["inspect_info"]
                export_meta = worker_result["export_meta"]

                # Verificação final antes de publicar o resultado no Projeto e marcar como Concluída
                if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                    cls._cleanup_partial_files(project_id, [model_path])
                    cls.update_job_status(
                        job_id,
                        JobStatus.CANCELLED,
                        error_message="Cancelado antes da publicação do artefato.",
                        metadata={"cancel_acknowledged": True}
                    )
                    return

                # Atualizar projeto com o modelo ativo apenas se o projeto continuar ativo
                with cls._state_lock:
                    db = SessionLocal()
                    try:
                        job_check = db.query(JobModel).filter(JobModel.id == job_id).first()
                        proj = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
                        if (
                            not job_check
                            or job_check.status == JobStatus.CANCELLED.value
                            or not proj
                            or proj.status == "deleting"
                        ):
                            cls._cleanup_partial_files(project_id, [model_path])
                            if job_check and job_check.status != JobStatus.CANCELLED.value:
                                job_check.status = JobStatus.CANCELLED.value
                                job_check.completed_at = get_now()
                                job_check.error_message = "Cancelado pois o projeto entrou em exclusão."
                                db.commit()
                            return

                        proj.active_model_path = rel_path
                        proj.parameters_json = json.dumps(params)
                        proj.updated_at = get_now()
                        db.commit()
                    finally:
                        db.close()

                completed_ok = cls.update_job_status(
                    job_id,
                    JobStatus.COMPLETED,
                    progress=1.0,
                    result_files=[rel_path],
                    metadata={"inspection": inspect_info, "export": export_meta}
                )
                if not completed_ok:
                    # Caso tenha sido cancelado concorrentemente, não deixar arquivo órfão não registrado
                    cls._cleanup_partial_files(project_id, [model_path])

        except (asyncio.CancelledError, JobCancelledException):
            cls._cleanup_partial_files(project_id, [model_path] if model_path else None)
            cls.update_job_status(
                job_id,
                JobStatus.CANCELLED,
                error_message="Execução cancelada cooperativamente.",
                metadata={"cancel_acknowledged": True}
            )
        except Exception as e:
            cls._cleanup_partial_files(project_id, [model_path] if model_path else None)
            cls.update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        finally:
            with cls._state_lock:
                cls._running_tasks.pop(job_id, None)
                cls._cancellation_events.pop(job_id, None)

    @classmethod
    def dispatch_job(cls, job_id: str, project_id: str, params: Dict[str, Any]):
        with cls._state_lock:
            cls._cancellation_events.setdefault(job_id, threading.Event())
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(cls.run_procedural_job_async(job_id, project_id, params))
            with cls._state_lock:
                cls._running_tasks[job_id] = task
            return task
        except RuntimeError:
            # Sem loop ativo (ex: chamadas síncronas diretas via TestClient síncrono)
            return asyncio.run(cls.run_procedural_job_async(job_id, project_id, params))

    @classmethod
    async def shutdown_active_jobs(cls, timeout: float = 2.0):
        """
        Sinaliza cancelamento cooperativo e aguarda o encerramento limpo das tasks ativas
        durante o shutdown do servidor FastAPI, evitando threads ou tasks órfãs.
        """
        with cls._state_lock:
            for ev in cls._cancellation_events.values():
                ev.set()
            tasks = [t for t in cls._running_tasks.values() if not t.done()]
            for t in tasks:
                t.cancel()

        if tasks:
            try:
                await asyncio.wait(tasks, timeout=timeout)
            except Exception:
                pass
