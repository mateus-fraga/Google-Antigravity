import sys
import types

import numpy as np
import pytest
import trimesh
from pydantic import ValidationError

from backend.app.lrm.triposr_engine import TripoSREngine, TripoSRUnavailableError
from backend.app.procedural.image_to_3d import ImageTo3DGenerator
from backend.app.schemas.jobs import JobCreate


def test_triposr_mode_is_accepted_and_legacy_modes_preserved():
    assert {"silhouette", "heightmap", "triposr"} <= ImageTo3DGenerator.SUPPORTED_MODES
    for mode in ("silhouette", "heightmap", "triposr"):
        job = JobCreate(
            project_id="p1",
            operation_type="image_to_3d",
            params={"reference_image_filename": "a.png", "mode": mode},
        )
        assert job.params["mode"] == mode


def test_triposr_rejects_invalid_mcubes_resolution():
    with pytest.raises(ValidationError):
        JobCreate(
            project_id="p1",
            operation_type="image_to_3d",
            params={"reference_image_filename": "a.png", "mode": "triposr", "mcubes_resolution": 99999},
        )


def test_normalize_mesh_scales_and_grounds_y_up():
    mesh = trimesh.creation.box(extents=[4.0, 8.0, 2.0])
    out = TripoSREngine._normalize_mesh(mesh)
    assert np.isclose(out.extents.max(), 1.0)
    assert np.isclose(out.bounds[0][1], 0.0)
    assert np.isclose(out.bounds[0][0], -out.bounds[1][0])
    assert np.isclose(out.bounds[0][2], -out.bounds[1][2])


def test_engine_reports_missing_dependencies_clearly(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    TripoSREngine._instance = None
    with pytest.raises(TripoSRUnavailableError):
        TripoSREngine()


def test_orchestrator_routes_triposr_mode_and_exports_glb(monkeypatch, tmp_path):
    import threading
    from PIL import Image
    from backend.app.config import settings
    from backend.app.jobs.orchestrator import JobOrchestrator

    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path / "projects")
    proj_dir = settings.STORAGE_DIR / "proj_triposr"
    proj_dir.mkdir(parents=True, exist_ok=True)

    img_path = proj_dir / "ref_image_test.png"
    Image.new("RGBA", (64, 64), (200, 80, 40, 255)).save(img_path, format="PNG")

    class DummyTripoSREngine:
        def generate_mesh_from_image(self, image_path, mcubes_resolution=256, remove_background=True, cancel_check=None):
            if cancel_check:
                cancel_check()
            sphere = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
            colors = np.tile([210, 100, 60, 255], (len(sphere.vertices), 1)).astype(np.uint8)
            sphere.visual.vertex_colors = colors
            return TripoSREngine._normalize_mesh(sphere)

    monkeypatch.setattr(TripoSREngine, "get_instance", classmethod(lambda cls: DummyTripoSREngine()))
    monkeypatch.setattr(JobOrchestrator, "is_cancel_requested", classmethod(lambda cls, jid: False))

    result = JobOrchestrator._execute_procedural_pipeline_sync(
        job_id="job-triposr-01",
        project_id="proj_triposr",
        params={"reference_image_filename": "ref_image_test.png", "mode": "triposr", "mcubes_resolution": 128},
        cancel_event=threading.Event(),
        operation_type="image_to_3d",
    )

    assert result["model_path"].exists()
    assert result["export_meta"]["validated"] is True
    assert result["semantic_metadata"]["image_to_3d_mode"] == "triposr"
    assert result["semantic_metadata"]["mcubes_resolution"] == 128
    assert result["inspect_info"]["coordinate_system"] == "Y-up"


def _get_torch_or_stub(monkeypatch=None):
    """
    Retorna o módulo `torch` real se instalado no ambiente, ou um stub leve compatível
    (com `no_grad`, `nn.Module`, `FloatTensor`, `LongTensor` e `Tensor`) para que os testes
    unitários funcionem tanto com PyTorch instalado quanto em ambientes sem GPU/torch.
    """
    import contextlib

    try:
        import torch as real_torch
        if real_torch is not None:
            return real_torch
    except ImportError:
        pass

    stub_torch = types.ModuleType("torch")
    stub_torch.no_grad = contextlib.nullcontext
    stub_torch.Tensor = object
    stub_torch.FloatTensor = object
    stub_torch.LongTensor = object
    stub_torch.float32 = "float32"
    stub_torch.long = "long"

    stub_cuda = types.SimpleNamespace(
        is_available=lambda: False,
        empty_cache=lambda: None,
    )
    stub_torch.cuda = stub_cuda

    stub_nn = types.ModuleType("torch.nn")

    class _StubModule:
        def __init__(self, *args, **kwargs):
            pass

    stub_nn.Module = _StubModule
    stub_nn_func = types.ModuleType("torch.nn.functional")
    stub_nn.functional = stub_nn_func
    stub_torch.nn = stub_nn

    if monkeypatch is not None:
        monkeypatch.setitem(sys.modules, "torch", stub_torch)
        monkeypatch.setitem(sys.modules, "torch.nn", stub_nn)
        monkeypatch.setitem(sys.modules, "torch.nn.functional", stub_nn_func)

        for opt_mod, attrs in (
            ("einops", {"rearrange": lambda x, *a, **kw: x}),
            ("huggingface_hub", {"hf_hub_download": lambda *a, **kw: ""}),
            ("omegaconf", {"OmegaConf": object, "DictConfig": dict}),
        ):
            try:
                __import__(opt_mod)
            except ImportError:
                m = types.ModuleType(opt_mod)
                for k, v in attrs.items():
                    setattr(m, k, v)
                monkeypatch.setitem(sys.modules, opt_mod, m)

    return stub_torch


def test_adapt_checkpoint_for_transformers_v5(monkeypatch):
    _get_torch_or_stub(monkeypatch)
    from backend.app.lrm.tsr.system import TSR

    legacy_ckpt = {
        "image_tokenizer.model.encoder.layer.0.attention.attention.query.weight": "w_q",
        "image_tokenizer.model.encoder.layer.0.attention.output.dense.bias": "b_o",
        "image_tokenizer.model.encoder.layer.0.intermediate.dense.weight": "w_fc1",
        "image_tokenizer.model.encoder.layer.0.output.dense.weight": "w_fc2",
        "image_tokenizer.model.encoder.layer.0.layernorm_before.weight": "ln1",
        "backbone.other.weight": "other",
    }
    modern_target = {
        "image_tokenizer.model.layers.0.attention.q_proj.weight": None,
    }
    adapted = TSR._adapt_checkpoint_for_transformers(legacy_ckpt, modern_target)
    assert adapted["image_tokenizer.model.layers.0.attention.q_proj.weight"] == "w_q"
    assert adapted["image_tokenizer.model.layers.0.attention.o_proj.bias"] == "b_o"
    assert adapted["image_tokenizer.model.layers.0.mlp.fc1.weight"] == "w_fc1"
    assert adapted["image_tokenizer.model.layers.0.mlp.fc2.weight"] == "w_fc2"
    assert adapted["image_tokenizer.model.layers.0.layernorm_before.weight"] == "ln1"
    assert adapted["backbone.other.weight"] == "other"


def test_generate_mesh_from_image_cleans_normals_degenerates_and_floating_debris(tmp_path):
    from PIL import Image

    torch_mod = _get_torch_or_stub()

    img_path = tmp_path / "sample.png"
    Image.new("RGB", (64, 64), (180, 90, 40)).save(img_path)

    # Criar malha principal + fragmento flutuante menor + face degenerada + normais invertidas
    main_body = trimesh.creation.icosphere(subdivisions=2, radius=0.5)
    main_body.faces = main_body.faces[:, [0, 2, 1]]  # Inverter normais propositalmente
    debris = trimesh.creation.icosphere(subdivisions=1, radius=0.05)
    debris.apply_translation([3.0, 3.0, 3.0])
    dirty_mesh = trimesh.util.concatenate([main_body, debris])
    # Adicionar face degenerada (vértices repetidos)
    degen_face = np.array([[0, 0, 0]], dtype=np.int64)
    dirty_mesh.faces = np.vstack([dirty_mesh.faces, degen_face])

    class FakeModel:
        def __call__(self, images, device=None):
            return ["fake_scene_code"]

        def extract_mesh(self, scene_codes, has_vertex_color=True, resolution=256):
            return [dirty_mesh.copy()]

    engine = object.__new__(TripoSREngine)
    engine._torch = torch_mod
    engine.device = "cpu"
    engine.model = FakeModel()
    engine._rembg_session = None

    cleaned = engine.generate_mesh_from_image(
        img_path,
        mcubes_resolution=64,
        remove_background=False,
    )

    # Deve manter apenas o corpo principal (320 faces da icosphere subdiv=2, descartando o fragmento e a face degenerada)
    assert len(cleaned.faces) == len(main_body.faces)
    assert cleaned.volume > 0.0
    assert np.isclose(cleaned.bounds[0][1], 0.0)
    assert np.isclose(cleaned.extents.max(), 1.0)


def test_generate_mesh_from_image_reorients_z_up_to_y_up_and_grounds_at_y_zero(tmp_path):
    """
    Garante que um objeto alongado gerado pelo TripoSR no seu espaço nativo Z-up
    (ex.: torre/pilar com dimensão maior no eixo Z = 4.0, profundidade X = 1.0, largura Y = 2.0)
    é rotacionado automaticamente para ficar em pé no eixo vertical Y (altura Y = 1.0m após normalização),
    com a frente (+X original) apontando para +Z e a base exatamente apoiada no chão (Y_min = 0.0).
    """
    from PIL import Image

    torch_mod = _get_torch_or_stub()

    img_path = tmp_path / "tower.png"
    Image.new("RGB", (64, 64), (120, 140, 180)).save(img_path)

    # Caixa nativa no espaço do TripoSR: X=1.0 (frente-trás), Y=2.0 (largura), Z=4.0 (altura Z-up)
    z_up_box = trimesh.creation.box(extents=[1.0, 2.0, 4.0])

    class FakeZUpModel:
        def __call__(self, images, device=None):
            return ["fake_scene_code"]

        def extract_mesh(self, scene_codes, has_vertex_color=True, resolution=256):
            return [z_up_box.copy()]

    engine = object.__new__(TripoSREngine)
    engine._torch = torch_mod
    engine.device = "cpu"
    engine.model = FakeZUpModel()
    engine._rembg_session = None

    oriented = engine.generate_mesh_from_image(
        img_path,
        mcubes_resolution=64,
        remove_background=False,
    )

    extents = oriented.extents
    bounds = oriented.bounds

    # Após rot_x(-90°) e rot_y(+90°) + normalização para 1.0m:
    # - Antigo Z (4.0) vira altura Y -> normalizado para 1.0m
    # - Antigo Y (2.0) vira largura X -> normalizado para 0.5m
    # - Antigo X (1.0) vira profundidade Z -> normalizado para 0.25m
    assert np.isclose(extents[1], 1.0, atol=1e-5)   # Altura vertical Y é o maior eixo (1.0m)
    assert np.isclose(extents[0], 0.5, atol=1e-5)   # Largura X (0.5m)
    assert np.isclose(extents[2], 0.25, atol=1e-5)  # Profundidade Z (0.25m)

    # Base apoiada no plano XZ (Y_min = 0.0, Y_max = 1.0) e X/Z centralizados na origem
    assert np.isclose(bounds[0][1], 0.0, atol=1e-5)
    assert np.isclose(bounds[1][1], 1.0, atol=1e-5)
    assert np.isclose(bounds[0][0], -bounds[1][0], atol=1e-5)
    assert np.isclose(bounds[0][2], -bounds[1][2], atol=1e-5)
    assert oriented.metadata.get("coordinate_system") == "Y-up"


def test_remove_background_fallback_without_rembg_handles_padding_resize_and_uniform(monkeypatch):
    from PIL import Image, ImageDraw

    _get_torch_or_stub(monkeypatch)
    monkeypatch.setitem(sys.modules, "rembg", None)

    engine = object.__new__(TripoSREngine)
    engine._rembg_session = None

    # 1. Imagem RGB comum (64x64) com objeto escuro em fundo branco (testa remoção do pad de 2px)
    small_img = Image.new("RGB", (64, 64), (255, 255, 255))
    ImageDraw.Draw(small_img).rectangle([16, 16, 48, 48], fill=(30, 80, 180))
    out_small = engine._remove_background(small_img)
    assert out_small.mode == "RGB"
    assert out_small.width == out_small.height and out_small.width > 0

    # 2. Imagem RGB grande (800x600 > 512px) onde `_extract_binary_mask` redimensiona a máscara
    large_img = Image.new("RGB", (800, 600), (250, 250, 250))
    ImageDraw.Draw(large_img).ellipse([200, 150, 600, 450], fill=(180, 40, 40))
    out_large = engine._remove_background(large_img)
    assert out_large.mode == "RGB"
    assert out_large.width == out_large.height and out_large.width > 0

    # 3. Imagem RGB uniforme (máscara vazia -> fallback para imagem opaca completa sem quebrar resize_foreground)
    uniform_img = Image.new("RGB", (64, 64), (255, 255, 255))
    out_uniform = engine._remove_background(uniform_img)
    assert out_uniform.mode == "RGB"
    assert out_uniform.width == out_uniform.height and out_uniform.width > 0

    # 4. Imagem RGBA já com transparência preservada
    rgba_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(rgba_img).rectangle([12, 12, 52, 52], fill=(40, 180, 90, 255))
    out_rgba = engine._remove_background(rgba_img)
    assert out_rgba.mode == "RGB"
    assert out_rgba.width == out_rgba.height and out_rgba.width > 0




