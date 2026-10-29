import pytest
import asyncio
from backend.app.schemas.jobs import JobStatus
from backend.app.jobs.orchestrator import JobOrchestrator
from backend.app.storage.database import init_db, SessionLocal, ProjectModel, JobModel

def test_job_orchestrator_transitions():
    # Validações estritas de transição
    with pytest.raises(ValueError):
        JobOrchestrator.validate_transition(JobStatus.PENDING, JobStatus.COMPLETED)

    with pytest.raises(ValueError):
        JobOrchestrator.validate_transition(JobStatus.COMPLETED, JobStatus.RUNNING)

    # Transições legais
    JobOrchestrator.validate_transition(JobStatus.PENDING, JobStatus.PREPARING)
    JobOrchestrator.validate_transition(JobStatus.PREPARING, JobStatus.RUNNING)
    JobOrchestrator.validate_transition(JobStatus.RUNNING, JobStatus.COMPLETED)

@pytest.mark.anyio
async def test_job_execution_lifecycle():
    init_db()
    db = SessionLocal()
    proj_id = "test-orch-proj"
    try:
        proj = ProjectModel(id=proj_id, name="Orchestrator Test")
        db.add(proj)
        db.commit()

        job = JobOrchestrator.create_job(
            db,
            project_id=proj_id,
            operation_type="procedural_generation",
            params={"shape_type": "cylinder", "radius": 0.5, "height": 1.5}
        )
        assert job.status == JobStatus.PENDING.value

        await JobOrchestrator.run_procedural_job_async(job.id, proj_id, {"shape_type": "cylinder", "radius": 0.5, "height": 1.5})

        db.refresh(job)
        assert job.status == JobStatus.COMPLETED.value
        assert job.progress == 1.0

        db.refresh(proj)
        assert proj.active_model_path is not None
        assert "cylinder" in proj.active_model_path
    finally:
        db.query(JobModel).filter(JobModel.project_id == proj_id).delete()
        db.query(ProjectModel).filter(ProjectModel.id == proj_id).delete()
        db.commit()
        db.close()
