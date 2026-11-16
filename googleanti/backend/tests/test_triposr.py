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


def test_adapt_checkpoint_for_transformers_v5():
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
    import torch

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
    engine._torch = torch
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



