import logging
from typing import List, Dict, Any
from github import Github
from github.GithubException import GithubException
from django.utils import timezone
from brandtechsolution.config import config
from brand.models import Project

logger = logging.getLogger(__name__)


def _short(description):
    """Fit a repository description into Project.short_description (500)."""
    if description and len(description) > 500:
        return description[:497] + '...'
    return description


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

    def _fetch_commits_from_github(self, repo, count: int = 10) -> List[Dict]:
        """
        Internal helper: fetches commit metadata from a PyGithub repo object.
        This is the ONLY place that hits the GitHub API for commit data.
        Called exclusively during sync operations — never per user request.
        """
        commits_data = []
        try:
            for commit in repo.get_commits()[:count]:
                c = commit.commit
                commits_data.append({
                    'sha': commit.sha[:7],
                    'message': c.message.split('\n')[0][:120],
                    'author': c.author.name if c.author else 'Unknown',
                    'date': c.author.date.isoformat() if c.author else None,
                    'files_touched': commit.stats.total if commit.stats else 0,
                    'additions': commit.stats.additions if commit.stats else 0,
                    'deletions': commit.stats.deletions if commit.stats else 0,
                })
        except GithubException as e:
            logger.warning(f"Could not fetch commits: {e}")
        return commits_data

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_user_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories the user owns or collaborates on."""
        try:
            user = self.client.get_user()
            repos = user.get_repos(affiliation='owner,collaborator')

            synced_projects = {
                p.github_repo_id: p
                for p in Project.objects.filter(github_repo_id__isnull=False)
            }
            repo_list = []
            for repo in repos:
                owner_login = repo.owner.login if hasattr(repo, 'owner') and hasattr(repo.owner, 'login') else ''
                role = 'owner' if owner_login == self.username else 'collaborator'
                project = synced_projects.get(repo.id)
                is_synced = project is not None

                project_data = None
                if project:
                    project_data = {
                        'id': project.id,
                        'title': project.title,
                        'short_description': project.short_description or "",
                        'description': project.description or "",
                        'commit_count': project.commit_count or 0,
                        'last_synced_at': project.last_synced_at.isoformat() if project.last_synced_at else None,
                        'has_readme': bool(project.readme_content),
                        'readme_content': project.readme_content or "",
                        'cached_commits': project.cached_commits or [],
                        'project_url': project.project_url or "",
                        'featured': project.featured,
                    }

                language = repo.language if isinstance(getattr(repo, 'language', None), str) else None
                stars = repo.stargazers_count if isinstance(getattr(repo, 'stargazers_count', None), int) else 0
                forks = repo.forks_count if isinstance(getattr(repo, 'forks_count', None), int) else 0
                default_branch = repo.default_branch if isinstance(getattr(repo, 'default_branch', None), str) else 'main'
                full_name = repo.full_name if isinstance(getattr(repo, 'full_name', None), str) else repo.name
                
                updated_at_val = getattr(repo, 'updated_at', None)
                updated_at = updated_at_val.isoformat() if hasattr(updated_at_val, 'isoformat') else None

                repo_list.append({
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
                    'is_synced': is_synced,
                    'project': project_data,
                })

            return sorted(repo_list, key=lambda x: (not x['is_synced'], x['name'].lower()))

        except GithubException as e:
            logger.error(f"GitHub API Error when fetching repositories: {e}")
            raise Exception(f"Failed to fetch from GitHub: {e.data.get('message', str(e))}")
        except Exception as e:
            logger.error(f"Unexpected error when fetching repositories: {e}")
            raise Exception(f"An unexpected error occurred: {str(e)}")

    def get_repository_readme(self, repo_id: int) -> Dict[str, Any]:
        """Fetch raw and decoded README markdown for a repository."""
        try:
            # If project exists and has cached readme, return it
            project = Project.objects.filter(github_repo_id=repo_id).first()
            if project and project.readme_content:
                return {
                    "success": True,
                    "readme": project.readme_content,
                    "cached": True,
                }

            repo = self.client.get_repo(repo_id)
            readme_file = repo.get_readme()
            readme_content = readme_file.decoded_content.decode('utf-8')
            return {
                "success": True,
                "readme": readme_content,
                "cached": False,
            }
        except GithubException as e:
            logger.warning(f"Could not fetch README for repo {repo_id}: {e}")
            return {"success": False, "error": "No README found for this repository on GitHub."}
        except Exception as e:
            logger.error(f"Unexpected error fetching README: {e}")
            return {"success": False, "error": str(e)}

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
            for repo_id in repo_ids:
                try:
                    repo = self.client.get_repo(repo_id)
                    role = 'owner' if repo.owner.login == self.username else 'collaborator'

                    # Total commit count — single API call via PaginatedList.totalCount
                    try:
                        commit_count = repo.get_commits().totalCount
                    except GithubException:
                        commit_count = 0

                    # Raw README markdown
                    try:
                        readme_content = repo.get_readme().decoded_content.decode('utf-8')
                    except GithubException:
                        readme_content = None

                    # Last 10 commits — stored in DB, served cold to every user
                    cached_commits = self._fetch_commits_from_github(repo, count=10) or None

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
                    Project.objects.update_or_create(
                        github_repo_id=repo.id,
                        defaults=facts,
                        create_defaults={
                            **facts,
                            'title': repo.name,
                            'short_description': _short(repo.description),
                            'description': repo.description or "",
                        },
                    )
                    success_count += 1

                except GithubException as e:
                    logger.error(f"Failed to sync repo {repo_id}: {e}")
                    error_count += 1
                    errors.append(f"Repo {repo_id}: {e.data.get('message', str(e))}")

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
        """
        Returns commits for a project.

        Normal path  → reads `cached_commits` from DB (instant, no GitHub call).
        force_refresh → fetches live from GitHub and updates the DB cache.
        First-time   → if cached_commits is empty, falls back to live fetch.
        """
        try:
            project = Project.objects.get(github_repo_id=github_repo_id)

            if not force_refresh and project.cached_commits:
                return {"success": True, "commits": project.cached_commits, "cached": True}

            # First-time or forced refresh — hit GitHub, then persist
            repo = self.client.get_repo(github_repo_id)
            commits_data = self._fetch_commits_from_github(repo, count=10)
            Project.objects.filter(github_repo_id=github_repo_id).update(
                cached_commits=commits_data or None
            )
            return {"success": True, "commits": commits_data, "cached": False}

        except Project.DoesNotExist:
            return {"success": False, "error": "Project not found."}
        except GithubException as e:
            logger.error(f"Failed to fetch commits for repo {github_repo_id}: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error fetching commits: {e}")
            return {"success": False, "error": str(e)}
