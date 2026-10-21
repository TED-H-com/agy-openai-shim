# agy-openai-shim (managed by Grok Bot from grok-bot-01)

OpenClaw has no supported Antigravity/Gemini-CLI OAuth path, so OpenClaw reaches
Gemini 3.8 Flash on Ted's Google subscriptions through this loopback shim:

  OpenClaw provider `antigravity-agy` (api openai-completions, http://127.0.0.1:18795/v1)
    -> server.py (stdlib) -> official `agy` CLI (--output-format stream-json)
    -> accounts: acct1 -> acct2 -> acct3 (round_robin per request, failover on error)

Tool calls are emulated (<tool_call> tags -> OpenAI tool_calls); agy's own tools are denied.
Code vendored from the Hermes plugin antigravity-subscription-directsdk (MIT) + multi-account patch.

Files
  ~/.local/share/agy-openai-shim/            code (server.py, agy/)
  ~/.config/agy-openai-shim/env               settings (no secrets)
  ~/.gemini/antigravity-accounts/acctN/antigravity-oauth-token   OAuth tokens (600), copied from grok-bot-01
  ~/.local/state/agy-openai-shim/pool/events.log                 which account served / cooled down
  systemctl --user status agy-openai-shim ; journalctl --user -u agy-openai-shim
Health: curl -s 127.0.0.1:18795/health
Re-login an account: on grok-bot-01 run agy login for that account, then re-run the fleet deploy (copies tokens).

## Origin and license
The `agy/` package is derived from the Hermes plugin
[soyelmismo/hermes-antigravity-subscription](https://github.com/soyelmismo/hermes-antigravity-subscription)
(MIT, Copyright (c) 2026 soyelmismo). Its license is kept at `agy/LICENSE` and `LICENSE-UPSTREAM`.
Local changes: multi-account pool (round_robin / fill_first), transient-error handling, and the stdlib `server.py` OpenAI-compatible front end.
The `upstream` remote and `upstream-sync` branch track that repo for reference; layouts differ, so syncs are manual.

Fleet setting (2026-10-21): `ANTIGRAVITY_POOL_STRATEGY=round_robin`. See `.env.example` for setting names.
