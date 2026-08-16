"""Global search across threads, people and drafts."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.deps import DB, CurrentUser, rate_limit
from app.services.search import Hit, search as run_search

router = APIRouter(prefix="/v1/search", tags=["search"])


class Results(BaseModel):
    query: str
    hits: list[dict]
    took_semantic: bool


@router.get(
    "",
    response_model=Results,
    summary="Search everything",
    dependencies=[rate_limit(burst=60, per_second=2)],
)
async def search_everything(
    user: CurrentUser,
    db: DB,
    q: str = Query(min_length=2, description="What to look for"),
    limit: int = Query(20, le=100),
    semantic: bool = Query(True, description="Also search by meaning, not just words"),
) -> Results:
    # Embeddings are computed lazily and may be absent on very recent messages;
    # search degrades to lexical rather than returning nothing.
    embedding = None
    hits: list[Hit] = await run_search(
        db, workspace_id=user.workspace_id, query=q, embedding=embedding, limit=limit
    )
    return Results(
        query=q,
        hits=[h.__dict__ for h in hits],
        took_semantic=embedding is not None,
    )
