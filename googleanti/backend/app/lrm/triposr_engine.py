"""
Motor LRM nativo (TripoSR) — reconstrução 3D orgânica a partir de uma única imagem.

Todas as dependências pesadas (torch, tsr, rembg) são importadas de forma preguiçosa,
de modo que o restante da aplicação (e a suíte de testes) funciona sem elas instaladas.
Consulte `docs/TRIPOSR_INSTALL.md` para o plano de instalação.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import trimesh
from PIL import Image

_LRM_DIR = str(Path(__file__).resolve().parent)
if _LRM_DIR not in sys.path:
    sys.path.insert(0, _LRM_DIR)

logger = logging.getLogger(__name__)

MODEL_REPO = "stabilityai/TripoSR"


class TripoSRUnavailableError(RuntimeError):
    """Dependências do TripoSR ausentes ou modelo não carregável."""


class TripoSREngine:
    """Singleton lazy: o modelo é carregado uma única vez e reutilizado entre jobs."""

    _instance: Optional["TripoSREngine"] = None
    _lock = threading.Lock()

    DEFAULT_MCUBES_RESOLUTION = 256
    FOREGROUND_RATIO = 0.85
    TARGET_SIZE_M = 1.0

    def __init__(self, device: Optional[str] = None, chunk_size: int = 8192):
        try:
            import torch
            from tsr.system import TSR
        except ImportError as exc:
            raise TripoSRUnavailableError(
                "Dependências do TripoSR não instaladas (torch/tsr). Veja docs/TRIPOSR_INSTALL.md."
            ) from exc

        self._torch = torch
        if device is None:
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch.cuda.is_available():
            logger.warning("CUDA indisponível; usando CPU (inferência será lenta).")
            device = "cpu"
        self.device = device

        logger.info("Carregando %s em %s ...", MODEL_REPO, self.device)
        self.model = TSR.from_pretrained(
            MODEL_REPO,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        self.model.renderer.set_chunk_size(chunk_size)
        self.model.to(self.device)
        self._rembg_session: Any = None

    @classmethod
    def get_instance(cls) -> "TripoSREngine":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _remove_background(self, image: Image.Image) -> Image.Image:
        from tsr.utils import resize_foreground

        try:
            import rembg

            if self._rembg_session is None:
                self._rembg_session = rembg.new_session()
            rgba = rembg.remove(image.convert("RGB"), session=self._rembg_session)
        except ImportError:
            logger.warning(
                "rembg não disponível neste ambiente Python; utilizando segmentação local OpenCV/Alpha como fallback."
            )
            if image.mode == "RGBA" and image.getextrema()[3][0] < 255:
                rgba = image
            else:
                from backend.app.procedural.image_to_3d import ImageTo3DGenerator

                rgb_img = image.convert("RGBA")
                mask = ImageTo3DGenerator._extract_binary_mask(rgb_img)
                # `_extract_binary_mask` adiciona borda de 2px e limita a dimensão em [16, 512]
                if mask.shape[0] > 4 and mask.shape[1] > 4:
                    mask = mask[2:-2, 2:-2]
                if mask.shape != (rgb_img.height, rgb_img.width):
                    mask = np.asarray(
                        Image.fromarray(mask, mode="L").resize(rgb_img.size, Image.Resampling.NEAREST),
                        dtype=np.uint8,
                    )
                if np.count_nonzero(mask) == 0:
                    mask = np.full((rgb_img.height, rgb_img.width), 255, dtype=np.uint8)
                rgba_arr = np.asarray(rgb_img).copy()
                rgba_arr[:, :, 3] = mask
                rgba = Image.fromarray(rgba_arr, mode="RGBA")

        rgba = resize_foreground(rgba, self.FOREGROUND_RATIO)
        arr = np.asarray(rgba).astype(np.float32) / 255.0
        arr = arr[:, :, :3] * arr[:, :, 3:4] + (1.0 - arr[:, :, 3:4]) * 0.5
        return Image.fromarray((arr * 255.0).astype(np.uint8))

    @classmethod
    def _normalize_mesh(cls, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        mesh = mesh.copy()
        if mesh.is_empty or not np.all(np.isfinite(mesh.vertices)):
            raise ValueError("TripoSR gerou uma malha vazia ou com vértices inválidos.")
        extent = float(np.max(mesh.extents))
        if extent <= 0:
            raise ValueError("TripoSR gerou uma malha degenerada.")
        mesh.apply_scale(cls.TARGET_SIZE_M / extent)
        lo, hi = mesh.bounds
        mesh.apply_translation([
            -(lo[0] + hi[0]) / 2.0,
            -lo[1],
            -(lo[2] + hi[2]) / 2.0,
        ])
        mesh.metadata["coordinate_system"] = "Y-up"
        mesh.metadata["geometry_schema_version"] = 2
        mesh.metadata["image_to_3d_mode"] = "triposr"
        return mesh

    def generate_mesh_from_image(
        self,
        image_path: Path,
        mcubes_resolution: int = DEFAULT_MCUBES_RESOLUTION,
        remove_background: bool = True,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> trimesh.Trimesh:
        check = cancel_check or (lambda: None)
        check()
        with Image.open(image_path) as img:
            image = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            image.load()

        if remove_background:
            image = self._remove_background(image)
        else:
            image = image.convert("RGB")

        check()
        torch = self._torch
        with torch.no_grad():
            scene_codes = self.model([image], device=self.device)
            check()
            meshes = self.model.extract_mesh(
                scene_codes,
                has_vertex_color=True,
                resolution=int(mcubes_resolution),
            )
        check()
        if self.device.startswith("cuda"):
            torch.cuda.empty_cache()

        mesh = meshes[0]

        # 1. Unir vértices duplicados ou muito próximos (corrige quebras no shading)
        mesh.merge_vertices(merge_tex=True, merge_norm=True)

        # 2. Remover faces degeneradas (triângulos com área zero)
        if hasattr(mesh, "remove_degenerate_faces"):
            mesh.remove_degenerate_faces()
        else:
            mesh.update_faces(mesh.nondegenerate_faces())
            mesh.remove_unreferenced_vertices()

        # 3. Recalcular as normais (garante que a luz reage corretamente na superfície exterior)
        mesh.fix_normals()

        # 4. Remover artefactos e pedaços soltos de geometria (mantém apenas o corpo principal)
        componentes = mesh.split(only_watertight=False)
        if componentes:
            mesh = max(componentes, key=lambda m: len(m.faces))

        # 5. Converter da convenção nativa do TripoSR (Z-up, frente em +X) para Y-up (frente em +Z)
        rot_x = trimesh.transformations.rotation_matrix(np.radians(-90.0), [1.0, 0.0, 0.0])
        rot_y = trimesh.transformations.rotation_matrix(np.radians(90.0), [0.0, 1.0, 0.0])
        mesh.apply_transform(rot_x)
        mesh.apply_transform(rot_y)

        # 6. Escalar para 1.0m, centralizar XZ na origem e assentar a base no chão (Y_min = 0.0)
        return self._normalize_mesh(mesh)
