# Setup Guide

This guide will walk you through setting up `agy-openai-shim`.

## 1. Prerequisites

- Python 3.10+
- The `agy` (Google Antigravity CLI) installed and authenticated for **each** account you intend to place into the pool.

## 2. Installation

Clone the repository and copy the necessary files into a local bin directory:

```bash
git clone https://github.com/TED-H-com/agy-openai-shim.git
cd agy-openai-shim

# Set up the local share directory
mkdir -p ~/.local/share/agy-openai-shim
cp -r server.py agy ~/.local/share/agy-openai-shim/
```

## 3. Configuration Setup

Copy the example environment configuration to your config directory:

```bash
mkdir -p ~/.config/agy-openai-shim
cp env.example ~/.config/agy-openai-shim/env
```

Edit the `~/.config/agy-openai-shim/env` file to customize your setup:

- `AGY_SHIM_HOST` / `AGY_SHIM_PORT`: The bind address and port (default is `127.0.0.1:18795`).
- `ANTIGRAVITY_POOL_STRATEGY`: Strategy for the pool (`round_robin` or `fill_first`).
- `ANTIGRAVITY_ACCOUNT_DIRS`: A colon (`:`)-separated list of configuration directories for each account. This setting allows overriding automatic directory discovery.
- `AGY_SHIM_TIMEOUT`: The maximum seconds allowed per request (default `900`).

## 4. Managing OAuth Tokens

For every account added to the pool, the account's directory must contain a valid OAuth token. We recommend structuring the directories locally in the `~/.gemini/antigravity-accounts` path.

Example account structure:
```
~/.gemini/antigravity-accounts/acct1/antigravity-oauth-token
~/.gemini/antigravity-accounts/acct2/antigravity-oauth-token
```
*Note: Tokens must remain secure (e.g., file permissions set to mode `600`). This repository will never read or transport the contents of these tokens; it solely verifies their presence to manage the account pool.*

## 5. Running as a Systemd Service

Optionally, you can configure the shim to run in the background using `systemd`.

```bash
# Prepare the systemd user unit directory
mkdir -p ~/.config/systemd/user
cp agy-openai-shim.service ~/.config/systemd/user/

# Reload the systemd daemon to recognize the new service
systemctl --user daemon-reload

# Enable and start the service
systemctl --user enable --now agy-openai-shim
```

Check the service status:
```bash
systemctl --user status agy-openai-shim
```

## 6. Health Check

Ensure the server is running correctly:
```bash
curl -s http://127.0.0.1:18795/health
```
A successful response will output a `200 OK` JSON block listing the accounts actively pooled.
