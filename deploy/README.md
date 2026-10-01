# black-moa production deployment

This directory is the production Compose contract. Keep `deploy/.env` and
`deploy/backup.env` on the server only (`chmod 600`); neither file should be
committed.

## 1. Runtime environment

```bash
cd deploy
cp .env.example .env
chmod 600 .env
```

Required values:

- `BLACKMOA_PUBLIC_URL`: the HTTPS Cloudflare/public origin.
- `BLACKMOA_SECRET_KEY`: unique random secret, at least 32 bytes (`openssl rand -hex 32`). Rotating it invalidates user/visitor/state JWTs.
- `POSTGRES_PASSWORD`: unique database password.
- `BLACKMOA_BOOTSTRAP_TOKEN`: random one-time token used only to claim the first production admin. Remove or rotate it after bootstrap.
- `BLACKMOA_ENCRYPTION_KEY`: independent Fernet key used for provider/OAuth/channel secrets. New production installs should always set this explicitly.

Generate a Fernet key after the backend image exists:

```bash
sudo docker compose -p blackmoa build backend
sudo docker compose -p blackmoa run --rm --no-deps backend python -m blackmoa.core.keytool generate
```

Copy the output to `BLACKMOA_ENCRYPTION_KEY` without quotes.

### Existing installs that previously left `BLACKMOA_ENCRYPTION_KEY` empty

Older releases derived the Fernet key from `BLACKMOA_SECRET_KEY`. **Do not rotate
`BLACKMOA_SECRET_KEY` first.** On the existing secret, derive and pin the exact old
key:

```bash
sudo docker compose -p blackmoa run --rm --no-deps backend python -m blackmoa.core.keytool legacy
```

Put that output in `BLACKMOA_ENCRYPTION_KEY`, redeploy and verify integrations. Once
the database encryption key is explicit, `BLACKMOA_SECRET_KEY` can be rotated
independently (sessions/tokens will be invalidated, encrypted DB values will not).

For a Fernet rotation, set the new key as `BLACKMOA_ENCRYPTION_KEY` and put the
previous key in `BLACKMOA_ENCRYPTION_KEY_PREVIOUS`. New writes use only the primary
key; reads fall back to the previous keys. Keep previous keys until all legacy
ciphertext has been rewritten/re-saved.

## 2. Security-related optional settings

```dotenv
# Only user-controlled outbound URL ports that the safe HTTP transport may use.
BLACKMOA_OUTBOUND_ALLOWED_PORTS=80,443

# Untrusted PDF/Office/HTML parser child-process limits.
BLACKMOA_PARSER_TIMEOUT_SECONDS=20
BLACKMOA_PARSER_MEMORY_MB=512
BLACKMOA_PARSER_MAX_OUTPUT_BYTES=8388608
```

The backend/worker containers start with only the capabilities needed to repair
legacy named-volume ownership, then `gosu` to uid/gid `10001`. Application
processes are non-root, the root filesystem is read-only, `/tmp`/cache are
bounded tmpfs mounts, and the old Docker-socket `autoheal` container is not used.
Docker `restart: unless-stopped` still restarts a process that exits.

## 3. Deploy

```bash
sudo docker compose -p blackmoa config -q
sudo docker compose -p blackmoa up -d --build
sudo docker compose -p blackmoa ps
curl -fsS "http://127.0.0.1:${NGINX_PORT:-58710}/health"
```

The first start after this hardening release can recursively change ownership of
`blackmoa-data` and the Claude named volume once. `/data/.owner-uid-10001` prevents
repeating the expensive data-volume migration.

Only nginx is bound to the host, and only on `127.0.0.1`. Point Cloudflare Tunnel
at that local port. `/api/internal/mcp/` is denied by nginx; Claude's MCP bridge
uses the backend loopback path instead.

## 4. Encrypted backups

Install `age` (and `restic` if off-site replication is enabled), then create a
backup keypair and configuration:

```bash
sudo install -d -m 700 /root/.config/blackmoa /srv/blackmoa-backups
sudo age-keygen -o /root/.config/blackmoa/backup-age.key
cp backup.env.example backup.env
chmod 600 backup.env
```

Copy the public `age1...` recipient printed by `age-keygen` into
`BLACKMOA_BACKUP_AGE_RECIPIENT`. `BLACKMOA_BACKUP_AGE_IDENTITY` must be a filesystem path
to the private identity, never the private key text itself.

Create and verify a backup:

```bash
sudo ./scripts/backup.sh
sudo ./scripts/backup-verify.sh
```

The archive contains a PostgreSQL custom dump, `/data` except cache, and Claude
credential/state volume data. The outer archive is encrypted with age before it
is retained or sent to optional restic storage. `backup-verify.sh` decrypts into
a temporary directory, verifies SHA-256 checksums, runs `pg_restore --list`, and
checks both tar archives without modifying the live database.

Run a real restore drill periodically on an isolated host/database. A backup is
not considered operationally valid until restore has been exercised.

## 5. Key/secret handling rules

- Never commit `.env`, `backup.env`, age private identities, restic passwords or provider credentials.
- Keep `BLACKMOA_SECRET_KEY` and `BLACKMOA_ENCRYPTION_KEY` in separate secret-manager entries.
- Rotate the bootstrap token immediately after first-admin creation.
- When rotating Fernet keys, primary encrypts and previous keys decrypt only.
- Verify `/health`, Google/LLM integrations and one notification channel after any key change.
