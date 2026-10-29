from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

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
    created_at: datetime
    updated_at: datetime
    active_model_path: Optional[str] = None
