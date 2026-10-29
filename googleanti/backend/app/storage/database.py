import json
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, Float, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.app.config import settings

Base = declarative_base()

def get_utc_now():
    return datetime.now(timezone.utc)

class ProjectModel(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    category = Column(String, default="mechanical")
    purpose = Column(String, default="general")
    strategy = Column(String, default="procedural")
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)
    active_model_path = Column(String, nullable=True)
    parameters_json = Column(Text, default="{}")

class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    operation_type = Column(String, nullable=False)
    status = Column(String, default="Pendente", nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    progress = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    params_json = Column(Text, default="{}")
    result_files_json = Column(Text, default="[]")
    metadata_json = Column(Text, default="{}")

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
