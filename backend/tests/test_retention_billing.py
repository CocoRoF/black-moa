from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from memora.db.session import session_scope
from memora.models import Agent, Conversation, InboxItem, Notification, User, Visitor
from memora.services import credits as CR
from memora.services.retention import _purge_expired_thread_derivatives
from tests.conftest import signup


@pytest.mark.asyncio
async def test_retention_removes_notification_and_inbox_copies_for_expired_thread(client):
    user, _ = await signup(client)
    owner_id = uuid.UUID(user["id"])
    old = datetime.now(UTC) - timedelta(days=120)

    async with session_scope() as db:
        agent = Agent(
            owner_id=owner_id,
            name="Retention Test",
            provider="fake",
            model_id="fake-1",
            visitor_settings={"retention_days": 90},
        )
        db.add(agent)
        await db.flush()
        visitor = Visitor(
            owner_id=owner_id,
            agent_id=agent.id,
            token_hash=f"retention-{uuid.uuid4().hex}",
            display_name="Expired Visitor",
            email="expired@example.com",
            ip_hash="deadbeef",
            first_seen_at=old,
            last_seen_at=old,
            meta={"ua": "old-browser"},
        )
        db.add(visitor)
        await db.flush()
        conversation = Conversation(
            owner_id=owner_id,
            agent_id=agent.id,
            audience="visitor",
            visitor_id=visitor.id,
            title="expired",
            last_message_at=old,
        )
        db.add(conversation)
        await db.flush()
        inbox = InboxItem(
            owner_id=owner_id,
            agent_id=agent.id,
            conversation_id=conversation.id,
            visitor_id=visitor.id,
            kind="visitor_message",
            payload={"text": "PII copy"},
        )
        db.add(inbox)
        await db.flush()
        notification = Notification(
            owner_id=owner_id,
            event="visitor_message",
            payload={
                "conversation_id": str(conversation.id),
                "inbox_item_id": str(inbox.id),
                "visitor_id": str(visitor.id),
                "text": "PII copy",
            },
            channel_id=None,
            status="pending",
            created_at=old,
        )
        db.add(notification)
        await db.flush()
        ids = (agent.id, conversation.id, inbox.id, notification.id)

    async with session_scope() as db:
        await _purge_expired_thread_derivatives(
            db,
            owner_id=owner_id,
            agent_id=ids[0],
            cutoff=datetime.now(UTC) - timedelta(days=90),
        )

    async with session_scope() as db:
        assert await db.scalar(select(Conversation.id).where(Conversation.id == ids[1])) == ids[1]
        assert await db.scalar(select(InboxItem.id).where(InboxItem.id == ids[2])) is None
        assert await db.scalar(select(Notification.id).where(Notification.id == ids[3])) is None


@pytest.mark.asyncio
async def test_usage_day_uses_owner_timezone(client):
    user, _ = await signup(client)
    owner_id = uuid.UUID(user["id"])
    instant = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)

    async with session_scope() as db:
        owner = await db.get(User, owner_id)
        assert owner is not None
        owner.timezone = "America/Los_Angeles"

    async with session_scope() as db:
        assert await CR.usage_day(db, owner_id, now=instant) == date(2025, 12, 31)

    async with session_scope() as db:
        owner = await db.get(User, owner_id)
        assert owner is not None
        owner.timezone = "Asia/Seoul"

    async with session_scope() as db:
        assert await CR.usage_day(db, owner_id, now=instant) == date(2026, 1, 1)
