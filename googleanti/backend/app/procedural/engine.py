import numpy as np
import trimesh
from typing import Dict, Any, Tuple

class ProceduralGenerator:
    """
    Motor de geometria procedural local independente de Blender ou APIs externas.
    Utiliza Trimesh e NumPy para geração, transformação e validação métrica.
    """

    @staticmethod
    def create_box(width: float = 1.0, height: float = 1.0, depth: float = 1.0) -> trimesh.Trimesh:
        """Gera um cubo / paralelepípedo paramétrico."""
        width = max(0.01, float(width))
        height = max(0.01, float(height))
        depth = max(0.01, float(depth))
        mesh = trimesh.creation.box(extents=[width, depth, height])
        # Centralizar a base no chão (Z=0)
        mesh.apply_translation([0, 0, height / 2.0])
        return mesh

    @staticmethod
    def create_cylinder(radius: float = 0.5, height: float = 1.0, sections: int = 32) -> trimesh.Trimesh:
        """Gera um cilindro paramétrico."""
        radius = max(0.01, float(radius))
        height = max(0.01, float(height))
        sections = max(8, min(128, int(sections)))
        mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
        mesh.apply_translation([0, 0, height / 2.0])
        return mesh

    @staticmethod
    def create_gear(
        outer_radius: float = 1.0,
        inner_radius: float = 0.8,
        bore_radius: float = 0.3,
        num_teeth: int = 12,
        height: float = 0.2
    ) -> trimesh.Trimesh:
        """
        Gera uma engrenagem mecânica paramétrica com dentes reais e furo central.
        """
        num_teeth = max(4, min(64, int(num_teeth)))
        outer_radius = max(0.2, float(outer_radius))
        inner_radius = max(0.1, min(outer_radius - 0.05, float(inner_radius)))
        bore_radius = max(0.0, min(inner_radius - 0.05, float(bore_radius)))
        height = max(0.01, float(height))

        # Construir perfil 2D
        points = []
        angle_step = 2 * np.pi / num_teeth
        for i in range(num_teeth):
            base_angle = i * angle_step
            # Base do dente
            a1 = base_angle
            a2 = base_angle + angle_step * 0.25
            # Topo do dente
            a3 = base_angle + angle_step * 0.4
            a4 = base_angle + angle_step * 0.6
            # Descida
            a5 = base_angle + angle_step * 0.75

            points.append([inner_radius * np.cos(a1), inner_radius * np.sin(a1)])
            points.append([outer_radius * np.cos(a2), outer_radius * np.sin(a2)])
            points.append([outer_radius * np.cos(a3), outer_radius * np.sin(a3)])
            points.append([inner_radius * np.cos(a4), inner_radius * np.sin(a4)])
            points.append([inner_radius * np.cos(a5), inner_radius * np.sin(a5)])

        from shapely.geometry import Polygon

        polygon = Polygon(points)
        if bore_radius > 0:
            # Subtrair furo central
            bore_points = [
                [bore_radius * np.cos(a), bore_radius * np.sin(a)]
                for a in np.linspace(0, 2 * np.pi, 32, endpoint=False)
            ]
            bore_poly = Polygon(bore_points)
            polygon = polygon.difference(bore_poly)

        mesh = trimesh.creation.extrude_polygon(polygon, height=height)
        mesh.apply_translation([0, 0, height / 2.0])
        return mesh

    @staticmethod
    def create_table(
        width: float = 1.2,
        depth: float = 0.8,
        height: float = 0.75,
        top_thickness: float = 0.05,
        leg_thickness: float = 0.05
    ) -> trimesh.Trimesh:
        """
        Gera uma mesa paramétrica (tampo + 4 pernas) combinando geometrias estanques.
        """
        # Tampo
        top = trimesh.creation.box(extents=[width, depth, top_thickness])
        top.apply_translation([0, 0, height - top_thickness / 2.0])

        leg_height = height - top_thickness
        leg_offset_x = (width / 2.0) - leg_thickness
        leg_offset_y = (depth / 2.0) - leg_thickness

        legs = []
        for sx in [-1, 1]:
            for sy in [-1, 1]:
                leg = trimesh.creation.box(extents=[leg_thickness, leg_thickness, leg_height])
                leg.apply_translation([sx * leg_offset_x, sy * leg_offset_y, leg_height / 2.0])
                legs.append(leg)

        all_parts = [top] + legs
        combined = trimesh.util.concatenate(all_parts)
        return combined

    @classmethod
    def generate_by_params(cls, shape_type: str, params: Dict[str, Any]) -> trimesh.Trimesh:
        """Despacha a criação baseada no tipo de forma."""
        shape_type = shape_type.lower()
        if shape_type == "box":
            return cls.create_box(
                width=params.get("width", 1.0),
                height=params.get("height", 1.0),
                depth=params.get("depth", 1.0)
            )
        elif shape_type == "cylinder":
            return cls.create_cylinder(
                radius=params.get("radius", 0.5),
                height=params.get("height", 1.0),
                sections=params.get("sections", 32)
            )
        elif shape_type == "gear":
            return cls.create_gear(
                outer_radius=params.get("outer_radius", 1.0),
                inner_radius=params.get("inner_radius", 0.8),
                bore_radius=params.get("bore_radius", 0.3),
                num_teeth=params.get("num_teeth", 12),
                height=params.get("height", 0.2)
            )
        elif shape_type == "table":
            return cls.create_table(
                width=params.get("width", 1.2),
                depth=params.get("depth", 0.8),
                height=params.get("height", 0.75),
                top_thickness=params.get("top_thickness", 0.05),
                leg_thickness=params.get("leg_thickness", 0.05)
            )
        else:
            raise ValueError(f"Forma procedural não suportada: '{shape_type}'")

    @staticmethod
    def inspect_mesh(mesh: trimesh.Trimesh) -> Dict[str, Any]:
        """Calcula telemetria e integridade geométrica da malha."""
        bounds = mesh.bounds
        extents = mesh.extents.tolist() if bounds is not None else [0, 0, 0]
        return {
            "vertex_count": len(mesh.vertices),
            "face_count": len(mesh.faces),
            "is_watertight": bool(mesh.is_watertight),
            "extents": extents,
            "volume": float(mesh.volume) if mesh.is_volume else None,
            "is_empty": bool(mesh.is_empty)
        }
