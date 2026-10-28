"""Database-backed GitHub reads and bounded background refresh coordination."""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db import transaction
from django.utils import timezone
from github import GithubException

from brandtechsolution.config import config
from .models import GitHubRefreshState, GitHubRepositoryCache, Project

logger = logging.getLogger(__name__)
CATALOGUE_TTL = timedelta(hours=1)
ACCOUNT_TTL = timedelta(hours=6)
CONTENT_TTL = timedelta(hours=6)
LEASE_TTL = timedelta(minutes=15)


def cache_scope():
    # A one-way account boundary, never the credential itself.
    return hashlib.sha256(f"{config.github_access_token or ''}:{config.github_username or ''}".encode()).hexdigest()


def repository_revision(repo):
    pushed = getattr(repo, 'pushed_at', None)
    branch = getattr(repo, 'default_branch', None)
    if not isinstance(pushed, datetime):
        return ''  # Unknown revisions are never treated as proof that content is unchanged.
    return f"{branch if isinstance(branch, str) else 'main'}:{pushed.isoformat()}"


def fresh(checked_at, ttl=CONTENT_TTL):
    return checked_at is not None and checked_at > timezone.now() - ttl


def snapshot_for(repo):
    repo_id = getattr(repo, 'id', None)
    if not isinstance(repo_id, int):
        return None
    full_name = getattr(repo, 'full_name', None)
    if not isinstance(full_name, str):
        full_name = ''
    row, _ = GitHubRepositoryCache.objects.get_or_create(
        scope=cache_scope(), github_repo_id=repo_id, defaults={'full_name': full_name},
    )
    return row


def save_metadata(repo, metadata):
    row = snapshot_for(repo)
    if row is None:
        return None
    payload = {k: v for k, v in metadata.items() if k not in ('project', 'is_synced', 'docs')}
    row.metadata = payload
    row.full_name = payload.get('full_name') or row.full_name
    row.fetched_at = timezone.now()
    row.available = True
    row.save(update_fields=['metadata', 'full_name', 'fetched_at', 'available'])
    return row


def store_document_audit(repo, result, row=None):
    row = row or snapshot_for(repo)
    result = dict(result)
    cached_snapshot = result.pop('_cached_snapshot', False)
    bodies = result.pop('_contents', {})
    file_shas = result.pop('_file_shas', {})
    if row is not None and not cached_snapshot and result.get('status') in ('ok', 'problems'):
        row.documents = result
        row.document_contents = bodies
        row.document_shas = file_shas
        row.documents_revision = repository_revision(repo)
        row.documents_checked_at = timezone.now()
        row.save(update_fields=['documents', 'document_contents', 'document_shas', 'documents_revision', 'documents_checked_at'])
    return {k: v for k, v in result.items() if not k.startswith('_')}


@transaction.atomic
def cached_document_audit(repo, row=None):
    """One persisted audit and document body per content revision, shared by importers."""
    from .github_service import GitHubService

    row = row or snapshot_for(repo)
    if row is not None:
        row = GitHubRepositoryCache.objects.select_for_update().get(pk=row.pk)
    revision = repository_revision(repo)
    if (row is not None and revision and row.documents_revision == revision
            and fresh(row.documents_checked_at) and row.documents.get('status') in ('ok', 'problems')):
        return row.documents
    previous = {"shas": row.document_shas, "contents": row.document_contents} if row else None
    result = GitHubService.audit_repo_docs(repo, previous=previous, force=bool(row is None or not row.documents_checked_at))
    return store_document_audit(repo, result, row)


def roadmap_from_snapshot(row):
    if row is None:
        return None
    path = (row.documents.get('present') or {}).get('ROADMAP.md')
    return row.document_contents.get(path) if path else None


def refresh_content(service, repo, force=False):
    """Persist positive and negative README/commit results. No per-commit stats calls."""
    row = snapshot_for(repo)
    revision = repository_revision(repo)
    if (not force and row is not None and revision and row.content_revision == revision
            and fresh(row.content_checked_at)):
        return row
    readme_path = (row.documents.get('present') or {}).get('README.md') if row else None
    document_sha = row.document_shas.get(readme_path) if row and readme_path else None
    readme_sha = ''
    if (row and row.content_checked_at and document_sha
            and row.readme_sha == document_sha and row.readme_content is not None):
        readme, readme_sha = row.readme_content, document_sha
    elif row and row.documents_checked_at and not readme_path and row.documents.get('status') in ('ok', 'problems'):
        readme = None  # The persisted root listing already proves absence.
    else:
        try:
            readme_file = repo.get_readme()
            readme = readme_file.decoded_content.decode('utf-8')
            readme_sha = readme_file.sha if isinstance(getattr(readme_file, 'sha', None), str) else ''
        except GithubException as exc:
            if exc.status != 404:
                raise
            readme = None
    try:
        paginated = repo.get_commits()
        count = paginated.totalCount
        commits = service._fetch_commits_from_github(repo, count=10, paginated=paginated)
    except GithubException as exc:
        if exc.status != 409:
            raise
        count, commits = 0, []
    if row is None:
        return None
    row.readme_content = readme
    row.readme_sha = readme_sha
    row.recent_commits = commits
    row.commit_count = count
    row.content_revision = revision
    row.content_checked_at = timezone.now()
    row.save(update_fields=['readme_content', 'readme_sha', 'recent_commits', 'commit_count', 'content_revision', 'content_checked_at'])
    return row


def state_for(key):
    return GitHubRefreshState.objects.get_or_create(scope=cache_scope(), key=key)[0]


def blocked_until():
    state = GitHubRefreshState.objects.filter(scope=cache_scope(), key='rate-limit').first()
    return state.retry_after if state and state.retry_after and state.retry_after > timezone.now() else None


def record_failure(key, exc, full_name=None):
    now = timezone.now()
    retry = now + timedelta(minutes=5)
    rate_limited = False
    if isinstance(exc, GithubException):
        headers = {str(k).lower(): v for k, v in (exc.headers or {}).items()}
        rate_limited = exc.status == 429 or (exc.status == 403 and (
            str(headers.get('x-ratelimit-remaining')) == '0' or headers.get('retry-after')
            or (isinstance(exc.data, dict) and 'rate limit' in str(exc.data.get('message', '')).lower())))
        if rate_limited:
            candidates = [now + timedelta(minutes=10)]
            try:
                if headers.get('retry-after'):
                    candidates.append(now + timedelta(seconds=int(headers['retry-after'])))
                if headers.get('x-ratelimit-reset'):
                    candidates.append(datetime.fromtimestamp(int(headers['x-ratelimit-reset']), datetime_timezone.utc))
            except (ValueError, TypeError, OverflowError):
                logger.warning('GitHub returned an invalid retry header')
            retry = max(candidates)
    if (full_name and isinstance(exc, GithubException) and exc.status in (403, 404)
            and not rate_limited):
        GitHubRepositoryCache.objects.filter(scope=cache_scope(), full_name__iexact=full_name).update(available=False)
    message = 'GitHub rate limit reached; saved data is available while refresh waits.' if rate_limited else 'GitHub refresh failed; saved data has been kept and a retry is scheduled.'
    state_for(key)
    GitHubRefreshState.objects.filter(scope=cache_scope(), key=key).update(last_error=message, retry_after=retry)
    if rate_limited:
        state, _ = GitHubRefreshState.objects.get_or_create(scope=cache_scope(), key='rate-limit')
        state.retry_after = retry
        state.last_error = message
        state.save(update_fields=['retry_after', 'last_error'])
    return message


def refresh_status(key, ttl=CATALOGUE_TTL):
    state = state_for(key)
    now = timezone.now()
    blocked = blocked_until()
    error = state.last_error or ('GitHub rate limit reached; saved data is available while refresh waits.' if blocked else '')
    return {'updated_at': state.refreshed_at, 'stale': not fresh(state.refreshed_at, ttl),
            'refreshing': bool(state.lease_until and state.lease_until > now),
            'error': error, 'retry_after': blocked or state.retry_after}


def enqueue_refresh_job(scope, kind, repo_id, token):
    # send_task deliberately bypasses task_always_eager: a GET must never
    # execute network refresh code inline, even in a development environment.
    from brandtechsolution.celery import app
    with app.connection_for_write(connect_timeout=1) as connection:
        app.send_task('brand.refresh_github_cache', args=(scope, kind, repo_id, token),
                      connection=connection, retry=False)


def request_refresh(kind='catalogue', repo_id=None, force=False):
    """Queue at most one refresh per key across web workers; respect durable backoff."""
    key = f'repository:{repo_id}' if kind == 'repository' else kind
    scope = cache_scope()
    state_for(key)
    now = timezone.now()
    if blocked_until():
        return False
    with transaction.atomic():
        state = GitHubRefreshState.objects.select_for_update().get(scope=scope, key=key)
        if ((state.lease_until and state.lease_until > now)
                or (state.retry_after and state.retry_after > now)):
            return False
        ttl = ACCOUNT_TTL if kind == 'account' else CATALOGUE_TTL
        if not force and fresh(state.refreshed_at, ttl):
            return False
        token = uuid.uuid4().hex
        state.lease_token, state.lease_until, state.running = token, now + LEASE_TTL, False
        state.save(update_fields=['lease_token', 'lease_until', 'running'])
    try:
        enqueue_refresh_job(scope, kind, repo_id, token)
    except Exception:
        logger.exception('Could not queue GitHub refresh')
        GitHubRefreshState.objects.filter(scope=scope, key=key, lease_token=token).update(
            lease_until=None, running=False, retry_after=now + timedelta(minutes=1),
            last_error='Background refresh could not be queued; saved data is still available.')
    return True


def run_refresh(scope, kind, repo_id, token):
    """Execute an owned lease. Old-credential jobs cannot populate a new account's cache."""
    from .github_service import GitHubService

    key = f'repository:{repo_id}' if kind == 'repository' else kind
    if scope != cache_scope():
        GitHubRefreshState.objects.filter(scope=scope, key=key, lease_token=token).update(lease_until=None, running=False)
        return {'skipped': 'credentials changed'}
    with transaction.atomic():
        state = GitHubRefreshState.objects.select_for_update().get(scope=scope, key=key)
        if state.lease_token != token or state.running or state.lease_until is None:
            return {'skipped': 'duplicate refresh'}
        state.running = True
        state.save(update_fields=['running'])
    try:
        if blocked_until():
            return {'skipped': 'rate limit backoff'}
        service = GitHubService()
        if kind == 'catalogue':
            service.get_user_repositories()
            tracked = list(Project.objects.filter(is_github_synced=True, github_repo_id__isnull=False).values_list('github_repo_id', flat=True))
            if tracked:
                result = service.sync_repositories(tracked)
                if not result.get('success') or result.get('error_count'):
                    raise RuntimeError('Some tracked projects could not refresh')
        elif kind == 'account':
            value = service.get_account_info()
            GitHubRefreshState.objects.filter(scope=scope, key=key, lease_token=token).update(value=value)
        elif kind == 'repository':
            repo = service.client.get_repo(repo_id)
            previous = snapshot_for(repo)
            role = previous.metadata.get('role', 'collaborator') if previous else 'collaborator'
            member = previous.metadata.get('staff_member') if previous else None
            row = save_metadata(repo, service._format_repo_dict(repo, role=role, staff_member=member, synced_projects={}))
            audit = cached_document_audit(repo, row)
            if audit.get('status') == 'unknown':
                raise RuntimeError('Document audit unavailable')
            row = refresh_content(service, repo)
            if row:
                mirror_project(row)
        else:
            raise ValueError('Unknown GitHub refresh kind')
        GitHubRefreshState.objects.filter(scope=scope, key=key, lease_token=token).update(
            refreshed_at=timezone.now(), last_error='', retry_after=None)
        return {'status': 'ok'}
    except Exception as exc:
        message = record_failure(key, exc)
        if repo_id is not None and isinstance(exc, GithubException) and exc.status in (403, 404) and not blocked_until():
            headers = {str(k).lower(): str(v) for k, v in (exc.headers or {}).items()}
            if exc.status == 404 or (headers.get('x-ratelimit-remaining') != '0' and not headers.get('retry-after')):
                row, _ = GitHubRepositoryCache.objects.get_or_create(scope=scope, github_repo_id=repo_id, defaults={'full_name': ''})
                row.available = False
                row.save(update_fields=['available'])
        logger.warning('GitHub %s refresh failed (%s)', key, type(exc).__name__)
        return {'error': message}
    finally:
        GitHubRefreshState.objects.filter(scope=scope, key=key, lease_token=token).update(lease_until=None, running=False)


def mirror_project(row):
    if row.content_checked_at:
        Project.objects.filter(github_repo_id=row.github_repo_id, is_github_synced=True).update(
            readme_content=row.readme_content, cached_commits=row.recent_commits,
            commit_count=row.commit_count or 0, last_synced_at=timezone.now())


def cached_repositories():
    from .github_service import project_payload

    request_refresh('catalogue')
    projects = {p.github_repo_id: p for p in Project.objects.filter(github_repo_id__isnull=False)}
    rows = GitHubRepositoryCache.objects.filter(scope=cache_scope(), available=True)
    results = []
    for row in rows:
        entry = dict(row.metadata)
        if not entry:
            continue
        project = projects.get(row.github_repo_id)
        entry.update({'id': row.github_repo_id, 'docs': row.documents or {'status': 'unknown', 'problems': []},
                      'is_synced': project is not None, 'project': project_payload(project)})
        results.append(entry)
    return {'results': sorted(results, key=lambda x: (not x['is_synced'], x['name'].lower())),
            'cache': refresh_status('catalogue')}


def cached_account():
    request_refresh('account')
    state = state_for('account')
    return {**state.value, 'pending': not bool(state.value), 'cache': refresh_status('account', ACCOUNT_TTL)}


def cached_readme(repo_id):
    row = GitHubRepositoryCache.objects.filter(scope=cache_scope(), github_repo_id=repo_id).first()
    if row is not None and not row.available:
        return {'success': False, 'readme': '', 'cached': True, 'pending': False, 'missing': True}
    if row is not None and row.content_checked_at:
        if not fresh(row.content_checked_at):
            request_refresh('repository', repo_id, force=True)
        return {'success': row.readme_content is not None, 'readme': row.readme_content or '',
                'cached': True, 'pending': False, 'missing': row.readme_content is None}
    request_refresh('repository', repo_id, force=bool(row is not None))
    return {'success': False, 'readme': '', 'cached': True, 'pending': True}


def cached_commits(project, request_update=False):
    # An empty list is a known result, never a reason to call GitHub from a GET.
    row = GitHubRepositoryCache.objects.filter(scope=cache_scope(), github_repo_id=project.github_repo_id, available=True).first()
    if request_update or row is None or not fresh(row.content_checked_at):
        request_refresh('repository', project.github_repo_id, force=request_update or bool(row and not row.content_checked_at))
    commits = row.recent_commits if row and row.recent_commits is not None else project.cached_commits
    return {'success': True, 'commits': commits or [], 'cached': True,
            'pending': commits is None, 'cache': refresh_status(f'repository:{project.github_repo_id}')}
