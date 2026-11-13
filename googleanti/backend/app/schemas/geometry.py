from enum import Enum
import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

SUPPORTED_PROCEDURAL_SHAPES = {"box", "cylinder", "gear", "table", "sphere", "cone", "torus", "wall"}
SUPPORTED_COORDINATE_SYSTEMS = {"Y-up", "legacy_z_up"}

MIN_DIMENSION = 1e-4
MAX_DIMENSION = 1000.0
MIN_SECTIONS = 4
MAX_SECTIONS = 256
MIN_GEAR_TEETH = 4
MAX_GEAR_TEETH = 128


def _ensure_finite_number(val: Any, field_name: str, allow_zero: bool = False, allow_negative: bool = False) -> float:
    """
    Valida que `val` é um número real finito (`int` ou `float`, nunca `bool` ou string arbitrária),
    rejeitando explicitamente `NaN`, `Infinity`, `-Infinity` e aplicando restrições de sinal.
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"O campo '{field_name}' deve ser um número real válido (booleanos ou tipos não numéricos não são permitidos).")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"O campo '{field_name}' contém valor não finito (NaN ou Infinito não são permitidos).")
    if not allow_negative and fval < 0.0:
        raise ValueError(f"O campo '{field_name}' não pode ser negativo (recebido: {val}).")
    if not allow_zero and not allow_negative and fval <= 0.0:
        raise ValueError(f"O campo '{field_name}' deve ser estritamente maior que zero (recebido: {val}).")
    return fval


def _ensure_strict_int(val: Any, field_name: str, min_val: int, max_val: int) -> int:
    """
    Valida que `val` é um inteiro estrito (não `bool` nem float fracionário) dentro de `[min_val, max_val]`.
    """
    if isinstance(val, bool):
        raise ValueError(f"O campo '{field_name}' deve ser um número inteiro (booleano não permitido).")
    if isinstance(val, float):
        if not math.isfinite(val) or not val.is_integer():
            raise ValueError(f"O campo '{field_name}' deve ser um número inteiro exato.")
        ival = int(val)
    elif isinstance(val, int):
        ival = val
    else:
        raise ValueError(f"O campo '{field_name}' deve ser um número inteiro válido.")
    if ival < min_val or ival > max_val:
        raise ValueError(f"O campo '{field_name}' deve estar entre {min_val} e {max_val} (recebido: {ival}).")
    return ival


def validate_procedural_parameters_dict(shape_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    GEO-001 (Task 3.1): Valida rigorosamente um dicionário de parâmetros procedurais para `shape_type`,
    rejeitando valores não finitos (`NaN`, `Inf`, `-Inf`), booleanos disfarçados de números,
    dimensões <= 0, contagens de dentes/segmentos fora dos limites seguros e relações geométricas
    inválidas (ex.: `inner_radius >= outer_radius` ou `top_thickness >= height`).
    Retorna um novo dicionário com os parâmetros normalizados e validados.
    """
    if not isinstance(shape_type, str) or not shape_type.strip():
        raise ValueError("O tipo de forma ('shape_type') deve ser uma string não vazia.")
    norm_shape = shape_type.strip().lower()
    if norm_shape not in SUPPORTED_PROCEDURAL_SHAPES:
        raise ValueError(
            f"Forma procedural não suportada: '{shape_type}'. "
            f"Formas suportadas: {sorted(SUPPORTED_PROCEDURAL_SHAPES)}"
        )

    if not isinstance(params, dict):
        raise ValueError("Os parâmetros geométricos devem ser fornecidos em um objeto/dicionário.")

    # Verificar recursivamente se há qualquer float não finito ou booleano em campos numéricos conhecidos
    numeric_positive_keys = {
        "width", "height", "depth", "radius", "outer_radius", "inner_radius",
        "top_thickness", "leg_thickness", "major_radius", "minor_radius", "thickness"
    }
    non_negative_keys = {"bore_radius"}
    integer_keys = {
        "sections": (MIN_SECTIONS, MAX_SECTIONS),
        "subdivisions": (MIN_SECTIONS, MAX_SECTIONS),
        "num_teeth": (MIN_GEAR_TEETH, MAX_GEAR_TEETH),
    }

    cleaned: Dict[str, Any] = dict(params)
    cleaned["shape_type"] = norm_shape

    for k, v in params.items():
        if v is None:
            continue
        if k in numeric_positive_keys:
            fval = _ensure_finite_number(v, k, allow_zero=False, allow_negative=False)
            if fval < MIN_DIMENSION or fval > MAX_DIMENSION:
                raise ValueError(
                    f"Dimensão '{k}' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}] metros (recebido: {fval})."
                )
            cleaned[k] = fval
        elif k in non_negative_keys:
            fval = _ensure_finite_number(v, k, allow_zero=True, allow_negative=False)
            if fval > MAX_DIMENSION:
                raise ValueError(
                    f"Dimensão '{k}' excede o limite máximo de {MAX_DIMENSION} metros (recebido: {fval})."
                )
            cleaned[k] = fval
        elif k in integer_keys:
            min_i, max_i = integer_keys[k]
            cleaned[k] = _ensure_strict_int(v, k, min_i, max_i)
        elif isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"O parâmetro '{k}' contém valor numérico não finito (NaN ou Infinito).")

    # Validações relacionais específicas por forma
    if norm_shape == "gear":
        outer_r = cleaned.get("outer_radius", 1.0)
        inner_r = cleaned.get("inner_radius", outer_r * 0.75 if "outer_radius" in cleaned and "inner_radius" not in cleaned else 0.8)
        bore_r = cleaned.get("bore_radius", 0.3)
        num_teeth = cleaned.get("num_teeth", 12)
        height = cleaned.get("height", 0.2)

        outer_r = _ensure_finite_number(outer_r, "outer_radius")
        inner_r = _ensure_finite_number(inner_r, "inner_radius")
        bore_r = _ensure_finite_number(bore_r, "bore_radius", allow_zero=True)
        num_teeth = _ensure_strict_int(num_teeth, "num_teeth", MIN_GEAR_TEETH, MAX_GEAR_TEETH)
        height = _ensure_finite_number(height, "height")

        if inner_r >= outer_r:
            raise ValueError(
                f"Parâmetros inválidos para engrenagem: 'inner_radius' ({inner_r}) deve ser estritamente menor que 'outer_radius' ({outer_r})."
            )
        if bore_r >= inner_r:
            raise ValueError(
                f"Parâmetros inválidos para engrenagem: 'bore_radius' ({bore_r}) deve ser estritamente menor que 'inner_radius' ({inner_r})."
            )
        cleaned.update({
            "outer_radius": outer_r,
            "inner_radius": inner_r,
            "bore_radius": bore_r,
            "num_teeth": num_teeth,
            "height": height,
        })

    elif norm_shape == "table":
        width = _ensure_finite_number(cleaned.get("width", 1.2), "width")
        depth = _ensure_finite_number(cleaned.get("depth", 0.8), "depth")
        height = _ensure_finite_number(cleaned.get("height", 0.75), "height")
        top_thickness = _ensure_finite_number(cleaned.get("top_thickness", 0.05), "top_thickness")
        leg_thickness = _ensure_finite_number(cleaned.get("leg_thickness", 0.05), "leg_thickness")

        if top_thickness >= height:
            raise ValueError(
                f"Parâmetros inválidos para mesa: 'top_thickness' ({top_thickness}) deve ser estritamente menor que 'height' ({height})."
            )
        if leg_thickness * 2.0 >= min(width, depth):
            raise ValueError(
                f"Parâmetros inválidos para mesa: 'leg_thickness' ({leg_thickness}) é excessiva para a largura/profundidade ({width}x{depth})."
            )
        cleaned.update({
            "width": width,
            "depth": depth,
            "height": height,
            "top_thickness": top_thickness,
            "leg_thickness": leg_thickness,
        })

    elif norm_shape == "cylinder":
        radius = _ensure_finite_number(cleaned.get("radius", 0.5), "radius")
        height = _ensure_finite_number(cleaned.get("height", 1.0), "height")
        sections = _ensure_strict_int(cleaned.get("sections", cleaned.get("subdivisions", 32)), "sections", MIN_SECTIONS, MAX_SECTIONS)
        cleaned.update({"radius": radius, "height": height, "sections": sections})

    elif norm_shape in ("box", "wall"):
        width = _ensure_finite_number(cleaned.get("width", 1.0), "width")
        height = _ensure_finite_number(cleaned.get("height", 1.0), "height")
        depth = _ensure_finite_number(cleaned.get("depth", 1.0), "depth")
        cleaned.update({"width": width, "height": height, "depth": depth})

    elif norm_shape == "sphere":
        radius = _ensure_finite_number(cleaned.get("radius", 0.5), "radius")
        subdivisions = _ensure_strict_int(cleaned.get("subdivisions", cleaned.get("sections", 32)), "subdivisions", MIN_SECTIONS, MAX_SECTIONS)
        cleaned.update({"radius": radius, "subdivisions": subdivisions})

    elif norm_shape == "cone":
        radius = _ensure_finite_number(cleaned.get("radius", 0.5), "radius")
        height = _ensure_finite_number(cleaned.get("height", 1.0), "height")
        sections = _ensure_strict_int(cleaned.get("sections", 32), "sections", MIN_SECTIONS, MAX_SECTIONS)
        cleaned.update({"radius": radius, "height": height, "sections": sections})

    elif norm_shape == "torus":
        major_radius = _ensure_finite_number(cleaned.get("major_radius", cleaned.get("outer_radius", 0.6)), "major_radius")
        minor_radius = _ensure_finite_number(cleaned.get("minor_radius", cleaned.get("inner_radius", 0.2)), "minor_radius")
        if minor_radius >= major_radius:
            raise ValueError(
                f"Parâmetros inválidos para torus: 'minor_radius' ({minor_radius}) deve ser menor que 'major_radius' ({major_radius})."
            )
        sections = _ensure_strict_int(cleaned.get("sections", 32), "sections", MIN_SECTIONS, MAX_SECTIONS)
        cleaned.update({"major_radius": major_radius, "minor_radius": minor_radius, "sections": sections})

    return cleaned


class ObjectCategory(str, Enum):
    MECHANICAL = "mechanical"
    FURNITURE = "furniture"
    ARCHITECTURE = "architecture"
    ORGANIC = "organic"
    ARTISTIC = "artistic"
    CUSTOM = "custom"

class ObjectPurpose(str, Enum):
    VISUALIZATION = "visualization"
    GAMES = "games"
    ANIMATION = "animation"
    PRINT_3D = "print_3d"
    TECHNICAL = "technical"
    PROTOTYPE = "prototype"
    GENERAL = "general"

class GenerationStrategy(str, Enum):
    PROCEDURAL = "procedural"
    LOCAL_AI = "local_ai"
    EXTERNAL_API = "external_api"
    AUTO = "auto"

class Transformation(BaseModel):
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])  # Euler angles in degrees
    scale: List[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0])

    @model_validator(mode="before")
    @classmethod
    def normalize_translation_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "translation" in data and "position" not in data:
            data = dict(data)
            data["position"] = data["translation"]
        return data

    @property
    def translation(self) -> List[float]:
        return self.position

    @field_validator("position", "rotation")
    @classmethod
    def validate_vec3_finite(cls, v: List[Any], info) -> List[float]:
        if not isinstance(v, list) or len(v) != 3:
            raise ValueError(f"O vetor '{info.field_name}' deve conter exatamente 3 coordenadas [x, y, z].")
        return [_ensure_finite_number(coord, f"{info.field_name}[{i}]", allow_zero=True, allow_negative=True) for i, coord in enumerate(v)]

    @field_validator("scale")
    @classmethod
    def validate_scale_positive_finite(cls, v: List[Any]) -> List[float]:
        if not isinstance(v, list) or len(v) != 3:
            raise ValueError("O vetor 'scale' deve conter exatamente 3 fatores [sx, sy, sz].")
        return [_ensure_finite_number(coord, f"scale[{i}]", allow_zero=False, allow_negative=False) for i, coord in enumerate(v)]

class MaterialDef(BaseModel):
    color: str = "#888888"
    base_color: Optional[str] = None
    roughness: float = Field(0.5, ge=0.0, le=1.0, allow_inf_nan=False)
    metalness: float = Field(0.1, ge=0.0, le=1.0, allow_inf_nan=False)
    name: Optional[str] = "DefaultMaterial"

    @model_validator(mode="before")
    @classmethod
    def sync_color_and_base_color_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if data.get("base_color") and not data.get("color"):
                data["color"] = data["base_color"]
            elif data.get("color") and not data.get("base_color"):
                data["base_color"] = data["color"]
        return data

    @model_validator(mode="after")
    def sync_color_and_base_color_after(self) -> "MaterialDef":
        if not self.base_color:
            self.base_color = self.color
        return self

    @field_validator("roughness", "metalness", mode="before")
    @classmethod
    def reject_bool_in_material(cls, v: Any, info) -> float:
        return _ensure_finite_number(v, info.field_name, allow_zero=True, allow_negative=False)

class Component(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)  # e.g., cylinder, box, gear, table_top, table_leg
    parameters: Dict[str, Any] = Field(default_factory=dict)
    transformation: Transformation = Field(default_factory=Transformation)
    material: Optional[MaterialDef] = None
    children: List["Component"] = Field(default_factory=list)

    @field_validator("parameters")
    @classmethod
    def validate_component_parameters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("Os parâmetros do componente devem ser um dicionário.")
        cleaned: Dict[str, Any] = {}
        for k, val in v.items():
            if isinstance(val, bool):
                raise ValueError(f"Valor booleano não é permitido como parâmetro geométrico em '{k}'.")
            if isinstance(val, (int, float)):
                fval = _ensure_finite_number(
                    val,
                    k,
                    allow_zero=(k == "bore_radius"),
                    allow_negative=False
                )
                cleaned[k] = val if isinstance(val, int) else fval
            else:
                cleaned[k] = val
        return cleaned

class IntermediateObjectRepresentation(BaseModel):
    schema_version: str = "2.1.0"
    coordinate_system: str = "Y-up"
    geometry_schema_version: int = 2
    align_to_ground: bool = True
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    category: ObjectCategory = ObjectCategory.MECHANICAL
    purpose: ObjectPurpose = ObjectPurpose.GENERAL
    strategy: GenerationStrategy = GenerationStrategy.PROCEDURAL
    description: str = ""
    unit: str = "meters"
    components: List[Component] = Field(default_factory=list)
    user_inputs: Dict[str, Any] = Field(default_factory=dict)
    inferred_data: Dict[str, Any] = Field(default_factory=dict)
    assumed_defaults: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("coordinate_system")
    @classmethod
    def validate_coordinate_system(cls, v: str) -> str:
        if v not in SUPPORTED_COORDINATE_SYSTEMS:
            raise ValueError(f"Sistema de coordenadas inválido: '{v}'. Valores aceitos: {sorted(SUPPORTED_COORDINATE_SYSTEMS)}")
        return v

class ProceduralParams(BaseModel):
    shape_type: str = Field(..., description="Tipo de forma: cylinder, box, gear, table, sphere, cone, torus, wall")
    dimensions: Dict[str, float] = Field(default_factory=dict)
    subdivisions: Optional[int] = Field(32, ge=MIN_SECTIONS, le=MAX_SECTIONS)
    color: Optional[str] = "#3b82f6"

    @field_validator("shape_type")
    @classmethod
    def validate_shape_type(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("O campo 'shape_type' não pode ser vazio.")
        norm = v.strip().lower()
        if norm not in SUPPORTED_PROCEDURAL_SHAPES:
            raise ValueError(f"Tipo de forma não suportado: '{v}'.")
        return norm

    @field_validator("subdivisions", mode="before")
    @classmethod
    def validate_subdivisions_strict(cls, v: Any) -> Optional[int]:
        if v is None:
            return 32
        return _ensure_strict_int(v, "subdivisions", MIN_SECTIONS, MAX_SECTIONS)

    @field_validator("dimensions", mode="before")
    @classmethod
    def validate_dimensions_finite_positive(cls, v: Any) -> Dict[str, float]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("O campo 'dimensions' deve ser um dicionário de dimensões numéricas.")
        cleaned: Dict[str, float] = {}
        for k, val in v.items():
            allow_zero = (k == "bore_radius")
            fval = _ensure_finite_number(val, f"dimensions.{k}", allow_zero=allow_zero, allow_negative=False)
            if not allow_zero and (fval < MIN_DIMENSION or fval > MAX_DIMENSION):
                raise ValueError(
                    f"Dimensão '{k}' fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}] metros (recebido: {fval})."
                )
            elif allow_zero and fval > MAX_DIMENSION:
                raise ValueError(
                    f"Dimensão '{k}' excede o limite máximo de {MAX_DIMENSION} metros (recebido: {fval})."
                )
            cleaned[k] = fval
        return cleaned

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> "ProceduralParams":
        combined = dict(self.dimensions)
        if self.subdivisions is not None:
            combined.setdefault("subdivisions", self.subdivisions)
        validate_procedural_parameters_dict(self.shape_type, combined)
        return self

