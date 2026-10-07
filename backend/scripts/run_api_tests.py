"""Black-box API test run against the local backend. Results -> results.json.

Run from backend/ with the server already running:
    .\\.venv\\Scripts\\python.exe scripts\\run_api_tests.py

OWNER / OTHER_USERS_PROJECT / AXIOS_PROJECT are ids from the local MongoDB; update them
if the database is reset.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.mongo import close_mongo, connect_mongo, get_db  # noqa: E402
from app.services.session_service import create_session  # noqa: E402

BASE = "http://127.0.0.1:8000"
OWNER = "6a9d718f8ea8fc33df3af7aa"
OTHER_USERS_PROJECT = "6a9dcd017e8bc5de164a06b8"
AXIOS_PROJECT = "6aa24c76ed599e4b3b2d20b4"
OUT = Path(__file__).with_name("results.json")

results: list[dict] = []


def record(tc: str, title: str, expected: str, actual: str, passed: bool, seconds: float) -> None:
    results.append(
        {
            "id": tc,
            "title": title,
            "expected": expected,
            "actual": actual,
            "status": "PASS" if passed else "FAIL",
            "seconds": round(seconds, 1),
        }
    )
    print(f"{tc} {'PASS' if passed else 'FAIL'} ({seconds:.1f}s) {title} -> {actual}")


def detail_code(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(d, dict):
        return str(d.get("code") or "")
    return ""


async def main() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    session = await create_session(db, OWNER, settings)
    cookie_name = settings.session_cookie_name
    temp_ids: list[str] = []

    anon = httpx.AsyncClient(base_url=BASE, timeout=60)
    auth = httpx.AsyncClient(base_url=BASE, timeout=600, cookies={cookie_name: session})
    bad = httpx.AsyncClient(base_url=BASE, timeout=60, cookies={cookie_name: "forged-session-value"})

    try:
        t = time.time()
        r = await anon.get("/api/health")
        body = r.json()
        record("TC-01", "Health check endpoint", "200, status ok, MongoDB connected",
               f"{r.status_code}, status={body.get('status')}, mongodb={body.get('mongodb')}",
               r.status_code == 200 and body.get("status") == "ok" and body.get("mongodb") == "connected", time.time() - t)

        t = time.time()
        r = await anon.get("/api/auth/me")
        record("TC-02", "Session check without login", "200, authenticated=false",
               f"{r.status_code}, authenticated={r.json().get('authenticated')}",
               r.status_code == 200 and r.json().get("authenticated") is False, time.time() - t)

        t = time.time()
        r = await anon.get("/api/projects")
        record("TC-03", "Protected route without login", "401 Unauthorized", f"{r.status_code}",
               r.status_code == 401, time.time() - t)

        t = time.time()
        r = await bad.get("/api/projects")
        record("TC-04", "Protected route with forged session cookie", "401 Unauthorized", f"{r.status_code}",
               r.status_code == 401, time.time() - t)

        t = time.time()
        r = await auth.get("/api/auth/me")
        me = r.json()
        record("TC-05", "Session check after login", "200, authenticated=true, user returned",
               f"{r.status_code}, authenticated={me.get('authenticated')}, user={(me.get('user') or {}).get('name')}",
               r.status_code == 200 and me.get("authenticated") is True, time.time() - t)

        t = time.time()
        r = await auth.get("/api/projects")
        projects = r.json().get("projects", [])
        foreign = [p for p in projects if p["owner_user_id"] != OWNER]
        record("TC-06", "List projects shows only own projects", "200, every project owned by current user",
               f"{r.status_code}, {len(projects)} projects, {len(foreign)} foreign",
               r.status_code == 200 and not foreign, time.time() - t)

        t = time.time()
        r = await auth.post("/api/projects", json={"name": "x", "github_url": "https://gitlab.com/foo/bar"})
        record("TC-07", "Create project with non-GitHub URL", "400 invalid_github_url",
               f"{r.status_code} {detail_code(r)}", r.status_code == 400 and detail_code(r) == "invalid_github_url", time.time() - t)

        t = time.time()
        r = await auth.post("/api/projects", json={"name": "x", "github_url": "https://github.com/octocat/this-repo-does-not-exist-123"})
        record("TC-08", "Create project for non-existent repository", "404 repository_not_found",
               f"{r.status_code} {detail_code(r)}", r.status_code == 404 and detail_code(r) == "repository_not_found", time.time() - t)

        t = time.time()
        r = await auth.post("/api/projects", json={"name": "axios", "github_url": "https://github.com/axios/axios"})
        record("TC-09", "Create duplicate project (already connected repo)", "409 duplicate_repository",
               f"{r.status_code} {detail_code(r)}", r.status_code == 409 and detail_code(r) == "duplicate_repository", time.time() - t)

        t = time.time()
        r = await auth.get(f"/api/projects/{OTHER_USERS_PROJECT}")
        record("TC-10", "Open another user's project", "403/404, no data leaked",
               f"{r.status_code} {detail_code(r)}", r.status_code in (403, 404), time.time() - t)

        t = time.time()
        r = await auth.delete(f"/api/projects/{OTHER_USERS_PROJECT}")
        still = await db.projects.find_one({"_id": ObjectId(OTHER_USERS_PROJECT)})
        record("TC-11", "Delete another user's project", "403/404, project still exists",
               f"{r.status_code}, still exists={still is not None}", r.status_code in (403, 404) and still is not None, time.time() - t)

        t = time.time()
        r = await auth.post("/api/projects", json={"name": "Spoon-Knife", "github_url": "https://github.com/octocat/Spoon-Knife"})
        spoon = r.json().get("id") if r.status_code == 201 else None
        if spoon:
            temp_ids.append(spoon)
        record("TC-12", "Create project for valid public repository", "201 Created, project id returned",
               f"{r.status_code}, id={spoon}", r.status_code == 201 and bool(spoon), time.time() - t)

        if spoon:
            t = time.time()

            async def second_call():
                await asyncio.sleep(1.0)
                return await auth.post(f"/api/projects/{spoon}/analyze")

            first, second = await asyncio.gather(auth.post(f"/api/projects/{spoon}/analyze"), second_call())
            a = first.json()
            hr = a.get("health_report") or {}
            record("TC-13", "Analyze small repository (clone + analysis + health)", "200, status completed, health score present",
                   f"{first.status_code}, status={a.get('status')}, score={hr.get('overall_score')}",
                   first.status_code == 200 and a.get("status") == "completed" and hr.get("overall_score") is not None, time.time() - t)
            record("TC-14", "Second analyze while first is running", "409 analysis_in_progress",
                   f"{second.status_code} {detail_code(second)}", second.status_code == 409, 0)

            t = time.time()
            r = await auth.get(f"/api/projects/{spoon}/analysis")
            summary = ((r.json().get("analysis") or {}).get("summary") or {})
            record("TC-15", "Fetch stored analysis", "200, analysis summary with file counts",
                   f"{r.status_code}, files={summary.get('total_files')}", r.status_code == 200 and r.json().get("analysis") is not None, time.time() - t)

            t = time.time()
            r = await auth.post(f"/api/projects/{spoon}/architecture/generate")
            g = (r.json().get("graph") or {}) if r.status_code == 200 else {}
            record("TC-17", "Generate architecture diagram", "200, graph with nodes",
                   f"{r.status_code}, status={r.json().get('status')}, nodes={len(g.get('nodes') or [])}, edges={len(g.get('edges') or [])}",
                   r.status_code == 200 and len(g.get("nodes") or []) > 0, time.time() - t)

            t = time.time()
            status_value = None
            for _ in range(60):
                rs = await auth.get(f"/api/projects/{spoon}/rag/status")
                status_value = rs.json().get("status")
                if status_value in ("ready", "failed"):
                    break
                await asyncio.sleep(3)
            rsj = rs.json()
            record("TC-18", "Automatic RAG indexing after analysis", "status ready with chunk count > 0",
                   f"status={status_value}, files={rsj.get('file_count')}, chunks={rsj.get('chunk_count')}",
                   status_value == "ready" and (rsj.get("chunk_count") or 0) > 0, time.time() - t)

        t = time.time()
        r = await auth.post("/api/projects", json={"name": "react", "github_url": "https://github.com/react/react"})
        react_id = r.json().get("id") if r.status_code == 201 else (r.json().get("detail") or {}).get("existing_project_id")
        if r.status_code == 201 and react_id:
            temp_ids.append(react_id)
        if react_id:
            r = await auth.post(f"/api/projects/{react_id}/analyze")
            record("TC-16", "Analyze very large repository (react/react ~1 GB)", "400 repository_too_large with clear message",
                   f"{r.status_code} {detail_code(r)}", r.status_code == 400 and detail_code(r) == "repository_too_large", time.time() - t)

        t = time.time()
        r = await auth.post(f"/api/projects/{AXIOS_PROJECT}/chat", json={"message": "Where are the HTTP adapters implemented?"})
        c = r.json()
        files = sorted({s["file_path"] for s in c.get("sources") or []})
        record("TC-19", "Ask the Repository Assistant a code question", "200, grounded answer with cited source files",
               f"{r.status_code}, sources={len(files)} ({', '.join(files[:3])})",
               r.status_code == 200 and bool(c.get("answer")) and len(files) > 0, time.time() - t)

        t = time.time()
        r = await auth.post(f"/api/projects/{AXIOS_PROJECT}/chat", json={"message": ""})
        record("TC-20", "Send empty chat message", "422 validation error", f"{r.status_code}", r.status_code == 422, time.time() - t)

        t = time.time()
        r = await auth.post(f"/api/projects/{OTHER_USERS_PROJECT}/chat", json={"message": "hello"})
        record("TC-21", "Chat on another user's project", "403/404", f"{r.status_code}", r.status_code in (403, 404), time.time() - t)

        if spoon:
            t = time.time()
            r = await auth.delete(f"/api/projects/{spoon}")
            r2 = await auth.get(f"/api/projects/{spoon}")
            record("TC-22", "Delete own project", "204, then project returns 404",
                   f"{r.status_code}, then {r2.status_code}", r.status_code == 204 and r2.status_code == 404, time.time() - t)
            temp_ids.remove(spoon)

        t = time.time()
        r = await auth.post("/api/auth/logout")
        auth.cookies.clear()
        r2 = await httpx.AsyncClient(base_url=BASE, cookies={cookie_name: session}).get("/api/projects")
        record("TC-23", "Logout invalidates session", "Logout 200/204, old cookie then gets 401",
               f"logout {r.status_code}, reuse {r2.status_code}", r.status_code in (200, 204) and r2.status_code == 401, time.time() - t)
    finally:
        cleanup = httpx.AsyncClient(base_url=BASE, timeout=120, cookies={cookie_name: await create_session(db, OWNER, settings)})
        for pid in temp_ids:
            await cleanup.delete(f"/api/projects/{pid}")
        await db.sessions.delete_many({"user_id": OWNER, "session_id": {"$in": [session, cleanup.cookies.get(cookie_name)]}})
        await anon.aclose()
        await auth.aclose()
        await bad.aclose()
        await cleanup.aclose()
        await close_mongo()

    results.sort(key=lambda x: x["id"])
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(1 for x in results if x["status"] == "PASS")
    print(f"\n{passed}/{len(results)} passed")


asyncio.run(main())
