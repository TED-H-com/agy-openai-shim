# Core Modules Architecture

The `agy-openai-shim` internal functionality is divided into several specific modules to handle the translation between OpenAI API requests and the Google Antigravity CLI format, while maintaining stability, multi-account pooling, and fault tolerance.

## Architecture Overview

The system architecture focuses on receiving OpenAI-compatible requests through an HTTP server, routing those requests to a selected account pool, transforming the messages/prompts, and parsing streaming responses.

### `server.py`
The entry point of the application. It acts as the lightweight, standard-library-only HTTP server implementing the OpenAI `/v1/chat/completions` API structure. It manages incoming connections, delegates requests to the `agy` module functionality, and returns standard JSON responses or server-sent events for streaming.

### `agy/accounts.py`
Responsible for the multi-account pool feature. It handles:
- Automatically discovering available Antigravity account directories and OAuth tokens.
- Tracking metrics such as request counts and failover rates per account.
- Maintaining cooldown timers (e.g., locking out accounts that hit quota limits temporarily).
- Executing the selected pooling strategy (`round_robin` or `fill_first`).

### `agy/client.py`
The facade client that manages the execution loop with the `agy` (Antigravity CLI). It operates by establishing a child process via `agy/process.py`, handling input and stream orchestration. In case of quota errors or failures detected by the pool, `_PooledStream` in this module handles automatic retries and shifting to alternate pool accounts.

### `agy/models.py`
Manages model names and compatibility aliases. This file specifies how OpenAI-style model IDs (like `gemini-3.8-flash` or `claude-sonnet-4-6`) map natively into Antigravity CLI equivalents. It is also responsible for interpreting the `reasoning_effort` argument to automatically determine CLI suffixes (`-high`, `-medium`, `-low`).

### `agy/process.py`
A lower-level helper dedicated strictly to OS-level operations involving the `agy` CLI binary. It sets up isolated home environments (`$HOME`) so the CLI picks up the specific account token in a multi-account pooling scenario, and manages subprocess creation and clean termination (killing the process tree to avoid zombies).

### `agy/prompt.py`
Manages message and context formatting. Converts standard OpenAI chat history structures (`{"role": "user", "content": "..."}`) into formats compatible with the CLI. It handles specific cases such as translating the `developer` role to `system` and stripping out unsupported options.

### `agy/stream.py`
Parses the streaming output from the Antigravity CLI process. As the CLI emits JSON blocks, this module intercepts and restructures those chunks into exact OpenAI `ChatCompletionChunk` SSE payloads. It manages tool-call emulation and calculates precise usage counters based on the session's stream delta metrics.
