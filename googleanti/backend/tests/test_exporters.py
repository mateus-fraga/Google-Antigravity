import pytest
from pathlib import Path
from backend.app.procedural.engine import ProceduralGenerator
from backend.app.exporters.mesh_exporter import ModelExporter

def test_export_and_validate_glb(tmp_path: Path):
    mesh = ProceduralGenerator.create_box(1.0, 1.0, 1.0)
    out_file = tmp_path / "test_box.glb"
    
    result = ModelExporter.export_and_validate(mesh, out_file, fmt="glb")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert out_file.exists()

def test_export_and_validate_obj(tmp_path: Path):
    mesh = ProceduralGenerator.create_cylinder(0.5, 1.0, sections=16)
    out_file = tmp_path / "test_cyl.obj"
    
    result = ModelExporter.export_and_validate(mesh, out_file, fmt="obj")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert out_file.exists()

def test_export_and_validate_stl(tmp_path: Path):
    mesh = ProceduralGenerator.create_table(width=1.0, depth=0.8, height=0.7)
    out_file = tmp_path / "test_table.stl"
    
    result = ModelExporter.export_and_validate(mesh, out_file, fmt="stl")
    assert result["validated"] is True
    assert result["file_size_bytes"] > 0
    assert out_file.exists()
