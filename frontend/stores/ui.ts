"use client";
import { create } from "zustand";
import { storageGet, storageSet } from "@/lib/utils";

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  hydrate: () => void;
}
export const useUI = create<UIState>((set, get) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => { const v = !get().sidebarCollapsed; storageSet("local", "blackmoa:sidebar", v ? "1" : "0"); set({ sidebarCollapsed: v }); },
  hydrate: () => set({ sidebarCollapsed: storageGet("local", "blackmoa:sidebar") === "1" }),
}));
