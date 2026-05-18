# Dataset 3 regression — follow-up

## What

Dataset 3 (`dataset_3_jwt_key_rotation_noise`) went from **2 bugs → 10 bugs**
after the reflection + ledger + two-phase-scan changes landed on
`feat/reflection-and-two-phase-scan`.

- Baseline (in `bug_baseline.json`): 2 medium bugs
  - `root_cause_content` missing `k-2026-05`
  - `propagation_chain_coverage` missing `api-gateway`
- Current run on this branch: 10 bugs (1 high, 9 medium)

Datasets 1 and 2 did not regress:
- Dataset 1: 4 bugs → 0 bugs (the fix worked as designed)
- Dataset 2: 1 bug → 1 bug (same `confidence_must_be_low` bug, no change)

## Observed LLM output (current run)

```
trigger_event.service     : "postgres"
trigger_event.log_line    : "No logs found; hypothesized Postgres authentication/connection failure."
root_cause                : "Postgres authentication or connection failures likely caused
                             `auth-svc` to reject user sessions, resulting in 401 errors.
                             No logs were found to confirm the exact mechanism."
propagation_chain[0].ts   : "2026-05-11T06:00:00"   ← off by ~3 hours from the real rotation
propagation_chain[0].chunk_id : "N/A"               ← LLM never collected evidence
```

The investigation collapsed to "no logs found" + hypothesis. The actual JWT
rotation event is seeded at ~09:15:02 on 2026-05-11; the LLM's chain timestamp
of 06:00 suggests it scanned the wrong sub-window and gave up.

## Likely causes — to investigate

1. **Reflection prompt over-persuasive.** `REFLECTION_PROMPT` ends with
   *"Should you give up and submit with low confidence instead? If yes, do so
   now."* On noisy datasets (dataset 3 is intentionally noisy — cache-svc /
   user-svc red herrings) the LLM may take this as a hint to bail after the
   first weak scan. Worth A/B testing without that line.
2. **Iteration budget**: `max_iterations=10` minus one reflection at step 4 +
   one at step 7 leaves ~8 action steps. With 7 known services and progressive
   time-window expansion, that may be too few. Consider bumping for noise
   datasets or making the reflection count toward a separate budget.
3. **Ledger summary cluttering system prompt.** The `TOOLS ALREADY CALLED:`
   block on every iteration may push the LLM away from useful repeat
   variations (e.g. same query, different service). Verify it's not
   discouraging legitimate broadening.
4. **Time-window resolution** picked `06:00` not `09:00`. "Last Monday morning"
   is ambiguous — could be a separate intent-resolver issue unrelated to this
   branch.

## Next steps (when picking this up)

- Run `uv run python eval/run_evals.py --dataset dataset_3 --no-reflection`
  to isolate whether reflection is the cause. If it now passes, the prompt is
  too pessimistic.
- If reflection isn't it, try setting `REPI_ENABLE_REFLECTION=true` but
  bumping `max_iterations` to 15 to rule out budget exhaustion.
- Inspect a trace via the web UI on the investigation ID written to
  `investigations` table after the failing run.
