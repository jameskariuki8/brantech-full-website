"""Re-exports the pipeline tasks so Celery autodiscovery finds them."""
from editorial.pipeline.tasks import (  # noqa: F401
    run_editorial_pipeline_task,
    release_stale_pipeline_runs_task,
    index_article_embeddings_task,
)
