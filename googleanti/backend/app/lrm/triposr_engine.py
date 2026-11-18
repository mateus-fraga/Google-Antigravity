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
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import trimesh
from PIL import Image
from scipy.spatial import cKDTree

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
    def _align_mesh_upright(
        cls,
        mesh: trimesh.Trimesh,
        geometric_constraints: Dict[str, Any],
    ) -> Tuple[trimesh.Trimesh, np.ndarray]:
        """
        Endireitamento determinístico baseado no envelope externo + plano da base do Convex Hull
        (substitui PCA global, evitando distorção por proporção 1:1 e cavidades internas assimétricas):
        1. Se `is_symmetrical=True` e `primary_axis == "vertical"`: calcula os centros das
           bounding boxes 2D `(min_x+max_x)/2, (min_z+max_z)/2` em fatias horizontais (15%–85% de Y)
           para ignorar vértices da cavidade interna, ajusta a reta central via SVD e alinha a `[0, 1, 0]`.
        2. Se `needs_flat_base=True`: refina o assentamento usando a normal ponderada por área² das
           faces inferiores do `convex_hull` (`normal_y < -0.70`, 15% inferiores de Y) para deixar a base
           paralela ao plano XZ.
        Retorna `(mesh_alinhado, matriz_rotacao_acumulada_4x4)`.
        """
        mesh = mesh.copy()
        r_total = np.eye(4, dtype=np.float64)
        y_axis = np.array([0.0, 1.0, 0.0], dtype=np.float64)

        is_symmetrical = bool(geometric_constraints.get("is_symmetrical", False))
        needs_flat_base = bool(geometric_constraints.get("needs_flat_base", False))
        primary_axis = str(geometric_constraints.get("primary_axis", "vertical")).strip().lower()

        # Etapa 1: Alinhamento iterativo pelo eixo central do envelope externo (2D Slice BBox Centers)
        if is_symmetrical and primary_axis == "vertical":
            for _ in range(5):
                verts = np.asarray(mesh.vertices, dtype=np.float64)
                if len(verts) < 8 or not np.all(np.isfinite(verts)):
                    break
                y_min, y_max = float(verts[:, 1].min()), float(verts[:, 1].max())
                span = y_max - y_min
                if span <= 1e-6:
                    break

                edges = np.linspace(y_min + 0.15 * span, y_min + 0.85 * span, 8)
                centers = []
                for y0, y1 in zip(edges[:-1], edges[1:]):
                    mask = (verts[:, 1] >= y0) & (verts[:, 1] <= y1)
                    if np.count_nonzero(mask) < 4:
                        continue
                    sl = verts[mask]
                    cx = 0.5 * (float(sl[:, 0].min()) + float(sl[:, 0].max()))
                    cz = 0.5 * (float(sl[:, 2].min()) + float(sl[:, 2].max()))
                    cy = 0.5 * (float(y0) + float(y1))
                    centers.append([cx, cy, cz])

                # Fallback para malhas esparsas nas laterais (ex.: cilindros low-poly) via amostragem de superfície
                if len(centers) < 3 and len(mesh.faces) > 0:
                    try:
                        sampled = np.asarray(mesh.sample(2048), dtype=np.float64)
                        centers = []
                        for y0, y1 in zip(edges[:-1], edges[1:]):
                            mask = (sampled[:, 1] >= y0) & (sampled[:, 1] <= y1)
                            if np.count_nonzero(mask) < 4:
                                continue
                            sl = sampled[mask]
                            cx = 0.5 * (float(sl[:, 0].min()) + float(sl[:, 0].max()))
                            cz = 0.5 * (float(sl[:, 2].min()) + float(sl[:, 2].max()))
                            cy = 0.5 * (float(y0) + float(y1))
                            centers.append([cx, cy, cz])
                    except Exception:
                        centers = []

                if len(centers) < 3:
                    break

                c_arr = np.asarray(centers, dtype=np.float64)
                c_centered = c_arr - c_arr.mean(axis=0, keepdims=True)
                try:
                    _, _, vt = np.linalg.svd(c_centered, full_matrices=False)
                except Exception:
                    break

                axis_vec = vt[0].copy()
                if float(axis_vec[1]) < 0.0:
                    axis_vec = -axis_vec
                axis_norm = float(np.linalg.norm(axis_vec))
                if axis_norm <= 1e-8:
                    break
                axis_vec = axis_vec / axis_norm

                angle_deg = float(np.degrees(np.arccos(np.clip(axis_vec[1], -1.0, 1.0))))
                if angle_deg < 0.15 or angle_deg > 40.0:
                    break

                rot_step = trimesh.geometry.align_vectors(axis_vec, y_axis)
                mesh.apply_transform(rot_step)
                r_total = rot_step @ r_total

        # Etapa 2: Refinamento pelo plano inferior do Convex Hull (faces com normal_y < -0.70)
        if needs_flat_base:
            try:
                hull = mesh.convex_hull
                fn = np.asarray(hull.face_normals, dtype=np.float64)
                fc = np.asarray(hull.triangles_center, dtype=np.float64)
                fa = np.asarray(hull.area_faces, dtype=np.float64)
                y_min_h, y_max_h = float(hull.bounds[0][1]), float(hull.bounds[1][1])
                h_span = y_max_h - y_min_h
                if h_span > 1e-6 and len(fn) > 0:
                    bot_mask = (fn[:, 1] < -0.70) & (fc[:, 1] <= y_min_h + 0.15 * h_span)
                    if np.any(bot_mask):
                        weights = fa[bot_mask] ** 2
                        avg_normal = (fn[bot_mask] * weights[:, None]).sum(axis=0)
                        norm_val = float(np.linalg.norm(avg_normal))
                        if norm_val > 1e-8:
                            up_from_base = -(avg_normal / norm_val)
                            angle_deg = float(np.degrees(np.arccos(np.clip(up_from_base[1], -1.0, 1.0))))
                            if 0.1 < angle_deg <= 35.0:
                                rot_base = trimesh.geometry.align_vectors(up_from_base, y_axis)
                                mesh.apply_transform(rot_base)
                                r_total = rot_base @ r_total
            except Exception as exc:
                logger.warning("Refinamento de plano de base via Convex Hull ignorado: %s", exc)

        return mesh, r_total

    @classmethod
    def _apply_hybrid_geometric_postprocessing(
        cls,
        mesh: trimesh.Trimesh,
        geometric_constraints: Dict[str, Any],
    ) -> trimesh.Trimesh:
        """
        Pós-processamento Neuro-Simbólico (Smart Alignment & Watertight Slicing):
        1. Backup de coordenadas e `vertex_colors` (`COLOR_0`).
        2. Endireitamento pelo envelope externo (centros 2D de fatias) + refinamento do plano
           inferior do `convex_hull` via `_align_mesh_upright`.
        3. Corte estanque (`cap=True`) dos 3% inferiores quando `needs_flat_base=True`,
           recalculando normais e restaurando `vertex_colors` via `scipy.spatial.cKDTree`.
        """
        mesh = mesh.copy()

        # 1. Backup de Cores de Vértice (COLOR_0) e coordenadas espaciais
        orig_vertices = np.asarray(mesh.vertices, dtype=np.float64).copy()
        orig_colors: Optional[np.ndarray] = None
        raw_vc = getattr(getattr(mesh, "visual", None), "vertex_colors", None)
        if raw_vc is not None:
            vc_arr = np.asarray(raw_vc)
            if vc_arr.ndim == 2 and len(vc_arr) == len(orig_vertices) and vc_arr.shape[1] in (3, 4):
                orig_colors = vc_arr.copy()

        # 2. Correção de Inclinação (Envelope Externo / Fatias 2D + Plano de Base do Convex Hull)
        mesh, rot_align = cls._align_mesh_upright(mesh, geometric_constraints)
        if not np.allclose(rot_align, np.eye(4)):
            orig_vertices = trimesh.transformations.transform_points(orig_vertices, rot_align)

        # 3. Corte Matemático de Base Estanque (needs_flat_base)
        if bool(geometric_constraints.get("needs_flat_base", False)):
            min_y = float(mesh.bounds[0][1])
            shift_y = np.array([0.0, -min_y, 0.0], dtype=np.float64)
            mesh.apply_translation(shift_y)
            orig_vertices = orig_vertices + shift_y

            height = float(mesh.bounds[1][1] - mesh.bounds[0][1])
            if height > 1e-6:
                slice_y = height * 0.03
                sliced: Optional[trimesh.Trimesh] = None
                try:
                    sliced = trimesh.intersections.slice_mesh_plane(
                        mesh,
                        plane_normal=[0.0, 1.0, 0.0],
                        plane_origin=[0.0, slice_y, 0.0],
                        cap=True,
                    )
                except Exception as exc:
                    logger.warning("Falha no slice_mesh_plane(cap=True): %s; tentando sem tampa.", exc)
                    try:
                        sliced = trimesh.intersections.slice_mesh_plane(
                            mesh,
                            plane_normal=[0.0, 1.0, 0.0],
                            plane_origin=[0.0, slice_y, 0.0],
                            cap=False,
                        )
                    except Exception as exc2:
                        logger.warning("Falha no slice_mesh_plane(cap=False): %s; mantendo malha original.", exc2)
                        sliced = None

                if sliced is not None and not sliced.is_empty and len(sliced.faces) > 0:
                    mesh = sliced
                    mesh.fix_normals()
                    if orig_colors is not None and len(orig_vertices) > 0:
                        tree = cKDTree(orig_vertices)
                        _, nearest_idx = tree.query(np.asarray(mesh.vertices, dtype=np.float64))
                        mesh.visual = trimesh.visual.ColorVisuals(
                            mesh=mesh,
                            vertex_colors=orig_colors[nearest_idx],
                        )

        return mesh

    @classmethod
    def _normalize_mesh(cls, mesh: trimesh.Trimesh, mode_name: str = "triposr") -> trimesh.Trimesh:
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
        mesh.metadata["image_to_3d_mode"] = mode_name
        return mesh

    def generate_mesh_from_image(
        self,
        image_path: Path,
        mcubes_resolution: int = DEFAULT_MCUBES_RESOLUTION,
        remove_background: bool = True,
        cancel_check: Optional[Callable[[], None]] = None,
        geometric_constraints: Optional[Dict[str, Any]] = None,
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

        # 6. Pipeline Híbrido Neuro-Simbólico (Alinhamento PCA/Inércia + Corte Estanque + Preservação COLOR_0)
        mode_name = "triposr"
        if geometric_constraints is not None:
            check()
            mesh = self._apply_hybrid_geometric_postprocessing(mesh, geometric_constraints)
            mode_name = "hybrid_neural_symbolic"

        # 7. Assentamento Final Y-up: escalar para 1.0m, centralizar XZ na origem (0, 0) e Y_min = 0.0
        final_mesh = self._normalize_mesh(mesh, mode_name=mode_name)
        if geometric_constraints is not None:
            final_mesh.metadata["geometric_constraints"] = dict(geometric_constraints)
        return final_mesh
