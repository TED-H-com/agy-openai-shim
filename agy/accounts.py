"""Multi-account pool for the Antigravity provider (local patch, not upstream).

Accounts are directories under ``$ANTIGRAVITY_ACCOUNTS_DIR`` (default
``~/.gemini/antigravity-accounts``) whose names start with ``acct`` and that
hold an agy OAuth token file (e.g. ``acct1 -> ~/.gemini/antigravity-cli``).
Directories without a usable token (e.g. a login still in progress) are
simply not in the pool. ``ANTIGRAVITY_ACCOUNT_DIRS`` (os.pathsep-separated)
overrides discovery with an explicit list.

The pool is OFF (legacy single-token behavior) when ``ANTIGRAVITY_POOL=0``,
when ``ANTIGRAVITY_CONFIG_DIR`` is set (an explicit single-token override
wins), or when no account has a token.

Rotation state lives in ``$HERMES_HOME/antigravity-pool/state.json`` and is
guarded by an ``fcntl`` lock so concurrent Hermes processes share one cursor.
Only file presence/size of tokens is ever checked; token contents are never
read. Status: ``python accounts.py`` (accounts, counters, cooldowns); per-request
history in ``$HERMES_HOME/antigravity-pool/events.log``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows: best effort without cross-process locking
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TOKEN_FILENAMES = ("jetski-standalone-oauth-token", "antigravity-oauth-token")

STRATEGY_ROUND_ROBIN = "round_robin"  # rotate the starting account every request
STRATEGY_FILL_FIRST = "fill_first"  # stay on the first healthy account (keeps the worker warm)

_QUOTA_MARKERS = ("resource_exhausted", "429", "quota", "rate limit", "rate-limit", "too many requests")
_AUTH_MARKERS = (
    "unauthenticated", "401", "permission_denied", "invalid_grant", "invalid_token",
    "not authenticated", "not signed in", "token has been expired", "token expired",
    "reauth", "login required", "unauthorized", "authentication failed",
    "authentication required", "not logged in",
)


class AgyTransientError(RuntimeError):
    """A model choice that can be retried before output reaches the consumer."""


def parse_reset_seconds(text: str) -> float | None:
    """Parse agy's ordered, optional day/hour/minute/second reset duration."""
    match = re.search(
        r"\bresets\s+in\s+((?:\d+\s*d\s*)?(?:\d+\s*h\s*)?"
        r"(?:\d+\s*m\s*)?(?:\d+\s*s)?)(?=\s*(?:[.,;:)]|$))",
        text, re.IGNORECASE,
    )
    if not match or not match.group(1).strip():
        return None
    parts = re.findall(r"(\d+)\s*([dhms])", match.group(1), re.IGNORECASE)
    return float(sum(int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u.lower()]
                     for n, u in parts))


@dataclass(frozen=True)
class Account:
    name: str
    token_path: Path


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def pool_enabled() -> bool:
    if os.getenv("ANTIGRAVITY_POOL", "").strip().lower() in ("0", "false", "off", "no"):
        return False
    if os.getenv("ANTIGRAVITY_CONFIG_DIR", "").strip():
        return False
    return True


def accounts_dir() -> Path:
    raw = os.getenv("ANTIGRAVITY_ACCOUNTS_DIR", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".gemini" / "antigravity-accounts"


def state_dir() -> Path:
    raw = os.getenv("ANTIGRAVITY_POOL_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    hermes_home = os.getenv("HERMES_HOME", "").strip()
    base = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
    return base / "antigravity-pool"


def strategy() -> str:
    value = os.getenv("ANTIGRAVITY_POOL_STRATEGY", "").strip().lower()
    return STRATEGY_FILL_FIRST if value == STRATEGY_FILL_FIRST else STRATEGY_ROUND_ROBIN


def token_in_dir(directory: Path) -> Path | None:
    """First usable token file (size > 10) in *directory*; contents never read."""
    for filename in TOKEN_FILENAMES:
        candidate = directory / filename
        try:
            if candidate.is_file() and candidate.stat().st_size > 10:
                return candidate
        except OSError:
            continue
    return None


def discover_accounts() -> list[Account]:
    """Accounts with a usable token, in stable name order. [] when the pool is off."""
    if not pool_enabled():
        return []
    explicit = os.getenv("ANTIGRAVITY_ACCOUNT_DIRS", "").strip()
    if explicit:
        dirs = [Path(p).expanduser() for p in explicit.split(os.pathsep) if p.strip()]
    else:
        base = accounts_dir()
        try:
            dirs = sorted(
                (p for p in base.iterdir() if p.name.startswith("acct") and not p.name.endswith("-home")),
                key=lambda p: p.name,
            )
        except OSError:
            return []
    accounts: list[Account] = []
    for directory in dirs:
        try:
            if not directory.is_dir():
                continue
        except OSError:
            continue
        token = token_in_dir(directory)
        if token is not None:
            accounts.append(Account(name=directory.name, token_path=token))
    return accounts


def classify_error(exc: BaseException | str) -> str | None:
    """Classify quota/auth first, then retryable transient model failures."""
    text = str(exc).lower()
    if any(marker in text for marker in _QUOTA_MARKERS):
        return "quota"
    if any(marker in text for marker in _AUTH_MARKERS):
        return "auth"
    if isinstance(exc, AgyTransientError) or "antigravity transient error:" in text:
        return "transient"
    return None


@contextlib.contextmanager
def _locked_state() -> Iterator[dict]:
    """Yield the mutable state dict under an exclusive cross-process lock; persisted on exit."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "state.lock"
    state_path = directory / "state.json"
    with open(lock_path, "a+") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    state = {}
            except (OSError, ValueError):
                state = {}
            state.setdefault("cursor", 0)
            state.setdefault("accounts", {})
            yield state
            tmp = state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, state_path)
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _event(line: str) -> None:
    """Append one line to events.log (who served / failed each request); rotated at 1 MB."""
    with contextlib.suppress(OSError):
        path = state_dir() / "events.log"
        if path.exists() and path.stat().st_size > 1_000_000:
            os.replace(path, path.with_suffix(".log.1"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} pid={os.getpid()} {line}\n")


def _entry(state: dict, name: str) -> dict:
    entry = state["accounts"].setdefault(name, {})
    for key in ("served", "failures"):
        entry.setdefault(key, 0)
    entry.setdefault("cooldown_until", 0.0)
    return entry


def acquire_order(accounts: list[Account] | None = None) -> list[Account]:
    """Accounts to try for ONE request, in order.

    round_robin advances the shared cursor by one per request; fill_first
    always starts at the first account. Accounts in cooldown are skipped;
    if every account is cooling down, the one that recovers soonest is
    still tried once so the request is not refused outright.
    """
    accounts = discover_accounts() if accounts is None else accounts
    if not accounts:
        return []
    now = time.time()
    with _locked_state() as state:
        if strategy() == STRATEGY_ROUND_ROBIN:
            start = int(state.get("cursor", 0)) % len(accounts)
            state["cursor"] = (start + 1) % len(accounts)
        else:
            start = 0
        ordered = accounts[start:] + accounts[:start]
        healthy = [a for a in ordered if float(_entry(state, a.name)["cooldown_until"]) <= now]
        if healthy:
            return healthy
        return [min(ordered, key=lambda a: float(_entry(state, a.name)["cooldown_until"]))]


def in_cooldown(account: Account) -> bool:
    with _locked_state() as state:
        return float(_entry(state, account.name)["cooldown_until"]) > time.time()


def mark_success(account: Account, model: str | None = None) -> None:
    with _locked_state() as state:
        entry = _entry(state, account.name)
        entry["served"] += 1
        entry["last_served_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        entry["last_model"] = model or ""
        entry["cooldown_until"] = 0.0
    _event(f"served account={account.name} model={model or ''}")
    logger.info("Antigravity pool: request served by account %s (model=%s)", account.name, model)


def mark_failure(account: Account, kind: str | None, error: BaseException | str) -> None:
    """Record a failed attempt; quota/auth failures put the account in cooldown."""
    cooldown = 0.0
    source = ""
    if kind == "quota":
        reset = parse_reset_seconds(str(error))
        if reset is not None:
            cooldown = min(
                reset + _env_float("ANTIGRAVITY_POOL_QUOTA_RESET_MARGIN", 30.0),
                _env_float("ANTIGRAVITY_POOL_QUOTA_MAX_COOLDOWN", 8 * 86400.0),
            )
            source = " source=resets_in"
        else:
            cooldown = _env_float("ANTIGRAVITY_POOL_QUOTA_COOLDOWN", 900.0)
            source = " source=fallback"
    elif kind == "auth":
        cooldown = _env_float("ANTIGRAVITY_POOL_AUTH_COOLDOWN", 3600.0)
    with _locked_state() as state:
        entry = _entry(state, account.name)
        entry["failures"] += 1
        entry["last_error"] = f"{kind or 'other'}: {str(error)[:200]}"
        entry["last_error_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if cooldown:
            entry["cooldown_until"] = time.time() + cooldown
    _event(f"failed account={account.name} kind={kind or 'other'} cooldown={int(cooldown)}s{source}")
    logger.warning(
        "Antigravity pool: account %s failed (%s)%s",
        account.name, kind or "other", f"; cooling down {int(cooldown)}s{source}" if cooldown else "",
    )


def status_lines() -> list[str]:
    accounts = discover_accounts()
    lines = [
        f"pool enabled: {pool_enabled()}  strategy: {strategy()}  accounts dir: {accounts_dir()}",
        f"state: {state_dir() / 'state.json'}",
    ]
    try:
        state = json.loads((state_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"accounts": {}, "cursor": 0}
    names = {a.name for a in accounts}
    lines.append(f"active accounts: {len(accounts)}  next cursor: {state.get('cursor', 0)}")
    now = time.time()
    for name in sorted(names | set(state.get("accounts", {}))):
        entry = state.get("accounts", {}).get(name, {})
        cool = float(entry.get("cooldown_until", 0) or 0)
        lines.append(
            f"  {name:8s} token={'yes' if name in names else 'NO '} served={entry.get('served', 0)} "
            f"failures={entry.get('failures', 0)} last_served={entry.get('last_served_at', '-')} "
            f"cooldown={'%ds' % (cool - now) if cool > now else '-'} last_error={entry.get('last_error', '-')}"
        )
    return lines


if __name__ == "__main__":
    if sys.argv[1:2] == ["reset-cooldowns"]:
        with _locked_state() as _state:
            for _e in _state["accounts"].values():
                _e["cooldown_until"] = 0.0
    print("\n".join(status_lines()))
