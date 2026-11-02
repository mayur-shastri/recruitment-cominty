# Cominty Python SDK --- Offline Reference

> Purpose: offline reference for coding agents working with the Cominty
> managed-agent Python SDK.
>
> **Source of truth:** the package-maintainer documentation on PyPI:
> https://pypi.org/project/cominty-sdk/
>
> **Source repository:** https://github.com/cominty/python-sdk
>
> This file is a Markdown working copy of the public SDK documentation,
> organized for offline use. The PyPI README is the canonical reference
> and may change. Check the installed package version and compare
> against the canonical page before relying on version-sensitive
> details.

## 1. What the SDK does

`cominty-sdk` is Cominty's official asynchronous Python client for its
managed-agent chat API.

-   Async-first; built on `httpx`.
-   Typed Python models (Pydantic) and ships `py.typed`.
-   Supports awaiting a final response or streaming progress events.
-   Supports continuing conversations in existing threads.
-   Exposes thread management, memory files, file upload/download,
    message export, and agent capabilities.
-   Performs local parameter validation; invalid values raise
    `InvalidParams` before a request is sent.
-   SDK errors inherit from `ComintyError`.

Python requirement: **3.9+**.

## 2. Install

``` bash
pip install cominty-sdk
# or
uv add cominty-sdk
```

For the repository's examples and development dependencies:

``` bash
uv sync --all-extras --dev
```

## 3. Authentication and configuration

The SDK requires both a Cominty API key and a Cominty user ID.

-   API key: obtain from https://platform.cominty.ai/api-keys (the key
    is shown once).
-   User ID: in the Cominty platform, open the avatar menu and then
    Profile. It resembles `user_...`.

The SDK's `user_id` identifies the Cominty user on whose behalf requests
are made. It is not automatically a Slack user ID or an application's
own user ID.

### Environment variables

``` bash
export COMINTY_API_KEY="<your-api-key>"
export COMINTY_USER_ID="user_..."
```

### Explicit configuration

``` python
from cominty_sdk import AsyncCominty

client = AsyncCominty(
    api_token="<your-api-key>",
    user_id="user_...",
)
```

Explicit constructor arguments take precedence over environment
variables.

### Configuration reference

  Constructor argument   Environment variable   Default
  ---------------------- ---------------------- --------------------------
  `api_token`            `COMINTY_API_KEY`      Required
  `user_id`              `COMINTY_USER_ID`      Required
  `base_url`             `COMINTY_BASE_URL`     `https://ds.cominty.com`
  `timeout`              ---                    `60` seconds

Resolution order: explicit argument → environment variable → default.

**Important:** the SDK does not automatically load `.env`. Load it
yourself (for example with `python-dotenv`) or export the variables in
the process environment. A malformed `user_id` is rejected when the
client is constructed.

## 4. Find an agent ID

Every chat operation requires an `agent_id`. Find the agent in the
Cominty platform's Agents page:

https://platform.cominty.ai/agents

IDs may look like:

``` text
__cominty_agents::agent.chat
```

Use the exact ID shown by the platform; do not invent one.

## 5. Basic usage

``` python
import asyncio
from cominty_sdk import AsyncCominty

AGENT_ID = "__cominty_agents::agent.chat"

async def main() -> None:
    async with AsyncCominty() as client:
        run = await client.chat.start(
            agent_id=AGENT_ID,
            message="What is Cominty?",
        )
        print(await run.text())

asyncio.run(main())
```

`AsyncCominty` can be used as an async context manager. The context
manager closes the underlying client resources.

### `chat.start`

Starts a new conversation and returns a run handle:

``` python
run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Give me one fun fact.",
)
answer = await run.text()
```

`await run.text()` waits for completion and returns the response text.

`await run.result()` returns the full `Message` object, which can
contain status, files, structured output, and questions. `text()` is
shorthand for `result().content`.

### `chat.send`

Continues an existing thread. It takes the thread ID as the first
positional argument and otherwise has the same general message options
as `chat.start`.

``` python
first = await client.chat.start(
    agent_id=AGENT_ID,
    message="Pick a programming language.",
)
await first.text()

second = await client.chat.send(
    first.thread.id,
    agent_id=AGENT_ID,
    message="Show me a hello-world example.",
)
print(await second.text())
```

The existing thread's context is retained. Persist `run.thread.id` in
your application if a later request must continue the same conversation.

### Clarifying questions

An agent can finish a turn by returning questions instead of a final
answer. Each question has a `prompt` and suggested `options`.

``` python
run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Book me a room.",
)
await run.text()

for question in await run.questions():
    print(question.prompt, question.options)

reply = await client.chat.send(
    run.thread.id,
    agent_id=AGENT_ID,
    message="Tomorrow at 10 AM",
)
print(await reply.text())
```

The answer is sent as a normal follow-up message.

## 6. Streaming run events

A run can be iterated to receive progress events, including tool calls,
LLM steps, and the result event.

``` python
from cominty_sdk import events

run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Research this topic and summarize it.",
)

async for event in run:
    if isinstance(event, events.ToolCall):
        print("tool", event.data.name, "->", event.status)
    elif isinstance(event, events.LlmStep):
        print("llm", event.data.description)
    elif isinstance(event, events.Result):
        print("cost", event.data.cost.total)

print("FINAL:", await run.text())
```

A run's event stream is **single-use**. Iterate it or await its result.
Once drained, the result is cached, so calling `text()` or `result()`
afterward is free.

## 7. Message parameters

The package README documents these common parameters for `chat.start`
and `chat.send`:

  -----------------------------------------------------------------------
  Parameter               Type                    Notes
  ----------------------- ----------------------- -----------------------
  `agent_id`              `str`                   Required; exact agent
                                                  ID

  `message`               `str`                   Required; maximum
                                                  30,000 characters

  `name`                  `str`                   `start` only; names the
                                                  new thread

  `file_ids`              `list[str]`             IDs returned by
                                                  `chat.upload_file`;
                                                  maximum 5 files per
                                                  message

  `thread_capabilities`   `AgentCapabilities`     `start` only;
                                                  capability
                                                  configuration frozen
                                                  for the thread

  `message_scope`         `MessageScope`          Per-message capability
                                                  narrowing/enabling

  `max_steps`             `int`                   Per-message cap on tool
                                                  rounds; must be at
                                                  least 1
  -----------------------------------------------------------------------

Invalid values raise `InvalidParams` locally before an API request is
sent.

## 8. Limiting tool rounds with `max_steps`

`max_steps` caps the number of tool rounds for a single message, not for
the whole thread.

``` python
run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Research this and prepare a report.",
    max_steps=5,
)
print(await run.text())

# The cap must be supplied again on a later message if desired.
follow_up = await client.chat.send(
    run.thread.id,
    agent_id=AGENT_ID,
    message="Continue with the remaining work.",
    max_steps=10,
)
print(await follow_up.text())
```

If omitted (or passed as `SERVER_DEFAULT`), the server default applies
(documented as 60 at the time of the README). Reaching the cap is not an
API error: the agent stops using tools, summarizes, and may ask whether
to continue. The SDK does not expose a dedicated field indicating that
the cap was reached. Do not parse the model's prose to detect it.

There is no unlimited setting. `None` and integers below 1 are invalid.

## 9. Agent capabilities and per-message scopes

Capabilities control what an agent may use. The README documents:

-   `web`
-   `indexed_documents`
-   `mcp`
-   `skills`
-   `image_generation`
-   `video_generation`
-   `music_generation`
-   `memory`

Import the capability classes explicitly:

``` python
from cominty_sdk import (
    ALL,
    AgentCapabilities,
    IndexedDocumentsCapability,
    IndexedDocumentsScope,
    McpCapability,
    McpScope,
    MemoryCapability,
    MessageScope,
    SkillsCapability,
    WebCapability,
    WebScope,
)
```

### Thread capabilities

`thread_capabilities` is passed to `chat.start` only. It establishes the
capabilities for the thread and is frozen for that thread.

``` python
run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Review the relevant documents.",
    thread_capabilities=AgentCapabilities(
        web=WebCapability(activation="always"),
        indexed_documents=IndexedDocumentsCapability(
            activation="always",
            source_ids=[101],
        ),
        mcp=McpCapability(
            activation="on_request",
            connections=["harly-recruiter"],
        ),
        skills=SkillsCapability(activation="always"),
        memory=MemoryCapability(
            activation="always",
            namespace="recruitment-demo",
        ),
    ),
)
```

This is an illustrative configuration. Use the exact connection
identifiers configured in the Cominty workspace.

### Activation values

For capabilities that support activation:

-   `"always"` --- enabled by default.
-   `"on_request"` --- off until a message enables it.
-   `"never"` --- not installed for the thread.

`SkillsCapability` and `MemoryCapability` do not support `"on_request"`.

If a capability is omitted, the agent's existing configured value is
retained.

### Message scopes

`message_scope` is passed to `chat.start` or `chat.send` to control a
capability for one message.

``` python
reply = await client.chat.send(
    run.thread.id,
    agent_id=AGENT_ID,
    message="Use only the Harly connection for this request.",
    message_scope=MessageScope(
        mcp=McpScope(
            enabled=True,
            connections=["harly-recruiter"],
        ),
        web=WebScope(enabled=False),
    ),
)
```

A message scope can only narrow what the thread allows. It cannot grant
a capability that the thread does not have or widen a thread's
allowlist. The server returns HTTP 422 (`APIError`) if a message
attempts to widen the thread's permissions or target a capability the
thread does not have.

### Filters and allowlists

Filters such as `source_ids`, `document_ids`, `connections`, and
`include` default to `ALL` (the string `"*"`), meaning no restriction.

-   Omitting a filter means `ALL`.
-   Passing a capability replaces its stored configuration; omitting a
    filter in that replacement resets it to `ALL`.
-   To restrict access, pass a non-empty list.
-   `None`, `[]`, and `"*"` inside a list are invalid.
-   With `activation="never"` or `enabled=False`, do not pass additional
    filters.

`ALL` can be imported from `cominty_sdk` and used explicitly.

### Memory capability

`MemoryCapability(activation="always", namespace="...")` attaches a
thread to a memory namespace. That namespace is frozen for the lifetime
of the thread. A follow-up message cannot switch the thread to another
memory namespace.

A message has no memory scope. If no memory capability is supplied, the
thread uses the agent's configured namespace, or no memory if the agent
has none.

### Important distinctions

-   `AgentCapabilities` is a thread-level configuration supplied when
    starting a thread.
-   `MessageScope` applies to one message and can only narrow the
    thread-level permissions.
-   `MessageScope` has no `skills` or `memory` field.
-   MCP connection allowlists are capability configuration, not a
    substitute for authorization checks in your own backend.
-   A Cominty `user_id` is the Cominty account identity used by the SDK;
    do not assume it is the authenticated identity of an external Slack
    user.

## 10. MCP connection example

The SDK exposes MCP through `McpCapability` and `McpScope`. A thread can
be configured with an MCP connection allowlist:

``` python
from cominty_sdk import AgentCapabilities, McpCapability

thread_caps = AgentCapabilities(
    mcp=McpCapability(
        activation="always",
        connections=["harly-recruiter"],
    )
)

run = await client.chat.start(
    agent_id=AGENT_ID,
    message="List the open jobs.",
    thread_capabilities=thread_caps,
)
print(await run.text())
```

To make an already-allowed connection available for one message:

``` python
from cominty_sdk import McpScope, MessageScope

reply = await client.chat.send(
    run.thread.id,
    agent_id=AGENT_ID,
    message="Read the latest application.",
    message_scope=MessageScope(
        mcp=McpScope(
            enabled=True,
            connections=["harly-recruiter"],
        )
    ),
)
```

The workspace integration must exist and the connection identifier must
match its configured identifier. The SDK reference documents
connection-level allowlists; it does **not** establish that this is a
per-tool authorization mechanism.

## 11. Uploading and downloading files

`chat.upload_file()` registers a file. Attach its returned ID using
`file_ids` (maximum 5 files per message).

``` python
from pathlib import Path

# Path input: filename and MIME type are inferred.
resume = await client.chat.upload_file(Path("candidate-resume.pdf"))

# Bytes input: filename is required.
csv_file = await client.chat.upload_file(
    b"name,score\nAsha,91\n",
    filename="scores.csv",
)

run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Compare these files.",
    file_ids=[resume.id, csv_file.id],
)
reply = await run.result()
```

A plain string is rejected because it is ambiguous between a path and
file content. Use `Path(...)` for paths.

Download conversation files, including files produced by the agent:

``` python
from pathlib import Path

for file in reply.files:
    # Treat returned file names as untrusted; use only the final path segment.
    safe_name = Path(file.name).name
    content = await client.chat.download_file(file.id)
    Path(safe_name).write_bytes(content)
```

Documented constraints and cautions:

-   Maximum file size: 500 MiB (deployment-specific limits may be
    lower).
-   Uploads are sent to storage through a presigned URL; the API key is
    sent only to the Cominty API.
-   The API has no documented operation to list or delete uploaded
    files.
-   File bytes are held in memory in both directions.
-   Avoid logging full presigned URLs. The README specifically advises
    keeping the `httpx` logger at `WARNING` because `INFO` logging can
    expose full request URLs.

## 12. Exporting a message

`client.chat.export(message_id, format=...)` exports a completed message
as PDF or DOCX and returns bytes.

``` python
from pathlib import Path

run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Write a short product brief.",
)
message = await run.result()

pdf_bytes = await client.chat.export(message.id, format="pdf")
Path("brief.pdf").write_bytes(pdf_bytes)

docx_bytes = await client.chat.export(message.id, format="docx")
Path("brief.docx").write_bytes(docx_bytes)
```

Only `"pdf"` and `"docx"` are documented formats. The server does not
supply a filename; choose one when writing the bytes. Exporting a
message with no content (for example, one still running) raises
`APIError`.

## 13. Thread management

`client.threads` is automatically scoped to the `user_id` configured on
the client.

``` python
# List thread summaries (not full message histories).
threads = await client.threads.list(limit=20)
for thread in threads:
    print(thread.created_at, thread.name, thread.id)

# Free-text search.
matches = await client.threads.list(terms=["invoice"])

# Zero-based pagination.
page = await client.threads.list(limit=10, page=1)

# Load a thread and its full history.
thread = await client.threads.get(thread_id)
print(len(thread.messages))

# Partial update: only supplied fields are changed.
updated = await client.threads.update(
    thread_id,
    name="Recruitment conversation",
    starred=True,
)

# Archive is a soft delete.
await client.threads.archive(thread_id)
```

Persist the thread ID in your application if you need to resume a
conversation later. Do not assume a new `chat.start` call will resume an
existing thread; use `chat.send` with the existing thread ID.

## 14. Memory files

`client.memory` stores files an agent can read later. Files are scoped
to a namespace (a named memory bag). There is no separate
namespace-creation call; the first `create()` using a new namespace
creates the bag.

``` python
# Create.
file = await client.memory.create(
    path="tone.md",
    namespace="recruitment-demo",
    purpose="Recruitment communication style",
    content="Use concise, professional language.",
)

# List files in one namespace (returns summaries, not file contents).
files = await client.memory.list(namespace="recruitment-demo")

# List namespaces that already contain at least one file.
namespaces = await client.memory.list_namespaces()

# Read file contents.
file = await client.memory.get(
    "tone.md",
    namespace="recruitment-demo",
)

# Update. Version is an opaque concurrency token; round-trip it unchanged.
updated = await client.memory.update(
    "tone.md",
    namespace="recruitment-demo",
    version=file.version,
    content="Use concise, warm, professional language.",
)

# Delete.
await client.memory.delete(
    "tone.md",
    namespace="recruitment-demo",
)
```

Memory API constraints:

-   `namespace` may be at most 128 characters.
-   `path` may have at most one folder segment: `preferences/tone.md` is
    valid; `a/b/tone.md` is not.
-   `version` is opaque. Do not parse or compare it; pass back the last
    version received.
-   A stale version raises `ConflictError` (409).
-   There is currently no way to clear `content` or `purpose` once set;
    an explicit `null` does not clear the existing value.
-   Deleting an already-deleted path raises `NotFoundError`; delete is
    not idempotent.
-   `content` may be an empty string.

## 15. Cancelling a running message

`client.chat.cancel(message_id)` stops an assistant message that is
still being generated.

``` python
run = await client.chat.start(
    agent_id=AGENT_ID,
    message="Generate a long report.",
)

async with run:
    async for event in run:
        if should_stop():
            message = await client.chat.cancel(run.message_id)
            print(message.status)
            break
```

Cancellation is not idempotent. If the message already finished, failed,
or was cancelled, the API raises `APIError` (HTTP 400,
`"Message is not live"`). Treat this as a late cancellation. An unknown
message raises `NotFoundError`. Partial output produced before
cancellation remains in the event stream.

## 16. Error handling

All SDK exceptions inherit from `ComintyError`.

  -----------------------------------------------------------------------
  Exception                           Meaning
  ----------------------------------- -----------------------------------
  `ComintyError`                      Base class; catch-all

  `APIError`                          Any HTTP 4xx/5xx; exposes
                                      `status_code` and typed `error`
                                      body

  `AuthError`                         HTTP 401

  `PermissionError`                   HTTP 403

  `NotFoundError`                     HTTP 404

  `ConflictError`                     HTTP 409

  `RateLimitError`                    HTTP 429; exposes `reset_at`

  `ServerError`                       HTTP 5xx

  `APIConnectionError`                Network failure or timeout; no HTTP
                                      response

  `StreamInterrupted`                 Server shut down mid-stream;
                                      carries partial `Message`

  `InvalidParams`                     Local validation failure; `.errors`
                                      lists problems

  `SDKError`                          Unexpected SDK-internal condition
  -----------------------------------------------------------------------

Example:

``` python
from cominty_sdk import APIError, ComintyError, RateLimitError

try:
    run = await client.chat.start(agent_id=AGENT_ID, message="Hello")
    print(await run.text())
except RateLimitError as exc:
    print(f"Rate limited; retry after {exc.reset_at}")
except APIError as exc:
    print(f"API error {exc.status_code}: {exc.error}")
except ComintyError as exc:
    print(f"Cominty SDK error: {exc}")
```

Do not retry every exception blindly. In particular, distinguish local
validation errors, authorization failures, rate limits, conflicts,
network errors, and server errors.

## 17. Official examples in the repository

The repository contains runnable examples for:

  -----------------------------------------------------------------------
  Example                             Demonstrates
  ----------------------------------- -----------------------------------
  `01_stream_events.py`               Stream progress events

  `02_await_result.py`                Await a final result

  `03_follow_up.py`                   Continue an existing thread

  `04_answer_questions.py`            Read and answer agent questions

  `05_list_threads.py`                List and search threads

  `06_manage_thread.py`               Get, rename/star, and archive
                                      threads

  `07_custom_agent.py`                Call a custom managed agent

  `08_mcp_linear.py`                  Use an MCP server from an agent

  `10_max_steps.py`                   Cap tool rounds

  `11_capabilities.py`                Configure thread capabilities and
                                      message scopes

  `12_cancel_message.py`              Cancel a running message

  `13_export_message.py`              Export a response to PDF/DOCX

  `14_upload_files.py`                Upload, attach, and download files
  -----------------------------------------------------------------------

Repository examples:
https://github.com/cominty/python-sdk/tree/main/examples

## 18. Practical guidance for coding agents

When implementing against this SDK:

1.  Inspect the installed package version before coding. Do not assume
    the online README and installed version are identical.
2.  Prefer the SDK's typed objects and public methods over hand-written
    HTTP requests.
3.  Use `async with AsyncCominty()` for lifecycle management where
    practical.
4.  Persist `run.thread.id` in application storage when a later event
    must continue the same Cominty conversation.
5.  Use `chat.start` for a new thread and `chat.send(thread_id, ...)` to
    continue it.
6.  Set `thread_capabilities` when creating a thread; treat them as
    frozen for that thread.
7.  Use `message_scope` only to narrow or selectively enable
    capabilities already allowed by the thread.
8.  Do not confuse Cominty `user_id` with an external identity such as a
    Slack user ID. Maintain an explicit, trusted mapping in the
    application if external identity is needed.
9.  Do not treat MCP connection allowlists as a replacement for backend
    authorization.
10. Never log API keys, access tokens, or presigned file URLs.
11. Handle typed exceptions explicitly; avoid blind retries of
    non-transient failures.
12. If a method or field is not covered here, inspect the installed
    package's type hints/source and the matching repository version
    rather than inventing a signature.

## 19. Canonical references

-   PyPI package and maintainer README:
    https://pypi.org/project/cominty-sdk/
-   Source repository: https://github.com/cominty/python-sdk
-   Examples: https://github.com/cominty/python-sdk/tree/main/examples
-   Cominty platform: https://platform.cominty.ai/
-   Agents page: https://platform.cominty.ai/agents
-   API keys: https://platform.cominty.ai/api-keys

------------------------------------------------------------------------

End of offline reference.
