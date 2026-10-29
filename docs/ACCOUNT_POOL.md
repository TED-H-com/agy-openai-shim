# Account Pool

The `agy-openai-shim` supports pooling multiple Antigravity CLI accounts to distribute workload or implement failover.

## Directory Structure and Discovery

Accounts are discovered automatically if they reside in the default base directory (e.g., `~/.gemini/antigravity-accounts`) and their folder names start with `acct`.
Alternatively, you can provide an explicit list using the environment variable `ANTIGRAVITY_ACCOUNT_DIRS`.

For an account to be considered valid and added to the pool, its directory must contain a valid OAuth token file (either `jetski-standalone-oauth-token` or `antigravity-oauth-token`) with a file size greater than 10 bytes. The shim strictly relies on file presence/size and does not parse or read token contents.

Example layout:
```
~/.gemini/antigravity-accounts/acct1/antigravity-oauth-token
~/.gemini/antigravity-accounts/acct2/antigravity-oauth-token
```

## Rotation Strategies

The shim implements two account rotation strategies, configured via the `ANTIGRAVITY_POOL_STRATEGY` environment variable:

1. **`round_robin` (Default):**
   The shared pool cursor advances by one on every request. This distributes requests evenly across all healthy accounts.

2. **`fill_first`:**
   Always attempts to use the first available healthy account in the pool order. Subsequent accounts are only used if earlier accounts encounter failures (quota or auth limits) and enter a cooldown state. This approach helps keep the active worker warm.

## Tracking and Status

The state of the pool (including counters and active cooldowns) is stored in a JSON file (`state.json`), managed with cross-process locking. Logs of request outcomes (successes and failures) are appended to an `events.log` file, rotated at 1 MB.

To inspect the status of the pool, you can run the accounts script:
```bash
python agy/accounts.py
```
This prints the active accounts, total requests served, failure counters, and any active cooldown timers.
