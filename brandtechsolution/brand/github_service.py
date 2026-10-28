import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from github import Github
from github.GithubException import GithubException
from django.core.cache import cache
from django.utils import timezone
from brandtechsolution.config import config
from brand.models import Project
from brand import repo_docs

logger = logging.getLogger(__name__)

# How long a repository's document check is reused. The key also carries the
# repo's last push time, so a push invalidates it at once; this only bounds
# how stale a check can be when the push time did not change.
DOC_AUDIT_TTL_SECONDS = 6 * 3600


def _short(description):
    """Fit a repository description into Project.short_description (500)."""
    if description and len(description) > 500:
        return description[:497] + '...'
    return description


def _clean_github_username(username: str) -> str:
    """Normalize GitHub username by stripping whitespace and leading '@'."""
    if not username:
        return ""
    return username.strip().lstrip("@")


def _get_staff_github_mapping() -> Dict[str, Dict[str, Any]]:
    """Return mapping of lowercased github_username -> staff metadata."""
    from staff.models import StaffProfile

    mapping = {}
    try:
        profiles = StaffProfile.objects.exclude(github_username="").select_related("user")
        for p in profiles:
            cleaned = _clean_github_username(p.github_username)
            if cleaned:
                full_name = p.user.get_full_name() or p.user.username
                mapping[cleaned.lower()] = {
                    "username": cleaned,
                    "staff_name": full_name,
                    "staff_id": p.user_id,
                    "primary_role": getattr(p, "primary_role", "") or "",
                }
    except Exception as e:
        logger.warning(f"Failed to load staff GitHub mapping: {e}")
    return mapping


def _has_permission_to_repo(repo) -> bool:
    """
    Check if the authenticated GitHub token has permissions to access or modify this repository.
    Returns True if:
      - We have push (write), admin, or maintain permissions, OR
      - The repo is private and we have pull access.
    """
    perms = getattr(repo, "permissions", None)
    if not perms:
        return False
    if (
        getattr(perms, "push", False)
        or getattr(perms, "admin", False)
        or getattr(perms, "maintain", False)
    ):
        return True
    if getattr(repo, "private", False) and getattr(perms, "pull", False):
        return True
    return False


def project_payload(project):
    if project is None:
        return None
    return {
        'id': project.id, 'title': project.title,
        'short_description': project.short_description or '', 'description': project.description or '',
        'commit_count': project.commit_count or 0,
        'last_synced_at': project.last_synced_at.isoformat() if project.last_synced_at else None,
        'has_readme': bool(project.readme_content), 'readme_content': project.readme_content or '',
        'cached_commits': project.cached_commits or [], 'project_url': project.project_url or '',
        'featured': project.featured,
    }


class GitHubService:
    def __init__(self):
        """Initialize GitHub client using the configured Personal Access Token."""
        if not config.github_access_token:
            raise ValueError("GITHUB_ACCESS_TOKEN is not configured in environment variables.")
        self.client = Github(config.github_access_token)
        self.username = config.github_username

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_commits_from_github(self, repo, count: int = 10, paginated=None) -> List[Dict]:
        """
        Internal helper: fetches commit metadata from a PyGithub repo object.
        This is the ONLY place that hits the GitHub API for commit data.
        Called exclusively during sync operations — never per user request.
        """
        commits_data = []
        try:
            source = paginated if paginated is not None else repo.get_commits()
            for commit in source[:count]:
                c = commit.commit
                commits_data.append({
                    'sha': commit.sha[:7],
                    'message': c.message.split('\n')[0][:120],
                    'author': c.author.name if c.author else 'Unknown',
                    'date': c.author.date.isoformat() if c.author else None,
                    # Commit-list responses omit stats. Reading commit.stats
                    # would issue an additional API request for every row.
                })
        except GithubException:
            # Do not persist a transient error as an empty, successful result.
            raise
        return commits_data

    def _format_repo_dict(
        self,
        repo,
        role: str,
        staff_member: Optional[Dict[str, Any]],
        synced_projects: Dict[int, Project],
        docs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Helper to format a GitHub repository into standard API dictionary format."""
        project = synced_projects.get(repo.id)
        is_synced = project is not None

        project_data = project_payload(project)

        language = repo.language if isinstance(getattr(repo, 'language', None), str) else None
        stars = repo.stargazers_count if isinstance(getattr(repo, 'stargazers_count', None), int) else 0
        forks = repo.forks_count if isinstance(getattr(repo, 'forks_count', None), int) else 0
        default_branch = repo.default_branch if isinstance(getattr(repo, 'default_branch', None), str) else 'main'
        full_name = repo.full_name if isinstance(getattr(repo, 'full_name', None), str) else repo.name

        updated_at_val = getattr(repo, 'updated_at', None)
        updated_at = updated_at_val.isoformat() if isinstance(updated_at_val, datetime) else None

        perms = getattr(repo, 'permissions', None)
        perms_data = None
        if perms:
            perms_data = {
                'admin': bool(getattr(perms, 'admin', False)),
                'push': bool(getattr(perms, 'push', False)),
                'pull': bool(getattr(perms, 'pull', False)),
            }

        return {
            'id': repo.id,
            'name': repo.name,
            'full_name': full_name,
            'description': repo.description or "No description provided.",
            'html_url': repo.html_url,
            'is_private': bool(getattr(repo, 'private', False)),
            'role': role,
            'language': language,
            'stargazers_count': stars,
            'forks_count': forks,
            'default_branch': default_branch,
            'updated_at': updated_at,
            'pushed_at': repo.pushed_at.isoformat() if isinstance(getattr(repo, 'pushed_at', None), datetime) else None,
            'is_synced': is_synced,
            'project': project_data,
            'staff_member': staff_member,
            'permissions': perms_data,
            'docs': docs,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Document audit (README / CHANGELOG / ROADMAP / LICENSE)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def audit_repo_docs(repo, previous=None, force=False) -> Dict[str, Any]:
        """
        Check one repository against the document standard (brand/repo_docs.py).

        Costs one API call for the root listing, one per CHANGELOG/ROADMAP to
        read, and one more for docs/ when the root has no ROADMAP.md. The result
        is cached against the repo's last push, so a reload costs nothing.

        Returns the check_documents() dict plus 'status': 'ok' | 'problems' |
        'unknown'. 'unknown' means GitHub could not be asked, and carries 'error'.
        """
        pushed = getattr(repo, 'pushed_at', None)
        stamp = int(pushed.timestamp()) if isinstance(pushed, datetime) else 'na'
        from .github_cache import cache_scope
        key = f'github-doc-audit:v3:{cache_scope()}:{repo.id}:{stamp}'
        cached = cache.get(key)
        if cached is not None and not force:
            return cached

        try:
            try:
                root = repo.get_contents('')
            except GithubException as e:
                if e.status == 404:
                    # An empty repository has no contents to list.
                    result = repo_docs.check_documents({}, {})
                    result['status'] = 'problems'
                    result['empty_repo'] = True
                    cache.set(key, result, DOC_AUDIT_TTL_SECONDS)
                    return result
                raise
            if not isinstance(root, list):
                root = [root]
            root_files = {c.name: c.size for c in root if c.type == 'file'}
            file_shas = {c.name: c.sha for c in root if c.type == 'file' and isinstance(getattr(c, 'sha', None), str)}
            has_docs_dir = any(c.type == 'dir' and c.name == repo_docs.ROADMAP_FALLBACK_DIR for c in root)

            docs_files = None
            if has_docs_dir and not any(n.lower() == 'roadmap.md' for n in root_files):
                listing = repo.get_contents(repo_docs.ROADMAP_FALLBACK_DIR)
                docs_files = {c.name: c.size for c in listing if c.type == 'file'}
                file_shas.update({f'docs/{c.name}': c.sha for c in listing if c.type == 'file' and isinstance(getattr(c, 'sha', None), str)})

            wanted = {}
            for name in root_files:
                if name.lower() in ('changelog.md', 'roadmap.md'):
                    wanted[name] = name
            if docs_files:
                for name in docs_files:
                    if name.lower() == 'roadmap.md':
                        wanted[f'{repo_docs.ROADMAP_FALLBACK_DIR}/{name}'] = f'{repo_docs.ROADMAP_FALLBACK_DIR}/{name}'

            contents: Dict[str, Optional[str]] = {}
            previous = previous or {}
            for key_name, path in wanted.items():
                if (file_shas.get(path) and file_shas[path] == previous.get('shas', {}).get(path)
                        and path in previous.get('contents', {}) and previous['contents'][path] is not None):
                    contents[key_name] = previous['contents'][path]
                    continue
                try:
                    contents[key_name] = repo.get_contents(path).decoded_content.decode('utf-8')
                except (GithubException, UnicodeDecodeError, AssertionError) as e:
                    # Over 1 MB the contents API sends no body; binary is not text.
                    if isinstance(e, GithubException) and e.status != 404:
                        raise
                    logger.warning(f"Could not read {path} in {repo.full_name}: {e}")
                    contents[key_name] = None

            result = repo_docs.check_documents(root_files, contents, docs_files)
            result['_contents'] = contents
            result['_file_shas'] = file_shas
            result['status'] = 'ok' if result['ok'] else 'problems'
            cache.set(key, result, DOC_AUDIT_TTL_SECONDS)
            return result
        except Exception as e:
            if isinstance(e, GithubException) and e.status in (403, 429):
                raise
            # Not cached: the next load should try again. The panel shows
            # 'unknown' rather than a green tick it has not earned.
            logger.warning(f"Document audit failed for repo {getattr(repo, 'full_name', repo.id)}: {e}")
            return {'status': 'unknown', 'ok': False, 'problems': [], 'present': {}, 'roadmap': None,
                    'error': 'GitHub could not be asked about this repository\'s files.'}

    def get_account_info(self) -> Dict[str, Any]:
        """
        Say whose token this is. A personal access token always belongs to a
        user account, even when it can reach an organisation's repositories, so
        the answer is the account type of the token's owner plus the
        organisations that account belongs to.
        """
        user = self.client.get_user()
        token = config.github_access_token or ''
        if token.startswith('github_pat_'):
            token_kind = 'fine-grained personal access token'
        elif token.startswith('ghp_'):
            token_kind = 'classic personal access token'
        elif token.startswith('ghs_'):
            token_kind = 'GitHub App installation token'
        else:
            token_kind = 'token'
        orgs = [o.login for o in user.get_orgs()]
        account_type = user.type  # 'User' or 'Organization'
        configured = (self.username or '').strip()
        return {
            'login': user.login,
            'account_type': account_type,
            'is_organization': account_type == 'Organization',
            'token_kind': token_kind,
            'scopes': sorted(self.client.oauth_scopes or []),
            'organizations': orgs,
            'configured_username': configured,
            'username_matches': not configured or configured.lower() == user.login.lower(),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_user_repositories(self) -> List[Dict[str, Any]]:
        """
        Fetch all repositories the user owns, collaborates on, or has access to via staff profiles.
        Scans configured staff GitHub profiles and includes repositories where our authenticated
        GitHub token has permissions.
        """
        try:
            from .github_cache import cache_scope, fresh, repository_revision, save_metadata, store_document_audit, state_for
            from .models import GitHubRepositoryCache
            snapshots = {row.github_repo_id: row for row in GitHubRepositoryCache.objects.filter(scope=cache_scope())}
            discovery_complete = True
            staff_mapping = _get_staff_github_mapping()
            synced_projects = {
                p.github_repo_id: p
                for p in Project.objects.filter(github_repo_id__isnull=False)
            }
            repo_list = []
            repo_objects = []  # parallel to repo_list, for the document audit
            seen_repo_ids = set()

            # 1. Fetch repositories associated with the authenticated account
            user = self.client.get_user()
            repos = user.get_repos(affiliation='owner,collaborator,organization_member')

            for repo in repos:
                owner_login = repo.owner.login if hasattr(repo, 'owner') and hasattr(repo.owner, 'login') else ''
                owner_lower = owner_login.lower()
                if owner_lower == (self.username or '').lower():
                    role = 'owner'
                    staff_member = None
                elif owner_lower in staff_mapping:
                    role = 'staff'
                    staff_member = staff_mapping[owner_lower]
                else:
                    role = 'collaborator'
                    staff_member = None

                seen_repo_ids.add(repo.id)
                repo_objects.append(repo)
                repo_list.append(self._format_repo_dict(
                    repo,
                    role=role,
                    staff_member=staff_member,
                    synced_projects=synced_projects,
                ))

            # 2. Scan repositories owned by configured staff members
            for staff_lower, staff_info in staff_mapping.items():
                if staff_lower == (self.username or '').lower():
                    continue
                try:
                    staff_user = self.client.get_user(staff_info['username'])
                    for repo in staff_user.get_repos():
                        if repo.id in seen_repo_ids:
                            continue
                        if not _has_permission_to_repo(repo):
                            continue

                        seen_repo_ids.add(repo.id)
                        repo_objects.append(repo)
                        repo_list.append(self._format_repo_dict(
                            repo,
                            role='staff',
                            staff_member=staff_info,
                            synced_projects=synced_projects,
                        ))
                except GithubException as e:
                    if e.status in (403, 429):
                        raise
                    discovery_complete = False
                    logger.warning(f"Could not scan repos for staff user '{staff_info['username']}': {e}")
                except Exception as e:
                    discovery_complete = False
                    logger.warning(f"Unexpected error scanning repos for staff user '{staff_info['username']}': {e}")

            def documents_for(repo):
                row = snapshots.get(repo.id)
                revision = repository_revision(repo)
                if (row and revision and row.documents_revision == revision
                        and fresh(row.documents_checked_at) and row.documents):
                    return {**row.documents, '_contents': row.document_contents, '_file_shas': row.document_shas, '_cached_snapshot': True}
                return self.audit_repo_docs(repo, previous={"shas": row.document_shas, "contents": row.document_contents} if row else None, force=bool(row is None or not row.documents_checked_at))

            # Refresh only changed entries, and stop immediately on rate limits
            # rather than launching an audit for every repository concurrently.
            for repo, entry in zip(repo_objects, repo_list):
                docs = documents_for(repo)
                row = save_metadata(repo, entry)
                entry['docs'] = store_document_audit(repo, docs, row)
            if discovery_complete:
                GitHubRepositoryCache.objects.filter(scope=cache_scope()).exclude(github_repo_id__in=seen_repo_ids).update(available=False)
            state = state_for('catalogue')
            state.refreshed_at = timezone.now()
            state.save(update_fields=['refreshed_at'])

            self._discovered_repos = {repo.id: repo for repo in repo_objects}
            return sorted(repo_list, key=lambda x: (not x['is_synced'], x['name'].lower()))

        except GithubException as e:
            logger.error(f"GitHub API Error when fetching repositories: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error when fetching repositories: {e}")
            raise

    def get_repository_readme(self, repo_id: int) -> Dict[str, Any]:
        from .github_cache import cached_readme
        return cached_readme(repo_id)

    def sync_repositories(self, repo_ids: List[int]) -> Dict[str, Any]:
        """
        Sync specific repositories by their GitHub IDs.
        Creates or updates Project records with:
          - repo metadata (URL, role); name and description only when the
            project is first created, so admin edits survive a re-sync
          - total commit count
          - raw README markdown
          - last 10 commits cached in DB (no live GitHub calls needed by users)
        """
        success_count = 0
        error_count = 0
        errors = []

        try:
            staff_mapping = _get_staff_github_mapping()
            for repo_id in repo_ids:
                try:
                    repo = getattr(self, "_discovered_repos", {}).get(repo_id)
                    if repo is None:
                        repo = self.client.get_repo(repo_id)
                    owner_login = repo.owner.login if hasattr(repo, 'owner') and hasattr(repo.owner, 'login') else ''
                    owner_lower = owner_login.lower()
                    if owner_lower == (self.username or '').lower():
                        role = 'owner'
                    elif owner_lower in staff_mapping:
                        role = 'staff'
                    else:
                        role = 'collaborator'

                    from .github_cache import refresh_content, save_metadata
                    row = save_metadata(repo, self._format_repo_dict(
                        repo, role=role, staff_member=staff_mapping.get(owner_lower), synced_projects={}))
                    row = refresh_content(self, repo)
                    commit_count = row.commit_count or 0
                    readme_content = row.readme_content
                    cached_commits = row.recent_commits

                    # Two kinds of field. GitHub owns the repository facts and
                    # they are refreshed on every sync. The text is GitHub's
                    # only on the way in: once the project exists it belongs to
                    # whoever edits it in the admin panel. This used to be one
                    # update_or_create over both, and the hourly Beat sync put
                    # the repo name and description back over every edit.
                    facts = {
                        'github_url': repo.html_url,
                        'commit_count': commit_count,
                        'is_github_synced': True,
                        'github_role': role,
                        # When we synced, not when the repo last changed --
                        # repo.updated_at is what this used to store, and it
                        # made a working sync look days stale.
                        'last_synced_at': timezone.now(),
                        'readme_content': readme_content,
                        'cached_commits': cached_commits,
                    }
                    # create_defaults replaces defaults on create rather than
                    # adding to it, so the facts go in both.
                    project, _created = Project.objects.update_or_create(
                        github_repo_id=repo.id,
                        defaults=facts,
                        create_defaults={
                            **facts,
                            'title': repo.name,
                            'short_description': _short(repo.description),
                            'description': repo.description or "",
                        },
                    )
                    from tasks.github import queue_project_import
                    queue_project_import(project)
                    success_count += 1

                except GithubException as e:
                    logger.error(f"Failed to sync repo {repo_id}: {e}")
                    error_count += 1
                    errors.append(f"Repo {repo_id}: GitHub refresh failed (HTTP {e.status}).")
                    from .github_cache import record_failure, blocked_until
                    record_failure(f"repository:{repo_id}", e)
                    if blocked_until():
                        break

            return {
                "success": True,
                "synced_count": success_count,
                "error_count": error_count,
                "errors": errors,
            }

        except Exception as e:
            logger.exception("Failed during bulk sync.")
            return {"success": False, "error": str(e)}

    def get_recent_commits(self, github_repo_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        from .github_cache import cached_commits
        try:
            project = Project.objects.get(github_repo_id=github_repo_id)
        except Project.DoesNotExist:
            return {"success": False, "error": "Project not found."}
        return cached_commits(project, request_update=force_refresh)
