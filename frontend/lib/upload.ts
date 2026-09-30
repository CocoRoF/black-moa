"use client";
import { parseError, redirectToLogin, refreshAccess } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { useAuth } from "@/stores/auth";

/** 파일 하나를 올리며 실제로 얼마나 갔는지 알려 준다 (plan/55 §6-1).
 *
 *  `fetch` 는 보내는 쪽의 진행을 알려 주지 않는다. 10MB 사진이 느린 망에서 몇 초 걸리는
 *  동안 칩이 빙글빙글만 돌면 사람은 멈췄는지 가는 중인지 모른다 — 그래서 XHR 이다.
 *  토큰이 만료되었으면 한 번 새로 받아 다시 보낸다(`api()` 와 같은 규칙).
 */
export interface Uploaded { upload_id: string; url: string; mime: string; size: number; filename: string }

export function uploadFile(file: File, opts: {
  kind?: string; lane?: "docs" | "community"; onProgress?: (ratio: number) => void; signal?: AbortSignal;
  /** 다른 입구(방문자 파일은 대화에 딸린 주소로 올린다). */
  url?: string;
  /** 방문자 토큰처럼 로그인 토큰이 아닌 것. 주면 만료 때 다시 받지 않는다. */
  token?: string | null;
} = {}): Promise<Uploaded> {
  const send = (tok: string | null) => new Promise<{ status: number; body: string; headers: string }>((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", opts.url ?? "/api/uploads");
    x.withCredentials = true;
    if (tok) x.setRequestHeader("Authorization", `Bearer ${tok}`);
    x.setRequestHeader("Accept", "application/json");
    x.upload.onprogress = (e) => { if (e.lengthComputable) opts.onProgress?.(Math.min(1, e.loaded / e.total)); };
    x.onload = () => resolve({ status: x.status, body: x.responseText, headers: x.getAllResponseHeaders() });
    x.onerror = () => reject(new ApiError(0, "network", "network error"));
    x.onabort = () => reject(new DOMException("aborted", "AbortError"));
    opts.signal?.addEventListener("abort", () => x.abort(), { once: true });
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", opts.kind ?? "attachment");
    fd.append("lane", opts.lane ?? "docs");
    x.send(fd);
  });
  const asResponse = (r: { status: number; body: string }) => new Response(r.body || null, { status: r.status, headers: { "Content-Type": "application/json" } });
  return (async () => {
    const own = opts.token === undefined;
    let r = await send(own ? useAuth.getState().token : opts.token ?? null);
    if (r.status === 401 && own) {
      const fresh = await refreshAccess();
      if (!fresh) { redirectToLogin(); throw await parseError(asResponse(r)); }
      opts.onProgress?.(0);
      r = await send(fresh);
    }
    if (r.status < 200 || r.status >= 300) throw await parseError(asResponse(r));
    opts.onProgress?.(1);
    return JSON.parse(r.body) as Uploaded;
  })();
}

// ── 무엇을 받는가 ─────────────────────────────────────────────────────
//
// 서버의 규칙(services/uploads.py)과 같다. 보내 보고 거절당하기 전에 여기서 먼저 말한다 —
// 25MB 를 다 올린 뒤에야 "너무 커요"를 듣는 것만큼 허탈한 일이 없다.

export const IMAGE_MAX = 10 * 1024 * 1024;
export const DOC_MAX = 25 * 1024 * 1024;
export const MAX_FILES = 8;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif"]);
const DOC_EXT: Record<string, string> = {
  pdf: "application/pdf", txt: "text/plain", md: "text/markdown", csv: "text/csv",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  heic: "image/heic", heif: "image/heif", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", gif: "image/gif",
};
export const ACCEPT = "image/*,.heic,.heif,.pdf,.txt,.md,.csv,.docx,.xlsx,.pptx";

/** 브라우저가 알려 주는 종류는 비어 있거나(HEIC, .md) 틀릴 때가 있어 확장자로 한 번 더 본다. */
export function kindOf(f: File): string {
  const ext = (f.name.split(".").pop() ?? "").toLowerCase();
  const t = (f.type || "").toLowerCase();
  if (IMAGE_TYPES.has(t) || DOC_EXT[ext]?.startsWith("image/")) return DOC_EXT[ext] ?? t;
  return Object.values(DOC_EXT).includes(t) ? t : DOC_EXT[ext] ?? t;
}

export function isImage(f: File | { mime?: string }): boolean {
  const m = f instanceof File ? kindOf(f) : (f.mime ?? "");
  return m.startsWith("image/");
}

/** 받을 수 없으면 그 이유(번역 키)를, 받을 수 있으면 null. */
export function refuse(f: File): "chat.file_unsupported" | "chat.file_too_big_image" | "chat.file_too_big_doc" | "chat.file_empty" | null {
  const k = kindOf(f);
  if (!IMAGE_TYPES.has(k) && !Object.values(DOC_EXT).includes(k)) return "chat.file_unsupported";
  if (f.size === 0) return "chat.file_empty";
  if (IMAGE_TYPES.has(k) && f.size > IMAGE_MAX) return "chat.file_too_big_image";
  if (!IMAGE_TYPES.has(k) && f.size > DOC_MAX) return "chat.file_too_big_doc";
  return null;
}

/** 브라우저가 미리 보여 줄 수 있는 그림인가. HEIC 는 사파리 말고는 못 그린다. */
export function canPreview(f: File): boolean {
  const k = kindOf(f);
  return k.startsWith("image/") && k !== "image/heic" && k !== "image/heif";
}

export { fmtBytes } from "@/lib/format";
