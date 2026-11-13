from enum import Enum
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator
from backend.app.schemas.geometry import (
    validate_procedural_parameters_dict,
    _ensure_finite_number,
    MIN_DIMENSION,
    MAX_DIMENSION,
)
from backend.app.procedural.text_to_3d import TextTo3DGenerator
from backend.app.procedural.image_to_3d import ALLOWED_IMAGE_EXTENSIONS, ImageTo3DGenerator

SUPPORTED_OPERATION_TYPES = {"procedural_generation", "text_to_3d", "image_to_3d"}

class JobStatus(str, Enum):
    PENDING = "Pendente"
    PREPARING = "Preparando"
    RUNNING = "Em Execução"
    COMPLETED = "Concluída"
    FAILED = "Falhou"
    CANCELLED = "Cancelada"

class JobCreate(BaseModel):
    project_id: str
    operation_type: str = "procedural_generation"
    params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_parameters_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "parameters" in data and not data.get("params"):
                data = dict(data)
                data["params"] = data["parameters"]
        return data

    @model_validator(mode="after")
    def validate_job_parameters(self) -> "JobCreate":
        if not isinstance(self.params, dict):
            raise ValueError("O campo 'params' deve ser um dicionário.")
        if self.operation_type not in SUPPORTED_OPERATION_TYPES:
            raise ValueError(
                f"Tipo de operação não suportado: '{self.operation_type}'. "
                f"Operações válidas: {sorted(SUPPORTED_OPERATION_TYPES)}"
            )
        if self.operation_type == "procedural_generation":
            shape_type = self.params.get("shape_type", "box")
            # Se o payload vier aninhado com 'dimensions', mesclar para validação unificada
            flat_params = dict(self.params)
            if isinstance(flat_params.get("dimensions"), dict):
                for k, v in flat_params["dimensions"].items():
                    flat_params.setdefault(k, v)
            validated = validate_procedural_parameters_dict(shape_type, flat_params)
            self.params = validated
        elif self.operation_type == "text_to_3d":
            prompt_raw = self.params.get("prompt")
            ir, semantic_meta = TextTo3DGenerator.parse_prompt_to_ir(prompt_raw)
            cleaned_params = dict(self.params)
            cleaned_params["prompt"] = semantic_meta["prompt"]
            cleaned_params["parsed_intent"] = semantic_meta["parsed_intent"]
            cleaned_params["detected_components_count"] = semantic_meta["detected_components_count"]
            cleaned_params["extracted_dimensions"] = semantic_meta["extracted_dimensions"]
            self.params = cleaned_params
        elif self.operation_type == "image_to_3d":
            cleaned_params = dict(self.params)
            ref_img = cleaned_params.get("reference_image_filename") or cleaned_params.get("image_filename")
            if not isinstance(ref_img, str) or not ref_img.strip():
                raise ValueError("O campo 'reference_image_filename' é obrigatório para geração Image-to-3D.")
            ref_img = ref_img.strip()
            if ".." in ref_img or "/" in ref_img or "\\" in ref_img or "\x00" in ref_img:
                raise ValueError("Nome de imagem de referência inválido (caminhos relativos ou barras não são permitidos).")
            ext = Path(ref_img).suffix.lower()
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                raise ValueError(
                    f"Extensão de imagem inválida '{ext}'. Formatos permitidos: {sorted(ALLOWED_IMAGE_EXTENSIONS.keys())}"
                )
            mode = str(cleaned_params.get("mode", "silhouette")).strip().lower()
            if mode not in ImageTo3DGenerator.SUPPORTED_MODES:
                raise ValueError(
                    f"Modo Image-to-3D inválido: '{mode}'. Modos suportados: {sorted(ImageTo3DGenerator.SUPPORTED_MODES)}"
                )
            cleaned_params["reference_image_filename"] = ref_img
            cleaned_params["mode"] = mode
            for num_field in ("thickness", "base_thickness", "relief_depth"):
                if num_field in cleaned_params and cleaned_params[num_field] is not None:
                    fval = _ensure_finite_number(cleaned_params[num_field], num_field)
                    if fval < MIN_DIMENSION or fval > MAX_DIMENSION:
                        raise ValueError(
                            f"O parâmetro '{num_field}' ({fval}) está fora dos limites seguros [{MIN_DIMENSION}, {MAX_DIMENSION}]m."
                        )
                    cleaned_params[num_field] = fval
            if "resolution_scale" in cleaned_params and cleaned_params["resolution_scale"] is not None:
                rscale = _ensure_finite_number(cleaned_params["resolution_scale"], "resolution_scale")
                if rscale < 0.05 or rscale > 4.0:
                    raise ValueError("O parâmetro 'resolution_scale' deve estar entre 0.05 e 4.0.")
                cleaned_params["resolution_scale"] = rscale
            self.params = cleaned_params
        return self

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    operation_type: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[float] = None
    error_message: Optional[str] = None
    result_files: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    category: str = "mechanical"
    purpose: str = "general"
    strategy: str = "procedural"

class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = ""
    category: str
    purpose: str
    strategy: str
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    active_model_path: Optional[str] = None
    coordinate_system: str = "Y-up"
    geometry_schema_version: int = 2

    @model_validator(mode="before")
    @classmethod
    def extract_coordinate_metadata(cls, data: Any) -> Any:
        """
        GEO-001 (Task 3.3): Inspeciona o projeto carregado do banco SQLite (ou dict)
        para determinar se seu modelo ativo foi gerado sob a convenção nativa `Y-up`
        (`geometry_schema_version >= 2`) ou se é um modelo legado `legacy_z_up`
        (gerado anteriormente sem metadado de orientação Y-up), prevenindo dupla conversão.
        """
        if hasattr(data, "__dict__") and not isinstance(data, dict):
            params_raw = getattr(data, "parameters_json", None)
            active_model = getattr(data, "active_model_path", None)
            parsed_params = {}
            if isinstance(params_raw, str) and params_raw.strip():
                try:
                    parsed_params = json.loads(params_raw)
                except Exception:
                    parsed_params = {}
            if not isinstance(parsed_params, dict):
                parsed_params = {}

            coord_sys = parsed_params.get("coordinate_system")
            schema_ver = parsed_params.get("geometry_schema_version")
            if not coord_sys:
                # Se já possui modelo ativo gerado no passado sem flag coordinate_system -> legado Z-up
                if active_model:
                    coord_sys = "legacy_z_up"
                    schema_ver = 1
                else:
                    coord_sys = "Y-up"
                    schema_ver = 2
            return {
                "id": getattr(data, "id"),
                "name": getattr(data, "name"),
                "description": getattr(data, "description", ""),
                "category": getattr(data, "category", "mechanical"),
                "purpose": getattr(data, "purpose", "general"),
                "strategy": getattr(data, "strategy", "procedural"),
                "status": getattr(data, "status", "active"),
                "created_at": getattr(data, "created_at"),
                "updated_at": getattr(data, "updated_at"),
                "active_model_path": active_model,
                "coordinate_system": coord_sys,
                "geometry_schema_version": int(schema_ver) if isinstance(schema_ver, int) else (1 if coord_sys == "legacy_z_up" else 2),
            }
        return data

