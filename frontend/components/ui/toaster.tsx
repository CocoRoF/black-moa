"use client";
import { Toaster as Sonner } from "sonner";
import { useTheme } from "@/lib/theme";

export function Toaster() {
  const { resolved } = useTheme();
  return <Sonner theme={resolved} position="top-center" richColors closeButton duration={3500} toastOptions={{ classNames: { toast: "rounded-xl! text-sm!" } }} />;
}
