"""The AI newsroom dashboard.

Every view here is gated on a panel capability. They arrived unauthenticated
and CSRF-exempt, which meant anyone on the internet could POST to
/editorial/api/articles/<id>/approve/ and publish to the live site, or to
/editorial/api/run-pipeline/ and spend the project's model quota. The module
already imported staff_member_required without ever applying it, so the intent
was there.

capability_required rather than staff_member_required: this project gates the
panel on named capabilities (see staff/capabilities.py), and
staff_member_required would admit every is_staff account regardless of role.
Reading the newsroom needs manage_blog; anything that decides what reaches the
public site needs publish_blog, which is the capability that already governs
draft -> published for ordinary posts. Approving here IS publishing, so it
must not be reachable with a weaker permission than the blog editor's.
"""

from editorial.views.dashboard import dashboard_view
from editorial.views.pipeline import trigger_pipeline_api, pipeline_run_status_api, _run_payload
from editorial.views.articles import (
    article_detail_api,
    approve_article_api,
    reject_article_api,
    export_docx_view,
)
from editorial.views.search import semantic_search_api

__all__ = [
    'dashboard_view',
    'trigger_pipeline_api',
    'pipeline_run_status_api',
    'article_detail_api',
    'approve_article_api',
    'reject_article_api',
    'export_docx_view',
    'semantic_search_api',
]
