# repi evals

Hand-curated investigation scenarios for testing repi end-to-end. Each dataset is a self-contained world: a set of fictional services, raw log files, a seed script that ingests them, an expected outcome, and a starter query.

## Layout

```
eval/
├── dataset_1_cascading_inventory_migration/
│   ├── README.md          # Story, query, what makes it tricky
│   ├── seed.py            # Ingests logs/* via LogIngestor
│   ├── expected.json      # Expected investigation outcome
│   └── logs/              # Raw log files (one per service)
└── dataset_2_insufficient_logging/
    ├── README.md
    ├── seed.py
    ├── expected.json
    └── logs/
```

## Running a dataset

```bash
# 1. Make sure DB is up and migrations applied
make migrate

# 2. Seed
uv run python eval/dataset_1_cascading_inventory_migration/seed.py

# 3. Fire the starter query through the API (or web UI)
curl -X POST localhost:8000/investigate \
  -H "Content-Type: application/json" \
  -d "$(cat eval/dataset_1_cascading_inventory_migration/expected.json | jq '{query: .query}')"

# 4. Compare the result to expected.json (manually for now; harness TBD)
```

## What each dataset is for

- **dataset_1** — exercises temporal grounding (vague "friday night"), cross-service correlation (root cause buried in a service the user didn't name), and the structured answer schema (multi-hop propagation chain, ruled-out hypotheses for red-herring services).
- **dataset_2** — exercises honest gap-reporting. The data genuinely does not contain enough evidence to identify a root cause. A correct outcome is `confidence: low` with explicit `gaps` — not a fabricated root cause.

## Contributing new datasets

Keep them small (≤200 log lines per service), realistic, and unambiguously scored — `expected.json` should pin specific chunk_ids when possible (after seeding), or service+timestamp pairs that any correct answer must reference.
