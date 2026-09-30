import { Suspense } from "react";
import { ProfilePage } from "@/components/owner/Profile";
export default function Page() { return <Suspense fallback={null}><ProfilePage /></Suspense>; }
