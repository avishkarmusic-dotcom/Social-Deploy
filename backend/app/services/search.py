"""Global search: lexical and semantic, fused.

Neither half is sufficient alone. Full-text finds "Q3 invoice" when the user
types those exact words and misses "the bill from last quarter". Embeddings do
the opposite — they find the paraphrase and then confidently rank a vaguely
similar message above the literal one. So both run, and the results are merged
with reciprocal rank fusion.

RRF over score normalisation on purpose: tsvector ranks and cosine distances
live on incomparable scales, and any attempt to normalise them into one number
ends up encoding an arbitrary opinion about how much a semantic match is worth.
RRF only uses *position*, which is the one thing both lists agree on the
meaning of.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, ContentPiece, InboundPayload, InboundObject, Signal

K = 60          # RRF damping. 60 is the value the original paper landed on and
                # it holds up: small enough that rank 1 matters, large enough
                # that rank 8 still contributes.


@dataclass
class Hit:
    kind: str               # thread | contact | content
    id: str
    title: str
    snippet: str
    score: float
    extra: dict[str, Any]


async def search(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    embedding: list[float] | None = None,
    limit: int = 20,
) -> list[Hit]:
    lexical = await _lexical_threads(db, workspace_id, query, limit * 2)
    semantic = await _semantic_threads(db, workspace_id, embedding, limit * 2) if embedding else []

    fused: dict[str, float] = {}
    payload: dict[str, tuple] = {}
    for ranking in (lexical, semantic):
        for position, row in enumerate(ranking):
            key = str(row[0])
            fused[key] = fused.get(key, 0.0) + 1.0 / (K + position + 1)
            payload.setdefault(key, row)

    hits = [
        Hit(
            kind="thread",
            id=key,
            title=payload[key][1] or "(no subject)",
            snippet=payload[key][2] or "",
            score=round(score, 5),
            extra={"channel": payload[key][3], "last_activity_at": payload[key][4]},
        )
        for key, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    ][:limit]

    # People and drafts are matched by name only — nobody searches a contact by
    # paraphrase, and a fuzzy person match is worse than none.
    hits += await _contacts(db, workspace_id, query, 5)
    hits += await _content(db, workspace_id, query, 5)
    return hits


async def _lexical_threads(db, workspace_id, query, limit):
    tsquery = func.websearch_to_tsquery("english", query)
    stmt = (
        select(
            InboundObject.id,
            InboundObject.subject,
            InboundObject.snippet,
            InboundObject.account_id,
            InboundObject.last_activity_at,
            func.ts_rank(InboundPayload.search_tsv, tsquery).label("rank"),
        )
        .join(InboundPayload, InboundPayload.thread_id == InboundObject.id)
        .where(InboundObject.workspace_id == workspace_id, InboundPayload.search_tsv.op("@@")(tsquery))
        .order_by(text("rank DESC"))
        .limit(limit)
    )
    return list(await db.execute(stmt))


async def _semantic_threads(db, workspace_id, embedding, limit):
    """Cosine distance over the HNSW index. `<=>` is pgvector's operator; the
    index only engages when the ORDER BY uses it directly."""
    stmt = (
        select(
            InboundObject.id,
            InboundObject.subject,
            InboundObject.snippet,
            InboundObject.account_id,
            InboundObject.last_activity_at,
        )
        .join(InboundPayload, InboundPayload.thread_id == InboundObject.id)
        .where(InboundObject.workspace_id == workspace_id, InboundPayload.embedding.isnot(None))
        .order_by(InboundPayload.embedding.cosine_distance(embedding))
        .limit(limit)
    )
    return list(await db.execute(stmt))


async def _contacts(db, workspace_id, query, limit) -> list[Hit]:
    rows = await db.execute(
        select(Contact.id, Contact.display_name, Contact.company, Contact.relationship_strength)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.display_name.op("%")(query),   # pg_trgm similarity
        )
        .order_by(func.similarity(Contact.display_name, query).desc())
        .limit(limit)
    )
    return [
        Hit(
            kind="contact", id=str(cid), title=name, snippet=company or "",
            score=0.5, extra={"strength": strength},
        )
        for cid, name, company, strength in rows
    ]


async def _content(db, workspace_id, query, limit) -> list[Hit]:
    rows = await db.execute(
        select(ContentPiece.id, ContentPiece.title, ContentPiece.body, ContentPiece.status)
        .where(
            ContentPiece.workspace_id == workspace_id,
            ContentPiece.body.ilike(f"%{query}%"),
        )
        .limit(limit)
    )
    return [
        Hit(
            kind="content", id=str(cid), title=title or body[:60],
            snippet=body[:200], score=0.4, extra={"status": status},
        )
        for cid, title, body, status in rows
    ]
