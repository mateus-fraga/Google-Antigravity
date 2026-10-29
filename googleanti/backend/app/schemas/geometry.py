from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

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

class MaterialDef(BaseModel):
    color: str = "#888888"
    roughness: float = 0.5
    metalness: float = 0.1
    name: Optional[str] = "DefaultMaterial"

class Component(BaseModel):
    id: str
    name: str
    type: str  # e.g., cylinder, box, gear, table_top, table_leg
    parameters: Dict[str, Any] = Field(default_factory=dict)
    transformation: Transformation = Field(default_factory=Transformation)
    material: Optional[MaterialDef] = None
    children: List["Component"] = Field(default_factory=list)

class IntermediateObjectRepresentation(BaseModel):
    schema_version: str = "2.1.0"
    id: str
    name: str
    category: ObjectCategory = ObjectCategory.MECHANICAL
    purpose: ObjectPurpose = ObjectPurpose.GENERAL
    strategy: GenerationStrategy = GenerationStrategy.PROCEDURAL
    description: str = ""
    unit: str = "meters"
    components: List[Component] = Field(default_factory=list)
    user_inputs: Dict[str, Any] = Field(default_factory=dict)
    inferred_data: Dict[str, Any] = Field(default_factory=dict)
    assumed_defaults: Dict[str, Any] = Field(default_factory=dict)
    
class ProceduralParams(BaseModel):
    shape_type: str = Field(..., description="Tipo de forma: cylinder, box, gear, table, wall")
    dimensions: Dict[str, float] = Field(default_factory=dict)
    subdivisions: Optional[int] = Field(32, ge=4, le=128)
    color: Optional[str] = "#3b82f6"
