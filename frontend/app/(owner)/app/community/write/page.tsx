import { Suspense } from "react";
import { PostEditor } from "@/components/community/PostEditor";
export default function Page() { return <Suspense fallback={null}><PostEditor /></Suspense>; }
