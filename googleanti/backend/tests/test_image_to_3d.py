from io import BytesIO
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.procedural.image_to_3d import (
    ImageTo3DGenerator,
    MAX_UPLOAD_SIZE,
)

client = TestClient(app)


def _create_test_png_bytes(width: int = 96, height: int = 96, with_hole: bool = True) -> bytes:
    """
    Cria programaticamente uma imagem PNG RGBA em memória com uma forma geométrica
    central (e um furo interno opcional) sobre fundo transparente.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Desenhar quadrado externo opaco
    draw.rectangle([16, 16, width - 16, height - 16], fill=(255, 255, 255, 255))
    if with_hole:
        # Furo interno transparente
        draw.rectangle([34, 34, width - 34, height - 34], fill=(0, 0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_test_heightmap_bytes(width: int = 48, height: int = 48, fmt: str = "PNG") -> bytes:
    """
    Cria programaticamente um mapa de altura (gradiente radial suave) em memória.
    """
    xs = np.linspace(-1.0, 1.0, width)
    ys = np.linspace(-1.0, 1.0, height)
    gx, gy = np.meshgrid(xs, ys)
    dist = np.sqrt(gx ** 2 + gy ** 2)
    lum = np.clip(1.0 - dist, 0.0, 1.0)
    arr = (lum * 255.0).astype(np.uint8)
    img = Image.fromarray(arr, mode="L").convert("RGB")
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_secure_reference_image_upload_validation_and_retrieval():
    """
    Task 7.1 / 7.4 (1): Testa a segurança do upload de imagem de referência:
    - Rejeição de SVG, scripts, executáveis e PDFs;
    - Rejeição de extensão falsa (spoofing: ex. texto ou JPEG renomeado para .png);
    - Rejeição de arquivo vazio e arquivo acima de MAX_UPLOAD_SIZE (10 MB);
    - Upload válido de PNG, JPG e WEBP, registro no projeto e leitura segura via GET.
    """
    proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Image Security Test Project", "category": "artistic"},
    )
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    other_proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Other Project", "category": "artistic"},
    )
    other_proj_id = other_proj_res.json()["id"]

    try:
        # 1. Rejeitar SVG malicioso (mesmo com extensão .svg ou disfarçado de .png)
        svg_payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        r_svg = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("vector.svg", svg_payload, "image/svg+xml")},
        )
        assert r_svg.status_code == 400

        r_svg_spoof = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("spoofed.png", svg_payload, "image/png")},
        )
        assert r_svg_spoof.status_code == 400

        # 2. Rejeitar executável / texto arbitrário com extensão .jpg
        r_exe_spoof = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("malware.jpg", b"MZ\x90\x00\x03\x00\x00\x00NOT_A_JPEG", "image/jpeg")},
        )
        assert r_exe_spoof.status_code == 400

        # 3. Rejeitar divergência entre magic bytes (PNG real) e extensão (.jpg)
        valid_png = _create_test_png_bytes()
        r_mismatch = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("wrong_ext.jpg", valid_png, "image/jpeg")},
        )
        assert r_mismatch.status_code == 400

        # 4. Rejeitar arquivo vazio (0 bytes)
        r_empty = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert r_empty.status_code == 400

        # 5. Rejeitar arquivo maior que MAX_UPLOAD_SIZE (10 MB + 100 bytes)
        oversized = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (MAX_UPLOAD_SIZE + 100))
        r_oversized = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("huge.png", oversized, "image/png")},
        )
        assert r_oversized.status_code == 413

        # 6. Upload válido de PNG, JPEG e WEBP
        for ext, fmt, mime in (
            (".png", "PNG", "image/png"),
            (".jpg", "JPEG", "image/jpeg"),
            (".webp", "WEBP", "image/webp"),
        ):
            img_bytes = _create_test_heightmap_bytes(32, 32, fmt=fmt)
            up_res = client.post(
                f"/api/v1/projects/{proj_id}/images",
                files={"file": (f"sample{ext}", img_bytes, mime)},
            )
            assert up_res.status_code == 200
            up_data = up_res.json()
            assert up_data["format"] == fmt
            assert up_data["width"] == 32
            assert up_data["height"] == 32
            saved_fname = up_data["filename"]
            assert saved_fname.startswith("ref_image_")

            # Leitura contextual segura da imagem no próprio projeto
            get_img_res = client.get(f"/api/v1/projects/{proj_id}/images/{saved_fname}")
            assert get_img_res.status_code == 200
            assert get_img_res.content == img_bytes

            # Bloqueio de acesso cruzado a partir de outro projeto
            cross_res = client.get(f"/api/v1/projects/{other_proj_id}/images/{saved_fname}")
            assert cross_res.status_code in (403, 404)

    finally:
        client.delete(f"/api/v1/projects/{proj_id}")
        client.delete(f"/api/v1/projects/{other_proj_id}")


def test_silhouette_and_heightmap_generators_y_up_and_watertight(tmp_path: Path):
    """
    Task 7.2 / 7.3 / 7.4 (2): Valida a geração direta de malhas 3D a partir de imagens
    criadas programaticamente em `tmp_path` nos modos `silhouette` (com furo interno)
    e `heightmap`, confirmando Y_min == 0.0, dimensões esperadas e `is_watertight == True`.
    """
    # 1. Teste de Extrusão de Silhueta com furo interno
    sil_path = tmp_path / "test_silhouette.png"
    sil_path.write_bytes(_create_test_png_bytes(120, 120, with_hole=True))

    mesh_sil = ImageTo3DGenerator.generate_from_silhouette(
        image_path=sil_path,
        thickness=0.15,
        resolution_scale=1.0,
    )
    assert not mesh_sil.is_empty
    assert mesh_sil.is_watertight is True
    assert np.all(np.isfinite(mesh_sil.vertices))
    assert np.all(np.isfinite(mesh_sil.face_normals))
    assert mesh_sil.metadata["coordinate_system"] == "Y-up"
    assert mesh_sil.metadata["geometry_schema_version"] == 2
    assert abs(mesh_sil.bounds[0][1]) < 1e-5
    assert math.isclose(mesh_sil.bounds[1][1], 0.15, rel_tol=1e-3)
    # Normalizado em 1.0 x 1.0 metro no plano XZ
    assert math.isclose(mesh_sil.extents[0], 1.0, rel_tol=0.05)
    assert math.isclose(mesh_sil.extents[2], 1.0, rel_tol=0.05)

    # 2. Teste de Heightmap (Baixo-Relevo) estanque (watertight)
    hm_path = tmp_path / "test_heightmap.png"
    hm_path.write_bytes(_create_test_heightmap_bytes(40, 40, fmt="PNG"))

    mesh_hm = ImageTo3DGenerator.generate_from_heightmap(
        image_path=hm_path,
        base_thickness=0.05,
        relief_depth=0.20,
        max_grid_size=40,
    )
    assert not mesh_hm.is_empty
    assert mesh_hm.is_watertight is True
    assert np.all(np.isfinite(mesh_hm.vertices))
    assert np.all(np.isfinite(mesh_hm.face_normals))
    assert mesh_hm.metadata["coordinate_system"] == "Y-up"
    assert abs(mesh_hm.bounds[0][1]) < 1e-5
    # Altura máxima em Y = base_thickness (0.05) + relief_depth (0.20) = 0.25m
    assert math.isclose(mesh_hm.bounds[1][1], 0.25, rel_tol=0.05)


def test_full_async_image_to_3d_jobs_silhouette_and_heightmap():
    """
    Task 7.4: Valida o fluxo integrado completo via API:
    1. Upload da imagem de referência para o projeto;
    2. Execução de job `image_to_3d` em modo `silhouette` e `heightmap`;
    3. Verificação de telemetria (`is_watertight: True`, `Y-up`, bounds);
    4. Exportação multiformato (`GLB`, `OBJ`, `STL`) e download contextual seguro.
    """
    proj_res = client.post(
        "/api/v1/projects",
        json={"name": "Image-to-3D Full Pipeline", "category": "artistic"},
    )
    assert proj_res.status_code == 200
    proj_id = proj_res.json()["id"]

    try:
        # Upload da imagem PNG
        png_bytes = _create_test_png_bytes(80, 80, with_hole=True)
        up_res = client.post(
            f"/api/v1/projects/{proj_id}/images",
            files={"file": ("badge.png", png_bytes, "image/png")},
        )
        assert up_res.status_code == 200
        ref_filename = up_res.json()["filename"]

        for mode, extra_params, expected_max_y in (
            ("silhouette", {"thickness": 0.12, "resolution_scale": 1.0}, 0.12),
            ("heightmap", {"base_thickness": 0.04, "relief_depth": 0.16}, 0.20),
        ):
            job_payload = {
                "project_id": proj_id,
                "operation_type": "image_to_3d",
                "params": {
                    "reference_image_filename": ref_filename,
                    "mode": mode,
                    **extra_params,
                },
            }
            job_res = client.post("/api/v1/jobs", json=job_payload)
            assert job_res.status_code == 200
            job_id = job_res.json()["id"]

            status_res = client.get(f"/api/v1/jobs/{job_id}")
            assert status_res.status_code == 200
            s_data = status_res.json()
            assert s_data["status"] == "Concluída"
            assert len(s_data["result_files"]) == 1

            meta = s_data["metadata"]
            assert meta["coordinate_system"] == "Y-up"
            assert meta["image_to_3d_mode"] == mode
            assert meta["reference_image_filename"] == ref_filename
            inspect = meta["inspection"]
            assert inspect["is_watertight"] is True
            assert abs(inspect["bounds"][0][1]) < 1e-4
            assert math.isclose(inspect["bounds"][1][1], expected_max_y, rel_tol=0.05)

        # Exportar o modelo ativo nos 3 formatos e validar download
        for fmt in ("glb", "obj", "stl"):
            exp_res = client.post(f"/api/v1/projects/{proj_id}/export/{fmt}")
            assert exp_res.status_code == 200
            fname = exp_res.json()["filename"]
            dl_res = client.get(f"/api/v1/projects/{proj_id}/artifacts/{fname}")
            assert dl_res.status_code == 200
            assert len(dl_res.content) > 0

        # Validar rejeição HTTP 422 para parâmetros inválidos em image_to_3d
        for bad_params in (
            {},  # Sem reference_image_filename
            {"reference_image_filename": "../secret.png", "mode": "silhouette"},
            {"reference_image_filename": ref_filename, "mode": "invalid_mode"},
            {"reference_image_filename": ref_filename, "mode": "silhouette", "thickness": -0.5},
            {"reference_image_filename": ref_filename, "mode": "heightmap", "relief_depth": 0.0},
        ):
            bad_res = client.post(
                "/api/v1/jobs",
                json={
                    "project_id": proj_id,
                    "operation_type": "image_to_3d",
                    "params": bad_params,
                },
            )
            assert bad_res.status_code == 422

    finally:
        del_res = client.delete(f"/api/v1/projects/{proj_id}")
        assert del_res.status_code == 200
