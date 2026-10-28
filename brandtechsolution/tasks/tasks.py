"""Celery tasks for the task board."""
from celery import shared_task


@shared_task(
    name="tasks.poll_repositories",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    max_retries=3,
)
def poll_repositories_task():
    """Read new commits and roadmaps from every linked repository.

    Safe to repeat: commits are stored once per task, and roadmap items find
    their existing tasks by key.
    """
    from .github import poll_all

    return poll_all()


@shared_task(name="tasks.poll_repository")
def poll_repository_task(repository_id):
    from .github import poll_repository
    from .models import Repository

    repository = Repository.objects.filter(pk=repository_id).first()
    if repository is None:
        return None
    try:
        return poll_repository(repository)
    except Exception as exc:
        from brand.github_cache import record_failure
        record_failure(f"task-repository:{repository.pk}", exc, full_name=repository.full_name)
        Repository.objects.filter(pk=repository.pk).update(last_error="GitHub refresh failed; the next scheduled check will retry.")
        raise
