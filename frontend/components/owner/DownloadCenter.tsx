"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Laptop, Monitor, MonitorDown, SquareTerminal } from "@/components/icons";
import { Downloads, type AppAsset, type AppReleaseOut } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { fmtBytes, fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Page } from "./Shell";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { Segmented } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty";
import { buttonLook } from "@/components/ui/button";
import { LogoMark } from "@/components/brand/Logo";

type Os = "windows" | "macos" | "linux";
const OS_ICON: Record<Os, ReactNode> = { windows: <Monitor />, macos: <Laptop />, linux: <SquareTerminal /> };

/** 지금 이 화면을 연 컴퓨터. 휴대폰이면 null. */
function detectOs(): Os | null {
  if (typeof navigator === "undefined") return null;
  const ua = navigator.userAgent;
  const p = ((navigator as unknown as { userAgentData?: { platform?: string } }).userAgentData?.platform || navigator.platform || "").toString();
  if (/Android|iPhone|iPad|iPod/i.test(ua)) return null;
  if (/Win/i.test(p) || /Windows/i.test(ua)) return "windows";
  if (/Mac/i.test(p) || /Macintosh/i.test(ua)) return navigator.maxTouchPoints > 1 ? null : "macos";   // 아이패드는 Mac 이라고 말한다
  if (/Linux/i.test(p) || /Linux/i.test(ua)) return "linux";
  return null;
}

/** Apple 칩인지 Intel 인지 — 알려 주는 브라우저(크롬 계열)에서만 안다. 모르면 null. */
async function detectArch(): Promise<"arm64" | "x64" | null> {
  try {
    const d = (navigator as unknown as { userAgentData?: { getHighEntropyValues?: (h: string[]) => Promise<{ architecture?: string }> } }).userAgentData;
    const v = await d?.getHighEntropyValues?.(["architecture"]);
    if (v?.architecture === "arm") return "arm64";
    if (v?.architecture === "x86") return "x64";
  } catch { /* 모르면 둘 다 보여 준다 */ }
  return null;
}

/** 다운로드 센터 (plan/64). GitHub 로 나간 앱 릴리스를 여기서 받는다 — 서버가 설치본을 옮겨 두고 내어 준다. */
export function DownloadCenterPage() {
  const t = useT();
  const q = useQuery({ queryKey: ["downloads"], queryFn: Downloads.list, staleTime: 5 * 60_000 });
  const [os, setOs] = useState<Os | null>(null);
  const [arch, setArch] = useState<"arm64" | "x64" | null>(null);
  const [guide, setGuide] = useState<Os>("windows");
  useEffect(() => {
    const o = detectOs();
    setOs(o);
    if (o) setGuide(o);
    void detectArch().then(setArch);
  }, []);

  const latest = q.data?.latest ?? null;
  const older = (q.data?.releases ?? []).filter((r) => r.tag !== latest?.tag);

  return (
    <Page>
      <PageHeader title={t("dl.title")} description={t("dl.desc")} />
      {q.isLoading ? (
        <div className="space-y-4"><Skeleton className="h-52" /><Skeleton className="h-64" /></div>
      ) : !latest ? (
        <EmptyState icon={<MonitorDown />} title={t("dl.empty_title")} description={t("dl.empty_desc")} />
      ) : (
        <div className="space-y-5">
          <Hero release={latest} os={os} arch={arch} />
          {/* 한 줄에 하나씩: 블랙모아 앱 → 설치하는 법 → 이전 버전. */}
          <Card className="p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-semibold">{t("dl.install")}</h2>
              <Segmented value={guide} onChange={(v) => setGuide(v as Os)} ariaLabel={t("dl.install")}
                options={[{ value: "windows", label: "Windows" }, { value: "macos", label: "Mac" }, { value: "linux", label: "Linux" }]} />
            </div>
            <ol className="space-y-2.5">
              {(t(`dl.steps_${guide}`) || "").split("|").map((s, i) => (
                <li key={i} className="flex gap-3 text-sm leading-relaxed">
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/12 text-[11px] font-semibold text-accent">{i + 1}</span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          </Card>
          {older.length ? <Older releases={older} /> : null}
        </div>
      )}
    </Page>
  );
}

/** 운영체제마다 설치 프로그램 하나(서버가 골라 준다). 맥은 한 파일(universal)이고, 그 전의 판만 칩마다 둘이다. */
function label(a: AppAsset, t: (k: string) => string): string {
  if (a.platform === "windows") return t("dl.for_windows");
  if (a.platform === "macos") return a.arch === "universal" ? t("dl.for_mac") : a.arch === "arm64" ? t("dl.for_mac_arm") : t("dl.for_mac_intel");
  return t("dl.for_linux");
}

function Hero({ release, os, arch }: { release: AppReleaseOut; os: Os | null; arch: "arm64" | "x64" | null }) {
  const t = useT();
  const ready = release.assets.filter((a) => a.ready);
  // 이 컴퓨터의 설치 프로그램 하나를 크게. (universal 이전 판의 Mac 만 칩을 알면 그것을 앞에, 모르면 둘 다.)
  const mine = useMemo(() => {
    if (!os) return [];
    const same = ready.filter((a) => a.platform === os);
    if (os === "macos" && arch) {
      const hit = same.find((a) => a.arch === arch);
      return hit ? [hit, ...same.filter((a) => a !== hit)] : same;
    }
    return same;
  }, [ready, os, arch]);
  const rest = ready.filter((a) => !mine.includes(a));
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-5 p-5 md:flex-row md:items-center md:p-6">
        <div className="flex min-w-0 flex-1 items-center gap-4">
          <LogoMark size={64} className="shrink-0" />
          <div className="min-w-0">
            <h2 className="text-xl font-semibold">{t("dl.app")}</h2>
            <p className="mt-0.5 text-sm text-muted-fg">
              {t("dl.version", { v: release.version })}{release.published_at ? ` · ${fmtDate(release.published_at, { dateStyle: "long" })}` : ""}
            </p>
            <p className="mt-2 max-w-xl text-sm leading-relaxed">{t("dl.tagline")}</p>
          </div>
        </div>
        <div className="flex shrink-0 flex-col gap-2 md:min-w-[260px]">
          {mine.length ? mine.map((a, i) => (
            <a key={a.id} href={a.url ?? undefined} download
               className={buttonLook(i === 0 ? "accent" : "outline", "lg", "justify-between gap-3")}>
              <span className="inline-flex items-center gap-2 [&>svg]:h-4 [&>svg]:w-4"><Download />{label(a, t)}</span>
              <span className={cn("text-xs tabular-nums", i === 0 ? "opacity-80" : "text-muted-fg")}>{fmtBytes(a.size)}</span>
            </a>
          )) : (
            <p className="rounded-xl border border-border bg-muted/50 px-4 py-3 text-sm text-muted-fg">{t(os ? "dl.none_for_os" : "dl.mobile")}</p>
          )}
        </div>
      </div>
      {rest.length ? (
        <div className="border-t border-border bg-muted/30 px-5 py-3 md:px-6">
          <div className="mb-2 text-xs font-medium text-muted-fg">{mine.length ? t("dl.other") : t("dl.all")}</div>
          <div className="flex flex-wrap gap-2">
            {rest.map((a) => (
              <a key={a.id} href={a.url ?? undefined} download
                 className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm hover:bg-muted [&>svg]:h-4 [&>svg]:w-4">
                {OS_ICON[a.platform]}{label(a, t)}<span className="text-xs tabular-nums text-muted-fg">{fmtBytes(a.size)}</span>
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}

/** 이전 버전 — 설명 없이, 판마다 받을 파일만. */
function Older({ releases }: { releases: AppReleaseOut[] }) {
  const t = useT();
  return (
    <Card className="p-5">
      <h2 className="mb-3 text-base font-semibold">{t("dl.older")}</h2>
      <ul className="divide-y divide-border">
        {releases.map((r) => (
          <li key={r.tag} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:gap-6">
            <div className="flex w-44 shrink-0 items-baseline gap-2">
              <span className="text-sm font-medium">{t("dl.version", { v: r.version })}</span>
              <span className="text-xs text-muted-fg">{r.published_at ? fmtDate(r.published_at) : ""}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {r.assets.filter((a) => a.ready).map((a) => (
                <a key={a.id} href={a.url ?? undefined} download
                   className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-muted [&>svg]:h-3.5 [&>svg]:w-3.5">
                  {OS_ICON[a.platform]}{label(a, t)}
                </a>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
