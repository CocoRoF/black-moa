import { Suspense } from "react";
import { NetworkPage } from "@/components/owner/NetworkView";
export default function Page() { return <Suspense fallback={null}><NetworkPage /></Suspense>; }
