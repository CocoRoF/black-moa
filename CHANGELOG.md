# Changelog

All notable changes to Memora are documented here (Keep a Changelog; entries name the symptom, the cause and the invariant).

## [Unreleased] — many Claude accounts instead of one

### Added
- **A Claude Code account pool with load balancing** (`plan/30-claude-account-pool.md`). The install had exactly one Claude login, so that one subscription's rate limit was the whole service's rate limit and its expiry was the whole service's outage. An administrator can now authenticate several accounts from the Claude Code card on `/admin/providers`; the pipeline leases one per session and an account that is limited, expired or failing leaves the rotation by itself.
  - **Isolation is the load-bearing part.** Every account gets its own CLI home — `HOME` *and* `CLAUDE_CONFIG_DIR` are pointed at `<data_dir>/claude-accounts/<id>/`. Passing only one lets the CLI derive the config directory from `HOME`, which is how one account ends up reading another's tokens.
  - Four strategies: `least_busy` (default; load measured against each account's *own* concurrency ceiling, not absolute session count), `round_robin`, `weighted` (nginx-style smooth weighted round-robin, so 3:1 comes out `A A B A` rather than `A A A B` — bursting on one subscription is precisely what trips its limit), and `least_recently_used`.
  - Health is decided by the same `providers/errors.py::classify` verdict the user-facing message came from: `rate_limited` → 15-minute rest, `provider_quota` → an hour, `provider_auth` → marked expired rather than cooled, because waiting does not fix a logged-out account. Repeated unexplained failures open the circuit with a doubling backoff, and one success clears everything.
  - **A turn that failed for reasons that are not the account's doing changes nothing.** `context_limit`, `cancelled` and `credits_exhausted` are neutral: counting a too-long conversation as an account failure is how a healthy pool talks itself into an outage.
  - A session holds its account for the runtime's life (the CLI client is built with that account's credentials and its prompt cache belongs to it) and reports health per turn; when the leased account leaves the rotation the runtime is dropped so the next turn rebuilds on a healthy one instead of walking into the same wall.
  - The device-login relay is the same code as the single-account flow, pointed at a per-account home, and now runs one relay *per target* — a second account can be signed in while the first is still waiting for its code.
  - Credentials are Fernet-encrypted in the row (a database dump must not be a set of live sessions) and written `0600` inside a `0700` directory; deleting an account deletes its credential file, because a live token nobody audits is exactly the kind of leftover that outlives the decision to remove it.
  - `claude_creds.backup` now also harvests each account's CLI-refreshed token back into the database and re-materializes a missing file after a volume swap, guarded in both directions so an older copy never overwrites a newer one.
  - `ops.watch` watches the pool when the pool is serving: no eligible account is an immediate alert, members that dropped out are named, and each login is warned about three days before it expires. `at_capacity` is never alerted on — that is the pool doing its job.
  - `POST /providers/claude-code/probe` now probes what a real turn would use. Verifying the legacy credential file while the pool serves traffic is how a green check ends up next to a broken install.

### Changed
- An empty pool changes nothing: `acquire()` returns `None` and every caller falls back to the single-credential path, so an existing install keeps working until an administrator adds accounts. The migration only creates the table.

### Fixed
- **A background turn's health verdict no longer dies with the worker's rollback.** Distillation and summaries run inside `worker/__main__.run_job`, which rolls its session back when a handler raises — so the cooldown a rate-limited account had just earned was written into that session and discarded with it, and the account kept taking background work forever. The verdict is now persisted in its own session, on the exact path the pool exists to protect.
- **Live notifications actually arrive.** The Postgres LISTEN/NOTIFY listener asked SQLAlchemy's pool proxy for a `get_raw_connection()` that does not exist on it, so it failed on every attempt, reconnected every three seconds forever, and leaked the checkout it had just taken on each pass (visible as a steady drip of "garbage collector is trying to clean up non-checked-in connection"). Nothing published to the bus was ever delivered: `/api/notifications/stream` sent keepalives and the bell only moved on the next poll. It now takes the asyncpg connection from `raw.driver_connection`, and returns the checkout to the pool on every exit. Covered by a test that publishes through Postgres and reads it back on a subscriber — the smallest thing that would have caught it.
- **One account whose credential cannot be written to disk no longer collapses the pool.** `acquire()` used to give up on the first materialize failure, dropping the whole install back to the legacy single credential because one member of three had an unwritable directory. The broken account is skipped, the strategy is asked again, and the failure is counted through the normal health machine so a disk that stays broken rests the account instead of being picked on every build.

## [Unreleased] — 인맥 becomes a graph of real people

### Added
- **Identity on network nodes** (`plan/31-people-graph.md`). A node used to be a card the owner wrote, pointing at nobody. It can now *be* someone: a Memora account (`user_id`), a visitor who talked to this owner's secretary (`visitor_id`), or the owner themselves (`is_self`, exactly one per owner). Promotion only ever goes offline → guest → member, and it **merges into the existing card** rather than putting a second node beside it — years of notes must not fork because the person finally signed up.
- **Friend links between accounts** (`network_links`). A connection is something both people agreed to: accepting materialises a node and an edge on *both* sides. Sending a request back to someone who already asked is treated as accepting it, because that is what the person meant. Disconnecting removes the link and the edges and **keeps the nodes** — ending a relationship is not the same as never having met.
- **A directory you cannot browse.** Search takes an exact email, an exact mail handle, or a name prefix of at least two characters, and returns display name, avatar and handle only. The email comes back solely when the caller already typed it.
- **Guests are first class.** Everyone who actually talked to an owner's secretaries is listed with what is known: name, address, which secretary, how many turns, when. They can be added to the network as a guest node, and when their address turns out to belong to an account, the owner is offered a connection instead.
- **The graph is an ego network.** `/api/network/graph` always carries the owner's own node (created on first look) and every node's hop distance from it. The screen pins the owner in the middle, rings the others by distance, and draws real profile photos for the people who have accounts — the difference between "this person is here" and "I wrote their name down", visible without a legend.

### Changed
- **A guest identity is claimed by proof of address, not by typing one.** Fusion happens when an address is verified, when a verified account logs in, and when a visitor signs into a share link — never at signup. A guest identity carries somebody's real conversations, and putting an address in a form is not evidence of holding it. The delay is the point.
- Every remaining `window.confirm()` — eight of them, across knowledge, models, memory, notifications, chat, embedding and the network — now uses the product's own confirm dialog.

## [0.6.0] — 2026-09-08 — chat as its own surface, and an audit of what the secretary can actually use

### Added
- **Chat is a top-level surface** (`/app/chat`), not a tab inside one secretary. It opens the most recent conversation of the secretary you last talked to, switches secretaries from the header, and switches conversations from the list; the agent tabs lost their 대화 tab and the picker cards gained [대화] [설정].
- Expiry dates are picked with `@cocorof/react-calendar` (extracted from xgen-frontend and published to npm) instead of the browser's native datetime input.
- `tools/context_matrix.py` — an empirical harness that builds a throwaway tenant, drives real owner and visitor turns, and asserts that each piece of stored information does (or, when private, does not) reach the answer. 25 cases; the run behind this release passes 25/25. Findings: `plan/28-context-audit-2026-09-08.md`.
- The network list says which contacts a visitor's secretary may mention: a public badge per card, and a hint when every contact is private.
- Credits show today's usage against the plan's daily cap, and `daily_cap_reached` reads as a daily cap rather than an empty balance.

### Fixed
- **Every knowledge document failed to index without an embedding key**, so the knowledge base was empty on this install. Indexing now drops the vector leg and keeps the keyword legs; the API reports `semantic_search: false` and the page says so.
- **The FAQ fallback never matched.** Without embeddings it searched `question ILIKE '%the whole question%'`, which fires only if the visitor repeats the stored sentence verbatim. It now scores shared content words across question and answer, stripping Korean particles so 결제사를/결제사가 share a stem, and stays below the semantic threshold because keyword evidence is weaker.
- **The owner asking "did anyone leave a message?" was answered from memory.** `inbox_list` was a hidden tool while the new base prompt advertised it as directly callable and no longer explained ToolSearch; the tool is now advertised, and hidden ones are marked `(search first)`.
- **Tab strips could collapse and swallow their own clicks.** A scroll container's automatic minimum size is 0, so on a page whose content overflows the strip flattened to its 1px border while its 44px buttons overflowed under the list below — the network page could not return from 제안 to 그래프.
- **The prompt preview dialog showed a prompt the service no longer sends.** It assembled its own text from a legacy module, so it advertised a three-level disclosure model months after the product settled on public/private and omitted the mission, resources and secretary layers. `/prompt` and `/prompt-preview` now share one composer with the runtime, the legacy strings are deleted, and a test pins the endpoints to each other. `/prompt` also raised `NameError` on an invalid audience.
- The agent header is one row at the same height on every tab; the visitor simulator no longer shrinks it.
- A design pass over every surface (Playwright, 1440/560/390 × dark/light): dialog footers, empty states, scroll containers and overflow.
- Frontend and nginx had no healthcheck, so a wedged process still read as "Up".

## [0.5.0] — 2026-09-08 — two prompt layers, two disclosure levels

### Added
- **The system prompt is explicitly two layers.** Layer 1 (`pipeline/base_prompt.py`, always injected, always English) is composed by the service: the audience, who the secretary works for, the owner's identity and profile at the level this audience may see, the tools in this session with per-tool guidance, the resources the owner actually configured, the working rules for that audience, and how to answer. A resource that is not configured is omitted rather than described as empty. Layer 2 is the owner's — persona plus their own instructions, in their own language, under a header stating it may set voice and priorities but never loosens layer 1.
- It settles the deixis that made the secretary ask who "이 분" was: with a visitor, "이분 / 그분 / this person / your boss" means the owner.
- `GET /api/agents/{id}/prompt?audience=` returns what a turn actually composes (same function, not a copy); the settings page shows the base prompt read-only with an owner/visitor toggle and offers a localized starting draft for the secretary prompt.

### Changed
- **Disclosure is two levels: public or private.** Three levels asked the owner an unanswerable question and handed the middle one to the model — `profile_disclose` released an on-request value once the model judged the visitor's reason good enough. A public field is written into the visitor session's prompt; a private one is not in that conversation at all, and no tool can fetch it. `profile_disclose` is removed. Legacy `on_request` rows folded to private (applied in production, then the one-time migration was dropped from the tree).

### Fixed
- The prompt's opening identity line stated the owner's role and city regardless of visibility, disclosing on-request values before the gate could apply; it now passes the same check, and the name the secretary uses publicly falls back to the account label when the profile name is not public.
- The availability window reached the model as raw JSON; it now reads as "Mon/Tue/Wed/Thu/Fri 10:00-18:00".
- Block order is load-bearing: the executor routes everything after the first volatile block into session context, so a volatile block above the secretary layer silently dropped the owner's instructions out of the system prompt.
- The visitor prompt advertised `profile_update`, a tool visitors do not have.

## [0.4.4] — 2026-09-08 — the secretary knows who it works for

### Fixed
- **Every simulated visitor turn returned "internal error".** `start_turn` rate-limits the visitor path by `req.visitor.id`, but the owner's simulator runs that path with no visitor row — `AttributeError` on `None`. Simulated turns are now limited against the owner.
- **The greeting and the one-line role were frozen at creation.** Both were generated from the names in play at the time and stored, so renaming the agent (13 → 제니) or the owner left visitors reading the old copy forever. They are now rendered from the current names whenever the column is empty; migration 0007 clears the copies Memora generated (matched exactly, so an owner's own words are untouched), the settings form shows the live default as its placeholder, and onboarding leaves the role empty by default.
- One resolver decides what the owner is called — profile `preferred_name` → `full_name` → account label — so the public page, the prompt and the generated copy cannot disagree. The honorific 님 is only appended when the name does not already carry one ("하렴 사장님님" → "하렴 사장님").
- The unsaved-changes bar was `fixed inset-x-0`: it ran under the sidebar and centred its buttons on the window instead of the content column. Now sticky inside the column, in both the profile and agent settings forms.

### Verified on production
- A simulated visitor turn completes (5.6 s, 382 output tokens) and answers from the owner's profile: "하렴 사장님은 플래티어의 AI R&D 랩에서 제품개발파트 파트리더로…". The test conversation was deleted afterwards.
- Public link payload, agent card and settings all read 하렴 사장님 / 제니.
- Save bar starts at x=272 with a 240 px sidebar — no longer overlapping it.

## [0.4.3] — 2026-09-08 — the profile form keeps the cursor

### Fixed
- **Typing one character in `/app/profile` dropped focus.** `Row` and `V` were declared inside `ProfilePage`, so every keystroke produced new component *types* and React destroyed and rebuilt the whole row — the input it contained included. Both moved to module scope, taking their dependencies through a small context so call sites are unchanged. `NumCell` in the model catalog had the same shape, where a background refetch mid-edit would have discarded the value being typed.
- `react/no-unstable-nested-components` is now an error (the rest of the frontend already passes), so the defect cannot return unnoticed.

### Verified on production
- A Korean name and a full English sentence typed character by character both land intact, with focus retained, in the text input and the textarea.

## [0.4.2] — 2026-09-08 — provider card: one control per decision

### Changed
- **Console login is an auth mode, not a checkbox.** The card offered "sign in with a Console account" next to an auth mode that said OAuth — two controls for one decision, free to disagree. Modes are now `oauth | console | api_key | setup_token`; the device login starts whichever flow the *saved* mode dictates, and `POST …/login/start` refuses key-based modes outright (`login_not_applicable`). At runtime `console` is `oauth`: both flows write the same credentials file.
- Mode row rebuilt: the save button shares the select's row (a hint inside the `Field` was pushing the select up and leaving the button off its baseline) and the conditional setup-token field moved to its own row; the button turns accent with an "unsaved changes" note while dirty, and the login button is disabled ("save the auth mode first") until the change is saved.
- Login session panel reads as a result: green/red framing, spinner while running, URL and code box only while the CLI waits, and on success the console log collapses behind a show/hide toggle with a close button.

### Verified on production
- Real device login completed by the operator; credentials survived a full rebuild (`claude_credentials: present`).
- Probe through the executor: `ok`, "pong", 2.2 s, CLI 2.1.236.
- A real owner turn completed — 3628 in / 1039 out tokens, 13.11 credits on the ledger — so login → chat → metering → billing works end to end.
- Login button state across all four modes (enabled only for the saved browser-login mode with no unsaved change).

## [0.4.1] — 2026-09-08 — the Claude Code device login actually completes

### Fixed
- **The box for the pasted auth code never appeared.** The admin console rendered it only after an `input` event, which the backend emits solely as the echo of a code already sent — so the login could not be completed: URL, console output, nowhere to type. The box is now open for the whole run, takes focus when the CLI prompts, and survives a page reload (`GET /api/admin/providers/claude-code/login` returns a snapshot).
- Relay reworked on plain pipes instead of a pty (measured in the running image: both accept the code, but a pty wraps the URL in an OSC-8 hyperlink and echoes it twice). The flow is chosen explicitly — `auth login --claudeai` / `--console`, with a console-account toggle — because a bare `auth login` can stop on a menu a relay cannot answer.
- Output is read in chunks with a 300 ms idle flush, not by lines: the `Paste code here if prompted >` prompt carries no newline, and flushing on the first promptish chunk split it mid-word (observed live as `Paste code here if prompte` + `d >`).
- `done` now carries `ok` and the exit code, and `Login failed: …` surfaces as an error — a failed login used to end with a success toast. On success the credential is mirrored to the DB immediately and the auth mode pinned to `oauth`.
- Provider status now includes `claude auth status --json` (cached 60 s).

### Verified on production
- Device login driven end to end through the API: URL captured, `awaiting_input` set, a dummy code reached the CLI (`Login failed: … 400`, exit 1) and cancel stops the process cleanly.
- Password change keeps the changing device signed in and drops the other one (throwaway account, then deleted).
- All 25 owner + admin routes load with no console error, no page error and no failing API call.

## [0.4.0] — 2026-09-07 — default administrator, shared home, brand header

### Added
- **Seeded administrator.** Every install now boots with `admin@geny.com` / `admin123` (override via `MEMORA_DEFAULT_ADMIN_EMAIL` / `MEMORA_DEFAULT_ADMIN_PASSWORD`, skip with `MEMORA_DEFAULT_ADMIN_ENABLED=0`). Seeding is idempotent and never touches an existing account, so changing the password sticks. While the shipped password is still in use the console shows a red header pill and an overview banner, backed by `GET /api/admin/overview.default_admin_password_in_use`. A public deployment that keeps the default is one login away from takeover — change it from my page after the first login.
- My page: profile photo upload and email verification, alongside the existing password change, session list, data export and account deletion.
- `tests/test_admin_security.py`: a route sweep asserting every `/api/admin` endpoint answers 401 to anonymous callers and 403 to a signed-in non-admin (including a demoted admin still holding a valid access token), plus the seed's idempotence and warning flag.
- `noindex, nofollow` / `X-Frame-Options: DENY` / `Referrer-Policy: same-origin` on `/app` and `/admin`.

### Fixed
- **Changing your password no longer signs you out.** `POST /api/users/me/password` still revokes every session (that is the point), but now issues a fresh one for the caller and returns it — the response carries a new access token and sets a rotated refresh cookie, which the client adopts. Other devices are still logged out.
- Auth-page backdrop: the brand glow was `absolute` inside the `max-w-md` card column, so it was clipped to that column and rendered as a hard-edged rectangle behind the card. It is now a viewport-anchored layer with asymmetric, heavily blurred blooms and its own dark-mode opacities, and the card floats on it with a translucent, blurred surface.

### Changed
- Admins are ordinary users with one extra nav item: login and signup no longer redirect them to `/admin`, so everyone lands on the same `/app` home.
- Header logo is the "Geny" logo itself. The mascot+wordmark lockup rendered the wordmark as an illegible smudge at a 30px header height.

## [0.3.0] — 2026-09-07 — security hardening (PR #1, reviewed and adjusted)

### Added
- Server-enforced disclosure: `on_request` profile values never enter the visitor prompt; the visitor-only `profile_disclose` tool releases one value after a concrete reason and whitelists that literal for the current turn only.
- Fail-closed public event projection (allowlist), tenant re-checks on notification channels/rules, Turnstile fail-closed, `MEMORA_BOOTSTRAP_TOKEN` for the first HTTPS admin.
- Atomic credit reservations (`reserve → provider budget → settle/release`) with row-locked balance/day caps, DB invariants for one running turn per conversation and `(conversation_id, client_turn_id)`, partial-unique job dedupe.
- `safe_http`: DNS-pinned outbound transport (every answer must be globally routable, TLS SNI keeps the original hostname, redirects re-pinned) used by web fetch and webhook delivery.
- Untrusted document parsing in a scrubbed child process with wall-clock/CPU/address-space/FD limits and no network; archive/zip-bomb bounds.
- Visitor-relationship retention purge (conversations, PII, visitor-private facts, inbox, payload copies, memory notes), age-encrypted backups with verification, non-root read-only containers.

### Changed after review
- **Visitor streaming kept.** The PR closed the pre-redaction leak window by never streaming to visitors; the public chat would have gone silent for the whole turn. `guard.StreamRedactor` closes the same window while streaming — text is released only once no later token can turn it into a match (invariant in plan/19), and `turn.complete.answer` remains the authoritative final text.
- `$HOME` is a volume and `CLAUDE_CONFIG_DIR` is set: the read-only rootfs would otherwise leave the CLI unable to write `~/.claude.json`.
- The worker writes a liveness file that the container healthcheck reads — autoheal and the pgrep healthcheck were removed, so a wedged-but-running worker was invisible to docker.
- Provider budget floors at $0.02; `settle_turn` charges `min(actual, hold)`, so the DB hold stays the billing boundary while a low-balance final turn is not truncated.
- `apply(..., allow_reserved=True)` for already-incurred usage: STT/TTS/embedding charges and monthly-grant expiry were being refused (402 after the provider work) whenever a turn held credits.
- Stale credit reservations are reaped (2h TTL, 10-minute schedule) — a killed process used to hold a user's balance down forever.
- Startup verifies at-rest ciphertext actually decrypts, so rotating the signing key without pinning the Fernet key fails loudly with the exact recovery command instead of 500ing on first use.
- CI smoke secrets are generated per run (the literal placeholders tripped secret scanning).

## [0.2.0] — 2026-09-07

### Added
- Geny brand applied across the product: logo lockup in every header, mascot avatars/empty states/404, brand-blue palette, redesigned landing, PWA icons + favicon + default OG image generated from the Geny character.
- Mobile owner chat uses a single 52 px header row (back · agent · conversation · menu).
- Email verification flow (6-digit code), `POST /api/admin/telegram/set-webhook`, unsubscribe footer tokens, stale-job reaper, `/metrics` restricted to private network/admin.

### Fixed (from the full functional audit — 54 backend tests, Playwright flows for every page)
- Login lockout never engaged: failed attempts were rolled back with the raised 401. Invariant: security counters commit before the error propagates.
- SSE terminal events were never persisted once text had streamed: the merged delta row reused the terminal event's seq and collided on the (turn_id, seq) key. Invariant: every persisted row gets a distinct seq; forced flush drains the tail.
- Knowledge documents stuck in "processing" forever: the failure status was written inside the job transaction that the worker then rolled back. Invariant: failure state is committed separately from the failing work.
- Expired Google connections looked healthy forever (same rollback pattern) — status now committed.
- Distillation cost ~20 credits per short turn: Claude Code emitted ~2k thinking tokens per background call; background completions now run with `--effort low`.
- Monthly grant rollover cap, ledger kinds for metered usage, cancelled turns not charged, image base64 persisted in message rows, MIME mismatch uploads, wildcard leak in network search, journal slow-consumer leak, IndexCache open race, blocked visitors could still read messages, `/metrics` public, admin "today" computed in UTC, notification test hanging, plus dozens of validation/type fixes (see git log).
- Frontend: visitor header menu unclickable (stacking context), onboarding welcome chips lost on redirect, 401 noise on marketing pages, fake timestamp on greeting, dark-mode button contrast, Korean line breaks (`keep-all`).

## [0.1.0] — 2026-09-07

### Added
- Master plan (`plan/00`–`27`) — architecture, data model, harness pipeline, memory, knowledge, network graph, integrations, public mobile chat, consoles, credits, notifications, providers, API, security, deployment, testing, observability, roadmap, decision log, runbook, reference map.
- Backend (FastAPI, Python 3.12): accounts (first signup = admin, argon2id, 15-min access JWT + rotating httpOnly refresh with reuse detection, Google login), agents & personas (6 presets + sliders compiled deterministically), share links (`/{code}`, reserved handles), single harness pipeline on `geny-executor==2.65.6` with audience-scoped tool provider (32 tools; visitors never see owner tools), Claude Code CLI via loopback MCP bridge (native tools fully blocked), SSE turn journal with seq replay/cancel, credit ledger (append-only, idempotent per turn), host-side memory (markdown notes + Synapse per namespace owner/shared/visitors), knowledge RAG (pgvector + tsvector + trigram, FAQ), network graph (nodes/edges/paths/proposals/merge/CSV), Google integration (Gmail/Calendar/People), inbox (messages, meeting requests, unanswered questions → FAQ), notifications (email/telegram/slack/discord/webhook + rules + digest), admin console API (settings, providers with Claude Code device-login relay/import/probe, model catalog, plans, users, usage, invites, jobs, audit, health), worker (PG SKIP LOCKED queue, scheduled jobs, distillation).
- Deploy: `docker compose` stack (pgvector, backend, worker, frontend, nginx, autoheal), Cloudflare tunnel script, backup script.

### Deployed
- 2026-09-07 `https://memora.hrletsgo.me` (Cloudflare tunnel hr106 → 127.0.0.1:58700, compose project `memora`). Frontend: Next.js 15, 44 routes, 102 kB shared JS. Admin bootstrapped; Claude Code device login pending (human step).

### Fixed (during live verification with Claude Code 2.1.236)
- Prod probe failed with "claude binary not found": the executor treats an explicit `binary_path` literally, so `claude` (bare) must be resolved through PATH to an absolute path.
- Admin device-login relay showed no URL: the CLI wraps the OAuth link in an OSC-8 hyperlink that the ANSI stripper swallowed; URLs are now extracted from raw output first.
- Copying another CLI's `~/.claude/.credentials.json` is not a valid bootstrap: refresh tokens rotate, so the first refresh by the source invalidates the copy ("OAuth session expired and could not be refreshed"). Servers need their own login lineage.
- MCP `tools/list` returned an empty array because `ToolRegistry.list_exposed()` yields Tool objects, not names → the CLI saw no tools and "pretended" calls in prose. Invariant: bridge advertises exactly `registry.list_exposed()`.
- Terminal SSE events were emitted before the finalize transaction committed, so a client reading the balance right after `turn.complete` saw the old value. Invariant: terminal events are emitted only after commit.
- Guard chain defaults to empty and `chain_order` can only reorder → guards populated at runtime (`add_to_chain`).
- Claude Code hot spare disabled (`GENY_CLI_PREWARM=0`) after a second turn died with SIGKILL when a prewarmed process was reused.
