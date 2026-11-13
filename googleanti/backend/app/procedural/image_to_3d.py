from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from shapely.geometry import Polygon, MultiPolygon
import trimesh

from backend.app.schemas.geometry import (
    _ensure_finite_number,
    MIN_DIMENSION,
    MAX_DIMENSION,
)
from backend.app.procedural.engine import (
    ProceduralGenerator,
    _Z_UP_TO_Y_UP_MATRIX,
)

MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10 MB

ALLOWED_IMAGE_EXTENSIONS: Dict[str, str] = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
}

FORMAT_TO_EXTENSION: Dict[str, str] = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
}

FORMAT_TO_MEDIA_TYPE: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def validate_uploaded_image_bytes(raw_bytes: bytes, original_filename: str) -> Tuple[str, str, int, int]:
    """
    Bloco 7 (Task 7.1): Valida estritamente um arquivo de imagem enviado:
    1. Tamanho > 0 e <= MAX_UPLOAD_SIZE (10 MB).
    2. Extensão do nome original deve pertencer a {.png, .jpg, .jpeg, .webp}.
    3. Rejeição imediata de assinaturas perigosas (SVG/XML, HTML, scripts, PDF, executáveis PE/ELF).
    4. Verificação de magic bytes binários reais para PNG, JPEG ou WEBP.
    5. Decodificação completa e verificação de integridade via Pillow (impede arquivos truncados ou falsificados).
    6. Correspondência estrita entre a extensão declarada e o formato real detectado nos magic bytes.
    Retorna `(canonical_ext, pil_format, width, height)`.
    """
    if not isinstance(raw_bytes, (bytes, bytearray)) or len(raw_bytes) == 0:
        raise ValueError("O arquivo enviado está vazio.")

    if len(raw_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError(
            f"O arquivo excede o tamanho máximo permitido de {MAX_UPLOAD_SIZE // (1024 * 1024)} MB "
            f"(recebido: {len(raw_bytes)} bytes)."
        )

    if not original_filename or not isinstance(original_filename, str):
        raise ValueError("Nome de arquivo de imagem inválido.")

    ext = Path(original_filename.strip()).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            f"Extensão de arquivo não permitida: '{ext}'. Apenas imagens PNG, JPG/JPEG e WEBP são aceitas."
        )

    # Rejeitar assinaturas de texto/script/executáveis/vetoriais (SVG, XML, HTML, PDF, MZ, ELF)
    head_strip = bytes(raw_bytes[:256]).lstrip().lower()
    forbidden_prefixes = (
        b"<svg",
        b"<?xml",
        b"<!doctype",
        b"<html",
        b"<script",
        b"%pdf",
        b"mz",
        b"\x7felf",
        b"#!",
    )
    if any(head_strip.startswith(p) for p in forbidden_prefixes) or b"<svg" in head_strip:
        raise ValueError("Formato de arquivo proibido detectado (SVG, script, PDF ou executável não são permitidos).")

    # Verificação estrita de Magic Bytes
    detected_magic_format: Optional[str] = None
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_magic_format = "PNG"
    elif raw_bytes.startswith(b"\xff\xd8\xff"):
        detected_magic_format = "JPEG"
    elif len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        detected_magic_format = "WEBP"

    if detected_magic_format is None:
        raise ValueError(
            "Assinatura binária (magic bytes) inválida. O arquivo não é uma imagem PNG, JPEG ou WEBP autêntica."
        )

    expected_format_for_ext = ALLOWED_IMAGE_EXTENSIONS[ext]
    if detected_magic_format != expected_format_for_ext:
        raise ValueError(
            f"Divergência de formato detectada: a extensão '{ext}' espera {expected_format_for_ext}, "
            f"mas os magic bytes indicam {detected_magic_format}."
        )

    # Validar integridade estrutural da imagem com Pillow
    try:
        with Image.open(BytesIO(raw_bytes)) as img:
            pil_format = (img.format or "").upper()
            width, height = img.size
            img.verify()
        # Reabrir e forçar decodificação dos pixels para capturar imagens corrompidas no meio do stream
        with Image.open(BytesIO(raw_bytes)) as img_load:
            img_load.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ValueError(f"Arquivo de imagem corrompido ou ilegível: {exc}") from exc

    if pil_format != detected_magic_format:
        raise ValueError(
            f"Formato interno da imagem ({pil_format}) não corresponde aos magic bytes ({detected_magic_format})."
        )

    if width < 4 or height < 4 or width > 8192 or height > 8192:
        raise ValueError(f"Dimensões de imagem fora dos limites suportados (4x4 a 8192x8192): {width}x{height}px.")

    canonical_ext = FORMAT_TO_EXTENSION[detected_magic_format]
    return canonical_ext, detected_magic_format, int(width), int(height)


class ImageTo3DGenerator:
    """
    Bloco 7 (Tasks 7.2 e 7.3): Motor local de reconstrução Image-to-3D em convenção Y-up.
    Suporta dois modos de operação 100% locais (sem APIs externas):
    1. `silhouette`: Extração de contornos vetoriais (incluindo furos internos) via OpenCV/Shapely
       e extrusão sólida para `thickness` metros apoiada no plano XZ ($Y = 0$).
    2. `heightmap`: Mapeamento de luminância em grelha 3D $(X, Y, Z)$ com base sólida (`base_thickness`),
       relevo (`relief_depth`), paredes laterais e fundo fechado, produzindo uma malha estritamente
       estanque (`is_watertight == True`).
    """

    SUPPORTED_MODES = {"silhouette", "heightmap"}

    @classmethod
    def _load_validated_pil_image(cls, image_path: Path) -> Image.Image:
        if not isinstance(image_path, Path):
            image_path = Path(image_path)
        if not image_path.exists() or not image_path.is_file() or image_path.is_symlink():
            raise ValueError(f"Caminho de imagem de referência inválido ou inexistente: {image_path}")
        raw_bytes = image_path.read_bytes()
        validate_uploaded_image_bytes(raw_bytes, image_path.name)
        img = Image.open(BytesIO(raw_bytes))
        img.load()
        return img

    @classmethod
    def _extract_binary_mask(cls, pil_img: Image.Image, resolution_scale: float = 1.0) -> np.ndarray:
        """
        Extrai máscara binária uint8 (0 = fundo, 255 = objeto):
        - Se a imagem possuir canal Alpha com transparência efetiva, segmenta por `alpha > 127`.
        - Caso contrário, converte para tons de cinza e aplica limiarização de Otsu (ou média),
          invertendo automaticamente se o fundo ao redor das bordas for claro (branco).
        """
        w_orig, h_orig = pil_img.size
        target_w = max(16, min(512, int(round(w_orig * resolution_scale))))
        target_h = max(16, min(512, int(round(h_orig * resolution_scale))))

        if (target_w, target_h) != (w_orig, h_orig):
            pil_img = pil_img.resize((target_w, target_h), Image.Resampling.BILINEAR)

        rgba = np.asarray(pil_img.convert("RGBA"), dtype=np.uint8)
        alpha = rgba[:, :, 3]

        if int(alpha.min()) < 240 and int(alpha.max()) > 15:
            mask = np.where(alpha > 127, 255, 0).astype(np.uint8)
        else:
            gray = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
            # Suavização leve para reduzir ruído de compressão JPEG/WEBP
            blurred = cv2.GaussianBlur(gray, (3, 3), 0)
            _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Verificar os pixels da borda da imagem: se a maioria for 255, o fundo é claro -> inverter
            border_pixels = np.concatenate([mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]])
            if np.mean(border_pixels) > 127.0:
                mask = cv2.bitwise_not(mask)

            # Se a máscara ficou vazia (ex.: imagem quase uniforme), tentar limiar pela média
            if np.count_nonzero(mask) < 9:
                mean_val = float(np.mean(gray))
                if mean_val > 127.0:
                    mask = np.where(gray < mean_val - 5.0, 255, 0).astype(np.uint8)
                else:
                    mask = np.where(gray > mean_val + 5.0, 255, 0).astype(np.uint8)

        # Adicionar borda de 2px zerada para garantir fechamento de contornos que tocam a extremidade da imagem
        padded_mask = np.pad(mask, pad_width=2, mode="constant", constant_values=0)
        return padded_mask

    @classmethod
    def generate_from_silhouette(
        cls,
        image_path: Path,
        thickness: float = 0.1,
        resolution_scale: float = 1.0,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> trimesh.Trimesh:
        r"""
        Bloco 7 (Task 7.2): Extrai polígonos de contorno (com suporte a furos internos via `cv2.RETR_CCOMP`
        e `shapely.geometry.Polygon`), suaviza via `simplify`, extruda para `thickness` metros normalizando
        a escala no plano XZ (1x1m máx) e alinha nativamente em Y-up ($Y_{\min} = 0.0, Y_{\max} = \text{thickness}$).
        """
        t_val = _ensure_finite_number(thickness, "thickness")
        scale_val = _ensure_finite_number(resolution_scale, "resolution_scale")
        if t_val < MIN_DIMENSION or t_val > MAX_DIMENSION:
            raise ValueError(f"Espessura ('thickness') fora dos limites [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {t_val}")
        if scale_val < 0.05 or scale_val > 4.0:
            raise ValueError(f"Escala de resolução ('resolution_scale') deve estar entre 0.05 e 4.0 (recebido: {scale_val}).")

        if cancel_check:
            cancel_check()

        pil_img = cls._load_validated_pil_image(image_path)
        mask = cls._extract_binary_mask(pil_img, resolution_scale=scale_val)

        if cancel_check:
            cancel_check()

        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if not contours or hierarchy is None or len(contours) == 0:
            raise ValueError("Não foi possível extrair nenhuma silhueta/contorno válido da imagem fornecida.")

        hier = hierarchy[0]
        raw_polygons: List[Polygon] = []

        for idx, cnt in enumerate(contours):
            # Em RETR_CCOMP, parent == -1 indica contorno externo (shell)
            if hier[idx][3] != -1:
                continue
            if len(cnt) < 3:
                continue

            shell_pts = [(float(pt[0][0]), -float(pt[0][1])) for pt in cnt]
            if len(shell_pts) < 3:
                continue

            holes_pts: List[List[Tuple[float, float]]] = []
            child_idx = hier[idx][2]
            while child_idx != -1:
                child_cnt = contours[child_idx]
                if len(child_cnt) >= 3:
                    h_pts = [(float(pt[0][0]), -float(pt[0][1])) for pt in child_cnt]
                    if len(h_pts) >= 3:
                        holes_pts.append(h_pts)
                child_idx = hier[child_idx][0]

            try:
                poly = Polygon(shell=shell_pts, holes=holes_pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_empty or poly.area < 4.0:
                    continue
                simplified = poly.simplify(tolerance=0.6, preserve_topology=True)
                if not simplified.is_valid:
                    simplified = simplified.buffer(0)
                if not simplified.is_empty and simplified.area >= 4.0:
                    if isinstance(simplified, Polygon):
                        raw_polygons.append(simplified)
                    elif isinstance(simplified, MultiPolygon):
                        raw_polygons.extend([p for p in simplified.geoms if p.area >= 4.0])
            except Exception:
                continue

        if not raw_polygons:
            raise ValueError("A imagem fornecida não produziu polígonos 2D válidos para extrusão.")

        if cancel_check:
            cancel_check()

        # Normalizar conjunto de polígonos para caber em uma caixa 1.0 x 1.0 metro centrada em (0, 0)
        union_geom = MultiPolygon(raw_polygons) if len(raw_polygons) > 1 else raw_polygons[0]
        minx, miny, maxx, maxy = union_geom.bounds
        span_x = max(maxx - minx, 1e-6)
        span_y = max(maxy - miny, 1e-6)
        max_span = max(span_x, span_y)
        center_x = (minx + maxx) / 2.0
        center_y = (miny + maxy) / 2.0

        from shapely import affinity

        extruded_parts: List[trimesh.Trimesh] = []
        for poly in raw_polygons:
            if cancel_check:
                cancel_check()
            centered = affinity.translate(poly, xoff=-center_x, yoff=-center_y)
            scaled = affinity.scale(centered, xfact=1.0 / max_span, yfact=1.0 / max_span, origin=(0.0, 0.0))
            if not scaled.is_valid:
                scaled = scaled.buffer(0)
            if scaled.is_empty:
                continue

            sub_polys = [scaled] if isinstance(scaled, Polygon) else list(scaled.geoms)
            for sp in sub_polys:
                if sp.area < 1e-6:
                    continue
                part_mesh = trimesh.creation.extrude_polygon(sp, height=t_val)
                extruded_parts.append(part_mesh)

        if not extruded_parts:
            raise ValueError("Falha ao extrudar os polígonos extraídos da silhueta.")

        combined = extruded_parts[0] if len(extruded_parts) == 1 else trimesh.util.concatenate(extruded_parts)

        # Rotacionar de Z-up (extrusão em Z) para Y-up (altura/espessura em Y, base no plano XZ em Y = 0.0)
        combined.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        min_y = float(combined.bounds[0][1])
        if abs(min_y) > 1e-9:
            combined.apply_translation([0.0, -min_y, 0.0])

        final_mesh = ProceduralGenerator._finalize_and_verify_mesh(combined, shape_type="image_silhouette")
        final_mesh.metadata["image_to_3d_mode"] = "silhouette"
        final_mesh.metadata["thickness"] = t_val
        final_mesh.metadata["resolution_scale"] = scale_val
        final_mesh.metadata["polygon_count"] = len(extruded_parts)
        return final_mesh

    @classmethod
    def generate_from_heightmap(
        cls,
        image_path: Path,
        base_thickness: float = 0.05,
        relief_depth: float = 0.15,
        max_grid_size: int = 128,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> trimesh.Trimesh:
        r"""
        Bloco 7 (Task 7.3): Converte uma imagem 2D em uma malha 3D de baixo-relevo (heightmap) em Y-up:
        - Converte para tons de cinza e subamostra para no máximo `max_grid_size x max_grid_size` (padrão 128x128);
        - Calcula $Y_{x,z} = \text{base\_thickness} + (\text{luminância\_normalizada} \times \text{relief\_depth})$;
        - Constrói uma malha fechada (topo + base plana em $Y=0$ na mesma grelha + 4 paredes laterais sem T-junctions)
          garantindo topologia estritamente estanque (`is_watertight == True`).
        """
        base_t = _ensure_finite_number(base_thickness, "base_thickness")
        depth_t = _ensure_finite_number(relief_depth, "relief_depth")
        for name, val in (("base_thickness", base_t), ("relief_depth", depth_t)):
            if val < MIN_DIMENSION or val > MAX_DIMENSION:
                raise ValueError(f"Parâmetro '{name}' fora dos limites [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {val}")

        if cancel_check:
            cancel_check()

        pil_img = cls._load_validated_pil_image(image_path)
        gray_img = pil_img.convert("L")
        w_orig, h_orig = gray_img.size

        max_dim = max(8, min(256, int(max_grid_size)))
        scale = min(1.0, float(max_dim) / float(max(w_orig, h_orig)))
        cols = max(8, min(max_dim, int(round(w_orig * scale))))
        rows = max(8, min(max_dim, int(round(h_orig * scale))))

        if (cols, rows) != (w_orig, h_orig):
            gray_img = gray_img.resize((cols, rows), Image.Resampling.BILINEAR)

        lum = np.asarray(gray_img, dtype=np.float64) / 255.0

        if cancel_check:
            cancel_check()

        # Proporção física no plano XZ (maior lado = 1.0 metro, centrado na origem)
        max_rc = float(max(cols, rows))
        width_x = float(cols) / max_rc
        depth_z = float(rows) / max_rc

        xs = np.linspace(-width_x / 2.0, width_x / 2.0, cols, dtype=np.float64)
        zs = np.linspace(-depth_z / 2.0, depth_z / 2.0, rows, dtype=np.float64)
        grid_x, grid_z = np.meshgrid(xs, zs)

        top_y = base_t + (lum * depth_t)
        bot_y = np.zeros_like(top_y)

        # Camada superior (0 .. rows*cols - 1) e camada inferior (rows*cols .. 2*rows*cols - 1)
        top_vertices = np.column_stack([grid_x.ravel(), top_y.ravel(), grid_z.ravel()])
        bot_vertices = np.column_stack([grid_x.ravel(), bot_y.ravel(), grid_z.ravel()])
        vertices = np.vstack([top_vertices, bot_vertices])

        n_grid = rows * cols
        idx_grid = np.arange(n_grid, dtype=np.int64).reshape((rows, cols))

        # Crianção vetorizada dos triângulos do topo (normal voltada para +Y)
        v00 = idx_grid[:-1, :-1].ravel()
        v10 = idx_grid[1:, :-1].ravel()
        v01 = idx_grid[:-1, 1:].ravel()
        v11 = idx_grid[1:, 1:].ravel()

        top_tris_1 = np.column_stack([v00, v10, v11])
        top_tris_2 = np.column_stack([v00, v11, v01])

        # Triângulos da base inferior em Y=0 (mesma grelha com winding invertido para normal -Y, zero T-junctions)
        b00 = v00 + n_grid
        b10 = v10 + n_grid
        b01 = v01 + n_grid
        b11 = v11 + n_grid

        bot_tris_1 = np.column_stack([b00, b11, b10])
        bot_tris_2 = np.column_stack([b00, b01, b11])

        # Paredes laterais fechando o perímetro entre a camada superior e a camada inferior
        # 1. Borda Norte (row = 0, col: 0 -> cols-1)
        n_t0 = idx_grid[0, :-1]
        n_t1 = idx_grid[0, 1:]
        n_b0 = n_t0 + n_grid
        n_b1 = n_t1 + n_grid
        north_tris = np.vstack([np.column_stack([n_t0, n_t1, n_b1]), np.column_stack([n_t0, n_b1, n_b0])])

        # 2. Borda Sul (row = rows-1, col: 0 -> cols-1)
        s_t0 = idx_grid[-1, :-1]
        s_t1 = idx_grid[-1, 1:]
        s_b0 = s_t0 + n_grid
        s_b1 = s_t1 + n_grid
        south_tris = np.vstack([np.column_stack([s_t1, s_t0, s_b0]), np.column_stack([s_t1, s_b0, s_b1])])

        # 3. Borda Oeste (col = 0, row: 0 -> rows-1)
        w_t0 = idx_grid[:-1, 0]
        w_t1 = idx_grid[1:, 0]
        w_b0 = w_t0 + n_grid
        w_b1 = w_t1 + n_grid
        west_tris = np.vstack([np.column_stack([w_t1, w_t0, w_b0]), np.column_stack([w_t1, w_b0, w_b1])])

        # 4. Borda Leste (col = cols-1, row: 0 -> rows-1)
        e_t0 = idx_grid[:-1, -1]
        e_t1 = idx_grid[1:, -1]
        e_b0 = e_t0 + n_grid
        e_b1 = e_t1 + n_grid
        east_tris = np.vstack([np.column_stack([e_t0, e_t1, e_b1]), np.column_stack([e_t0, e_b1, e_b0])])

        if cancel_check:
            cancel_check()

        faces = np.vstack([top_tris_1, top_tris_2, bot_tris_1, bot_tris_2, north_tris, south_tris, west_tris, east_tris])
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

        final_mesh = ProceduralGenerator._finalize_and_verify_mesh(mesh, shape_type="image_heightmap")
        final_mesh.metadata["image_to_3d_mode"] = "heightmap"
        final_mesh.metadata["base_thickness"] = base_t
        final_mesh.metadata["relief_depth"] = depth_t
        final_mesh.metadata["grid_resolution"] = [int(cols), int(rows)]
        return final_mesh
