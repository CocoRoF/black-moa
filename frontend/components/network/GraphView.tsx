"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, forceX, forceY, type SimulationLinkDatum, type SimulationNodeDatum } from "d3-force";
import type { NetEdge, NetNode } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface SimNode extends SimulationNodeDatum { id: string; n: NetNode }
interface SimLink extends SimulationLinkDatum<SimNode> { e: NetEdge }
const PALETTE = ["#176fd6", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#8b5cf6", "#14b8a6", "#f97316", "#84cc16"];
const KIND_SHAPE: Record<string, string> = { person: "circle", company: "rect", org: "rect", project: "diamond" };

/** Size says how close, not how loud. Me largest, then the people I am actually connected
 *  to, then the cards I wrote — which is the order in which they matter to the question
 *  "who is around me". */
function radiusOf(n: NetNode): number {
  if (n.is_self) return 30;
  // 연결한 곳(Google 연락처 …): 사람이 아니라 사람들이 들어온 문이다 (plan/79).
  if (n.kind === "source") return 22;
  // A secretary hangs off its owner and is a door rather than a person: smaller, so the
  // people stay the shape of the picture (plan/43 §6).
  if (n.person === "agent") return 14;
  if (n.person === "member") return 20 + Math.min(6, (n.importance ?? 3));
  if (n.person === "guest") return 17 + Math.min(5, (n.importance ?? 3));
  return 8 + (n.importance ?? 3) * 2;
}

/** Two characters is what fits inside a 20px disc in Korean and in English alike. */
function initials(name: string): string {
  const t = (name || "").trim();
  if (!t) return "?";
  if (/[가-힣]/.test(t)) return t.slice(0, 2);
  const parts = t.split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : t.slice(0, 2)).toUpperCase();
}

/** Where the line stops and the arrowhead sits: short of the circle it points at, so the
 *  head is visible instead of buried under the node. */
function arrow(from: { x: number; y: number }, to: { x: number; y: number }, r: number) {
  const dx = to.x - from.x, dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const tipX = to.x - ux * (r + 3), tipY = to.y - uy * (r + 3);
  const backX = tipX - ux * 9, backY = tipY - uy * 9;
  const nx = -uy * 4.5, ny = ux * 4.5;
  return { x: backX, y: backY,
           points: `${tipX},${tipY} ${backX + nx},${backY + ny} ${backX - nx},${backY - ny}` };
}

const PERSON_LABEL: Record<string, string> = { self: "나", member: "Memora 사용자", guest: "게스트", offline: "메모", agent: "비서", source: "연결한 곳" };
function personLabel(n: NetNode, t: (k: string) => string): string {
  // 연동으로 가져온 사람은 어디서 왔는지를 말한다.
  if (n.person === "offline" && n.source && t(`net.source_${n.source}`) !== `net.source_${n.source}`) return t(`net.source_${n.source}`);
  return PERSON_LABEL[n.person] ?? n.kind;
}
const HUB_MARK: Record<string, { mark: string; color: string }> = { google_contacts: { mark: "G", color: "#1a73e8" }, kakao_friends: { mark: "K", color: "#3c1e1e" } };
/** 선이 말하는 관계 — 늘 보이는 것(비서·연동)과 고른 사람의 선에서만 보이는 것. */
const ALWAYS_LABEL = new Set(["secretary", "source"]);

export default function GraphView({ nodes, edges, selected, onSelect, className }: { nodes: NetNode[]; edges: NetEdge[]; selected?: string | null; onSelect: (id: string | null) => void; className?: string }) {
  const t = useT();
  const relLabel = (rel: string) => { const k = `net.rel_${rel}`; const v = t(k); return v === k ? "" : v; };
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [pos, setPos] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ id: number; x: number; y: number; vx: number; vy: number } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const fitRef = useRef<{ x: number; y: number; k: number }>({ x: 0, y: 0, k: 1 });

  useEffect(() => {
    const el = wrap.current; if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el); setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cx = size.w / 2, cy = size.h / 2;
    const sn: SimNode[] = nodes.map((n) => ({ id: n.id, n }));
    const ids = new Set(sn.map((s) => s.id));
    const sl: SimLink[] = edges.filter((e) => ids.has(e.src_id) && ids.has(e.dst_id)).map((e) => ({ source: e.src_id, target: e.dst_id, e }));
    // An ego network, not a cloud: I am pinned in the middle and everyone else settles onto
    // a ring at their distance from me. A plain force layout put the busiest node in the
    // centre, which answers a question nobody was asking.
    const ring = Math.max(90, Math.min(cx, cy) * 0.62);
    // 연결한 곳(Google 연락처 …)과 거기서 온 사람들 (plan/79): 연결한 곳은 나에게서 한 방향으로 한 칸, 그 사람들은
    // 그 너머 한 자리에 해바라기처럼 모인다 — 힘에만 맡기면 수백 명이 원판이 되어 나까지 덮었다.
    const hubOf = new Map<string, string>();
    for (const e of edges) if (e.rel === "imported") hubOf.set(e.dst_id, e.src_id);
    const hubs = sn.filter((x) => x.n.kind === "source");
    const hubAt = new Map<string, { hx: number; hy: number; ccx: number; ccy: number; cr: number }>();
    hubs.forEach((h, i) => {
      const a = [0, Math.PI, -Math.PI / 2, Math.PI / 2][i % 4];
      const count = hubs.length ? sn.filter((x) => hubOf.get(x.id) === h.id).length : 0;
      const cr = Math.max(50, Math.sqrt(count) * 21);
      const hd = ring * 1.05, cd = hd + 46 + cr;
      hubAt.set(h.id, { hx: cx + Math.cos(a) * hd, hy: cy + Math.sin(a) * hd, ccx: cx + Math.cos(a) * cd, ccy: cy + Math.sin(a) * cd, cr });
    });
    const clusterIdx = new Map<string, number>();
    for (const s of sn) {
      if (s.n.is_self) { s.fx = cx; s.fy = cy; s.x = cx; s.y = cy; continue; }
      const hub = hubAt.get(s.id);
      if (hub) { s.fx = hub.hx; s.fy = hub.hy; s.x = hub.hx; s.y = hub.hy; continue; }
      const home = hubOf.has(s.id) ? hubAt.get(hubOf.get(s.id)!) : undefined;
      if (home) {
        // 해바라기(황금각) 자리에서 시작 — 고르게 퍼지고 늘 같은 자리.
        const k = clusterIdx.get(hubOf.get(s.id)!) ?? 0; clusterIdx.set(hubOf.get(s.id)!, k + 1);
        const rr = 19 * Math.sqrt(k + 0.5), th = k * 2.39996;
        s.x = home.ccx + Math.cos(th) * rr; s.y = home.ccy + Math.sin(th) * rr;
        continue;
      }
      // A deterministic starting angle keeps the layout stable between renders — the same
      // graph should not reshuffle itself every time the page reloads.
      const seed = [...s.id].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 3600, 7) / 3600;
      const r0 = ring * (s.n.hops ? Math.min(3, s.n.hops) : 2.2);
      s.x = cx + Math.cos(seed * Math.PI * 2) * r0;
      s.y = cy + Math.sin(seed * Math.PI * 2) * r0;
    }
    const inCluster = (d: SimNode) => hubOf.has(d.id) && hubAt.has(hubOf.get(d.id)!);
    const targetX = (d: SimNode) => (inCluster(d) ? hubAt.get(hubOf.get(d.id)!)!.ccx : cx);
    const targetY = (d: SimNode) => (inCluster(d) ? hubAt.get(hubOf.get(d.id)!)!.ccy : cy);
    const sim = forceSimulation(sn)
      .force("link", forceLink<SimNode, SimLink>(sl).id((d) => d.id)
        .distance((l) => (l.e.rel === "source" ? 130 : 70 + (1 - (l.e.strength ?? 0.5)) * 60))
        // 출처 선은 그리기만 하고 끌지 않는다 — 자리는 무리의 중심이 정한다.
        .strength((l) => (l.e.rel === "imported" ? 0 : 0.35)))
      .force("charge", forceManyBody<SimNode>().strength((d) => (inCluster(d) ? -30 : -260)))
      .force("ring", forceRadial<SimNode>((d) => (d.n.is_self ? 0 : ring * (d.n.hops ? Math.min(3, d.n.hops) : 2.2)), cx, cy)
        .strength((d) => (d.n.is_self || inCluster(d) ? 0 : d.n.hops ? 0.55 : 0.3)))
      .force("x", forceX<SimNode>(targetX).strength((d) => (inCluster(d) ? 0.18 : 0.02)))
      .force("y", forceY<SimNode>(targetY).strength((d) => (inCluster(d) ? 0.18 : 0.02)))
      .force("collide", forceCollide<SimNode>().radius((d) => (inCluster(d) ? radiusOf(d.n) + 6 : radiusOf(d.n) + 14)))
      .stop();
    const ticks = Math.min(400, Math.max(120, Math.ceil(Math.log(0.001) / Math.log(1 - sim.alphaDecay()))));
    for (let i = 0; i < ticks; i++) sim.tick();
    setPos(new Map(sn.map((s) => [s.id, { x: s.x ?? 0, y: s.y ?? 0 }])));
    // 처음 보는 그림은 전부 화면 안에 — 사람이 많으면 줄여서 담는다(키우지는 않는다).
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const s of sn) {
      const r = radiusOf(s.n) + 8;
      x0 = Math.min(x0, (s.x ?? 0) - r - 40); x1 = Math.max(x1, (s.x ?? 0) + r + 40);
      y0 = Math.min(y0, (s.y ?? 0) - r); y1 = Math.max(y1, (s.y ?? 0) + r + 18);
    }
    const fit = sn.length && isFinite(x0) ? Math.min(1, (size.w - 24) / Math.max(1, x1 - x0), (size.h - 24) / Math.max(1, y1 - y0)) : 1;
    const home = { k: fit, x: size.w / 2 - fit * (x0 + x1) / 2, y: size.h / 2 - fit * (y0 + y1) / 2 };
    fitRef.current = home;
    setView(home);
  }, [nodes, edges, size.w, size.h]);

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const neighborIds = useMemo(() => { const s = new Set<string>(); const f = selected ?? hover; if (!f) return s; for (const e of edges) { if (e.src_id === f) s.add(e.dst_id); if (e.dst_id === f) s.add(e.src_id); } return s; }, [edges, selected, hover]);
  const focus = selected ?? hover;
  // 출처에서 온 무리의 사람들 — 이름은 가까이 볼 때만(겹쳐 읽을 수 없으니).
  const clustered = useMemo(() => new Set(edges.filter((e) => e.rel === "imported").map((e) => e.dst_id)), [edges]);

  // Zooming has to be a native listener: React registers wheel passively, so the
  // preventDefault in a JSX onWheel never took — it only logged "Unable to preventDefault
  // inside passive event listener" on every notch while the page scrolled underneath the
  // zoom.
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      setView((v) => {
        const k = Math.min(4, Math.max(0.2, v.k * (e.deltaY < 0 ? 1.1 : 0.9)));
        return { k, x: mx - ((mx - v.x) / v.k) * k, y: my - ((my - v.y) / v.k) * k };
      });
    };
    el.addEventListener("wheel", onWheelNative, { passive: false });
    return () => el.removeEventListener("wheel", onWheelNative);
  }, []);

  //: The node under the finger when it came down. Pointer capture on the svg retargets
  //: pointerup to the svg, so the browser's own `click` lands on the svg and never on the
  //: node; a press that did not become a drag is decided here, on the way up.
  const pressed = useRef<string | null>(null);
  const onDown = (e: React.PointerEvent) => {
    pressed.current = (e.target as Element).closest?.("[data-node]")?.getAttribute("data-node") ?? null;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    // Capture on the svg, not on whatever node happened to be under the finger — a node
    // re-renders on hover and takes the capture with it. And it is an optimisation, never
    // a reason to take the page down: setPointerCapture throws NotFoundError outright when
    // the pointer is already gone (a cancelled gesture, a drag that left the window), and
    // an exception thrown from a React event handler is the "Application error" screen.
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* the pointer went away first */ }
  };

  const onMove = (e: React.PointerEvent) => {
    // Read the drag once, here. Passing `drag.current` into the updater instead let React
    // call it after a pointercancel had already nulled the ref — "Cannot read properties
    // of null (reading 'vx')", and the whole page with it. Dragging the graph off the edge
    // is exactly the gesture that produces that cancel.
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
  };

  const onUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    // A press that stayed put is a choice; one that travelled was a drag of the canvas.
    if (e.type === "pointerup" && d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) onSelect(pressed.current);
    pressed.current = null;
  };

  return (
    <div ref={wrap} className={cn("relative h-full w-full overflow-hidden rounded-2xl border border-border bg-card touch-none select-none", className)}>
      <svg width={size.w} height={size.h} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} role="img" aria-label="network graph" className="block cursor-grab active:cursor-grabbing">
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {/* A one-way connection has to look one-way (plan/43 §2). A line that means the
              same thing whichever way it points cannot say that only one of them chose. */}
          {edges.map((e) => {
            const a = pos.get(e.src_id), b = pos.get(e.dst_id); if (!a || !b) return null;
            const hl = focus && (e.src_id === focus || e.dst_id === focus);
            const stroke = hl ? "var(--accent)" : "var(--border)";
            const both = e.direction === "both" || e.direction === "undirected";
            // Incoming is the same line the other way round: the arrow points at me.
            const [from, to] = e.direction === "incoming" ? [b, a] : [a, b];
            const head = both ? undefined : arrow(from, to, radiusOf(nodes.find((n) => n.id === (e.direction === "incoming" ? e.src_id : e.dst_id)) ?? nodes[0]));
            // 관계는 선이 말한다(지식 그래프처럼) — 비서·연동은 늘, 나머지는 고른 사람의 선에서만.
            // "가져옴" 은 출처 노드가 이미 말한다 — 수백 개의 같은 이름표를 달지 않는다.
            const label = e.rel !== "imported" && (ALWAYS_LABEL.has(e.rel) || hl) ? relLabel(e.rel) : "";
            const at = e.rel === "source" ? 0.4 : 0.5;
            const mx = from.x + (to.x - from.x) * at, my = from.y + (to.y - from.y) * at;
            const fs = 9.5 / Math.max(0.6, Math.min(1, view.k));
            return (
              <g key={e.id} strokeOpacity={focus && !hl ? 0.25 : 0.9}>
                <line x1={from.x} y1={from.y} x2={head ? head.x : to.x} y2={head ? head.y : to.y}
                      stroke={stroke} strokeWidth={hl ? 2 : e.rel === "imported" ? 0.8 : 1 + (e.strength ?? 0.5)}
                      strokeDasharray={both ? undefined : "5 3"} />
                {head ? <polygon points={head.points} fill={stroke} stroke="none" fillOpacity={focus && !hl ? 0.25 : 0.9} /> : null}
                {label ? (
                  <g transform={`translate(${mx},${my})`} opacity={focus && !hl ? 0.3 : 1} style={{ pointerEvents: "none" }}>
                    <rect x={-(label.length * fs * 0.55 + 6)} y={-fs * 0.85} width={(label.length * fs * 0.55 + 6) * 2} height={fs * 1.7}
                          rx={fs * 0.85} fill="var(--card)" stroke={hl ? "var(--accent)" : "var(--border)"} strokeWidth={0.8} />
                    <text textAnchor="middle" dominantBaseline="central" fontSize={fs} fontWeight={500}
                          fill={hl ? "var(--accent)" : "var(--muted-fg)"}>{label}</text>
                  </g>
                ) : null}
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = pos.get(n.id); if (!p) return null;
            const r = radiusOf(n);
            const color = n.is_self ? "var(--accent)" : PALETTE[(n.community ?? 0) % PALETTE.length];
            const dim = focus && focus !== n.id && !neighborIds.has(n.id);
            const shape = n.kind === "person" || n.person === "agent" ? "circle" : (KIND_SHAPE[n.kind] ?? "circle");
            const sel = selected === n.id;
            // A photo is the whole point of a network of real people: it is the difference
            // between "this person is here" and "I wrote their name down". A guest has no
            // account and so no photo — the dashed ring says so without a legend.
            const face = n.avatar_url && shape === "circle";
            const ringColor = sel ? "var(--fg)" : n.is_self ? "var(--accent)" : n.person === "offline" ? "var(--border)" : color;
            const ringWidth = sel ? 3.5 : n.is_self ? 3 : n.person === "member" ? 2.5 : 2;
            if (n.kind === "source") {
              const hm = HUB_MARK[n.source] ?? { mark: n.name.slice(0, 1), color: "var(--accent)" };
              return (
                <g key={n.id} data-node={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1}
                   onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)} className="cursor-pointer">
                  <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={9} fill="var(--card)" stroke={sel ? "var(--fg)" : hm.color} strokeWidth={sel ? 3 : 2} />
                  <text textAnchor="middle" dominantBaseline="central" fontSize={r * 0.9} fontWeight={700} fill={hm.color} style={{ pointerEvents: "none" }}>{hm.mark}</text>
                  <text y={r + 13} textAnchor="middle" fontSize={11.5 / Math.max(0.6, Math.min(1, view.k))} fontWeight={600} fill="var(--fg)" style={{ pointerEvents: "none" }}>
                    {t(`net.source_${n.source}`) !== `net.source_${n.source}` ? t(`net.source_${n.source}`) : n.name}
                    <tspan fill="var(--muted-fg)" fontWeight={400}> · {n.attrs?.count ?? 0}</tspan>
                  </text>
                </g>
              );
            }
            return (
              <g key={n.id} data-node={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1}
                 onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)} className="cursor-pointer">
                {n.is_self ? <circle r={r + 7} fill="none" stroke="var(--accent)" strokeOpacity={0.25} strokeWidth={1.5} /> : null}
                {shape === "rect" ? <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={4} fill={color} stroke={ringColor} strokeWidth={ringWidth} />
                  : shape === "diamond" ? <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={2} transform="rotate(45)" fill={color} stroke={ringColor} strokeWidth={ringWidth} />
                  : <>
                      <circle r={r} fill={face ? "var(--card)" : color} fillOpacity={n.person === "offline" ? 0.9 : 1} />
                      {face ? (
                        <>
                          <clipPath id={`face-${n.id}`}><circle r={r - 1} /></clipPath>
                          <image href={n.avatar_url!} x={-r + 1} y={-r + 1} width={(r - 1) * 2} height={(r - 1) * 2}
                                 clipPath={`url(#face-${n.id})`} preserveAspectRatio="xMidYMid slice" />
                        </>
                      ) : (
                        <text textAnchor="middle" dominantBaseline="central" fontSize={r * 0.72} fontWeight={600}
                              fill="#fff" fillOpacity={n.person === "offline" ? 0.85 : 1} style={{ pointerEvents: "none" }}>
                          {initials(n.name)}
                        </text>
                      )}
                      <circle r={r} fill="none" stroke={ringColor} strokeWidth={ringWidth}
                              strokeDasharray={n.person === "guest" ? "4 3" : undefined} />
                    </>}
                {clustered.has(n.id) && view.k < 1.4 && focus !== n.id ? null : <text y={r + 13} textAnchor="middle" fontSize={(n.is_self ? 12.5 : 11) / Math.max(0.6, Math.min(1, view.k))}
                      fontWeight={n.is_self ? 700 : n.person === "offline" ? 400 : 500}
                      fill={n.person === "offline" ? "var(--muted-fg)" : "var(--fg)"} style={{ pointerEvents: "none" }}>
                  {n.name.length > 14 ? n.name.slice(0, 13) + "…" : n.name}
                </text>}
              </g>
            );
          })}
        </g>
      </svg>
      {hover && byId.get(hover) ? <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-border bg-card/95 px-3 py-2 text-xs shadow"><div className="font-medium">{byId.get(hover)!.name}</div><div className="text-muted-fg">{personLabel(byId.get(hover)!, t)}{byId.get(hover)!.attrs?.company ? ` · ${byId.get(hover)!.attrs.company}` : ""}</div></div> : null}
      <div className="absolute bottom-3 right-3 flex gap-1">
        <button type="button" aria-label="zoom in" className="h-8 w-8 rounded-lg border border-border bg-card text-sm" onClick={() => setView((v) => ({ ...v, k: Math.min(4, v.k * 1.2) }))}>+</button>
        <button type="button" aria-label="zoom out" className="h-8 w-8 rounded-lg border border-border bg-card text-sm" onClick={() => setView((v) => ({ ...v, k: Math.max(0.2, v.k / 1.2) }))}>−</button>
        <button type="button" aria-label="reset" className="h-8 rounded-lg border border-border bg-card px-2 text-xs" onClick={() => setView(fitRef.current)}>⟲</button>
      </div>
    </div>
  );
}
