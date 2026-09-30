import { Suspense } from "react";
import { InboxPage } from "@/components/owner/InboxView";
export default function Page() { return <Suspense fallback={null}><InboxPage /></Suspense>; }
