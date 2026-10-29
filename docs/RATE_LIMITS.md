# Rate Limits and Error Handling

The `agy-openai-shim` handles upstream errors robustly to maximize availability. It classifies errors returned by the underlying Antigravity CLI and translates them into appropriate OpenAI HTTP status codes, whilst using error patterns to manage account pool cooling.

## Error Classification

When the shim encounters an exception, it scans the error message for known text markers and classifies it:

1. **`quota`:** Triggered by markers like `resource_exhausted`, `429`, `quota`, `rate limit`, or `too many requests`. Returns a `429 rate_limit_exceeded` to the client.
2. **`auth`:** Triggered by markers like `unauthenticated`, `401`, `invalid_grant`, `not logged in`, or `token expired`. Returns a `401 invalid_api_key`.
3. **`transient`:** Triggered by internal model errors or `AgyTransientError`. Returns a `503 upstream_transient`.
4. **`other`:** Unrecognized exceptions default to `502 upstream_error`.

To aid client integrations like Hermes, original upstream error messages are sanitized (truncated to max length) but passed along within the JSON payload rather than being suppressed.

## Rate Limit Backoff and Cooldowns

When an account experiences an error, it is placed into a "cooldown" period. During cooldown, the pool will automatically skip the account and attempt the request on the next available healthy account.

- **Dynamic Quota Cooldown:**
  If the `quota` error message contains a "resets in X" format (e.g., "resets in 5m 30s"), the shim parses this duration.
  The cooldown is set to this reset time plus a margin (`ANTIGRAVITY_POOL_QUOTA_RESET_MARGIN`, default 30.0s), capped at `ANTIGRAVITY_POOL_QUOTA_MAX_COOLDOWN` (default 8 days).

- **Static Quota Cooldown:**
  If it's a `quota` error but no explicit reset time is found, the account enters a static cooldown defined by `ANTIGRAVITY_POOL_QUOTA_COOLDOWN` (default 900.0s).

- **Auth Cooldown:**
  If an `auth` error is encountered, the account is placed in cooldown for `ANTIGRAVITY_POOL_AUTH_COOLDOWN` (default 3600.0s), providing administrators time to rotate the token.

In the extreme scenario where all accounts are in a cooldown state, the router avoids outright rejection by allowing an attempt on the account scheduled to recover the soonest.

## Transient Failures and Retries

For `transient` failures, the pool strategy automatically allows a single immediate retry on the same request using a different account, transparently to the caller. This also lazily applies to in-flight streaming requests, provided that no response chunks have yet been sent to the consumer.
