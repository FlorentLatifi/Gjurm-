"""The frontend's API types are generated from a committed copy of this API's OpenAPI schema
(frontend/src/shared/api/openapi.json) and type-checked against the app's own types. This test
keeps that copy honest: any change to a response model fails here until the copy is regenerated.

    cd backend && uv run gjurme openapi --out ../frontend/src/shared/api/openapi.json
    cd ../frontend && npm run api:types && npm run typecheck
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from gjurme.api.app import create_app
from gjurme.config import Settings

REPO = Path(__file__).resolve().parents[3]
SNAPSHOT = REPO / "frontend" / "src" / "shared" / "api" / "openapi.json"


def _contract(doc: dict[str, object]) -> dict[str, object]:
    # info (version, contact URL) depends on the environment; paths and schemas are the contract
    return {"paths": doc["paths"], "components": doc["components"]}


def test_committed_openapi_schema_matches_the_api(settings: Settings) -> None:
    live = create_app(settings, sessionmaker()).openapi()
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert _contract(committed) == _contract(live), (
        "The API changed: regenerate frontend/src/shared/api/openapi.json and the frontend types "
        "(see this test's docstring)."
    )


def test_response_fields_with_defaults_are_declared_required(settings: Settings) -> None:
    schemas = create_app(settings, sessionmaker()).openapi()["components"]["schemas"]
    assert "analysis_method" in schemas["ArticleDetail"]["required"]
    assert schemas["StoryArticle"]["properties"]["sentiment_label"]["anyOf"][0]["enum"] == [
        "negative",
        "neutral",
        "positive",
    ]
