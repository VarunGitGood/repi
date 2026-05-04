# ReAct Loop Overhaul — Design

**Date:** 2026-05-04
**Status:** Draft, pending implementation plan
**Author:** brainstorming session

## Problem

The current ReAct investigation loop has three observable failure modes:

1. **Temporal grounding is brittle.** `extract_time_range` (`repi/retrieval/heuristics.py:57`) only handles `since HH:MM` and `last N hours`. Phrases like "Friday night", "around the deploy", "this weekend" silently fall through, the investigation runs unbounded, and results devolve into noise. The pre-investigation block in `react_loop.py:202-223` only fires *when a time hint exists* — exactly the case where it is least needed.
2. **Cross-service correlation is blind.** `find_co_occurring` (`repi/investigation/tools.py:103`) only joins `chunk_id`s the LLM has already retrieved. If the LLM never thought to search `db-svc`, it never learns that `db-svc` errored 8 seconds before `auth-svc`. Cross-service discovery is capped by the LLM's recall, not by what is actually in the data.
3. **Generic answers.** The system prompt has four vague rules and the answer schema is `{summary, root_cause, evidence, confidence}` — nothing forces specific timestamps, citations, or a propagation chain. A reasonably skilled developer can match the depth of the output by reading logs directly, defeating the tool's value.

Two compounding issues:

- `parse_intent` (`repi/intent/basic_parser.py`) is invoked at the CLI but its output is never threaded into the loop, so the resolver work it does is wasted.
- There is no clarification path. The loop never asks the user "which Friday?" and never states an assumption — it just guesses or fails quietly.

## Goals

- Resolve temporal context up front, with a single user-facing clarification round when needed.
- Surface cross-service activity automatically before the LLM reasons, and expose it as a tool for re-querying.
- Force the final answer to a structured shape that cannot be filled with hand-waving.
- Preserve audit/replay correctness — every step (including clarifications) lives in `investigation_steps`.

## Non-goals

- Anomaly detection beyond "ERROR/WARNING counts in a time window". No statistical baselines, no ML.
- Auto-learning aliases from past queries. Out of scope until real query volume justifies it.
- Multi-round clarification. One round only; if still ambiguous, commit with widest-defaults and `confidence: low`.
- Replacing the LLM provider abstraction or model. Same provider, same model for the optional resolver fallback call.

## High-level flow

```
query → intent_resolver → ambiguous? ──yes──> ask_user step (status=awaiting_clarification)
                              │                        │
                             no                  user replies via /clarify
                              │                        │
                              └──────anchor────────────┘
                                        │
                                auto cross-service sweep
                                        │
                                ReAct loop (tools available)
                                        │
                                structured final answer (schema-validated)
```

## Component design

### 1. `intent_resolver` — clarify-first gatekeeper

**File:** `repi/intent/resolver.py` (new). Replaces `repi/intent/basic_parser.py` and absorbs `extract_time_range`.

**Entry point:**

```python
def resolve(query: str, known_services: list[str], now: datetime) -> ResolvedIntent | ClarificationNeeded
```

**Hybrid pipeline:**

1. **Rule pass.** Upgraded patterns:
   - **Time:** existing `last N {min,h,days}`, `today`, `yesterday`, `since HH:MM` — plus weekday names (`monday`, `last friday`), parts-of-day windows (`morning`=06–12, `afternoon`=12–18, `evening`=18–22, `night`=22–06 next day), `this {weekend,week}`, `around HH:MM`, `between HH:MM and HH:MM`. Weekday + part-of-day combine ("Friday night" → last Friday 22:00 → Saturday 06:00). Anchored to user-local timezone via `USER_TIMEZONE` env var (default `UTC`).
   - **Service:** exact substring match against `known_services`. Fuzzy match (Levenshtein ≥ 0.8) against canonical names. No alias table in v1.
   - **Symptom:** keyword extraction against fixed vocabulary (`5xx`, `latency`, `oom`, `timeout`, `auth_reject`, `crash`, `restart`, …). If query has none and verb is vague (`fail`, `break`, `weird`, `wrong`, `down`), mark symptom as ambiguous.

2. **Ambiguity check.** Returns `ClarificationNeeded` if any of:
   - No time AND no symptom anchor (pure "why is X broken").
   - Time phrase present but unparseable by rules ("last deploy", "around the spike").
   - Service named but not in `known_services` and no fuzzy match ≥ 0.85.
   - Multiple plausible weekdays (e.g. just "Friday" with no "last/this").

3. **LLM fallback.** Fires only if rules produced `ClarificationNeeded` *and* the templated question would be too generic. One call, same provider as main loop, small prompt:
   ```
   Input:  {query, known_services, now_utc, what_rules_couldnt_parse}
   Output: {ok: bool, parsed?: ResolvedIntent, question?: str}
   ```
   Most queries never hit this path.

4. **Output:**
   - `ResolvedIntent(time_from, time_to, services, symptoms, assumed: list[str])` — `assumed` records inferred values ("assumed 'Friday night' = 2026-05-02 22:00–2026-05-03 06:00 UTC") so the final answer can echo them back.
   - OR `ClarificationNeeded(question: str, missing_dims: list[str])` — single consolidated question covering all ambiguous dimensions.

**Single-round guarantee.** When the user's reply comes back via `/clarify`, the resolver runs once more on `original_query + " " + clarification_reply` (naive concat). If still ambiguous, commit anyway: log a warning, fill missing dims with widest-reasonable defaults, tag the final answer's `confidence: low` with `gaps: [...]`.

**Service discovery.** Resolver pulls `known_services` from the live database (`watcher_config` table, falling back to `log_chunks` if needed) on each call. The current `known_services` parameter threaded through `react_loop.investigate()` is removed.

### 2. `ask_user` as a ReAct step + `/clarify` endpoint

The clarification round piggybacks on existing step machinery.

**Schema changes:**

- `investigations.status` adds value: `awaiting_clarification`.
- New column: `investigations.pending_question text null` (only set while status is `awaiting_clarification`).
- The question and the user's reply are stored as a normal `investigation_step` row with `action.tool_name = "ask_user"` and `observation.result = {"reply": "..."}`. No parallel tables.

**Loop behavior:**

1. `loop.investigate(query)` calls `intent_resolver.resolve(query, known_services, now)`.
2. If `ResolvedIntent` → continue normally (auto-sweep → ReAct).
3. If `ClarificationNeeded(question)`:
   - Persist a step with `thought = "I need to clarify before I can investigate"`, `action = {"tool": "ask_user", "args": {"question": question}}`, no observation.
   - Set `investigations.status = "awaiting_clarification"`, `pending_question = question`.
   - Return immediately. SSE stream emits the step (frontend renders as a question prompt) then a `paused` sentinel.

**New API endpoint:**

`POST /investigations/{id}/clarify`, body `{reply: string}`:

- Validates `status == "awaiting_clarification"` (else 409 Conflict).
- Writes the user's reply as the `observation` on the pending `ask_user` step.
- Sets `status = "running"`, clears `pending_question`.
- Re-runs `intent_resolver.resolve(original_query + " " + reply)` — single round. If still ambiguous, commits with widest-defaults + `confidence: low`.
- Triggers loop continuation (auto-sweep → ReAct). Frontend reconnects to the existing SSE stream.

**Concurrency:** if a user fires `POST /investigate` with a new query while another investigation is `awaiting_clarification`, it just creates a separate investigation. No global lock.

**Frontend:**

- When SSE delivers a step where `action.tool == "ask_user"`, render the question + an input box instead of a normal step card.
- On submit, POST to `/clarify` and reconnect to SSE.
- No long-held SSE connections during user think-time — the stream closes at the `ask_user` step and reopens after `/clarify`.

### 3. Auto cross-service sweep + `sweep_window` tool

**File:** `repi/investigation/sweep.py` (new). Replaces the existing pre-investigation block in `react_loop.py:202-223`.

**Auto-sweep** runs after intent resolution succeeds, before the LLM gets its first turn.

- Input: `time_from`, `time_to`, optional `services`.
- Single SQL against `log_chunks`:
  ```sql
  SELECT chunk_id, source_service, log_level, timestamp_start, text
  FROM log_chunks
  WHERE timestamp_start BETWEEN $1 AND $2
    AND log_level IN ('ERROR', 'WARNING')
  ORDER BY timestamp_start
  LIMIT 50
  ```
- Bucket by service; compute per-service error/warning counts and earliest error timestamp.
- Returns a compact summary, not raw logs:
  ```json
  {
    "window": ["2026-05-02T22:00Z", "2026-05-03T06:00Z"],
    "services_with_errors": [
      {"service": "auth-svc", "errors": 14, "warnings": 3, "first_error": "22:14:07Z"},
      {"service": "db-svc", "errors": 2, "warnings": 0, "first_error": "22:13:59Z"}
    ],
    "ordered_first_errors": ["db-svc@22:13:59", "auth-svc@22:14:07"]
  }
  ```
- This goes into the message stream as `SWEEP CONTEXT:` before the user query — facts, not a hint.
- The chunk_ids surfaced by the sweep are persisted as evidence (existing `add_chunks` path). Full log text is not included; the LLM can call `search_logs` or `get_timeline` if it wants the lines.
- Sweep limit is a flat top-50. Tier-by-service is deferred until truncation is shown to hide important services in real usage.

**Empty sweep** (no errors in window) still proceeds to ReAct; sweep context becomes `{"window": [...], "services_with_errors": []}` so the LLM knows the window had no signal.

**`sweep_window` tool.** Same logic, exposed as an LLM-callable tool so the model can re-run at a tighter window once it narrows the anchor:

```
sweep_window(time_from: ISO, time_to: ISO, exclude_services?: list[str]) → same shape as auto-sweep
```

`find_co_occurring` stays. Sweep tells you "what services were noisy in this window"; co-occurring tells you "of these specific chunks, which paired up across services within N seconds".

### 4. Structured answer schema + validation

**File:** `repi/investigation/schema.py` (new). Pydantic model + validator.

Replaces today's loose `{summary, root_cause, evidence, confidence}`.

```json
{
  "incident_window": {"start": "ISO8601", "end": "ISO8601"},
  "affected_services": ["auth-svc", "db-svc"],
  "trigger_event": {
    "chunk_id": "uuid",
    "service": "db-svc",
    "timestamp": "ISO8601",
    "log_line": "verbatim text"
  },
  "propagation_chain": [
    {"service": "db-svc", "chunk_id": "...", "ts": "22:13:59Z", "what": "connection pool exhausted"},
    {"service": "auth-svc", "chunk_id": "...", "ts": "22:14:07Z", "what": "session lookup timed out"}
  ],
  "root_cause": "one-sentence verdict",
  "ruled_out_hypotheses": [
    {"hypothesis": "deploy at 22:00 caused it", "why_ruled_out": "no deploy logs in window; first error precedes any deploy marker"}
  ],
  "assumptions": ["assumed 'Friday night' = 2026-05-02 22:00–06:00 UTC"],
  "confidence": "high | medium | low",
  "gaps": ["empty if confidence=high"]
}
```

**Field rationale (anti-genericness):**

- `trigger_event` with chunk_id + verbatim line → can't hand-wave.
- `propagation_chain` ordered by timestamp, chunk_id per hop → forces a real sequence, not "auth and db both errored".
- `ruled_out_hypotheses` → must enumerate alternatives and dismiss them with evidence. Captures dev judgment.
- `assumptions` echoes resolver inferences so the user can correct them.
- `gaps` lets the model honestly admit missing data instead of inventing.

**System prompt overhaul.** The current 4-rule prompt is replaced with: filled-in good-answer example, rejected bad-answer example with reasons, sweep context format, the `assumptions` echo requirement, and a hard rule — *every* string field referencing a service event MUST cite a chunk_id from the evidence pool.

**Validation gate.** Before returning, the loop validates the final JSON against the schema. Reject and retry once if any of:

- `trigger_event.chunk_id` is not in the evidence pool.
- `propagation_chain` is empty when `affected_services` has 2+ entries.
- `ruled_out_hypotheses` is empty when `confidence != "high"`.
- Any `chunk_id` referenced anywhere is not in the evidence pool.

On retry, the LLM gets the validation error as feedback. After one retry, accept what it produced and downgrade `confidence` to `low` with the validation error appended to `gaps`.

### 5. Frontend service autocomplete (additive)

- New endpoint `GET /services` returns `[{name, env, enabled}, ...]` from `watcher_config`.
- Web query input gets a chip-style picker — typing triggers a dropdown of matching service names; selecting inserts the canonical name.
- Resolver behavior unchanged: any exact canonical-name match in the query is treated as resolved. No special "from autocomplete" flag.

## Error handling

- LLM resolver call fails → fall back to widest-defaults + `confidence: low`.
- Sweep query returns empty → proceed to ReAct with empty sweep context.
- `/clarify` called when status is not `awaiting_clarification` → 409 Conflict.
- Schema validation fails twice → return the LLM's last attempt with `confidence: low`, validation error in `gaps`.
- Tool call from the LLM with unknown tool name → existing behavior preserved (observation contains error string).

## Testing

- `tests/intent/test_resolver.py` — table-driven. Cases: each time pattern, each ambiguity trigger, each clarification path (rule-resolvable, LLM-fallback, post-clarification commit-with-defaults). LLM mocked.
- `tests/investigation/test_clarification_flow.py` — end-to-end of the `ask_user` step + `/clarify` endpoint. Status transitions, single-round commit, replay correctness. DB and LLM mocked.
- `tests/investigation/test_sweep.py` — auto-sweep against a seeded test DB. Bucketing, ordered_first_errors, chunk_id persistence into evidence.
- `tests/investigation/test_schema_validation.py` — schema validator. Missing chunk_id, empty propagation_chain with 2+ services, empty ruled_out with high confidence. Verifies retry-once-then-downgrade.
- `tests/investigation/test_react_loop.py` — existing tests updated. Add: resolver-resolved → no clarification step. Resolver-ambiguous → ask_user step then pause.

## File-level changes

| File | Change |
|---|---|
| `repi/intent/basic_parser.py` | Delete. |
| `repi/intent/resolver.py` | New. Hybrid rules + LLM fallback. Returns `ResolvedIntent \| ClarificationNeeded`. |
| `repi/retrieval/heuristics.py` | Remove `extract_time_range` (absorbed into resolver). Keep `cluster_logs`. Verify `progressive_search` is unused after sweep replaces it; delete if so. |
| `repi/investigation/sweep.py` | New. `auto_sweep(pool, time_from, time_to) → dict`. Used as pre-step and as the `sweep_window` tool. |
| `repi/investigation/tools.py` | Add `sweep_window` (thin wrapper around sweep.py). Add to `TOOL_SCHEMAS`. Keep `find_co_occurring`. |
| `repi/investigation/react_loop.py` | Rewrite top of `investigate()`: resolver call → ask_user-or-sweep branch. New system prompt. Remove existing pre-investigation block. Add schema validator + retry logic before final answer. |
| `repi/investigation/schema.py` | New. Pydantic model for the structured answer + validator. |
| `repi/investigation/store.py` | Persist/read `pending_question`. Methods `set_awaiting_clarification`, `resume_from_clarification`. |
| `repi/models/schema.py` | Add `pending_question text null`. Extend status with `awaiting_clarification`. |
| `db/migrations/002_clarification.sql` | New migration. |
| `repi/api/investigate.py` | New `POST /investigations/{id}/clarify` endpoint. SSE handler updated to gracefully end on `ask_user` step. |
| `repi/api/services.py` | New. `GET /services` for frontend autocomplete. |
| `repi/core/container.py` | Wire new resolver, sweep, schema validator. Remove `known_services` plumbing. |
| `repi/core/config.py` | Add `USER_TIMEZONE` setting (default `UTC`). |
| Web frontend | (i) Service autocomplete in query input, (ii) render `ask_user` step as input form, (iii) POST to `/clarify`, (iv) reconnect SSE. |
| `tests/intent/test_resolver.py` | New. |
| `tests/investigation/test_clarification_flow.py`, `test_sweep.py`, `test_schema_validation.py` | New. |
| `tests/investigation/test_react_loop.py` | Update for new flow. |
| `CLAUDE.md` | Remove `cli.py` reference; add resolver + sweep + ask_user to architecture section. |

## Recommended phasing

The total scope is realistically 4-5 PRs, not one. Suggested order — earlier phases deliver value even without later ones:

1. **Phase 1 — Schema + sweep.** Structured answer schema + validator + system prompt overhaul + auto-sweep + `sweep_window` tool. Improves answer quality and cross-service correlation immediately, with no API or frontend changes.
2. **Phase 2 — Resolver (no clarification).** New `intent_resolver` returning `ResolvedIntent` only (treat ambiguous cases as widest-defaults + `confidence: low`). Wire into the loop. Removes `basic_parser` and `extract_time_range`. No clarification round yet, but temporal grounding is already much better.
3. **Phase 3 — Clarification flow.** Add `ClarificationNeeded` return + `ask_user` step + `/clarify` endpoint + status migration + frontend question rendering.
4. **Phase 4 — Service autocomplete.** `GET /services` + frontend chip picker.
5. **Phase 5 — LLM fallback in resolver.** Only if Phase 2's rule-only behavior is shown insufficient on real queries.

## Open questions

None at design time. All decisions captured above.
