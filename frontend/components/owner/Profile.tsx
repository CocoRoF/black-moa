"use client";
import Link from "next/link";
import { createContext, useContext, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Public, Users } from "@/lib/api";
import { useLocale, useT, type TFn } from "@/lib/i18n";
import { useCompanyFeatures } from "@/lib/hooks";
import { friendlyError } from "@/lib/errors";
import { Page } from "./Shell";
import { VisibilityPicker } from "@/components/ui/visibility";
import { normalize } from "@/lib/visibility";
import { Section } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { TagInput, PageHeader } from "@/components/ui/misc";
import { SwitchRow } from "@/components/ui/switch";
import { useAuth } from "@/stores/auth";
import { TaxonomyPicker, labelOf } from "@/components/ui/taxonomy-picker";
import { ChevronDown } from "@/components/icons";
import { Community } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { CompanyVerifyCard } from "./CompanyVerifyCard";

type Vis = "public" | "known" | "private";
const DEFAULT_VIS: Record<string, Vis> = { full_name: "public", preferred_name: "public", title: "public", company: "public", bio: "public", location: "private", languages: "public", links: "public", "contact.email": "private", "contact.phone": "private", contact_rules: "public", extra: "private", job_codes: "public", region_codes: "public", industry_codes: "public" };

/** Row/V live at module scope on purpose.
 *  Declared inside ProfilePage they were a *new component type* on every render, so each
 *  keystroke made React unmount and remount the row - the input lost focus after one
 *  character. The context carries the row's dependencies without touching call sites. */
interface RowCtx { t: TFn; vis: Record<string, string>; setVis: Dispatch<SetStateAction<Record<string, string>>> }
const ProfileRowCtx = createContext<RowCtx | null>(null);

function V({ k }: { k: string }) {
  const c = useContext(ProfileRowCtx)!;
  return <VisibilityPicker value={(c.vis[k] as Vis) ?? DEFAULT_VIS[k] ?? "private"} onChange={(v) => c.setVis((p) => ({ ...p, [k]: v }))} />;
}

function Row({ k, children, hint }: { k: string; children: React.ReactNode; hint?: string }) {
  const c = useContext(ProfileRowCtx)!;
  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium">{c.t(`profile.f_${k.replace(".", "_")}`)}</span><V k={k} /></div>
      {children}{hint ? <p className="mt-1 text-xs text-muted-fg">{hint}</p> : null}
    </div>
  );
}

/** A row whose value is a set of taxonomy codes, opened in the same dialog the job board
 *  uses — so "데이터·AI" means the same thing on a profile as it does on a posting. */
function TaxoRow({ k, nodes, title, hint, max, value, onChange }: {
  k: string; nodes?: TaxoNodeList; title: string; hint: string; max: number; value: string[]; onChange: (v: string[]) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Row k={k}>
      <button type="button" onClick={() => setOpen(true)} disabled={!nodes}
              className="flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2 text-left text-sm disabled:opacity-60">
        {value.length ? value.map((v) => (
          <span key={v} className="rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">{labelOf(nodes, v)}</span>
        )) : <span className="text-muted-fg">{t("profile.pick")}</span>}
        <ChevronDown className="ml-auto h-4 w-4 shrink-0 text-muted-fg" />
      </button>
      <TaxonomyPicker open={open} nodes={nodes} title={title} hint={hint} value={value} max={max}
                      onChange={onChange} onClose={() => setOpen(false)} />
    </Row>
  );
}
type TaxoNodeList = Parameters<typeof labelOf>[0];

/** Where this person lives on the open internet (plan/41 §3).
 *
 *  The address is only half of it: the page opens once a secretary is published, so this
 *  says which half is missing rather than handing out a link that 404s.
 */
function PublicPageCard() {
  const t = useT();
  const handle = useQuery({ queryKey: ["mail-handle"], queryFn: () => Users.mailHandle() });
  const h = handle.data?.handle || "";
  const page = useQuery({ queryKey: ["me", "public-page", h], queryFn: () => Public.person(h), enabled: !!h, retry: false });
  const url = h && typeof window !== "undefined" ? `${window.location.origin}/@${h}` : "";
  const open = !!page.data;
  return (
    <Section title={t("profile.public_page")} description={t("profile.public_page_desc")}>
      {!h ? (
        <p className="text-sm text-muted-fg">
          {t("profile.public_page_no_handle")} <Link href="/app/account" className="text-accent underline-offset-2 hover:underline">{t("profile.public_page_set_handle")}</Link>
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded-lg bg-muted px-2.5 py-1.5 text-sm">{url.replace(/^https?:\/\//, "")}</code>
            <Button size="sm" variant="outline" onClick={() => { navigator.clipboard?.writeText(url); toast.success(t("common.copied")); }}>{t("common.copy")}</Button>
            {open ? <a href={`/@${h}`} target="_blank" rel="noreferrer" className="text-sm text-accent underline-offset-2 hover:underline">{t("profile.public_page_open")}</a> : null}
          </div>
          {!open && !page.isLoading ? (
            <p className="text-sm text-muted-fg">
              {t("profile.public_page_needs_link")} <Link href="/app/agents" className="text-accent underline-offset-2 hover:underline">{t("profile.public_page_go_agents")}</Link>
            </p>
          ) : null}
          {open ? <SearchListingRow /> : null}
        </div>
      )}
    </Section>
  );
}

/** 프로필에 내 인맥 목록을 누가 볼 수 있나 (plan/43 §5). [인맥] 화면에 있던 것을 여기로 옮겼다 (plan/57):
 *  [내 정보] 에서 공개 범위를 정하는 곳은 프로필 하나이고, 이것도 프로필에 보이는 것이다. */
function ConnectionsVisibility() {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const save = useMutation({
    mutationFn: (v: string) => Users.patchMe({ network_public: v }),
    onSuccess: (u) => { setUser(u); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <Section title={t("profile.connections")} description={t("profile.connections_desc")}
      action={<VisibilityPicker value={normalize(user?.network_public ?? "public")} onChange={(v) => save.mutate(v)} />}>
      <p className="text-xs text-muted-fg">{t("profile.connections_hint")}</p>
    </Section>
  );
}

/** 광장에서 쓰는 이름 (plan/52).
 *
 *  내 정보의 다른 칸과 성격이 다르다. 공개 범위가 없고, 어디에도 내 계정과 함께
 *  나가지 않는다. 여기 있는 이유는 정하는 자리가 여기가 맞아서다.
 *
 *  자주 바꾸면 이름이 아니라 가면이 된다. 한 주에 한 번만 바꾼다.
 */
function CommunityNameCard() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me", "community-name"], queryFn: () => Users.communityName() });
  const [name, setName] = useState("");
  const [ask, setAsk] = useState(false);
  useEffect(() => { if (q.data) setName(q.data.name); }, [q.data]);

  const had = (q.data?.name ?? "").trim();
  const wait = q.data?.wait_days ?? 0;
  const want = name.trim();
  const changed = want.toLowerCase() !== had.toLowerCase();
  const locked = !!had && wait > 0;

  const save = useMutation({
    mutationFn: () => Users.setCommunityName(want),
    onSuccess: (r) => {
      qc.setQueryData(["me", "community-name"], r);
      qc.invalidateQueries({ queryKey: ["c"] });
      setAsk(false);
      toast.success(t("profile.square_name_saved"));
    },
    onError: (e) => { setAsk(false); toast.error(friendlyError(e, locale)); },
  });

  return (
    <Section title={t("profile.square_name")} description={t("profile.square_name_desc")}>
      {q.isLoading ? <Skeleton className="h-10" /> : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={30} disabled={locked}
                   placeholder={t("profile.square_name_ph")} className="h-10 w-full sm:w-64" aria-label={t("profile.square_name")} />
            <Button variant="accent" disabled={locked || !changed || want.length < 2} loading={save.isPending}
                    onClick={() => (had ? setAsk(true) : save.mutate())}>
              {had ? t("profile.square_name_change") : t("common.save")}
            </Button>
          </div>
          <p className="text-xs text-muted-fg">
            {locked ? t("profile.square_name_wait", { n: wait })
                    : had ? t("profile.square_name_rule", { n: q.data?.change_days ?? 7 })
                          : t("profile.square_name_unset")}
          </p>
        </div>
      )}
      <ConfirmDialog open={ask} onClose={() => setAsk(false)} onConfirm={() => save.mutate()}
                     title={t("profile.square_name_warn_title")}
                     description={t("profile.square_name_warn", { old: had, next: want, n: q.data?.change_days ?? 7 })}
                     confirmLabel={t("profile.square_name_change")} cancelLabel={t("common.cancel")} loading={save.isPending} />
    </Section>
  );
}

/** Whoever has the address can always read the page. Turning up in a search for your own
 *  name is a different thing to agree to, so it is its own switch. */
function SearchListingRow() {
  const t = useT(); const locale = useLocale();
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const on = user?.page_indexable !== false;
  const save = useMutation({
    mutationFn: (next: boolean) => Users.patchMe({ page_indexable: next }),
    onSuccess: (u) => { setUser(u); toast.success(t("common.saved")); },
    onError: (e) => toast.error(friendlyError(e, locale)),
  });
  return (
    <div className="pt-1">
      <SwitchRow title={t("profile.search_listing")} description={t("profile.search_listing_desc")}
                 checked={on} onChange={(v) => save.mutate(v)} disabled={save.isPending} />
    </div>
  );
}

export function ProfilePage() {
  const t = useT(); const locale = useLocale(); const qc = useQueryClient();
  const q = useQuery({ queryKey: ["profile"], queryFn: Users.profile });
  const taxonomy = useQuery({ queryKey: ["job-taxonomy"], queryFn: Community.jobTaxonomy, staleTime: 600_000 });
  // 관리자가 기업 기능을 끄면 소속과 회사 인증은 여기에도 없다 — 새로 넣을 수도 없다 (plan/71).
  const companies = useCompanyFeatures().on;
  const [data, setData] = useState<Record<string, any>>({});
  const [vis, setVis] = useState<Record<string, string>>({});
  useEffect(() => { if (q.data) { setData(q.data.data ?? {}); setVis(q.data.visibility ?? {}); } }, [q.data]);
  const dirty = useMemo(() => !!q.data && (JSON.stringify(data) !== JSON.stringify(q.data.data ?? {}) || JSON.stringify(vis) !== JSON.stringify(q.data.visibility ?? {})), [data, vis, q.data]);
  const save = useMutation({ mutationFn: () => Users.putProfile({ data, visibility: vis }), onSuccess: (r) => { qc.setQueryData(["profile"], { ...r, updated_at: new Date().toISOString() }); toast.success(t("common.saved")); }, onError: (e) => toast.error(friendlyError(e, locale)) });
  const set = (k: string, v: unknown) => setData((p) => ({ ...p, [k]: v }));
  const contact = data.contact ?? {};
  const rowCtx = useMemo(() => ({ t, vis, setVis }), [t, vis]);
  if (q.isLoading) return <Page><Skeleton className="h-96" /></Page>;
  return (
    <ProfileRowCtx.Provider value={rowCtx}>
    <Page className="pb-28">
      {/* [내 정보] 에서 공개 범위가 있는 곳은 여기 하나다 — 칸마다 "내 프로필에서 누구에게 보이나".
          외부인과의 대화에서 무엇을 쓸지는 비서마다 [지식] 탭에서 정한다 (plan/57). */}
      <PageHeader title={t("nav.profile")} description={t("profile.desc")} />
      <div className="space-y-4">
        <PublicPageCard />
        <ConnectionsVisibility />
        <CommunityNameCard />
        <Section title={t("profile.basic")}>
          <div className="divide-y divide-border">
            <Row k="full_name"><Input value={data.full_name ?? ""} onChange={(e) => set("full_name", e.target.value)} /></Row>
            <Row k="preferred_name"><Input value={data.preferred_name ?? ""} onChange={(e) => set("preferred_name", e.target.value)} /></Row>
            <Row k="title"><Input value={data.title ?? ""} onChange={(e) => set("title", e.target.value)} /></Row>
            {companies ? <Row k="company"><CompanyVerifyCard value={data.company ?? ""} onChange={(v) => set("company", v)} /></Row> : null}
            <Row k="bio"><Textarea value={data.bio ?? ""} maxLength={1500} onChange={(e) => set("bio", e.target.value)} /></Row>
            <Row k="location"><Input value={data.location ?? ""} onChange={(e) => set("location", e.target.value)} /></Row>
            <Row k="languages"><TagInput value={Array.isArray(data.languages) ? data.languages : []} onChange={(v) => set("languages", v)} placeholder={t("profile.languages_placeholder")} /></Row>
            <Row k="links"><TagInput value={Array.isArray(data.links) ? data.links : []} onChange={(v) => set("links", v)} placeholder="https://…" /></Row>
          </div>
        </Section>
        {/* The community's taxonomy, on a person: what they do, where they are, what the
            company does. The same three a posting asks for, in the same dialog. */}
        <Section title={t("profile.field")}>
          <div className="divide-y divide-border">
            <TaxoRow k="job_codes" nodes={taxonomy.data?.jobs} title={t("job.family")} hint={t("job.family_hint")} max={5}
                     value={Array.isArray(data.job_codes) ? data.job_codes : []} onChange={(v) => set("job_codes", v)} />
            <TaxoRow k="region_codes" nodes={taxonomy.data?.regions} title={t("job.location")} hint={t("job.location_hint")} max={5}
                     value={Array.isArray(data.region_codes) ? data.region_codes : []} onChange={(v) => set("region_codes", v)} />
            <TaxoRow k="industry_codes" nodes={taxonomy.data?.industries} title={t("job.industry")} hint={t("job.industry_hint")} max={3}
                     value={Array.isArray(data.industry_codes) ? data.industry_codes : []} onChange={(v) => set("industry_codes", v)} />
          </div>
        </Section>
        <Section title={t("profile.contact")}>
          <div className="divide-y divide-border">
            <Row k="contact.email"><Input type="email" value={contact.email ?? ""} onChange={(e) => set("contact", { ...contact, email: e.target.value })} /></Row>
            <Row k="contact.phone"><Input type="tel" value={contact.phone ?? ""} onChange={(e) => set("contact", { ...contact, phone: e.target.value })} /></Row>
            <Row k="contact_rules" hint={t("profile.contact_rules_hint")}><Textarea value={data.contact_rules ?? ""} maxLength={1000} onChange={(e) => set("contact_rules", e.target.value)} className="min-h-[72px]" /></Row>
          </div>
        </Section>
        {/* 연락 가능 시간은 [내 정보 → 스케줄] 로 옮겼다 (plan/56) — 일정과 한자리에서 정한다. */}
        {/* The same profile feeds the community: this decides what a post's author line says.
            It is the member's call, exactly like the secretary's disclosure settings. */}
        <Section title={t("profile.community")} description={t("profile.community_desc")}>
          <Field label={t("profile.community_identity")} hint={t(`profile.ident_hint_${data.community_identity || "job"}`)}>
            <Select value={String(data.community_identity ?? "job")} onChange={(e) => set("community_identity", e.target.value)}>
              <option value="job">{t("profile.ident_job")}</option>
              <option value="name_only">{t("profile.ident_name")}</option>
            </Select>
          </Field>
          <p className="mt-2 rounded-xl bg-muted px-3 py-2 text-xs text-muted-fg">
            {t("profile.ident_preview")}: <span className="font-medium text-fg">{(data.preferred_name || data.full_name || "").toString() || t("profile.ident_you")}</span>
            {String(data.community_identity ?? "job") === "job" && (data.title || (companies && data.company))
              ? <span> | {[data.title, companies ? data.company : ""].filter(Boolean).join(" · ")}</span> : null}
          </p>
        </Section>
        <Section title={t("profile.extra")} description={t("profile.extra_desc")} action={<V k="extra" />}>
          <Textarea value={data.extra ?? ""} maxLength={3000} onChange={(e) => set("extra", e.target.value)} className="min-h-[120px]" />
        </Section>
      </div>
      {dirty ? (
        <div /* sticky inside the content column: a viewport-fixed bar ran under the sidebar and centred on the window */
          className="bottom-bar sticky bottom-0 z-20 -mx-4 mt-4 mb-16 border-t border-border bg-card/95 px-4 backdrop-blur md:-mx-6 md:mb-0 md:px-6 pb-[var(--sab)]">
          <div className="flex items-center justify-between gap-3 py-3"><span className="text-sm text-muted-fg">{t("common.unsaved_changes")}</span>
            <div className="flex gap-2"><Button variant="ghost" onClick={() => { setData(q.data!.data ?? {}); setVis(q.data!.visibility ?? {}); }}>{t("common.discard")}</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></div></div>
        </div>
      ) : null}
    </Page>
    </ProfileRowCtx.Provider>
  );
}

