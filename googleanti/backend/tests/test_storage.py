import pytest
import os
from backend.app.storage.database import init_db, SessionLocal, ProjectModel, JobModel

def test_database_init_and_crud():
    init_db()
    db = SessionLocal()
    try:
        # Create project
        proj = ProjectModel(
            id="test-proj-01",
            name="Projeto Teste",
            description="Criado para teste de banco",
            category="mechanical",
            purpose="technical"
        )
        db.add(proj)
        db.commit()

        # Query project
        queried = db.query(ProjectModel).filter(ProjectModel.id == "test-proj-01").first()
        assert queried is not None
        assert queried.name == "Projeto Teste"

        # Create Job
        job = JobModel(
            id="test-job-01",
            project_id=proj.id,
            operation_type="procedural_generation",
            status="Pendente"
        )
        db.add(job)
        db.commit()

        queried_job = db.query(JobModel).filter(JobModel.id == "test-job-01").first()
        assert queried_job is not None
        assert queried_job.status == "Pendente"

        # Cleanup
        db.delete(queried_job)
        db.delete(queried)
        db.commit()
    finally:
        db.close()
