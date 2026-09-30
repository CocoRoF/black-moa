import { Suspense } from "react";
import { ScheduleView } from "@/components/schedule/ScheduleView";
export default function Page() { return <Suspense fallback={null}><ScheduleView /></Suspense>; }
