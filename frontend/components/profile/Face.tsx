"use client";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { ProfileModal } from "@/components/profile/ProfileModal";

/** A face that opens the person (plan/44 §8).
 *
 *  Every avatar and byline in the app is one of these: a person's `id`, or a secretary's
 *  `agentId`, and pressing it opens the same card wherever it sits. Given nobody — a pen
 *  name in the square, a guest with no account — it draws its children and does nothing,
 *  which is the difference between a name and a door.
 *
 *  A span, not a button: this often sits inside a link (a post row that opens the post),
 *  and a button inside a link is markup no browser keeps. It swallows the press so the link
 *  around it stays put.
 */
export function Face({ id, agentId, className, children, stop = true }: {
  id?: string | null; agentId?: string | null; className?: string; children: ReactNode;
  /** Keep the press from reaching whatever this sits in. */
  stop?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const who = agentId ? { agentId } : id ? { userId: id } : null;
  if (!who) return <span className={className}>{children}</span>;
  return (
    <>
      <span role="button" tabIndex={0} className={cn("cursor-pointer rounded-md hover:opacity-80", className)}
            onClick={(e) => { if (stop) { e.preventDefault(); e.stopPropagation(); } setOpen(true); }}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); setOpen(true); } }}>
        {children}
      </span>
      {open ? <ProfileModal userId={who.userId} agentId={who.agentId} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
