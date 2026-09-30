"use client";
import { useState, type FormEvent } from "react";
import Link from "next/link";
import Image from "next/image";
import { ArrowRight, Bot, Briefcase, Mail, MapPin, MessageSquareText, Phone, ShieldCheck } from "@/components/icons";
import { LocaleProvider, useT } from "@/lib/i18n";
import { useBrowserLocale } from "@/lib/hooks";
import { Wordmark } from "@/components/brand/Logo";
import { coverFallback } from "@/components/profile/ProfileHeader";

/** What a public page carries. Only fields its owner marked public ever appear here. */
export interface PersonPayload {
  handle: string;
  display_name: string;
  avatar_url: string | null;
  fields: {
    full_name?: string; preferred_name?: string; title?: string; company?: string; bio?: string;
    location?: string; languages?: string[] | string; links?: string[];
    cover?: string; cover_pos?: number; company_verified_at?: string | null;
    contact?: { email?: string; phone?: string }; contact_rules?: string; extra?: string;
  };
  secretary: {
    code: string; name: string; role_line: string; greeting: string;
    avatar_url: string | null; cover_url?: string | null; suggested_questions: string[];
    theme: { accent?: string; avatar_shape?: string };
    status: string; resting: boolean;
  };
  indexable?: boolean;
  posts?: { slug: string; title: string; excerpt: string; published_at: string | null; visibility: string; kind?: string; images?: string[] }[];
  account?: { signed_in: boolean; is_owner: boolean };
}

/** A person's front door (plan/41 §3).
 *
 *  Everywhere else a profile is something you read. Here it is someone you can talk to:
 *  the question box below the introduction opens the conversation with what was typed,
 *  rather than dropping the visitor into an empty chat to start again.
 */
export function PersonPage({ data }: { data: PersonPayload }) {
  const locale = useBrowserLocale();
  return <LocaleProvider locale={locale}><Inner data={data} /></LocaleProvider>;
}

function Inner({ data }: { data: PersonPayload }) {
  const t = useT();
  const [q, setQ] = useState("");
  const f = data.fields ?? {};
  const s = data.secretary;
  const accent = s.theme?.accent || "#1a5fe0";
  const chat = (question?: string) =>
    `/secretary/${encodeURIComponent(s.code)}${question ? `?q=${encodeURIComponent(question)}` : ""}`;
  const ask = (e: FormEvent) => { e.preventDefault(); window.location.href = chat(q.trim() || undefined); };
  const line = [f.title, f.company].filter(Boolean).join(" · ");
  const links = (Array.isArray(f.links) ? f.links : []).filter((x) => typeof x === "string" && x).slice(0, 6);
  const round = s.theme?.avatar_shape !== "square";

  return (
    <div className="min-h-dvh bg-bg">
      <div className="relative h-40 w-full md:h-56"
           style={f.cover ? { backgroundImage: `url(${f.cover})`, backgroundSize: "cover", backgroundPosition: `center ${f.cover_pos ?? 50}%` }
                          : { background: coverFallback(accent) }} aria-hidden />
      {/* A cover can be a dark gradient or somebody's bright photograph, so the mark rides
          on its own scrim rather than hoping for contrast. */}
      <Link href="/" className="absolute left-4 top-4 z-10 inline-flex items-center rounded-xl bg-black/35 px-2.5 py-1.5 backdrop-blur-sm transition-opacity hover:opacity-85">
        <Wordmark size={18} className="brightness-0 invert" />
      </Link>

      {/* `relative` on purpose: the cover above is positioned, and without this the avatar
          that overlaps it would be painted underneath. */}
      <main className="relative mx-auto w-full max-w-[720px] px-5 pb-16">
        <div className="-mt-12 flex items-end gap-4 md:-mt-14">
          {data.avatar_url ? (
            <Image src={data.avatar_url} alt="" width={96} height={96} unoptimized
                   className="h-24 w-24 rounded-full border-4 border-bg object-cover" />
          ) : (
            <div className="flex h-24 w-24 items-center justify-center rounded-full border-4 border-bg text-2xl font-semibold text-white"
                 style={{ background: accent }}>{(data.display_name || "?").slice(0, 1)}</div>
          )}
        </div>

        <h1 className="mt-4 text-2xl font-semibold tracking-tight">{data.display_name}</h1>
        <p className="mt-0.5 text-sm text-muted-fg">@{data.handle}</p>
        {line ? (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-sm">
            <Briefcase className="h-4 w-4 text-muted-fg" />{line}
            {f.company && f.company_verified_at ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success">
                <ShieldCheck className="h-3 w-3" />{t("cx.verified_badge")}
              </span>
            ) : null}
          </p>
        ) : null}
        {f.location ? <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-fg"><MapPin className="h-4 w-4" />{f.location}</p> : null}
        {f.bio ? <p className="mt-4 whitespace-pre-wrap text-[15px] leading-relaxed">{f.bio}</p> : null}
        {f.extra ? <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-muted-fg">{f.extra}</p> : null}
        {f.contact?.email || f.contact?.phone || f.contact_rules ? (
          <div className="mt-4 space-y-1 text-sm">
            {f.contact?.email ? <a href={`mailto:${f.contact.email}`} className="flex items-center gap-1.5 text-muted-fg hover:text-fg"><Mail className="h-4 w-4" />{f.contact.email}</a> : null}
            {f.contact?.phone ? <a href={`tel:${f.contact.phone}`} className="flex items-center gap-1.5 text-muted-fg hover:text-fg"><Phone className="h-4 w-4" />{f.contact.phone}</a> : null}
            {f.contact_rules ? <p className="flex items-start gap-1.5 text-muted-fg"><MessageSquareText className="mt-0.5 h-4 w-4 shrink-0" /><span className="whitespace-pre-wrap">{f.contact_rules}</span></p> : null}
          </div>
        ) : null}
        {links.length ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {links.map((href) => (
              <a key={href} href={href} target="_blank" rel="noreferrer noopener nofollow"
                 className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-fg hover:border-accent hover:text-accent">
                {href.replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 40)}
              </a>
            ))}
          </div>
        ) : null}

        {/* The door into the conversation. It is the page's main action, so it sits in the
            page rather than behind a button that opens somewhere else first. */}
        <section className="mt-8 rounded-2xl border border-border bg-card p-5 shadow-soft">
          <div className="flex items-center gap-3">
            {s.avatar_url ? (
              <Image src={s.avatar_url} alt="" width={44} height={44} unoptimized
                     className={`h-11 w-11 object-cover ${round ? "rounded-full" : "rounded-xl"}`} />
            ) : (
              <div className={`flex h-11 w-11 items-center justify-center text-white ${round ? "rounded-full" : "rounded-xl"}`} style={{ background: accent }}>
                <Bot className="h-5 w-5" />
              </div>
            )}
            <div className="min-w-0">
              <div className="text-sm font-semibold">{t("person.secretary_of", { name: data.display_name, agent: s.name })}</div>
              <div className="truncate text-xs text-muted-fg">{s.role_line || t("person.secretary_role")}</div>
            </div>
          </div>

          {s.status !== "active" || s.resting ? (
            <p className="mt-4 rounded-xl bg-muted px-3 py-2.5 text-sm text-muted-fg">{t("person.resting")}</p>
          ) : (
            <>
              <form onSubmit={ask} className="mt-4 flex gap-2">
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("person.ask_placeholder", { name: data.display_name })}
                       aria-label={t("person.ask_placeholder", { name: data.display_name })}
                       className="h-10 min-w-0 flex-1 rounded-xl border border-border bg-bg px-4 text-[15px] outline-none focus:border-accent" />
                <button type="submit" style={{ background: accent }}
                        className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl px-4 text-sm font-semibold text-white">
                  {t("person.ask")}<ArrowRight className="h-4 w-4" />
                </button>
              </form>
              {s.suggested_questions?.length ? (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {s.suggested_questions.slice(0, 3).map((sq) => (
                    <a key={sq} href={chat(sq)} className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-fg hover:border-accent hover:text-accent">{sq}</a>
                  ))}
                </div>
              ) : null}
              <p className="mt-3 text-xs text-muted-fg">{t("person.ask_hint", { name: data.display_name })}</p>
            </>
          )}
        </section>

        {data.posts?.length ? (
          <section className="mt-8">
            <h2 className="text-sm font-semibold text-muted-fg">{t("person.posts")}</h2>
            {/* One grid, photos and words together: a picture somebody published is a post
                like any other, not a shelf of its own (plan/42 §9). */}
            <ul className="mt-2 grid grid-cols-3 gap-1.5">
              {data.posts.map((post) => (
                <li key={post.slug}>
                  <a href={`/@${data.handle}/${encodeURIComponent(post.slug)}`}
                     className="group relative flex aspect-square items-center justify-center overflow-hidden rounded-lg border border-border bg-muted">
                    {post.images?.length ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={post.images[0]} alt="" loading="lazy"
                           className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]" />
                    ) : (
                      <span className="line-clamp-4 p-2.5 text-left text-[11px] leading-snug text-muted-fg">
                        {post.kind === "note" ? post.excerpt : post.title}
                      </span>
                    )}
                    {(post.images?.length ?? 0) > 1 ? (
                      <span className="absolute right-1.5 top-1.5 rounded-md bg-fg/60 px-1.5 text-[10px] text-bg">{post.images!.length}</span>
                    ) : null}
                    {post.visibility === "friends" ? (
                      <span className="absolute left-1.5 top-1.5 rounded-md bg-fg/60 px-1.5 text-[10px] text-bg">{t("blog.vis_friends")}</span>
                    ) : null}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <p className="mt-8 text-center text-xs text-muted-fg">
          <Link href="/" className="hover:text-fg">{t("person.made_with")}</Link>
        </p>
      </main>
    </div>
  );
}
