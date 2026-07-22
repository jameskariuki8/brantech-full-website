import logging
from typing import List, Dict, Any
from github import Github
from github.GithubException import GithubException
from brandtechsolution.config import config
from brand.models import Project

logger = logging.getLogger(__name__)


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

            repo_list = []
            for repo in repos:
                role = 'owner' if repo.owner.login == self.username else 'collaborator'
                is_synced = Project.objects.filter(github_repo_id=repo.id).exists()
                repo_list.append({
                    'id': repo.id,
                    'name': repo.name,
                    'description': repo.description or "No description provided.",
                    'html_url': repo.html_url,
                    'is_private': repo.private,
                    'role': role,
                    'is_synced': is_synced,
                })

            return sorted(repo_list, key=lambda x: (not x['is_synced'], x['name'].lower()))

        except GithubException as e:
            logger.error(f"GitHub API Error when fetching repositories: {e}")
            raise Exception(f"Failed to fetch from GitHub: {e.data.get('message', str(e))}")
        except Exception as e:
            logger.error(f"Unexpected error when fetching repositories: {e}")
            raise Exception(f"An unexpected error occurred: {str(e)}")

    def sync_repositories(self, repo_ids: List[int]) -> Dict[str, Any]:
        """
        Sync specific repositories by their GitHub IDs.
        Creates or updates Project records with:
          - repo metadata (name, description, URLs, role)
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

                    Project.objects.update_or_create(
                        github_repo_id=repo.id,
                        defaults={
                            'title': repo.name,
                            'short_description': (repo.description[:497] + '...') if repo.description and len(repo.description) > 500 else repo.description,
                            'description': repo.description or "",
                            'github_url': repo.html_url,
                            'commit_count': commit_count,
                            'is_github_synced': True,
                            'github_role': role,
                            'last_synced_at': repo.updated_at,
                            'readme_content': readme_content,
                            'cached_commits': cached_commits,
                        }
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
