import { Suspense } from "react";
import { IntegrationsPage } from "@/components/owner/IntegrationsView";
export default function Page() { return <Suspense fallback={null}><IntegrationsPage /></Suspense>; }
