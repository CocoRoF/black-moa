import { Suspense } from "react";
import { FilesView } from "@/components/owner/FilesView";
export default function Page() { return <Suspense fallback={null}><FilesView /></Suspense>; }
