"use client";
import { InboxView } from "@/components/owner/InboxView";
import { useAgent } from "./AgentLayout";
export function AgentInbox() { const a = useAgent(); return <InboxView agentId={a.id} />; }
