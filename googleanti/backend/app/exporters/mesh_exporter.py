import os
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Callable
import numpy as np
import trimesh

class ModelExporter:
    """
    Serviço de exportação e validação de malhas em GLB, OBJ e STL.
    Executa escrita atômica via arquivo temporário (.tmp.<fmt>) com fsync + os.replace,
    checkpoints cooperativos de cancelamento e testes de integridade pós-exportação
    (existência, tamanho mínimo, reimportação round-trip, finitude numérica e preservação
    das dimensões / bounding box em convenção Y-up).
    """

    SUPPORTED_FORMATS = ["glb", "gltf", "obj", "stl"]

    @classmethod
    def export_and_validate(
        cls,
        mesh: trimesh.Trimesh,
        output_path: Path | str,
        fmt: str = "glb",
        cancel_check: Optional[Callable[[], None]] = None,
        job_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if mesh is None or mesh.is_empty:
            raise ValueError("Não é possível exportar uma malha nula ou vazia.")
        if not np.all(np.isfinite(mesh.vertices)):
            raise ValueError("A malha de origem contém vértices não finitos (NaN/Inf).")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = fmt.lower().lstrip(".")

        if fmt not in cls.SUPPORTED_FORMATS:
            raise ValueError(f"Formato não suportado: {fmt}. Formatos válidos: {cls.SUPPORTED_FORMATS}")

        if cancel_check is not None:
            cancel_check()

        orig_bounds = np.array(mesh.bounds, dtype=np.float64)
        orig_extents = np.array(mesh.extents, dtype=np.float64)

        # Gerar arquivo temporário isolado por job_id na mesma pasta para escrita atômica e limpeza isolada
        tmp_suffix = uuid.uuid4().hex[:8]
        job_tag = f"_{job_id}" if job_id else ""
        tmp_path = output_path.parent / f".{output_path.stem}{job_tag}_{tmp_suffix}.tmp.{fmt}"

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

            # 4. Reimportar a partir do arquivo temporário para conferência round-trip de integridade geométrica
            reloaded = trimesh.load(str(tmp_path), file_type=fmt)
            if isinstance(reloaded, trimesh.Scene):
                if len(reloaded.geometry) == 0:
                    raise ValueError("Cena reimportada não contém geometrias válidas.")
                reloaded_mesh = reloaded.to_geometry() if hasattr(reloaded, "to_geometry") else trimesh.util.concatenate(list(reloaded.geometry.values()))
            else:
                reloaded_mesh = reloaded

            reloaded_vertex_count = int(len(reloaded_mesh.vertices))
            reloaded_face_count = int(len(reloaded_mesh.faces))
            if reloaded_vertex_count == 0 or reloaded_face_count == 0:
                raise ValueError(f"Geometria reimportada ({fmt}) não possui vértices ou faces válidos.")

            if not np.all(np.isfinite(reloaded_mesh.vertices)):
                raise ValueError(f"Geometria reimportada ({fmt}) contém vértices não finitos (NaN/Inf).")

            reloaded_bounds = np.array(reloaded_mesh.bounds, dtype=np.float64)
            reloaded_extents = np.array(reloaded_mesh.extents, dtype=np.float64)

            # Verificar que o round-trip preservou as dimensões nos 3 eixos (X, Y, Z) e os bounds sem rotações espúrias
            if not np.allclose(orig_extents, reloaded_extents, rtol=1e-3, atol=1e-4):
                raise ValueError(
                    f"Divergência dimensional no round-trip ({fmt}): "
                    f"original={orig_extents.tolist()} vs reimportado={reloaded_extents.tolist()}"
                )
            if not np.allclose(orig_bounds, reloaded_bounds, rtol=1e-3, atol=1e-4):
                raise ValueError(
                    f"Divergência de bounding box/orientação no round-trip ({fmt}): "
                    f"original={orig_bounds.tolist()} vs reimportado={reloaded_bounds.tolist()}"
                )

            if cancel_check is not None:
                cancel_check()

            # 5. Promover atomicamente o temporário validado para o caminho final
            os.replace(str(tmp_path), str(output_path))

            meta = mesh.metadata if isinstance(getattr(mesh, "metadata", None), dict) else {}
            coord_sys = meta.get("coordinate_system", "Y-up")
            schema_ver = int(meta.get("geometry_schema_version", 2))

            return {
                "file_path": str(output_path),
                "format": fmt,
                "file_size_bytes": file_size,
                "original_faces": int(len(mesh.faces)),
                "reloaded_faces": reloaded_face_count,
                "original_vertices": int(len(mesh.vertices)),
                "reloaded_vertices": reloaded_vertex_count,
                "original_extents": orig_extents.tolist(),
                "reloaded_extents": reloaded_extents.tolist(),
                "reloaded_bounds": reloaded_bounds.tolist(),
                "coordinate_system": coord_sys,
                "geometry_schema_version": schema_ver,
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

