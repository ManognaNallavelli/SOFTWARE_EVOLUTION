"""Clone public GitHub repositories into a project-specific workspace."""

from __future__ import annotations

import logging
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status

from app.analyzers.ignore_rules import safe_repo_root
from app.config import Settings

logger = logging.getLogger(__name__)

CLONE_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class CloneResult:
    local_path: Path
    branch: str
    github_url: str


def ensure_clone_base(settings: Settings) -> Path:
    configured = (settings.repo_clone_dir or "").strip()
    if configured:
        base = Path(configured)
        if not base.is_absolute():
            base = Path.cwd() / base
    else:
        # Prefer OS temp to avoid OneDrive/cloud-sync locks under the project folder.
        base = Path(tempfile.gettempdir()) / "ase_repos"
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def _rmtree_retry(path: Path, attempts: int = 8) -> None:
    if not path.exists():
        return
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)
    if path.exists() and last_error is not None:
        logger.warning("Incomplete cleanup for %s: %s", path, last_error)


def cleanup_clone_path(path: Path | None) -> None:
    """Remove one clone directory (safe for concurrent per-project runs)."""
    if path is None:
        return
    _rmtree_retry(Path(path))


def cleanup_project_clone(settings: Settings, project_id: str) -> None:
    try:
        root = safe_repo_root(ensure_clone_base(settings), project_id)
    except ValueError:
        return
    _rmtree_retry(root)
    logger.info("Cleaned clone workspace for project %s", project_id)


def _git_error_summary(stderr: str, stdout: str) -> str:
    text = "\n".join(part for part in (stderr, stdout) if part).strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    interesting = [
        ln
        for ln in lines
        if ln.lower().startswith(("fatal:", "error:", "warning:"))
        or "denied" in ln.lower()
        or "too long" in ln.lower()
        or "space" in ln.lower()
    ]
    chosen = interesting[-3:] if interesting else lines[-3:]
    return " | ".join(chosen)[:400]


def clone_public_repository(
    *,
    settings: Settings,
    project_id: str,
    github_url: str,
    branch: str | None,
) -> CloneResult:
    try:
        base = ensure_clone_base(settings)
        project_root = safe_repo_root(base, project_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_project_id", "message": str(exc)},
        ) from exc

    project_root.mkdir(parents=True, exist_ok=True)

    # Unique per-run folder avoids Windows "destination exists" after incomplete deletes.
    target = project_root / f"repo-{secrets.token_hex(6)}"
    clone_url = github_url.rstrip("/")
    if not clone_url.endswith(".git"):
        clone_url = f"{clone_url}.git"

    # core.longpaths helps Windows checkouts of deep trees (e.g. React monorepo).
    cmd = ["git", "-c", "core.longpaths=true", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([clone_url, str(target)])

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "git_not_installed",
                "message": "Git is not installed on the server and is required to clone repositories.",
            },
        ) from exc
    except subprocess.TimeoutExpired as exc:
        cleanup_clone_path(target)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "clone_timeout",
                "message": (
                    "Cloning the repository timed out. This often happens with very large "
                    "repos (for example facebook/react). Try a smaller public repository."
                ),
            },
        ) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        summary = _git_error_summary(stderr, stdout)
        logger.warning(
            "Clone failed for %s (rc=%s): %s",
            project_id,
            completed.returncode,
            (summary or stderr or stdout)[:800],
        )
        cleanup_clone_path(target)

        message = "Failed to clone the GitHub repository."
        lower = f"{stderr}\n{stdout}".lower()
        if "not found" in lower or "repository not found" in lower:
            message = "GitHub repository could not be cloned (not found or inaccessible)."
        elif "could not resolve host" in lower or "unable to access" in lower:
            message = "Could not reach GitHub while cloning the repository."
        elif "filename too long" in lower:
            message = (
                "Clone failed because some file paths are too long for Windows. "
                "Try a smaller repository, or enable Windows long-path support."
            )
        elif "access is denied" in lower or "permission denied" in lower:
            message = (
                "Clone failed due to a Windows file lock (Access denied) while writing git objects. "
                "Retry once; if it persists, reboot or pause antivirus scanning of the temp folder."
            )
        elif "no space" in lower or "disk quota" in lower:
            message = "Clone failed because the disk is out of space."
        elif summary:
            message = f"Failed to clone the GitHub repository. {summary}"

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "clone_failed", "message": message},
        )

    used_branch = branch or "unknown"
    head = target / ".git" / "HEAD"
    if head.exists():
        try:
            content = head.read_text(encoding="utf-8", errors="ignore").strip()
            if content.startswith("ref: refs/heads/"):
                used_branch = content.split("/")[-1]
        except OSError:
            pass

    return CloneResult(local_path=target, branch=used_branch, github_url=github_url)
