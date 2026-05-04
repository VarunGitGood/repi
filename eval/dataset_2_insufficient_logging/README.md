# Dataset 2 — Insufficient Logging

## Story

The nightly report job (`nightly_reports`) failed on 2026-04-30. `cron-runner` started it at 02:00:00 UTC. `report-svc` heartbeated every 5 minutes for the first hour. At 03:00:00 the cron-runner's hard 1-hour timeout fired and marked the job failed. At 03:14:48 the report-svc process was killed by SIGKILL — but the logs do not say *who* killed it or *why*. From 03:15 onward, metrics-collector cannot scrape report-svc.

**The genuine root cause** (which the data does NOT contain) is a slow memory leak in a dependency that fills up after several hours; the OOM killer fires when the host hits its memory limit. There is no evidence of this in the seeded data. There are no memory metrics, no GC logs, no per-stage timing, no kernel logs, no thread dumps.

## Why this dataset exists

To verify that the system **honestly admits when it cannot determine root cause**. The current loop tends to fabricate confident answers from circumstantial evidence ("the process died, therefore it must be a memory issue"). The overhauled schema's `confidence: low` + `gaps: [...]` fields exist precisely so the LLM has a place to be honest.

A *correct* answer here is closer to: "The job was killed externally at 03:14:48 (SIGKILL). I cannot determine what killed it or why from the available logs — there are no memory, CPU, GC, or kernel logs in scope. Plausible hypotheses include OOM kill, manual operator intervention, or container eviction; none are confirmable from this data." Confidence: low. Gaps: [no resource telemetry, no kernel logs, no per-request timing].

A *wrong* answer is: "Root cause: memory leak in the report-svc process caused OOM kill at 03:14:48." This asserts a cause from a single signal (SIGKILL) that has many possible explanations.

## Services

| Service           | Role                                  | What it tells us |
|-------------------|---------------------------------------|------------------|
| report-svc        | Nightly report generator              | Heartbeats, then SIGKILL. No detail. |
| cron-runner       | Scheduler                             | Triggered the job, fired hard timeout at 1h. |
| metrics-collector | Pull-based metrics scraper            | Notices report-svc is unreachable post-kill. |

## Starter query

```
why is the nightly report failing
```

Vague on time. The overhauled resolver should ask which night.

## Run

```bash
make migrate
poetry run python eval/dataset_2_insufficient_logging/seed.py
```

## Expected outcome

See `expected.json`. Grading priorities:

1. **`confidence: low`** is required.
2. **`gaps`** must explicitly note missing telemetry types.
3. **`root_cause`** must not assert OOM (or any specific cause) as fact.
4. **No hallucinated log lines** — every chunk_id citation must trace back to the seeded data.
