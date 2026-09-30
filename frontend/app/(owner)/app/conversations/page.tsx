import { Suspense } from "react";
import { ConversationsPage } from "@/components/owner/Conversations";
export default function Page() { return <Suspense fallback={null}><ConversationsPage /></Suspense>; }
