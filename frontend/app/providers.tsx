"use client";
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/lib/theme";
import { Toaster } from "@/components/ui/toaster";
import { ConfirmHost } from "@/lib/confirm";
import { ChunkReloadGuard } from "@/components/ChunkReloadGuard";
import { ApiError } from "@/lib/errors";
import { migrateStorageKeys } from "@/lib/utils";

export function Providers({ children }: { children: ReactNode }) {
  // In a state initialiser, not an effect: the stores below read storage while they
  // hydrate, which happens before any effect of ours would run.
  useState(() => { migrateStorageKeys(); return null; });
  const [qc] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000, refetchOnWindowFocus: false,
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      },
    },
  }));
  return (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ChunkReloadGuard />
        {children}
        <Toaster />
        <ConfirmHost />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
