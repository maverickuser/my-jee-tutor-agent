# Repo Refactor Spec

Status: Draft

## Goal

Restructure the repository so each package has one responsibility, with stable public APIs during migration.

The target is a cleaner layout that follows convention-first project organization, similar in spirit to Apache-style source trees and Maven’s standard layout guidance:
- predictable package boundaries
- small modules with one reason to change
- compatibility shims during migration

## Design principles

- Single Responsibility Principle: one module, one reason to change.
- Layered boundaries: domain code must not depend on adapters.
- Stable public surface: keep compatibility imports until migration is complete.
- Convention over configuration: prefer a predictable layout over ad hoc file growth.
- Compatibility first: migrate implementation before removing legacy entry points.

## Target package layout

### `jee_tutor.request`

Owns incoming request handling.

Responsibilities:
- request payload models
- request validation
- request idempotency
- request orchestration entrypoint

### `jee_tutor.agent`

Owns diagnosis workflow behavior.

Responsibilities:
- diagnosis orchestration
- CrewAI coordination
- LLM/tool orchestration
- output assembly

### `jee_tutor.agent.domain`

Owns pure business logic.

Responsibilities:
- diagnosis data models
- output schemas
- output validation rules
- invariants and pure business rules

### `jee_tutor.agent.application`

Owns control flow.

Responsibilities:
- workflow coordination
- batching decisions
- completion and validation flow
- sequencing of the diagnosis steps

### `jee_tutor.agent.infrastructure`

Owns external adapters and wiring.

Responsibilities:
- LLM client adapters
- CrewAI wiring
- prompt loading
- rate limiting
- tool adapters

### `jee_tutor.artifacts`

Owns persistence of analysis outputs.

Responsibilities:
- PDF generation
- markdown persistence
- artifact writing

### `jee_tutor.email`

Owns email delivery.

Responsibilities:
- email config
- SES/Lambda delivery
- email worker

### `jee_tutor.config`

Owns configuration loading and resolution.

Responsibilities:
- config loading
- typed config objects
- env/config resolution

### `jee_tutor.utils`

Owns generic helpers only.

Responsibilities:
- reusable utility helpers
- no business logic
- no AWS, email, or JEE-specific behavior

## Source moves

The refactor should follow these moves conceptually:

- `invocation` becomes `request`
- mixed agent logic splits into `agent.domain`, `agent.application`, and `agent.infrastructure`
- config resolution helpers move into `config`
- generic helpers move into `utils`
- artifact persistence stays isolated in `artifacts`
- email delivery stays isolated in `email`

## Migration rules

1. Do not break public imports in the first pass.
2. Add compatibility re-exports before moving implementation.
3. Move behavior behind stable import surfaces.
4. Update tests incrementally with each slice.
5. Remove legacy shims only after all callers are migrated.

## Non-goals

- No behavior change in the first refactor pass.
- No prompt redesign as part of the package move.
- No evaluation logic rewrite.
- No infrastructure redesign unless needed for import stability.

## Success criteria

- Existing tests still pass during and after migration.
- Public imports continue to work through shims.
- No module mixes domain logic with AWS, CrewAI, or request parsing.
- `request`, `agent`, `artifacts`, `email`, `config`, and `utils` are clearly separated.

## Recommended migration order

1. Create target packages.
2. Add compatibility exports.
3. Move config and utils first.
4. Split agent domain/application/infrastructure.
5. Rename `invocation` to `request`.
6. Clean up shims and dead code.
7. Run full tests and update import paths.

## Reference direction

This spec intentionally follows a convention-first repository style, similar to Apache projects that favor predictable directory structure and minimal surprise for contributors.
