import os
import json
import uuid
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
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

SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

def get_utc_now():
    return datetime.now(timezone.utc)

def remove_quarantine_path(path_to_remove: Path):
    """Executa a remoção definitiva do diretório em quarentena com segurança."""
    try:
        resolved = path_to_remove.resolve()
        quarantine_root = settings.QUARANTINE_DIR.resolve()
        if str(resolved).startswith(str(quarantine_root)) and resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)
    except Exception:
        pass

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
        strategy=data.strategy,
        status="active"
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project

@router.get("/projects", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    return db.query(ProjectModel).filter(ProjectModel.status == "active").order_by(ProjectModel.updated_at.desc()).all()

@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project or project.status == "deleting":
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return project

@router.delete("/projects/{project_id}")
def delete_project(project_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Exclusão recuperável em duas fases com quarentena (STORE-001 / R1):
    1. Marca projeto como 'deleting' no banco para bloquear jobs e acessos concorrentes.
    2. Move a pasta física para storage/.quarantine/{id}_{timestamp} atomicamente.
    3. Remove os registros do banco SQLite e faz commit.
       - Se commit falhar: restaura pasta da quarentena e reverte status para 'active'.
    4. Remove a pasta da quarentena de forma segura em background.
    """
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    if project.status == "deleting":
        raise HTTPException(status_code=409, detail="Projeto já está em processo de exclusão")

    # Passo 1: Marcação de status no banco para bloqueio
    project.status = "deleting"
    db.commit()

    # Caminhos físicos
    project_dir = (settings.STORAGE_DIR / project_id).resolve()
    storage_root = settings.STORAGE_DIR.resolve()

    # Proteção de segurança: diretório DEVE ser estritamente filho de STORAGE_DIR
    try:
        if os.path.commonpath([str(storage_root), str(project_dir)]) != str(storage_root):
            project.status = "active"
            db.commit()
            raise HTTPException(status_code=403, detail="Caminho de projeto inválido ou fora do armazenamento autorizado")
    except ValueError:
        project.status = "active"
        db.commit()
        raise HTTPException(status_code=403, detail="Caminho de armazenamento inválido")

    quarantine_subpath = None
    if project_dir.exists():
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        quarantine_subpath = (settings.QUARANTINE_DIR / f"{project_id}_{timestamp_str}").resolve()
        try:
            shutil.move(str(project_dir), str(quarantine_subpath))
        except Exception as e:
            project.status = "active"
            db.commit()
            raise HTTPException(status_code=500, detail=f"Falha ao mover arquivos para quarentena: {str(e)}")

    # Passo 3: Commit no SQLite
    try:
        db.query(JobModel).filter(JobModel.project_id == project_id).delete()
        db.delete(project)
        db.commit()
    except Exception as e:
        db.rollback()
        # Rollback da quarentena se commit de banco falhar
        if quarantine_subpath and quarantine_subpath.exists():
            try:
                shutil.move(str(quarantine_subpath), str(project_dir))
            except Exception:
                pass
        # Restaurar status no banco
        try:
            proj_revert = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if proj_revert:
                proj_revert.status = "active"
                db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Falha na exclusão do banco de dados: {str(e)}")

    # Passo 4: Limpeza em background da quarentena
    if quarantine_subpath and quarantine_subpath.exists():
        background_tasks.add_task(remove_quarantine_path, quarantine_subpath)

    return {"message": f"Projeto {project_id} removido com sucesso"}

# ----------------- TAREFAS (JOBS) -----------------

@router.post("/jobs", response_model=JobResponse)
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    project = db.query(ProjectModel).filter(ProjectModel.id == data.project_id).first()
    if not project or project.status == "deleting":
        raise HTTPException(status_code=404, detail="Projeto referenciado não existe ou está em exclusão")

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

# ----------------- ARTEFATOS E ARQUIVOS CONTEXTUAIS -----------------

@router.get("/projects/{project_id}/artifacts/{filename}")
def download_artifact(project_id: str, filename: str, db: Session = Depends(get_db)):
    """
    Endpoint contextual seguro para download de artefatos vinculados ao projeto (SEC-001 / Task 1.1).
    Validações:
    - O projeto deve existir no banco de dados e não estar marcado como deleting.
    - O filename deve ser estritamente alfanumérico seguro (sem barras, .. ou caracteres de controle).
    - O caminho resolvido deve ser estritamente filho da pasta storage/projects/{project_id}.
    - Não permite symlinks.
    - O arquivo deve constar na lista de artefatos gerados pelo projeto ou modelo ativo.
    """
    # 1. Validação de regex do nome do arquivo
    if not SAFE_FILENAME_REGEX.match(filename) or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido ou contém caracteres não permitidos")

    # 2. Validação do projeto no banco
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project or project.status == "deleting":
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou indisponível")

    # 3. Resolução segura de caminhos e validação de pertencimento
    project_dir = (settings.STORAGE_DIR / project_id).resolve()
    target_path = (project_dir / filename).resolve()

    try:
        if os.path.commonpath([str(project_dir), str(target_path)]) != str(project_dir):
            raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do projeto")
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    # 4. Verificação de existência e tipo (não aceita diretórios nem symlinks)
    if not target_path.exists() or target_path.is_dir() or target_path.is_symlink():
        raise HTTPException(status_code=404, detail="Artefato não encontrado")

    # 5. Validação de registro nos artefatos do projeto
    jobs = db.query(JobModel).filter(JobModel.project_id == project_id).all()
    registered_files = set()
    if project.active_model_path:
        registered_files.add(Path(project.active_model_path).name)

    for j in jobs:
        try:
            files = json.loads(j.result_files_json or "[]")
            for f in files:
                registered_files.add(Path(f).name)
        except Exception:
            pass

    if filename not in registered_files:
        raise HTTPException(status_code=403, detail="Arquivo solicitado não está registrado como artefato deste projeto")

    # Media type baseado na extensão
    suffix = target_path.suffix.lower()
    media_type = "model/gltf-binary" if suffix == ".glb" else "text/plain" if suffix == ".obj" else "application/octet-stream"

    return FileResponse(target_path, media_type=media_type, filename=target_path.name)

# Rota mantida temporariamente com redirecionamento de compatibilidade interna se necessário
@router.get("/files/download")
def download_file_legacy(path: str = Query(..., description="Caminho relativo seguro do arquivo")):
    """Rota legada marcada como obsoleta, rejeita acessos fora da raiz estrita."""
    clean_path = Path(path).resolve()
    base_dir = settings.STORAGE_DIR.resolve()
    try:
        if os.path.commonpath([str(base_dir), str(clean_path)]) != str(base_dir):
            raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do armazenamento de projetos")
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    if not clean_path.exists() or clean_path.is_dir() or clean_path.is_symlink():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    media_type = "model/gltf-binary" if clean_path.suffix.lower() == ".glb" else "application/octet-stream"
    return FileResponse(clean_path, media_type=media_type, filename=clean_path.name)
