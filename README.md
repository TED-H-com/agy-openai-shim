# agy-openai-shim

OpenAI-compatible `/v1/chat/completions` loopback server backed by Google's official `agy` (Antigravity) CLI. Lets tools that speak the OpenAI wire protocol use an Antigravity / Gemini subscription instead of a metered API key.

This is a **Python, stdlib-only** implementation with a **multi-account pool** (round-robin or fill-first failover, per-account quota cooldown). It is **not** the same codebase as [tphakala/agy-openai-shim](https://github.com/tphakala/agy-openai-shim) (Go).

## How it works

```
your agent (OpenAI base URL http://127.0.0.1:18795/v1)
  -> server.py
  -> official `agy` CLI (--output-format stream-json)
  -> account pool (round_robin or fill_first)
```

Tool calls are emulated (`<tool_call>` tags → OpenAI `tool_calls`). The CLI's own host tools are denied.

## Requirements

- Python 3.10+
- `agy` (Google Antigravity CLI) CLI installed and authenticated for each account you put in the pool

## Install

```bash
git clone https://github.com/TED-H-com/agy-openai-shim.git
cd agy-openai-shim
mkdir -p ~/.local/share/agy-openai-shim
cp -r server.py agy ~/.local/share/agy-openai-shim/
mkdir -p ~/.config/agy-openai-shim
cp env.example ~/.config/agy-openai-shim/env
# edit env: set ANTIGRAVITY_ACCOUNT_DIRS to your account config dirs
```

Optional systemd user unit (see `agy-openai-shim.service`):

```bash
mkdir -p ~/.config/systemd/user
cp agy-openai-shim.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agy-openai-shim
```

## Configuration

Copy `env.example` to `~/.config/agy-openai-shim/env`. Important variables:

| Variable | Meaning |
|---|---|
| `AGY_SHIM_HOST` / `AGY_SHIM_PORT` | Bind address (default `127.0.0.1:18795`) |
| `ANTIGRAVITY_ACCOUNT_DIRS` | `:`-separated list of per-account config dirs (each must contain an OAuth token file) |
| `ANTIGRAVITY_POOL_STRATEGY` | `round_robin` or `fill_first` |
| `ANTIGRAVITY_POOL_STATE_DIR` | Where pool state and `events.log` live |
| `AGY_SHIM_TIMEOUT` | Per-request timeout in seconds (default `900`) |

OAuth tokens stay in each account directory (mode `600`). This repo never ships tokens. Token contents are never read by the shim—only file presence/size is checked.

Example account layout:

```
~/.gemini/antigravity-accounts/acct1/antigravity-oauth-token
~/.gemini/antigravity-accounts/acct2/antigravity-oauth-token
~/.gemini/antigravity-accounts/acct3/antigravity-oauth-token
```

## Health check

```bash
curl -s http://127.0.0.1:18795/health
```

## Attribution

Core Antigravity client code is vendored from the Hermes plugin
`antigravity-subscription-directsdk`
([soyelmismo/hermes-antigravity-subscription](https://github.com/soyelmismo/hermes-antigravity-subscription), MIT).
The multi-account pool, systemd packaging, and OpenAI `/v1` server wrapper are additions in this repository.

## License

MIT — see [LICENSE](LICENSE).
