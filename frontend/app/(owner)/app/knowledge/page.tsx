import { Suspense } from "react";
import { KnowledgePage } from "@/components/owner/Knowledge";
export default function Page() { return <Suspense fallback={null}><KnowledgePage /></Suspense>; }
