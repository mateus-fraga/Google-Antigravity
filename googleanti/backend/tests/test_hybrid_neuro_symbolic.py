import json
import threading
import types

import httpx
import numpy as np
import pytest
import trimesh
from PIL import Image

from backend.app.config import settings
from backend.app.jobs.orchestrator import JobOrchestrator
from backend.app.lrm.triposr_engine import TripoSREngine
from backend.app.procedural.hybrid_inspector import HybridInspector
from backend.app.procedural.image_to_3d import ImageTo3DGenerator
from backend.app.schemas.jobs import JobCreate


class _DummyResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


def test_hybrid_inspector_parses_valid_ollama_json_and_markdown(monkeypatch, tmp_path):
    img_path = tmp_path / "vase.png"
    Image.new("RGB", (64, 64), (190, 100, 60)).save(img_path)

    # 1. JSON estrito
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: _DummyResponse(
            200,
            {"response": json.dumps({"needs_flat_base": False, "is_symmetrical": False, "primary_axis": "horizontal"})},
        ),
    )
    res = HybridInspector.inspect_image(img_path)
    assert res == {
        "needs_flat_base": False,
        "is_symmetrical": False,
        "primary_axis": "horizontal",
    }

    # 2. JSON dentro de bloco markdown
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: _DummyResponse(
            200,
            {"response": '```json\n{"needs_flat_base": true, "is_symmetrical": false, "primary_axis": "vertical"}\n```'},
        ),
    )
    res_md = HybridInspector.inspect_image(img_path)
    assert res_md == {
        "needs_flat_base": True,
        "is_symmetrical": False,
        "primary_axis": "vertical",
    }


@pytest.mark.parametrize(
    "failure_behavior",
    [
        "connect_error",
        "timeout",
        "http_500",
        "invalid_json",
        "invalid_schema",
        "missing_file",
    ],
)
def test_hybrid_inspector_safe_fallback_never_raises(monkeypatch, tmp_path, failure_behavior):
    img_path = tmp_path / "obj.png"
    if failure_behavior != "missing_file":
        Image.new("RGB", (32, 32), (100, 100, 100)).save(img_path)

    def _fake_post(*args, **kwargs):
        if failure_behavior == "connect_error":
            raise httpx.ConnectError("Ollama offline")
        if failure_behavior == "timeout":
            raise httpx.TimeoutException("Ollama timeout")
        if failure_behavior == "http_500":
            return _DummyResponse(500, {"error": "internal"})
        if failure_behavior == "invalid_json":
            return _DummyResponse(200, {"response": "not a valid json at all"})
        if failure_behavior == "invalid_schema":
            return _DummyResponse(200, {"response": json.dumps({"needs_flat_base": "yes", "is_symmetrical": 123})})
        return _DummyResponse(200, {})

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = HybridInspector.inspect_image(img_path)
    assert result == {
        "needs_flat_base": True,
        "is_symmetrical": True,
        "primary_axis": "vertical",
    }


def test_triposr_hybrid_pca_alignment_watertight_slicing_and_color_preservation(tmp_path):
    import contextlib

    img_path = tmp_path / "terracotta_vase.png"
    Image.new("RGB", (64, 64), (192, 96, 64)).save(img_path)

    # Criar um cilindro estanque no espaço nativo Z-up do TripoSR, ligeiramente inclinado (12° em X e 8° em Y)
    # para simular inclinação residual + ruído neural na base
    raw_vase = trimesh.creation.cylinder(radius=0.35, height=1.6, sections=32)
    tilt = trimesh.transformations.euler_matrix(np.radians(12.0), np.radians(8.0), 0.0)
    raw_vase.apply_transform(tilt)

    terracotta_rgba = np.array([192, 96, 64, 255], dtype=np.uint8)
    raw_vase.visual = trimesh.visual.ColorVisuals(
        mesh=raw_vase,
        vertex_colors=np.tile(terracotta_rgba, (len(raw_vase.vertices), 1)),
    )

    class FakeModel:
        def __call__(self, images, device=None):
            return ["fake_scene_code"]

        def extract_mesh(self, scene_codes, has_vertex_color=True, resolution=256):
            return [raw_vase.copy()]

    stub_torch = types.SimpleNamespace(
        no_grad=contextlib.nullcontext,
        cuda=types.SimpleNamespace(empty_cache=lambda: None),
    )

    engine = object.__new__(TripoSREngine)
    engine._torch = stub_torch
    engine.device = "cpu"
    engine.model = FakeModel()
    engine._rembg_session = None

    constraints = {
        "needs_flat_base": True,
        "is_symmetrical": True,
        "primary_axis": "vertical",
    }
    mesh = engine.generate_mesh_from_image(
        img_path,
        mcubes_resolution=64,
        remove_background=False,
        geometric_constraints=constraints,
    )

    # 1. Malha cortada deve permanecer 100% estanque (cap=True com mapbox-earcut)
    assert mesh.is_watertight is True
    assert mesh.volume > 0.0

    # 2. Assentamento exato Y_min == 0.0, X/Z centralizados e escala máxima 1.0m
    assert np.isclose(mesh.bounds[0][1], 0.0, atol=1e-5)
    assert np.isclose(mesh.bounds[0][0], -mesh.bounds[1][0], atol=1e-5)
    assert np.isclose(mesh.bounds[0][2], -mesh.bounds[1][2], atol=1e-5)
    assert np.isclose(mesh.extents.max(), 1.0, atol=1e-5)

    # 3. Alinhamento PCA removeu a inclinação residual: eixo de menor inércia alinhado com Y
    # A razão de diâmetro XZ deve ser simétrica (X ~= Z) e menor que a altura Y (1.0m)
    assert np.isclose(mesh.extents[1], 1.0, atol=1e-4)
    assert np.isclose(mesh.extents[0], mesh.extents[2], atol=0.02)

    # 4. Corte plano gerou vértices coplanares em Y = 0 e preservou as cores de terracota (COLOR_0)
    base_vertices_mask = mesh.vertices[:, 1] <= 1e-4
    assert int(np.sum(base_vertices_mask)) >= 8

    vc = np.asarray(mesh.visual.vertex_colors)
    assert vc.shape == (len(mesh.vertices), 4)
    assert np.all(vc[base_vertices_mask] == terracotta_rgba)
    assert mesh.metadata["image_to_3d_mode"] == "hybrid_neural_symbolic"
    assert mesh.metadata["geometric_constraints"] == constraints


def test_job_create_and_orchestrator_route_hybrid_neural_symbolic(monkeypatch, tmp_path):
    assert "hybrid_neural_symbolic" in ImageTo3DGenerator.SUPPORTED_MODES

    job_req = JobCreate(
        project_id="proj_hybrid",
        operation_type="image_to_3d",
        params={"reference_image_filename": "ref_vase.png", "mode": "hybrid_neural_symbolic", "mcubes_resolution": 128},
    )
    assert job_req.params["mode"] == "hybrid_neural_symbolic"

    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path / "projects")
    proj_dir = settings.STORAGE_DIR / "proj_hybrid"
    proj_dir.mkdir(parents=True, exist_ok=True)
    img_path = proj_dir / "ref_vase.png"
    Image.new("RGB", (64, 64), (192, 96, 64)).save(img_path)

    expected_constraints = {
        "needs_flat_base": True,
        "is_symmetrical": True,
        "primary_axis": "vertical",
    }
    captured = {}

    monkeypatch.setattr(HybridInspector, "inspect_image", classmethod(lambda cls, p: dict(expected_constraints)))

    class DummyEngine:
        def generate_mesh_from_image(
            self,
            image_path,
            mcubes_resolution=256,
            remove_background=True,
            cancel_check=None,
            geometric_constraints=None,
        ):
            captured["constraints"] = geometric_constraints
            cyl = trimesh.creation.cylinder(radius=0.3, height=1.2, sections=24)
            cyl.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-90.0), [1.0, 0.0, 0.0]))
            cyl.visual = trimesh.visual.ColorVisuals(
                mesh=cyl,
                vertex_colors=np.tile([192, 96, 64, 255], (len(cyl.vertices), 1)).astype(np.uint8),
            )
            processed = TripoSREngine._apply_hybrid_geometric_postprocessing(cyl, geometric_constraints)
            return TripoSREngine._normalize_mesh(processed, mode_name="hybrid_neural_symbolic")

    monkeypatch.setattr(TripoSREngine, "get_instance", classmethod(lambda cls: DummyEngine()))
    monkeypatch.setattr(JobOrchestrator, "is_cancel_requested", classmethod(lambda cls, jid: False))

    result = JobOrchestrator._execute_procedural_pipeline_sync(
        job_id="job-hybrid-01",
        project_id="proj_hybrid",
        params={"reference_image_filename": "ref_vase.png", "mode": "hybrid_neural_symbolic", "mcubes_resolution": 128},
        cancel_event=threading.Event(),
        operation_type="image_to_3d",
    )

    assert captured["constraints"] == expected_constraints
    assert result["model_path"].exists()
    assert result["export_meta"]["validated"] is True
    assert result["inspect_info"]["is_watertight"] is True
    assert np.isclose(result["inspect_info"]["bounds"][0][1], 0.0, atol=1e-5)
    assert result["semantic_metadata"]["image_to_3d_mode"] == "hybrid_neural_symbolic"
    assert result["semantic_metadata"]["geometric_constraints"] == expected_constraints


def test_align_mesh_upright_1_to_1_tilted_vase_with_asymmetric_cavity():
    """
    Valida que `_align_mesh_upright` + pós-processamento híbrido corrige a inclinação
    de câmera (~25°) de um vaso 1:1 com cavidade interna assimétrica e leve ruído neural
    na base, mantendo a malha estanque, apoiada em Y_min = 0.0 e preservando vertex_colors.
    """
    rings = 36
    secs = 48
    ys = np.linspace(-0.5, 0.5, rings)
    verts = []
    faces = []
    for i, y in enumerate(ys):
        t = y + 0.5
        r = 0.30 + 0.20 * np.sin(np.pi * t) + 0.08 * t
        for j in range(secs):
            ang = 2.0 * np.pi * j / secs
            rng = np.random.default_rng(i * 100 + j)
            dy = rng.uniform(-0.012, 0.012) if i == 0 else 0.0
            verts.append([r * np.cos(ang), y + dy, r * np.sin(ang)])

    bot_c = len(verts)
    verts.append([0.0, -0.505, 0.0])
    # Cavidade interna deslocada lateralmente (simulando escavação diagonal pela câmera)
    top_c = len(verts)
    verts.append([0.14, 0.15, 0.08])

    for i in range(rings - 1):
        for j in range(secs):
            jn = (j + 1) % secs
            a = i * secs + j
            b = i * secs + jn
            c = (i + 1) * secs + j
            d = (i + 1) * secs + jn
            faces.append([a, b, d])
            faces.append([a, d, c])
    for j in range(secs):
        jn = (j + 1) % secs
        faces.append([bot_c, jn, j])
        faces.append([top_c, (rings - 1) * secs + j, (rings - 1) * secs + jn])

    vase = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)
    vase.fix_normals()
    assert vase.is_watertight

    terracotta = np.array([188, 92, 58, 255], dtype=np.uint8)
    vase.visual = trimesh.visual.ColorVisuals(
        mesh=vase,
        vertex_colors=np.tile(terracotta, (len(vase.vertices), 1)),
    )

    tilt = trimesh.transformations.euler_matrix(np.radians(24.0), 0.0, np.radians(-11.0))
    vase_tilted = vase.copy()
    vase_tilted.apply_transform(tilt)
    true_up_tilted = (tilt @ np.array([0.0, 1.0, 0.0, 1.0]))[:3]

    constraints = {"needs_flat_base": True, "is_symmetrical": True, "primary_axis": "vertical"}
    _, rot_total = TripoSREngine._align_mesh_upright(vase_tilted, constraints)
    recovered_up = (rot_total @ np.append(true_up_tilted, 1.0))[:3]
    residual_err_deg = float(np.degrees(np.arccos(np.clip(recovered_up[1], -1.0, 1.0))))
    assert residual_err_deg < 2.0

    processed = TripoSREngine._apply_hybrid_geometric_postprocessing(vase_tilted, constraints)
    final_mesh = TripoSREngine._normalize_mesh(processed, mode_name="hybrid_neural_symbolic")

    assert final_mesh.is_watertight is True
    assert np.isclose(final_mesh.bounds[0][1], 0.0, atol=1e-5)
    assert np.isclose(final_mesh.extents[0], final_mesh.extents[2], atol=0.03)
    vc = np.asarray(final_mesh.visual.vertex_colors)
    assert vc.shape == (len(final_mesh.vertices), 4)
    assert np.all(vc == terracotta)

