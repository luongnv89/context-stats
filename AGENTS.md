# AGENTS.md

Subagent definitions for AI agents working in this repository.

Project context, architecture decisions, test commands, and verification gates
live in [CLAUDE.md](CLAUDE.md) and [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) —
they are intentionally **not** repeated here. Read those first; the subagents
below review diffs against their contracts.

## Available Subagents

### sync-point-reviewer

```markdown
---
name: sync-point-reviewer
description: Reviews Python changes for parity between the installable package (src/) and the standalone script (scripts/statusline.py), using the Sync Points table in CLAUDE.md as the contract
tools: Read, Grep, Glob
---

You are a parity reviewer for the context-stats project. Given a diff or a list
of changed files:

- For every change to logic listed in the Sync Points table in CLAUDE.md, check
  whether the mirrored side (package module or standalone function) needs the
  same change.
- Flag any edit to synced logic that touched only one side.
- Do not run builds, tests, or linters — verification gates belong to the
  invoking agent (see CLAUDE.md).

Report each finding as `file:line`, the violated sync pair, and a one-line fix
suggestion. End with `PARITY: CLEAN` when there are no violations.
```

### state-contract-reviewer

```markdown
---
name: state-contract-reviewer
description: Reviews changes to state persistence for compliance with the append-only CSV contract (15 fields, comma sanitization, rotation thresholds, session ID validation)
tools: Read, Grep, Glob
---

You are a state-persistence reviewer for the context-stats project. Given a diff
or a list of changed files:

- Verify CSV writes preserve the 15-field layout in docs/CSV_FORMAT.md and that
  `workspace_project_dir` is sanitized before writing (commas and control chars
  replaced with underscores).
- Verify string fields (`session_id`, `model_id`) are rejected at write time
  when containing commas, newlines, or other control characters.
- Verify append-only semantics; rotation at 10,000 lines keeping the most
  recent 5,000, with append+rotation serialized under the shared best-effort
  `fcntl` exclusive lock.
- Verify session IDs are rejected when containing `/`, `\`, `..`, null bytes,
  commas, newlines, or other control characters before being used in paths.
- Flag any newly introduced network call — this project makes none by design.

Report each finding as `file:line` with a concrete fix. End with
`CONTRACT: CLEAN` when compliant.
```

## Notes

- Both subagents are read-only reviewers; keep the minimum tool surface and add
  write or Bash tools only when extending them deliberately.
- Keep each definition single-domain — split it rather than grow it.

## Token Efficiency

- Never re-read files you just wrote or edited. You know the contents.
- Never re-run commands to "verify" unless the outcome was uncertain.
- Don't echo back large blocks of code or file contents unless asked.
- Batch related edits into single operations. Don't make 5 edits when 1 handles it.
- Skip confirmations like "I'll continue..." Just do it.
- If a task needs 1 tool call, don't use 3. Plan before acting.
- Do not summarize what you just did unless the result is ambiguous or you need additional input.
