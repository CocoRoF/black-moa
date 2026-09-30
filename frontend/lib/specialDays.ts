"use client";
import { useMemo } from "react";
import { useQueries, type QueryClient } from "@tanstack/react-query";
import type { DayInfo, SpecialName } from "@/lib/api";

/** 한 해치 달력 (plan/60): 한국의 공휴일·명절·절기·기념일과 날마다의 음력.
 *
 *  달력 한 해는 한번 정해지면 거의 바뀌지 않는다. 그래서 스케줄 화면은 사용자 일정만 불러오고, 이것은
 *  해마다 한 번 받아 이 기기에 둔다.
 *  - 다시 열어도 기기에 둔 것을 곧바로 쓴다(네트워크를 기다리지 않는다).
 *  - 한 시간(지난해는 일주일)이 지나면 조용히 확인한다. 서버는 버전이 같으면 본문 없이 304 로 답하고
 *    브라우저가 받아 둔 것을 쓴다. 정부가 임시공휴일을 새로 정했을 때만 새 한 해치가 온다.
 */

export const COUNTRY = "KR";
const KEY = (y: number) => `memora.cal.v1.${COUNTRY}.${y}`;
/** 음력 표가 닿는 해 — 서버와 같다. */
const YEAR_MIN = 1990, YEAR_MAX = 2050;

interface YearPayload {
  country: string; year: number; version: string;
  days: Record<string, { off: boolean; names: SpecialName[] }>;
  /** 1월 1일부터 날마다 "8.15"(윤달이면 "L6.1"). */
  lunar: (string | null)[];
}
interface Stored { at: number; data: YearPayload }

function thisYear(): number { return new Date().getFullYear(); }
const freshFor = (y: number) => (y < thisYear() ? 7 * 24 * 3600_000 : 3600_000);

function load(y: number): Stored | undefined {
  try {
    const raw = localStorage.getItem(KEY(y));
    if (!raw) return undefined;
    const s = JSON.parse(raw) as Stored;
    return s?.data?.year === y && Array.isArray(s.data.lunar) ? s : undefined;
  } catch { return undefined; }
}

function save(y: number, data: YearPayload): void {
  try { localStorage.setItem(KEY(y), JSON.stringify({ at: Date.now(), data } satisfies Stored)); } catch { /* 저장소를 못 쓰면 매번 받는다 */ }
}

async function fetchYear(y: number): Promise<YearPayload> {
  // 로그인과 상관없는 공공의 달력 — 브라우저 캐시(ETag)가 그대로 일하도록 평범한 GET 으로.
  const r = await fetch(`/api/calendar/${COUNTRY}/${y}`, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`calendar ${y}: ${r.status}`);
  const data = (await r.json()) as YearPayload;
  save(y, data);
  return data;
}

/** 이 해들의 날마다: 쉬는 날인가, 이름들, 음력. 달력 한 장이 두 해에 걸치면 두 해를 합친다. */
export function useSpecialDays(years: number[]): Record<string, DayInfo> {
  const ys = [...new Set(years)].filter((y) => y >= YEAR_MIN && y <= YEAR_MAX).sort();
  const results = useQueries({
    queries: ys.map((y) => {
      const stored = typeof window === "undefined" ? undefined : load(y);
      return {
        queryKey: ["calendar-days", COUNTRY, y],
        queryFn: () => fetchYear(y),
        initialData: stored?.data,
        initialDataUpdatedAt: stored?.at,
        staleTime: freshFor(y),
        gcTime: Infinity,
        refetchOnWindowFocus: true,
        retry: 1,
      };
    }),
  });
  const versions = results.map((r) => r.data?.version ?? "").join("|");
  return useMemo(() => {
    const out: Record<string, DayInfo> = {};
    for (const r of results) {
      const d = r.data;
      if (!d) continue;
      const start = Date.UTC(d.year, 0, 1);
      d.lunar.forEach((code, i) => {
        const key = new Date(start + i * 86400_000).toISOString().slice(0, 10);
        const special = d.days[key];
        out[key] = { off: special?.off ?? false, names: special?.names ?? [], lunar: parseLunar(code) };
      });
      // 음력 표 밖의 해라도 이름 있는 날은 싣는다.
      for (const [key, v] of Object.entries(d.days)) if (!out[key]) out[key] = { off: v.off, names: v.names, lunar: null };
    }
    return out;
    // 버전이 같으면 같은 결과다 — 한 해치를 다시 풀지 않는다.
  }, [versions]); // eslint-disable-line react-hooks/exhaustive-deps
}

function parseLunar(code: string | null): DayInfo["lunar"] {
  if (!code) return null;
  const leap = code.startsWith("L");
  const [m, d] = code.replace(/^L/, "").split(".").map(Number);
  return m && d ? { month: m, day: d, leap } : null;
}

/** 관리자가 공식 출처를 새로 받았을 때: 이 기기에 둔 한 해치를 버리고 다시 받는다. */
export function forgetSpecialDays(qc: QueryClient): void {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith("memora.cal.")) localStorage.removeItem(k);
    }
  } catch { /* 무시 */ }
  qc.invalidateQueries({ queryKey: ["calendar-days"] });
}
