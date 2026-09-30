import { Suspense } from "react";
import { AuthSkeleton, SsoCompleteForm } from "@/components/marketing/AuthForms";

// 연결로 들어왔는데 공급자가 이메일을 주지 않은 사람이 가입을 마치는 곳 (plan/59).
export const dynamic = "force-dynamic";

export default function Page() { return <Suspense fallback={<AuthSkeleton />}><SsoCompleteForm /></Suspense>; }
