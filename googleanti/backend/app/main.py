import os
import logging
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.config import settings
from backend.app.storage.database import init_db, SessionLocal, ProjectModel, JobModel
from backend.app.schemas.jobs import JobStatus
from backend.app.jobs.orchestrator import JobOrchestrator
from backend.app.api.routes import (
    router as api_router,
    QUARANTINE_FOLDER_REGEX,
    _is_valid_timestamp,
    parse_quarantine_folder_name,
    validate_quarantine_manifest,
    remove_quarantine_path
)

logger = logging.getLogger("ai_3d_studio.reconciliation")

def find_project_quarantine_dirs(quarantine_dir: os.PathLike, project_id: str) -> list[Path]:
    """
    STORE-004: Localiza diretórios de quarentena vinculados a `project_id` garantindo
    correspondência exata via regex `^{project_id}_(?P<timestamp>\\d{14,20})$`,
    evitando colisões de prefixo (ex: proj-1 vs proj-10) e ignorando symlinks.
    """
    matched: list[Path] = []
    q_root = Path(quarantine_dir)
    if not q_root.exists() or q_root.is_symlink():
        return matched

    for item in os.scandir(q_root):
        try:
            if item.is_symlink():
                continue
            if item.is_dir(follow_symlinks=False):
                parsed = parse_quarantine_folder_name(item.name)
                if parsed and parsed[0] == project_id:
                    matched.append(q_root / item.name)
        except OSError:
            continue
    return matched

def reconcile_storage_and_quarantine():
    """
    Reconciliação transacional e idempotente no startup (Task 1.3 / R1 / STORE-002 / STORE-003 / STORE-004):
    Invariantes de Segurança:
    1. NENHUM arquivo recuperável é destruído sem confirmação durável e verificável (manifesto válido).
    2. Cada projeto em estado 'deleting' é processado em sua própria transação isolada para que
       uma falha de commit em um projeto nunca afete ou reverta o estado de outro.
    3. Quando um projeto em 'deleting' possui pasta em quarentena SEM manifesto válido,
       a pasta é restaurada para `STORAGE_DIR/{project_id}`, mas o projeto permanece protegido
       e só volta para 'active' se o commit no SQLite suceder; se o commit no SQLite falhar,
       o diretório restaurado NÃO é apagado e na próxima execução será reativado com segurança.
    4. Quando um projeto em 'deleting' possui manifesto válido confirmado, primeiro conclui-se
       o commit de remoção no SQLite e somente depois remove-se fisicamente a pasta da quarentena
       por meio de `remove_quarantine_path()` (que revalida integralmente o manifesto antes da purga).
    """
    quarantine_dir = settings.QUARANTINE_DIR.resolve()
    storage_root = settings.STORAGE_DIR.resolve()
    protected_quarantine_dirs: set[str] = set()

    # Etapa 1: Obter lista de IDs de projetos com status == 'deleting'
    db_list = SessionLocal()
    try:
        deleting_ids = [
            row[0] for row in db_list.query(ProjectModel.id).filter(ProjectModel.status == "deleting").all()
        ]
    except Exception as e:
        logger.error(f"Erro ao consultar projetos em estado 'deleting': {e}")
        deleting_ids = []
    finally:
        db_list.close()

    # Etapa 2: Processar cada projeto 'deleting' de forma isolada e idempotente
    for proj_id in deleting_ids:
        db = SessionLocal()
        try:
            p = db.query(ProjectModel).filter(ProjectModel.id == proj_id).first()
            if not p or p.status != "deleting":
                continue

            project_dir = (storage_root / p.id).resolve()
            matched_folders = find_project_quarantine_dirs(quarantine_dir, p.id)

            for qf in matched_folders:
                protected_quarantine_dirs.add(str(qf.resolve()))

            # Caso A: A pasta original em STORAGE_DIR já existe (ex: restaurada em tentativa anterior cujo commit falhou)
            if project_dir.exists():
                logger.info(f"Projeto {p.id} possui pasta em STORAGE_DIR. Reativando status para 'active'.")
                p.status = "active"
                db.commit()
                continue

            # Caso B: Existem pastas correspondentes na quarentena
            if matched_folders:
                confirmed_folders = []
                unconfirmed_folders = []
                for q_folder in matched_folders:
                    meta_file = q_folder / ".quarantine_meta.json"
                    if meta_file.exists() and validate_quarantine_manifest(meta_file, expected_project_id=p.id, folder_name=q_folder.name):
                        confirmed_folders.append(q_folder)
                    else:
                        unconfirmed_folders.append(q_folder)

                if confirmed_folders and not unconfirmed_folders:
                    # Exclusão formalmente confirmada pelo manifesto durável:
                    # Primeiro removemos o registro no SQLite e comitamos; se o commit falhar,
                    # a pasta e o manifesto permanecem na quarentena para a próxima execução.
                    try:
                        db.query(JobModel).filter(JobModel.project_id == p.id).delete()
                        db.delete(p)
                        db.commit()
                    except Exception as db_err:
                        db.rollback()
                        logger.error(
                            f"Falha no commit SQLite ao finalizar exclusão confirmada de {p.id}: {db_err}. "
                            "Quarentena e manifesto preservados para nova tentativa."
                        )
                        continue

                    # Após commit bem-sucedido no banco, expurgar fisicamente as pastas confirmadas usando remove_quarantine_path
                    for q_folder in confirmed_folders:
                        if remove_quarantine_path(q_folder, expected_project_id=p.id):
                            protected_quarantine_dirs.discard(str(q_folder.resolve()))
                            logger.info(f"Quarentena confirmada para {p.id} ({q_folder.name}) purgada com sucesso.")
                        else:
                            logger.error(f"Não foi possível remover fisicamente {q_folder.name}; será tentado no próximo ciclo.")
                else:
                    # Exclusão NÃO confirmada (sem manifesto ou manifesto inválido/corrompido):
                    # Restaurar a pasta mais recente para STORAGE_DIR e reativar o projeto.
                    target_q_folder = sorted(unconfirmed_folders or matched_folders, key=lambda x: x.name)[-1]
                    moved_to_storage = False
                    try:
                        bad_meta = target_q_folder / ".quarantine_meta.json"
                        if bad_meta.exists() and not bad_meta.is_symlink():
                            try:
                                bad_meta.unlink()
                            except OSError:
                                pass

                        shutil.move(str(target_q_folder), str(project_dir))
                        moved_to_storage = True
                    except Exception as move_err:
                        logger.error(
                            f"Falha ao restaurar pasta de quarentena para {p.id}: {move_err}. "
                            f"Arquivos PRESERVADOS em {target_q_folder} e projeto permanece em 'deleting'."
                        )
                        continue

                    if moved_to_storage:
                        try:
                            p.status = "active"
                            db.commit()
                            protected_quarantine_dirs.discard(str(target_q_folder.resolve()))
                            logger.info(f"Pasta do projeto {p.id} restaurada da quarentena e projeto reativado.")
                        except Exception as commit_err:
                            db.rollback()
                            logger.error(
                                f"Arquivos de {p.id} foram restaurados para {project_dir}, mas o commit SQLite falhou: {commit_err}. "
                                "Arquivos permanecem seguros em STORAGE_DIR e o status será reativado na próxima reconciliação."
                            )
            else:
                # Caso C: Diretório não existe nem em STORAGE_DIR nem em QUARANTINE_DIR
                logger.info(f"Projeto {p.id} sem arquivos em storage ou quarentena. Finalizando limpeza no SQLite.")
                try:
                    db.query(JobModel).filter(JobModel.project_id == p.id).delete()
                    db.delete(p)
                    db.commit()
                except Exception as db_err:
                    db.rollback()
                    logger.error(f"Falha ao limpar registro órfão sem arquivos para {p.id}: {db_err}")
        except Exception as e:
            db.rollback()
            logger.error(f"Erro inesperado ao reconciliar projeto {proj_id}: {e}")
        finally:
            db.close()

    # Etapa 3: Varredura secundária de pastas órfãs na quarentena
    try:
        if quarantine_dir.exists() and not quarantine_dir.is_symlink():
            db_verify = SessionLocal()
            try:
                all_project_ids = {row[0] for row in db_verify.query(ProjectModel.id).all()}
            finally:
                db_verify.close()

            for item in os.scandir(quarantine_dir):
                item_path = quarantine_dir / item.name
                try:
                    if item.is_symlink():
                        logger.warning(f"Ignorando e preservando symlink suspeito na quarentena: {item.name}")
                        continue

                    resolved_item = item_path.resolve()
                    if str(resolved_item) in protected_quarantine_dirs:
                        logger.warning(f"Diretório em quarentena {item.name} protegido contra remoção neste ciclo.")
                        continue

                    if item.is_dir(follow_symlinks=False):
                        parsed = parse_quarantine_folder_name(item.name)
                        if not parsed:
                            logger.warning(
                                f"Diretório na quarentena '{item.name}' não segue o padrão '{{project_id}}_{{timestamp}}'. "
                                "Preservando preventivamente."
                            )
                            continue

                        candidate_id, _ = parsed
                        if candidate_id in all_project_ids:
                            logger.warning(
                                f"Diretório {item.name} refere-se a projeto ainda presente no SQLite ({candidate_id}). "
                                "Preservando preventivamente."
                            )
                            continue

                        # Delega para remove_quarantine_path que valida integralmente o manifesto antes de remover
                        if remove_quarantine_path(resolved_item, expected_project_id=candidate_id):
                            logger.info(f"Diretório órfão de exclusão comprovada {item.name} purgado com sucesso.")
                        else:
                            logger.warning(
                                f"Diretório na quarentena {item.name} não possui manifesto válido de exclusão. "
                                "Preservando preventivamente contra perda acidental de dados."
                            )
                    else:
                        # Apenas arquivos temporários de manifesto (.tmp_meta_*.tmp) órfãos são removidos
                        if item.name.startswith(".tmp_meta_") and item.name.endswith(".tmp"):
                            try:
                                resolved_item.unlink(missing_ok=True)
                            except OSError as unlink_err:
                                logger.warning(f"Não foi possível remover temporário órfão {item.name}: {unlink_err}")
                        else:
                            logger.warning(f"Arquivo avulso inesperado na quarentena preservado: {item.name}")
                except Exception as item_err:
                    logger.error(f"Erro ao inspecionar item na quarentena {item.name}: {item_err}")
    except Exception as e:
        logger.error(f"Erro na rotina de varredura secundária de quarentena: {e}")

def reconcile_interrupted_jobs():
    """
    Reconciliação determinística e idempotente de tarefas órfãs na inicialização (Task 2.3 / R2 / ASYNC-001):
    - Inspeciona a tabela `jobs` no SQLite em busca de registros em estados não-terminais
      (`Pendente`, `Preparando`, `Em Execução`).
    - Transita cada tarefa interrompida para o estado terminal `Cancelada` (`JobStatus.CANCELLED.value`),
      preenche `completed_at` com timestamp UTC, registra justificativa explícita em `error_message`
      e adiciona metadado de auditoria (`reconciled_on_startup: True`, `interrupted_from_status`).
    - Limpa exclusivamente arquivos temporários parciais (`.tmp.*` / `.tmp`) nos diretórios dos projetos,
      preservando integralmente todos os artefatos válidos de jobs já concluídos.
    """
    import json
    from datetime import datetime, timezone

    non_terminal_statuses = [
        JobStatus.PENDING.value,
        JobStatus.PREPARING.value,
        JobStatus.RUNNING.value
    ]

    db = SessionLocal()
    affected_projects: set[str] = set()
    try:
        interrupted_jobs = db.query(JobModel).filter(
            JobModel.status.in_(non_terminal_statuses)
        ).all()

        now = datetime.now(timezone.utc)
        for job in interrupted_jobs:
            prev_status = job.status
            job.status = JobStatus.CANCELLED.value
            if not job.completed_at:
                job.completed_at = now
            job.error_message = (
                f"Tarefa interrompida por reinicialização do servidor (estado anterior: {prev_status})."
            )
            try:
                meta = json.loads(job.metadata_json or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            meta["reconciled_on_startup"] = True
            meta["interrupted_from_status"] = prev_status
            meta["reconciled_at"] = now.isoformat()
            job.metadata_json = json.dumps(meta)
            affected_projects.add(job.project_id)

        if interrupted_jobs:
            db.commit()
            logger.info(
                f"Reconciliação de jobs: {len(interrupted_jobs)} tarefa(s) interrompida(s) "
                "transitada(s) para 'Cancelada'."
            )
    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao reconciliar tarefas interrompidas na inicialização: {e}")
    finally:
        db.close()

    # Limpar quaisquer arquivos temporários parciais (.tmp.*) nos projetos afetados ou em STORAGE_DIR
    try:
        storage_root = settings.STORAGE_DIR.resolve()
        if storage_root.exists() and storage_root.is_dir() and not storage_root.is_symlink():
            for proj_dir in storage_root.iterdir():
                if proj_dir.is_dir() and not proj_dir.is_symlink() and proj_dir.name != settings.QUARANTINE_DIR.name:
                    JobOrchestrator._cleanup_partial_files(proj_dir.name, sweep_all_tmp=True)
    except Exception as clean_err:
        logger.warning(f"Erro ao limpar arquivos temporários parciais na reconciliação de jobs: {clean_err}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    # Registrar event loop principal para despacho assíncrono não-bloqueante (Achado B)
    JobOrchestrator.set_main_loop(asyncio.get_running_loop())
    # Inicialização do banco e tabelas
    init_db()
    # Reconciliação de arquivos e armazenamento (Bloco 1)
    reconcile_storage_and_quarantine()
    # Reconciliação de tarefas interrompidas por reinício do servidor (Bloco 2 - Task 2.3)
    reconcile_interrupted_jobs()
    try:
        yield
    finally:
        # Encerramento limpo e cooperativo de jobs em execução no shutdown (Bloco 2 - Task 2.1)
        await JobOrchestrator.shutdown_active_jobs()
        JobOrchestrator.set_main_loop(None)

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
