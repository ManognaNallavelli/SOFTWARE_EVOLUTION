"""GitHub URL normalization and public repository validation."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AI-Software-Evolution-Platform",
    "X-GitHub-Api-Version": "2022-11-28",
}


@dataclass(frozen=True)
class ParsedGitHubRepo:
    owner: str
    repo: str
    normalized_url: str


@dataclass(frozen=True)
class ValidatedGitHubRepo:
    github_repo_id: int
    owner: str
    repo: str
    full_name: str
    normalized_url: str
    default_branch: str
    html_url: str
    size_kb: int = 0


def normalize_github_url(raw_url: str) -> ParsedGitHubRepo:
    candidate = raw_url.strip()
    match = _GITHUB_URL_RE.match(candidate)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_github_url",
                "message": "Enter a valid public GitHub repository URL "
                "(e.g. https://github.com/owner/repo).",
            },
        )

    owner = match.group(1)
    repo = match.group(2)
    if owner.lower() in {"settings", "orgs", "marketplace", "features", "topics", "explore"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_github_url",
                "message": "That URL does not look like a GitHub repository.",
            },
        )

    normalized = f"https://github.com/{owner}/{repo}"
    return ParsedGitHubRepo(owner=owner, repo=repo, normalized_url=normalized)


def _fetch_github_repo(api_url: str) -> httpx.Response:
    last_error: Exception | None = None
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for _ in range(3):
            try:
                return client.get(api_url, headers=_GITHUB_HEADERS)
            except httpx.HTTPError as exc:
                last_error = exc
    assert last_error is not None
    raise last_error


async def validate_public_github_repository(raw_url: str) -> ValidatedGitHubRepo:
    parsed = normalize_github_url(raw_url)
    api_url = f"https://api.github.com/repos/{parsed.owner}/{parsed.repo}"

    try:
        response = await asyncio.to_thread(_fetch_github_repo, api_url)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "github_unreachable",
                "message": "Could not reach GitHub to validate the repository. Try again shortly.",
            },
        ) from exc

    if response.status_code in {502, 503, 504}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "github_temporarily_unavailable",
                "message": "GitHub is temporarily unavailable while validating the repository. Try again.",
            },
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "repository_not_found",
                "message": "GitHub repository not found. Check the URL or confirm the repository is public.",
            },
        )

    if response.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "github_rate_limited",
                "message": "GitHub rejected the validation request (rate limit or access). Try again later.",
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "github_validation_failed",
                "message": f"GitHub validation failed with status {response.status_code}.",
            },
        )

    payload = response.json()
    if payload.get("private") is True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "private_repository",
                "message": "Only public GitHub repositories are supported in this phase.",
            },
        )

    repo_id = payload.get("id")
    if not isinstance(repo_id, int):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "github_invalid_response",
                "message": "GitHub returned an unexpected repository payload.",
            },
        )

    full_name = str(payload.get("full_name") or f"{parsed.owner}/{parsed.repo}")
    default_branch = str(payload.get("default_branch") or "main")
    html_url = str(payload.get("html_url") or parsed.normalized_url)
    raw_size = payload.get("size")
    size_kb = int(raw_size) if isinstance(raw_size, int) and raw_size >= 0 else 0

    return ValidatedGitHubRepo(
        github_repo_id=repo_id,
        owner=parsed.owner,
        repo=parsed.repo,
        full_name=full_name,
        normalized_url=parsed.normalized_url,
        default_branch=default_branch,
        html_url=html_url,
        size_kb=size_kb,
    )
