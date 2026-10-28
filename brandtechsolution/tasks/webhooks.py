"""GitHub push webhook for the task board.

Optional: the Beat poll (tasks.github.poll_all) finds the same commits a few
minutes later. The webhook only makes it immediate. Configure it on GitHub
with content type application/json, the "push" event, and the secret in
GITHUB_WEBHOOK_SECRET.
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .github import apply_commits, commits_from_push, push_touches_documents
from .models import Repository

logger = logging.getLogger(__name__)


def _signed(request, secret):
    sent = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, expected)


@csrf_exempt
@require_POST
def github_webhook(request):
    secret = getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or ""
    if not secret:
        return JsonResponse({"error": "The GitHub webhook is not configured."}, status=503)
    if not _signed(request, secret):
        return JsonResponse({"error": "Bad signature."}, status=403)

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return JsonResponse({"ok": True, "pong": True})
    if event != "push":
        return JsonResponse({"ok": True, "ignored": event})

    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Body is not JSON."}, status=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("repository"), dict):
        return JsonResponse({"error": "Expected a push object with a repository."}, status=400)
    if not isinstance(payload.get("commits", []), list) or any(
        not isinstance(c, dict) or not isinstance(c.get("message", ""), str)
        or not isinstance(c.get("id"), str) or len(c["id"]) != 40
        or not isinstance(c.get("author", {}), dict)
        or not isinstance(c.get("timestamp", ""), str)
        or not isinstance(c.get("url", ""), str)
        or any(not isinstance(c.get(key, []), list) for key in ("added", "modified", "removed"))
        for c in payload.get("commits", [])
    ):
        return JsonResponse({"error": "Invalid commits."}, status=400)

    full_name = (payload.get("repository") or {}).get("full_name", "")
    repository = Repository.objects.filter(full_name__iexact=full_name).first()
    if repository is None:
        return JsonResponse({"ok": True, "ignored": "repository is not linked"})

    default = (payload.get("repository") or {}).get("default_branch") or repository.default_branch
    on_default = payload.get("ref") == f"refs/heads/{default}"
    if on_default:
        # Invalidate only this repository. Signed payload metadata may arrive before
        # GitHub's repository listing reflects the new push timestamp.
        from brand.github_cache import cache_scope, request_refresh
        from brand.models import GitHubRepositoryCache
        snapshots = GitHubRepositoryCache.objects.filter(scope=cache_scope(), full_name__iexact=full_name)
        ids = list(snapshots.values_list("github_repo_id", flat=True))
        snapshots.update(documents_checked_at=None, content_checked_at=None)
        for repo_id in ids:
            request_refresh("repository", repo_id, force=True)
        Repository.objects.filter(pk=repository.pk).update(last_processed_revision="")

    result = apply_commits(repository, commits_from_push(payload), on_default_branch=on_default)

    if on_default and push_touches_documents(payload):
        from .tasks import poll_repository_task

        poll_repository_task.delay(repository.pk)
        result["documentation"] = "queued"
        if repository.track_roadmap:
            result["roadmap"] = "queued"
    return JsonResponse({"ok": True, **result})
