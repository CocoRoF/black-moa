import { Suspense } from "react";
import { ChatSurface } from "@/components/owner/ChatSurface";

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatSurface />
    </Suspense>
  );
}
