"""
GitHub repository scanner for OpenAPI spec files.

Uses the GitHub REST API to walk the file tree and parse any YAML/JSON files
that are valid OpenAPI specs. Enforces a 60-second timeout.
"""

import asyncio
import base64
from typing import Optional
from urllib.parse import urlparse

import httpx
import structlog

from sentinel_shared.models import EndpointRecord
from .openapi_parser import parse_openapi_spec, OpenAPIParseError

logger = structlog.get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
SCAN_TIMEOUT_SECONDS = 60
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB per file


class GitHubScanError(Exception):
    """Raised when a GitHub repository scan fails."""

    def __init__(self, message: str, repo_url: str = ""):
        super().__init__(message)
        self.repo_url = repo_url


def _parse_repo_url(repo_url: str) -> tuple[str, str]:
    """
    Parse a GitHub repository URL into (owner, repo) tuple.

    Supports formats:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - owner/repo

    Args:
        repo_url: GitHub repository URL or owner/repo string.

    Returns:
        Tuple of (owner, repo_name).

    Raises:
        GitHubScanError: If the URL cannot be parsed.
    """
    repo_url = repo_url.strip().rstrip("/")

    if repo_url.startswith("https://github.com/"):
        path = repo_url[len("https://github.com/"):]
    elif repo_url.startswith("http://github.com/"):
        path = repo_url[len("http://github.com/"):]
    elif repo_url.startswith("github.com/"):
        path = repo_url[len("github.com/"):]
    else:
        path = repo_url

    # Remove .git suffix
    if path.endswith(".git"):
        path = path[:-4]

    parts = path.strip("/").split("/")
    if len(parts) < 2:
        raise GitHubScanError(
            f"Cannot parse GitHub repo URL: '{repo_url}'",
            repo_url=repo_url,
        )

    return parts[0], parts[1]


async def _get_default_branch(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    token: Optional[str],
) -> str:
    """Get the default branch name for a repository."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    response = await client.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
        headers=headers,
    )
    response.raise_for_status()
    return response.json().get("default_branch", "main")


async def _get_file_tree(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    branch: str,
    token: Optional[str],
) -> list[dict]:
    """
    Fetch the full recursive file tree for a repository branch.

    Returns list of tree items with 'path', 'type', 'sha', 'size' fields.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    response = await client.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}",
        headers=headers,
        params={"recursive": "1"},
    )
    response.raise_for_status()
    data = response.json()

    if data.get("truncated"):
        logger.warning(
            "github_tree_truncated",
            owner=owner,
            repo=repo,
            branch=branch,
        )

    return data.get("tree", [])


async def _fetch_file_content(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    file_path: str,
    token: Optional[str],
) -> Optional[bytes]:
    """
    Fetch the content of a file from GitHub.

    Returns file content as bytes, or None if the file is too large or fetch fails.
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{file_path}",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        # Check file size
        if data.get("size", 0) > MAX_FILE_SIZE_BYTES:
            logger.debug("github_file_too_large", path=file_path, size=data.get("size"))
            return None

        # Decode base64 content
        content_b64 = data.get("content", "")
        if not content_b64:
            return None

        return base64.b64decode(content_b64.replace("\n", ""))

    except Exception as exc:
        logger.debug("github_file_fetch_failed", path=file_path, error=str(exc))
        return None


def _is_potential_openapi_file(file_path: str) -> bool:
    """Check if a file path looks like it could contain an OpenAPI spec."""
    lower = file_path.lower()
    return lower.endswith(".yaml") or lower.endswith(".yml") or lower.endswith(".json")


async def scan_github_repo(
    repo_url: str,
    token: Optional[str] = None,
    default_host: str = "unknown",
) -> list[EndpointRecord]:
    """
    Scan a GitHub repository for OpenAPI spec files and extract endpoint records.

    Walks the repository file tree, fetches YAML/JSON files, attempts to parse
    each as an OpenAPI spec, and collects all endpoint records.

    Args:
        repo_url: GitHub repository URL (e.g., https://github.com/owner/repo).
        token: Optional GitHub personal access token for private repos.
        default_host: Default host to use for endpoints if not specified in spec.

    Returns:
        List of EndpointRecord instances from all valid OpenAPI specs found.

    Raises:
        GitHubScanError: If the repository cannot be accessed or scan times out.
    """
    owner, repo = _parse_repo_url(repo_url)
    records: list[EndpointRecord] = []

    async def _do_scan() -> list[EndpointRecord]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get default branch
            try:
                branch = await _get_default_branch(client, owner, repo, token)
            except httpx.HTTPStatusError as exc:
                raise GitHubScanError(
                    f"Failed to access repository '{owner}/{repo}': HTTP {exc.response.status_code}",
                    repo_url=repo_url,
                ) from exc

            # Get file tree
            try:
                tree = await _get_file_tree(client, owner, repo, branch, token)
            except httpx.HTTPStatusError as exc:
                raise GitHubScanError(
                    f"Failed to fetch file tree for '{owner}/{repo}': HTTP {exc.response.status_code}",
                    repo_url=repo_url,
                ) from exc

            # Filter to potential OpenAPI files
            candidate_files = [
                item for item in tree
                if item.get("type") == "blob" and _is_potential_openapi_file(item.get("path", ""))
            ]

            logger.info(
                "github_scan_started",
                owner=owner,
                repo=repo,
                branch=branch,
                candidate_files=len(candidate_files),
            )

            scan_records: list[EndpointRecord] = []

            for file_item in candidate_files:
                file_path = file_item.get("path", "")
                content = await _fetch_file_content(client, owner, repo, file_path, token)
                if content is None:
                    continue

                try:
                    file_records = parse_openapi_spec(
                        content,
                        file_name=f"{owner}/{repo}/{file_path}",
                        default_host=default_host,
                    )
                    scan_records.extend(file_records)
                    logger.debug(
                        "github_file_parsed",
                        path=file_path,
                        endpoints_found=len(file_records),
                    )
                except OpenAPIParseError:
                    # Not an OpenAPI spec — skip silently
                    pass
                except Exception as exc:
                    logger.debug(
                        "github_file_parse_error",
                        path=file_path,
                        error=str(exc),
                    )

            logger.info(
                "github_scan_complete",
                owner=owner,
                repo=repo,
                total_endpoints=len(scan_records),
            )
            return scan_records

    try:
        records = await asyncio.wait_for(_do_scan(), timeout=SCAN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise GitHubScanError(
            f"GitHub scan timed out after {SCAN_TIMEOUT_SECONDS} seconds for '{owner}/{repo}'",
            repo_url=repo_url,
        )

    return records
