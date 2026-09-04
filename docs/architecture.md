# Architecture

## Clean-room boundary

This repository has independent Git history and implementation. The only
material transcribed from the reference MCP project is its public list of 13
compatibility tool names. Member tool names come from the requested workflows.

Implementation behavior is derived from the public `fatsecret` Python package,
its generated Platform OpenAPI contract, its separately maintained member-web
OpenAPI contract, and the official MCP Python SDK.

## Sources of truth

- FatSecret Platform OAS: supported HTTP operations and payload models.
- FatSecret member-web OAS: experimental recipe, diary, and RDI HTTP semantics.
- `fatsecret` Python API: retries, authentication, parsing, and verification.
- `catalog.py`: MCP naming, profiles, mutation classification, and exposure.
- Typed functions in `tools.py`: MCP input schemas and handler descriptions.

OAS generation cannot decide MCP exposure. An HTTP operation may be unsuitable
for model invocation, may require reconciliation, or may have a schema too large
to advertise in the default profile.

## Execution

The MCP layer uses the official MCP 2.x Python SDK. Blocking `fatsecret` calls
run in worker threads. Official Platform and unsupported member-site clients
remain separate providers.

Mutations use an account-namespaced durable SQLite request journal and an
account-scoped interprocess file lease. Recipe copies use the backend's
checkpointed copy service and bind operation IDs to the originating account.
Official user mutations require a stable configured account ID; rotating OAuth
tokens therefore cannot change idempotency or locking namespaces. Each mutation
binds one credential snapshot for its complete execution.
FatSecret-provided `Retry-After` deadlines are authoritative and are not
shortened by a local request budget.

## Discovery and observability

The resolver inspects public versioned Platform resource methods, combines them
with an explicit reviewed member-web method list, and retains the highest
numeric Platform version for each operation family. Discovery does not imply
authorization: execution is limited to a static reviewed read allowlist and the
active profile. Authentication metadata is excluded. Writes must use reviewed,
typed tools.

Advertisement and runtime compatibility are separate. Food tools try reviewed
versions newest-first and fall back only when FatSecret returns error 10 for an
unknown method. The accepted method is cached for the server process; a restart
rechecks the newest version. Other upstream failures are not masked.

SQLite telemetry stores tool name, category, inferred goal class, outcome,
duration, resolver reach, and selected capability names. It does not store tool
arguments, results, credentials, recipe content, or food content.
