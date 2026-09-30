import { Suspense } from "react";
import { MailView } from "@/components/mail/MailView";
export default function Page() { return <Suspense fallback={null}><MailView /></Suspense>; }
