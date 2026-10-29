import os
import json
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.storage.database import get_db, ProjectModel, JobModel
from backend.app.schemas.jobs import (
    ProjectCreate,
    ProjectResponse,
    JobCreate,
    JobResponse,
    JobStatus
)
from backend.app.jobs.orchestrator import JobOrchestrator
from backend.app.config import settings

router = APIRouter()

# ----------------- PROJETOS -----------------

@router.post("/projects", response_model=ProjectResponse)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    proj_id = f"proj-{uuid.uuid4().hex[:8]}"
    project = ProjectModel(
        id=proj_id,
        name=data.name,
        description=data.description,
        category=data.category,
        purpose=data.purpose,
        strategy=data.strategy
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project

@router.get("/projects", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(ProjectModel).order_by(ProjectModel.updated_at.desc()).all()

@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project

@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # Deletar jobs associados
    db.query(JobModel).filter(JobModel.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    return {"message": f"Projeto {project_id} removido com sucesso"}

# ----------------- TAREFAS (JOBS) -----------------

@router.post("/jobs", response_model=JobResponse)
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == data.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto referenciado não existe")

    job = JobOrchestrator.create_job(
        db,
        project_id=data.project_id,
        operation_type=data.operation_type,
        params=data.params
    )

    # Disparar execução em segundo plano
    JobOrchestrator.dispatch_job(job.id, data.project_id, data.params)

    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        operation_type=job.operation_type,
        status=JobStatus(job.status),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=job.progress,
        error_message=job.error_message,
        result_files=json.loads(job.result_files_json or "[]"),
        metadata=json.loads(job.metadata_json or "{}")
    )

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")

    return JobResponse(
        id=job.id,
        project_id=job.project_id,
        operation_type=job.operation_type,
        status=JobStatus(job.status),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=job.progress,
        error_message=job.error_message,
        result_files=json.loads(job.result_files_json or "[]"),
        metadata=json.loads(job.metadata_json or "{}")
    )

@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")

    JobOrchestrator.cancel_job(job_id)
    return {"message": f"Cancelamento solicitado para a tarefa {job_id}"}

# ----------------- ARQUIVOS E MODELOS -----------------

@router.get("/files/download")
def download_file(path: str = Query(..., description="Caminho relativo seguro do arquivo")):
    # Prevenção rigorosa de Path Traversal
    clean_path = Path(path).resolve()
    base_dir = settings.BASE_DIR.resolve()
    if not str(clean_path).startswith(str(base_dir)):
        raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do escopo do projeto")

    if not clean_path.exists() or clean_path.is_dir():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    media_type = "model/gltf-binary" if clean_path.suffix.lower() == ".glb" else "application/octet-stream"
    return FileResponse(clean_path, media_type=media_type, filename=clean_path.name)
