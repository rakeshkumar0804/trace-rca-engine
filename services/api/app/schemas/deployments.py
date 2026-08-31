from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field


class DeploymentStatus(str, Enum):
    """Lifecycle state of a service deployment rollout."""
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class Deployment(BaseModel):
    """Production or staging release rollout of a specific service version and commit."""
    deployment_id: UUID
    service: str
    version: str
    commit_sha: str
    started_at: datetime
    completed_at: datetime | None = None
    environment: str
    status: DeploymentStatus


class GitCommit(BaseModel):
    """Version control change record containing metadata, affected files, and code diff summary."""
    commit_sha: str
    author: str
    timestamp: datetime
    repository: str
    files_changed: list[str]
    diff_summary: str
    symbols_changed: list[str] = Field(default_factory=list)
