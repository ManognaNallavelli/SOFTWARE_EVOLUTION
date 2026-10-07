"""Verify Phase 3 architecture UX-support + richer deterministic graphs."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pymongo import ReturnDocument

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.architecture.deterministic import build_deterministic_architecture
from app.architecture.prompt_builder import build_architecture_brief, build_gemini_prompt
from app.architecture.validator import validate_architecture_graph
from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo, get_db
from app.schemas.analysis import RepositoryAnalysisPayload
from app.services.session_service import create_session


async def seed_user(google_sub: str, email: str, name: str) -> str:
    db = get_db()
    now = datetime.now(timezone.utc)
    result = await db.users.find_one_and_update(
        {"google_sub": google_sub},
        {
            "$set": {"email": email, "name": name, "picture": None, "updated_at": now},
            "$setOnInsert": {"google_sub": google_sub, "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    assert result is not None
    return str(result["_id"])


def _assert_graph_supported(graph: dict, analysis: dict) -> None:
    node_ids = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
    # No empty evidence on nodes
    for node in graph["nodes"]:
        assert node.get("evidence") or node.get("file_paths"), node


async def run() -> None:
    settings = get_settings()
    await connect_mongo()
    db = get_db()
    cookie = settings.session_cookie_name
    user = await seed_user("arch-refine-a", "arch-refine@example.com", "Arch Refine")
    session = await create_session(db, user, settings)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=300.0) as client:
        print("== Create project without analysis ==")
        await db.projects.delete_many({"owner_user_id": user, "github_full_name": "pypa/sampleproject"})
        await db.architectures.delete_many({"owner_user_id": user})
        r = await client.post(
            "/api/projects",
            json={
                "name": "Arch Refine Sample",
                "github_url": "https://github.com/pypa/sampleproject",
                "technologies": ["Python"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        project = r.json()
        pid = project["id"]

        print("== Generate without analysis => 409 analysis_required ==")
        r = await client.post(
            f"/api/projects/{pid}/architecture/generate?deterministic=true",
            cookies={cookie: session},
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "analysis_required"

        print("== Frontend-equivalent: analyze then generate ==")
        r = await client.post(f"/api/projects/{pid}/analyze", cookies={cookie: session})
        assert r.status_code == 200, r.text
        analyzed = r.json()
        assert analyzed["status"] == "completed"
        analyzed_at = analyzed.get("analyzed_at")

        r = await client.post(
            f"/api/projects/{pid}/architecture/generate?deterministic=true",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert body["source"] == "deterministic"
        assert body["gemini_model"] in (None, "")
        assert body["graph"] is not None
        assert len(body["graph"]["nodes"]) >= 2
        # Prefer meaningful edge types when available
        edge_types = {e["type"] for e in body["graph"]["edges"]}
        assert "contains" not in edge_types or len(edge_types) > 1 or len(body["graph"]["edges"]) == 0
        _assert_graph_supported(body["graph"], analyzed["analysis"])
        print(
            "OK sample nodes",
            len(body["graph"]["nodes"]),
            "edges",
            len(body["graph"]["edges"]),
            "types",
            sorted(edge_types),
        )

        print("== Existing analysis: regenerate does not require re-analyze ==")
        r = await client.post(
            f"/api/projects/{pid}/architecture/generate?deterministic=true",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        regen = r.json()
        assert regen["version"] >= body["version"]
        # analysis timestamp should still be the completed one
        assert regen.get("analyzed_at") is not None

        print("== GET loads existing architecture ==")
        r = await client.get(f"/api/projects/{pid}/architecture", cookies={cookie: session})
        assert r.status_code == 200, r.text
        stored = r.json()
        assert stored["graph"] is not None
        assert stored["status"] == "completed"

        print("== Flask richer deterministic graph ==")
        await db.projects.delete_many({"owner_user_id": user, "github_full_name": "pallets/flask"})
        r = await client.post(
            "/api/projects",
            json={
                "name": "Flask Arch",
                "github_url": "https://github.com/pallets/flask",
                "technologies": ["Python"],
            },
            cookies={cookie: session},
        )
        assert r.status_code == 201, r.text
        flask_id = r.json()["id"]
        r = await client.post(f"/api/projects/{flask_id}/analyze", cookies={cookie: session})
        assert r.status_code == 200, r.text
        flask_analysis = r.json()["analysis"]
        assert flask_analysis is not None

        # Offline unit check of richer builder
        payload = RepositoryAnalysisPayload.model_validate(flask_analysis)
        brief = build_architecture_brief(payload)
        assert "packages" in brief and len(brief["packages"]) >= 1
        assert "guidance" in brief
        prompt = build_gemini_prompt(brief)
        assert "Do NOT invent" in prompt
        assert "Prefer meaningful architectural relationships" in prompt or "prefer meaningful" in prompt.lower()

        raw = build_deterministic_architecture(payload)
        graph = validate_architecture_graph(raw, payload)
        assert len(graph.nodes) >= 4, graph.model_dump()
        meaningful = {e.type for e in graph.edges}
        assert meaningful & {"imports", "uses", "depends_on", "exposes", "calls", "stores"}
        # Should not be only repo→contains→folder
        contains_only = meaningful <= {"contains"} and len(graph.edges) > 0
        assert not contains_only, meaningful
        print("OK flask nodes", len(graph.nodes), "edges", len(graph.edges), "types", sorted(meaningful))

        r = await client.post(
            f"/api/projects/{flask_id}/architecture/generate?deterministic=true",
            cookies={cookie: session},
        )
        assert r.status_code == 200, r.text
        flask_arch = r.json()
        assert flask_arch["source"] == "deterministic"
        assert len(flask_arch["graph"]["nodes"]) >= 4

        print("== Ownership isolation ==")
        other = await seed_user("arch-refine-b", "arch-refine-b@example.com", "Arch B")
        other_session = await create_session(db, other, settings)
        r = await client.get(f"/api/projects/{pid}/architecture", cookies={cookie: other_session})
        assert r.status_code in {403, 404}, r.text

        if settings.gemini_api_key.strip():
            print("== Real Gemini path ==")
            r = await client.post(
                f"/api/projects/{pid}/architecture/generate",
                cookies={cookie: session},
            )
            assert r.status_code == 200, r.text
            gem = r.json()
            assert gem["status"] == "completed"
            assert gem["graph"] is not None
            print("OK gemini source", gem["source"], "model", gem.get("gemini_model"), "nodes", len(gem["graph"]["nodes"]))
            if gem["source"] != "gemini":
                print("NOTE: Gemini path fell back to deterministic; check API availability.")
            else:
                assert gem.get("gemini_model")
                _assert_graph_supported(gem["graph"], analyzed["analysis"])
        else:
            print("== Skip Gemini (GEMINI_API_KEY empty) ==")

        await client.delete(f"/api/projects/{pid}", cookies={cookie: session})
        await client.delete(f"/api/projects/{flask_id}", cookies={cookie: session})
        print("Phase 3 refinement verification passed.")
        _ = analyzed_at

    await close_mongo()


if __name__ == "__main__":
    asyncio.run(run())
