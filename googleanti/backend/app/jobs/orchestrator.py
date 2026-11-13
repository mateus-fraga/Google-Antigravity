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
from backend.app.procedural.text_to_3d import TextTo3DGenerator
from backend.app.procedural.image_to_3d import ImageTo3DGenerator
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
    _main_loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def set_main_loop(cls, loop: Optional[asyncio.AbstractEventLoop]):
        """
        Registra o event loop principal da aplicação FastAPI (no startup do lifespan)
        para garantir despacho assíncrono não-bloqueante e semáforo compartilhado.
        """
        with cls._state_lock:
            cls._main_loop = loop

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        """
        Retorna um `asyncio.Semaphore(cls.MAX_CONCURRENT_JOBS)` vinculado ao event loop atual.
        Recria automaticamente se o event loop mudou (ex: entre testes ou reinicializações).
        """
        loop = asyncio.get_running_loop()
        with cls._state_lock:
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
    def _cleanup_partial_files(
        cls,
        project_id: str,
        candidate_paths: Optional[List[Path]] = None,
        job_id: Optional[str] = None,
        sweep_all_tmp: bool = False
    ):
        """
        Remove arquivos parciais/temporários gerados por uma tarefa cancelada ou interrompida,
        nunca tocando em artefatos já validados e registrados por tarefas concluídas anteriormente
        nem nos arquivos temporários ativos de outras tarefas concorrentes do mesmo projeto (Achado C).
        - Quando `job_id` é informado (cancelamento/falha em runtime), remove apenas os arquivos em
          `candidate_paths` e temporários cujo nome contenha `_{job_id}_`.
        - A varredura ampla (`sweep_all_tmp=True`) só é executada na reconciliação de inicialização
          (`reconcile_interrupted_jobs`), quando garantidamente não há tarefas em execução.
        """
        if candidate_paths:
            for p in candidate_paths:
                try:
                    if p and p.exists() and not p.is_dir() and not p.is_symlink():
                        p.unlink(missing_ok=True)
                except OSError:
                    pass

        project_dir = settings.STORAGE_DIR / project_id
        if project_dir.exists() and project_dir.is_dir() and not project_dir.is_symlink():
            for item in project_dir.iterdir():
                if ".tmp." in item.name or item.name.endswith(".tmp"):
                    if sweep_all_tmp or (job_id and f"_{job_id}_" in item.name):
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
                try:
                    t_loop = task.get_loop()
                    if t_loop.is_running():
                        t_loop.call_soon_threadsafe(task.cancel)
                    else:
                        task.cancel()
                except Exception:
                    task.cancel()

        return True

    @classmethod
    def _execute_procedural_pipeline_sync(
        cls,
        job_id: str,
        project_id: str,
        params: Dict[str, Any],
        cancel_event: threading.Event,
        operation_type: str = "procedural_generation"
    ) -> Dict[str, Any]:
        """
        Worker síncrono executado fora do event loop principal via `asyncio.to_thread` (Task 2.1 / 2.2 / 6.4).
        Suporta `procedural_generation` e `text_to_3d`.
        Possui pontos de controle cooperativos (`check_cancel`) antes e depois de cada etapa CPU-bound:
        - Checkpoint 1: Antes da geração geométrica 2D/3D (`ProceduralGenerator` / `TextTo3DGenerator`).
        - Checkpoint 2: Após a geração do mesh e antes da inspeção geométrica.
        - Checkpoint 3: Antes e durante a exportação/validação atômica (`ModelExporter.export_and_validate`).
        - Checkpoint 4: Após a exportação, antes de autorizar a publicação no projeto/job.
        Se cancelado em qualquer ponto, limpa imediatamente quaisquer arquivos temporários ou parciais.
        """
        model_path: Optional[Path] = None
        semantic_metadata: Optional[Dict[str, Any]] = None

        def check_cancel():
            if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                cls._cleanup_partial_files(project_id, [model_path] if model_path else None, job_id=job_id)
                raise JobCancelledException("Execução interrompida por solicitação de cancelamento.")

        try:
            # Checkpoint 1: Pré-geração geométrica
            check_cancel()
            if operation_type == "image_to_3d" or ("reference_image_filename" in params and "shape_type" not in params):
                ref_filename = str(params.get("reference_image_filename") or params.get("image_filename") or "").strip()
                if not ref_filename or ".." in ref_filename or "/" in ref_filename or "\\" in ref_filename:
                    raise ValueError("Nome de imagem de referência inválido.")
                project_dir_check = settings.STORAGE_DIR / project_id
                image_path = project_dir_check / ref_filename
                if not image_path.exists() or not image_path.is_file() or image_path.is_symlink():
                    raise ValueError(f"Imagem de referência '{ref_filename}' não encontrada no projeto {project_id}.")
                mode = str(params.get("mode", "silhouette")).strip().lower()
                if mode == "heightmap":
                    base_t = float(params.get("base_thickness", 0.05))
                    relief_d = float(params.get("relief_depth", 0.15))
                    mesh = ImageTo3DGenerator.generate_from_heightmap(
                        image_path=image_path,
                        base_thickness=base_t,
                        relief_depth=relief_d,
                        cancel_check=check_cancel,
                    )
                    semantic_metadata = {
                        "image_to_3d_mode": "heightmap",
                        "reference_image_filename": ref_filename,
                        "base_thickness": base_t,
                        "relief_depth": relief_d,
                    }
                else:
                    thick = float(params.get("thickness", 0.1))
                    rscale = float(params.get("resolution_scale", 1.0))
                    mesh = ImageTo3DGenerator.generate_from_silhouette(
                        image_path=image_path,
                        thickness=thick,
                        resolution_scale=rscale,
                        cancel_check=check_cancel,
                    )
                    semantic_metadata = {
                        "image_to_3d_mode": "silhouette",
                        "reference_image_filename": ref_filename,
                        "thickness": thick,
                        "resolution_scale": rscale,
                    }
                shape_type = f"img3d_{mode}"
            elif operation_type == "text_to_3d" or ("prompt" in params and "shape_type" not in params):
                prompt_text = str(params.get("prompt", ""))
                ir, semantic_metadata = TextTo3DGenerator.parse_prompt_to_ir(prompt_text)
                check_cancel()
                mesh = ProceduralGenerator.generate_from_ir(ir, align_to_ground=True)
                shape_type = f"text3d_{semantic_metadata.get('parsed_intent', 'object')}"
            else:
                shape_type = str(params.get("shape_type", "box"))
                mesh = ProceduralGenerator.generate_by_params(shape_type, params)

            # Checkpoint 2: Pós-geração do mesh / pré-inspeção
            check_cancel()
            inspect_info = ProceduralGenerator.inspect_mesh(mesh)

            # Checkpoint 3: Preparação de diretório e exportação atômica validada
            check_cancel()
            project_dir = settings.STORAGE_DIR / project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            base_stem = f"{shape_type}_{uuid.uuid4().hex[:6]}"
            model_filename = f"{base_stem}.glb"
            model_path = project_dir / model_filename
            candidate_files = [model_path]

            export_meta = ModelExporter.export_and_validate(
                mesh,
                model_path,
                fmt="glb",
                cancel_check=check_cancel,
                job_id=job_id
            )

            # Checkpoint 4: Pós-exportação, antes de publicar resultado
            check_cancel()

            rel_glb = str(model_path.relative_to(settings.BASE_DIR))

            return {
                "model_path": model_path,
                "candidate_files": candidate_files,
                "rel_path": rel_glb,
                "result_files": [rel_glb],
                "inspect_info": inspect_info,
                "export_meta": export_meta,
                "semantic_metadata": semantic_metadata,
            }
        except JobCancelledException:
            cls._cleanup_partial_files(project_id, locals().get("candidate_files") or ([model_path] if model_path else None), job_id=job_id)
            raise
        except BaseException:
            cls._cleanup_partial_files(project_id, locals().get("candidate_files") or ([model_path] if model_path else None), job_id=job_id)
            raise

    @classmethod
    async def run_procedural_job_async(
        cls,
        job_id: str,
        project_id: str,
        params: Dict[str, Any],
        operation_type: Optional[str] = None
    ):
        """
        Orquestra o ciclo de vida assíncrono do job respeitando o semáforo de concorrência
        (`MAX_CONCURRENT_JOBS = 2`) e isolando o processamento pesado em worker thread (`asyncio.to_thread`).
        """
        with cls._state_lock:
            cancel_event = cls._cancellation_events.setdefault(job_id, threading.Event())

        if not operation_type:
            db_op = SessionLocal()
            try:
                j_row = db_op.query(JobModel).filter(JobModel.id == job_id).first()
                if j_row and j_row.operation_type:
                    operation_type = j_row.operation_type
            except Exception:
                pass
            finally:
                db_op.close()
        effective_op = operation_type or "procedural_generation"

        semaphore = cls._get_semaphore()
        model_path: Optional[Path] = None
        candidate_files: Optional[List[Path]] = None

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
                    cancel_event,
                    effective_op
                )
                model_path = worker_result["model_path"]
                candidate_files = worker_result.get("candidate_files", [model_path])
                rel_path = worker_result["rel_path"]
                result_files_list = worker_result.get("result_files", [rel_path])
                inspect_info = worker_result["inspect_info"]
                export_meta = worker_result["export_meta"]
                semantic_meta = worker_result.get("semantic_metadata")

                # Verificação final antes de publicar o resultado no Projeto e marcar como Concluída
                if cancel_event.is_set() or cls.is_cancel_requested(job_id):
                    cls._cleanup_partial_files(project_id, candidate_files, job_id=job_id)
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
                            cls._cleanup_partial_files(project_id, candidate_files, job_id=job_id)
                            if job_check and job_check.status != JobStatus.CANCELLED.value:
                                job_check.status = JobStatus.CANCELLED.value
                                job_check.completed_at = get_now()
                                job_check.error_message = "Cancelado pois o projeto entrou em exclusão."
                                db.commit()
                            return

                        proj.active_model_path = rel_path
                        try:
                            existing_proj_params = json.loads(proj.parameters_json or "{}")
                            if not isinstance(existing_proj_params, dict):
                                existing_proj_params = {}
                        except Exception:
                            existing_proj_params = {}
                        enriched_params = dict(existing_proj_params)
                        enriched_params.update(params)
                        enriched_params["coordinate_system"] = inspect_info.get("coordinate_system", "Y-up")
                        enriched_params["geometry_schema_version"] = inspect_info.get("geometry_schema_version", 2)
                        if semantic_meta:
                            enriched_params.update(semantic_meta)
                        proj.parameters_json = json.dumps(enriched_params)
                        proj.updated_at = get_now()
                        db.commit()
                    finally:
                        db.close()

                final_meta: Dict[str, Any] = {
                    "coordinate_system": inspect_info.get("coordinate_system", "Y-up"),
                    "geometry_schema_version": inspect_info.get("geometry_schema_version", 2),
                    "inspection": inspect_info,
                    "export": export_meta,
                }
                if semantic_meta:
                    final_meta.update(semantic_meta)
                    final_meta["text_to_3d"] = semantic_meta

                completed_ok = cls.update_job_status(
                    job_id,
                    JobStatus.COMPLETED,
                    progress=1.0,
                    result_files=result_files_list,
                    metadata=final_meta
                )
                if not completed_ok:
                    # Caso tenha sido cancelado concorrentemente, não deixar arquivo órfão não registrado
                    cls._cleanup_partial_files(project_id, candidate_files, job_id=job_id)

        except (asyncio.CancelledError, JobCancelledException):
            cls._cleanup_partial_files(project_id, candidate_files or ([model_path] if model_path else None), job_id=job_id)
            cls.update_job_status(
                job_id,
                JobStatus.CANCELLED,
                error_message="Execução cancelada cooperativamente.",
                metadata={"cancel_acknowledged": True}
            )
        except Exception as e:
            cls._cleanup_partial_files(project_id, candidate_files or ([model_path] if model_path else None), job_id=job_id)
            cls.update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        finally:
            with cls._state_lock:
                cls._running_tasks.pop(job_id, None)
                cls._cancellation_events.pop(job_id, None)

    @classmethod
    def get_active_task(cls, job_id: str) -> Optional[asyncio.Task]:
        with cls._state_lock:
            return cls._running_tasks.get(job_id)

    @classmethod
    def _ensure_background_loop(cls) -> asyncio.AbstractEventLoop:
        """
        Garante a existência de um event loop em background persistente quando a aplicação
        é invocada sem lifespan ativo (ex: `TestClient(app)` instanciado sem bloco `with`),
        evitando que o portal efêmero do TestClient cancele a task ao encerrar a requisição `POST /jobs`.
        Quando o servidor FastAPI real está rodando (ou `with TestClient(app):`), `_main_loop` já está ativo
        e é utilizado diretamente.
        """
        with cls._state_lock:
            if cls._main_loop is not None and cls._main_loop.is_running():
                return cls._main_loop
            bg_loop = getattr(cls, "_bg_loop", None)
            if bg_loop is not None and bg_loop.is_running():
                return bg_loop

            ready = threading.Event()
            new_loop = asyncio.new_event_loop()

            def _run_loop():
                asyncio.set_event_loop(new_loop)
                ready.set()
                new_loop.run_forever()

            t = threading.Thread(target=_run_loop, name="ai3d-job-orchestrator-loop", daemon=True)
            t.start()
            ready.wait(timeout=2.0)
            cls._bg_loop = new_loop
            return new_loop

    @classmethod
    def dispatch_job(
        cls,
        job_id: str,
        project_id: str,
        params: Dict[str, Any],
        operation_type: Optional[str] = None
    ):
        """
        Agenda a execução assíncrona do job no event loop principal registrado (`_main_loop`),
        no event loop ativo da coroutine ou no loop de background persistente, garantindo:
        1. Retorno imediato de `POST /api/v1/jobs` sem bloquear o cliente HTTP;
        2. Compartilhamento estrito do mesmo `asyncio.Semaphore(MAX_CONCURRENT_JOBS = 2)`.
        """
        with cls._state_lock:
            cls._cancellation_events.setdefault(job_id, threading.Event())
            main_loop = cls._main_loop

        target_loop: Optional[asyncio.AbstractEventLoop] = None
        if main_loop is not None and main_loop.is_running():
            target_loop = main_loop
        else:
            target_loop = cls._ensure_background_loop()

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is target_loop:
            task = target_loop.create_task(cls.run_procedural_job_async(job_id, project_id, params, operation_type))
            with cls._state_lock:
                cls._running_tasks[job_id] = task
            return task
        else:
            scheduled = threading.Event()
            task_holder: Dict[str, asyncio.Task] = {}

            def _schedule_on_target():
                t = target_loop.create_task(cls.run_procedural_job_async(job_id, project_id, params, operation_type))
                with cls._state_lock:
                    cls._running_tasks[job_id] = t
                task_holder["task"] = t
                scheduled.set()

            target_loop.call_soon_threadsafe(_schedule_on_target)
            scheduled.wait(timeout=1.0)
            return task_holder.get("task")

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
