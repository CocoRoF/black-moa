from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from memora.db.session import session_scope
from memora.memory.facade import AgentMemory
from memora.models import Agent, Conversation, InboxItem, Notification, Visitor
from memora.services.extract import extract
from memora.services.retention import retention_purge_memory, retention_sweep
from tests.conftest import signup


def test_real_parser_child_extracts_html():
    result = extract(
        b"<html><head><title>Sandbox</title></head><body><h1>Hello</h1><p>isolated parser</p></body></html>",
        "text/html; charset=utf-8",
        "sample.html",
    )
    assert "Hello" in result.text
    assert "isolated parser" in result.text


@pytest.mark.asyncio
async def test_full_retention_purges_visitor_identity_and_filesystem_memory(client):
    user, _ = await signup(client)
    owner_id = uuid.UUID(user["id"])
    old = datetime.now(UTC) - timedelta(days=45)

    async with session_scope() as db:
        agent = Agent(
            owner_id=owner_id,
            name="Full Retention Test",
            provider="fake",
            model_id="fake-1",
            visitor_settings={"retention_days": 30},
        )
        db.add(agent)
        await db.flush()
        visitor = Visitor(
            owner_id=owner_id,
            agent_id=agent.id,
            token_hash=f"purge-{uuid.uuid4().hex}",
            display_name="Delete Me",
            email="delete-me@example.com",
            note="visitor note",
            ip_hash="cafebabe",
            first_seen_at=old,
            last_seen_at=old,
            meta={"ua": "retained-pii"},
        )
        db.add(visitor)
        await db.flush()
        conversation = Conversation(
            owner_id=owner_id,
            agent_id=agent.id,
            audience="visitor",
            visitor_id=visitor.id,
            title="expired relationship",
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
            payload={"email": visitor.email, "text": "delete this copy"},
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
                "email": visitor.email,
            },
            status="pending",
            created_at=old,
        )
        db.add(notification)
        await db.flush()
        agent_id = agent.id
        visitor_id = visitor.id
        conversation_id = conversation.id
        inbox_id = inbox.id
        notification_id = notification.id

    memory = AgentMemory(agent_id, "visitor", visitor_id)
    note = await memory.remember(
        title="Visitor private memory",
        body="delete-me@example.com",
        category="visitor",
    )
    assert await memory.read("visitors", note.id) is not None

    async with session_scope() as db:
        result = await retention_sweep(db, {})
        assert result["conversations_deleted"] >= 1
        assert result["visitors_deleted"] >= 1

    async with session_scope() as db:
        assert await db.scalar(select(Conversation.id).where(Conversation.id == conversation_id)) is None
        assert await db.scalar(select(InboxItem.id).where(InboxItem.id == inbox_id)) is None
        assert await db.scalar(select(Notification.id).where(Notification.id == notification_id)) is None
        assert await db.scalar(select(Visitor.id).where(Visitor.id == visitor_id)) is None

    # In production this payload is executed by the queued worker handler. Run
    # the handler explicitly here so the test covers the filesystem/index half
    # of the same retention lifecycle without needing a second worker process.
    async with session_scope() as db:
        purged = await retention_purge_memory(
            db,
            {"agent_id": str(agent_id), "visitor_id": str(visitor_id)},
        )
    assert purged["memory_notes_deleted"] >= 1
    assert await memory.read("visitors", note.id) is None

    # Give background filesystem/index operations a scheduling point before the
    # shared test lifespan proceeds to the next case.
    await asyncio.sleep(0)
