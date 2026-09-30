# MFSG frontend

Next.js 15 (App Router) · React 19 · Tailwind v4 · zustand · react-query.

## Develop
```bash
export PATH=/home/workspace/.tools/node22/bin:$PATH
npm install
INTERNAL_API_URL=http://127.0.0.1:8123 npm run dev     # http://localhost:3000, /api proxied to the backend
```

## Check / build
```bash
npm run lint && npx tsc --noEmit && npm run build
```

## Run the production build
```bash
INTERNAL_API_URL=http://backend:8000 node .next/standalone/server.js
```
In production nginx must route `/api/*`, `/health`, `/static/*` to the backend (the dev rewrite is disabled unless `PROXY_API_IN_PROD=1`).

## Environment variables (runtime, never baked in)
| var | purpose |
|---|---|
| `INTERNAL_API_URL` | backend base URL used by server components and the dev proxy (default `http://127.0.0.1:8123`) |
| `PORT` / `HOSTNAME` | standalone server bind (Dockerfile sets 3000 / 0.0.0.0) |
| `PUBLIC_URL` | canonical origin (e.g. `https://mfsg.example.com`) used as `metadataBase` for absolute OG/manifest URLs on the visitor page |
| `PROXY_API_IN_PROD` | set to `1` to keep the `/api` rewrite in production (no nginx) |

## Layout
- `app/(marketing)` landing / login / signup / legal
- `app/[code]` public visitor chat (mobile-first PWA)
- `app/(owner)/app/**` owner console
- `app/(admin)/admin/**` admin console
- `components/ui` primitives · `components/chat` streaming chat · `lib/api.ts` fetch + refresh · `lib/sse.ts` turn stream
