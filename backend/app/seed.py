"""Seed data.

Written to be worth looking at, not just to populate rows. The threads below
span the full range the scorer has to handle — a real investor, a recruiter, an
angry public review, a renewal at risk, and enough noise that the Signal Rail
has something to filter. A demo where everything is important teaches nothing.

    docker compose exec api python -m app.seed
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import structlog
from sqlalchemy import delete, select


from app.core.crypto import new_workspace_key, seal
from app.core.db import system_session
from app.models import (
    Automation, SourceAccount, Contact, ContactIdentity, InboundPayload, InboundObject,
    Signal, User, Workspace, WorkspaceMember,
)

log = structlog.get_logger()
NOW = datetime.now(UTC)

DEMO_EMAIL = "demo@tryvanta.social"

THREADS = [
    dict(
        kind="linkedin", sender="Marcus Feld", company="Alder Ventures",
        subject="Following your last two releases — 15 minutes?",
        body=("We've been tracking what you're shipping. We lead pre-seed at $1.5-3M "
              "and would want to move quickly if the timing is right. Are you raising "
              "in the next two quarters? Thursday or Friday morning works."),
        hours=3, category="investor", kind_opp="investment", opp=94, urg=78, value=2_000_000,
        summary="Pre-seed partner wants a call this week and is signalling a $1.5-3M lead.",
        actions=["Confirm whether you're raising", "Offer Thursday 10:00 IST", "Send the one-pager"],
    ),
    dict(
        kind="gmail", sender="Ananya Rao", company="Northwind Systems",
        subject="Staff engineer, platform — worth a conversation?",
        body=("Your work on distributed orchestration is exactly what the team is "
              "missing. Band is 48-62L plus equity, hybrid Hyderabad. Happy to skip "
              "the screen and go straight to the hiring manager."),
        hours=5, category="recruiter", kind_opp="job", opp=86, urg=64, value=62_000,
        summary="Recruiter offering to skip screening for a staff platform role.",
        actions=["Ask for the team's charter", "Confirm hybrid days", "Propose two slots"],
    ),
    dict(
        kind="google_business", sender="Priya Sethi", company=None,
        subject="2-star review",
        body=("Booked for 4pm, was seen at 4:40 with no update. Staff were kind but "
              "nobody told me anything. Won't rebook unless this changes."),
        hours=6, category="customer", kind_opp=None, opp=41, urg=96, value=None,
        summary="Two-star review about a 40-minute wait. Public, no reply yet.",
        actions=["Reply publicly within the hour", "Offer to rebook directly"],
    ),
    dict(
        kind="whatsapp", sender="Devansh Iyer", company="Meridian Group",
        subject="Renewal — need numbers before Friday's board",
        body=("Board meets Friday and I need the usage summary to defend the line "
              "item. Without it by Thursday noon I have to park the renewal."),
        hours=20, category="client", kind_opp="client_lead", opp=81, urg=92, value=48_000,
        summary="Renewal at risk. Needs a usage summary before Thursday noon.",
        actions=["Send usage summary by Thursday 12:00", "Include the retention delta"],
    ),
    dict(
        kind="gmail", sender="ICQCC Programme Office", company="Conference",
        subject="Invitation to speak — AI track, November",
        body=("We'd like to invite you to a 30-minute session on the applied AI "
              "track. Travel and accommodation covered. Confirm by 15 August."),
        hours=26, category="partnership", kind_opp="speaking", opp=74, urg=55, value=None,
        summary="Paid-travel speaking slot. Confirmation needed by 15 August.",
        actions=["Check the November calendar", "Confirm before 15 Aug"],
    ),
    dict(
        kind="telegram", sender="Halcyon Labs", company="Halcyon",
        subject="Reseller terms for the APAC region",
        body=("We'd take exclusive APAC reselling with a 25% margin and a 200-unit "
              "first order. Contract ready to move if the terms work."),
        hours=40, category="partnership", kind_opp="business", opp=79, urg=48, value=120_000,
        summary="Exclusive APAC reseller offer: 25% margin, 200-unit first order.",
        actions=["Model the margin at 200 units", "Push back on exclusivity"],
    ),
    dict(
        kind="slack", sender="Rhea Kulkarni", company="Internal",
        subject="Blocking: pricing page copy still in review",
        body="We can't ship the launch page without final pricing copy. Last open item.",
        hours=30, category="support", kind_opp=None, opp=22, urg=74, value=None,
        summary="Launch page blocked on pricing copy.",
        actions=["Review pricing copy today"],
    ),
    dict(
        kind="gmail", sender="Lyra Digest", company=None,
        subject="This week in growth: 11 tactics you're not using",
        body="Plus: why cohort retention is the only chart that matters.",
        hours=34, category="newsletter", kind_opp=None, opp=4, urg=2, value=None,
        summary="Weekly growth newsletter. Nothing needs a reply.",
        actions=[],
    ),
]

AUTOMATIONS = [
    dict(
        name="Recruiter reaches out",
        trigger={"event": "thread.scored", "filters": [
            {"field": "category", "op": "eq", "value": "recruiter"},
            {"field": "opportunity_score", "op": "gte", "value": 70},
        ]},
        actions=[{"type": "notify", "params": {"title": "Recruiter with a real role", "priority": "high"}},
                 {"type": "tag_contact", "params": {"tag": "Recruiter"}}],
    ),
    dict(
        name="Review drops below three stars",
        trigger={"event": "thread.scored", "filters": [
            {"field": "channel", "op": "eq", "value": "google_business"},
            {"field": "sentiment", "op": "eq", "value": "negative"},
        ]},
        actions=[{"type": "draft_reply", "params": {"tone": "support"}},
                 {"type": "notify", "params": {"title": "Negative review is public", "priority": "high"}}],
    ),
    dict(
        name="High-value thread never goes cold",
        trigger={"event": "thread.scored", "filters": [
            {"field": "opportunity_score", "op": "gte", "value": 75},
        ]},
        actions=[{"type": "set_followup", "params": {"days": 2}},
                 {"type": "boost_importance", "params": {"by": 20}}],
    ),
]


async def seed(reset: bool = True) -> None:
    async with system_session() as db:
        if reset:
            existing = await db.scalar(select(Workspace).where(Workspace.slug == "demo"))
            if existing:
                await db.execute(delete(Workspace).where(Workspace.id == existing.id))
                await db.flush()
                log.info("seed.reset")

        user = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(email=DEMO_EMAIL, full_name="Avishkar", timezone="Asia/Kolkata")
            db.add(user)
            await db.flush()

        data_key, wrapped = new_workspace_key()
        workspace = Workspace(
            name="Tryvanta", slug="demo", plan="pro", owner_id=user.id, wrapped_key=wrapped
        )
        db.add(workspace)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))

        accounts: dict[str, SourceAccount] = {}
        for kind in {t["kind"] for t in THREADS}:
            account = SourceAccount(
                workspace_id=workspace.id, source_kind=kind,
                external_id=f"demo-{kind}", display_name=f"Demo {kind}",
                status="connected", last_synced_at=NOW,
            )
            db.add(account)
            await db.flush()
            accounts[kind] = account

        for spec in THREADS:
            sent = NOW - timedelta(hours=spec["hours"])
            contact = Contact(
                workspace_id=workspace.id,
                display_name=spec["sender"],
                company=spec["company"],
                last_interaction_at=sent,
                importance=60 if spec["opp"] > 70 else 40,
                relationship_strength=min(spec["opp"], 90),
            )
            db.add(contact)
            await db.flush()
            db.add(ContactIdentity(
                contact_id=contact.id, source_kind=spec["kind"],
                handle=f"{spec['sender'].lower().replace(' ', '.')}@{spec['kind']}",
            ))

            obj = InboundObject(
                workspace_id=workspace.id,
                source_account_id=accounts[spec["kind"]].id,
                contact_id=contact.id,
                external_id=str(uuid4()),
                object_kind="message",
                title=spec["subject"],
                snippet=spec["body"][:200],
                is_unread=spec["hours"] < 24,
                state="open",
            )
            db.add(obj)
            await db.flush()

            db.add(InboundPayload(
                workspace_id=workspace.id, object_id=obj.id, external_id=str(uuid4()),
                direction="inbound", actor_name=spec["sender"],
                body_enc=seal(spec["body"], data_key, aad=str(obj.id)),
                sent_at=sent,
            ))
            db.add(Signal(
                workspace_id=workspace.id, object_id=obj.id, object_kind=obj.object_kind,
                category=spec["category"], urgency=spec["urg"],
                opportunity_score=spec["opp"], opportunity_kind=spec["kind_opp"],
                estimated_value_usd=spec["value"], summary=spec["summary"],
                action_items=spec["actions"],
                sentiment="negative" if spec["opp"] < 45 and spec["urg"] > 80 else "positive",
                language="en", model="seed", prompt_version="seed-1",
            ))

        for rule in AUTOMATIONS:
            db.add(Automation(workspace_id=workspace.id, enabled=True, **rule))

    log.info("seed.done", threads=len(THREADS), automations=len(AUTOMATIONS))
    print(f"\n  Seeded {len(THREADS)} threads across "
          f"{len({t['kind'] for t in THREADS})} channels.")
    print(f"  Sign in as {DEMO_EMAIL}\n")


if __name__ == "__main__":
    asyncio.run(seed())
