import os
from pathlib import Path
from typing import Dict, Any, Tuple
import trimesh

class ModelExporter:
    """
    Serviço de exportação e validação de malhas em GLB, OBJ e STL.
    Executa testes de integridade pós-exportação (existência, tamanho mínimo e reimportação).
    """

    SUPPORTED_FORMATS = ["glb", "gltf", "obj", "stl"]

    @classmethod
    def export_and_validate(
        cls,
        mesh: trimesh.Trimesh,
        output_path: Path | str,
        fmt: str = "glb"
    ) -> Dict[str, Any]:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = fmt.lower().lstrip(".")

        if fmt not in cls.SUPPORTED_FORMATS:
            raise ValueError(f"Formato não suportado: {fmt}. Formatos válidos: {cls.SUPPORTED_FORMATS}")

        # Realizar exportação
        export_bytes = mesh.export(file_type=fmt)
        if isinstance(export_bytes, str):
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(export_bytes)
        else:
            with open(output_path, "wb") as f:
                f.write(export_bytes)

        # Validação pós-exportação
        if not output_path.exists():
            raise FileNotFoundError(f"Arquivo exportado não encontrado em: {output_path}")

        file_size = output_path.stat().st_size
        if file_size == 0:
            raise ValueError(f"Arquivo exportado está vazio (0 bytes): {output_path}")

        # Reimportar para conferência de geometria
        reloaded = trimesh.load(str(output_path), file_type=fmt)
        if isinstance(reloaded, trimesh.Scene):
            # Se carregado como Scene (comum para GLB/glTF), converter para Trimesh combinado
            if len(reloaded.geometry) == 0:
                raise ValueError("Cena reimportada não contém geometrias válidas.")
            reloaded_mesh = trimesh.util.concatenate(list(reloaded.geometry.values()))
        else:
            reloaded_mesh = reloaded

        reloaded_vertex_count = len(reloaded_mesh.vertices)
        reloaded_face_count = len(reloaded_mesh.faces)

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
