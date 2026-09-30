"use client";
import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, BadgeCheck, Bot, Briefcase, BriefcaseBusiness, Camera, Factory, Globe, Image as ImageIcon, Link2, Mail, Map, MapPin, Pencil, Newspaper, ShieldCheck, MessageSquare, MessageSquareText, Phone, Trash2, Users } from "@/components/icons";
import { Chat, Community, Network, Users as UsersApi, type MemberProfile } from "@/lib/api";
import { labelOf } from "@/components/ui/taxonomy-picker";
import { useAuth } from "@/stores/auth";
import { useLocale, useT } from "@/lib/i18n";
import { friendlyError } from "@/lib/errors";
import { fmtDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "./Shell";
import { Avatar } from "@/components/ui/misc";
import { ProfileHeader, coverFallback } from "@/components/profile/ProfileHeader";
import { useImageCrop } from "@/components/ui/image-crop";
import { usePhotoViewer } from "@/components/ui/photo-view";
import { PostRow } from "@/components/community/CommunityHome";
import { PostModal } from "@/components/feed/PostModal";
import { ConnectionControl, statusOf, useLink } from "@/components/network/Connection";
import { useMessenger } from "@/stores/messenger";
import { Pages } from "@/components/ui/pages";
import { Button, buttonLook } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { DropdownMenu } from "@/components/ui/dropdown";

/** A person's page — their home in this product.
 *
 *  Everything on it already exists somewhere else: the account's photo and name, the
 *  profile fields they marked public, the connections they agreed to, the posts they
 *  published. The page holds no copy of any of it, which is why editing sends you to 내
 *  정보 rather than opening a second form that could disagree with the first.
 *
 *  Two shapes, deliberately. On a phone it is a card, the way a messenger shows a person.
 *  On a desktop it is a homepage: a cover across the full width of whatever monitor is
 *  in front of you, the face on it, and then their own things in columns beside a panel
 *  of details. The same data, laid out for the room available.
 */
export function MemberProfilePage({ userId }: { userId?: string }) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const me = useAuth((s) => s.user);
  const id = userId || me?.id || "";
  const q = useQuery({ queryKey: ["network", "profile", id], queryFn: () => Network.profile(id), enabled: !!id });
  // Both photos are picked the same way: choose a file, frame it, upload the frame. Only
  // where the resulting URL is stored differs.
  const { crop, node: cropUI } = useImageCrop();
  const avatarRef = useRef<HTMLInputElement>(null);
  const coverRef = useRef<HTMLInputElement>(null);
  const [saving, setSaving] = useState(false);
  const pick = async (file: File, what: "avatar" | "cover") => {
    const framed = await crop(file, what === "avatar" ? "circle" : "cover");
    if (!framed) return;
    setSaving(true);
    try {
      const up = await Chat.upload(framed, "avatar");
      if (what === "avatar") {
        useAuth.getState().setUser(await UsersApi.patchMe({ avatar_url: up.url }));
      } else {
        // A cover is decoration on a page other people are meant to look at, so it is
        // published with the picture instead of waiting behind a visibility switch.
        await UsersApi.putProfile({ data: { cover: up.url }, visibility: { cover: "public" } });
      }
      qc.invalidateQueries({ queryKey: ["network"] });
      toast.success(t("common.saved"));
    } catch (e) { toast.error(friendlyError(e, locale)); } finally { setSaving(false); }
  };

  // Order matters: `isError` first. Checking `!q.data` before it meant an unknown id sat on
  // a skeleton forever instead of saying what happened.
  if (q.isError) return <Page><EmptyState title={t("prof.not_found")} description={t("prof.not_found_desc")} /></Page>;
  if (q.isLoading || !q.data) return <Page><Skeleton className="h-64" /></Page>;
  const p = q.data;
  const remove = async (what: "avatar" | "cover") => {
    setSaving(true);
    try {
      if (what === "avatar") useAuth.getState().setUser(await UsersApi.patchMe({ avatar_url: "" }));
      else await UsersApi.putProfile({ data: { cover: null, cover_pos: 50 } });
      qc.invalidateQueries({ queryKey: ["network"] });
      toast.success(t("common.saved"));
    } catch (e) { toast.error(friendlyError(e, locale)); } finally { setSaving(false); }
  };
  const editing = { onPickCover: p.is_me ? () => coverRef.current?.click() : undefined,
                    onPickAvatar: p.is_me ? () => avatarRef.current?.click() : undefined,
                    onRemoveCover: p.is_me ? () => void remove("cover") : undefined,
                    onRemoveAvatar: p.is_me ? () => void remove("avatar") : undefined, saving };
  const actions = <Actions p={p} />;

  return (
    <Page full className="px-0! py-0!">
      <div className="lg:hidden"><PhoneProfile p={p} actions={actions} {...editing} /></div>
      <div className="hidden lg:block"><HomeProfile p={p} actions={actions} {...editing} /></div>
      {p.is_me ? (
        <>
          <input ref={avatarRef} type="file" accept="image/*" hidden
                 onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void pick(file, "avatar"); }} />
          <input ref={coverRef} type="file" accept="image/*" hidden
                 onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ""; if (file) void pick(file, "cover"); }} />
        </>
      ) : null}
      {cropUI}
    </Page>
  );
}

interface Shape {
  p: MemberProfile; actions: ReactNode; saving: boolean;
  onPickCover?: () => void; onPickAvatar?: () => void; onRemoveCover?: () => void; onRemoveAvatar?: () => void;
}

/** The phone: a card, the way a messenger shows a person. */
function PhoneProfile({ p, actions, saving, onPickCover, onPickAvatar, onRemoveCover, onRemoveAvatar }: Shape) {
  const t = useT();
  return (
    <div className="px-4 py-5">
      {!p.is_me ? (
        <Link href="/app/network" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted-fg hover:text-fg"><ArrowLeft className="h-4 w-4" />{t("nav.network")}</Link>
      ) : null}
      <div className="mx-auto w-full max-w-[560px] overflow-hidden rounded-2xl border border-border bg-card">
        <ProfileHeader
          coverUrl={coverOf(p)} avatarSrc={p.avatar_url} coverBusy={saving}
          onPickCover={onPickCover} onPickAvatar={onPickAvatar} onRemoveCover={onRemoveCover} onRemoveAvatar={onRemoveAvatar}
          avatar={<div className="overflow-hidden rounded-full bg-card ring-4 ring-card"><Avatar name={p.display_name} src={p.avatar_url} size={112} /></div>}
          name={p.display_name}
          badges={<>
            {p.handle ? <span className="text-sm font-normal text-muted-fg">@{p.handle}</span> : null}
            {p.link?.status === "mutual" ? <Badge tone="success"><BadgeCheck className="h-3 w-3" />{t("net.friends")}</Badge> : null}
          </>}
          meta={<Counts p={p} />}
          actions={actions}
        />
        <div className="border-t border-border px-4 pb-5 pt-4 sm:px-6">
          <Bio p={p} />
          <Facts p={p} className="mt-4 grid gap-2 sm:grid-cols-2" />
          <Empty p={p} />
        </div>
      </div>
      <BlogPosts p={p} className="mx-auto mt-4 w-full max-w-[560px]" />
      <Posts id={p.id} className="mx-auto mt-4 w-full max-w-[560px]" />
    </div>
  );
}

/** The desktop: their homepage. The cover runs the full width of the monitor, the columns
 *  underneath widen with it, and everything is a section of *their* site rather than a row
 *  in a card. */
function HomeProfile({ p, actions, saving, onPickCover, onPickAvatar, onRemoveCover, onRemoveAvatar }: Shape) {
  const t = useT();
  const photo = usePhotoViewer();
  const cover = coverOf(p);
  const drag = useCoverPosition(p, () => cover && photo.view(cover, t("prof.cover")));
  return (
    <div className="group/hero pb-14">
      {/* The band is five times wider than a cover is, so something has to give: showing
          the picture whole left it floating in a blurred surround, and filling the band
          picks a strip through the middle that on a portrait is somebody's jumper. So the
          band is filled — and the owner drags the picture to say which strip. */}
      <div className={cn("relative h-[clamp(220px,30vh,420px)] w-full overflow-hidden bg-muted", cover && p.is_me && "cursor-ns-resize")}
           style={cover ? undefined : { background: coverFallback() }} {...(cover && p.is_me ? drag.handlers : {})}>
        {cover ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={cover} alt="" className="h-full w-full select-none object-cover" style={{ objectPosition: `50% ${drag.pos}%` }} draggable={false} />
            {!p.is_me ? (
              <button type="button" aria-label={t("prof.cover_view")} onClick={() => photo.view(cover, t("prof.cover"))} className="absolute inset-0 cursor-zoom-in" />
            ) : (
              <span className="sr-only">{t("prof.cover_drag")}</span>
            )}
            {p.is_me ? (
              <span className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/45 px-3 py-1 text-[11px] text-white opacity-0 backdrop-blur transition-opacity group-hover/hero:opacity-100">
                {t("prof.cover_drag")}
              </span>
            ) : null}
          </>
        ) : null}
        {/* The face lands on the bottom edge of this, so the bottom has to stay dark enough
            for a white ring to read against a bright photograph. */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-bg/80 to-transparent" />
        {!p.is_me ? (
          <Link href="/app/network" className="absolute left-6 top-6 inline-flex items-center gap-1.5 rounded-full bg-black/40 px-3 py-1.5 text-xs font-medium text-white backdrop-blur hover:bg-black/60">
            <ArrowLeft className="h-3.5 w-3.5" />{t("nav.network")}
          </Link>
        ) : null}
        {onPickCover ? (
          <div className="absolute right-6 top-6 flex gap-1.5">
            <button type="button" onClick={onPickCover} disabled={saving} aria-label={t("prof.cover_edit")}
                    className="inline-flex h-9 items-center gap-1.5 rounded-full bg-black/45 px-3 text-xs font-medium text-white backdrop-blur hover:bg-black/60 disabled:opacity-60">
              <Camera className="h-3.5 w-3.5" />{t("prof.cover_edit")}
            </button>
            {cover && onRemoveCover ? (
              <button type="button" onClick={onRemoveCover} disabled={saving} aria-label={t("prof.photo_remove")}
                      className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-black/45 text-white backdrop-blur hover:bg-black/60 disabled:opacity-60">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="mx-auto w-full max-w-[1180px] px-6 2xl:max-w-[1440px] xl:px-8">
        <header className="flex flex-wrap items-end gap-x-6 gap-y-4 pb-7">
          <div className="relative -mt-[68px] shrink-0">
            <button type="button" disabled={!p.avatar_url} aria-label={t("prof.avatar_view")}
                    onClick={() => p.avatar_url && photo.view(p.avatar_url, p.display_name)}
                    className={cn("block overflow-hidden rounded-full bg-card ring-4 ring-bg", p.avatar_url && "cursor-zoom-in")}>
              <Avatar name={p.display_name} src={p.avatar_url} size={144} />
            </button>
            {onPickAvatar ? (
              <DropdownMenu className="absolute bottom-1 right-1"
                trigger={<button type="button" aria-label={t("settings.avatar_upload")}
                                 className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card shadow hover:bg-muted">
                           <Camera className="h-4 w-4" />
                         </button>}
                items={p.avatar_url && onRemoveAvatar
                  ? [{ key: "pick", label: t("prof.photo_change"), icon: <Camera />, onSelect: onPickAvatar },
                     { key: "remove", label: t("prof.photo_remove"), icon: <Trash2 />, danger: true, onSelect: onRemoveAvatar }]
                  : [{ key: "pick", label: t("prof.photo_change"), icon: <Camera />, onSelect: onPickAvatar }]} />
            ) : null}
          </div>
          <div className="min-w-0 flex-1 pb-1">
            <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[28px] font-semibold leading-tight tracking-tight xl:text-[32px]">
              {p.display_name}
              {p.handle ? <span className="text-base font-normal text-muted-fg">@{p.handle}</span> : null}
              {p.link?.status === "mutual" ? <Badge tone="success"><BadgeCheck className="h-3 w-3" />{t("net.friends")}</Badge> : null}
            </h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-fg"><Counts p={p} /></div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2 pb-1">{actions}</div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] xl:gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="min-w-0 space-y-6">
            {p.fields?.bio || p.fields?.extra ? (
              <Panel title={t("prof.about")}><Bio p={p} /></Panel>
            ) : null}
            <BlogPosts p={p} />
            <Posts id={p.id} />
            <Empty p={p} />
          </div>
          <aside className="space-y-6">
            <Panel title={t("prof.details")}>
              <Facts p={p} className="space-y-2.5" />
            </Panel>
            <OpenSecretaries p={p} />
            <Links p={p} />
          </aside>
        </div>
      </div>
      {photo.node}
    </div>
  );
}

/** Where the cover sits inside a band that is not its shape.
 *
 *  Drag it and the picture slides; let go and the position is saved with the profile, so
 *  the strip the owner chose is the strip everyone sees. Nothing to save for a visitor —
 *  they only ever read it.
 */
function useCoverPosition(p: MemberProfile, onTap?: () => void) {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const stored = Math.min(100, Math.max(0, Number(p.fields?.cover_pos ?? 50)));
  const [pos, setPos] = useState(stored);
  const at = useRef<{ y: number; from: number; height: number; moved: boolean } | null>(null);
  const save = useMutation({
    mutationFn: (v: number) => UsersApi.putProfile({ data: { cover_pos: Math.round(v) }, visibility: { cover_pos: "public" } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["network", "profile"] }); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  const handlers = {
    onPointerDown: (e: React.PointerEvent) => {
      // The upload button and the back link live on top of the cover. Capturing the
      // pointer here swallowed their click, so [배경 사진] stopped working the moment the
      // cover became draggable.
      if ((e.target as HTMLElement).closest("button, a")) return;
      const el = e.currentTarget as HTMLElement;
      try { el.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
      at.current = { y: e.clientY, from: pos, height: el.getBoundingClientRect().height || 1, moved: false };
    },
    onPointerMove: (e: React.PointerEvent) => {
      const d = at.current;
      if (!d) return;
      const dy = e.clientY - d.y;
      if (Math.abs(dy) > 2) d.moved = true;
      // Dragging down should bring the top of the picture into view, which is a *smaller*
      // object-position. The band's own height is the travel, so the picture keeps up with
      // the cursor instead of racing it.
      setPos(Math.min(100, Math.max(0, d.from - (dy / d.height) * 100)));
    },
    onPointerUp: () => {
      const d = at.current;
      at.current = null;
      if (!d) return;
      // A drag repositions; a tap opens the picture. The owner should not lose the viewer
      // just because their cover is also draggable.
      if (d.moved) save.mutate(pos); else onTap?.();
    },
    onPointerCancel: () => { at.current = null; },
  };
  return { pos, handlers, saving: save.isPending };
}

const coverOf = (p: MemberProfile) => (typeof p.fields?.cover === "string" ? p.fields.cover : null);

function Panel({ title, action, children, className }: { title: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-2xl border border-border bg-card", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 sm:px-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">{title}</h2>
        {action ? <div className="ml-auto">{action}</div> : null}
      </div>
      <div className="px-4 py-4 sm:px-5">{children}</div>
    </section>
  );
}

function Counts({ p }: { p: MemberProfile }) {
  const t = useT();
  return (
    <>
      <span className="inline-flex items-center gap-1"><Users className="h-3.5 w-3.5" />{t("prof.connections", { n: p.connections })}</span>
      {p.joined_at ? <span>{t("prof.joined", { when: fmtDateTime(p.joined_at) })}</span> : null}
    </>
  );
}

function Bio({ p }: { p: MemberProfile }) {
  return (
    <>
      {p.fields?.bio ? <p className="whitespace-pre-wrap text-sm leading-relaxed">{String(p.fields.bio)}</p> : null}
      {p.fields?.extra ? <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-fg">{String(p.fields.extra)}</p> : null}
    </>
  );
}

/** One button, because there is one act (plan/43).
 *
 *  Connecting needs nobody's permission and nothing waits. 단추는 사이트 어디서나 같다(plan/69): 내가 연결하지
 *  않았으면 [인맥 맺기], 연결했으면 [인맥 지우기]. 옆의 표시가 지금 사이 — 인맥 · 내가 연결 · 나를 연결. */
function Actions({ p }: { p: MemberProfile }) {
  const t = useT();
  const openWith = useMessenger((s) => s.openWith);
  const status = useLink(p.is_me ? null : p.id, statusOf(p.link));
  if (p.is_me) return <Link href="/app/profile" className={buttonLook("outline", "md")}><Pencil className="h-4 w-4" />{t("prof.edit")}</Link>;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <ConnectionControl userId={p.id} name={p.display_name} known={statusOf(p.link)} size="md" />
      {/* Writing to them, from the page that is about them (plan/44 §7). Talking starts
          with connecting, so it shows once either of them has reached for the other. */}
      {status && status !== "none" ? (
        <Button variant="outline" onClick={() => openWith({ userId: p.id })}>
          <MessageSquare className="h-4 w-4" />{t("msg.message")}
        </Button>
      ) : null}
    </div>
  );
}

/** What they published about themselves. Read from the same per-field visibility the
 *  secretary obeys, so nothing appears here that would not be said out loud. */
function Facts({ p, className }: { p: MemberProfile; className?: string }) {
  const t = useT();
  const f = p.fields ?? {};
  // The taxonomy is fetched only to name the codes; a profile with none never asks for it.
  const codes = [...(f.job_codes ?? []), ...(f.region_codes ?? []), ...(f.industry_codes ?? [])];
  const taxonomy = useQuery({ queryKey: ["job-taxonomy"], queryFn: Community.jobTaxonomy, staleTime: 600_000, enabled: codes.length > 0 });
  const named = (list: string[] | undefined, nodes: Parameters<typeof labelOf>[0]) => (list ?? []).map((c) => labelOf(nodes, c));
  const rows = [
    f.title || f.company ? { icon: f.company && f.company_verified_at ? <ShieldCheck /> : <Briefcase />,
                             text: [f.title, f.company].filter(Boolean).join(" · ") + (f.company && f.company_verified_at ? ` · ${t("cx.verified_badge")}` : "") } : null,
    f.location ? { icon: <MapPin />, text: String(f.location) } : null,
    f.languages ? { icon: <Globe />, text: Array.isArray(f.languages) ? f.languages.join(", ") : String(f.languages) } : null,
    p.email ? { icon: <Mail />, text: p.email } : null,
    // [정보] 에서 이 사람에게 보이게 둔 연락처 (plan/57). 인맥이라 이미 보이는 주소와 같으면 두 번 적지 않는다.
    f.contact?.email && f.contact.email !== p.email ? { icon: <Mail />, text: f.contact.email } : null,
    f.contact?.phone ? { icon: <Phone />, text: f.contact.phone } : null,
    f.contact_rules ? { icon: <MessageSquareText />, text: f.contact_rules } : null,
  ].filter(Boolean) as { icon: ReactNode; text: string }[];
  // One line per kind, each behind its own icon: a single pile of chips made "광진구" and
  // "풀스택" look like the same sort of fact.
  const groups = [
    { icon: <BriefcaseBusiness />, items: named(f.job_codes, taxonomy.data?.jobs) },
    { icon: <Map />, items: named(f.region_codes, taxonomy.data?.regions) },
    { icon: <Factory />, items: named(f.industry_codes, taxonomy.data?.industries) },
  ].filter((g) => g.items.length);
  if (!rows.length && !groups.length) return null;
  return (
    <div>
      <dl className={className}>
        {rows.map((x) => (
          <div key={x.text} className="flex items-center gap-2 text-sm text-muted-fg [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0">
            {x.icon}<span className="min-w-0 truncate text-fg">{x.text}</span>
          </div>
        ))}
      </dl>
      {groups.length ? (
        <div className="mt-3 space-y-2">
          {groups.map((g, i) => (
            <div key={i} className="flex items-start gap-2 [&>svg]:mt-1 [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0 [&>svg]:text-muted-fg">
              {g.icon}
              <div className="flex min-w-0 flex-wrap gap-1.5">
                {g.items.map((c) => <span key={c} className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-fg">{c}</span>)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** 이 사람이 문을 열어 둔 비서 (plan/44 §8).
 *
 *  누구나 말을 걸 수 있는 비서만 여기 선다. 공개 링크가 없는 비서는 **없는 것처럼**
 *  다뤄야 한다. 이름만 보여 주고 누를 수 없게 두면, 그건 있는데 못 쓰는 것으로
 *  읽혀서 문을 닫아 둔 사람의 뜻과 어긋난다.
 *
 *  내 페이지에서도 같은 것이 보인다. **남에게 어떻게 보이는지를 내가 볼 수 있어야**
 *  공개 설정이 손에 잡힌다.
 */
function OpenSecretaries({ p }: { p: MemberProfile }) {
  const t = useT();
  const list = (p.secretaries ?? []).filter((b) => b?.link_code);
  if (!list.length) {
    // 내 페이지일 때만 말해 준다. 남의 페이지에서 "열어 둔 비서가 없다" 는
    // 그 사람의 설정을 들여다보는 말이라 할 필요가 없다.
    if (!p.is_me) return null;
    return (
      <Panel title={<><Bot className="h-4 w-4" />{t("prof.open_secretaries")}</>}>
        <p className="text-sm text-muted-fg">{t("prof.no_open_secretary")}</p>
        <Link href="/app/agents" className="mt-2 inline-block text-sm text-accent hover:underline">
          {t("prof.open_a_secretary")}
        </Link>
      </Panel>
    );
  }
  return (
    <Panel title={<><Bot className="h-4 w-4" />{t("prof.open_secretaries")}</>}>
      <ul className="space-y-2.5">
        {list.map((b) => (
          <li key={b.id}>
            <Link
              href={`/secretary/${encodeURIComponent(b.link_code)}`}
              className="group flex items-center gap-3 rounded-xl border border-border px-3 py-2.5 transition-colors hover:border-accent"
            >
              <Avatar name={b.name} src={b.avatar_url ?? undefined} size={36} mascot />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{b.name}</span>
                <span className="block truncate text-xs text-muted-fg">
                  {b.role_line || t("prof.secretary_of", { name: p.display_name })}
                </span>
              </span>
              <MessageSquare className="h-4 w-4 shrink-0 text-muted-fg group-hover:text-accent" />
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Links({ p }: { p: MemberProfile }) {
  const t = useT();
  const raw = p.fields?.links;
  const list = (Array.isArray(raw) ? raw : typeof raw === "string" ? [raw] : []).filter((x): x is string => !!x && typeof x === "string");
  if (!list.length) return null;
  return (
    <Panel title={<><Link2 className="h-4 w-4" />{t("prof.links")}</>}>
      <ul className="space-y-2">
        {list.map((href) => (
          <li key={href}>
            <a href={/^https?:\/\//.test(href) ? href : `https://${href}`} target="_blank" rel="noreferrer noopener"
               className="block truncate text-sm text-accent hover:underline">{href}</a>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Nothing to show, said rather than left blank — a visitor should not have to guess
 *  whether someone is new or private. */
function Empty({ p }: { p: MemberProfile }) {
  const t = useT();
  const f = p.fields ?? {};
  const bare = !f.bio && !f.title && !f.company && !f.location && !f.languages;
  if (!bare) return null;
  if (!p.is_me) return <p className="text-sm text-muted-fg">{t("prof.nothing_public")}</p>;
  return <p className="text-sm text-muted-fg">{t("prof.fill_me")} <Link href="/app/profile" className="text-accent underline">{t("prof.edit")}</Link></p>;
}

/** Everything they wrote that I may see, in one grid (plan/42 §9).
 *
 *  The album used to sit beside this list: the same act of showing a picture, but with a
 *  caption and no address, one switch for the whole shelf, and nowhere to reply. A photo is
 *  a post now, so there is one section — and a post with no picture is a tile of its words. */
function BlogPosts({ p, className }: { p: MemberProfile; className?: string }) {
  const t = useT();
  const [read, setRead] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  // Page one came with the profile, so the grid draws at once and only pays for the pages
  // somebody actually turns to.
  const q = useQuery({
    queryKey: ["people", p.id, "posts", page], queryFn: () => Network.posts(p.id, page),
    enabled: page > 1, placeholderData: keepPreviousData,
  });
  const total = p.posts_total ?? (p.posts?.length ?? 0);
  const items = page === 1 ? (p.posts ?? []) : (q.data?.items ?? []);
  const pages = q.data?.pages ?? Math.max(1, Math.ceil(total / 12));
  if (!total) return null;
  const tileCls = "group relative flex aspect-square items-center justify-center overflow-hidden rounded-lg border border-border bg-muted";
  return (
    <Panel className={className}
           title={<><ImageIcon className="h-4 w-4" />{t("net.posts")}<span className="text-xs font-normal text-muted-fg">{total}</span></>}
           action={p.handle ? <a href={`/@${p.handle}`} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">/@{p.handle}</a> : null}>
      <ul className="grid grid-cols-3 gap-1.5">
        {items.map((post) => {
          const cover = post.images?.[0];
          const tile = (
            <>
              {cover ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={cover} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]" />
              ) : (
                <span className="line-clamp-4 p-2.5 text-left text-[11px] leading-snug text-muted-fg">
                  {post.kind === "note" ? post.body || post.excerpt : post.title}
                </span>
              )}
              {(post.images?.length ?? 0) > 1 ? (
                <span className="absolute right-1.5 top-1.5 rounded-md bg-fg/60 px-1.5 text-[10px] text-bg">{post.images.length}</span>
              ) : null}
              {post.visibility !== "public" ? (
                <span className="absolute left-1.5 top-1.5 rounded-md bg-fg/60 px-1.5 text-[10px] text-bg">{t(`blog.vis_${post.visibility}`)}</span>
              ) : null}
            </>
          );
          return (
            <li key={post.id}>
              {/* Pressing a tile opens the post where you are, the same window a card in
                  소식 opens. Leaving for another tab to read something already on screen
                  is how this used to work and it was never what anybody wanted. */}
              <button type="button" onClick={() => setRead(post.id)} className={cn(tileCls, "cursor-zoom-in")}>{tile}</button>
            </li>
          );
        })}
      </ul>
      <Pages page={page} pages={pages} onGo={setPage} />
      {read ? <PostModal postId={read} onClose={() => setRead(null)} onChanged={() => {}} /> : null}
    </Panel>
  );
}

function Posts({ id, className }: { id: string; className?: string }) {
  const t = useT(); const locale = useLocale();
  const q = useQuery({ queryKey: ["community", "by", id], queryFn: () => Community.posts({ author: id, limit: 8 }), enabled: !!id });
  const items = q.data?.items ?? [];
  if (!q.isLoading && !items.length) return null;
  return (
    <Panel className={className} title={<><Newspaper className="h-4 w-4" />{t("prof.posts")}</>}
           action={items.length >= 8 ? <Link href="/app/community" className="text-xs text-accent hover:underline">{t("prof.posts_all")}</Link> : null}>
      {q.isLoading ? <Skeleton className="h-24" /> : (
        <ul className="-mx-4 divide-y divide-border sm:-mx-5">
          {items.map((post) => <PostRow key={post.id} post={post} locale={locale} showBoard />)}
        </ul>
      )}
    </Panel>
  );
}

