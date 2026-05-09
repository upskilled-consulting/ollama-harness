"""GET /api/github/* — GitHub repo intelligence via gh CLI + local git."""

import asyncio
import json
import re as _re
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
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
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
    branch, dirty, ahead, behind, meta = await asyncio.gather(
        _git("rev-parse", "--abbrev-ref", "HEAD"),
        _git("status", "--porcelain"),
        _git("rev-list", "--count", "@{u}..HEAD"),
        _git("rev-list", "--count", "HEAD..@{u}"),
        _gh("repo", "view", "--json",
            "name,owner,description,url,defaultBranchRef,isPrivate,stargazerCount,forkCount,pushedAt"),
    )
    dirty_count = len([ln for ln in dirty.splitlines() if ln.strip()])
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
        "--pretty=format:%H\x1f%h\x1f%s\x1f%an\x1f%ar\x1f%aI",
        "-365",
    )
    commits = []
    for line in raw.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 6:
            commits.append({
                "sha":     parts[0],
                "short":   parts[1],
                "message": parts[2],
                "author":  parts[3],
                "ago":     parts[4],
                "date":    parts[5][:10],  # YYYY-MM-DD only
            })
    return _set_cache("commits", commits)


_SHA_RE = _re.compile(r"^[0-9a-f]{4,64}$")


@router.get("/github/commits/{sha}/detail")
async def github_commit_detail(sha: str):
    if not _SHA_RE.match(sha):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid SHA")
    cache_key = f"commit_detail_{sha}"
    if (cached := _get_cache(cache_key, ttl=3600)) is not None:
        return cached

    msg   = await _git("show", "--no-patch", "--pretty=format:%B", sha)
    stat  = await _git("show", "--stat", "--no-patch", sha)

    files_raw = await _git("diff-tree", "--no-commit-id", "-r", "--name-status", sha)
    files: list[dict] = []
    for ln in files_raw.splitlines():
        parts = ln.split("\t", 1)
        if len(parts) == 2:
            files.append({"status": parts[0].strip(), "file": parts[1].strip()})

    diff = await _git("show", "--unified=3", "--no-color", sha)
    if len(diff) > 4_000:
        diff = diff[:4_000] + "\n\n… diff truncated — open on GitHub for full diff"

    return _set_cache(cache_key, {
        "sha":     sha,
        "message": msg.strip(),
        "stat":    stat,
        "files":   files,
        "diff":    diff,
    })


@router.get("/github/commits/{sha}/tree")
async def github_commit_tree(sha: str, path: str = ""):
    if not _SHA_RE.match(sha):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid SHA")
    cache_key = f"tree_{sha}_{path}"
    if (cached := _get_cache(cache_key, ttl=3600)) is not None:
        return cached

    tree_ref = sha if not path else f"{sha}:{path}"
    raw = await _git("ls-tree", "--long", tree_ref)

    entries = []
    for line in raw.splitlines():
        try:
            meta, name = line.split("\t", 1)
            parts = meta.split()
            if len(parts) >= 3:
                entries.append({
                    "mode":   parts[0],
                    "type":   parts[1],       # "blob" or "tree"
                    "object": parts[2],
                    "size":   int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None,
                    "name":   name.strip(),
                })
        except Exception:
            pass

    entries.sort(key=lambda e: (0 if e["type"] == "tree" else 1, e["name"].lower()))
    return _set_cache(cache_key, entries)


@router.get("/github/commits/{sha}/file")
async def github_commit_file(sha: str, path: str = ""):
    if not _SHA_RE.match(sha):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid SHA")
    if not path:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="path required")
    cache_key = f"file_{sha}_{path}"
    if (cached := _get_cache(cache_key, ttl=3600)) is not None:
        return cached

    content = await _git("show", f"{sha}:{path}")
    binary = "\x00" in content
    if binary:
        return _set_cache(cache_key, {"path": path, "content": "", "binary": True, "truncated": False})

    truncated = len(content) > 50_000
    if truncated:
        content = content[:50_000]
    return _set_cache(cache_key, {"path": path, "content": content, "binary": False, "truncated": truncated})


@router.post("/github/refresh")
async def github_refresh():
    _CACHE.clear()
    return {"ok": True}
