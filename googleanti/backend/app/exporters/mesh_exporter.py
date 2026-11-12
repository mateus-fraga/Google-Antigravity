import os
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import trimesh

class ModelExporter:
    """
    Serviço de exportação e validação de malhas em GLB, OBJ e STL.
    Executa escrita atômica via arquivo temporário (.tmp.<fmt>) com fsync + os.replace,
    checkpoints cooperativos de cancelamento e testes de integridade pós-exportação
    (existência, tamanho mínimo e reimportação).
    """

    SUPPORTED_FORMATS = ["glb", "gltf", "obj", "stl"]

    @classmethod
    def export_and_validate(
        cls,
        mesh: trimesh.Trimesh,
        output_path: Path | str,
        fmt: str = "glb",
        cancel_check: Optional[Callable[[], None]] = None
    ) -> Dict[str, Any]:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = fmt.lower().lstrip(".")

        if fmt not in cls.SUPPORTED_FORMATS:
            raise ValueError(f"Formato não suportado: {fmt}. Formatos válidos: {cls.SUPPORTED_FORMATS}")

        if cancel_check is not None:
            cancel_check()

        # Gerar arquivo temporário isolado na mesma pasta para escrita atômica e fácil limpeza em cancelamento
        tmp_suffix = uuid.uuid4().hex[:8]
        tmp_path = output_path.parent / f".{output_path.stem}_{tmp_suffix}.tmp.{fmt}"

        try:
            # 1. Serializar malha em memória
            export_bytes = mesh.export(file_type=fmt)

            if cancel_check is not None:
                cancel_check()

            # 2. Gravar no arquivo temporário com flush e fsync
            if isinstance(export_bytes, str):
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(export_bytes)
                    f.flush()
                    os.fsync(f.fileno())
            else:
                with open(tmp_path, "wb") as f:
                    f.write(export_bytes)
                    f.flush()
                    os.fsync(f.fileno())

            if cancel_check is not None:
                cancel_check()

            # 3. Validar arquivo temporário antes de publicar no caminho final
            if not tmp_path.exists():
                raise FileNotFoundError(f"Arquivo temporário exportado não encontrado em: {tmp_path}")

            file_size = tmp_path.stat().st_size
            if file_size == 0:
                raise ValueError(f"Arquivo exportado está vazio (0 bytes): {tmp_path}")

            # 4. Reimportar a partir do arquivo temporário para conferência de integridade geométrica
            reloaded = trimesh.load(str(tmp_path), file_type=fmt)
            if isinstance(reloaded, trimesh.Scene):
                if len(reloaded.geometry) == 0:
                    raise ValueError("Cena reimportada não contém geometrias válidas.")
                reloaded_mesh = trimesh.util.concatenate(list(reloaded.geometry.values()))
            else:
                reloaded_mesh = reloaded

            reloaded_vertex_count = len(reloaded_mesh.vertices)
            reloaded_face_count = len(reloaded_mesh.faces)

            if cancel_check is not None:
                cancel_check()

            # 5. Promover atomicamente o temporário validado para o caminho final
            os.replace(str(tmp_path), str(output_path))

            return {
                "file_path": str(output_path),
                "format": fmt,
                "file_size_bytes": file_size,
                "original_faces": len(mesh.faces),
                "reloaded_faces": reloaded_face_count,
                "original_vertices": len(mesh.vertices),
                "reloaded_vertices": reloaded_vertex_count,
                "validated": True
            }
        except BaseException:
            # Garantir limpeza imediata do arquivo temporário parcial em qualquer erro ou cancelamento
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
