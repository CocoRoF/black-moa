"use client";
import { create } from "zustand";

/** 메신저가 열려 있는지, 어느 방을 보고 있는지 (plan/44 §7).
 *
 *  The dock sits in the shell, and anything on any page can ask it to open a room — a face
 *  in the graph, a row in 인맥, a profile card. That request has to survive the component
 *  that made it going away, so it lives here rather than in a prop drilled through the page
 *  that happened to be open.
 */
interface MessengerState {
  open: boolean;
  /** The room being read, or null while the list is showing. */
  roomId: string | null;
  /** Somebody to open a room with, held until the dock has asked the server for it. */
  pending: { userId?: string; agentId?: string } | null;
  unread: number;
  show: () => void;
  hide: () => void;
  toggle: () => void;
  openRoom: (id: string) => void;
  back: () => void;
  openWith: (to: { userId?: string; agentId?: string }) => void;
  takePending: () => { userId?: string; agentId?: string } | null;
  setUnread: (n: number) => void;
}

export const useMessenger = create<MessengerState>((set, get) => ({
  open: false,
  roomId: null,
  pending: null,
  unread: 0,
  show: () => set({ open: true }),
  hide: () => set({ open: false }),
  toggle: () => set((s) => ({ open: !s.open })),
  openRoom: (id) => set({ open: true, roomId: id }),
  back: () => set({ roomId: null }),
  openWith: (to) => set({ open: true, roomId: null, pending: to }),
  takePending: () => { const p = get().pending; if (p) set({ pending: null }); return p; },
  setUnread: (n) => set({ unread: Math.max(0, n) }),
}));
