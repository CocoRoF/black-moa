import { Suspense } from "react";
import { AgentInbox } from "@/components/agent/AgentInbox";
export default function Page() { return <Suspense fallback={null}><AgentInbox /></Suspense>; }
