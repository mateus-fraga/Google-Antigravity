import pytest
from backend.app.procedural.engine import ProceduralGenerator

def test_create_box():
    mesh = ProceduralGenerator.create_box(width=2.0, height=1.0, depth=3.0)
    assert not mesh.is_empty
    assert mesh.is_watertight
    assert len(mesh.vertices) == 8
    assert len(mesh.faces) == 12
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["is_watertight"] is True
    assert round(info["extents"][0], 2) == 2.0
    assert round(info["extents"][1], 2) == 3.0
    assert round(info["extents"][2], 2) == 1.0

def test_create_cylinder():
    mesh = ProceduralGenerator.create_cylinder(radius=1.0, height=2.0, sections=16)
    assert not mesh.is_empty
    assert mesh.is_watertight
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["vertex_count"] > 0
    assert round(info["extents"][2], 2) == 2.0

def test_create_gear():
    mesh = ProceduralGenerator.create_gear(outer_radius=1.5, inner_radius=1.2, num_teeth=8, height=0.25)
    assert not mesh.is_empty
    assert mesh.is_watertight
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["face_count"] > 20

def test_create_table():
    mesh = ProceduralGenerator.create_table(width=1.0, depth=0.6, height=0.8)
    assert not mesh.is_empty
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["vertex_count"] == 8 * 5  # 5 caixas = 40 vértices
