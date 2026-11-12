import numpy as np
import pytest
from backend.app.procedural.engine import ProceduralGenerator


def test_create_box():
    """
    Task 3.2: Verifica que `create_box` gera paralelepípedo assimétrico em convenção Y-up:
    - Eixo X = width (2.0)
    - Eixo Y = height (1.0), apoiado no solo XZ (Y_min = 0.0, Y_max = 1.0)
    - Eixo Z = depth (3.0)
    """
    mesh = ProceduralGenerator.create_box(width=2.0, height=1.0, depth=3.0)
    assert not mesh.is_empty
    assert mesh.is_watertight
    assert len(mesh.vertices) == 8
    assert len(mesh.faces) == 12
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["is_watertight"] is True
    assert info["coordinate_system"] == "Y-up"
    assert info["geometry_schema_version"] == 2
    assert np.isclose(info["extents"][0], 2.0, atol=1e-4)  # X = width
    assert np.isclose(info["extents"][1], 1.0, atol=1e-4)  # Y = height
    assert np.isclose(info["extents"][2], 3.0, atol=1e-4)  # Z = depth
    assert np.isclose(info["bounds"][0][1], 0.0, atol=1e-5)
    assert np.isclose(info["bounds"][1][1], 1.0, atol=1e-5)


def test_create_cylinder():
    """
    Task 3.2: Verifica que `create_cylinder` gera cilindro vertical em Y-up:
    - Eixo Y = height (2.0), base em Y=0.0 e topo em Y=2.0
    - Secção circular no plano XZ com diâmetro = 2 * radius (2.0)
    """
    mesh = ProceduralGenerator.create_cylinder(radius=1.0, height=2.0, sections=32)
    assert not mesh.is_empty
    assert mesh.is_watertight
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["vertex_count"] > 0
    assert info["coordinate_system"] == "Y-up"
    assert np.isclose(info["extents"][1], 2.0, atol=1e-4)  # Y = height
    assert np.isclose(info["bounds"][0][1], 0.0, atol=1e-5)
    assert np.isclose(info["bounds"][1][1], 2.0, atol=1e-5)


def test_create_gear():
    """
    Task 3.2: Verifica que `create_gear` gera engrenagem com espessura ao longo do eixo Y (height=0.25)
    e perfil dentado no plano XZ, apoiada em Y=0.0.
    """
    mesh = ProceduralGenerator.create_gear(outer_radius=1.5, inner_radius=1.2, bore_radius=0.3, num_teeth=12, height=0.25)
    assert not mesh.is_empty
    assert mesh.is_watertight
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["face_count"] > 20
    assert info["coordinate_system"] == "Y-up"
    assert np.isclose(info["extents"][1], 0.25, atol=1e-4)  # Y = height (espessura)
    assert np.isclose(info["bounds"][0][1], 0.0, atol=1e-5)
    assert np.isclose(info["bounds"][1][1], 0.25, atol=1e-5)
    assert info["extents"][0] > 2.4  # Diâmetro no plano XZ > 2 * inner_radius
    assert info["extents"][2] > 2.4


def test_create_table():
    """
    Task 3.2: Verifica que `create_table` gera mesa assimétrica em Y-up:
    - Largura em X = 1.0, Altura em Y = 0.8 (de Y=0.0 a Y=0.8), Profundidade em Z = 0.6.
    """
    mesh = ProceduralGenerator.create_table(width=1.0, depth=0.6, height=0.8)
    assert not mesh.is_empty
    info = ProceduralGenerator.inspect_mesh(mesh)
    assert info["vertex_count"] == 8 * 5  # 5 caixas = 40 vértices
    assert np.isclose(info["extents"][0], 1.0, atol=1e-4)  # X = width
    assert np.isclose(info["extents"][1], 0.8, atol=1e-4)  # Y = height
    assert np.isclose(info["extents"][2], 0.6, atol=1e-4)  # Z = depth
    assert np.isclose(info["bounds"][0][1], 0.0, atol=1e-5)
    assert np.isclose(info["bounds"][1][1], 0.8, atol=1e-5)


def test_additional_primitives_sphere_cone_torus_y_up():
    """
    Task 3.2: Verifica que `sphere`, `cone` e `torus` também respeitam estritamente Y-up
    com base apoiada em Y = 0.0 e normais/vértices finitos.
    """
    sphere = ProceduralGenerator.generate_by_params("sphere", {"radius": 0.75, "subdivisions": 24})
    s_info = ProceduralGenerator.inspect_mesh(sphere)
    assert np.isclose(s_info["bounds"][0][1], 0.0, atol=1e-4)
    assert np.isclose(s_info["extents"][1], 1.5, atol=1e-2)
    assert s_info["has_finite_vertices"] is True

    cone = ProceduralGenerator.generate_by_params("cone", {"radius": 0.4, "height": 1.6, "sections": 32})
    c_info = ProceduralGenerator.inspect_mesh(cone)
    assert np.isclose(c_info["bounds"][0][1], 0.0, atol=1e-4)
    assert np.isclose(c_info["bounds"][1][1], 1.6, atol=1e-4)
    assert np.isclose(c_info["extents"][1], 1.6, atol=1e-4)

    torus = ProceduralGenerator.generate_by_params("torus", {"major_radius": 0.8, "minor_radius": 0.2, "sections": 24})
    t_info = ProceduralGenerator.inspect_mesh(torus)
    assert np.isclose(t_info["bounds"][0][1], 0.0, atol=1e-4)
    assert np.isclose(t_info["extents"][1], 0.4, atol=1e-2)


def test_procedural_generator_rejects_invalid_inputs_directly():
    """
    Task 3.1: Verifica que `ProceduralGenerator` rejeita entradas inválidas (NaN, Inf, <= 0,
    booleanos, formas inexistentes) diretamente sem substituir por geometrias silenciosas.
    """
    with pytest.raises(ValueError):
        ProceduralGenerator.create_box(width=float("nan"), height=1.0, depth=1.0)
    with pytest.raises(ValueError):
        ProceduralGenerator.create_box(width=1.0, height=-0.5, depth=1.0)
    with pytest.raises(ValueError):
        ProceduralGenerator.create_cylinder(radius=0.0, height=1.0)
    with pytest.raises(ValueError):
        ProceduralGenerator.create_gear(outer_radius=0.5, inner_radius=0.6)
    with pytest.raises(ValueError):
        ProceduralGenerator.generate_by_params("invalid_primitive", {"width": 1.0})

