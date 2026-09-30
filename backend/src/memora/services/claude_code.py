"""Claude Code provider ops: status, device-login relay (pipes), credentials import/backup, probe."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from memora.config import get_settings
from memora.core.errors import Conflict, ValidationFailed
from memora.core.logging import get_logger
from memora.core.pools import run_blocking
from memora.providers.llm.credentials import resolve_claude_binary
from memora.services import settings as S

log = get_logger("memora.claude")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\r")


def creds_path():
    return get_settings().claude_home / ".credentials.json"


_version_cache: tuple[float, str] | None = None
_auth_status_cache: tuple[float, dict[str, Any]] | None = None


async def cli_version(*, max_age_s: float = 300.0) -> str:
    """Spawning the CLI on every /overview or /providers call is wasteful — cache for 5 minutes."""
    global _version_cache
    if _version_cache and time.monotonic() - _version_cache[0] < max_age_s:
        return _version_cache[1]
    binary = resolve_claude_binary()
    try:
        proc = await asyncio.create_subprocess_exec(binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                    env={"HOME": str(get_settings().claude_home.parent), "PATH": os.environ.get("PATH", "")})
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        v = out.decode(errors="replace").strip()[:80] or "unknown"
    except FileNotFoundError:
        v = "not installed"
    except Exception as e:  # noqa: BLE001
        v = f"error: {e.__class__.__name__}"
    _version_cache = (time.monotonic(), v)
    return v


def _oauth_valid(creds: dict[str, Any] | None) -> bool:
    """True when the file holds a usable subscription credential: access+refresh tokens and not yet expired."""
    oauth = (creds or {}).get("claudeAiOauth") if isinstance(creds, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken") or not oauth.get("refreshToken"):
        return False
    exp = oauth.get("expiresAt")
    return not (exp and float(exp) / 1000 < time.time())


def _oauth_expires_at(creds: dict[str, Any] | None) -> float:
    try:
        return float(((creds or {}).get("claudeAiOauth") or {}).get("expiresAt") or 0)
    except (TypeError, ValueError):
        return 0.0


def read_credentials() -> dict[str, Any] | None:
    p = creds_path()
    try:
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None



def oauth_access_token() -> str:
    """The subscription's access token, when the CLI is logged in and it has not expired.

    The models API accepts it as a bearer token, which is how model discovery works on an
    install that has a Claude subscription and no API key at all.
    """
    creds = read_credentials()
    if not _oauth_valid(creds):
        return ""
    return str(((creds or {}).get("claudeAiOauth") or {}).get("accessToken") or "")


async def status(db: AsyncSession) -> dict[str, Any]:
    mode = await S.get(db, "providers.claude_code.auth_mode")
    creds = read_credentials()
    oauth = (creds or {}).get("claudeAiOauth") or {}
    exp = oauth.get("expiresAt")
    # Two different clocks, and the console used to show only the short one. `expiresAt` is
    # the access token, which the CLI silently refreshes roughly every 8 hours;
    # `refreshTokenExpiresAt` is how long this login actually lasts. Reporting the access
    # token as "expiry" made a healthy install look like it died overnight.
    sess = oauth.get("refreshTokenExpiresAt")
    session_dead = not oauth.get("refreshToken") or bool(sess and sess / 1000 < time.time())
    out = {"auth_mode": mode, "binary": resolve_claude_binary(),
           "version": await cli_version(), "credentials_present": creds is not None,
           "expires_at": datetime.fromtimestamp(exp / 1000, tz=UTC).isoformat() if exp else None,
           "access_expired": bool(exp and exp / 1000 < time.time()),
           "session_expires_at": datetime.fromtimestamp(sess / 1000, tz=UTC).isoformat() if sess else None,
           "expired": bool(creds) and session_dead, "subscription": oauth.get("subscriptionType"),
           "rate_limit_tier": oauth.get("rateLimitTier"), "scopes": oauth.get("scopes"),
           "has_setup_token": bool(await S.get(db, "providers.claude_code.setup_token")),
           "has_anthropic_key": bool(await S.get(db, "providers.anthropic.api_key")),
           "last_probe": await S.get(db, "providers.claude_code.status") or {},
           "cli_auth": await cli_auth_status()}
    job = current_login()
    if job is not None and not job.done:
        out["login_running"] = True
    # A pool, once it has a usable member, is what actually answers turns — the console
    # must not keep reporting the legacy single login as the whole story.
    with contextlib.suppress(Exception):
        from memora.services import claude_pool as P
        out["pool"] = {**(await P.overview(db))["counts"], "active": await P.enabled(db),
                       "strategy": await P.strategy(db)}
    return out


async def import_credentials(db: AsyncSession, raw_json: str, *, updated_by=None) -> dict[str, Any]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValidationFailed("invalid JSON", code="invalid_json") from e
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not oauth or not oauth.get("accessToken") or not oauth.get("refreshToken"):
        raise ValidationFailed("missing claudeAiOauth.accessToken/refreshToken", code="invalid_credentials_shape")
    p = creds_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    await S.put(db, "providers.claude_code.credentials_json", json.dumps(data), updated_by=updated_by)
    await S.put(db, "providers.claude_code.auth_mode", "oauth", updated_by=updated_by)
    return await status(db)


async def backup_credentials(db: AsyncSession) -> bool:
    """Copy the CLI's (auto-refreshed) credentials file into system_settings — only when it is valid and not older
    than what is already stored, so an expired/empty file never overwrites a good backup."""
    creds = read_credentials()
    if not _oauth_valid(creds):
        return False
    raw_prev = await S.get(db, "providers.claude_code.credentials_json", use_cache=False)
    try:
        prev = json.loads(raw_prev) if raw_prev else None
    except json.JSONDecodeError:
        prev = None
    if prev == creds:
        return False
    if prev is not None and _oauth_expires_at(prev) > _oauth_expires_at(creds):
        return False
    await S.put(db, "providers.claude_code.credentials_json", json.dumps(creds))
    return True


async def restore_credentials(db: AsyncSession) -> bool:
    """Materialize the stored backup into the CLI home — never over a live file that is valid and newer."""
    raw = await S.get(db, "providers.claude_code.credentials_json", use_cache=False)
    if not raw:
        return False
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not _oauth_valid(stored):
        return False
    current = read_credentials()
    if _oauth_valid(current) and _oauth_expires_at(current) >= _oauth_expires_at(stored):
        return False
    p = creds_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(stored))
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    return True


# ── device login relay ─────────────────────────────────────────────
#
# Plain pipes, not a pty. `claude auth login` prints the OAuth URL, then blocks on
# stdin for the code pasted back from the browser - measured on CLI 2.1.236 inside
# this image, both pipes and a pty accept the code, but a pty wraps the URL in an
# OSC-8 hyperlink and echoes it twice, so the console pane fills with escape noise.
# Pipes give clean lines. (Same shape Geny converged on.)


def _looks_like_prompt(text: str) -> bool:
    t = _ANSI.sub("", text).strip()
    return bool(t) and (t.endswith((">", "?", ":")) or "paste" in t.lower())


def _cred_fingerprint(creds: dict[str, Any] | None) -> str:
    """Identity of a stored credential — enough to tell a new login from the old one.

    The refresh token and its expiry: a fresh login always changes both, and neither is
    logged anywhere (only this digest is ever held in memory).
    """
    if not isinstance(creds, dict):
        return ""
    o = creds.get("claudeAiOauth") or creds
    raw = f"{o.get('refreshToken', '')}|{o.get('refreshTokenExpiresAt', '')}|{o.get('expiresAt', '')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw.strip("|") else ""


class LoginJob:
    """One `claude auth login` relay.

    ``home``/``config_dir`` are what make the pool possible: the same relay runs against a
    per-account CLI home, so logging a second account in cannot overwrite the first one's
    tokens. Omitted, they fall back to the single-account ``MEMORA_CLAUDE_HOME``.
    """

    def __init__(self, argv: list[str], *, console: bool = False, home: Path | None = None,
                 config_dir: Path | None = None, on_success: Callable[[], Awaitable[None]] | None = None) -> None:
        self.argv = argv
        self.console = console
        s = get_settings()
        self.config_dir = config_dir or s.claude_home
        self.home = home or (s.claude_home.parent if s.claude_home.name == ".claude" else s.claude_home)
        self.on_success = on_success
        self.lines: list[dict[str, Any]] = []
        self.seq = 0
        self.done = False
        self.ok = False
        self.exit_code: int | None = None
        self.url: str | None = None
        self.awaiting_input = False
        self._proc: asyncio.subprocess.Process | None = None
        self._tasks: list[asyncio.Task] = []
        self.started = time.time()
        self.subscribers: set[asyncio.Queue] = set()
        # What was already on disk when this job started. An account that is signed in
        # already has a valid credential here, and "valid credential exists" would other-
        # wise read as "this login succeeded" the instant the CLI was launched — before
        # anybody pasted anything.
        self._credential_at_start = _cred_fingerprint(self._written_credentials())

    def _new_credential_written(self) -> bool:
        """A credential that is valid *and* not the one we started with."""
        cur = self._written_credentials()
        return _oauth_valid(cur) and _cred_fingerprint(cur) != self._credential_at_start

    def _written_credentials(self) -> dict[str, Any] | None:
        """Read back the file THIS job was pointed at, not the global one."""
        p = self.config_dir / ".credentials.json"
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except Exception:  # noqa: BLE001
            return None

    def _emit(self, kind: str, text: str, **extra: Any) -> None:
        self.seq += 1
        ev = {"seq": self.seq, "kind": kind, "text": text, "at": time.time(), **extra}
        self.lines.append(ev)
        del self.lines[:-400]
        for q in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)

    async def start(self) -> None:
        s = get_settings()
        self.home.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        env = {
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.config_dir),
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "BROWSER": "echo",  # headless: print the URL instead of trying to open a browser
            "NO_COLOR": "1",
        }
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, cwd=str(s.data_dir), start_new_session=True)
        except Exception as e:
            self._emit("error", f"cannot start claude login: {e.__class__.__name__}: {str(e)[:200]}")
            self._emit("done", "finished", ok=False, exit_code=None)
            self.done = True
            raise
        self._tasks = [asyncio.create_task(self._drain(self._proc.stdout)),
                       asyncio.create_task(self._drain(self._proc.stderr)),
                       asyncio.create_task(self._wait())]

    async def _drain(self, stream: asyncio.StreamReader | None) -> None:
        """Chunked reads with an idle flush, not readline.

        The code prompt ("Paste code here if prompted > ") carries no newline, so a line
        reader would hold it until the process exits - exactly when it is useless. Flushing
        the moment a chunk merely *looks* promptish splits it mid-word instead, so an
        incomplete tail is held until the CLI goes quiet for a beat.
        """
        if stream is None:
            return
        buf = ""
        while True:
            try:
                chunk = await asyncio.wait_for(stream.read(512), timeout=0.3)
            except TimeoutError:
                if buf.strip():  # the CLI stopped writing: whatever is held is complete
                    self._handle(buf, prompt=_looks_like_prompt(buf))
                    buf = ""
                continue
            except Exception:  # noqa: BLE001
                return
            if not chunk:
                break
            buf += chunk.decode(errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                self._handle(line)
            if len(buf) > 4000:  # never grow without bound on a CLI that emits no newline
                self._handle(buf)
                buf = ""
        if buf.strip():
            self._handle(buf, prompt=_looks_like_prompt(buf))

    async def _wait(self) -> None:
        """Finish when the credential exists, not when the CLI feels like exiting.

        `claude auth login` prints "Login successful." and then keeps running — it is an
        interactive program and nobody is at the keyboard. Waiting for its exit meant a
        login that had already worked sat there for up to fifteen minutes, which is what
        an admin experiences as "logging in takes forever". The file on disk is the truth:
        once it holds a valid credential the job is done and the process can go.
        """
        proc = self._proc
        assert proc is not None
        deadline = time.time() + 900
        rc: int
        while True:
            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=2)
                break
            except TimeoutError:
                if self._new_credential_written():
                    self._emit("info", "login complete")
                    with contextlib.suppress(Exception):
                        proc.terminate()
                    try:
                        rc = await asyncio.wait_for(proc.wait(), timeout=10)
                    except TimeoutError:
                        await self.cancel(force=True)
                        rc = await proc.wait()
                    break
                if time.time() > deadline:
                    self._emit("error", "login timed out after 15 minutes")
                    await self.cancel(force=True)
                    rc = await proc.wait()
                    break
        for t in self._tasks:
            if t is not asyncio.current_task():
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(t), timeout=5)
        self.exit_code = rc
        self.awaiting_input = False
        # The credential is the verdict, not the exit code — this relay ends the CLI once
        # the login lands, so a non-zero exit is the normal, successful path. It has to be
        # a *new* credential: an account that was already signed in must not be able to
        # report a login nobody completed.
        self.ok = self._new_credential_written()
        if self.ok:
            # The CLI wrote a fresh credential; mirror it into the DB right away so a
            # container restart (or a volume swap) does not lose the login.
            with contextlib.suppress(Exception):
                if self.on_success is not None:
                    await self.on_success()
                else:
                    from memora.db.session import session_scope
                    async with session_scope() as db:
                        await backup_credentials(db)
                        # keep an explicit console choice; only a missing/key mode falls back to oauth
                        current = await S.get(db, "providers.claude_code.auth_mode")
                        if current not in ("oauth", "console"):
                            await S.put(db, "providers.claude_code.auth_mode", "console" if self.console else "oauth")
        self._emit("done", "ok" if self.ok else f"login did not complete (exit {rc})", ok=self.ok, exit_code=rc)
        self.done = True
        for q in list(self.subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)

    def _handle(self, raw: str, *, prompt: bool = False) -> None:
        # Extract URLs from the RAW text first: a pty run wraps the OAuth link in an OSC-8
        # hyperlink (ESC ] 8 ; ; URL BEL) that the ANSI stripper would swallow whole.
        for m in re.finditer(r"https?://[^\s\x07\x1b\"']+", raw):
            u = m.group(0)
            if ("oauth" in u or "claude" in u or "anthropic" in u) and u != self.url:
                self.url = u
                self._emit("url", u)
        text = _ANSI.sub("", raw).strip()
        if not text:
            return
        if prompt:
            self.awaiting_input = True
            self._emit("prompt", text[:500])
            return
        low = text.lower()
        if "login failed" in low or low.startswith("error"):
            self._emit("error", text[:500])
            return
        self._emit("log", text[:500])

    async def send_input(self, text: str) -> None:
        proc = self._proc
        if proc is None or self.done or proc.stdin is None or proc.stdin.is_closing():
            raise Conflict("login not running", code="login_not_running")
        payload = (text.strip() + "\n")[:4096].encode()
        try:
            proc.stdin.write(payload)
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise Conflict(f"stdin write failed: {e}", code="login_stdin_closed") from e
        self.awaiting_input = False
        # Never log the code itself: it is a one-time credential.
        head = text.strip()[:6]
        self._emit("input", f"(sent {len(text.strip())} chars: {head}…)")

    async def cancel(self, *, force: bool = False) -> None:
        if self._proc and self._proc.returncode is None:
            import signal
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL if force else signal.SIGTERM)

    def snapshot(self) -> dict[str, Any]:
        return {"running": not self.done, "done": self.done, "ok": self.ok, "exit_code": self.exit_code,
                "url": self.url, "awaiting_input": self.awaiting_input, "seq": self.seq,
                "started_at": self.started, "lines": self.lines[-200:]}


# One relay per target, not one relay per process: the single-account flow keeps the
# "default" slot, and every pool account gets its own, so an operator can log a second
# subscription in while the first one is still waiting for its code.
DEFAULT_LOGIN = "default"
_logins: dict[str, LoginJob] = {}
_login_lock = asyncio.Lock()


async def start_login(*, console: bool = False, email: str | None = None, key: str = DEFAULT_LOGIN,
                      home: Path | None = None, config_dir: Path | None = None,
                      on_success: Callable[[], Awaitable[None]] | None = None) -> LoginJob:
    """One relay at a time per target, serialized so two admins clicking at once cannot spawn two CLIs.

    The flow is chosen explicitly (``--claudeai`` / ``--console``): without a flag the CLI
    can stop on an interactive menu that a relay cannot answer sensibly.
    """
    async with _login_lock:
        existing = _logins.get(key)
        if existing is not None and not existing.done:
            if time.time() - existing.started > 960:  # wait timeout is 900s; treat a stuck job as dead
                await existing.cancel(force=True)
                existing.done = True
            else:
                raise Conflict("login already running", code="login_running")
        argv = [resolve_claude_binary(), "auth", "login", "--console" if console else "--claudeai"]
        if email:
            argv += ["--email", email.strip()[:200]]
        job = LoginJob(argv, console=console, home=home, config_dir=config_dir, on_success=on_success)
        _logins[key] = job
        try:
            await job.start()
        except Exception as e:  # noqa: BLE001
            from memora.core.errors import ServiceUnavailable
            raise ServiceUnavailable(f"cannot start claude login: {e.__class__.__name__}: {str(e)[:200]}", code="login_start_failed") from e
        return job


def current_login(key: str = DEFAULT_LOGIN) -> LoginJob | None:
    return _logins.get(key)


def forget_login(key: str) -> None:
    """Drop a finished relay's slot — called when its account is removed, so the registry
    does not accumulate one entry per account that ever existed."""
    _logins.pop(key, None)


async def cli_auth_status(*, max_age_s: float = 60.0) -> dict[str, Any]:
    """`claude auth status --json` - the CLI's own verdict (logged_in, account, subscription).

    Cached: the providers page and /overview both poll, and each call spawns a process.
    """
    global _auth_status_cache
    if _auth_status_cache and time.monotonic() - _auth_status_cache[0] < max_age_s:
        return _auth_status_cache[1]
    s = get_settings()
    out: dict[str, Any] = {}
    try:
        proc = await asyncio.create_subprocess_exec(
            resolve_claude_binary(), "auth", "status", "--json",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={"HOME": str(s.claude_home.parent), "CLAUDE_CONFIG_DIR": str(s.claude_home), "PATH": os.environ.get("PATH", ""), "NO_COLOR": "1"})
        raw, err = await asyncio.wait_for(proc.communicate(), timeout=15)
        body = raw.decode(errors="replace").strip()
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict) and parsed:
            out = {"logged_in": bool(parsed.get("loggedIn")), "auth_method": parsed.get("authMethod"),
                   "subscription": parsed.get("subscriptionType"), "email": parsed.get("email"),
                   "org": parsed.get("orgName")}
        else:
            out = {"logged_in": None, "error": (err.decode(errors="replace") or body)[:200] or None}
    except Exception as e:  # noqa: BLE001
        out = {"logged_in": None, "error": f"{e.__class__.__name__}: {str(e)[:120]}"}
    _auth_status_cache = (time.monotonic(), out)
    return out


def _reap(task: asyncio.Task) -> None:
    """Consume a fire-and-forget task's outcome, so a teardown that fails is not reported
    later as an exception nobody retrieved."""
    with contextlib.suppress(BaseException):
        task.exception()


# A person is watching a spinner while this runs. Long enough for a cold CLI start, short
# enough to be an answer rather than a wait.
PROBE_TIMEOUT_S = 60.0


async def run_probe(bundle: Any) -> dict[str, Any]:
    """One tiny turn through the executor CLI client with whatever credentials it was given.

    Shared by the single-account probe and the per-account pool probe, so "does this login
    actually work" is answered the same way for both.
    """
    from geny_executor import ClaudeCodeCLIClient, ModelConfig
    from geny_executor.core.pipeline import _creds_to_client_kwargs

    t0 = time.monotonic()
    result: dict[str, Any] = {"ok": False, "at": datetime.now(UTC).isoformat()}

    async def _run() -> dict[str, Any]:
        creds = bundle.by_provider["claude_code_cli"]
        kwargs = _creds_to_client_kwargs("claude_code_cli", creds)
        kwargs.pop("mcp_config", None)
        # Building the client spawns a process. Off the loop: a CLI that sits there waiting
        # for a terminal blocks everything else this worker is doing, and the timeout below
        # cannot fire while the loop is blocked.
        client = await run_blocking("llm", lambda: ClaudeCodeCLIClient(**kwargs, prewarm_spawn=False), label="probe:build")
        try:
            resp = await client.create_message(model_config=ModelConfig(model="haiku", max_tokens=32),
                                               messages=[{"role": "user", "content": "Reply with the single word: pong"}],
                                               system="You are a probe.")
            text = "".join(getattr(b, "text", "") or (b.get("text", "") if isinstance(b, dict) else "") for b in (resp.content or []))
            return {"ok": True, "text": text[:80],
                    "cli_version": (resp.raw or {}).get("cli_version") if isinstance(resp.raw, dict) else None}
        finally:
            # Teardown is not part of the answer. Closing talks to the same CLI that may
            # already be wedged, and awaiting it here put those seconds in front of the
            # person waiting — including on the timeout path, where the point is to stop
            # waiting. Fire it and forget it; the process is reaped either way.
            with contextlib.suppress(Exception):
                asyncio.ensure_future(client.aclose()).add_done_callback(_reap)

    try:
        # One cap over the whole thing — construction, call and teardown. It used to cover
        # only the call, so a CLI that hung while starting left an admin watching a spinner
        # for as long as it felt like.
        result.update(await asyncio.wait_for(_run(), timeout=PROBE_TIMEOUT_S))
        result["ms"] = int((time.monotonic() - t0) * 1000)
    except TimeoutError:
        result.update(ok=False, error=f"probe timed out after {PROBE_TIMEOUT_S:.0f}s",
                      ms=int((time.monotonic() - t0) * 1000))
    except Exception as e:  # noqa: BLE001
        result.update(ok=False, error=f"{e.__class__.__name__}: {str(e)[:300]}", ms=int((time.monotonic() - t0) * 1000))
    return result


async def probe(db: AsyncSession) -> dict[str, Any]:
    """Run one tiny turn through the executor CLI client to prove auth works."""
    from memora.providers.llm.credentials import build_bundle
    from memora.services import claude_pool as P
    result: dict[str, Any] = {"ok": False, "at": datetime.now(UTC).isoformat()}
    # Probe what a real turn would use. With a pool configured that is a leased account,
    # not the legacy credential file — probing the file while the pool serves traffic is
    # how a green check ends up next to a broken install.
    lease = await P.acquire(db, purpose="probe")
    if lease is not None:
        result = await run_probe(await build_bundle(db, "claude_code", timeout_s=120, lease=lease))
        result["account"] = lease.label
        from memora.providers.errors import classify
        await P.report(db, lease, ok=bool(result.get("ok")),
                       code=None if result.get("ok") else classify(str(result.get("error") or "")),
                       error=str(result.get("error") or ""))
        await S.put(db, "providers.claude_code.status", result)
        return result
    mode = await S.get(db, "providers.claude_code.auth_mode") or "oauth"
    # clear, actionable errors before spawning anything
    precheck: str | None = None
    if mode == "oauth":
        creds = read_credentials()
        if creds is None:
            precheck = "credentials_missing: no ~/.claude/.credentials.json — run the device login or import credentials"
        elif not _oauth_valid(creds):
            precheck = "credentials_expired: the stored OAuth token has expired — log in again"
    elif mode == "api_key" and not await S.get(db, "providers.anthropic.api_key"):
        precheck = "api_key_missing: set the Anthropic API key or switch auth mode"
    elif mode == "setup_token" and not await S.get(db, "providers.claude_code.setup_token"):
        precheck = "setup_token_missing: paste a setup token or switch auth mode"
    if precheck:
        result.update(ok=False, error=precheck, ms=0)
        await S.put(db, "providers.claude_code.status", result)
        return result
    result = await run_probe(await build_bundle(db, "claude_code", timeout_s=120))
    await S.put(db, "providers.claude_code.status", result)
    return result
