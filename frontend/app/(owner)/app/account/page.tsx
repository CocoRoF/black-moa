import { Suspense } from "react";
import { AccountVerificationPage } from "@/components/owner/AccountVerification";
export default function Page() { return <Suspense fallback={null}><AccountVerificationPage /></Suspense>; }
