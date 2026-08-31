# FatSecret MCP Server

An independent Python MCP server backed by the `fatsecret` package. It exposes
the supported FatSecret Platform API separately from experimental member-site
recipe and RDI operations.

This project has independent source code and Git history. Compatibility tool
names were transcribed from a pre-existing public tool list; no implementation,
schemas, configuration, tests, or architecture were copied from that project.

## Install

Run the current GitHub version with a fresh dependency resolution at each MCP
server start:

```bash
uvx --refresh --from git+https://github.com/ChocoTonic/fatsecret-mcp-server \
  fatsecret-mcp-server --profile default
```

`uvx --refresh` is the update mechanism. The running server does not rewrite
its own executable or dependency environment.

## Configure

Platform credentials:

```bash
export FATSECRET_CONSUMER_KEY=...
export FATSECRET_CONSUMER_SECRET=...
export FATSECRET_ACCESS_TOKEN=...       # required for user-scoped tools
export FATSECRET_ACCESS_SECRET=...
```

Member recipe and RDI credentials:

```bash
export FATSECRET_USERNAME=...
export FATSECRET_PASSWORD=...
```

Credentials may instead be stored in the operating-system keyring. Credential
tools are disabled unless `FATSECRET_MCP_ALLOW_CREDENTIAL_TOOLS=true` and should
only be exposed temporarily through the `bootstrap` profile.

Profiles are `default`, `member`, `discovery`, `diary`, `bootstrap`, and `full`.
The capability resolver is present in every profile. It can execute only an
explicitly reviewed read allowlist permitted by the active profile, without
advertising every backend schema. Resolved writes and authentication metadata
are blocked.

## Mutation contract

Every resource mutation requires an idempotency key. Reuse the same key after a
timeout; using it for a different payload is rejected. Recipe-copy resumes use
their durable operation ID as the idempotency identity. Ambiguous outcomes are
retained as unknown and must be reconciled before another write.

Durable state is namespaced by a one-way account identifier. Account writes are
serialized across server processes, and the state directory, database, and lock
files are restricted to the current operating-system user.

Recipe ingredients use a known FatSecret `food_id`. Omit `portion_id` for grams,
or first call `list_member_food_portions` to select an exact opaque portion ID.

Member recipe and RDI operations automate unsupported FatSecret website forms
and can break when that website changes.

See [architecture](docs/architecture.md) and the
[tool inventory](docs/tool-inventory.md).
