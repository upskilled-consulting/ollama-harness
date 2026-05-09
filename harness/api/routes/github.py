"""GET /api/github/* — GitHub repo intelligence via gh CLI + local git."""

import asyncio
import json
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter

from harness.config import ROOT

router = APIRouter(tags=["github"])

# ---------------------------------------------------------------------------
# Simple in-process TTL cache (avoids hammering gh on every poll)
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, object]] = {}
_TTL = 60.0  # seconds


def _cached(key: str, ttl: float = _TTL):
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            now = time.monotonic()
            if key in _CACHE:
                ts, val = _CACHE[key]
                if now - ts < ttl:
                    return val
            val = await fn(*args, **kwargs)
            _CACHE[key] = (now, val)
            return val
        return wrapper
    return decorator


async def _gh(*args: str, cwd: Path = ROOT) -> dict | list | None:
    """Run a gh CLI command, return parsed JSON or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(cwd),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception:
        return None


async def _git(*args: str, cwd: Path = ROOT) -> str:
    """Run a git command, return stripped stdout or '' on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(cwd),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/github/repo")
@_cached("repo", ttl=30)
async def github_repo():
    """Local branch + ahead/behind + remote repo metadata."""
    branch = await _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty  = await _git("status", "--porcelain")
    dirty_count = len([l for l in dirty.splitlines() if l.strip()])

    ahead  = await _git("rev-list", "--count", "@{u}..HEAD")
    behind = await _git("rev-list", "--count", "HEAD..@{u}")

    meta = await _gh("repo", "view", "--json",
                     "name,owner,description,url,defaultBranchRef,isPrivate,stargazerCount,forkCount,pushedAt")

    return {
        "branch":       branch or "unknown",
        "dirty_files":  dirty_count,
        "ahead":        int(ahead)  if ahead.isdigit()  else 0,
        "behind":       int(behind) if behind.isdigit() else 0,
        "meta":         meta,
    }


@router.get("/github/prs")
@_cached("prs")
async def github_prs():
    """Open pull requests."""
    data = await _gh("pr", "list",
                     "--json", "number,title,state,author,createdAt,headRefName,isDraft,reviewDecision",
                     "--limit", "15")
    return data or []


@router.get("/github/issues")
@_cached("issues")
async def github_issues():
    """Open issues."""
    data = await _gh("issue", "list",
                     "--json", "number,title,state,author,createdAt,labels,assignees",
                     "--limit", "15")
    return data or []


@router.get("/github/runs")
@_cached("runs_ci", ttl=30)
async def github_ci_runs():
    """Recent CI workflow runs."""
    data = await _gh("run", "list",
                     "--limit", "10",
                     "--json", "databaseId,name,status,conclusion,createdAt,headBranch,url,event")
    return data or []


@router.get("/github/commits")
@_cached("commits")
async def github_commits():
    """Recent commits on current branch via local git log."""
    raw = await _git(
        "log", "--oneline", "--no-decorate",
        "--pretty=format:%H\x1f%h\x1f%s\x1f%an\x1f%ar",
        "-15",
    )
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            commits.append({
                "sha":     parts[0],
                "short":   parts[1],
                "message": parts[2],
                "author":  parts[3],
                "ago":     parts[4],
            })
    return commits


@router.post("/github/refresh")
async def github_refresh():
    """Bust all cached GitHub data."""
    _CACHE.clear()
    return {"ok": True}
