import { Suspense } from "react";
import { SettingsPage } from "@/components/owner/AccountSettings";
export default function Page() { return <Suspense fallback={null}><SettingsPage /></Suspense>; }
