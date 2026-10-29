# API Compatibility Matrix

This document describes how the `agy-openai-shim` maps OpenAI API wire protocols to Google's Antigravity CLI format.

## Supported Endpoints

- `GET /v1/models` (or `/models`): Returns a static list of supported models.
- `GET /health` (or `/healthz`): Returns a simple 200 OK status and lists active accounts in the pool. Returns 503 if no accounts are available.
- `POST /v1/chat/completions` (or `/chat/completions`): Supports chat completions request.

## Supported Models

The following model IDs are explicitly provided in `/v1/models`:

- `gemini-3.8-flash`
- `gemini-3.8-flash-low`
- `gemini-3.8-flash-medium`
- `gemini-3.8-flash-high`
- `gemini-3.1-pro`

Other valid Antigravity model names might also work if provided by the client, though they are not enumerated in the models list.

## Feature Mapping

- **Streaming:** Both streaming (`stream: true`) and non-streaming responses are supported.
- **Roles:** The `developer` role from OpenAI clients is automatically translated into the `system` role before being sent to the Antigravity CLI.
- **Tool Calls:** `<tool_call>` tags from Antigravity are mapped to native OpenAI `tool_calls` output format. The Antigravity CLI's own built-in host tools are explicitly disabled via `--disable-slash-commands`.
- **Reasoning Effort:** Supports `reasoning_effort` top-level parameter or within the `reasoning` parameter object (`reasoning.effort`), mapping it to the `--effort` CLI flag.

## Unimplemented Features

Features not mentioned above (such as embeddings, audio inputs, image generation) are not supported. Usage of standard OpenAI headers, outside of basic content-length parsing, is largely ignored.
