import os
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.storage.database import init_db, SessionLocal, ProjectModel
from backend.app.api.routes import router as api_router

def reconcile_storage_and_quarantine():
    """
    Reconciliação no startup (Task 1.3 / R1):
    1. Inspeciona projetos que permaneceram com status 'deleting' (ex: queda de energia ou interrupção durante exclusão).
       - Se a pasta do projeto ainda existe em STORAGE_DIR, restaura o status para 'active'.
       - Se existe pasta correspondente na quarentena (.quarantine/{project_id}_*), restaura a pasta para o projeto e volta para 'active'.
       - Se nenhuma pasta existir nem no storage nem na quarentena, finaliza a remoção do projeto e seus jobs no SQLite.
    2. Após reconciliar os projetos, limpa quaisquer pastas órfãs residuais no diretório de quarentena.
    """
    db = SessionLocal()
    try:
        deleting_projects = db.query(ProjectModel).filter(ProjectModel.status == "deleting").all()
        quarantine_dir = settings.QUARANTINE_DIR.resolve()

        for p in deleting_projects:
            project_dir = settings.STORAGE_DIR / p.id
            if project_dir.exists():
                # Pasta original ainda existe intacta no storage
                p.status = "active"
                continue

            # Verificar se há pasta deste projeto em quarentena
            found_in_quarantine = None
            if quarantine_dir.exists():
                for item in quarantine_dir.iterdir():
                    if item.is_dir() and item.name.startswith(f"{p.id}_"):
                        found_in_quarantine = item
                        break

            if found_in_quarantine and found_in_quarantine.exists():
                # Restaurar a pasta da quarentena de volta ao storage do projeto
                try:
                    shutil.move(str(found_in_quarantine), str(project_dir))
                    p.status = "active"
                except Exception:
                    # Se falhar a restauração física, mantém 'deleting' para intervenção
                    pass
            else:
                # Diretório já não existe em lugar nenhum; finaliza limpeza no SQLite
                db.query(JobModel).filter(JobModel.project_id == p.id).delete()
                db.delete(p)

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    # Limpar pastas da quarentena que não estejam vinculadas a projetos em recuperação
    try:
        quarantine_dir = settings.QUARANTINE_DIR.resolve()
        if quarantine_dir.exists():
            for item in quarantine_dir.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização do banco e tabelas
    init_db()
    # Reconciliação de arquivos e armazenamento
    reconcile_storage_and_quarantine()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend local do AI 3D Studio para modelagem procedural e processamento 3D.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "local_only": True
    }
