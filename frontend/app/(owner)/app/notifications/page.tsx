import { Suspense } from "react";
import { NotificationsPage } from "@/components/owner/NotificationsView";
export default function Page() { return <Suspense fallback={null}><NotificationsPage /></Suspense>; }
