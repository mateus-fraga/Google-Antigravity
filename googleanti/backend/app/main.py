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
    Reconciliação no startup (Task 1.3):
    1. Limpa pastas residuais deixadas no diretório de quarentena devido a crashes ou quedas de energia.
    2. Identifica projetos que possam ter permanecido com status 'deleting' caso o processo tenha caído antes do commit.
    """
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

    # Reconciliação no banco: se houver projeto marcado como 'deleting' cujo diretório já não existe ou está inconsistente
    db = SessionLocal()
    try:
        deleting_projects = db.query(ProjectModel).filter(ProjectModel.status == "deleting").all()
        for p in deleting_projects:
            project_dir = settings.STORAGE_DIR / p.id
            if not project_dir.exists():
                # Já foi movido para quarentena e apagado, finaliza remoção no banco
                db.delete(p)
            else:
                # Diretório ainda existe intacto, restaura para active
                p.status = "active"
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

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
