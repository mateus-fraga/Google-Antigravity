import os
import json
import uuid
import re
import stat as stat_mod
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Iterator
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
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

logger = logging.getLogger("ai_3d_studio.routes")

router = APIRouter()

SAFE_FILENAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
SAFE_PROJECT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")
QUARANTINE_FOLDER_REGEX = re.compile(r"^(?P<project_id>[a-zA-Z0-9_\-]+)_(?P<timestamp>\d{14,20})$")
QUARANTINE_MANIFEST_VERSION = 1

def get_utc_now():
    return datetime.now(timezone.utc)

def _is_valid_timestamp(ts_str: str) -> bool:
    """
    STORE-004: Valida que o timestamp do manifesto/pasta é uma string numérica de 14 a 20 dígitos
    representando uma data/hora UTC válida (%Y%m%d%H%M%S...) ou formato ISO 8601 válido.
    """
    if not isinstance(ts_str, str) or not ts_str.strip():
        return False
    if re.match(r"^\d{14,20}$", ts_str):
        try:
            datetime.strptime(ts_str[:14], "%Y%m%d%H%M%S")
            return True
        except ValueError:
            return False
    try:
        datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False

def parse_quarantine_folder_name(folder_name: str) -> Optional[tuple[str, str]]:
    """
    STORE-004: Extrai (project_id, timestamp) do nome da pasta de quarentena
    seguindo estritamente o padrão '{project_id}_{timestamp_numerico}'.
    Retorna None se o nome não obedecer ao contrato exato.
    """
    if not isinstance(folder_name, str):
        return None
    m = QUARANTINE_FOLDER_REGEX.match(folder_name)
    if not m:
        return None
    proj_id = m.group("project_id")
    ts_str = m.group("timestamp")
    if not _is_valid_timestamp(ts_str):
        return None
    return proj_id, ts_str

def validate_quarantine_manifest(
    meta_file: os.PathLike,
    expected_project_id: Optional[str] = None,
    folder_name: Optional[str] = None
) -> bool:
    """
    STORE-004: Validação rigorosa do esquema, tipos de dados e correspondência do manifesto de quarentena.
    Regras obrigatórias:
    - O arquivo não pode ser symlink e deve ser um objeto JSON (dict).
    - 'version' deve ser inteiro >= 1 (rejeita booleano, string vazia, zero ou negativo) ou string "1"/"1.0" legada.
    - 'delete_confirmed' deve ser estritamente o booleano True (`data.get("delete_confirmed") is True`).
    - 'project_id' deve ser string não vazia, sem '..' ou '/', e coincidir exatamente com:
      a) `expected_project_id` (quando fornecido);
      b) o `project_id` extraído de `folder_name` (ou do diretório pai do manifesto).
    - 'timestamp' deve ser string válida de timestamp e coincidir com o sufixo de timestamp da pasta de quarentena.
    - Caso 'folder_name' esteja presente no JSON, deve coincidir exatamente com o nome real da pasta.
    Qualquer divergência, incompletude ou erro resulta em False (preservação preventiva dos arquivos).
    """
    try:
        meta_path = Path(meta_file)
        if not meta_path.exists() or meta_path.is_symlink() or meta_path.is_dir():
            return False

        actual_folder_name = folder_name if folder_name is not None else meta_path.parent.name
        parsed_folder = parse_quarantine_folder_name(actual_folder_name)
        if not parsed_folder:
            logger.warning(f"Nome de pasta de quarentena fora do padrão estrito: {actual_folder_name}")
            return False
        folder_project_id, folder_timestamp = parsed_folder

        with open(meta_path, "r", encoding="utf-8") as mf:
            data = json.load(mf)

        if not isinstance(data, dict):
            return False

        # 1. Validação estrita de delete_confirmed (deve ser exatamente o booleano True)
        if data.get("delete_confirmed") is not True:
            return False

        # 2. Validação estrita de version (int >= 1 ou string "1"/"1.0", nunca bool)
        version = data.get("version")
        if isinstance(version, bool) or version is None:
            return False
        if isinstance(version, int):
            if version < 1:
                return False
        elif isinstance(version, str):
            if version not in ("1", "1.0"):
                return False
        else:
            return False

        # 3. Validação estrita de project_id
        manifest_project_id = data.get("project_id")
        if not isinstance(manifest_project_id, str) or not manifest_project_id.strip():
            return False
        if ".." in manifest_project_id or "/" in manifest_project_id or "\\" in manifest_project_id:
            return False

        if expected_project_id is not None and manifest_project_id != expected_project_id:
            logger.warning(
                f"Manifesto em {meta_path} possui project_id divergente do esperado: "
                f"esperado={expected_project_id}, manifesto={manifest_project_id}"
            )
            return False

        if manifest_project_id != folder_project_id:
            logger.warning(
                f"Manifesto em {meta_path} diverge do identificador da pasta: "
                f"pasta={folder_project_id}, manifesto={manifest_project_id}"
            )
            return False

        # 4. Validação estrita de timestamp e correspondência com a pasta
        manifest_ts = data.get("timestamp")
        if not _is_valid_timestamp(manifest_ts):
            logger.warning(f"Manifesto em {meta_path} possui timestamp inválido: {manifest_ts}")
            return False

        if manifest_ts != folder_timestamp:
            logger.warning(
                f"Manifesto em {meta_path} possui timestamp divergente do nome da pasta: "
                f"pasta={folder_timestamp}, manifesto={manifest_ts}"
            )
            return False

        # 5. Se o manifesto gravou folder_name, deve coincidir com o diretório atual
        if "folder_name" in data and data["folder_name"] != actual_folder_name:
            logger.warning(
                f"Manifesto em {meta_path} possui folder_name divergente: "
                f"atual={actual_folder_name}, manifesto={data['folder_name']}"
            )
            return False

        return True
    except Exception as e:
        logger.warning(f"Erro ao validar manifesto de quarentena {meta_file}: {e}")
        return False

def _sync_directory_if_supported(dir_path: Path):
    """
    STORE-002: Sincroniza metadados do diretório no sistema operacional quando suportado.
    Em POSIX, realiza open(O_RDONLY) + os.fsync(fd). Em Windows, onde os.fsync em diretórios
    pode lançar PermissionError/OSError, ignora de forma controlada após tentativa segura.
    """
    if not hasattr(os, "O_RDONLY"):
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = None
    try:
        fd = os.open(str(dir_path), flags)
        os.fsync(fd)
    except OSError:
        # Windows ou filesystems que não permitem fsync direto em descritor de diretório
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

def _contains_symlink_in_chain(target: Path, stop_at: Path) -> bool:
    """
    SEC-001: Verifica se o caminho não resolvido ou qualquer ancestral até stop_at
    é um link simbólico (ou junction/reparse point no Windows).
    Deve ser executado ANTES de Path.resolve().
    """
    try:
        if target.is_symlink() or os.path.islink(str(target)):
            return True
        if hasattr(target, "is_junction") and target.is_junction():
            return True
    except OSError:
        return True

    curr = target
    stop_abs = os.path.abspath(str(stop_at))
    while True:
        curr_abs = os.path.abspath(str(curr))
        try:
            if curr.is_symlink() or os.path.islink(curr_abs):
                return True
            if hasattr(curr, "is_junction") and curr.is_junction():
                return True
        except OSError:
            return True
        if curr_abs == stop_abs or curr.parent == curr:
            break
        curr = curr.parent
    return False

def _open_verified_regular_file(raw_path: Path, resolved_path: Path) -> Optional[tuple[int, int]]:
    """
    SEC-001: Abre o arquivo de forma segura e retorna (fd, st_size) mantendo o descritor
    de arquivo ABERTO para que o envio do conteúdo ocorra diretamente a partir do descritor validado,
    eliminando integralmente a janela de condição de corrida (TOCTOU) entre validação e leitura.
    Realiza:
    1. os.lstat(raw_path) e os.stat(resolved_path) para confirmar que é arquivo regular (não symlink/FIFO/dir)
       e que possui o mesmo inode/device antes da abertura.
    2. os.open(raw_path, O_RDONLY | O_NOFOLLOW | O_BINARY) para obter o descritor real sem seguir symlinks.
    3. os.fstat(fd) no descritor aberto para confirmar que st_ino e st_dev coincidem exatamente com o lstat inicial.
    4. Nova checagem pós-abertura de `_contains_symlink_in_chain` e `os.lstat(raw_path)` para garantir que o caminho
       não foi trocado por um symlink ou outro arquivo durante a chamada `os.open` (especialmente em plataformas sem O_NOFOLLOW).
    Se qualquer verificação falhar, fecha o descritor imediatamente e retorna None.
    """
    fd: Optional[int] = None
    try:
        st_l_before = os.lstat(str(raw_path))
        st_r_before = os.stat(str(resolved_path))
        if stat_mod.S_ISLNK(st_l_before.st_mode) or not stat_mod.S_ISREG(st_l_before.st_mode):
            return None
        if not stat_mod.S_ISREG(st_r_before.st_mode):
            return None
        if (st_l_before.st_ino != st_r_before.st_ino) or (st_l_before.st_dev != st_r_before.st_dev):
            return None

        open_flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        if hasattr(os, "O_BINARY"):
            open_flags |= os.O_BINARY

        fd = os.open(str(raw_path), open_flags)
        st_fd = os.fstat(fd)
        if not stat_mod.S_ISREG(st_fd.st_mode):
            os.close(fd)
            return None
        if (st_fd.st_ino != st_l_before.st_ino) or (st_fd.st_dev != st_l_before.st_dev):
            os.close(fd)
            return None

        # Checagem pós-abertura para plataformas sem O_NOFOLLOW nativo (ex: Windows):
        # confirma que o caminho não virou symlink e continua apontando para o mesmo inode aberto em fd
        if _contains_symlink_in_chain(raw_path, settings.STORAGE_DIR):
            os.close(fd)
            return None
        st_l_after = os.lstat(str(raw_path))
        if stat_mod.S_ISLNK(st_l_after.st_mode) or not stat_mod.S_ISREG(st_l_after.st_mode):
            os.close(fd)
            return None
        if (st_l_after.st_ino != st_fd.st_ino) or (st_l_after.st_dev != st_fd.st_dev):
            os.close(fd)
            return None

        return fd, st_fd.st_size
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        return None

def _verify_regular_file_no_race(raw_path: Path, resolved_path: Path) -> bool:
    """
    SEC-001: Wrapper booleano para verificação de integridade anti-TOCTOU.
    Abre e valida o descritor via `_open_verified_regular_file` e o fecha em seguida.
    """
    opened = _open_verified_regular_file(raw_path, resolved_path)
    if opened is None:
        return False
    fd, _ = opened
    try:
        os.close(fd)
    except OSError:
        pass
    return True

def _stream_from_verified_fd(fd: int, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """
    SEC-001: Gerador que transmite os bytes diretamente a partir do descritor de arquivo `fd`
    já aberto e verificado (nunca reabre pelo nome do caminho no filesystem) e garante o
    fechamento do descritor no bloco `finally`.
    """
    try:
        with os.fdopen(fd, "rb", closefd=True) as file_obj:
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        # Caso os.fdopen não tenha assumido ou fechado fd por alguma falha prévia
        try:
            os.close(fd)
        except OSError:
            pass

def write_atomic_quarantine_manifest(quarantine_path: Path, project_id: str, timestamp_str: str) -> bool:
    """
    STORE-002 / STORE-004: Grava manifesto atômico na quarentena com arquivo temporário,
    flush, os.fsync, os.replace e sincronização de diretório quando suportada.
    Garante schema estrito: version (int >= 1), project_id (str), delete_confirmed (bool True),
    timestamp (str) e folder_name (str).
    Limpa o arquivo temporário caso qualquer etapa falhe.
    """
    random_suffix = uuid.uuid4().hex[:8]
    tmp_meta = quarantine_path / f".tmp_meta_{random_suffix}.tmp"
    target_meta = quarantine_path / ".quarantine_meta.json"
    try:
        if not quarantine_path.exists() or not quarantine_path.is_dir() or quarantine_path.is_symlink():
            logger.error(f"Caminho de quarentena inválido ao gravar manifesto: {quarantine_path}")
            return False

        manifest_data = {
            "version": QUARANTINE_MANIFEST_VERSION,
            "project_id": project_id,
            "delete_confirmed": True,
            "timestamp": timestamp_str,
            "folder_name": quarantine_path.name
        }
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(str(tmp_meta), str(target_meta))
        _sync_directory_if_supported(quarantine_path)
        return True
    except Exception as e:
        logger.error(f"Falha ao escrever manifesto atômico de quarentena para {project_id}: {e}")
        try:
            if tmp_meta.exists():
                tmp_meta.unlink()
        except OSError:
            pass
        return False

def remove_quarantine_path(path_to_remove: Path, expected_project_id: Optional[str] = None) -> bool:
    """
    STORE-003 / STORE-004: Executa a remoção definitiva do diretório em quarentena com validação estrita.
    Regras obrigatórias antes de qualquer exclusão:
    1. Rejeita links simbólicos ou junctions antes de resolver o caminho.
    2. Verifica que `resolved` é estritamente subdiretório direto de `QUARANTINE_DIR`.
    3. Extrai e valida o padrão do nome da pasta (`{project_id}_{timestamp}`) via `parse_quarantine_folder_name`.
    4. Valida integralmente o manifesto `.quarantine_meta.json` via `validate_quarantine_manifest`,
       incluindo `version`, `project_id`, `timestamp`, correspondência com o nome real da pasta e `delete_confirmed is True`.
    5. Em caso de qualquer inconsistência, preserva integralmente os arquivos, registra o motivo e retorna False.
    """
    try:
        raw_target = Path(path_to_remove)
        if _contains_symlink_in_chain(raw_target, settings.QUARANTINE_DIR):
            logger.error(f"Recusando remoção de symlink ou caminho com link na quarentena: {path_to_remove}")
            return False

        resolved = raw_target.resolve()
        quarantine_root = settings.QUARANTINE_DIR.resolve()
        try:
            if (
                os.path.commonpath([str(quarantine_root), str(resolved)]) != str(quarantine_root)
                or resolved == quarantine_root
                or resolved.parent != quarantine_root
            ):
                logger.error(f"Tentativa de remoção de quarentena fora do diretório autorizado: {resolved}")
                return False
        except ValueError:
            return False

        if not resolved.exists():
            return True

        if not resolved.is_dir() or resolved.is_symlink():
            logger.error(f"Alvo de remoção na quarentena não é um diretório regular válido: {resolved}")
            return False

        parsed = parse_quarantine_folder_name(resolved.name)
        if not parsed:
            logger.error(
                f"Abortando purga de '{resolved.name}': nome da pasta não obedece ao padrão '{{project_id}}_{{timestamp}}'. "
                "Arquivos preservados."
            )
            return False

        folder_project_id, _ = parsed
        if expected_project_id is not None and folder_project_id != expected_project_id:
            logger.error(
                f"Abortando purga de '{resolved.name}': project_id da pasta ({folder_project_id}) diverge do esperado ({expected_project_id}). "
                "Arquivos preservados."
            )
            return False

        meta_file = resolved / ".quarantine_meta.json"
        if not validate_quarantine_manifest(
            meta_file,
            expected_project_id=expected_project_id or folder_project_id,
            folder_name=resolved.name
        ):
            logger.error(
                f"Abortando purga de '{resolved.name}': manifesto .quarantine_meta.json ausente, inválido ou divergente. "
                "Arquivos preservados."
            )
            return False

        errors = []
        def _onerror(func, path, exc_info):
            err_val = exc_info[1] if isinstance(exc_info, tuple) else exc_info
            logger.error(f"Erro ao remover item de quarentena {path} em {func}: {err_val}")
            errors.append((path, err_val))

        shutil.rmtree(resolved, onerror=_onerror)
        if errors or resolved.exists():
            logger.error(f"Remoção da quarentena {resolved.name} incompleta ({len(errors)} erros).")
            return False

        logger.info(f"Diretório em quarentena purgado com sucesso: {resolved.name}")
        return True
    except Exception as e:
        logger.error(f"Falha ao purgar diretório de quarentena {path_to_remove}: {e}")
        return False

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
    Exclusão recuperável em duas fases com quarentena e confirmação durável (STORE-001 / STORE-002 / STORE-003 / STORE-004):
    1. Valida formato de project_id e verifica existência do projeto.
    2. Cancela quaisquer jobs ativos do projeto antes de iniciar a exclusão.
    3. Marca projeto como 'deleting' no SQLite para bloquear novos jobs e acessos concorrentes.
    4. Move a pasta física para storage/.quarantine/{id}_{timestamp} de forma isolada.
    5. Grava manifesto atômico de confirmação (.quarantine_meta.json) com fsync ANTES do commit destrutivo no SQLite.
       - Se o manifesto falhar: restaura imediatamente a pasta da quarentena para o storage, reverte status para 'active'
         e retorna HTTP 500, sem jamais apresentar uma operação incompleta como concluída ou deixar dados sem confirmação.
    6. Remove os registros do banco SQLite (Jobs e Projeto) e executa db.commit().
       - Se o commit falhar: faz rollback no SQLite, remove o manifesto, restaura a pasta da quarentena para o storage,
         reverte status para 'active' (se aplicável) e retorna HTTP 500 preservando integralmente os dados.
    7. Agenda a remoção física da pasta em quarentena em background (que valida integralmente o manifesto antes de remover).
    """
    if not SAFE_PROJECT_ID_REGEX.match(project_id) or ".." in project_id:
        raise HTTPException(status_code=400, detail="Identificador de projeto inválido")

    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    if project.status == "deleting":
        raise HTTPException(status_code=409, detail="Projeto já está em processo de exclusão")

    # Cancelar quaisquer jobs ativos do projeto antes da exclusão
    active_jobs = db.query(JobModel).filter(
        JobModel.project_id == project_id,
        JobModel.status.in_([JobStatus.PENDING.value, JobStatus.PREPARING.value, JobStatus.RUNNING.value])
    ).all()
    for active_job in active_jobs:
        try:
            JobOrchestrator.cancel_job(active_job.id)
        except Exception as e:
            logger.warning(f"Erro ao cancelar job {active_job.id} na exclusão do projeto: {e}")

    # Passo 1: Marcação de status no banco para bloqueio
    try:
        project.status = "deleting"
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Falha ao marcar projeto {project_id} como 'deleting': {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao iniciar exclusão do projeto")

    # Caminhos físicos (verificar links simbólicos antes de resolver)
    raw_project_dir = settings.STORAGE_DIR / project_id
    storage_root = settings.STORAGE_DIR.resolve()
    quarantine_root = settings.QUARANTINE_DIR.resolve()
    quarantine_root.mkdir(parents=True, exist_ok=True)

    if raw_project_dir.exists() and _contains_symlink_in_chain(raw_project_dir, settings.STORAGE_DIR):
        project.status = "active"
        db.commit()
        raise HTTPException(status_code=403, detail="Diretório do projeto contém link simbólico não autorizado")

    project_dir = raw_project_dir.resolve()

    # Proteção de segurança: diretório DEVE ser estritamente filho de STORAGE_DIR e não pode ser QUARANTINE_DIR
    try:
        if (
            os.path.commonpath([str(storage_root), str(project_dir)]) != str(storage_root)
            or project_dir == storage_root
            or os.path.commonpath([str(quarantine_root), str(project_dir)]) == str(quarantine_root)
        ):
            project.status = "active"
            db.commit()
            raise HTTPException(status_code=403, detail="Caminho de projeto inválido ou fora do armazenamento autorizado")
    except ValueError:
        project.status = "active"
        db.commit()
        raise HTTPException(status_code=403, detail="Caminho de armazenamento inválido")

    quarantine_subpath: Optional[Path] = None
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    if raw_project_dir.exists():
        quarantine_subpath = (quarantine_root / f"{project_id}_{timestamp_str}").resolve()
        try:
            shutil.move(str(project_dir), str(quarantine_subpath))
            _sync_directory_if_supported(quarantine_root)
            _sync_directory_if_supported(storage_root)
        except Exception as e:
            logger.error(f"Falha ao mover diretório do projeto {project_id} para quarentena: {e}")
            try:
                project.status = "active"
                db.commit()
            except Exception:
                db.rollback()
            raise HTTPException(status_code=500, detail=f"Falha ao isolar arquivos em quarentena: {str(e)}")

        # Passo 2 (STORE-002): Gravar e sincronizar manifesto atômico ANTES de remover do SQLite.
        # Se falhar, reverter imediatamente a movimentação e abortar com erro 500 (nunca fingir sucesso).
        manifest_ok = write_atomic_quarantine_manifest(quarantine_subpath, project_id, timestamp_str)
        if not manifest_ok:
            logger.error(f"Falha crítica ao gravar manifesto de quarentena para {project_id}. Revertendo exclusão.")
            try:
                shutil.move(str(quarantine_subpath), str(project_dir))
                project.status = "active"
                db.commit()
            except Exception as rev_err:
                db.rollback()
                logger.critical(
                    f"Erro ao reverter quarentena após falha de manifesto para {project_id}: {rev_err}. "
                    f"Dados preservados em {quarantine_subpath} com status 'deleting'."
                )
            raise HTTPException(
                status_code=500,
                detail="Não foi possível confirmar durabilidade do manifesto de quarentena. Operação abortada e dados preservados."
            )

    # Passo 3 (STORE-003): Deleção e commit no SQLite
    try:
        db.query(JobModel).filter(JobModel.project_id == project_id).delete()
        db.delete(project)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Falha no commit SQLite ao excluir projeto {project_id}: {e}")
        # Rollback da quarentena: remover manifesto de confirmação antes de restaurar
        if quarantine_subpath and quarantine_subpath.exists():
            meta_path = quarantine_subpath / ".quarantine_meta.json"
            try:
                if meta_path.exists():
                    meta_path.unlink()
                    _sync_directory_if_supported(quarantine_subpath)
            except OSError as unlink_err:
                logger.critical(f"Falha ao invalidar manifesto durante rollback de {project_id}: {unlink_err}")

            try:
                shutil.move(str(quarantine_subpath), str(project_dir))
                _sync_directory_if_supported(storage_root)
            except Exception as move_back_err:
                logger.critical(
                    f"Falha ao restaurar pasta da quarentena após erro de banco para {project_id}: {move_back_err}. "
                    f"Pasta preservada em {quarantine_subpath}."
                )

        # Restaurar status para 'active' somente se os arquivos voltaram para project_dir (ou se o projeto não tinha pasta)
        try:
            proj_revert = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
            if proj_revert:
                if project_dir.exists() or quarantine_subpath is None:
                    proj_revert.status = "active"
                else:
                    # Permanece 'deleting' (sem manifesto) para que a reconciliação tente restaurar depois
                    proj_revert.status = "deleting"
                db.commit()
        except Exception as rev_db_err:
            db.rollback()
            logger.error(f"Não foi possível atualizar status após rollback de {project_id}: {rev_db_err}")

        raise HTTPException(status_code=500, detail=f"Falha na exclusão do banco de dados: {str(e)}")

    # Passo 4: Agendamento seguro da remoção definitiva em background
    if quarantine_subpath and quarantine_subpath.exists():
        background_tasks.add_task(remove_quarantine_path, quarantine_subpath, project_id)

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

def _collect_registered_project_filenames(db: Session, project: ProjectModel) -> set[str]:
    """
    SEC-001: Coleta o conjunto estrito de nomes de arquivos registrados para um projeto ativo
    a partir de active_model_path e result_files_json dos jobs do próprio projeto.
    Ignora entradas com traversal ou fora do diretório do projeto.
    """
    registered_files: set[str] = set()
    if project.active_model_path:
        norm = str(project.active_model_path).replace("\\", "/")
        if ".." not in norm:
            registered_files.add(Path(norm).name)

    jobs = db.query(JobModel).filter(JobModel.project_id == project.id).all()
    for j in jobs:
        try:
            files = json.loads(j.result_files_json or "[]")
            if isinstance(files, list):
                for f in files:
                    if isinstance(f, str):
                        norm_f = f.replace("\\", "/")
                        if ".." not in norm_f:
                            registered_files.add(Path(norm_f).name)
        except Exception:
            pass
    return registered_files

@router.get("/projects/{project_id}/artifacts/{filename}")
def download_artifact(project_id: str, filename: str, db: Session = Depends(get_db)):
    """
    Endpoint contextual seguro para download de artefatos vinculados ao projeto (SEC-001 / Task 1.1).
    Validações:
    1. project_id e filename devem obedecer padrões alfanuméricos estritos (sem barras, .. ou nulos).
    2. O projeto deve existir no banco de dados e estar com status 'active'.
    3. O caminho original (não resolvido) é inspecionado ANTES de resolve() para impedir links simbólicos
       (mesmo quando o symlink aponta para um arquivo válido dentro do mesmo projeto).
    4. Após resolve(), valida confinamento estrito dentro de storage/projects/{project_id} via os.path.commonpath.
    5. Confirma que o arquivo consta nos artefatos registrados do projeto.
    6. Abre e mantém o descritor de arquivo validado (`_open_verified_regular_file`) e transmite o conteúdo
       diretamente a partir desse descritor (`_stream_from_verified_fd`), eliminando qualquer condição de corrida
       (TOCTOU) entre a verificação de segurança e a leitura dos bytes enviados ao cliente.
    """
    if not SAFE_PROJECT_ID_REGEX.match(project_id) or ".." in project_id or "\x00" in project_id:
        raise HTTPException(status_code=400, detail="Identificador de projeto inválido")

    if not SAFE_FILENAME_REGEX.match(filename) or ".." in filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido ou contém caracteres não permitidos")

    if filename.startswith(".quarantine_meta") or Path(filename).suffix.lower() in [".db", ".sqlite", ".py"]:
        raise HTTPException(status_code=403, detail="Acesso a arquivos internos do sistema é proibido")

    # Validação do projeto no banco
    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project or project.status == "deleting":
        raise HTTPException(status_code=404, detail="Projeto não encontrado ou em processo de exclusão")

    # Caminho original ANTES de resolve() — rejeita symlinks em qualquer nível
    raw_project_dir = settings.STORAGE_DIR / project_id
    raw_target_path = raw_project_dir / filename

    if _contains_symlink_in_chain(raw_target_path, settings.STORAGE_DIR):
        raise HTTPException(status_code=403, detail="Links simbólicos não são permitidos para download de artefatos")

    if not raw_target_path.exists() or raw_target_path.is_dir():
        raise HTTPException(status_code=404, detail="Artefato não encontrado")

    # Resolução segura de caminhos e validação de pertencimento
    storage_root = settings.STORAGE_DIR.resolve()
    quarantine_root = settings.QUARANTINE_DIR.resolve()
    project_dir = raw_project_dir.resolve()
    target_path = raw_target_path.resolve()

    try:
        if os.path.commonpath([str(storage_root), str(project_dir)]) != str(storage_root) or project_dir == storage_root:
            raise HTTPException(status_code=403, detail="Acesso não autorizado")
        if os.path.commonpath([str(quarantine_root), str(target_path)]) == str(quarantine_root):
            raise HTTPException(status_code=403, detail="Acesso a arquivos de quarentena é proibido")
        if os.path.commonpath([str(project_dir), str(target_path)]) != str(project_dir) or target_path == project_dir:
            raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do projeto")
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    # Garantia de que é arquivo direto na raiz da pasta do projeto
    if target_path.parent != project_dir or target_path.name != filename:
        raise HTTPException(status_code=403, detail="Acesso não autorizado a subdiretórios ou links")

    # Validação de registro nos artefatos do projeto
    registered_files = _collect_registered_project_filenames(db, project)
    if filename not in registered_files:
        raise HTTPException(status_code=403, detail="Arquivo solicitado não está registrado como artefato deste projeto")

    # Abrir e vincular o descritor de arquivo validado (sem fechá-lo antes do envio!)
    opened = _open_verified_regular_file(raw_target_path, target_path)
    if opened is None:
        raise HTTPException(status_code=403, detail="Falha na verificação de integridade do arquivo (possível symlink ou alteração concorrente)")

    verified_fd, verified_size = opened
    suffix = target_path.suffix.lower()
    media_type = "model/gltf-binary" if suffix == ".glb" else "text/plain" if suffix == ".obj" else "application/octet-stream"

    headers = {
        "Content-Disposition": f'attachment; filename="{target_path.name}"',
        "Content-Length": str(verified_size)
    }
    return StreamingResponse(
        _stream_from_verified_fd(verified_fd),
        media_type=media_type,
        headers=headers
    )

# Rota mantida estritamente com autorização contextual idêntica para compatibilidade com o frontend atual
@router.get("/files/download")
def download_file_legacy(path: str = Query(..., description="Caminho relativo seguro do arquivo"), db: Session = Depends(get_db)):
    """
    SEC-001: Rota legada protegida com verificação contextual estrita idêntica a download_artifact.
    - Inspeciona o caminho original antes de resolve() para bloquear qualquer symlink (mesmo intra-projeto).
    - Exige confinamento direto em STORAGE_DIR/{project_id}/{filename}.
    - Bloqueia diretórios internos, quarentena, arquivos de sistema e artefatos não registrados.
    - Delega o envio para `download_artifact`, transmitindo diretamente do descritor validado sem condição de corrida.
    """
    if not path or not isinstance(path, str):
        raise HTTPException(status_code=400, detail="Caminho inválido")

    raw_path_str = str(path).strip().replace("\\", "/")
    if not raw_path_str or "\x00" in raw_path_str:
        raise HTTPException(status_code=400, detail="Caminho inválido ou contém caracteres nulos")

    raw_p = Path(raw_path_str)
    if ".." in raw_p.parts or ".." in raw_path_str:
        raise HTTPException(status_code=400, detail="Caminho inválido ou contém sequências de traversal não permitidas")

    storage_root = settings.STORAGE_DIR.resolve()
    quarantine_root = settings.QUARANTINE_DIR.resolve()

    # Determinar caminho original não resolvido (candidate_raw) para checar symlinks ANTES de resolve()
    if raw_p.is_absolute():
        candidate_raw = raw_p
        try:
            if os.path.commonpath([str(storage_root), os.path.abspath(str(candidate_raw))]) != str(storage_root):
                raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do armazenamento de projetos")
        except ValueError:
            raise HTTPException(status_code=403, detail="Acesso não autorizado")
    else:
        # Se começar com o nome da pasta de storage (ex: "projects/proj-xxx/model.glb"), ancorar em BASE_DIR
        if len(raw_p.parts) >= 2 and raw_p.parts[0] == settings.STORAGE_DIR.name:
            candidate_raw = settings.BASE_DIR / raw_p
        else:
            candidate_raw = settings.STORAGE_DIR / raw_p

    # Verificar symlinks na cadeia original ANTES de resolver
    if _contains_symlink_in_chain(candidate_raw, settings.STORAGE_DIR):
        raise HTTPException(status_code=403, detail="Links simbólicos não são permitidos para download")

    clean_path = candidate_raw.resolve()

    # O arquivo deve estar obrigatoriamente dentro de STORAGE_DIR
    try:
        if os.path.commonpath([str(storage_root), str(clean_path)]) != str(storage_root) or clean_path == storage_root:
            raise HTTPException(status_code=403, detail="Acesso não autorizado a caminho fora do armazenamento de projetos")
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    # Bloquear quarentena
    try:
        if os.path.commonpath([str(quarantine_root), str(clean_path)]) == str(quarantine_root):
            raise HTTPException(status_code=403, detail="Acesso a arquivos de quarentena é proibido")
    except ValueError:
        pass

    # Mapear estritamente para {project_id}/{filename} dentro de STORAGE_DIR
    try:
        rel_to_storage = clean_path.relative_to(storage_root)
        parts = rel_to_storage.parts
        if len(parts) != 2:
            raise HTTPException(status_code=403, detail="Caminho deve referenciar diretamente um artefato de projeto válido")
        project_id, filename = parts[0], parts[1]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Caminho não pôde ser mapeado a um projeto")

    # Delegar para a mesma validação e transmissão por descritor aberto de download_artifact
    return download_artifact(project_id=project_id, filename=filename, db=db)
