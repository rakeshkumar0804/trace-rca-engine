from datetime import datetime, timedelta
from random import Random
from uuid import UUID

from app.schemas.deployments import Deployment, DeploymentStatus, GitCommit
from .commits_generator import generate_healthy_commits


def generate_healthy_deployments(
    commits: list[GitCommit],
    rng: Random,
) -> list[Deployment]:
    """Generates successful deployment records corresponding to a set of git commits."""
    deployments: list[Deployment] = []
    
    for commit in commits:
        service_name = commit.repository.split("/")[-1]
        dep_id = UUID(int=rng.getrandbits(128))
        
        # Deployment started shortly after commit was merged
        started_at = commit.timestamp + timedelta(minutes=rng.uniform(2.0, 10.0))
        # Rollout duration of 2 to 6 minutes
        rollout_duration = timedelta(minutes=rng.uniform(2.0, 6.0))
        completed_at = started_at + rollout_duration
        
        major = rng.randint(1, 2)
        minor = rng.randint(10, 25)
        patch = rng.randint(0, 9)
        version = f"v{major}.{minor}.{patch}"
        
        deployment = Deployment(
            deployment_id=dep_id,
            service=service_name,
            version=version,
            commit_sha=commit.commit_sha,
            started_at=started_at,
            completed_at=completed_at,
            environment="production",
            status=DeploymentStatus.SUCCESS,
        )
        deployments.append(deployment)
        
    return deployments


def generate_healthy_deployment_history(
    services: list[str],
    window_start: datetime,
    rng: Random,
    count: int = 3,
) -> tuple[list[Deployment], list[GitCommit]]:
    """Generates paired healthy commits and deployments that succeeded prior to the investigation window."""
    commits = generate_healthy_commits(services, window_start, rng, count=count)
    deployments = generate_healthy_deployments(commits, rng)
    return deployments, commits
