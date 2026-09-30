/**
 * 메인과 앱이 직접 그리는 창(틀·아바타·빠른 대화)이 주고받는 것의 전부.
 *
 * 세 문(비서와 대화·소식·커뮤니티)의 안쪽은 memo-ora.com 이 "앱 모드" 로 그린다(plan/62).
 * 그쪽과의 약속은 `preload/host.ts` 의 `__memoraHost` 하나다.
 */

/** 고정이다. 설정으로도 못 바꾼다. */
export const ORIGIN = 'https://memo-ora.com';

/** 앱의 틀 세대. 웹은 이 값이 2 이상일 때만 앱 모드로 그린다. */
export const SHELL_GEN = 2;

export interface AuthState {
  signedIn: boolean;
  /** 아직 쿠키로 복구를 시도하는 중. */
  restoring: boolean;
}

// ───────────────────────── 문 ─────────────────────────

export type Door = 'chat' | 'feed' | 'community';
/** 본창의 내용 자리. 세 문은 웹이, 알림·설정은 앱이 그린다. */
export type Pane = Door | 'alerts' | 'settings';

export const DOORS: readonly { id: Door; label: string; home: string }[] = [
  { id: 'chat', label: '비서와 대화', home: '/app/chat' },
  { id: 'feed', label: '소식', home: '/app/feed' },
  { id: 'community', label: '커뮤니티', home: '/app/community' },
];

export const doorHome = (d: Door): string => DOORS.find((x) => x.id === d)!.home;

const starts = (p: string, base: string) => p === base || p.startsWith(base + '/');

/** 주소가 어느 문의 것인가. 로그인 쪽은 어느 뷰에서나 열린다("auth"). 문 밖이면 null.
 *  웹의 `lib/desktop.ts` 와 같은 규칙이다 — 둘이 갈라지면 링크가 뷰 사이를 오간다. */
export function doorOf(path: string): Door | 'auth' | null {
  const p = path.split(/[?#]/)[0] || '/';
  if (starts(p, '/app/chat') || starts(p, '/app/onboarding')) return 'chat';
  if (starts(p, '/app/feed') || starts(p, '/app/blog') || starts(p, '/app/u') || starts(p, '/app/me')) return 'feed';
  if (starts(p, '/app/community')) return 'community';
  if (['/login', '/signup', '/forgot-password', '/reset-password'].some((b) => starts(p, b))) return 'auth';
  return null;
}

/** 이 뷰에서 `url` 로 가려 할 때 할 일. */
export type Route =
  | { kind: 'stay' }
  | { kind: 'door'; door: Door; path: string }
  | { kind: 'browser'; url: string };

export function routeFor(url: string, here: Door): Route {
  let u: URL;
  try {
    u = new URL(url, ORIGIN);
  } catch {
    return { kind: 'stay' };
  }
  if (u.origin !== ORIGIN) return { kind: 'browser', url: u.toString() };
  const path = u.pathname + u.search + u.hash;
  // `/app` 자체(웹의 비서 홈)는 웹이 이 문의 첫 화면으로 돌린다. 로그인 직후가 늘 여기로 온다.
  if (u.pathname === '/app' || u.pathname === '/app/') return { kind: 'stay' };
  const d = doorOf(path);
  if (d === 'auth' || d === here) return { kind: 'stay' };
  if (d) return { kind: 'door', door: d, path };
  return { kind: 'browser', url: u.toString() };
}

// ───────────────────────── 설정 ─────────────────────────

export interface Shortcuts {
  quick: string;
  avatar: string;
  main: string;
  /** 화면 보여주고 묻기(plan/70). 처음에는 비어 있다(쓰지 않음). */
  capture: string;
}

export interface Settings {
  /** 켤 때 아바타도 같이. */
  avatarOnStart: boolean;
  /** 아바타와 빠른 대화가 부르는 비서. 비어 있으면 첫 비서. */
  agentId: string | null;
  /** 아바타가 답을 소리로 읽는다. */
  speak: boolean;
  notify: { proactive: boolean; inbox: boolean; messages: boolean };
  shortcuts: Shortcuts;
  theme: 'system' | 'light' | 'dark';
  /**
   * 화면 보여주기(plan/70): 켜면 아바타·빠른 대화에 [화면 보여주기] 가 생긴다. 누를 때만 한 장을 찍어, 확인한 뒤에
   * 물음과 함께 비서에게 보낸다. 처음에는 꺼져 있다 — 화면은 사람이 켜야 나간다.
   */
  capture: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  avatarOnStart: false,
  agentId: null,
  speak: true,
  notify: { proactive: true, inbox: true, messages: true },
  shortcuts: { quick: 'CommandOrControl+Shift+Space', avatar: 'CommandOrControl+Shift+A', main: 'CommandOrControl+Shift+M', capture: '' },
  theme: 'system',
  capture: false,
};

/** 찍어 둔 화면 한 장(보내기 전). 원본은 메인에 있고, 창에는 작은 미리보기만 간다. */
export interface ShotPreview {
  /** 작은 미리보기(data:image/jpeg). */
  preview: string;
  width: number;
  height: number;
}

// ───────────────────────── 상태 ─────────────────────────

export interface Person {
  name: string;
  email: string;
  avatarUrl: string | null;
}

export interface AgentLite {
  id: string;
  name: string;
  /** 프로필 사진(동그라미로 잘린 것). 아이콘 막대·빠른 대화의 작은 얼굴. */
  avatarUrl: string | null;
  /** 올린 그림 그대로(plan/63). 아바타 창이 띄운다. 없으면 프로필 사진. */
  characterUrl: string | null;
  accent?: string | null;
}

export interface ShellState {
  signedIn: boolean;
  restoring: boolean;
  pane: Pane;
  me: Person | null;
  agents: AgentLite[];
  /** 아바타·빠른 대화의 비서. */
  agent: AgentLite | null;
  avatarOn: boolean;
  unread: { inbox: number; rooms: number };
  /** 지금 문의 뷰가 뒤로 갈 수 있나. */
  canBack: boolean;
  loading: boolean;
  /** 서버에 닿지 못해 문을 그리지 못했다. */
  offline: boolean;
  platform: string;
  version: string;
  autostart: boolean;
  /** 등록하지 못한 단축키(다른 프로그램이 쓰는 조합). */
  shortcutErrors: (keyof Shortcuts)[];
  /** 새 판과 자동 업데이트의 진행(plan/65). */
  update: UpdateInfo;
  /** 이 서비스에서 음성을 쓰는가(plan/67). 관리자가 끄면 앱도 마이크·소리 단추와 그 설정을 감춘다. */
  voice: VoiceAvailability;
}

export interface VoiceAvailability {
  /** 말로 묻기(받아쓰기) */
  stt: boolean;
  /** 답을 소리로(읽어 주기) */
  tts: boolean;
}

/** 서버에 묻기 전에는 감춘다 — 꺼진 단추가 잠깐 보였다 사라지지 않게. */
export const VOICE_UNKNOWN: VoiceAvailability = { stt: false, tts: false };

/** 다운로드 센터가 내어 주는 설치 파일 하나(`/api/downloads`). */
export interface InstallerOut {
  name: string;
  platform: 'windows' | 'macos' | 'linux';
  arch: 'x64' | 'arm64' | 'universal';
  kind: string;
  size: number;
  sha256: string | null;
  ready: boolean;
  url: string | null;
}

/** 이 컴퓨터의 설치 프로그램 하나: 윈도 .exe, 리눅스 .deb, 맥은 universal(그 전 판이면 칩이 맞는 것).
 *  받을 준비가 됐고 sha256 이 있는 것만 — 확인할 수 없는 파일은 설치하지 않는다. */
export function pickInstaller(assets: InstallerOut[], platform: string = process.platform, arch: string = process.arch): InstallerOut | null {
  const os = platform === 'win32' ? 'windows' : platform === 'darwin' ? 'macos' : platform === 'linux' ? 'linux' : null;
  if (!os) return null;
  const mine = assets.filter((a) => a.platform === os && a.ready && a.url && a.sha256);
  if (os === 'windows') return mine.find((a) => a.kind === 'exe') ?? null;
  if (os === 'linux') return mine.find((a) => a.kind === 'deb') ?? null;
  return mine.find((a) => a.arch === 'universal') ?? mine.find((a) => a.arch === (arch === 'arm64' ? 'arm64' : 'x64')) ?? null;
}

export interface UpdateInfo {
  /** 다운로드 센터의 최신 판. */
  latest: string | null;
  /** 이 앱보다 새것인가. */
  newer: boolean;
  /** 이 컴퓨터에 맞는 설치 파일이 있어 앱 안에서 바로 업데이트할 수 있는가. */
  installable: boolean;
  phase: 'idle' | 'downloading' | 'installing' | 'ready' | 'error';
  /** 받은 정도 0~1. */
  progress: number;
  error?: string;
  /** 받아 둔 파일(시험에서만 쓴다). */
  file?: string;
  /** [업데이트 확인] 을 누르고 답을 기다리는 중. */
  checking: boolean;
  /** 마지막으로 다운로드 센터에 물어본 때(ms). */
  checkedAt: number | null;
  /** 손으로 확인했는데 묻지 못했다. */
  checkError?: string;
}

/** 판 비교: a 가 b 보다 새것인가. "0.10.0" > "0.9.3", 꼬리표(-beta)는 없는 것보다 앞선다. */
export function newerThan(a: string, b: string): boolean {
  const parse = (v: string) => {
    const [core, pre = ''] = v.trim().replace(/^v/, '').split('-', 2);
    return { n: core.split('.').map((x) => Number.parseInt(x, 10) || 0), pre };
  };
  const x = parse(a);
  const y = parse(b);
  for (let i = 0; i < Math.max(x.n.length, y.n.length); i++) {
    const d = (x.n[i] ?? 0) - (y.n[i] ?? 0);
    if (d) return d > 0;
  }
  if (x.pre === y.pre) return false;
  if (!x.pre) return true; // 정식 > 미리보기
  if (!y.pre) return false;
  return x.pre > y.pre;
}

export interface InboxLite {
  id: string;
  kind: string;
  status: string;
  title: string;
  text: string;
  createdAt: string;
}

// ───────────────────────── 턴 ─────────────────────────

export type TurnEventType =
  | 'turn.start' | 'text.delta' | 'thinking.delta' | 'thinking.status' | 'tool.start' | 'tool.end'
  | 'card' | 'memory.retrieved' | 'guard.redacted' | 'usage' | 'notice'
  | 'turn.complete' | 'turn.error' | 'turn.cancelled';

export const TERMINAL: ReadonlySet<string> = new Set(['turn.complete', 'turn.error', 'turn.cancelled']);

export interface TurnEvent {
  seq: number;
  type: TurnEventType | string;
  at: string;
  data: Record<string, unknown>;
}

/** 빠른 대화·아바타가 받는 답의 모양. 조각이 올 때마다 통째로 덮어쓴다. */
export interface Answer {
  /** 묻기 한 번의 이름. 새로 물으면 바뀐다. */
  id: string;
  agentId: string;
  conversationId: string | null;
  question: string;
  text: string;
  /** 지금 하는 일 한 줄(생각 중·도구 이름). 글이 흐르기 시작하면 비운다. */
  status: string;
  done: boolean;
  error?: string;
}

export interface AvatarSubject {
  agentId: string | null;
  name: string;
  avatarUrl: string | null;
  /** 아바타 창이 세울 그림: 원본이 있으면 원본, 없으면 프로필 사진. */
  imageUrl: string | null;
}

/** 사진을 어떻게 놓았나(plan/66): 창에 맞춘 크기의 배수, 그리고 창 가운데에서 치우친 정도(창 크기에 대한 비율 —
 *  창을 키우거나 줄여도 같은 자리에 머문다). 사진마다 따로 기억한다. */
export interface PictureView {
  scale: number;
  x: number;
  y: number;
}

/** 아바타 창이 알리는 지금 일(녹음·재생·답은 아바타 창에 산다). */
export interface AvatarActivity {
  recording: boolean;
  busy: boolean;
  speaking: boolean;
  /** 비서가 먼저 건넨 말에 아직 답하지 않았다(컨트롤에 [답하기]). */
  proactive: boolean;
}

/** 두 창(아바타·컨트롤)이 함께 보는 상태. 설정과 서비스에 속한 것은 메인이 채운다. */
export interface AvatarStatus extends AvatarActivity {
  /** 답을 소리로 듣는가(설정). */
  speak: boolean;
  /** 사진을 숨기고 말풍선만. */
  hidden: boolean;
  /** 서비스가 음성을 허락하는가(plan/67). 꺼져 있으면 그 단추는 없다. */
  stt: boolean;
  tts: boolean;
  /** 화면 보여주기를 켰는가(설정, plan/70). */
  capture: boolean;
}

export const IDLE_STATUS: AvatarStatus = { recording: false, busy: false, speaking: false, proactive: false, speak: true, hidden: false, stt: false, tts: false, capture: false };

/** 아바타 창 안에서 "아바타" 인 곳(사진·말풍선). 컨트롤은 마우스가 여기 있을 때만 나온다. 창 기준 좌표. */
export interface HitArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 컨트롤 창이 누른 단추. 녹음·그만·답하기는 아바타 창으로, 소리 켜고 끄기는 메인이 설정에 적는다. */
export type AvatarCommand = 'mic' | 'stop' | 'reply' | 'toggle-speak' | 'capture';

export type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

/** 아바타가 말하고 있는 상태. 조각이 올 때마다 덮어쓴다. */
export interface SayState {
  text: string;
  done: boolean;
  /** 답이 아직 없을 때 지금 하는 일(생각하는 중, 일정을 확인하는 중 …). */
  status?: string;
  /** 사람이 읽을 수 있는 한 문장. 실패했을 때만. */
  error?: string;
  /** 비서가 먼저 건넨 말이면 참. 답하기 단추가 붙는다. */
  proactive?: boolean;
}

// ───────────────────────── 다리 ─────────────────────────

/** preload 가 `window.memora` 로 내놓는 것. 앱이 직접 그리는 창 셋이 함께 쓴다. */
export interface Bridge {
  platform: string;
  /** 지금 어두운 화면인가. 창이 뜰 때 한 번 읽고, 바뀌면 onTheme 으로 온다. */
  dark: boolean;
  onTheme(fn: (dark: boolean) => void): () => void;
  /** 이 서비스에서 음성을 쓰는가(plan/67). */
  voice(): Promise<VoiceAvailability>;
  onVoice(fn: (v: VoiceAvailability) => void): () => void;

  shell: {
    state(): Promise<ShellState>;
    onState(fn: (s: ShellState) => void): () => void;
    select(pane: Pane): Promise<void>;
    back(): Promise<void>;
    reload(): Promise<void>;
    /** 지금 문의 그 자리를 브라우저로. */
    openInBrowser(): Promise<void>;
    /** 웹의 한 자리를 브라우저로(설정 화면의 "웹에서 전체 기능"). */
    openWeb(path: string): Promise<void>;
    accountMenu(x: number, y: number): Promise<void>;
    inbox(): Promise<InboxLite[]>;
    openInbox(id: string): Promise<void>;
    settings(): Promise<Settings>;
    setSettings(patch: Partial<Settings>): Promise<Settings>;
    setAutostart(on: boolean): Promise<boolean>;
    openQuick(): Promise<void>;
    toggleAvatar(): Promise<void>;
    signOut(): Promise<void>;
    /** 지금 새 판이 있는지 다운로드 센터에 묻는다(앱을 다시 켜지 않아도). */
    checkUpdate(): Promise<void>;
    /** 다운로드 센터를 브라우저로 연다. */
    openDownloads(): Promise<void>;
    /** 새 판을 다운로드 센터에서 받아 설치하고 다시 켠다. */
    update(): Promise<void>;
  };

  avatar: {
    subject(): Promise<AvatarSubject>;
    onSubject(fn: (s: AvatarSubject) => void): () => void;
    /** 비서에게 묻는다. 답은 onSay 로 흘러온다. 웹의 그 대화에 그대로 쌓인다. */
    ask(text: string): Promise<void>;
    stop(): Promise<void>;
    onSay(fn: (s: SayState) => void): () => void;
    /** 녹음한 소리를 글로. webm/opus 를 그대로 보낸다. */
    transcribe(audio: ArrayBuffer, mime: string): Promise<{ text: string }>;
    /** 글을 소리로. mp3 바이트가 돌아온다. */
    speak(text: string): Promise<ArrayBuffer>;
    /** 설정의 "답을 소리로". */
    speaks(): Promise<boolean>;
    setSpeak(on: boolean): Promise<void>;
    status(): Promise<AvatarStatus>;
    onStatus(fn: (s: AvatarStatus) => void): () => void;
    /** 본창의 대화로. */
    openChat(): Promise<void>;
    openQuick(): Promise<void>;
    close(): Promise<void>;
    /** 세울 그림의 바이트. 앱의 창에서 픽셀을 다루려면(바탕 오리기) 같은 출처여야 해서 메인이 받아 건넨다. */
    image(url: string): Promise<ArrayBuffer | null>;
    /** 창이 뜨기 전부터 흐르던 답(빠른 대화에서 물어 아바타가 막 열렸을 때). */
    lastSay(): Promise<SayState | null>;

    // ── 창 (잠금을 풀었을 때) ──
    /** 창을 끌어 옮긴다. 자주 부르므로 답을 기다리지 않는다. */
    moveBy(dx: number, dy: number): void;
    /** 가장자리·모서리를 끌어 크기를 바꾼다. */
    resizeBy(edge: ResizeEdge, dx: number, dy: number): void;
    /** 끌기가 끝났다 — 지금 자리를 바로 적는다. */
    commitBounds(): void;
    locked(): Promise<boolean>;
    setLocked(locked: boolean): void;
    onLocked(fn: (locked: boolean) => void): () => void;
    /** 컨트롤 창이 이 창의 바닥을 덮는 높이. 말풍선을 그만큼 들어 올린다. */
    onChipInset(fn: (px: number) => void): () => void;
    /** 사진·말풍선이 차지한 곳. 잠겼을 때 마우스가 여기 오면 컨트롤이 나온다. */
    reportHitArea(area: HitArea | null): void;
    /** 마우스가 사진·말풍선 위에서 움직였다(윈도·맥은 통과 창에도 움직임을 넘겨준다, plan/70). */
    hoverPing(): void;
    /** [화면 보여주기]: 찍어서 빠른 대화에 붙여 연다(plan/70). */
    capture(): void;

    // ── 사진 ──
    view(url: string): Promise<PictureView | null>;
    /** null 이면 처음 모양으로. */
    saveView(url: string, view: PictureView | null): Promise<void>;
    setHidden(hidden: boolean): Promise<void>;

    // ── 컨트롤 창과 ──
    onCommand(fn: (c: AvatarCommand) => void): () => void;
    reportActivity(a: AvatarActivity): void;
  };

  /** 잠긴 아바타의 컨트롤 창(plan/66). 아바타 창은 클릭을 통과시키므로 단추는 이 창에 산다. */
  chip: {
    status(): Promise<AvatarStatus>;
    onStatus(fn: (s: AvatarStatus) => void): () => void;
    command(c: AvatarCommand): void;
    /** 잠금을 푼다(이 창은 사라지고 단추는 아바타 창 안으로 돌아간다). */
    unlock(): void;
    /** 컨트롤을 끌면 아바타가 따라 움직인다. */
    moveBy(dx: number, dy: number): void;
    commitBounds(): void;
    /** 내용에 맞춘 창 크기. */
    reportSize(w: number, h: number): void;
    /** 마우스가 아바타 위에 왔다(true)·떠났다(false). 보일 때만 눌린다. */
    onReveal(fn: (shown: boolean) => void): () => void;
    /** 마우스가 컨트롤 안에 들어왔다·나갔다 — 그 위에 있는 동안은 숨지 않는다. */
    reportHover(inside: boolean): void;
    openChat(): Promise<void>;
    openQuick(): Promise<void>;
  };

  /**
   * 빠른 대화(plan/69): 어디서든 뜨는 입력 줄. 보내면 창은 닫히고, 답은 **아바타의 말풍선**으로 나온다(Geny·Dex).
   * 비서를 고르면 아바타의 비서도 그 비서가 된다 — 곁에 있는 비서는 하나다.
   */
  quick: {
    /** 창이 보일 때마다 부른다: 비서 목록, 곁의 비서, 화면 보여주기가 켜졌는지, 붙어 있는 화면. */
    agents(): Promise<{ agents: AgentLite[]; agentId: string | null; capture: boolean; shot: ShotPreview | null }>;
    /** 지금 화면을 한 장 찍어 이 물음에 붙인다(plan/70). 창들은 찍는 동안 비킨다. */
    capture(): Promise<ShotPreview>;
    /** 붙여 둔 화면을 뗀다. */
    dropShot(): Promise<void>;
    /** 붙어 있는 화면(아바타의 [화면 보여주기] 로 열렸을 때 등). */
    onShot(fn: (s: ShotPreview | null) => void): () => void;
    pick(agentId: string): Promise<void>;
    ask(agentId: string, text: string): Promise<void>;
    /** 아바타가 하던 답을 멈춘다. */
    stop(): Promise<void>;
    /** 아바타가 지금 하는 답(멈춤 단추·오류를 보이려고). */
    onAnswer(fn: (a: Answer | null) => void): () => void;
    transcribe(agentId: string, audio: ArrayBuffer, mime: string): Promise<{ text: string }>;
    hide(): Promise<void>;
    resize(height: number): Promise<void>;
    /** 창이 다시 보였다(입력칸에 초점을 줄 때). */
    onShown(fn: () => void): () => void;
  };
}

/** IPC 채널 이름. 문자열을 두 군데 적지 않기 위해 여기 모은다. */
export const CH = {
  // 틀
  state: 'shell:state',
  select: 'shell:select',
  back: 'shell:back',
  reload: 'shell:reload',
  openInBrowser: 'shell:open-in-browser',
  openWeb: 'shell:open-web',
  accountMenu: 'shell:account-menu',
  inbox: 'shell:inbox',
  openInbox: 'shell:open-inbox',
  settings: 'shell:settings',
  setSettings: 'shell:set-settings',
  setAutostart: 'shell:set-autostart',
  openQuick: 'shell:open-quick',
  toggleAvatar: 'shell:toggle-avatar',
  signOut: 'shell:sign-out',
  checkUpdate: 'shell:check-update',
  openDownloads: 'shell:open-downloads',
  update: 'shell:update',
  // 아바타
  subject: 'avatar:subject',
  ask: 'avatar:ask',
  stop: 'avatar:stop',
  say: 'avatar:say',
  stt: 'avatar:stt',
  tts: 'avatar:tts',
  speaks: 'avatar:speaks',
  openChat: 'avatar:open-chat',
  close: 'avatar:close',
  avatarImage: 'avatar:image',
  lastSay: 'avatar:last-say',
  setSpeak: 'avatar:set-speak',
  moveBy: 'avatar:move-by',
  resizeBy: 'avatar:resize-by',
  commitBounds: 'avatar:commit-bounds',
  getLocked: 'avatar:get-locked',
  setLocked: 'avatar:set-locked',
  lockedChanged: 'avatar:locked',
  chipInset: 'avatar:chip-inset',
  getView: 'avatar:view',
  saveView: 'avatar:save-view',
  setHidden: 'avatar:set-hidden',
  avatarCommand: 'avatar:command',
  avatarActivity: 'avatar:activity',
  avatarStatus: 'avatar:status',
  getStatus: 'avatar:get-status',
  chipSize: 'chip:size',
  chipReveal: 'chip:reveal',
  hitArea: 'avatar:hit-area',
  hoverPing: 'avatar:hover-ping',
  chipHover: 'chip:hover',
  voice: 'app:voice',
  getVoice: 'app:get-voice',
  // 빠른 대화
  qAgents: 'quick:agents',
  qPick: 'quick:pick',
  qAsk: 'quick:ask',
  qStop: 'quick:stop',
  qAnswer: 'quick:answer',
  qStt: 'quick:stt',
  qTts: 'quick:tts',
  qOpen: 'quick:open-in-main',
  qHide: 'quick:hide',
  qCapture: 'quick:capture',
  qDropShot: 'quick:drop-shot',
  qShot: 'quick:shot',
  qResize: 'quick:resize',
  qShown: 'quick:shown',
  // 테마 — 앱이 정해서 모든 화면에 직접 건넨다(운영체제에 따라 Electron 의 테마가 웹에 닿지 않는다)
  themeNow: 'app:theme-now',
  theme: 'app:theme',
  // 웹 뷰의 다리 (preload/host.ts)
  hostToken: 'host:token',
  hostSignout: 'host:signout',
  hostNavigate: 'host:navigate',
  hostOpen: 'host:open',
  hostCommand: 'host:command',
} as const;
