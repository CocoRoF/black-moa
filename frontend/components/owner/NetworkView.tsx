"use client";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, GitBranch, List, MessageSquare, Network as NetworkIcon, Search, UserPlus } from "@/components/icons";
import Link from "next/link";
import { Network, type Account, type NetNode, type Suggestion } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useDebounced } from "@/lib/hooks";
import { Page } from "./Shell";
import { Segmented, Tabs } from "@/components/ui/tabs";
import { Button, buttonLook } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Sheet } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { PageHeader, Avatar } from "@/components/ui/misc";
import { NodeMemo } from "./NodeMemo";
import { ConnectionControl, statusOf } from "@/components/network/Connection";
import { useMessenger } from "@/stores/messenger";

const GraphView = dynamic(() => import("@/components/network/GraphView"), { ssr: false, loading: () => <Skeleton className="h-full w-full" /> });

export function NetworkPage() {
  const t = useT(); const qc = useQueryClient();
  const openWith = useMessenger((s) => s.openWith);
  // The inbox links straight at a tab: a notice about a request should land on the
  // request, not on the graph (plan/41 §9.1).
  const wanted = useSearchParams().get("tab");
  // Five tabs, one per thing a person actually wants to see (plan/43 §3): the picture,
  // the people who chose each other, my own half, theirs, and who to connect to next.
  const TABS = ["graph", "friends", "outgoing", "incoming", "suggest"] as const;
  type Tab = (typeof TABS)[number];
  const [tab, setTab] = useState<Tab>(TABS.includes(wanted as Tab) ? (wanted as Tab) : "graph");
  const [finding, setFinding] = useState(false);
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [kind, setKind] = useState(""); const [tag, setTag] = useState(""); const [q, setQ] = useState(""); const dq = useDebounced(q, 300);
  const [sel, setSel] = useState<string | null>(null);
  const stats = useQuery({ queryKey: ["network", "stats"], queryFn: Network.stats });
  const graph = useQuery({ queryKey: ["network", "graph", { kind, tag, dq }], queryFn: () => Network.graph({ kinds: kind || undefined, tags: tag || undefined, q: dq || undefined }), placeholderData: keepPreviousData });
  const links = useQuery({ queryKey: ["network", "links"], queryFn: Network.links });
  const suggest = useQuery({ queryKey: ["network", "suggest"], queryFn: Network.suggestions });
  const inval = () => qc.invalidateQueries({ queryKey: ["network"] });
  const nodes = graph.data?.nodes ?? []; const edges = graph.data?.edges ?? [];
  const topTags: { tag: string; count: number }[] = useMemo(() => (stats.data?.top_tags ?? []).map((x: any) => (Array.isArray(x) ? { tag: x[0], count: x[1] } : x)), [stats.data]);

  return (
    <Page className="flex flex-col h-full min-h-0">
      {/* One way in, and it goes through a person. Typing a stranger into a form, drawing a
          relation between two cards, or importing a spreadsheet all added people who never
          agreed to be here and could never be kept up to date — an address book wearing a
          graph's clothes. What is left is: connect to someone real, or add a guest who
          actually came to see you (plan/31). */}
      {/* One heading. Finding people is a step inside 인맥, not a page stacked on top of
          it, so the page's own title changes and gains a way back — rather than a second
          title arriving underneath the first. */}
      <PageHeader
        title={finding ? t("net.find_people") : t("nav.network")}
        description={finding ? t("net.find_people_desc") : t("net.desc")}
        lead={finding ? <Button variant="ghost" size="icon" aria-label={t("common.back")} onClick={() => setFinding(false)}><ArrowLeft className="h-5 w-5" /></Button> : undefined}
        action={finding ? undefined : <Button variant="accent" onClick={() => setFinding(true)}><Search className="h-4 w-4" />{t("net.find_people")}</Button>}
      />
      {finding ? <FindPeoplePanel /> : (
      <>
      <Tabs value={tab} onChange={setTab} className="mb-3" items={[
        { key: "graph", label: t("net.tab_graph") },
        { key: "friends", label: t("net.tab_friends"), count: links.data?.friends.length },
        { key: "outgoing", label: t("net.tab_outgoing"), count: links.data?.outgoing.length },
        { key: "incoming", label: t("net.tab_incoming"), count: links.data?.incoming.length },
        { key: "suggest", label: t("net.tab_suggest"), count: suggest.data?.items.length },
      ]} />
      {tab === "graph" ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Segmented value={mode} onChange={setMode} options={[{ value: "graph", label: <span className="inline-flex items-center gap-1"><GitBranch className="h-3.5 w-3.5" />{t("net.view_graph")}</span> }, { value: "list", label: <span className="inline-flex items-center gap-1"><List className="h-3.5 w-3.5" />{t("net.view_list")}</span> }]} />
            <div className="relative min-w-[180px] flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" /><Input className="h-10 pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("net.search")} /></div>
            <Select value={kind} onChange={(e) => setKind(e.target.value)} className="h-10 w-auto"><option value="">{t("net.all_kinds")}</option>{Object.keys(stats.data?.kinds ?? {}).map((k) => <option key={k} value={k}>{k}</option>)}</Select>
            <Select value={tag} onChange={(e) => setTag(e.target.value)} className="h-10 w-auto"><option value="">{t("net.all_tags")}</option>{topTags.map((x) => <option key={x.tag} value={x.tag}>{x.tag} ({x.count})</option>)}</Select>
          </div>
          {graph.isLoading ? <Skeleton className="h-[60vh]" /> : nodes.length === 0 ? <EmptyState icon={<NetworkIcon />} title={t("net.empty")} description={t("net.empty_desc")} action={<Button variant="accent" onClick={() => setFinding(true)}>{t("net.find_people")}</Button>} />
            : mode === "graph" ? <div className="h-[calc(100dvh-420px)] min-h-[360px]"><GraphView nodes={nodes} edges={edges} selected={sel} onSelect={setSel} /></div>
            : <CardList nodes={nodes.filter((n) => !n.is_self && n.kind !== "source")} onOpen={setSel} />}
          {graph.data?.truncated ? <p className="mt-2 text-xs text-muted-fg">{t("net.truncated")}</p> : null}
        </>
      ) : tab === "friends" || tab === "outgoing" || tab === "incoming" ? (
        <PeoplePanel which={tab} links={links} onFind={() => setFinding(true)} />
      ) : (
        <SuggestPanel suggest={suggest} onFind={() => setFinding(true)} />
      )}
      </>
      )}
      {sel?.startsWith("source:") ? (
        <SourceSheet node={nodes.find((n) => n.id === sel) ?? null} onClose={() => setSel(null)} />
      ) : (
        <NodeMemo id={sel} onClose={() => setSel(null)} onChanged={inval}
                  onMessage={(to) => { setSel(null); openWith(to); }} />
      )}
    </Page>
  );
}

/** 연결한 곳(Google 연락처 …) — 사람이 아니라 사람들이 들어온 문 (plan/79). 몇 명이 여기로 들어왔고, 가져오기는
 *  어디서 관리하는지만 말한다. */
function SourceSheet({ node, onClose }: { node: NetNode | null; onClose: () => void }) {
  const t = useT();
  if (!node) return null;
  const key = `net.source_${node.source}`;
  const name = t(key) !== key ? t(key) : node.name;
  return (
    <Sheet open onClose={onClose} side="right" title={name}>
      <div className="space-y-4">
        <p className="text-sm text-muted-fg">{t("net.source_sheet_desc", { name, n: node.attrs?.count ?? 0 })}</p>
        <Link href="/app/account#connections" className={buttonLook("outline", "sm")}>{t("net.source_manage")}</Link>
      </div>
    </Sheet>
  );
}

/** A face and a name, at the size the surrounding list needs. Falls back to initials, the
 *  same way the graph does, so a person without a photo still reads as a person. */
function Face({ src, name, size = 40 }: { src?: string | null; name?: string | null; size?: number }) {
  return <Avatar name={name ?? ""} src={src ?? undefined} size={size} />;
}

/** One person, one line (plan/43 §4).
 *
 *  A card somebody keeps about a person is not the person. When the card is bound to a
 *  member, pressing it goes to that member's own page; otherwise it opens the note the
 *  owner wrote, which is all a card on this page ever was. */
function CardList({ nodes, onOpen }: { nodes: NetNode[]; onOpen: (id: string) => void }) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
      {nodes.map((n) => {
        const sub = [n.attrs?.title, n.attrs?.company].filter(Boolean).join(" · ")
          || (typeof n.attrs?.email === "string" ? n.attrs.email : "");
        const inner = (
          <>
            <Face src={n.avatar_url} name={n.name} size={44} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{n.name}</span>
              <span className="block truncate text-xs text-muted-fg">{sub}</span>
            </span>
          </>
        );
        const cls = "flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-muted/50";
        return (
          <li key={n.id}>
            {n.user_id
              /* One gesture, one panel: a member opens the same memo the graph opens, and
                 the page about them is one press further, inside it (plan/44 §8). */
              ? <button type="button" onClick={() => onOpen(n.id)} className={cls}>{inner}</button>
              : <button type="button" onClick={() => onOpen(n.id)} className={cls}>{inner}</button>}
          </li>
        );
      })}
    </ul>
  );
}

function PersonRow({ a, right, sub, onOpen }: { a: Account; right?: React.ReactNode; sub?: React.ReactNode; onOpen?: () => void }) {
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      {/* The face is the way in: on a page about people, a photo that does nothing when you
          press it is a photo pretending to be a person. */}
      <Link href={`/app/u/${a.id}`} onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg hover:opacity-90">
        <Face src={a.avatar_url} name={a.display_name} size={44} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{a.display_name}</span>
          <span className="block truncate text-xs text-muted-fg">{sub ?? (a.handle ? `@${a.handle}` : a.email ?? "")}</span>
        </span>
      </Link>
      {right ? <div className="flex shrink-0 items-center gap-2">{right}</div> : null}
    </li>
  );
}

/** Friends, and the requests in both directions.
 *
 *  A connection between two accounts is the only thing on this page both people agreed to,
 *  so it gets its own list rather than being buried among the cards. */
/** 인맥, 내가 연결한, 나를 연결한 — three views of one act (plan/43 §3).
 *
 *  There is nothing to accept here. Connecting back is the same button that connects, and
 *  it is what makes the two of you 인맥. */
function PeoplePanel({ which, links, onFind }: {
  which: "friends" | "outgoing" | "incoming";
  links: ReturnType<typeof useQuery<{ friends: Account[]; incoming: Account[]; outgoing: Account[] }>>;
  onFind: () => void;
}) {
  // 연결을 바꾸면 Connection.applyLink 가 이 목록을 다시 받는다.
  const t = useT();
  const openWith = useMessenger((s) => s.openWith);
  if (links.isLoading) return <Skeleton className="h-40" />;
  const rows = links.data?.[which] ?? [];
  if (!rows.length) {
    return <EmptyState icon={<UserPlus />} title={t(`net.no_${which}`)} description={t(`net.no_${which}_desc`)}
                       action={<Button variant="accent" onClick={onFind}>{t("net.find_people")}</Button>} />;
  }
  // 이 탭이 곧 지금 사이다: 인맥 · 내가 연결 · 나를 연결. 단추는 어디서나 같은 [인맥 맺기] · [인맥 지우기].
  const known = which === "friends" ? "mutual" : which;
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
      {rows.map((a) => (
        <PersonRow key={a.id} a={a} sub={a.handle ? `@${a.handle}` : ""} right={
          <span className="flex items-center gap-1">
            {/* Writing to somebody is the thing this list is for. It used to end at the
                name (plan/44 §7). */}
            <Button size="sm" variant="ghost" aria-label={t("msg.message")} onClick={() => openWith({ userId: a.id })}>
              <MessageSquare className="h-4 w-4" />
            </Button>
            <ConnectionControl userId={a.id} name={a.display_name} known={a.link ? statusOf(a.link) : known} showState={false} />
          </span>
        } />
      ))}
    </ul>
  );
}

/** Who to connect to next. Only people who already did something: they connected to me, or
 *  they talked to my secretary (plan/43 §3). */
function SuggestPanel({ suggest, onFind }: {
  suggest: ReturnType<typeof useQuery<{ items: Suggestion[] }>>;
  onFind: () => void;
}) {
  const t = useT();
  if (suggest.isLoading) return <Skeleton className="h-40" />;
  const rows = suggest.data?.items ?? [];
  if (!rows.length) {
    return <EmptyState icon={<UserPlus />} title={t("net.suggest_none")} description={t("net.suggest_hint")}
                       action={<Button variant="accent" onClick={onFind}>{t("net.find_people")}</Button>} />;
  }
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
      {rows.map((a) => (
        <PersonRow key={a.id} a={a}
          sub={a.reason === "connected_me" ? t("net.why_connected_me") : t("net.why_guest")}
          right={<ConnectionControl userId={a.id} name={a.display_name} known={statusOf(a.link)} showState={false} />} />
      ))}
    </ul>
  );
}

/** 인맥 찾기: a list you scan and add from.
 *
 *  Opens on people this account already has a reason to know — someone who talked to my
 *  secretary and turns out to have an account, or a connection of a connection, each row
 *  carrying that reason. Typing searches the directory instead. Neither view is a listing
 *  of accounts: every name here arrives with why it is here. */
function FindPeoplePanel() {
  const t = useT();
  const [q, setQ] = useState(""); const dq = useDebounced(q, 300);
  const searching = dq.trim().length >= 2;
  const res = useQuery({ queryKey: ["network", "people-search", dq], queryFn: () => Network.peopleSearch(dq), enabled: searching });
  const sug = useQuery({ queryKey: ["network", "suggestions"], queryFn: Network.suggestions });
  const list: (Account & Partial<Suggestion>)[] = searching ? (res.data?.items ?? []) : (sug.data?.items ?? []);
  const loading = searching ? res.isLoading : sug.isLoading;
  const why = (a: Partial<Suggestion>) =>
    a.reason === "guest" ? t("net.why_guest")
      : a.reason === "connected_me" ? t("net.why_connected_me")
      : undefined;
  return (
    <div className="space-y-4">
      {/* No heading here: the page header above is already this panel's title. */}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
        <Input autoFocus className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("net.find_people_ph")} />
      </div>
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">{searching ? t("net.find_results") : t("net.suggest_title")}</h3>
        <span className="text-xs text-muted-fg">{searching ? t("net.find_people_hint") : t("net.suggest_hint")}</span>
      </div>
      {loading ? <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[68px]" />)}</div>
        : list.length === 0 ? <EmptyState icon={<UserPlus />} title={searching ? t("net.find_none") : t("net.suggest_none")} description={searching ? "" : t("net.suggest_hint")} />
        : (
          <ul className="space-y-2">{list.map((a) => (
            <PersonRow key={a.id} a={a} sub={why(a) ?? (a.handle ? `@${a.handle}` : a.email ?? "")}
              right={<ConnectionControl userId={a.id} name={a.display_name} known={statusOf(a.link)} />} />
          ))}</ul>
        )}
    </div>
  );
}

/** A card, and the note on it (plan/43 §4).
 *
 *  This used to be a drawer with the person's relations, their attributes, a star rating,
 *  a visibility switch and a form for logging meetings. None of that was ever filled in,
 *  and all of it was in the way of the one thing a card is for: remembering something
 *  about somebody. So it is a note, and it opens where you are.
 */
