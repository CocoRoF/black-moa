"use client";
import { ApiError } from "./errors";
import type { Level } from "./visibility";
import { useAuth, type User } from "@/stores/auth";

export type Json = Record<string, unknown>;

let refreshing: Promise<string | null> | null = null;
const HAD_SESSION = "blackmoa:had-session";
/** We cannot read the httpOnly refresh cookie; remember that a session was created so first-time visitors don't hit /refresh (401 noise). */
export function markSession(on: boolean) { try { if (on) localStorage.setItem(HAD_SESSION, "1"); else localStorage.removeItem(HAD_SESSION); } catch { /* ignore */ } }
export function hadSession(): boolean { try { return localStorage.getItem(HAD_SESSION) === "1"; } catch { return false; } }

/** ONE single-flight refresh; returns a new access token or null. */
export async function refreshAccess(): Promise<string | null> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    try {
      const r = await fetch("/api/auth/refresh", { method: "POST", credentials: "include", headers: { Accept: "application/json" } });
      if (!r.ok) { if (r.status === 401) markSession(false); return null; }
      const data = (await r.json()) as { access_token: string; user: User };
      useAuth.getState().setAuth(data.access_token, data.user);
      markSession(true);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export function redirectToLogin() {
  if (typeof window === "undefined") return;
  useAuth.getState().clear();
  markSession(false);
  const here = window.location.pathname + window.location.search;
  if (window.location.pathname.startsWith("/login")) return;
  window.location.assign(`/login?next=${encodeURIComponent(here)}`);
}

export interface ReqOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  token?: string | null;      // explicit override (visitor token)
  auth?: boolean;             // default true: attach owner token and refresh on 401
  raw?: boolean;              // return Response instead of parsed JSON
  query?: Record<string, string | number | boolean | null | undefined>;
}

function buildUrl(path: string, query?: ReqOptions["query"]) {
  if (!query) return path;
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `${path}${path.includes("?") ? "&" : "?"}${qs}` : path;
}

export async function parseError(r: Response): Promise<ApiError> {
  let code = `http_${r.status}`;
  let message = r.statusText;
  let detail: unknown = undefined;
  try {
    const j = await r.json();
    if (j?.error) { code = j.error.code ?? code; message = j.error.message ?? message; detail = j.error.detail; }
    else if (j?.detail) { detail = j.detail; message = typeof j.detail === "string" ? j.detail : message; }
  } catch { /* ignore */ }
  if (r.status === 429 && code.startsWith("http_")) code = "rate_limited";
  if (r.status === 401 && code.startsWith("http_")) code = "unauthorized";
  const ra = r.headers.get("Retry-After");
  return new ApiError(r.status, code, message, detail, ra ? parseInt(ra, 10) || null : null);
}

export async function api<T = unknown>(path: string, opts: ReqOptions = {}): Promise<T> {
  const { body, token, auth = true, raw = false, query, headers: h, ...rest } = opts;
  const url = buildUrl(path, query);
  const doFetch = async (tok: string | null) => {
    const headers = new Headers(h ?? {});
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    let payload: BodyInit | undefined;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers.set("Content-Type", "application/json"); payload = JSON.stringify(body); }
    if (tok) headers.set("Authorization", `Bearer ${tok}`);
    return fetch(url, { ...rest, headers, body: payload, credentials: rest.credentials ?? "same-origin" });
  };
  let tok = token !== undefined ? token : auth ? useAuth.getState().token : null;
  let r = await doFetch(tok);
  if (r.status === 401 && auth && token === undefined) {
    const fresh = await refreshAccess();
    if (!fresh) { redirectToLogin(); throw await parseError(r); }
    tok = fresh;
    r = await doFetch(tok);
    if (r.status === 401) { redirectToLogin(); throw await parseError(r); }
  }
  if (!r.ok) throw await parseError(r);
  if (raw) return r as unknown as T;
  if (r.status === 204) return undefined as T;
  const text = await r.text();
  if (!text) return undefined as T;
  try { return JSON.parse(text) as T; } catch { return text as unknown as T; }
}

export const get = <T,>(p: string, o: ReqOptions = {}) => api<T>(p, { ...o, method: "GET" });
export const post = <T,>(p: string, body?: unknown, o: ReqOptions = {}) => api<T>(p, { ...o, method: "POST", body });
export const put = <T,>(p: string, body?: unknown, o: ReqOptions = {}) => api<T>(p, { ...o, method: "PUT", body });
export const patch = <T,>(p: string, body?: unknown, o: ReqOptions = {}) => api<T>(p, { ...o, method: "PATCH", body });
export const del = <T,>(p: string, o: ReqOptions = {}) => api<T>(p, { ...o, method: "DELETE" });

/** Fetch an authenticated binary as an object URL (QR, export ZIP, uploads). */
export async function fetchBlobUrl(path: string, opts: ReqOptions = {}): Promise<string> {
  const r = await api<Response>(path, { ...opts, raw: true, headers: { Accept: "*/*" } });
  const b = await r.blob();
  return URL.createObjectURL(b);
}

// ─── typed resource helpers ──────────────────────────────────────────
export interface AuthStatus { bootstrap_needed: boolean; bootstrap_token_required?: boolean; signup_mode: "open" | "invite" | "closed";
  /** 로그인에 쓰기가 켜진 연결 (plan/59) — 로그인·가입 화면의 버튼. */
  sso: { id: string; label: string }[]; service_name: string; tagline: string; verify_before_agent?: boolean; mail_configured?: boolean;
  /** 음성을 쓰는가 (plan/67). 관리자가 끄면 마이크·소리 단추와 그 설정을 감춘다. */
  voice?: { stt: boolean; tts: boolean };
  /** 기업 기능을 쓰는가 (plan/71). 관리자가 끄면 기업정보 탭·기업 페이지·소속·회사 인증을 감춘다. */
  companies?: boolean;
  /** 지금 동의받는 이용약관·개인정보 처리방침의 판 (plan/73). */
  legal_version?: string }
export interface Branding { service_name: string; tagline: string; logo_url: string; turnstile_site_key: string }

export interface Link { id: string; agent_id: string; code: string; url: string; label: string; status: "active" | "paused" | "expired" | "revoked"; effective_status?: string; expires_at: string | null; max_conversations: number | null; conversation_count: number; turn_count: number; last_visit_at: string | null; created_at: string;
  /** plan/38: may other members' secretaries talk to this one, and how many of their turns a day the owner will pay for. */
  settings: { allow_agents: boolean; agent_turns_per_day: number; findable: boolean;
    /** 방문자에게 보일 모양 (plan/71): 채팅(기본) · 무대. */
    layout?: "chat" | "stage" } }
/** 먼저 말 걸기는 여기 없다. 그 리듬은 관리자가 일괄로 정한다 (plan/54). */
export interface RelationshipParams { pace?: "slow" | "normal" | "fast"; address_evolves: boolean; emotional_range: number }
export interface Persona {
  preset: string; formality: number; warmth: number; verbosity: number; humor: number; emoji: boolean; self_reference?: string; catchphrases?: string[]; address_owner_as?: string; traits?: string[]; extra?: string;
  /** Studio (plan/37): the opening scene, forbidden topics, voice samples, and how the relationship is allowed to grow. */
  first_meeting?: string; taboo?: string[]; examples?: { user: string; assistant: string }[]; relationship?: Partial<RelationshipParams>;
}
export type RelationshipStage = "new" | "familiar" | "trusted" | "companion";
export interface Relationship {
  agent_id: string; agent_name?: string; stage: RelationshipStage; stage_label: string; stage_index: number; stages: RelationshipStage[]; score: number;
  started_at: string | null; last_turn_at: string | null; days_together: number; turns: number; active_days: number; streak_days: number; facts_remembered: number;
  stage_changed_at: string | null; milestones: { key: string; at: string }[]; mood: { state?: string; reason?: string; set_at?: string; expires_at?: string }; moods: string[];
  progress: { stage: RelationshipStage; ratio: number; needs: { days: number; turns: number; facts: number; posts: number }; targets: { days: number; turns: number; facts: number; posts: number } } | null;
  params: RelationshipParams;
  /** 지금 우리 사이의 온도 0~100 (plan/45 §4). 쌓은 것과 달리 방치하면 빠르게 식는다. */
  affinity: number;
  /** 쌓은 것이 허락하는 단계와 온도가 허락하는 단계. 실제 단계는 둘 중 낮은 쪽이다. */
  earned_stage: RelationshipStage; warmth_stage: RelationshipStage;
  posts_written: number; idle_days: number | null; grace_days: number;
  /** 관리자가 정하는 리듬 (plan/54). `managed` 는 "이 화면에서 고치는 것이 아니다" 는 뜻이다. */
  proactive: { enabled: boolean; managed?: boolean; max_per_day: number; last_at: string | null; last_kind: string; sent_today: number;
    /** The owner's rule: nothing is sent within this many minutes of their own last message; `quiet_until` is set while that window is open. */
    quiet_minutes: number; quiet_until: string | null };
}
export interface ProactiveStatus { status: string; phase: "queued" | "writing" | "sent" | "skipped" | "failed"; kind: string | null; skipped: string | null; conversation_id: string | null; message_id: string | null; elapsed_s: number; writing_s: number | null; error: string | null }
export type JournalEntry =
  | { type: "fact"; id: string; at: string; subject: string; predicate: string; object: string; kind: string; visibility: string }
  | { type: "note"; id: string; namespace: string; at: string; title: string; body: string; category: string; pinned: boolean; importance: string }
  | { type: "milestone"; id: string; at: string; key: string }
  | { type: "post"; id: string; at: string; title: string; body: string; visibility: string; images: number; read: boolean };
/** 비서 [지식] 탭 = 외부인과의 대화에서 무엇을 쓰나 (plan/57). 나와의 대화는 늘 전부라 여기 없다. */
export type OutsiderLevel = "off" | "known" | "public";
export type OutsiderScope = "picked" | "all";
export interface OutsiderSettings {
  profile: boolean;
  knowledge: OutsiderLevel; knowledge_scope: OutsiderScope; knowledge_files: boolean;
  files: OutsiderLevel; files_scope: OutsiderScope;
  network: OutsiderLevel; network_scope: OutsiderScope;
  schedule: OutsiderLevel;
  memory: boolean; visitors: boolean; web: boolean;
}
export type OutsiderKind = "knowledge" | "files" | "network";
export interface Outsider {
  agent_id: string; settings: OutsiderSettings; links_active: number;
  profile: { fields: { key: string; level: Level }[]; name: string; posts: { public: number; known: number } };
  knowledge: { docs_total: number; faqs_total: number; docs_picked: number; faqs_picked: number; titles: string[]; file_docs: number };
  files: { total: number; picked: number; names: string[] };
  network: { total: number; picked: number; names: string[] };
  schedule: { weekly: WeeklyRow[]; note: string; timezone: string; preview: { start: string; end: string; label: string }[]; skip_holidays?: boolean };
  memory: { shared_notes: number; public_facts: number };
}
export interface OutsiderItem { id: string; type: "doc" | "faq" | "file" | "person"; title: string; sub: string; picked: boolean; status?: string; doc_kind?: string; node_kind?: string }
export interface PersonaVersion { id: string; label: string; created_at: string; snapshot: Record<string, any>; summary: { name: string | null; preset: string | null; role_line: string | null; custom_len: number } }
export interface StudioDraft { name?: string; role_line?: string; persona?: Persona; custom_instructions?: string; language?: string }
export interface StudioPreview { question: string; draft: string; current: string | null; same: boolean; credits: number }
export interface StudioVerify { probes: { key: string; question: string; answer: string }[]; intended: Record<string, any>; perceived: Record<string, number>; issues: string[]; verdict: "consistent" | "drifting" | "off" | null; one_line: string; credits: number }
/** 비서가 외부인에게 **어떻게 말하는가**. 무엇을 쓰는지는 [지식] 탭, 칸의 공개 범위는 [내 정보 → 정보] 다 (plan/57). */
export interface DisclosurePolicy { topics_public: string[]; topics_private: string[]; unknown_policy: "offer_message" | "say_unknown" }
export interface Agent {
  id: string; name: string; role_line: string; avatar_url: string | null; status: "active" | "paused" | "archived";
  /** The band behind the photo on the profile card (plan/32). */
  cover_url: string | null;
  /** 올린 그림 그대로(자르지도 흰 바탕을 깔지도 않은 원본). PC 앱의 아바타가 띄운다 (plan/63). */
  character_url?: string | null;
  provider: string; model_id: string; persona: Persona; custom_instructions: string;
  /** 외부인과의 대화에서 하는 일 — 음성·메시지 남기기·미팅 요청 (plan/57). 나와의 대화는 늘 전부. */
  capabilities: Record<string, boolean>;
  disclosure_policy: DisclosurePolicy; outsider?: OutsiderSettings; greeting: string; suggested_questions: string[]; language: string;
  theme: { accent: string; avatar_shape: string; bubble_style: string; background: string };
  /** What a visitor sees right now: the owner's own text, or the default rendered from the current names. */
  greeting_display?: string; role_line_display?: string;
  voice: { tts_voice: string; tts_speed: number; stt_language: string };
  visitor_settings: { retention_days: number; rate_per_minute: number; require_turnstile: boolean; collect_identity: string; turns_per_day?: number; sessions_per_hour?: number; accept_files?: boolean; files_per_day?: number; file_max_mb?: number };
  thinking_enabled: boolean; stats: Record<string, number>; created_at: string; updated_at: string; links: Link[];
  /** The owner's own guard rails on this secretary (plan/34). 0 = no limit. */
  turn_cost_cap_credits: number; daily_credit_cap: number; monthly_credit_cap: number;
}
export interface ModelInfo { provider: string; model_id: string; display_name: string; context_window: number; supports_thinking: boolean; supports_vision: boolean; is_default: boolean; credit_per_1k_input: number; credit_per_1k_output: number }
export interface PersonaPreset { id: string; label: string; description: string; formality: number; warmth: number; verbosity: number; humor: number; emoji: boolean; traits: string[] }
export interface Conversation { id: string; agent_id: string; audience: "owner" | "visitor"; visitor_id: string | null; title: string; status: string; summary: string | null; last_message_at: string | null; message_count: number; unread_owner: boolean; created_at: string;
  /** human — a person on the other side; agent — one side of a secretary-to-secretary exchange (plan/38). */
  kind: "human" | "agent"; relay_id: string | null }
export type RelayStatus = "open" | "closed";
export interface Relay {
  id: string; status: RelayStatus; role: "initiator" | "target"; my_agent_id: string; my_agent_name: string; my_conversation_id: string | null;
  peer_agent_name: string; peer_owner_name: string; purpose: string; opener: string; message_count: number; max_messages: number; credit_cap: number; my_credits: number;
  hop_pending: "initiator" | "target" | null; summary: string; closed_at: string | null; closed_by: string | null; close_reason: string | null; created_at: string | null; last_message_at: string | null;
}
export interface RelayMessage { seq: number; side: "initiator" | "target" | "system"; kind: string; content: string; created_at: string; agent_name: string; mine: boolean }
export interface RelayDetail extends Relay { messages: RelayMessage[]; names: { initiator_agent: string; target_agent: string; initiator_owner: string; target_owner: string } }
export interface CardData { card_type: string; payload: Record<string, any>; message_id?: string }
export interface MessageOut { id: string; role: "user" | "assistant" | "card" | "system"; content: string; attachments?: any[]; cards: CardData[]; turn_id?: string | null; created_at: string; feedback?: { verdict: string; note: string };
  /** 끝까지 가지 못한 턴의 말이면 (plan/69): 멈춤 · 다른 화면에서 새로 물어 멈춤 · 받지 못함 · 아직 흐름. */
  turn_status?: "cancelled" | "superseded" | "failed" | "running" }
export interface Balance { balance: number; plan: { code: string; name: string; monthly_credits: number; max_agents: number; max_share_links: number; max_storage_mb: number; features: Record<string, boolean> }; cycle_ends_at: string | null; low: boolean; stripe_enabled: boolean }
export type InboxKind = "message" | "storage_notice" | "meeting_request" | "contact_share" | "question_unanswered" | "community_comment" | "community_reply" | "relay_result" | "relay_visit" | "company_review" | "company_job" | "link_request" | "link_accepted" | "person_follow" | "post_comment" | "post_reply" | "post_mention";
// agent_id is null on community notifications: they are addressed to the person, not a secretary.
export interface InboxItem { id: string; agent_id: string | null; conversation_id: string | null; visitor_id: string | null; kind: InboxKind; payload: Record<string, any>; status: string; owner_reply: string | null; created_at: string; updated_at: string | null; visitor?: { display_name: string | null; email: string | null; note: string | null; turn_count: number; first_seen_at: string; blocked: boolean }; conversation?: { role: string; content: string; cards: CardData[] | null; created_at: string }[] }
/** What happened when a meeting was accepted (plan/41 §9.2, plan/56): it always lands on the
 *  schedule, and `google` says whether it also reached a connected Google calendar. */
/** 수락한 미팅이 스케줄에 들어간 결과. ``external`` 은 "넣기" 를 켠 바깥 달력(Google·카카오)에도 넣었는가 (plan/59). */
export interface CalendarWrite { created: boolean; schedule_event_id?: string; start_at?: string; end_at?: string; html_link?: string; attendee?: string;
  external?: { provider: string | null; label: string; status: "added" | "unchanged" | "off" | "no_connection" | "failed" } }
export interface KnowledgeDoc { id: string; kind: "file" | "note" | "url"; title: string; filename: string | null; mime: string | null; size_bytes: number | null; source_url: string | null; status: "queued" | "processing" | "ready" | "failed" | string; error: string | null; chunk_count: number; embedding_model: string | null; created_at: string; updated_at: string | null; text_preview?: string }
export interface Faq { id: string; question: string; answer: string; source: string }
/** `person` is the identity layer (plan/31): who this node actually is.
 *  self — me · member — a black-moa account · guest — someone who talked to my secretary ·
 *  offline — a card I wrote. Only the first three have a face. */
export type PersonClass = "self" | "member" | "guest" | "offline";
export interface NetNode { link_code?: string; owner_node_id?: string; id: string; kind: string; name: string; aliases: string[]; tags: string[]; importance: number; source: string; last_contact_at: string | null; attrs: Record<string, any>; notes: string; community?: number; depth?: number; person: PersonClass | "agent" | "source"; is_self: boolean; user_id: string | null; visitor_id: string | null; avatar_url: string | null; hops?: number | null }
export interface Account { id: string; display_name: string; real_name?: string; avatar_url: string | null; handle: string | null; email?: string | null; link?: { status: "mutual" | "outgoing" | "incoming"; direction: "both" | "incoming" | "outgoing" } | null; note?: string | null; at?: string }
/** A member's profile as another member may see it: only the fields its owner published. */
export interface MemberProfile {
  id: string; display_name: string; avatar_url: string | null; handle: string | null; is_me: boolean;
  link: Account["link"]; joined_at: string | null; connections: number; email?: string | null; real_name?: string;
  fields: { full_name?: string; preferred_name?: string; title?: string; company?: string; bio?: string; location?: string; languages?: string[] | string; links?: any; cover?: string; cover_pos?: number; job_codes?: string[]; region_codes?: string[]; industry_codes?: string[]; company_verified_at?: string | null;
    /** [정보] 의 공개 범위대로 — 칸마다 이 사람에게 보이는 것만 온다 (plan/57). */
    contact?: { email?: string; phone?: string }; contact_rules?: string; extra?: string };
  /** Who reads whom (plan/41 §5): their counts, and whether I read them. */
  follow?: { followers: number; following: number; i_follow: boolean };
  /** The first page of their writing; the rest is turned with `Network.posts`. */
  posts?: BlogPost[];
  posts_total?: number;
  /** The secretaries they left a door open to (plan/44 §8). */
  secretaries?: { id: string; name: string; avatar_url: string | null; role_line: string; link_code: string }[];
}
/** A proposal only exists when it resolves to someone the system can act on (plan/31):
 *  `connect` sends an 인맥 신청, `add_guest` binds a guest who actually visited. */
export interface Proposal {
  id: string; kind: string; payload: Record<string, any>; confidence: number; status: string;
  agent_id: string | null; created_at: string;
  resolved: { action: "connect" | "add_guest" | "none"; why?: string; visitor_id?: string;
              person?: { id: string; display_name: string; avatar_url: string | null; handle: string | null; turns?: number; link?: Account["link"] } };
}
/** Somebody, or a secretary anybody can talk to. Naming a secretary asks it to read the
 *  post and answer under it (plan/43 §6). */
export interface Mentionable {
  kind: "person" | "agent"; id: string; handle: string; display_name: string; avatar_url: string | null; link_code?: string;
  /** A secretary carries whose it is. */
  owner_name?: string; mine?: boolean;
}
export interface Suggestion extends Account { reason: "guest" | "connected_me"; reason_detail: string | null; mutual: number }
export interface Guest { visitor_id: string; name: string | null; email: string | null; note: string | null; agent: string | null; turns: number; blocked: boolean; first_seen_at: string | null; last_seen_at: string | null; signed_in: boolean; account: Account | null; link: Account["link"]; node_id: string | null }
export interface NetEdge { id: string; src_id: string; dst_id: string; rel: string; direction: string; strength: number; since: string | null; until: string | null; attrs: Record<string, any>; source: string }
export interface Channel { id: string; kind: string; label: string; config: Record<string, any>; enabled: boolean; verified_at: string | null; last_error: string | null; created_at: string }
export interface Rule { id: string; event: string; agent_id: string | null; channel_ids: string[]; enabled: boolean; quiet_hours: { start?: string; end?: string } | Record<string, any>; min_urgency: number }
export interface Connection { id: string; provider: string; provider_label: string; account_label: string; capabilities: string[];
  /** 공급자가 이미 권한을 내준 기능 — 여기 없는 기능을 켜면 동의 화면을 한 번 더 거친다. */
  granted: string[]; status: string; last_sync_at: string | null; error: string | null; created_at: string }
/** 사용자가 이을 수 있는 공급자 — 관리자가 [연결] 에서 켜고 준 기능만 (plan/59). */
export interface IntegrationProvider { id: string; label: string; capabilities: { id: string }[] }
/** 계정에 들어오는 방법 하나 (plan/59). */
export interface LoginIdentity { id: string; provider: string; label: string; email: string | null; name: string; created_at: string | null }
/** 관리자 [연결] 의 공급자 하나 (plan/59). */
export interface AdminConnectionField { key: string; kind: "text" | "secret" | "bool"; required: boolean; value?: string | boolean; has_value?: boolean; masked?: string }
export interface AdminConnection {
  id: string; label: string; console_url: string; enabled: boolean; login: boolean; features: string[];
  capabilities: { id: string; scopes: string[] }[]; login_scopes: string[]; fields: AdminConnectionField[]; missing: string[];
  ready: boolean; login_ready: boolean; redirect_uris: { login: string; connect: string };
  stats: { identities: number; login_only: number; connections: number; connections_by_status: Record<string, number> };
}
export interface ConnectionCheck { ok: boolean; code: string; detail?: string; fields?: string[]; redirect_uris: { login: string; connect: string } }
/** 비서의 기억 하나. `visibility` 는 **이 기억이 어디까지 나가는가**이고, 기억마다
 *  붙는다 (plan/48 §2). 예전에는 방 이름(owner/shared)이 그 답이었다. */
export interface MemoryNote { id: string; title: string; body: string; category: string; tags: string[]; pinned: boolean;
                              importance: string; visibility?: string; created: string; updated: string; source: string; meta: Record<string, any> }
/** **그 비서가** 알게 된 사실 하나. 비서가 만든 것이라 비서의 것이다 (plan/49).
 *  `about_visitor` 는 범위가 아니라 그 손님에 대한 사실이라는 표시다. */
export interface Fact { id: string; subject: string; predicate: string; object: string; kind: string; confidence: number;
                        visibility: string; about_visitor?: boolean; updated_at: string }

/** 한 원천이 몇 개이고 그중 밖으로 나가는 것이 몇 개인가 (plan/48 §2). */

export const Auth = {
  status: () => get<AuthStatus>("/api/auth/status", { auth: false }),
  login: (b: { email: string; password: string }) => post<{ access_token: string; user: User }>("/api/auth/login", b, { auth: false, credentials: "include" }),
  signup: (b: { email: string; password: string; display_name: string; nickname?: string | null; invite_code?: string | null; bootstrap_token?: string | null; agree_terms: boolean }) => post<{ access_token: string; user: User }>("/api/auth/signup", b, { auth: false, credentials: "include" }),
  logout: () => post("/api/auth/logout", undefined, { credentials: "include" }),
  logoutAll: () => post("/api/auth/logout-all", undefined, { credentials: "include" }),
  me: () => get<User>("/api/auth/me"),
  /** 앱에 들어올 때 받는 동의 (plan/73). ``version`` 은 화면이 보여 준 판. */
  agreeTerms: (version: string) => post<{ user: User }>("/api/auth/terms", { version, agree: true }),
  forgot: (email: string) => post("/api/auth/password/forgot", { email }, { auth: false }),
  reset: (token: string, password: string) => post("/api/auth/password/reset", { token, password }, { auth: false }),
  sendVerification: () => post<{ ok: boolean; already?: boolean }>("/api/auth/email/send-code"),
  verifyEmail: (code: string) => post<{ ok: boolean }>("/api/auth/email/verify", { code }),
  /** 연결로 로그인 (plan/59). 브라우저가 이 주소로 이동하면 공급자의 로그인 화면으로 간다. */
  ssoStartUrl: (provider: string, o: { next?: string; invite?: string | null; agree?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (o.next) q.set("next", o.next);
    if (o.invite) q.set("invite", o.invite);
    if (o.agree) q.set("agree", "true");
    const qs = q.toString();
    return `/api/auth/${encodeURIComponent(provider)}/start${qs ? `?${qs}` : ""}`;
  },
  ssoPending: (t: string) => get<{ provider: string; provider_label: string; name: string; email_hint: string; signup_mode: string; invite_needed: boolean }>("/api/auth/sso/pending", { auth: false, query: { t } }),
  ssoComplete: (b: { token: string; email: string; display_name: string; invite_code?: string | null; agree_terms: boolean }) =>
    post<{ access_token: string; user: User; next: string }>("/api/auth/sso/complete", b, { auth: false, credentials: "include" }),
  identities: () => get<{ has_password: boolean; providers: { id: string; label: string; linked: boolean }[]; items: LoginIdentity[] }>("/api/auth/identities"),
  linkStart: (provider: string, next?: string) => post<{ url: string }>(`/api/auth/identities/${provider}/start`, { next: next ?? "/app/settings" }, { credentials: "include" }),
  unlink: (id: string) => del(`/api/auth/identities/${id}`),
};
/** A post on someone's own page (plan/41 §4). */
export interface BlogPost {
  id: string; slug: string; title: string; excerpt: string; body?: string;
  visibility: "public" | "friends" | "private"; status: "draft" | "published";
  /** note — written in the box at the top of 소식, no title of its own (plan/42 §4). */
  kind: "note" | "article";
  published_at: string | null; updated_at: string | null; view_count: number;
  like_count: number; comment_count: number;
  /** Signed addresses an <img> can fetch, in the order the author arranged them. */
  images: string[];
  /** Who the words name, resolved when it was saved (plan/42 §11). A mention points at a
   *  person, so `label` is whatever stands for them in the text and `handle` may be empty. */
  mentions: { id: string; label: string; handle: string; agent?: boolean; code?: string }[];
  /** The upload ids behind `images`, for editing. Only on my own post. */
  image_ids?: string[];
}
export interface PostComment {
  id: string; body: string; created_at: string;
  /** Signed by whoever wrote it: a person, or a secretary that was named (plan/43 §6). */
  author: { id: string; name: string; handle: string; avatar_url: string | null; agent?: boolean };
  /** Whether this reader may remove it, said by the server rather than guessed from the
   *  byline: a secretary signs its own comment and its owner is who deletes it. */
  can_delete?: boolean;
  /** The comment this answers. Two layers and no more (plan/42 §5). */
  parent_id?: string | null;
}
export const Blog = {
  /** My own writing, drafts included, in the shape 소식 draws. One page at a time. */
  list: (page = 1, limit = 10) =>
    get<{ items: FeedItem[]; page: number; pages: number; total: number }>("/api/blog", { query: { page, limit } }),
  read: (id: string) => get<BlogPost>(`/api/blog/${id}`),
  create: (b: { title?: string; body: string; visibility?: string; publish?: boolean; kind?: string; images?: string[]; mentions?: string[] }) => post<BlogPost>("/api/blog", b),
  update: (id: string, b: { title?: string; body?: string; visibility?: string; status?: string; images?: string[]; mentions?: string[] }) => patch<BlogPost>(`/api/blog/${id}`, b),
  remove: (id: string) => del(`/api/blog/${id}`),
  like: (id: string, on: boolean) => post<{ liked: boolean; like_count: number }>(`/api/blog/${id}/like`, { on }),
  comments: (id: string) => get<{ items: PostComment[] }>(`/api/blog/${id}/comments`),
  comment: (id: string, body: string, parentId?: string | null) =>
    post<PostComment>(`/api/blog/${id}/comments`, { body, parent_id: parentId ?? null }),
  removeComment: (postId: string, id: string) => del<{ ok: boolean; removed: number }>(`/api/blog/${postId}/comments/${id}`),
};

/** One card in 소식. Everything here is from somebody this person chose; the community is
 *  a different room and never appears (plan/42 §2). */
export interface FeedItem extends BlogPost {
  at: string | null; liked: boolean;
  why: "friend" | "following" | "mine";
  author: { id: string; name: string; handle: string; avatar_url: string | null };
  /** Mine to change or take down. */
  can_edit?: boolean;
}
export const Feed = {
  /** One post in the same shape as a card here, wherever it was pressed (plan/42 §12). */
  one: (id: string) => get<FeedItem>(`/api/feed/posts/${id}`),
  list: (cursor?: string) =>
    get<{ items: FeedItem[]; cursor: string | null; suggestions: Suggestion[];
          sources: { friends: boolean; following: boolean } }>("/api/feed", { query: cursor ? { cursor } : {} }),
};

export interface RoomFace {
  kind: "person" | "agent"; id: string; name: string; avatar_url: string | null; handle?: string;
  /** A secretary carries whose it is: two people can each have a 제니. */
  owner_name?: string; mine?: boolean;
}
export interface RoomRow {
  id: string; kind: "dm" | "secretary"; title: string; others: RoomFace[];
  last_message_at: string | null; message_count: number; unread: boolean;
  last: { body: string; role: string; at: string } | null;
  conversation_id: string | null;
  /** Whether the secretary in here is my own: the full-screen chat is for mine. */
  own_secretary?: boolean;
}
export interface RoomMessage {
  id: string; role: string; body: string;
  sender_user_id: string | null; sender_agent_id: string | null;
  attachments: any[]; cards: any[]; turn_id: string | null; created_at: string;
}
/** 메신저 (plan/44). 방이 하나의 손잡이다. */
export const Rooms = {
  list: () => get<{ items: RoomRow[]; unread: number }>("/api/rooms", { query: { limit: 100 } }),
  unread: () => get<{ unread: number }>("/api/rooms/unread"),
  open: (b: { user_id?: string; agent_id?: string }) => post<RoomRow>("/api/rooms/open", b),
  read: (id: string) => get<RoomRow>(`/api/rooms/${id}`),
  messages: (id: string, before?: string) =>
    get<{ items: RoomMessage[]; members: RoomFace[] }>(`/api/rooms/${id}/messages`, { query: before ? { before } : {} }),
  say: (id: string, body: string, uploadIds: string[] = []) => post<RoomMessage>(`/api/rooms/${id}/messages`, { body, upload_ids: uploadIds }),
  markRead: (id: string) => post<{ ok: boolean; unread: number }>(`/api/rooms/${id}/read`),
  unsay: (id: string, messageId: string) => del<{ ok: boolean }>(`/api/rooms/${id}/messages/${messageId}`),
};

export const Public = {
  /** 이용약관·개인정보 처리방침과 운영자 정보 (plan/73). */
  legal: () => get<{ terms: string; privacy: string; version: string; effective_date: string; service: string; operator: Record<string, string> }>("/api/public/legal", { auth: false }),
  branding: () => get<Branding>("/api/public/branding", { auth: false }),
  // A person's own page (plan/41 §3). Open to anyone, so no token.
  person: (handle: string) => get<PersonPublic>(`/api/public/people/${encodeURIComponent(handle)}`, { auth: false }),
  /** A published secretary as its own page sees it, by link code. */
  link: (code: string) => get<{ agent: PublicAgentCard }>(`/api/public/links/${encodeURIComponent(code)}`, { auth: false }),
};
/** Only what a card needs. The chat's own copy of this type carries the rest. */
export interface PublicAgentCard {
  name: string; role_line: string; avatar_url: string | null; cover_url?: string | null;
  owner_display_name: string; language: string; status: string; resting: boolean;
  theme: { accent?: string; avatar_shape?: string };
}
export interface PersonPublic {
  handle: string; display_name: string; avatar_url: string | null;
  fields: Record<string, any>;
  user_id?: string;
  secretary: { code: string; name: string; role_line: string; status: string; resting: boolean };
  posts?: BlogPost[];
  account?: { signed_in: boolean; is_owner: boolean };
}
export interface AgentPrompt {
  audience: "owner" | "visitor";
  base_sections: { name: string; text: string }[];
  base_prompt: string; secretary_prompt: string; custom_instructions: string; custom_default: string;
}

export const Agents = {
  list: (include_archived = false) => get<{ items: Agent[]; max_agents: number }>("/api/agents", { query: { include_archived } }),
  get: (id: string) => get<Agent>(`/api/agents/${id}`),
  create: (b: Json) => post<Agent>("/api/agents", b),
  patch: (id: string, b: Json) => patch<Agent>(`/api/agents/${id}`, b),
  action: (id: string, action: "pause" | "resume" | "archive" | "restore") => post<Agent>(`/api/agents/${id}/actions/${action}`),
  remove: (id: string) => del(`/api/agents/${id}`),
  promptPreview: (id: string, audience: string) => get<{ audience: string; sections: { key: string; text: string }[]; tools: string[] }>(`/api/agents/${id}/prompt-preview`, { query: { audience } }),
  outsider: (id: string) => get<Outsider>(`/api/agents/${id}/outsider`),
  patchOutsider: (id: string, b: Partial<OutsiderSettings>) => patch<Outsider>(`/api/agents/${id}/outsider`, b),
  outsiderItems: (id: string, kind: OutsiderKind, q = "") => get<{ kind: OutsiderKind; scope: OutsiderScope; items: OutsiderItem[] }>(`/api/agents/${id}/outsider/items`, { query: { kind, q } }),
  putPicks: (id: string, b: { kind: OutsiderKind; scope?: OutsiderScope; ids: string[]; faq_ids?: string[] }) => put<Outsider>(`/api/agents/${id}/outsider/picks`, b),
  tools: (id: string, audience: string) => get<{ tools: { name: string; description: string; core: boolean; requires_capability: string | null; requires_feature: string | null }[] }>(`/api/agents/${id}/tools`, { query: { audience } }),
  presets: () => get<{ items: PersonaPreset[] }>("/api/personas/presets"),
  prompt: (id: string, audience: "owner" | "visitor" = "owner") => get<AgentPrompt>(`/api/agents/${id}/prompt`, { query: { audience } }),
  models: () => get<{ items: ModelInfo[] }>("/api/models"),
  links: (id: string) => get<{ items: Link[] }>(`/api/agents/${id}/links`),
  createLink: (id: string, b: Json) => post<Link>(`/api/agents/${id}/links`, b),
  patchLink: (lid: string, b: Json) => patch<Link>(`/api/links/${lid}`, b),
  deleteLink: (lid: string) => del(`/api/links/${lid}`),
  simulate: (id: string) => post<Conversation>(`/api/agents/${id}/simulate`),
  memory: (id: string) => get<{ counts: Record<string, Record<string, number>> }>(`/api/agents/${id}/memory`),
  notes: (id: string, ns: string, category?: string) => get<{ items: MemoryNote[] }>(`/api/agents/${id}/memory/${ns}/notes`, { query: { category } }),
  note: (id: string, ns: string, nid: string) => get<MemoryNote>(`/api/agents/${id}/memory/${ns}/note`, { query: { id: nid } }),
  writeNote: (id: string, b: Json) => post<MemoryNote>(`/api/agents/${id}/memory/notes`, b),
  deleteNote: (id: string, ns: string, nid: string) => del(`/api/agents/${id}/memory/${ns}/note?id=${encodeURIComponent(nid)}`),
  searchMemory: (id: string, q: string) => get<{ items: any[] }>(`/api/agents/${id}/memory/search`, { query: { q } }),
  facts: (id: string, status = "active") => get<{ items: Fact[] }>(`/api/agents/${id}/facts`, { query: { status } }),
  patchFact: (fid: string, b: Json) => patch(`/api/facts/${fid}`, b),
};
export const Relationships = {
  list: () => get<{ items: Relationship[] }>("/api/relationships"),
  get: (aid: string) => get<Relationship>(`/api/agents/${aid}/relationship`),
  journal: (aid: string, limit = 60) => get<{ items: JournalEntry[] }>(`/api/agents/${aid}/relationship/journal`, { query: { limit } }),
  patch: (aid: string, b: Json) => patch<Relationship>(`/api/agents/${aid}/relationship`, b),
  sayNow: (aid: string, kind?: string) => post<{ queued: boolean; job_id: string | null; last_proactive_at: string | null }>(`/api/agents/${aid}/relationship/proactive`, { kind: kind ?? null }),
  proactiveStatus: (aid: string, jobId: string) => get<ProactiveStatus>(`/api/agents/${aid}/relationship/proactive/${jobId}`),
};
export const Relays = {
  start: (aid: string, b: { target: string; message: string; purpose?: string; max_messages?: number; credit_cap?: number }) => post<Relay>(`/api/agents/${aid}/relays`, b),
  list: (q: { agent_id?: string; role?: "initiator" | "target" } = {}) => get<{ items: Relay[] }>("/api/relays", { query: q }),
  get: (id: string) => get<RelayDetail>(`/api/relays/${id}`),
  stop: (id: string) => post<RelayDetail>(`/api/relays/${id}/stop`),
};
export const Studio = {
  firstMeetingTemplates: () => get<{ items: { id: string; label: string; text: string }[] }>("/api/studio/first-meeting-templates"),
  preview: (aid: string, question: string, draft: StudioDraft, compare = true) => post<StudioPreview>(`/api/agents/${aid}/studio/preview`, { question, draft, compare }),
  verify: (aid: string, draft: StudioDraft) => post<StudioVerify>(`/api/agents/${aid}/studio/verify`, { draft }),
  versions: (aid: string) => get<{ items: PersonaVersion[] }>(`/api/agents/${aid}/versions`),
  labelVersion: (aid: string, vid: string, label: string) => patch<PersonaVersion>(`/api/agents/${aid}/versions/${vid}`, { label }),
  restoreVersion: (aid: string, vid: string) => post<Agent>(`/api/agents/${aid}/versions/${vid}/restore`),
  deleteVersion: (aid: string, vid: string) => del(`/api/agents/${aid}/versions/${vid}`),
};
export const Chat = {
  conversations: (aid: string, audience?: string, kind?: "human" | "agent") => get<{ items: Conversation[] }>(`/api/agents/${aid}/conversations`, { query: { audience, kind } }),
  createConversation: (aid: string, title = "") => post<Conversation>(`/api/agents/${aid}/conversations`, { title }),
  getConversation: (aid: string, cid: string) => get<Conversation>(`/api/agents/${aid}/conversations/${cid}`),
  patchConversation: (aid: string, cid: string, b: Json) => patch<Conversation>(`/api/agents/${aid}/conversations/${cid}`, b),
  deleteConversation: (aid: string, cid: string) => del(`/api/agents/${aid}/conversations/${cid}`),
  messages: (aid: string, cid: string, before?: string) => get<{ items: MessageOut[] }>(`/api/agents/${aid}/conversations/${cid}/messages`, { query: { before, limit: 100 } }),
  // Saying an answer was wrong, and what was actually the case (plan/41 §8).
  turnFeedback: (aid: string, tid: string, b: { verdict: "wrong" | "good"; note?: string }) =>
    post<{ verdict: string; note: string; faq_id: string | null; question: string }>(`/api/agents/${aid}/turns/${tid}/feedback`, b),
  activeTurn: (aid: string, cid: string) => get<{ turn_id: string; seq: number } | null>(`/api/agents/${aid}/conversations/${cid}/active-turn`),
  turn: (aid: string, tid: string) => get<any>(`/api/agents/${aid}/turns/${tid}`),
  cancel: (aid: string, tid: string) => post(`/api/agents/${aid}/turns/${tid}/cancel`),
  /** `lane` is which class of work the server resizes the image in — community pictures
   *  must not queue behind knowledge indexing, and vice versa (plan/32 §2). */
  upload: (file: File, kind = "attachment", lane: "docs" | "community" = "docs") => { const fd = new FormData(); fd.append("file", file); fd.append("kind", kind); fd.append("lane", lane); return post<{ upload_id: string; url: string; mime: string; size: number; filename: string }>("/api/uploads", fd); },
  stt: (aid: string, blob: Blob, language = "") => { const fd = new FormData(); fd.append("file", blob, blob.type.includes("mp4") ? "audio.mp4" : "audio.webm"); fd.append("language", language); return post<{ text: string; language?: string }>(`/api/agents/${aid}/stt`, fd); },
  tts: (aid: string, text: string) => api<Response>(`/api/agents/${aid}/tts`, { method: "POST", body: { text }, raw: true, headers: { Accept: "audio/mpeg" } }),
};
export const Credits = {
  balance: () => get<Balance>("/api/credits/balance"),
  ledger: () => get<{ items: { id: string; delta: number; balance_after: number; kind: string; ref_type: string | null; ref_id: string | null; note: string | null; created_at: string }[] }>("/api/credits/ledger"),
  usage: (days = 30) => get<{ daily: { day: string; credits: number; turns: number; visitor_turns: number }[]; by_model: { provider: string; model_id: string; credits: number; count: number }[] }>("/api/credits/usage", { query: { days } }),
  topup: () => post("/api/credits/topup-request"),
  checkout: (pkg: string) => post<{ url: string }>("/api/billing/checkout", { package: pkg }),
};
export const Inbox = {
  list: (q: { agent_id?: string; kind?: string; status?: string; source?: string; limit?: number; since?: string; until?: string } = {}) => get<{ items: InboxItem[]; new_count: number }>("/api/inbox", { query: q }),
  get: (id: string) => get<InboxItem>(`/api/inbox/${id}`),
  setStatus: (id: string, b: { status: string; reply?: string; send_email?: boolean; start_at?: string; duration_minutes?: number }) =>
    post<InboxItem & { calendar?: CalendarWrite | null }>(`/api/inbox/${id}/status`, b),
  teach: (id: string, b: { answer: string }) => post<{ faq_id: string }>(`/api/inbox/${id}/teach`, b),
  block: (vid: string, unblock = false) => post<{ blocked: boolean }>(`/api/inbox/visitors/${vid}/block`, undefined, { query: { unblock } }),
};
export const Users = {
  mailHandle: (handle?: string) => get<{ handle: string; domain: string; address: string;
    check?: { ok: boolean; handle?: string; address?: string; code?: string | null; message?: string | null } }>(
    "/api/users/me/mail-handle", { query: handle !== undefined ? { handle } : {} }),
  setMailHandle: (handle: string) => put<{ handle: string; domain: string; address: string }>("/api/users/me/mail-handle", { handle }),
  /** 광장에서 쓰는 이름 (plan/52). 계정에 하나뿐이고, 밖으로는 이 이름만 나간다. */
  communityName: () => get<{ name: string; wait_days: number; change_days: number }>("/api/users/me/community-name"),
  setCommunityName: (name: string) => put<{ name: string; wait_days: number; change_days: number }>("/api/users/me/community-name", { name }),
  patchMe: (b: Json) => patch<User>("/api/users/me", b),
  // Returns a freshly minted session: every other device is signed out, this one is not.
  password: (b: { current_password: string; new_password: string }) =>
    post<{ ok: boolean; access_token: string; user: User }>("/api/users/me/password", b, { credentials: "include" }),
  sessions: () => get<{ items: { id: string; ua: string; ip: string; created_at: string; expires_at: string }[] }>("/api/users/me/sessions"),
  profile: () => get<{ data: Record<string, any>; visibility: Record<string, string>; updated_at: string }>("/api/users/me/profile"),
  putProfile: (b: { data?: Record<string, any>; visibility?: Record<string, string> }) => put<{ data: Record<string, any>; visibility: Record<string, string> }>("/api/users/me/profile", b),
  // Proving where you work with a work mailbox (plan/40 §10).
  company: () => get<CompanyVerifyState>("/api/users/me/company"),
  companyStart: (email: string) => post<CompanyVerifyState>("/api/users/me/company/start", { email }),
  companyConfirm: (b: { code?: string; company_id?: string }) => post<CompanyVerifyState>("/api/users/me/company/confirm", b),
  companyRemove: () => del("/api/users/me/company"),
  deleteMe: () => del("/api/users/me"),
};
/** 비서의 파일 한 개 (plan/55). 주소는 서버가 서명해서 준다 — 화면은 만들지 않는다. */
export type FileKind = "image" | "pdf" | "document" | "sheet" | "slides" | "text" | "audio" | "other";
export interface AgentFileItem {
  /** 들어온 비서 — Drive·직접 모은 파일, 지운 비서가 받았던 파일은 비어 있다(plan/77). */
  id: string; agent_id: string | null; agent_name: string; source: "chat" | "messenger" | "public" | "manual" | "drive"; scope: "owner" | "visitor";
  visitor_id: string | null; conversation_id: string | null; filename: string; mime: string; kind: FileKind; size: number;
  caption: string; preview: string; text_chars: number; pages: number; status: "pending" | "ready" | "unreadable";
  created_at: string | null; url: string; thumb_url: string | null; error?: string | null;
  /** 상세에서만: 같은 바이트의 지식 문서가 있으면 그 id, 지식이 받는 형식인가. */
  knowledge_document_id?: string | null; can_promote?: boolean;
}
export interface StorageSegment { key: string; kind: "knowledge" | "agent" | "files" | "messenger" | "other"; bytes: number; files: number; agent_id?: string; name?: string; accent?: string | null; visitor_files?: number }
export interface StorageUsage { used_bytes: number; limit_bytes: number; ratio: number; plan: string; segments: StorageSegment[] }
export const Files = {
  list: (q: { agent_id?: string; since?: string; until?: string; source?: string; kind?: string; q?: string; sort?: "recent" | "size"; limit?: number; offset?: number } = {}) =>
    get<{ items: AgentFileItem[]; total: number; total_bytes: number; unreadable: number }>("/api/files", { query: q }),
  get: (id: string) => get<AgentFileItem>(`/api/files/${id}`),
  text: (id: string, offset = 0, limit = 20000) => get<{ text: string; offset: number; total: number; truncated: boolean }>(`/api/files/${id}/text`, { query: { offset, limit } }),
  remove: (id: string) => del(`/api/files/${id}`),
  toKnowledge: (id: string) => post<{ document_id: string; title: string }>(`/api/files/${id}/to-knowledge`),
  /** 지운 지 30일이 안 된 파일을 되살린다 (plan/78). */
  restore: (id: string) => post<AgentFileItem>(`/api/files/${id}/restore`),
  storage: () => get<StorageUsage>("/api/storage"),
  /** [관리·설정 → 클라우드 관리] 한 장 (plan/78). */
  cloud: () => get<CloudOverview>("/api/cloud"),
};
export interface CloudOverview {
  usage: StorageUsage;
  totals: { files: number; unreadable: number; documents: number; trash_files: number; trash_bytes: number };
  by_source: { source: string; files: number; bytes: number }[];
  by_kind: { kind: string; files: number; bytes: number }[];
  largest: AgentFileItem[];
  trash: (AgentFileItem & { deleted_at: string; purge_at: string })[];
  keep_days: number;
  drive: DriveStatus;
}
/** Google Drive 와 [파일] (plan/75). 권한은 drive.file — 사용자가 Google 의 파일 선택 창에서 고른 파일과 이 앱이 만든 파일만. */
export interface DriveStatus { available: boolean; connected: boolean; picker: boolean }
export const Drive = {
  status: () => get<DriveStatus>("/api/drive/status"),
  /** 파일 선택 창을 여는 데 필요한 것 — 이 사람의 접근 토큰과 앱의 브라우저 키·프로젝트 번호. */
  picker: () => get<{ access_token: string; api_key: string; app_id: string }>("/api/drive/picker"),
  /** 고른 파일을 [내 정보 → 파일]로 — 파일은 계정의 것이다(plan/77). */
  import: (file_ids: string[]) =>
    post<{ imported: { id: string; name: string }[]; failed: { drive_id: string; code: string }[] }>("/api/drive/import", { file_ids }),
  /** [파일]의 파일을 내 Drive 의 "black-moa" 폴더에 올린다. */
  save: (file_id: string) => post<{ id: string; name: string; link: string }>("/api/drive/save", { file_id }),
};
/** [내 정보 → 스케줄] (plan/56). 시각은 전부 주인의 시간대 — 화면은 받은 글자를 그대로 쓴다. */
export interface ScheduleEvent {
  /** owner · secretary · meeting, 또는 가져온 바깥 달력의 공급자(google · kakao …). */
  id: string; source: string; readonly: boolean; title: string; all_day: boolean;
  start: string | null; end: string | null; start_date: string | null; end_date: string | null;
  location: string; note: string; busy: boolean; agent_id: string | null; inbox_item_id: string | null; attendees: string[];
}
/** 스케줄의 [연동] 탭에 붙일 수 있는 바깥 달력 하나 (plan/58). ``available`` 은 관리 설정에서 켜 두었는가. */
export interface CalendarSource {
  provider: string; label: string; available: boolean; connected: boolean;
  account?: string; status?: string; error?: string | null;
  read?: boolean; write?: boolean; read_granted?: boolean; write_granted?: boolean;
  /** 자동으로 가져오는 간격(분). 0 은 끔. */
  auto_every?: number; last_sync?: string | null; events?: number;
  /** 마지막 가져오기가 실패했다면 그 까닭(calendar_forbidden · calendar_failed). 연결은 살아 있다(plan/76). */
  sync_error?: string | null;
}
export interface WeeklyRow { days: number[]; start: string; end: string }
/** 연락 가능 시간. 공개 범위는 없다 — 외부인에게 빈 시간을 알려 줄지는 비서의 [지식] 탭이 정한다 (plan/57). */
export interface Availability { weekly: WeeklyRow[]; note: string; timezone: string;
  /** 공휴일에는 빈 시간을 내지 않는다 (plan/60). */
  skip_holidays: boolean }
/** 한국의 특별한 날 하나 (plan/60). off 면 쉬는 날(공휴일·대체공휴일·선거일·임시공휴일). */
export interface SpecialName { name: string; kind: "holiday" | "festival" | "solar_term" | "anniversary"; off: boolean }
/** 달력의 하루: 쉬는 날인가, 이름들, 음력. */
export interface DayInfo { off: boolean; names: SpecialName[]; lunar: { month: number; day: number; leap: boolean } | null }
/** 관리자 [연결 → 공휴일] (plan/60). */
export interface AdminHolidayYear {
  year: number; sources: Record<"holiday" | "festival" | "solar_term" | "anniversary", "kasi" | "builtin">;
  counts: Record<"holiday" | "festival" | "solar_term" | "anniversary", number>; off_days: number;
  /** 내용이 바뀔 때만 바뀐다 — 브라우저가 새로 받는 기준. */
  version: string; checked_at: string | null; changed_at: string | null;
  /** 한 해치가 다 발표됐는가 — 그러면 공휴일만 확인한다. */
  complete: boolean;
  only_official: { date: string; name: string }[]; only_builtin: { date: string; name: string }[];
}
/** 다운로드 센터 (plan/64): GitHub 릴리스에서 옮겨 둔 앱 설치본. */
export interface AppAsset { id: string; name: string; platform: "windows" | "macos" | "linux"; arch: "x64" | "arm64" | "universal"; kind: "exe" | "dmg" | "deb"; size: number; sha256: string | null; ready: boolean; url: string | null }
export interface AppReleaseOut { tag: string; version: string; name: string; notes: string; published_at: string | null; prerelease: boolean; assets: AppAsset[] }
export const Downloads = {
  list: () => get<{ latest: AppReleaseOut | null; releases: AppReleaseOut[] }>("/api/downloads"),
};
export interface AdminDownloads {
  enabled: boolean; repo: string; tag_prefix: string; token: { has_value: boolean; masked: string };
  /** 릴리스를 굽는 CI 가 알려 오는가(열쇠가 있나), 지금 CI 가 건넨 짧은 토큰으로 옮기는 중인가. */
  ci: { has_key: boolean; session: boolean };
  status: { ok?: boolean; at?: string; code?: string; error?: string; releases?: number; queued?: number };
  releases: (AppReleaseOut & { files: { name: string; platform: string; arch: string; size: number; status: "pending" | "ready" | "failed"; error: string; tries: number; downloads: number; mirrored_at: string | null }[] })[];
}
export interface AdminHolidays {
  enabled: boolean; key: { has_value: boolean; masked: string }; dataset_url: string; builtin: string;
  years: AdminHolidayYear[]; last_error: { at: string; code: string; detail: string } | null;
}
export interface EventInput { title?: string; all_day?: boolean; start?: string; end?: string | null; location?: string; note?: string; busy?: boolean | null }
export const Schedule = {
  /** 이 사람의 일정만. 공휴일·음력은 한 해치로 따로 받아 기기에 둔다(lib/specialDays, plan/60). */
  range: (from: string, to: string) => get<{ timezone: string; events: ScheduleEvent[] }>("/api/schedule", { query: { from, to } }),
  create: (b: EventInput) => post<ScheduleEvent>("/api/schedule/events", b),
  update: (id: string, b: EventInput) => patch<ScheduleEvent>(`/api/schedule/events/${id}`, b),
  remove: (id: string) => del(`/api/schedule/events/${id}`),
  availability: () => get<Availability>("/api/schedule/availability"),
  saveAvailability: (b: { weekly?: WeeklyRow[]; note?: string; skip_holidays?: boolean }) => put<Availability>("/api/schedule/availability", b),
  sources: () => get<{ items: CalendarSource[] }>("/api/schedule/sources"),
  patchSource: (provider: string, b: { read?: boolean; write?: boolean; auto_every?: number }) =>
    patch<{ items: CalendarSource[]; consent_url: string | null }>(`/api/schedule/sources/${provider}`, b),
  connectSource: (provider: string) => post<{ url: string }>(`/api/schedule/sources/${provider}/connect`),
  syncSource: (provider: string) => post<{ events: number; items: CalendarSource[] }>(`/api/schedule/sources/${provider}/sync`),
};

/** [내 정보 → 메일] (plan/57). 비서는 Google 에 직접 닿지 않고 여기를 본다 — 나와의 대화에서만. */
export interface MailAccount { id: string; provider: string; provider_label: string; account: string; status: string; can_read: boolean; last_sync: string | null; count: number; error: string | null;
  /** 메일함 연결(IMAP, plan/74)을 만든 서비스 — gmail · naver · daum · kakao · custom. 다시 연결할 때 채워 둔다. */
  preset?: string }
export interface MailItem { id: string; from: string; to: string[]; subject: string; snippet: string; summary: string; unread: boolean; important: boolean; received_at: string | null }
export interface SentMail { id: string; to: string; subject: string; agent: string; agent_id: string | null; at: string | null }
export const Mail = {
  list: (q: { q?: string; before?: string; limit?: number } = {}) =>
    get<{ accounts: MailAccount[]; items: MailItem[]; next_before: string | null }>("/api/mail", { query: q }),
  read: (id: string) => get<MailItem & { body: string; date: string; account: string; provider: string }>(`/api/mail/${id}`),
  sync: () => post<{ queued: number }>("/api/mail/sync"),
  sent: () => get<{ items: SentMail[] }>("/api/mail/sent"),
  /** 메일함 연결 — IMAP + 앱 비밀번호 (plan/74). 서버가 먼저 로그인해 보고 저장한다. */
  addAccount: (b: { preset: string; email: string; password: string; host?: string | null }) =>
    post<{ accounts: MailAccount[] }>("/api/mail/accounts", b),
  removeAccount: (id: string) => del<{ accounts: MailAccount[] }>(`/api/mail/accounts/${id}`),
};

/** 비서가 사람끼리 방을 읽어도 된다는 허락 (plan/55 §6-4). */
export interface RoomGrant {
  id: string; agent: { id: string; name: string; avatar_url: string | null }; room_id: string;
  person: { name: string; handle: string; avatar_url: string | null }; scope: "conversation" | "always";
  conversation_id: string | null; reason: string; granted_at: string; last_read_at: string | null;
}
export const RoomAccess = {
  decide: (agentId: string, b: { message_id: string; room_id: string | null; choice: "conversation" | "always" | "deny" }) =>
    post<{ decided: { choice: string; room_id: string | null; grant_id: string | null; at: string } }>(`/api/agents/${agentId}/room-access`, b),
  list: (q: { room_id?: string; agent_id?: string } = {}) => get<{ items: RoomGrant[] }>("/api/room-grants", { query: q }),
  revoke: (id: string) => del(`/api/room-grants/${id}`),
};
export const Knowledge = {
  docs: (q: { kind?: string; status?: string } = {}) => get<{ items: KnowledgeDoc[]; usage_bytes: number; max_mb: number; semantic_search: boolean }>("/api/knowledge/documents", { query: q }),
  create: (fd: FormData) => post<KnowledgeDoc>("/api/knowledge/documents", fd),
  get: (id: string) => get<KnowledgeDoc>(`/api/knowledge/documents/${id}`),
  patch: (id: string, b: Json) => patch<KnowledgeDoc>(`/api/knowledge/documents/${id}`, b),
  remove: (id: string) => del(`/api/knowledge/documents/${id}`),
  chunks: (id: string) => get<{ items: { ordinal: number; heading: string | null; page: number | null; tokens: number; text: string }[]; total: number }>(`/api/knowledge/documents/${id}/chunks`),
  reindex: (id: string) => post<KnowledgeDoc>(`/api/knowledge/documents/${id}/reindex`),
  /** 내 지식에서 찾는다. `viewer` 로 남이 보면 무엇이 나오는지 미리 볼 수 있다. */
  search: (q: string) => get<{ items: any[] }>("/api/knowledge/search", { query: { q } }),
  faqs: () => get<{ items: Faq[] }>("/api/knowledge/faqs"),
  createFaq: (b: Json) => post<{ id: string }>("/api/knowledge/faqs", b),
  patchFaq: (id: string, b: Json) => patch(`/api/knowledge/faqs/${id}`, b),
  deleteFaq: (id: string) => del(`/api/knowledge/faqs/${id}`),
  importFaqs: (file: File, visibility = "public") => { const fd = new FormData(); fd.append("file", file); fd.append("visibility", visibility); return post<{ imported: number }>("/api/knowledge/faqs/import", fd); },
};
export const Network = {
  graph: (q: Record<string, string | undefined> = {}) => get<{ nodes: NetNode[]; edges: NetEdge[]; truncated?: boolean; center?: string; self_id?: string | null }>("/api/network/graph", { query: q }),
  stats: () => get<{ nodes: number; edges: number; kinds: Record<string, number>; top_tags: [string, number][] | { tag: string; count: number }[] }>("/api/network/stats"),
  nodes: (q: { q?: string; kind?: string; tag?: string } = {}) => get<{ items: NetNode[] }>("/api/network/nodes", { query: { ...q, limit: 200 } }),
  /** A published secretary as the graph's panel needs it: who it is, and my memo. */
  agentSubject: (id: string) => get<{ kind: "agent"; id: string; name: string; avatar_url: string | null; link_code: string; notes: string; owner: { id: string; name: string } | null }>(`/api/network/subjects/agent/${id}`),
  agentMemo: (id: string, body: string) => put<{ notes: string }>(`/api/network/subjects/agent/${id}/memo`, { body }),
  node: (id: string) => get<NetNode & { edges: NetEdge[]; neighbors: NetNode[]; interactions: { id: string; kind: string; at: string; summary: string }[] }>(`/api/network/nodes/${id}`),
  createNode: (b: Json) => post<NetNode>("/api/network/nodes", b),
  patchNode: (id: string, b: Json) => patch<NetNode>(`/api/network/nodes/${id}`, b),
  deleteNode: (id: string) => del(`/api/network/nodes/${id}`),
  addInteraction: (id: string, b: { kind: string; at: string; summary: string }) => post(`/api/network/nodes/${id}/interactions`, b),
  createEdge: (b: Json) => post<NetEdge>("/api/network/edges", b),
  deleteEdge: (id: string) => del(`/api/network/edges/${id}`),
  proposals: (status = "pending") => get<{ items: Proposal[] }>("/api/network/proposals", { query: { status } }),
  decide: (id: string, d: "accept" | "reject") => post(`/api/network/proposals/${id}/${d}`),
  importCsv: (file: File) => { const fd = new FormData(); fd.append("file", file); return post<{ imported: number }>("/api/network/import/csv", fd); },
  // People (plan/31): the directory, friend links, and the guests who actually showed up.
  peopleSearch: (q: string) => get<{ items: Account[] }>("/api/network/people/search", { query: { q } }),
  links: () => get<{ friends: Account[]; incoming: Account[]; outgoing: Account[] }>("/api/network/people/links"),
  removeLink: (userId: string) => del(`/api/network/people/links/${userId}`),
  /** Connecting is the whole relationship (plan/43): one way, immediate, and both
   *  sides doing it is what 인맥 means. */
  follow: (userId: string) => post<{ following: boolean; added: boolean; status: "mutual" | "outgoing" | "incoming" | "none" }>(`/api/network/people/${userId}/follow`),
  unfollow: (userId: string) => del<{ following: boolean; status: "mutual" | "outgoing" | "incoming" | "none" }>(`/api/network/people/${userId}/follow`),
  /** 이 사람과 지금 어떤 사이인가 (plan/69) — 사이트의 모든 인맥 단추가 이것 하나를 읽는다. */
  link: (userId: string) => get<{ status: "mutual" | "outgoing" | "incoming" | "none" | "self"; direction?: string }>(`/api/network/people/${userId}/link`),
  suggestions: () => get<{ items: Suggestion[] }>("/api/network/people/suggestions"),
  /** Who `@` may offer in a caption: people I am connected to, either way (plan/42 §11). */
  mentionable: (q: string) => get<{ items: Mentionable[] }>("/api/network/people/mentionable", { query: { q } }),
  /** One page of somebody's posts, filtered to what I may see. */
  posts: (id: string, page = 1, limit = 12) =>
    get<{ items: BlogPost[]; page: number; pages: number; total: number }>(`/api/network/people/${id}/posts`, { query: { page, limit } }),
  profile: (userId: string) => get<MemberProfile>(`/api/network/people/${userId}`),
  guests: () => get<{ items: Guest[] }>("/api/network/guests"),
  addGuest: (visitorId: string) => post<NetNode>(`/api/network/guests/${visitorId}`),
};
export const Integrations = {
  list: () => get<{ providers: IntegrationProvider[]; connections: Connection[] }>("/api/integrations"),
  /** 연결을 마치면 ``next`` 로 돌아온다 — [메일]·[스케줄]·[알림] 에서 시작했으면 그리로. 이미 허락한 권한은 서버가 지킨다. */
  start: (provider: string, capabilities: string[], next?: string) =>
    post<{ url: string }>(`/api/integrations/${provider}/start`, { capabilities, next }, { credentials: "include" }),
  sync: (id: string) => post(`/api/integrations/${id}/sync`),
  /** 아직 받지 않은 권한을 켜면 바꾸지 않고 ``consent_url`` 을 준다. */
  patch: (id: string, capabilities: string[], next?: string) =>
    patch<Connection & { consent_url: string | null }>(`/api/integrations/${id}`, { capabilities, next }, { credentials: "include" }),
  disconnect: (id: string) => del(`/api/integrations/${id}`),
};
export const Notifications = {
  channels: () => get<{ items: Channel[]; events: string[]; kinds: string[]; telegram_bot: string }>("/api/notifications/channels"),
  createChannel: (b: { kind: string; config: Json; label?: string }) => post<Channel>("/api/notifications/channels", b),
  patchChannel: (id: string, b: Json) => patch<Channel>(`/api/notifications/channels/${id}`, b),
  deleteChannel: (id: string) => del(`/api/notifications/channels/${id}`),
  testChannel: (id: string) => post<{ ok: boolean; error?: string }>(`/api/notifications/channels/${id}/test`),
  sendChannelCode: (id: string) => post<Channel>(`/api/notifications/channels/${id}/verify/send`),
  verifyChannel: (id: string, code: string) => post<Channel>(`/api/notifications/channels/${id}/verify`, { code }),
  rules: () => get<{ items: Rule[] }>("/api/notifications/rules"),
  createRule: (b: Json) => post<Rule>("/api/notifications/rules", b),
  patchRule: (id: string, b: Json) => patch<Rule>(`/api/notifications/rules/${id}`, b),
  deleteRule: (id: string) => del(`/api/notifications/rules/${id}`),
  log: () => get<{ items: { id: string; event: string; status: string; error: string | null; channel_id: string | null; created_at: string; sent_at: string | null }[] }>("/api/notifications/log"),
  telegramLink: () => post<{ code: string; bot_username: string; instructions: string }>("/api/notifications/telegram/link"),
};
export interface LoginSnapshot {
  running: boolean; done: boolean; ok?: boolean; exit_code?: number | null; url?: string | null;
  awaiting_input?: boolean; seq?: number; lines: { seq: number; kind: string; text: string }[];
}

/** One authenticated Claude Code identity in the load-balanced pool (plan/30). */
export interface ClaudeAccount {
  id: string; label: string; email: string | null; auth_mode: string; enabled: boolean;
  weight: number; max_concurrency: number; status: string; in_flight: number; usable: boolean;
  /** eligible = would be handed the next session right now; the reason says why not. */
  eligible: boolean; ineligible_reason: string | null; cooldown_until: string | null;
  consecutive_failures: number; total_leases: number; total_failures: number;
  last_used_at: string | null; last_ok_at: string | null; last_probe_at: string | null;
  last_error: string | null; subscription: string | null; rate_limit_tier: string | null;
  session_expires_at: string | null; access_expires_at: string | null;
  has_setup_token: boolean; has_api_key: boolean; credentials_present: boolean; notes: string | null;
}
export interface ClaudePool {
  enabled: boolean; active: boolean; strategy: string; strategies: string[];
  policy: { failure_threshold: number; failure_cooldown_s: number; rate_limit_cooldown_s: number; quota_cooldown_s: number };
  accounts: ClaudeAccount[];
  counts: { total: number; eligible: number; enabled: number; in_flight: number };
}

// ── traffic (plan/40) ───────────────────────────────────────────────
export interface PoolStat { size: number; in_flight: number; queued: number; peak_in_flight: number; calls: number; avg_wait_ms: number; avg_run_ms: number; slowest_ms: number; slowest: string }
export interface LiveRequest { id: string; route: string; method: string; lane: string; elapsed_ms: number; ip: string; owner_id: string | null; streaming: boolean; silent_ms: number; stuck: boolean }
export interface DbLaneStat { in_use: number; ceiling: number; acquired: number; peak: number; waits: number; avg_wait_ms: number; rejected: number }
export interface DbStats {
  capacity: number; checked_out: number; in_use: number; generation: number;
  healthy: boolean; seconds_since_ok: number; consecutive_failures: number;
  reconnects: number; retries: number; last_error: string; lanes: Record<string, DbLaneStat>;
}
export interface TrafficOverview {
  fleet?: {
    processes: { key: string; role: string; age_s: number; fresh: boolean; loop_lag_s: number;
                 pools: Record<string, { size: number; in_flight: number; queued: number }>;
                 db: { capacity: number; checked_out: number };
                 sessions?: number; in_flight?: number; served?: number;
                 worker?: { concurrency: number; class_limits: Record<string, number>; reserved: Record<string, number> } }[];
    pools: Record<string, { size: number; in_flight: number; queued: number }>;
    db: { capacity: number; checked_out: number };
    fresh: number; stale: string[];
  };
  summary: {
    window_minutes: number;
    overall: { n: number; avg_ms: number; p50: number; p95: number; p99: number; max_ms: number; longest_ms: number; errors: number; throttled: number; slow: number; lag_ms: number };
    lanes: { lane: string; n: number; avg_ms: number; p95_ms: number; errors: number; max_ms: number }[];
  };
  series: { at: string; n: number; avg_ms: number; p95_ms: number; errors: number }[];
  process: { loop_lag_s: number; pools: Record<string, PoolStat>; db: DbStats; sessions: number; served: number; in_flight: number; buffered: number; dropped: number; by_lane: Record<string, number> };
  in_flight: LiveRequest[];
}
export interface TrafficEndpoint { route: string; method: string; lane: string; n: number; avg_ms: number; p95_ms: number; max_ms: number; total_ms: number; errors: number; throttled: number }
export interface TrafficAnomaly { at: string; route: string; method: string; lane: string; status: number; ms: number; ttfb_ms: number; lag_ms: number; owner_id: string | null; ip: string; error: string | null }
export interface TrafficCaller { owner_id: string | null; email: string | null; name: string | null; ip: string; n: number; total_ms: number; errors: number; throttled: number }

// ── system console (plan/46) ────────────────────────────────────────
export interface LlmStat { calls: number; failures: number; in_flight: number; peak_in_flight: number; avg_ms: number; max_ms: number; input_tokens: number; output_tokens: number; error_rate: number; seconds_since_last: number | null; last_error: string; codes: Record<string, number> }
export interface LlmCall { id: string; provider: string; model: string; kind: string; elapsed_ms: number; owner_id: string | null; agent_id: string | null; account: string; stuck: boolean }
export interface LlmRecent { provider: string; model: string; kind: string; ms: number; ok: boolean; code: string | null; account: string; owner_id: string | null; error: string; input_tokens: number; output_tokens: number; at: number }
export interface LlmSession { key: string; session_id: string; agent_id: string; conversation_id: string; audience: string; turns: number; idle_s: number; busy: boolean; tools: number; context_window: number; account: string; account_held_s: number | null; provider: string; model: string; agent_name: string; owner_name: string }
export interface LlmOverview {
  totals: { calls: number; failures: number; error_rate: number; avg_ms: number; in_flight: number; stuck: number; input_tokens: number; output_tokens: number };
  providers: Record<string, LlmStat>; models: Record<string, LlmStat>; kinds: Record<string, LlmStat>;
  in_flight: LlmCall[]; recent: LlmRecent[];
  load: { llm_pool: PoolStat; loop_lag_s: number };
  pool: any; providers_configured: { id: string; configured: boolean; models: number; verdict: boolean | null; checked_at: string | null }[];
  sessions: LlmSession[];
}
export interface DbTable { name: string; rows: number; size_mb: number; comment: string | null }
export interface DbColumn { name: string; type: string; nullable: boolean; masked: boolean }
export interface DbResult { columns: string[]; rows: Record<string, unknown>[]; row_count: number; truncated: boolean; masked: string[]; limit: number; sql: string }
export interface JobsOverview {
  kinds: { kind: string; queued: number; running: number; done: number; failed: number; dead: number; avg_s: number; p95_s: number; oldest_running_s: number; oldest_wait_s: number }[];
  series: { at: string; done: number; failed: number; avg_s: number }[];
  owners: { owner_id: string | null; name: string; queued: number; oldest_wait_s: number }[];
  running: { id: string; kind: string; worker: string; attempts: number; owner_id: string | null; elapsed_s: number }[];
  workers: { id: string; last_seen_at: string; info: Record<string, unknown>; stale: boolean }[];
  limits: { concurrency: number; kinds: Record<string, number>; classes: Record<string, number>; kind_class: Record<string, string> };
  window_hours: number;
}

export interface TriggerRule {
  key: string; label: string; enabled: boolean; kind: string;
  when: { state: string; silent_days?: [number, number | null]; after_days?: [number, number]; occasion?: string;
          /** 함께한 날: 처음 대화한 날부터 센 날수, 그리고 사이가 가까워진 날에도 울리는지 */
          days?: number[]; stage_up?: boolean };
  window: [number, number]; per_day: number; once: boolean; next: string; tone: string;
}
export interface TriggerLogItem {
  id: string; at: string; text: string; conversation_id: string;
  agent: { id: string; name: string; avatar_url: string | null }; owner: { id: string; name: string };
  kind: string; rule: string; label: string; model: string; tokens: number; worth: number;
  repeat: boolean; replied_at: string | null; reply: string;
}
export interface TriggerLog {
  since: string; until: string; total: number; items: TriggerLogItem[];
  summary: { count: number; people: number; worth: number; usd: number; replied: number; repeats: number };
  facets: { agents: { id: string; name: string }[]; rules: { key: string; label: string }[] };
}
export interface TriggerTestResult {
  text: string; empty: boolean; agent: { id: string; name: string; avatar_url: string | null };
  rule: string; label: string; kind: string; occasion: string; situation: string; model: string; provider: string; fell_back: boolean;
  tokens: { input: number; output: number };
}
export interface TriggerEvent { day: number; date: string; hour: number; rule: string; label: string; state: string; silent_days: number }
export interface TriggerView {
  enabled: boolean; provider: string; model: string; max_per_day: number; lapse_after_days: number; min_gap_minutes: number;
  rules: TriggerRule[]; rules_valid: boolean; labels: Record<string, string>; kinds: string[]; hard_max_per_day: number;
  running: { provider: string; model: string; fell_back: boolean };
  states: Record<string, number>;
  today_worth: number;
  recent: { at: string; agent: string; owner: string; kind: string; rule: string; pair: string }[];
  defaults: TriggerRule[];
}

export const Admin = {
  overview: () => get<any>("/api/admin/overview"),
  settings: (prefix = "") => get<Record<string, any>>("/api/admin/settings", { query: { prefix } }),
  putSettings: (values: Json) => put<Record<string, any>>("/api/admin/settings", { values }),
  clearSetting: (key: string) => del(`/api/admin/settings/${key}`),
  /** 기본 이용약관·개인정보 처리방침의 원문(자리표시 그대로) — plan/73. */
  legalDefault: (kind: "terms" | "privacy") => get<{ kind: string; text: string; version: string }>(`/api/admin/legal/default/${kind}`),
  providers: () => get<{ providers: { id: string; configured: boolean; masked: string; status: { verdict: boolean | null; detail: unknown; at: string } | null }[]; claude_code: any }>("/api/admin/providers"),
  putProvider: (id: string, api_key: string) => put<{ id: string; verdict: boolean | null; detail: unknown }>(`/api/admin/providers/${id}`, { api_key }),
  // verdict is tri-state: true verified, false rejected, null could not be checked
  verifyProvider: (id: string) => post<{ id: string; verdict: boolean | null; detail: unknown }>(`/api/admin/providers/${id}/verify`),
  claudeMode: (auth_mode: string, setup_token?: string) => put<any>("/api/admin/providers/claude-code/mode", { auth_mode, setup_token }),
  claudeImport: (credentials_json: string) => post<any>("/api/admin/providers/claude-code/import", { credentials_json }),
  claudeProbe: () => post<any>("/api/admin/providers/claude-code/probe"),
  claudeRestore: () => post<any>("/api/admin/providers/claude-code/restore"),
  // Which account type the browser flow asks for follows the saved auth mode.
  claudeLoginStart: (opts?: { email?: string | null }) =>
    post<LoginSnapshot & { started: boolean }>("/api/admin/providers/claude-code/login/start", { email: opts?.email ?? null }),
  claudeLoginState: () => get<LoginSnapshot>("/api/admin/providers/claude-code/login"),
  claudeLoginInput: (text: string) => post("/api/admin/providers/claude-code/login/input", { text }),
  claudeLoginCancel: () => post("/api/admin/providers/claude-code/login/cancel"),
  // Account pool. Every account carries its own login relay, so these mirror the
  // single-account calls above with an id in the path.
  claudePool: () => get<ClaudePool>("/api/admin/providers/claude-code/accounts"),
  claudePoolSettings: (b: { enabled?: boolean; strategy?: string }) => put<ClaudePool>("/api/admin/providers/claude-code/pool", b),
  claudeAccountCreate: (b: Json) => post<ClaudeAccount>("/api/admin/providers/claude-code/accounts", b),
  claudeAccountPatch: (id: string, b: Json) => patch<ClaudeAccount>(`/api/admin/providers/claude-code/accounts/${id}`, b),
  claudeAccountDelete: (id: string) => del(`/api/admin/providers/claude-code/accounts/${id}`),
  claudeAccountImport: (id: string, credentials_json: string) => post<ClaudeAccount>(`/api/admin/providers/claude-code/accounts/${id}/import`, { credentials_json }),
  claudeAccountProbe: (id: string) => post<{ ok: boolean; error?: string; ms?: number; text?: string }>(`/api/admin/providers/claude-code/accounts/${id}/probe`),
  claudeAccountClearCooldown: (id: string) => post<ClaudeAccount>(`/api/admin/providers/claude-code/accounts/${id}/cooldown/clear`),
  claudeAccountLoginStart: (id: string, email?: string | null) =>
    post<LoginSnapshot & { started: boolean }>(`/api/admin/providers/claude-code/accounts/${id}/login/start`, { email: email ?? null }),
  claudeAccountLoginState: (id: string) => get<LoginSnapshot>(`/api/admin/providers/claude-code/accounts/${id}/login`),
  claudeAccountLoginInput: (id: string, text: string) => post(`/api/admin/providers/claude-code/accounts/${id}/login/input`, { text }),
  claudeAccountLoginCancel: (id: string) => post(`/api/admin/providers/claude-code/accounts/${id}/login/cancel`),
  models: () => get<{ items: any[] }>("/api/admin/models"),
  // 비서 트리거 이벤트 (plan/54): 규칙·모델은 관리자의 것이다.
  triggers: () => get<TriggerView>("/api/admin/triggers"),
  putTriggers: (b: Json) => put<TriggerView>("/api/admin/triggers", b),
  triggerLog: (q: { since?: string; until?: string; agent?: string; rule?: string; replied?: string; offset?: number; limit?: number }) =>
    get<TriggerLog>("/api/admin/triggers/log", { query: q }),
  /** 내 비서로 규칙 하나의 말을 받아 본다. 비서에는 아무것도 남지 않는다. */
  testTrigger: (agent_id: string, rule: TriggerRule) => post<TriggerTestResult>("/api/admin/triggers/test", { agent_id, rule }),
  simulateTriggers: (b: Json, days = 30, talk_days = "0") =>
    post<{ days: number; talk_days: number[]; events: TriggerEvent[] }>("/api/admin/triggers/simulate", b, { query: { days, talk_days } }),
  seedModels: (overwrite = false) => post<{ added: number; alias_repaired: number; default_moved: string }>("/api/admin/models/seed", undefined, { query: { overwrite_prices: overwrite } }),
  discover: (provider: string) => get<{ items: string[]; aliases: string[]; note?: string }>("/api/admin/models/discover", { query: { provider } }),
  createModel: (b: Json) => post<any>("/api/admin/models", b),
  patchModel: (id: string, b: Json) => patch<any>(`/api/admin/models/${id}`, b),
  deleteModel: (id: string) => del(`/api/admin/models/${id}`),
  plans: () => get<{ items: any[] }>("/api/admin/plans"),
  createPlan: (b: Json) => post<any>("/api/admin/plans", b),
  patchPlan: (id: string, b: Json) => patch<any>(`/api/admin/plans/${id}`, b),
  users: (q = "", page = 1) => get<{ items: any[]; total: number }>("/api/admin/users", { query: { q, page, size: 50 } }),
  user: (id: string) => get<any>(`/api/admin/users/${id}`),
  grant: (id: string, delta: number, note: string) => post<{ balance: number }>(`/api/admin/users/${id}/credits`, { delta, note }),
  role: (id: string, role: string) => post<{ role: string }>(`/api/admin/users/${id}/role`, { role }),
  patchUser: (id: string, b: Json) => patch<any>(`/api/admin/users/${id}`, b),
  deleteUser: (id: string) => del(`/api/admin/users/${id}`),
  usage: (days = 30) => get<any>("/api/admin/usage", { query: { days } }),
  invites: () => get<{ items: any[] }>("/api/admin/invites"),
  createInvite: (b: Json) => post<{ code: string }>("/api/admin/invites", b),
  deleteInvite: (id: string) => del(`/api/admin/invites/${id}`),
  communityOverview: () => get<{ posts: number; posts_7d: number; comments: number; open_reports: number; jobs: number;
    boards: { id: string; slug: string; name: string; description: string; kind: string; icon: string; sort_order: number; enabled: boolean; post_count: number }[] }>("/api/admin/community/overview"),
  createBoard: (b: Json) => post<{ id: string }>("/api/admin/community/boards", b),
  patchBoard: (id: string, b: Json) => patch<{ ok: boolean }>(`/api/admin/community/boards/${id}`, b),
  communityReports: (status = "open") => get<{ items: any[] }>("/api/admin/community/reports", { query: { status } }),
  resolveReport: (id: string, action: "hide" | "dismiss") => post<{ ok: boolean }>(`/api/admin/community/reports/${id}/resolve`, undefined, { query: { action } }),
  communityPosts: (status = "published") => get<{ items: any[] }>("/api/admin/community/posts", { query: { status } }),
  setPostStatus: (id: string, status: string) => post<{ ok: boolean }>(`/api/admin/community/posts/${id}/status`, undefined, { query: { status } }),
  jobs: (status?: string) => get<{ items: any[]; counts: Record<string, number>; workers: any[] }>("/api/admin/jobs", { query: { status } }),
  retryJob: (id: string) => post(`/api/admin/jobs/${id}/retry`),
  discardJob: (id: string) => post(`/api/admin/jobs/${id}/discard`),
  audit: (q: { action?: string } = {}) => get<{ items: any[] }>("/api/admin/audit", { query: q }),
  health: () => get<any>("/api/admin/health"),
  reindex: () => post<{ queued: number }>("/api/admin/embedding/reindex"),
  smtpTest: (to: string) => post<{ ok: boolean; error?: string }>("/api/admin/smtp/test", { to }),
  /** [연결] (plan/59) — 공급자마다 켜기 · 로그인 · 기능 · 앱 키 · 설정 확인. */
  connections: () => get<{ site_url: string; providers: AdminConnection[] }>("/api/admin/connections"),
  saveConnection: (provider: string, b: { enabled?: boolean; login?: boolean; features?: string[]; values?: Record<string, string | boolean>; clear?: string[] }) =>
    put<AdminConnection>(`/api/admin/connections/${provider}`, b),
  checkConnection: (provider: string) => post<ConnectionCheck>(`/api/admin/connections/${provider}/check`),
  /** [연결 → 공휴일] (plan/60) — 한국천문연구원 특일 정보. */
  downloads: () => get<AdminDownloads>("/api/admin/downloads"),
  saveDownloads: (b: { enabled?: boolean; repo?: string; tag_prefix?: string; token?: string; clear_token?: boolean }) => put<AdminDownloads>("/api/admin/downloads", b),
  checkDownloads: () => post<{ ok: boolean; code?: string; message?: string; private?: boolean; releases?: number }>("/api/admin/downloads/check"),
  syncDownloads: () => post<{ queued: boolean }>("/api/admin/downloads/sync"),
  holidays: () => get<AdminHolidays>("/api/admin/holidays"),
  saveHolidays: (b: { enabled?: boolean; key?: string; clear_key?: boolean }) => put<AdminHolidays>("/api/admin/holidays", b),
  checkHolidays: () => post<{ ok: boolean; code: string; detail?: string; items?: number }>("/api/admin/holidays/check"),
  syncHolidays: () => post<{ queued: boolean }>("/api/admin/holidays/sync"),
  traffic: (minutes = 60) => get<TrafficOverview>("/api/admin/traffic", { query: { minutes } }),
  trafficEndpoints: (minutes = 60, order = "total_ms") => get<{ items: TrafficEndpoint[] }>("/api/admin/traffic/endpoints", { query: { minutes, order } }),
  trafficAnomalies: (minutes = 180) => get<{ items: TrafficAnomaly[] }>("/api/admin/traffic/anomalies", { query: { minutes } }),
  trafficCallers: (minutes = 60) => get<{ items: TrafficCaller[] }>("/api/admin/traffic/callers", { query: { minutes } }),
  trafficQueue: () => get<{ items: { kind: string; status: string; n: number; oldest_running_s: number }[]; dead_last_day: number }>("/api/admin/traffic/queue"),
  llm: () => get<LlmOverview>("/api/admin/llm"),
  llmSessions: () => get<{ items: LlmSession[] }>("/api/admin/llm/sessions"),
  closeSession: (key: string) => del(`/api/admin/llm/sessions/${encodeURIComponent(key)}`),
  jobsOverview: (hours = 24) => get<JobsOverview>("/api/admin/jobs/overview", { query: { hours } }),
  diagServer: () => get<any>("/api/admin/diagnostics/server"),
  diagDatabase: () => get<any>("/api/admin/diagnostics/database"),
  diagStorage: () => get<any>("/api/admin/diagnostics/storage"),
  dbTables: () => get<{ items: DbTable[]; role: string; max_rows: number }>("/api/admin/diagnostics/db/tables"),
  dbColumns: (table: string) => get<{ items: DbColumn[] }>("/api/admin/diagnostics/db/columns", { query: { table } }),
  dbQuery: (sql: string, limit: number, table = "") => post<DbResult>("/api/admin/diagnostics/db/query", { sql, limit, table }),
  companySources: () => get<CompanySources>("/api/admin/companies/sources"),
  companyRuns: () => get<CompanyRuns>("/api/admin/companies/runs"),
  collectCompanies: (source: string) => post<{ queued: boolean; job_id: string | null }>(`/api/admin/companies/collect/${source}`),
  companies: (q: { q?: string; market?: string; region?: string; industry?: string; page?: number } = {}) =>
    get<{ items: CompanyRow[]; total: number; page: number; size: number }>("/api/admin/companies", { query: { size: 50, ...q } }),
  company: (id: string) => get<CompanyRow & CompanyDetail>(`/api/admin/companies/${id}`),
  patchCompany: (id: string, b: Json) => patch<CompanyRow & CompanyDetail>(`/api/admin/companies/${id}`, b),
  companyDomains: (id: string) => get<{ items: CompanyDomain[] }>(`/api/admin/companies/${id}/domains`),
  addCompanyDomain: (id: string, domain: string) => post<CompanyDomain>(`/api/admin/companies/${id}/domains`, { domain }),
  removeCompanyDomain: (id: string, domainId: string) => del(`/api/admin/companies/${id}/domains/${domainId}`),
  domainClaims: () => get<{ items: (CompanyDomain & { company_name: string; market: string; industry_text: string })[]; confirmed: number }>("/api/admin/companies/domain-claims"),
  decideDomainClaim: (id: string, action: "approve" | "reject") => post<{ ok: boolean }>(`/api/admin/companies/domain-claims/${id}/${action}`),
  setupComplete: () => post("/api/admin/setup/complete"),
};

// ── community ───────────────────────────────────────────────────────
export interface CommunityBoard { id: string; slug: string; name: string; description: string; kind: "discussion" | "jobs"; icon: string; post_count: number; people_count: number; last_post_at: string | null }
export interface CommunityAuthor { id: string; name: string; job: string; avatar_url: string | null; is_me: boolean; pen_name?: boolean }
export interface CommunityPost {
  id: string; title: string; excerpt?: string; body?: string;
  board: { slug: string; name: string; icon: string } | null;
  author: CommunityAuthor | null;
  comment_count: number; like_count: number; view_count: number; liked: boolean; images?: string[];
  created_at: string; edited_at: string | null; version: number;
}
export interface CommunityComment {
  id: string; parent_id: string | null; depth: number; body: string; deleted: boolean;
  like_count: number; liked: boolean; created_at: string; author: CommunityAuthor | null;
}

/** The employer, when a posting is linked to a real company (plan/33 §5). */
export interface CompanyBrief {
  id: string; name: string; market: string; stock_code: string | null;
  industry_text: string; region_text: string; homepage: string; ceo: string;
  status: string; employees: number | null; listed_on: string | null;
  rating: number; review_count: number;
}
export interface CommunityJob {
  id: string; title: string; company: string; location: string; employment_type: string;
  experience_min: number; salary_min: number | null; salary_max: number | null; tags: string[];
  region_codes: string[]; job_codes: string[]; industry_codes: string[]; remote: boolean; job_labels: string[];
  description: string; apply_url: string; status: string; created_at: string; is_mine: boolean;
  /** The employer's own details, when the posting is linked to a real company. */
  company_info?: CompanyBrief | null;
  company_id?: string | null;
}

export type Facet = { value: string; count: number };
export interface TaxonomyNode { value: string; label: string; keywords?: string; children?: TaxonomyNode[] }
export interface JobTaxonomy { regions: TaxonomyNode[]; jobs: TaxonomyNode[]; industries: TaxonomyNode[]; employment_types: string[] }
export interface JobFacets {
  total: number; remote: number;
  region: Record<string, number>; job: Record<string, number>; industry: Record<string, number>;
  type: Record<string, number>; tags: Facet[];
}

export const Community = {
  me: () => get<{ readiness: { has_name: boolean; has_job: boolean; complete: boolean }; suggested_boards: string[]; can_write: boolean }>("/api/community/me"),
  boards: (kind?: string) => get<{ items: CommunityBoard[] }>("/api/community/boards", { query: { kind } }),
  posts: (q: { board?: string; sort?: string; limit?: number; cursor?: string; mine?: boolean; q?: string; author?: string } = {}) =>
    get<{ items: CommunityPost[]; next_cursor: string | null }>("/api/community/posts", { query: q }),
  post: (id: string) => get<CommunityPost>(`/api/community/posts/${id}`),
  createPost: (b: { board: string; title: string; body: string; client_token?: string; images?: string[] }) => post<{ id: string }>("/api/community/posts", b),
  editPost: (id: string, b: { title?: string; body?: string; version?: number; images?: string[] }) => patch<{ id: string; version: number }>(`/api/community/posts/${id}`, b),
  removePost: (id: string) => del(`/api/community/posts/${id}`),
  comments: (id: string, sort = "new") => get<{ items: CommunityComment[] }>(`/api/community/posts/${id}/comments`, { query: { sort } }),
  addComment: (id: string, b: { body: string; parent_id?: string | null }) => post<{ id: string }>(`/api/community/posts/${id}/comments`, b),
  editComment: (id: string, body: string) => patch<{ ok: boolean }>(`/api/community/comments/${id}`, { body }),
  removeComment: (id: string) => del(`/api/community/comments/${id}`),
  like: (target: "posts" | "comments", id: string) => post<{ liked: boolean; like_count: number }>(`/api/community/${target}/${id}/like`),
  report: (target: "posts" | "comments", id: string, reason: string, detail = "") => post<{ ok: boolean }>(`/api/community/${target}/${id}/report`, { reason, detail }),
  jobs: (q: { q?: string; region?: string; job?: string; industry?: string; employment_type?: string;
              max_experience?: number; min_salary?: number; max_salary?: number; remote?: boolean; tag?: string } = {}) =>
    get<{ items: CommunityJob[] }>("/api/community/jobs", { query: q }),
  jobTaxonomy: () => get<JobTaxonomy>("/api/community/jobs/taxonomy"),
  companySuggest: (q: string) =>
    get<{ items: { id: string; name: string; stock_code: string | null; market: string; industry_text: string; region_text: string }[] }>(
      "/api/community/companies/suggest", { query: { q } }),
  // 내 주변 맛집 (plan/34). The provider finds; our people rate.
  jobFacets: () => get<JobFacets>("/api/community/jobs/facets"),
  createJob: (b: Json) => post<{ id: string }>("/api/community/jobs", b),
  closeJob: (id: string) => post<{ ok: boolean }>(`/api/community/jobs/${id}/close`),
};

// ── companies (plan/33, plan/40) ────────────────────────────────────
export interface CompanyRow {
  id: string; name: string; stock_code: string | null; market: string;
  industry_text: string; industry_codes: string[]; region_code: string; region_text: string;
  ceo: string; homepage: string; status: string;
  /** What people say and do about it — the numbers a card shows (plan/40). */
  rating: number; review_count: number; follow_count: number; open_jobs: number; tags: string[];
  employees: number | null; listed_on: string | null;
}
/** A company as a search result or a shelf tile carries it. */
export interface CompanyCard extends CompanyRow {
  founded_on?: string | null; following: boolean;
  recommend?: number | null; salary_median?: number | null;
  /** On the "for me" row only: why this company is here, and how many of that. */
  why?: "jobs" | "reviews" | "industry"; n?: number;
}
export type Axis = "pay" | "balance" | "culture" | "promotion" | "management";
export interface SalaryStat { n: number; median: number; min: number; max: number; avg: number; bands?: Record<string, SalaryStat> }
export interface CompanyStats {
  n: number; rating: number; axes: Record<Axis, number>;
  recommend: number | null; ceo: number | null; growth: number | null;
  by_year: Record<string, { n: number; rating: number; axes: Record<Axis, number>; recommend: number | null }>;
  by_job: Record<string, { n: number; rating: number; salary: SalaryStat | null }>;
  salary: SalaryStat | null;
  interview: { n: number; difficulty: number | null; pass_rate: number | null } | null;
  benefits: { code: string; n: number }[];
  topics: Record<string, number>;
  employment: { current: number; former: number };
  /** Overall scores, five stars down to one. */
  dist?: Record<string, number>;
  /** Option counts per question (plan/40 §8): {"hours": {"h45_52": 3, "le40": 1}, …}. */
  facts?: Record<string, Record<string, number>>;
  /** How many reviews answered the questions (older ones carry stars only). */
  answered?: number;
  /** Reviews by people who proved a work mailbox at this company (plan/40 §10). */
  verified_n?: number;
  computed_at?: string;
}
export type Answers = Record<string, string | string[]>;
export interface QuestionSpec { code: string; area: Axis | null; required: boolean; multi: boolean; max: number | null; options: string[] }
export interface CompanyReview {
  id: string; company_id: string; status: string;
  employment: "current" | "former"; job_code: string; job_family: string; job_label: string; family_label: string;
  work_year: number; title: string; pros: string; cons: string; advice: string;
  rating: number; axes: Record<Axis, number>;
  recommend: boolean; ceo_approval: boolean | null; growth: "up" | "flat" | "down";
  salary: number | null; experience_years: number | null;
  interview: { difficulty?: number; result?: "pass" | "fail" | "pending"; questions?: string; process?: string };
  benefits: string[]; topics: string[];
  /** The concrete answers; empty on a review written before the questions existed. */
  answers: Answers;
  helpful_count: number; helpful: boolean; is_mine: boolean;
  /** Written by someone who proved a work mailbox at this company. */
  verified?: boolean;
  created_at: string; updated_at: string | null; version: number;
  company?: { id: string; name: string; market: string; industry_text: string; region_text: string };
}
export interface SalaryPick {
  company: CompanyCard; mentions: number; source: "reviews" | "jobs";
  snippet: { review_id?: string; title: string; excerpt?: string; rating?: number; family_label?: string; salary?: number | null;
             salary_min?: number | null; salary_max?: number | null; job_id?: string | null } | null;
}
export interface AreaPick extends CompanyCard {
  /** The area's score for this company and the fact that headlines the area. */
  score: number;
  fact: { question: string; option: string; n: number; total: number; pct: number } | null;
}
export interface CompanyHomeData {
  popular: CompanyCard[];
  /** The five areas a review speaks about, each with its top companies (plan/40 §9). */
  areas: { key: Axis; items: AreaPick[] }[];
  salary_top: SalaryPick[];
  for_me: { needs_profile: boolean; items: CompanyCard[]; job_labels?: string[] };
  following: CompanyCard[];
  my_company: { name: string; verified?: boolean; company: CompanyCard | null } | null;
  shelves: { key: string; items: CompanyCard[] }[];
  recent_reviews: CompanyReview[];
  totals: { companies: number; reviews: number };
}
export interface CompanyDetailData {
  company: CompanyRow & CompanyDetail & CompanyCard;
  stats: CompanyStats; my_review: CompanyReview | null; following: boolean;
  related: CompanyCard[]; posts_count: number; years: string[];
  /** The reader's own job family as seen at this company, when their profile names one. */
  my_job: { family: string; label: string; stats: { n: number; rating: number; salary: SalaryStat | null } | null } | null;
  /** The reader proved a work mailbox here: their review carries the badge. */
  my_verified?: boolean;
}
/** Proving where you work (plan/40 §10). `none` → `code_sent` → (`choose` | `propose`) → `verified`. */
export interface CompanyVerifyState {
  state: "none" | "code_sent" | "choose" | "propose" | "verified";
  company_text?: string; domain?: string; email_masked?: string; expires_at?: string; verified_at?: string | null;
  company?: CompanyCard | null;
  /** Whether the directory stands behind "this domain is this company": confirmed, or pending a decision. */
  mapping?: "confirmed" | "pending";
  candidates?: CompanyCard[];
}
export interface CompanyDomain { id: string; domain: string; company_id: string; source: "homepage" | "admin" | "claim"; status: "confirmed" | "pending"; claims: number; created_at: string | null }
export interface CompareItem extends CompanyCard {
  stats: { n: number; rating: number; axes: Partial<Record<Axis, number>>; recommend: number | null; ceo: number | null; growth: number | null;
           salary: SalaryStat | null; interview: { n: number; difficulty: number | null; pass_rate: number | null } | null;
           benefits: string[]; employment: { current?: number; former?: number };
           facts?: Record<string, Record<string, number>>; answered?: number };
}
export interface CompanyMeta {
  axes: Axis[]; benefits: { code: string; group: string }[]; tags: string[];
  employments: string[]; growths: string[]; interview_results: string[]; min_text: number; year_now: number;
  sorts: string[]; job_families: TaxonomyNode[];
  questions: QuestionSpec[]; areas: Axis[]; fact_questions: string[];
}
export interface SearchAllData {
  q: string;
  companies: { items: CompanyCard[]; total: number };
  jobs: { id: string; title: string; company: string; company_id: string | null; location: string; employment_type: string;
          salary_min: number | null; salary_max: number | null; created_at: string }[];
  posts: { id: string; title: string; excerpt: string; board: string; like_count: number; comment_count: number; created_at: string }[];
}
export interface CompanyPost { id: string; title: string; excerpt: string; board: string; like_count: number; comment_count: number; view_count?: number; created_at: string }
export interface ReviewInput {
  employment: string; job_code: string; work_year: number; title: string; pros: string; cons: string; advice: string;
  /** The current form. Scores, recommendation and outlook are derived server-side. */
  answers: Answers;
  salary: number | null; experience_years: number | null;
  interview: { difficulty?: number | null; result?: string | null; questions?: string; process?: string } | null;
  benefits: string[];
}
export const Companies = {
  list: (q: { q?: string; region?: string; industry?: string; market?: string; sort?: string; page?: number } = {}) =>
    get<{ items: CompanyCard[]; total: number; page: number; size: number }>("/api/community/companies", { query: q }),
  home: () => get<CompanyHomeData>("/api/community/companies/home"),
  searchAll: (q: string) => get<SearchAllData>("/api/community/companies/search", { query: { q } }),
  meta: () => get<CompanyMeta>("/api/community/companies/meta"),
  mine: () => get<{ items: CompanyReview[] }>("/api/community/companies/reviews/mine"),
  detail: (id: string) => get<CompanyDetailData>(`/api/community/companies/${id}`),
  compare: (ids: string[]) => get<{ items: CompareItem[]; max: number }>("/api/community/companies/compare", { query: { ids: ids.join(",") } }),
  follow: (id: string) => post<{ following: boolean; follow_count: number }>(`/api/community/companies/${id}/follow`),
  reviews: (id: string, q: { year?: number | null; sort?: string; kind?: string; job?: string; page?: number; size?: number } = {}) =>
    get<{ items: CompanyReview[]; total: number; page: number; size: number }>(`/api/community/companies/${id}/reviews`, { query: q }),
  writeReview: (id: string, b: ReviewInput) =>
    post<{ review: CompanyReview; stats: CompanyStats; company: CompanyCard }>(`/api/community/companies/${id}/reviews`, b),
  deleteReview: (rid: string) => del(`/api/community/companies/reviews/${rid}`),
  helpful: (rid: string) => post<{ helpful: boolean; helpful_count: number }>(`/api/community/companies/reviews/${rid}/helpful`),
  report: (rid: string, reason: string, detail = "") => post<{ ok: boolean }>(`/api/community/companies/reviews/${rid}/report`, { reason, detail }),
  jobs: (id: string) => get<{ items: CommunityJob[] }>(`/api/community/companies/${id}/jobs`),
  posts: (id: string) => get<{ items: CompanyPost[] }>(`/api/community/companies/${id}/posts`),
  salary: (id: string) => get<{ summary: SalaryStat | null; by_job: Record<string, { n: number; rating: number; salary: SalaryStat }>;
                                job_labels: Record<string, string>; reviews: CompanyReview[]; total: number }>(`/api/community/companies/${id}/salary`),
};
export interface CompanyDetail {
  corp_code: string | null; biz_no: string | null; product: string;
  listed_on: string | null; fiscal_month: string; address: string; phone: string;
  founded_on: string | null; employees: number | null;
  sources: Record<string, string>; locked_fields: string[]; hidden: boolean;
}
export interface CompanyRuns {
  runs: { id: string; source: string; at: string; finished_at: string | null; running: boolean;
          ok: boolean | null; fetched: number; created: number; updated: number; skipped: number;
          error: string | null; seconds: number | null }[];
  queue: { id: string; kind: string; status: string; source: string | null; attempts: number;
           run_at: string | null; running_s: number | null; error: string | null }[];
}
export interface CompanySourceRun { at: string; ok: boolean | null; fetched: number; created: number; updated: number; skipped?: number; error?: string | null; seconds?: number | null; running?: boolean }
export interface CompanySources {
  total: number;
  by_market: Record<string, number>;
  auto_collect: boolean;
  /** 기업 기능 전체 (plan/71). 끄면 기업정보 탭·기업 페이지·소속·회사 인증이 사라진다. 저장된 것은 남는다. */
  enabled: boolean;
  dart_per_run: number;
  dart_daily_limit: number;
  dart_spent_today: number;
  coverage: {
    total: number;
    listed: number;
    /** Companies a reader is actually shown — the ones we can say something about. */
    visible: number;
    fields: Record<string, number>;
    pct: Record<string, number>;
    /** What each percentage is measured against: the exchange supplies industry and
     *  region for listed companies only, so a single denominator would lie. */
    of: Record<string, number>;
    filled_by: Record<string, string>;
  };
  sources: { source: string; label: string; note: string; needs_key: string | null; where: string | null;
             key_set: boolean; history: CompanySourceRun[]; last_run: CompanySourceRun | null }[];
}

