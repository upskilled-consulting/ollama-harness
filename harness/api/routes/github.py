"""GET /api/github/* — GitHub repo intelligence via gh CLI + local git."""

import asyncio
import json
import time

from fastapi import APIRouter

from harness.config import ROOT

router = APIRouter(tags=["github"])

_CACHE: dict[str, tuple[float, object]] = {}
_TTL = 60.0


def _get_cache(key: str, ttl: float = _TTL):
    now = time.monotonic()
    entry = _CACHE.get(key)
    if entry and now - entry[0] < ttl:
        return entry[1]
    return None


def _set_cache(key: str, val: object) -> object:
    _CACHE[key] = (time.monotonic(), val)
    return val


async def _gh(*args: str) -> dict | list | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(ROOT),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception:
        return None


async def _git(*args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(ROOT),
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


@router.get("/github/repo")
async def github_repo():
    if (cached := _get_cache("repo", 30)) is not None:
        return cached
    branch = await _git("rev-parse", "--abbrev-ref", "HEAD")
    dirty  = await _git("status", "--porcelain")
    dirty_count = len([ln for ln in dirty.splitlines() if ln.strip()])
    ahead  = await _git("rev-list", "--count", "@{u}..HEAD")
    behind = await _git("rev-list", "--count", "HEAD..@{u}")
    meta   = await _gh("repo", "view", "--json",
                       "name,owner,description,url,defaultBranchRef,isPrivate,stargazerCount,forkCount,pushedAt")
    return _set_cache("repo", {
        "branch":      branch or "unknown",
        "dirty_files": dirty_count,
        "ahead":       int(ahead)  if ahead.isdigit()  else 0,
        "behind":      int(behind) if behind.isdigit() else 0,
        "meta":        meta,
    })


@router.get("/github/prs")
async def github_prs():
    if (cached := _get_cache("prs")) is not None:
        return cached
    data = await _gh("pr", "list",
                     "--json", "number,title,state,author,createdAt,headRefName,isDraft,reviewDecision",
                     "--limit", "15")
    return _set_cache("prs", data or [])


@router.get("/github/issues")
async def github_issues():
    if (cached := _get_cache("issues")) is not None:
        return cached
    data = await _gh("issue", "list",
                     "--json", "number,title,state,author,createdAt,labels,assignees",
                     "--limit", "15")
    return _set_cache("issues", data or [])


@router.get("/github/runs")
async def github_ci_runs():
    if (cached := _get_cache("runs_ci", 30)) is not None:
        return cached
    data = await _gh("run", "list",
                     "--limit", "10",
                     "--json", "databaseId,name,status,conclusion,createdAt,headBranch,url,event")
    return _set_cache("runs_ci", data or [])


@router.get("/github/commits")
async def github_commits():
    if (cached := _get_cache("commits")) is not None:
        return cached
    raw = await _git(
        "log", "--no-decorate",
        "--pretty=format:%H\x1f%h\x1f%s\x1f%an\x1f%ar",
        "-15",
    )
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            commits.append({"sha": parts[0], "short": parts[1],
                            "message": parts[2], "author": parts[3], "ago": parts[4]})
    return _set_cache("commits", commits)


@router.post("/github/refresh")
async def github_refresh():
    _CACHE.clear()
    return {"ok": True}
