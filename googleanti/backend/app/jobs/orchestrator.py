import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from sqlalchemy.orm import Session
from backend.app.schemas.jobs import JobStatus
from backend.app.storage.database import SessionLocal, JobModel, ProjectModel
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter
from backend.app.config import settings

def get_now():
    return datetime.now(timezone.utc)

class JobOrchestrator:
    """
    Máquina de estados e executor assíncrono para tarefas de modelagem e processamento.
    Estados: Pendente -> Preparando -> Em Execução -> Concluída / Falhou / Cancelada.
    """

    # Transições válidas
    VALID_TRANSITIONS = {
        JobStatus.PENDING: [JobStatus.PREPARING, JobStatus.CANCELLED],
        JobStatus.PREPARING: [JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED],
        JobStatus.RUNNING: [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED],
        JobStatus.COMPLETED: [],
        JobStatus.FAILED: [],
        JobStatus.CANCELLED: []
    }

    _running_tasks: Dict[str, asyncio.Task] = {}

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
        return job

    @classmethod
    def update_job_status(
        cls,
        job_id: str,
        target_status: JobStatus,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
        result_files: Optional[list] = None,
        metadata: Optional[dict] = None
    ):
        db = SessionLocal()
        try:
            job = db.query(JobModel).filter(JobModel.id == job_id).first()
            if not job:
                return

            current_status = JobStatus(job.status)
            if current_status != target_status:
                cls.validate_transition(current_status, target_status)
                job.status = target_status.value

            if target_status == JobStatus.RUNNING and not job.started_at:
                job.started_at = get_now()
            elif target_status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                job.completed_at = get_now()

            if progress is not None:
                job.progress = progress
            if error_message is not None:
                job.error_message = error_message
            if result_files is not None:
                job.result_files_json = json.dumps(result_files)
            if metadata is not None:
                job.metadata_json = json.dumps(metadata)

            db.commit()
        finally:
            db.close()

    @classmethod
    def cancel_job(cls, job_id: str) -> bool:
        if job_id in cls._running_tasks:
            task = cls._running_tasks[job_id]
            task.cancel()
        cls.update_job_status(job_id, JobStatus.CANCELLED, error_message="Cancelado pelo usuário.")
        return True

    @classmethod
    async def run_procedural_job_async(cls, job_id: str, project_id: str, params: Dict[str, Any]):
        cls.update_job_status(job_id, JobStatus.PREPARING, progress=0.1)
        await asyncio.sleep(0.05)

        cls.update_job_status(job_id, JobStatus.RUNNING, progress=0.3)
        await asyncio.sleep(0.05)

        try:
            shape_type = params.get("shape_type", "box")
            mesh = ProceduralGenerator.generate_by_params(shape_type, params)
            inspect_info = ProceduralGenerator.inspect_mesh(mesh)

            # Exportar modelo padrão GLB
            project_dir = settings.STORAGE_DIR / project_id
            project_dir.mkdir(parents=True, exist_ok=True)
            model_filename = f"{shape_type}_{uuid.uuid4().hex[:6]}.glb"
            model_path = project_dir / model_filename

            export_meta = ModelExporter.export_and_validate(mesh, model_path, fmt="glb")

            # Atualizar projeto com o modelo ativo
            db = SessionLocal()
            try:
                proj = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
                if proj:
                    proj.active_model_path = str(model_path.relative_to(settings.BASE_DIR))
                    proj.parameters_json = json.dumps(params)
                    proj.updated_at = get_now()
                    db.commit()
            finally:
                db.close()

            cls.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                progress=1.0,
                result_files=[str(model_path.relative_to(settings.BASE_DIR))],
                metadata={"inspection": inspect_info, "export": export_meta}
            )
        except asyncio.CancelledError:
            cls.update_job_status(job_id, JobStatus.CANCELLED, error_message="Execução cancelada.")
            raise
        except Exception as e:
            cls.update_job_status(job_id, JobStatus.FAILED, error_message=str(e))
        finally:
            cls._running_tasks.pop(job_id, None)

    @classmethod
    def dispatch_job(cls, job_id: str, project_id: str, params: Dict[str, Any]):
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(cls.run_procedural_job_async(job_id, project_id, params))
            cls._running_tasks[job_id] = task
            return task
        except RuntimeError:
            # Sem loop ativo (ex: chamadas síncronas do TestClient)
            return asyncio.run(cls.run_procedural_job_async(job_id, project_id, params))
