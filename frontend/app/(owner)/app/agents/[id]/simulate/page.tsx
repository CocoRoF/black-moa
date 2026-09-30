import { Suspense } from "react";
import { OwnerChat } from "@/components/agent/OwnerChat";

export default function Page() {
  // The agent layout already renders the header above, so this one skips its own.
  return <Suspense fallback={null}><OwnerChat simulate hideMobileHeader /></Suspense>;
}
