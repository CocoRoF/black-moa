import { Suspense } from "react";
import { ConnectionsPage } from "@/components/admin/Connections";
export default function Page() { return <Suspense fallback={null}><ConnectionsPage /></Suspense>; }
