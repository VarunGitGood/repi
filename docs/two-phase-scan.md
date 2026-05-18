# Two-phase scan_window — design

## Why this exists

Production SREs investigate incidents in two stages:

1. **Scan for symptoms.** Find when things broke — ERROR/WARN bursts, latency spikes, 500s.
2. **Walk back for cause.** The thing that actually changed (migration, deploy, config reload, key rotation) almost always logs at **INFO** seconds before the first ERROR. INFO is filtered out of the symptom scan, so a separate walk-back is required.
3. **Cross-service correlation.** Symptom service is rarely the cause service. Once a cause candidate is in hand, correlate timestamps across services.

`repi` already does (1) well via `scan_window` and (3) okay via the multi-service summary that `scan_window` returns. (2) is the gap.

### Motivating bug — dataset 1, current failing trace

```
22:00:14 [INFO]  inventory-svc  Migration 0042 added column warehouse_id NOT NULL
22:00:47 [ERROR] inventory-svc  Failed to insert SKU sku_8821: null value in column "warehouse_id" violates not-null constraint
```

With `level=["ERROR","WARNING"]` (the `scan_window` default), the 22:00:14 line is invisible. The LLM, lacking the migration line in its evidence pool, cites the constraint-violation ERROR as `trigger_event`. The grader fails the run on `trigger_log_line` and `root_cause_content` checks (both demand "migration").

This is a structural problem, not a prompting one. The data the LLM needs is missing from the call result, so no amount of reasoning gets it there.

## What changes

### 1. `scan_window` returns a new `pre_context_logs` field

Signature gains `pre_context_seconds: int = 60` and `pre_context_per_service_limit: int = 20`. After computing per-service `first_error`, a second SQL pass (CTE) fetches the chunks in `[first_error - pre_context_seconds, first_error)`, with these filters:

- `log_level IS DISTINCT FROM 'ERROR'` — phase 1 already has these
- `log_level IS DISTINCT FROM 'DEBUG'` — too noisy to be useful
- per-service `ROW_NUMBER() OVER (ORDER BY timestamp_start DESC) <= N` — keep the N lines closest to the first ERROR, drop older ones

The filter is **level-agnostic** by design (Option C from the discussion in PR review). Triggering events don't follow a universal level convention — migrations log at INFO in some shops, NOTICE in others, CRITICAL/FATAL when a deploy fails. Filtering on `IN ('INFO','WARNING')` would miss CRITICAL key-rotation logs entirely. Time proximity is the load-bearing signal; level is not.

The result is exposed as `pre_context_logs` alongside the existing `logs`, with the same shape (chunk_id, service, level, timestamp, text).

The `TOOL_SCHEMAS["scan_window"]` description explains the two-phase intent so the LLM understands that `pre_context_logs` is where causes typically live, while `logs` is where symptoms appear.

### 2. `_extract_chunks` recurses into nested log lists

`ReactInvestigationLoop._extract_chunks` previously only inspected the top-level dict / list. `scan_window` returns `{ logs: [...], summary: {...}, total: N, window: [...] }` — the chunk-bearing entries are nested under `logs`, so zero chunks were ever persisted as evidence for `scan_window` callers. This is a latent bug that became visible once `pre_context_logs` was added.

Fix: walk every list-valued entry of the tool result and capture every dict with a `chunk_id`. Picks up `logs`, `pre_context_logs`, and any future nested chunk lists automatically.

## What we considered and rejected

- **Prompt rule 8 / structural validation in the answer schema.** Already tried (PR #30). Fails stochastically ~1 in 3 runs — when the data the LLM needs isn't in evidence, no prompt can recover it.
- **A new `explain_first_error` tool.** Would add an extra LLM round-trip and require the LLM to remember to call it. Two-phase-in-one-call avoids both costs.
- **Auto-sweep at the system-prompt level.** Surfaces irrelevant noise across the whole window; doesn't focus on pre-error context.
- **Changing `REFLECTION_INTERVAL`.** The failure mode wasn't "premature final_answer at step 2" — it was "evidence pool missing the cause line." Tuning reflection cadence wouldn't help.
- **Filtering pre_context to `IN ('INFO','WARNING')`.** Originally landed this way; replaced with "not ERROR, not DEBUG" because INFO/WARNING is a convention, not a guarantee. CRITICAL key-rotation logs and FATAL deploy-failure logs would have been invisible to the walk-back. Time proximity is the real signal — level filtering was a convenient cheat that broke on noise-heavy datasets.

## Out of scope

- Anomaly auto-detection
- Continuous monitoring
- Query-time hints / heuristics
- Changes to the prompt rules
- Web UI changes — `pre_context_logs` is on the wire via the existing SSE step event; rendering is a separate decision.
