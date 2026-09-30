import { Suspense } from "react";
import { ForgotForm, AuthSkeleton } from "@/components/marketing/AuthForms";

// Rendered per request, not at build time. The form reads what is after the question mark
// in the address, and a page built before that exists has to leave the space empty and let
// the browser fill it — the same page arriving twice, which is what React was complaining
// about once in a while here.
export const dynamic = "force-dynamic";

export default function Page() { return <Suspense fallback={<AuthSkeleton />}><ForgotForm /></Suspense>; }
