"""Visitor-retention boundary.

Conversation retention is treated as relationship retention: expired visitor
threads must not leave PII copies in inbox/notification payloads, pending network
proposals, visitor facts or the filesystem-backed visitor memory namespace.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memora.core import pools
from memora.memory.facade import namespace_root
from memora.memory.synapse import index_cache
from memora.models import Agent, Visitor
from memora.services import jobs as J
from memora.services import settings as S


async def purge_visitor_memory(agent_id: uuid.UUID, visitor_id: uuid.UUID) -> int:
    root = namespace_root(agent_id, "visitors")
    if not root.exists():
        return 0
    idx = await index_cache.get(root)
    notes = await pools.to_thread("docs", lambda: list(idx.notes.iter_all()))
    tag = f"visitor:{visitor_id}"
    matched = [
        note.id
        for note in notes
        if str((note.meta or {}).get("visitor_id") or "") == str(visitor_id) or tag in (note.tags or [])
    ]
    for note_id in matched:
        await pools.to_thread("docs", idx.notes.delete, note_id)
        await pools.to_thread("docs", idx.remove, note_id)
    return len(matched)


async def retention_purge_memory(_db: AsyncSession, payload: dict) -> dict:
    agent_id = uuid.UUID(payload["agent_id"])
    visitor_id = uuid.UUID(payload["visitor_id"])
    return {"memory_notes_deleted": await purge_visitor_memory(agent_id, visitor_id)}


async def _purge_expired_thread_derivatives(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    agent_id: uuid.UUID,
    cutoff: datetime,
) -> None:
    params = {"owner": owner_id, "agent": agent_id, "cutoff": cutoff}
    expired_uuid = """
        SELECT id FROM conversations
        WHERE owner_id=:owner AND agent_id=:agent AND audience='visitor'
          AND coalesce(last_message_at, created_at) < :cutoff
    """
    expired_text = """
        SELECT id::text FROM conversations
        WHERE owner_id=:owner AND agent_id=:agent AND audience='visitor'
          AND coalesce(last_message_at, created_at) < :cutoff
    """

    # Notification payloads are denormalized copies of inbox/thread data, so
    # remove those copies before their FK references can be SET NULL/cascaded.
    await db.execute(text(f"""
        DELETE FROM notifications n
        WHERE n.owner_id=:owner AND (
          n.payload->>'conversation_id' IN ({expired_text})
          OR n.payload->>'inbox_item_id' IN (
            SELECT i.id::text FROM inbox_items i WHERE i.conversation_id IN ({expired_uuid})
          )
        )
    """), params)
    await db.execute(text(f"""
        DELETE FROM inbox_items WHERE owner_id=:owner AND conversation_id IN ({expired_uuid})
    """), params)

    # A visitor proposal is not owner data until the owner approves it. Pending
    # proposals sourced from an expired thread therefore expire with the thread.
    await db.execute(text("""
        DELETE FROM network_proposals p
        USING turns t, conversations c
        WHERE p.source_turn_id=t.id AND t.conversation_id=c.id
          AND c.owner_id=:owner AND c.agent_id=:agent AND c.audience='visitor'
          AND coalesce(c.last_message_at, c.created_at) < :cutoff
          AND p.status='pending'
    """), params)
    # Approved/rejected proposals may remain as owner decisions, but the
    # dangling visitor-turn correlation is no longer needed.
    await db.execute(text("""
        UPDATE network_proposals p SET source_turn_id=NULL
        FROM turns t, conversations c
        WHERE p.source_turn_id=t.id AND t.conversation_id=c.id
          AND c.owner_id=:owner AND c.agent_id=:agent AND c.audience='visitor'
          AND coalesce(c.last_message_at, c.created_at) < :cutoff
          AND p.status<>'pending'
    """), params)


# One pass stays bounded so a large backlog cannot exceed the worker job
# timeout. The sweep is idempotent and scheduled every 6h, so the remainder is
# picked up on the next run.
MAX_VISITORS_PER_SWEEP = 500
NEEDLE_CHUNK = 100


async def _delete_jobs_referencing(db: AsyncSession, needles: list[str]) -> None:
    """Drop queued/finished job payloads that still embed purged identifiers.

    One set-based statement per chunk instead of a full ``jobs`` scan per
    visitor and per inbox item (that was O(visitors x inbox_items) sequential
    scans on every sweep). The freshly queued ``retention.purge_memory`` jobs
    carry the same visitor id on purpose and are excluded.
    """
    for i in range(0, len(needles), NEEDLE_CHUNK):
        chunk = [f"%{n}%" for n in needles[i:i + NEEDLE_CHUNK]]
        await db.execute(text("""
            DELETE FROM jobs
            WHERE kind <> 'retention.purge_memory' AND payload::text LIKE ANY(:needles)
        """), {"needles": chunk})


async def retention_sweep(db: AsyncSession, _payload: dict) -> dict:
    agents = (await db.execute(select(Agent))).scalars().all()
    conversations_deleted = 0
    visitors_deleted = 0
    memory_purges_queued = 0
    purge_needles: list[str] = []
    now = datetime.now(UTC)

    for agent in agents:
        days = int(
            (agent.visitor_settings or {}).get("retention_days")
            or await S.get(db, "public.default_retention_days")
            or 90
        )
        cutoff = now - timedelta(days=max(1, days))
        await _purge_expired_thread_derivatives(
            db,
            owner_id=agent.owner_id,
            agent_id=agent.id,
            cutoff=cutoff,
        )
        result = await db.execute(text("""
            DELETE FROM conversations
            WHERE owner_id=:owner AND agent_id=:agent AND audience='visitor'
              AND coalesce(last_message_at, created_at) < :cutoff
        """), {"owner": agent.owner_id, "agent": agent.id, "cutoff": cutoff})
        conversations_deleted += int(result.rowcount or 0)
        # 방문자가 건넨 파일도 같은 보존 기간을 따른다 (plan/55 §6-3). 지운 것으로 적되
        # 30일 보관(주인이 지운 파일의 규칙)을 이미 지난 것으로 적어 다음 정리에 바이트까지 간다.
        await db.execute(text("""
            UPDATE agent_files SET deleted_at = :gone
             WHERE agent_id=:agent AND scope='visitor' AND deleted_at IS NULL AND created_at < :cutoff
        """), {"agent": agent.id, "cutoff": cutoff, "gone": now - timedelta(days=31)})

        stale_ids = [
            row[0]
            for row in (await db.execute(text("""
                SELECT v.id FROM visitors v
                WHERE v.owner_id=:owner AND v.agent_id=:agent AND v.last_seen_at < :cutoff
                  AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.visitor_id=v.id)
                ORDER BY v.last_seen_at
                LIMIT :limit
            """), {"owner": agent.owner_id, "agent": agent.id, "cutoff": cutoff,
                   "limit": max(0, MAX_VISITORS_PER_SWEEP - visitors_deleted)})).all()
        ]
        for visitor_id in stale_ids:
            visitor = await db.get(Visitor, visitor_id)
            if visitor is None:
                continue
            vid = str(visitor.id)
            inbox_ids = [
                str(row[0])
                for row in (await db.execute(
                    text("SELECT id FROM inbox_items WHERE owner_id=:owner AND visitor_id=:visitor"),
                    {"owner": agent.owner_id, "visitor": visitor.id},
                )).all()
            ]
            await db.execute(text("""
                DELETE FROM notifications
                WHERE owner_id=:owner AND payload->>'visitor_id'=:visitor
            """), {"owner": agent.owner_id, "visitor": vid})
            for inbox_id in inbox_ids:
                await db.execute(text("""
                    DELETE FROM notifications
                    WHERE owner_id=:owner AND payload->>'inbox_item_id'=:inbox
                """), {"owner": agent.owner_id, "inbox": inbox_id})

            await db.execute(text("DELETE FROM inbox_items WHERE owner_id=:owner AND visitor_id=:visitor"),
                             {"owner": agent.owner_id, "visitor": visitor.id})
            await db.execute(text("DELETE FROM facts WHERE owner_id=:owner AND visitor_id=:visitor"),
                             {"owner": agent.owner_id, "visitor": visitor.id})
            await db.execute(text("""
                DELETE FROM network_proposals
                WHERE owner_id=:owner AND agent_id=:agent AND status='pending'
                  AND payload::text LIKE :needle
            """), {"owner": agent.owner_id, "agent": agent.id, "needle": f"%{vid}%"})
            # Old queued/done jobs can otherwise retain UUID-addressable copies of
            # visitor/inbox payloads outside the conversational FK graph. Collected
            # here and deleted in one batched statement after the agent loop.
            purge_needles.append(vid)
            purge_needles.extend(inbox_ids)

            await J.enqueue(
                db,
                "retention.purge_memory",
                {"agent_id": str(agent.id), "visitor_id": vid},
                priority=8,
                dedupe_key=f"retention-memory:{visitor.id}",
                max_attempts=3,
            )
            memory_purges_queued += 1
            await db.delete(visitor)
            visitors_deleted += 1
        if visitors_deleted >= MAX_VISITORS_PER_SWEEP:
            break

    if purge_needles:
        await db.flush()
        await _delete_jobs_referencing(db, purge_needles)

    # A visitor may keep its row (recent last_seen_at) while every conversation
    # it appeared in has expired. The private facts derived from those threads
    # expire with them.
    await db.execute(text("""
        DELETE FROM facts WHERE visibility='visitor_private' AND visitor_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.visitor_id = facts.visitor_id)
    """))

    # Conversation/turn FKs cascade, while these journal tables intentionally
    # do not have FKs for write throughput.
    await db.execute(text("DELETE FROM turn_events WHERE NOT EXISTS (SELECT 1 FROM turns t WHERE t.id=turn_events.turn_id)"))
    await db.execute(text("DELETE FROM tool_spans WHERE NOT EXISTS (SELECT 1 FROM turns t WHERE t.id=tool_spans.turn_id)"))
    await db.execute(text("DELETE FROM turn_events WHERE type='text.delta' AND at < now() - interval '30 days'"))
    await db.execute(text("DELETE FROM jobs WHERE status IN ('done','dead') AND finished_at < now() - interval '14 days'"))
    # One heartbeat row per container id, and nothing ever removed them, so every restart
    # since the install left a headstone in the worker list.
    hb = await db.execute(text("DELETE FROM worker_heartbeats WHERE last_seen_at < now() - interval '7 days'"))
    # Refresh tokens rotate, so every refresh leaves a revoked row behind. Nothing removed
    # them and the table was the second largest in the database. Revoked rows are kept long
    # enough to still catch a replayed token, expired ones until they are well past use.
    sess = await db.execute(text("""
        DELETE FROM auth_sessions
        WHERE (revoked_at IS NOT NULL AND revoked_at < now() - interval '7 days')
           OR expires_at < now() - interval '7 days'
    """))
    # 감사 기록(로그인·가입·동의·관리자 조회 등, IP·단말 정보 포함)은 1년 (plan/73, 개인정보 처리방침 3절).
    # 통신비밀보호법의 로그인 기록 3개월, 개인정보의 안전성 확보조치 기준의 접속기록 1년을 넘겨 두고, 그 뒤에는 지운다.
    audit = await db.execute(text("DELETE FROM audit_logs WHERE created_at < now() - interval '1 year'"))
    # 읽어 주기 소리(TTS)는 같은 글을 다시 읽을 때를 위한 것이다. 30일이 지나면 지운다(처리방침 3절).
    tts_deleted = await pools.to_thread("misc", _purge_tts_cache, 30, label="tts-purge")
    # 아무 데도 붙지 않은 업로드(글칸에 올렸다 뺀 것, 지운 비서가 받았던 것)를 거둔다 (plan/55).
    from memora.services import files as FILES
    orphans = await FILES.purge_orphans(db)
    return {
        "audit_logs_deleted": int(audit.rowcount or 0),
        "tts_cache_deleted": tts_deleted,
        "orphan_uploads_deleted": orphans,
        "worker_heartbeats_deleted": int(hb.rowcount or 0),
        "auth_sessions_deleted": int(sess.rowcount or 0),
        "conversations_deleted": conversations_deleted,
        "visitors_deleted": visitors_deleted,
        "memory_purges_queued": memory_purges_queued,
    }


def _purge_tts_cache(days: int) -> int:
    """읽어 주기 소리 파일 중 ``days`` 일 넘게 지난 것을 지운다."""
    import time

    from memora.config import get_settings

    root = get_settings().cache_root / "tts"
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for f in root.glob("*/*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            continue
    return n
