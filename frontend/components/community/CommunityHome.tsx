"use client";
import { useCallback, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Eye, Flame, MessageCircle, PenLine, Search, ShieldAlert, Sparkles, ThumbsUp, TrendingUp, UserRound } from "@/components/icons";
import { Community, type CommunityPost } from "@/lib/api";
import { useLocale, useT } from "@/lib/i18n";
import { fmtNumber, fmtRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "@/components/owner/Shell";
import { Button, buttonLook } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Avatar } from "@/components/ui/misc";
import { Face } from "@/components/profile/Face";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { Segmented } from "@/components/ui/tabs";
import { Busy } from "@/components/ui/busy";
import { BoardIcon } from "@/components/icons";

type Sort = "for_me" | "hot" | "new";

/** One place the feed's cache key is spelled, so a prefetch cannot miss by a field. */
const feedKey = (board: string | undefined, sort: Sort, q: string, mine: boolean) =>
  ["c", "posts", board ?? "", sort, q, mine] as const;

/** The community front page: topics on the left, the feed in the middle, and what is
 *  popular *here* on the right — scoped to whatever topic is open, because a global list
 *  beside a filtered feed is the same list twice. */
export function CommunityHome({ boardSlug, mine }: { boardSlug?: string; mine?: boolean }) {
  const t = useT(); const locale = useLocale();
  const [sort, setSort] = useState<Sort>(mine ? "new" : boardSlug ? "hot" : "for_me");
  // Three ways to read a feed, each with its own mark: what suits you, what is moving, what
  // just landed. A fourth ("most liked") only re-sorted the same rows as "hot".
  const SORTS: { value: Sort; label: string; icon: React.ReactNode }[] = [
    ...(mine ? [] : [{ value: "for_me" as const, label: t("com.for_me"), icon: <Sparkles className="h-3.5 w-3.5" /> }]),
    { value: "hot", label: t("com.hot"), icon: <Flame className="h-3.5 w-3.5" /> },
    { value: "new", label: t("com.new"), icon: <Clock className="h-3.5 w-3.5" /> },
  ];
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");

  const boards = useQuery({ queryKey: ["c", "boards"], queryFn: () => Community.boards("discussion"), staleTime: 300_000 });
  const me = useQuery({ queryKey: ["c", "me"], queryFn: Community.me, staleTime: 120_000 });
  // keepPreviousData is what makes a sort or a search read as the same list rearranging:
  // without it every key change empties the query and the feed collapses into skeletons.
  const posts = useQuery({
    queryKey: feedKey(boardSlug, sort, query, !!mine),
    queryFn: () => Community.posts({ board: boardSlug, sort, q: query || undefined, mine, limit: 30 }),
    placeholderData: keepPreviousData,
  });
  const trending = useQuery({
    queryKey: ["c", "trending"],
    queryFn: () => Community.posts({ sort: "hot", limit: 6 }),
    staleTime: 120_000,
    placeholderData: keepPreviousData,
  });
  // What is hot across the service stays put; a topic adds its own list under it.
  const boardTrending = useQuery({
    queryKey: ["c", "trending", boardSlug],
    queryFn: () => Community.posts({ sort: "hot", limit: 6, board: boardSlug }),
    enabled: !!boardSlug,
    staleTime: 120_000,
    placeholderData: keepPreviousData,
  });
  const board = useMemo(() => boards.data?.items.find((b) => b.slug === boardSlug), [boards.data, boardSlug]);
  const canWrite = me.data ? me.data.can_write : true;
  const writeHref = `/app/community/write${boardSlug ? `?board=${boardSlug}` : ""}`;

  // Switching topic is a route change, so the feed cannot be kept across it — but it can
  // already be in the cache by the time the click lands, and the rail can mark the target
  // the moment it is clicked instead of after the new page mounts.
  const qc = useQueryClient();
  const router = useRouter();
  const [, startNav] = useTransition();
  const here = mine ? "/app/community/mine" : boardSlug ? `/app/community/b/${boardSlug}` : "/app/community";
  const [goingTo, setGoingTo] = useState<string | null>(null);
  const current = goingTo ?? here;

  const warm = useCallback((href: string, slug?: string) => {
    router.prefetch(href);
    qc.prefetchQuery({
      queryKey: feedKey(slug, slug ? "hot" : "for_me", "", false),
      queryFn: () => Community.posts({ board: slug, sort: slug ? "hot" : "for_me", limit: 30 }),
      staleTime: 30_000,
    });
    if (slug) {
      qc.prefetchQuery({ queryKey: ["c", "trending", slug], queryFn: () => Community.posts({ sort: "hot", limit: 6, board: slug }), staleTime: 120_000 });
    }
  }, [qc, router]);

  const go = useCallback((href: string) => {
    setGoingTo(href);
    startNav(() => router.push(href, { scroll: false }));
  }, [router]);

  const busy = posts.isFetching && !posts.isLoading;

  return (
    <Page>
      <div className="grid gap-5 lg:grid-cols-[212px_minmax(0,1fr)] xl:grid-cols-[212px_minmax(0,1fr)_286px]">
        <aside className="hidden lg:block">
          <div className="sticky top-4 space-y-1">
            <div className="px-2 pb-1 text-xs font-medium text-muted-fg">{t("com.topics")}</div>
            <BoardLink href="/app/community" active={current === "/app/community"} label={t("com.all")} icon="home" onGo={go} onWarm={warm} />
            {(boards.data?.items ?? []).map((b) => (
              <BoardLink key={b.slug} href={`/app/community/b/${b.slug}`} active={current === `/app/community/b/${b.slug}`}
                         slug={b.slug} label={b.name} icon={b.icon} count={b.post_count} onGo={go} onWarm={warm} />
            ))}
            {/* 맛집 has its own page — a map, not a list — so it sits with the topics but goes elsewhere. */}
          </div>
        </aside>

        <div className="min-w-0">
          <header className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3.5">
            <div className="min-w-0 flex-1">
              <h1 className="text-xl font-semibold tracking-tight">
                {mine ? t("com.mine") : board ? board.name : t("com.title")}
              </h1>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-muted-fg">
                {mine ? t("com.mine_desc") : board ? (
                  // A tagline says what a topic is for; these numbers say whether anyone is
                  // there, which is what decides whether to read on.
                  <>
                    <span>{t("com.stat_posts", { n: fmtNumber(board.post_count) })}</span>
                    <span aria-hidden>·</span>
                    <span>{t("com.stat_people", { n: fmtNumber(board.people_count) })}</span>
                    {board.last_post_at ? <><span aria-hidden>·</span>
                      <span>{t("com.stat_last", { when: fmtRelative(board.last_post_at, locale) })}</span></> : null}
                  </>
                ) : t("com.subtitle")}
              </p>
            </div>
            {/* Say why the button will refuse before it is pressed. */}
            {canWrite ? (
              <Link href={writeHref} className={buttonLook("accent", "md")}><PenLine className="h-4 w-4" />{t("com.write")}</Link>
            ) : (
              <Link href="/app/account" className={buttonLook("outline", "md")}><ShieldAlert className="h-4 w-4" />{t("com.verify_to_write")}</Link>
            )}
          </header>

          {/* The nudge that turns an anonymous reader into someone others recognise. */}
          {me.data && !me.data.readiness.complete ? (
            <Link href="/app/profile" className="mb-3 flex items-center gap-3 rounded-2xl border border-accent/40 bg-accent/10 px-4 py-3 text-sm hover:bg-accent/15">
              <UserRound className="h-5 w-5 shrink-0 text-accent" />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{t("com.nudge_title")}</span>
                <span className="block text-xs text-muted-fg">{me.data.readiness.has_name ? t("com.nudge_job") : t("com.nudge_name")}</span>
              </span>
              <span className="shrink-0 text-xs text-accent">{t("com.nudge_go")}</span>
            </Link>
          ) : null}

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Segmented value={sort} onChange={setSort} size="sm" ariaLabel={t("com.sort")}
              options={SORTS.map((o) => ({ value: o.value, label: <span className="inline-flex items-center gap-1.5">{o.icon}{o.label}</span> }))} />
            <form className="flex w-full items-center gap-1 sm:ml-auto sm:w-auto" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("com.search")} className="h-10 min-w-0 flex-1 sm:h-9 sm:w-56 sm:flex-none" />
              <Button type="submit" variant="ghost" size="icon" aria-label={t("com.search")}><Search className="h-4 w-4" /></Button>
            </form>
          </div>

          {/* Topic picker for phones, where the rail is off screen */}
          {!mine ? (
            <div className="-mx-1 mb-3 flex gap-1.5 overflow-x-auto px-1 py-0.5 scroll-fade-x lg:hidden">
              <Chip href="/app/community" active={current === "/app/community"} label={t("com.all")} icon="home" onGo={go} />
              {(boards.data?.items ?? []).map((b) => (
                <Chip key={b.slug} href={`/app/community/b/${b.slug}`} active={current === `/app/community/b/${b.slug}`}
                      label={b.name} icon={b.icon} onGo={go} />
              ))}
            </div>
          ) : null}

          {/* One container for every state, so the feed never disappears and reappears. */}
          <Busy busy={busy} className="min-h-[180px]">
            {posts.isLoading ? (
              <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
            ) : (posts.data?.items.length ?? 0) === 0 ? (
              <EmptyState icon={<MessageCircle />} title={t("com.empty_title")} description={t("com.empty_desc")}
                action={canWrite ? <Link href={writeHref} className={buttonLook("accent", "md")}>{t("com.write")}</Link> : undefined} />
            ) : (
              <ul key={`${boardSlug ?? ""}:${sort}:${query}`} className="list-in divide-y divide-border overflow-hidden rounded-2xl border border-border bg-card">
                {posts.data!.items.map((p) => <PostRow key={p.id} post={p} locale={locale} showBoard={!boardSlug} />)}
              </ul>
            )}
          </Busy>
        </div>

        {/* Not xl-only any more. As the third grid child it sits in the right rail on a
            wide screen and falls in under the feed on a phone, where it used to be simply
            absent — the community's whole discovery surface, invisible on the device most
            people read it on. */}
        <aside className="min-w-0">
          <div className="space-y-3 xl:sticky xl:top-4">
            <TrendingCard title={t("com.trending")} icon={<TrendingUp className="h-4 w-4" />} q={trending} />
            {board ? (
              <TrendingCard title={t("com.trending_in", { name: board.name })}
                            icon={<Flame className="h-4 w-4" />} q={boardTrending} />
            ) : null}
          </div>
        </aside>
      </div>
    </Page>
  );
}

function TrendingCard({ title, icon, q }: {
  title: string; icon: React.ReactNode;
  q: { isLoading: boolean; data?: { items: CommunityPost[] } };
}) {
  const t = useT();
  return (
    <SideCard title={title} icon={icon}>
      {q.isLoading ? <Skeleton className="h-24" />
        : (q.data?.items ?? []).length === 0 ? <p className="px-1 py-2 text-xs text-muted-fg">{t("com.empty_title")}</p>
        : (
          <ol className="space-y-0.5">
            {q.data!.items.slice(0, 6).map((p, i) => (
              <li key={p.id}>
                <Link href={`/app/community/p/${p.id}`} className="flex items-start gap-2 rounded-lg px-1.5 py-1.5 hover:bg-muted">
                  <span className="w-4 shrink-0 text-center text-xs font-semibold tabular-nums text-accent">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2 text-[13px] leading-snug">{p.title}</span>
                    <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-fg">
                      <span className="inline-flex items-center gap-0.5"><ThumbsUp className="h-3 w-3" />{fmtNumber(p.like_count)}</span>
                      <span className="inline-flex items-center gap-0.5"><MessageCircle className="h-3 w-3" />{fmtNumber(p.comment_count)}</span>
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
    </SideCard>
  );
}

function SideCard({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-card p-3.5">
      <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-muted-fg">{icon}{title}</h2>
      {children}
    </section>
  );
}

function BoardLink({ href, active, label, icon, count, slug, onGo, onWarm }: {
  href: string; active: boolean; label: string; icon: string; count?: number; slug?: string;
  onGo: (href: string) => void; onWarm: (href: string, slug?: string) => void;
}) {
  return (
    // A real anchor — middle-click and "open in new tab" still work — that takes over the
    // plain click so the highlight moves now and the feed is already warm.
    <Link href={href} onMouseEnter={() => onWarm(href, slug)} onFocus={() => onWarm(href, slug)}
      onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; e.preventDefault(); onGo(href); }}
      className={cn("flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-colors duration-150 [&>svg]:h-[18px] [&>svg]:w-[18px] [&>svg]:shrink-0",
      active ? "bg-accent/12 font-medium text-accent" : "text-muted-fg hover:bg-muted hover:text-fg")}>
      <BoardIcon name={icon} />
      <span className="truncate">{label}</span>
      {typeof count === "number" && count > 0 ? <span className="ml-auto text-[11px] tabular-nums text-muted-fg">{count}</span> : null}
    </Link>
  );
}

function Chip({ href, active, label, icon, onGo }: { href: string; active: boolean; label: string; icon?: string; onGo: (href: string) => void }) {
  return (
    <Link href={href} onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; e.preventDefault(); onGo(href); }}
      className={cn("inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13px] transition-colors duration-150",
      active ? "border-accent bg-accent/10 text-accent" : "border-border text-muted-fg")}>
      <BoardIcon name={icon} className="h-3.5 w-3.5" />{label}
    </Link>
  );
}

export function PostRow({ post, locale, showBoard }: { post: CommunityPost; locale: "ko" | "en"; showBoard?: boolean }) {
  const t = useT();
  return (
    <li>
      <Link href={`/app/community/p/${post.id}`} className="block px-4 py-3.5 hover:bg-muted/50">
        <div className="flex items-center gap-2 text-[11px] text-muted-fg">
          {showBoard && post.board ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5">
              <BoardIcon name={post.board.icon} className="h-3 w-3" />{post.board.name}
            </span>
          ) : null}
          <span>{fmtRelative(post.created_at, locale)}</span>
          {post.edited_at ? <span>· {t("com.edited")}</span> : null}
        </div>
        <h3 className="mt-1 truncate text-[15px] font-medium">{post.title}</h3>
        <div className="mt-0.5 flex items-start gap-3">
          {post.excerpt ? <p className="line-clamp-2 flex-1 text-sm text-muted-fg">{post.excerpt}</p> : <span className="flex-1" />}
          {post.images?.length ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={post.images[0]} alt="" className="h-14 w-14 shrink-0 rounded-lg border border-border object-cover" loading="lazy" />
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-fg">
          {post.author ? (
            /* A face beside a real name opens the person. A pen name has no face and
               opens nobody: the square never crosses back into the house (plan/41 §1). */
            <Face id={post.author.pen_name ? "" : post.author.id} className="inline-flex items-center gap-1.5">
              {post.author.pen_name ? null : <Avatar name={post.author.name} src={post.author.avatar_url} size={18} />}
              <span className="font-medium text-fg/80">{post.author.name}</span>
              {post.author.job ? <span className="text-muted-fg">| {post.author.job}</span> : null}
            </Face>
          ) : null}
          <span className="ml-auto inline-flex items-center gap-3 tabular-nums">
            <span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5" />{fmtNumber(post.view_count)}</span>
            <span className={cn("inline-flex items-center gap-1", post.liked && "text-accent")}><ThumbsUp className="h-3.5 w-3.5" />{fmtNumber(post.like_count)}</span>
            <span className="inline-flex items-center gap-1"><MessageCircle className="h-3.5 w-3.5" />{fmtNumber(post.comment_count)}</span>
          </span>
        </div>
      </Link>
    </li>
  );
}
