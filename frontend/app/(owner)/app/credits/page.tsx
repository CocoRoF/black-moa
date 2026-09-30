import { Suspense } from "react";
import { CreditsPage } from "@/components/owner/CreditsView";
export default function Page() { return <Suspense fallback={null}><CreditsPage /></Suspense>; }
