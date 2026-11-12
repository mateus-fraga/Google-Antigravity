import math
import numpy as np
import trimesh
from typing import Dict, Any, Optional
from backend.app.schemas.geometry import (
    _ensure_finite_number,
    _ensure_strict_int,
    validate_procedural_parameters_dict,
    MIN_DIMENSION,
    MAX_DIMENSION,
    MIN_SECTIONS,
    MAX_SECTIONS,
    MIN_GEAR_TEETH,
    MAX_GEAR_TEETH,
)

# Matriz de rotação de -90 graus em torno do eixo X:
# Converte primitivas nativas do Trimesh geradas com eixo de extrusão Z (base XY)
# para a convenção glTF 2.0 / Three.js Y-up (eixo vertical Y, plano de solo XZ):
#   x' =  x
#   y' =  z
#   z' = -y
# Determinante = +1 (rotação própria da mão direita, preserva winding order anti-horário e normais externas).
_Z_UP_TO_Y_UP_MATRIX = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=np.float64,
)


class ProceduralGenerator:
    """
    Motor de geometria procedural local independente de Blender ou APIs externas.
    Utiliza Trimesh, NumPy e Shapely para geração, transformação e validação métrica.
    Opera nativamente sob a convenção Y-up (GEO-001 / glTF 2.0 / Three.js):
    - Eixo X: largura (horizontal)
    - Eixo Y: altura (vertical, com base assentada no plano XZ em Y = 0.0)
    - Eixo Z: profundidade (frente/trás)
    """

    COORDINATE_SYSTEM = "Y-up"
    GEOMETRY_SCHEMA_VERSION = 2

    @classmethod
    def _finalize_and_verify_mesh(cls, mesh: trimesh.Trimesh, shape_type: str = "procedural") -> trimesh.Trimesh:
        """
        GEO-001 (Task 3.2): Garante integridade topológica e numérica pós-geração:
        - Remove faces degeneradas (área zero) e vértices não referenciados;
        - Corrige consistência de winding e normais voltadas para o exterior (`trimesh.repair.fix_normals`);
        - Verifica ausência total de `NaN` ou `Inf` nos vértices e normais;
        - Anota metadados de orientação (`coordinate_system: "Y-up"`, `geometry_schema_version: 2`) em `mesh.metadata`.
        """
        if mesh is None or mesh.is_empty:
            raise ValueError(f"A malha gerada para '{shape_type}' está vazia.")

        if not np.all(np.isfinite(mesh.vertices)):
            raise ValueError(f"A malha gerada para '{shape_type}' contém vértices não finitos (NaN/Inf).")

        # Remover faces degeneradas (área > 1e-12) se existirem
        try:
            non_degen = mesh.nondegenerate_faces()
            if non_degen is not None and len(non_degen) == len(mesh.faces) and not np.all(non_degen):
                mesh.update_faces(non_degen)
                mesh.remove_unreferenced_vertices()
        except Exception:
            pass

        # Garantir winding consistente e normais externas
        try:
            trimesh.repair.fix_winding(mesh)
            trimesh.repair.fix_inversion(mesh)
            trimesh.repair.fix_normals(mesh)
        except Exception:
            pass

        if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
            raise ValueError(f"A malha gerada para '{shape_type}' não possui faces ou vértices válidos.")

        if not np.all(np.isfinite(mesh.face_normals)):
            raise ValueError(f"A malha gerada para '{shape_type}' contém normais não finitas.")

        if mesh.metadata is None:
            mesh.metadata = {}
        mesh.metadata["coordinate_system"] = cls.COORDINATE_SYSTEM
        mesh.metadata["geometry_schema_version"] = cls.GEOMETRY_SCHEMA_VERSION
        mesh.metadata["shape_type"] = shape_type
        return mesh

    @classmethod
    def create_box(cls, width: float = 1.0, height: float = 1.0, depth: float = 1.0) -> trimesh.Trimesh:
        """
        Gera um cubo / paralelepípedo paramétrico em convenção Y-up:
        - Eixo X = width (centrado em 0: [-width/2, +width/2])
        - Eixo Y = height (apoiado no solo XZ: [0.0, height])
        - Eixo Z = depth (centrado em 0: [-depth/2, +depth/2])
        """
        w = _ensure_finite_number(width, "width")
        h = _ensure_finite_number(height, "height")
        d = _ensure_finite_number(depth, "depth")
        for name, val in (("width", w), ("height", h), ("depth", d)):
            if val < MIN_DIMENSION or val > MAX_DIMENSION:
                raise ValueError(f"Dimensão '{name}' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {val}")

        mesh = trimesh.creation.box(extents=[w, h, d])
        # Assentar a base no solo XZ (Y = 0.0 -> Y_max = h)
        mesh.apply_translation([0.0, h / 2.0, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="box")

    @classmethod
    def create_cylinder(cls, radius: float = 0.5, height: float = 1.0, sections: int = 32) -> trimesh.Trimesh:
        """
        Gera um cilindro paramétrico vertical em convenção Y-up:
        - Secção circular no plano XZ com raio `radius` (diâmetro 2*radius em X e Z)
        - Altura ao longo do eixo Y (base em Y = 0.0, topo em Y = height)
        """
        r = _ensure_finite_number(radius, "radius")
        h = _ensure_finite_number(height, "height")
        sec = _ensure_strict_int(sections, "sections", MIN_SECTIONS, MAX_SECTIONS)
        for name, val in (("radius", r), ("height", h)):
            if val < MIN_DIMENSION or val > MAX_DIMENSION:
                raise ValueError(f"Dimensão '{name}' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {val}")

        mesh = trimesh.creation.cylinder(radius=r, height=h, sections=sec)
        # Trimesh cria o cilindro ao longo do eixo Z centrado na origem; rotacionar para eixo Y vertical
        mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        mesh.apply_translation([0.0, h / 2.0, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="cylinder")

    @classmethod
    def create_gear(
        cls,
        outer_radius: float = 1.0,
        inner_radius: float = 0.8,
        bore_radius: float = 0.3,
        num_teeth: int = 12,
        height: float = 0.2
    ) -> trimesh.Trimesh:
        """
        Gera uma engrenagem mecânica paramétrica com dentes reais e furo central em convenção Y-up:
        - Perfil radial dentado no plano XZ (diâmetro ~ 2*outer_radius em X e Z)
        - Espessura/altura extrudada ao longo do eixo Y (base em Y = 0.0, topo em Y = height)
        """
        validated = validate_procedural_parameters_dict(
            "gear",
            {
                "outer_radius": outer_radius,
                "inner_radius": inner_radius,
                "bore_radius": bore_radius,
                "num_teeth": num_teeth,
                "height": height,
            },
        )
        outer_r = validated["outer_radius"]
        inner_r = validated["inner_radius"]
        bore_r = validated["bore_radius"]
        teeth = validated["num_teeth"]
        h = validated["height"]

        # Construir perfil 2D
        points = []
        angle_step = 2 * np.pi / teeth
        for i in range(teeth):
            base_angle = i * angle_step
            a1 = base_angle
            a2 = base_angle + angle_step * 0.25
            a3 = base_angle + angle_step * 0.4
            a4 = base_angle + angle_step * 0.6
            a5 = base_angle + angle_step * 0.75

            points.append([inner_r * np.cos(a1), inner_r * np.sin(a1)])
            points.append([outer_r * np.cos(a2), outer_r * np.sin(a2)])
            points.append([outer_r * np.cos(a3), outer_r * np.sin(a3)])
            points.append([inner_r * np.cos(a4), inner_r * np.sin(a4)])
            points.append([inner_r * np.cos(a5), inner_r * np.sin(a5)])

        from shapely.geometry import Polygon

        polygon = Polygon(points)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if bore_r > 0:
            bore_points = [
                [bore_r * np.cos(a), bore_r * np.sin(a)]
                for a in np.linspace(0, 2 * np.pi, max(32, teeth * 2), endpoint=False)
            ]
            bore_poly = Polygon(bore_points)
            polygon = polygon.difference(bore_poly)

        # `extrude_polygon` extruda de z=0 até z=h no espaço Z-up do Trimesh.
        # Aplicando `_Z_UP_TO_Y_UP_MATRIX`, z=[0, h] torna-se diretamente y=[0, h] apoiado no plano XZ!
        mesh = trimesh.creation.extrude_polygon(polygon, height=h)
        mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        # Garantir alinhamento numérico exato da base em Y = 0.0
        min_y = float(mesh.bounds[0][1])
        if abs(min_y) > 1e-9:
            mesh.apply_translation([0.0, -min_y, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="gear")

    @classmethod
    def create_table(
        cls,
        width: float = 1.2,
        depth: float = 0.8,
        height: float = 0.75,
        top_thickness: float = 0.05,
        leg_thickness: float = 0.05
    ) -> trimesh.Trimesh:
        """
        Gera uma mesa paramétrica (tampo + 4 pernas) em convenção Y-up:
        - Largura ao longo de X (`width`), altura vertical ao longo de Y (`height`, de Y=0 até Y=height),
          profundidade ao longo de Z (`depth`).
        - Pernas apoiadas em Y = 0.0 até Y = height - top_thickness.
        - Tampo horizontal no plano XZ de Y = height - top_thickness até Y = height.
        """
        validated = validate_procedural_parameters_dict(
            "table",
            {
                "width": width,
                "depth": depth,
                "height": height,
                "top_thickness": top_thickness,
                "leg_thickness": leg_thickness,
            },
        )
        w = validated["width"]
        d = validated["depth"]
        h = validated["height"]
        top_t = validated["top_thickness"]
        leg_t = validated["leg_thickness"]

        # Tampo horizontal no plano XZ elevado em Y
        top = trimesh.creation.box(extents=[w, top_t, d])
        top.apply_translation([0.0, h - top_t / 2.0, 0.0])

        leg_height = h - top_t
        leg_offset_x = (w / 2.0) - leg_t
        leg_offset_z = (d / 2.0) - leg_t

        legs = []
        for sx in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                leg = trimesh.creation.box(extents=[leg_t, leg_height, leg_t])
                leg.apply_translation([sx * leg_offset_x, leg_height / 2.0, sz * leg_offset_z])
                legs.append(leg)

        all_parts = [top] + legs
        combined = trimesh.util.concatenate(all_parts)
        return cls._finalize_and_verify_mesh(combined, shape_type="table")

    @classmethod
    def create_sphere(cls, radius: float = 0.5, subdivisions: int = 32) -> trimesh.Trimesh:
        """
        Gera uma esfera paramétrica em convenção Y-up assentada no plano XZ (Y_min = 0.0, Y_max = 2*radius).
        """
        r = _ensure_finite_number(radius, "radius")
        sub = _ensure_strict_int(subdivisions, "subdivisions", MIN_SECTIONS, MAX_SECTIONS)
        if r < MIN_DIMENSION or r > MAX_DIMENSION:
            raise ValueError(f"Dimensão 'radius' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {r}")

        u_count = max(8, min(128, sub))
        v_count = max(8, min(128, sub))
        mesh = trimesh.creation.uv_sphere(radius=r, count=[u_count, v_count])
        mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        min_y = float(mesh.bounds[0][1])
        mesh.apply_translation([0.0, -min_y, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="sphere")

    @classmethod
    def create_cone(cls, radius: float = 0.5, height: float = 1.0, sections: int = 32) -> trimesh.Trimesh:
        """
        Gera um cone paramétrico vertical em convenção Y-up (base circular no plano XZ em Y=0.0, ápice em Y=height).
        """
        r = _ensure_finite_number(radius, "radius")
        h = _ensure_finite_number(height, "height")
        sec = _ensure_strict_int(sections, "sections", MIN_SECTIONS, MAX_SECTIONS)
        for name, val in (("radius", r), ("height", h)):
            if val < MIN_DIMENSION or val > MAX_DIMENSION:
                raise ValueError(f"Dimensão '{name}' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}]m: {val}")

        mesh = trimesh.creation.cone(radius=r, height=h, sections=sec)
        # Trimesh cria o cone com base em Z=0 e ápice em Z=height; rotacionando por _Z_UP_TO_Y_UP_MATRIX,
        # a base fica em Y=0 e o ápice em Y=height.
        mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        min_y = float(mesh.bounds[0][1])
        if abs(min_y) > 1e-9:
            mesh.apply_translation([0.0, -min_y, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="cone")

    @classmethod
    def create_torus(cls, major_radius: float = 0.6, minor_radius: float = 0.2, sections: int = 32) -> trimesh.Trimesh:
        """
        Gera um torus horizontal paralelo ao plano XZ e assentado em Y = 0.0 (Y_max = 2*minor_radius).
        """
        validated = validate_procedural_parameters_dict(
            "torus",
            {"major_radius": major_radius, "minor_radius": minor_radius, "sections": sections},
        )
        maj_r = validated["major_radius"]
        min_r = validated["minor_radius"]
        sec = validated["sections"]

        mesh = trimesh.creation.torus(major_radius=maj_r, minor_radius=min_r, major_sections=sec, minor_sections=sec)
        mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        min_y = float(mesh.bounds[0][1])
        mesh.apply_translation([0.0, -min_y, 0.0])
        return cls._finalize_and_verify_mesh(mesh, shape_type="torus")

    @classmethod
    def generate_by_params(cls, shape_type: str, params: Dict[str, Any]) -> trimesh.Trimesh:
        """Despacha a criação baseada no tipo de forma após validação estrita dos parâmetros."""
        if not isinstance(params, dict):
            raise ValueError("Os parâmetros geométricos devem ser um dicionário válido.")

        flat_params = dict(params)
        if isinstance(flat_params.get("dimensions"), dict):
            for k, v in flat_params["dimensions"].items():
                flat_params.setdefault(k, v)

        validated = validate_procedural_parameters_dict(shape_type, flat_params)
        norm_shape = validated["shape_type"]

        if norm_shape in ("box", "wall"):
            return cls.create_box(
                width=validated["width"],
                height=validated["height"],
                depth=validated["depth"],
            )
        elif norm_shape == "cylinder":
            return cls.create_cylinder(
                radius=validated["radius"],
                height=validated["height"],
                sections=validated["sections"],
            )
        elif norm_shape == "gear":
            return cls.create_gear(
                outer_radius=validated["outer_radius"],
                inner_radius=validated["inner_radius"],
                bore_radius=validated["bore_radius"],
                num_teeth=validated["num_teeth"],
                height=validated["height"],
            )
        elif norm_shape == "table":
            return cls.create_table(
                width=validated["width"],
                depth=validated["depth"],
                height=validated["height"],
                top_thickness=validated["top_thickness"],
                leg_thickness=validated["leg_thickness"],
            )
        elif norm_shape == "sphere":
            return cls.create_sphere(
                radius=validated["radius"],
                subdivisions=validated["subdivisions"],
            )
        elif norm_shape == "cone":
            return cls.create_cone(
                radius=validated["radius"],
                height=validated["height"],
                sections=validated["sections"],
            )
        elif norm_shape == "torus":
            return cls.create_torus(
                major_radius=validated["major_radius"],
                minor_radius=validated["minor_radius"],
                sections=validated["sections"],
            )
        else:
            raise ValueError(f"Forma procedural não suportada: '{shape_type}'")

    @classmethod
    def resolve_coordinate_metadata(
        cls,
        metadata_or_params: Optional[Dict[str, Any]] = None,
        has_existing_model: bool = True
    ) -> Dict[str, Any]:
        """
        GEO-001 (Task 3.3): Identifica de forma determinística a convenção de coordenadas de um modelo/projeto,
        diferenciando modelos nativos `Y-up` (`geometry_schema_version >= 2`) de modelos legados (`legacy_z_up`),
        e indicando se conversão de eixo é necessária (`requires_z_to_y_conversion`), prevenindo dupla conversão.
        """
        data = metadata_or_params if isinstance(metadata_or_params, dict) else {}
        # Buscar em nível raiz ou dentro de sub-dicionário 'inspection'
        coord = data.get("coordinate_system")
        version = data.get("geometry_schema_version")
        if not coord and isinstance(data.get("inspection"), dict):
            coord = data["inspection"].get("coordinate_system")
            version = data["inspection"].get("geometry_schema_version")

        if coord == "Y-up" or (isinstance(version, int) and not isinstance(version, bool) and version >= 2):
            return {
                "coordinate_system": "Y-up",
                "geometry_schema_version": int(version) if isinstance(version, int) and not isinstance(version, bool) else cls.GEOMETRY_SCHEMA_VERSION,
                "is_legacy": False,
                "requires_z_to_y_conversion": False,
            }

        if coord == "legacy_z_up" or has_existing_model:
            return {
                "coordinate_system": "legacy_z_up",
                "geometry_schema_version": 1,
                "is_legacy": True,
                "requires_z_to_y_conversion": True,
            }

        return {
            "coordinate_system": "Y-up",
            "geometry_schema_version": cls.GEOMETRY_SCHEMA_VERSION,
            "is_legacy": False,
            "requires_z_to_y_conversion": False,
        }

    @classmethod
    def normalize_legacy_mesh_to_y_up(
        cls,
        mesh: trimesh.Trimesh,
        metadata_or_params: Optional[Dict[str, Any]] = None
    ) -> trimesh.Trimesh:
        """
        GEO-001 (Task 3.3): Converte uma malha legada gerada em `Z-up` para `Y-up` APENAS se seus
        metadados indicarem origem legada (`legacy_z_up`), marcando-a como `Y-up` (`geometry_schema_version = 2`)
        após a rotação para garantir idempotência estrita (nunca aplica a conversão duas vezes).
        """
        if mesh is None or mesh.is_empty:
            raise ValueError("Não é possível normalizar uma malha vazia.")

        effective_meta: Dict[str, Any] = {}
        if isinstance(mesh.metadata, dict):
            effective_meta.update(mesh.metadata)
        if isinstance(metadata_or_params, dict):
            effective_meta.update(metadata_or_params)

        resolution = cls.resolve_coordinate_metadata(effective_meta, has_existing_model=True)
        result_mesh = mesh.copy()
        if result_mesh.metadata is None:
            result_mesh.metadata = {}

        if not resolution["requires_z_to_y_conversion"]:
            result_mesh.metadata["coordinate_system"] = "Y-up"
            result_mesh.metadata["geometry_schema_version"] = cls.GEOMETRY_SCHEMA_VERSION
            result_mesh.metadata["converted_from_legacy_z_up"] = bool(
                effective_meta.get("converted_from_legacy_z_up", False)
            )
            return result_mesh

        # Rotacionar de Z-up para Y-up e alinhar base em Y = 0.0
        result_mesh.apply_transform(_Z_UP_TO_Y_UP_MATRIX)
        min_y = float(result_mesh.bounds[0][1])
        if abs(min_y) > 1e-9:
            result_mesh.apply_translation([0.0, -min_y, 0.0])

        result_mesh.metadata["coordinate_system"] = "Y-up"
        result_mesh.metadata["geometry_schema_version"] = cls.GEOMETRY_SCHEMA_VERSION
        result_mesh.metadata["converted_from_legacy_z_up"] = True
        return result_mesh

    @classmethod
    def inspect_mesh(cls, mesh: trimesh.Trimesh) -> Dict[str, Any]:
        """
        GEO-001 (Task 3.2): Calcula telemetria e integridade geométrica real da malha,
        incluindo `bounds` (`[[min_x, min_y, min_z], [max_x, max_y, max_z]]`), `extents` (`[dx, dy, dz]`),
        `coordinate_system: "Y-up"`, `geometry_schema_version: 2`, `is_watertight`, `has_finite_vertices`
        e `has_valid_normals`.
        """
        bounds_arr = mesh.bounds
        if bounds_arr is not None:
            bounds_list = [[float(v) for v in bounds_arr[0]], [float(v) for v in bounds_arr[1]]]
            extents = [float(v) for v in mesh.extents.tolist()]
        else:
            bounds_list = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
            extents = [0.0, 0.0, 0.0]

        meta = mesh.metadata if isinstance(getattr(mesh, "metadata", None), dict) else {}
        coord_system = meta.get("coordinate_system", cls.COORDINATE_SYSTEM)
        schema_version = int(meta.get("geometry_schema_version", cls.GEOMETRY_SCHEMA_VERSION))

        has_finite_vertices = bool(len(mesh.vertices) > 0 and np.all(np.isfinite(mesh.vertices)))
        has_valid_normals = bool(len(mesh.faces) > 0 and np.all(np.isfinite(mesh.face_normals)))

        return {
            "vertex_count": int(len(mesh.vertices)),
            "face_count": int(len(mesh.faces)),
            "is_watertight": bool(mesh.is_watertight),
            "bounds": bounds_list,
            "extents": extents,
            "volume": float(mesh.volume) if mesh.is_volume else None,
            "is_empty": bool(mesh.is_empty),
            "coordinate_system": coord_system,
            "geometry_schema_version": schema_version,
            "up_axis": "Y",
            "ground_plane": "XZ",
            "has_finite_vertices": has_finite_vertices,
            "has_valid_normals": has_valid_normals,
        }

