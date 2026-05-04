# Dataset 1 — Cascading Inventory Migration

## Story

Friday night, 2026-05-01. The ops team applied migration `0042_add_warehouse_id.sql` to `inventory-svc` at 22:00:14 UTC. The migration added a `warehouse_id NOT NULL` column to the `skus` table — but the SKU sync writer was not updated to populate it. Within 30 seconds, low-volume SKU writes started returning 500. `cart-svc` calls inventory-svc on every "add to cart" / "view cart" operation and retries 5x with exponential backoff on 5xx. The retry storm peaked at ~140 req/s against inventory-svc (baseline 12 req/s).

By 22:04:11 UTC, `cart-svc`'s HTTP client pool to inventory-svc was 100% exhausted. From that moment on, *all* cart operations — not just the SKU-sync ones — timed out waiting for an HTTP slot. Checkouts failed for ~30 minutes until ops rolled back the migration at 22:33:22 UTC and restarted the pool.

## Services

| Service           | Role                                    | Affected? |
|-------------------|-----------------------------------------|-----------|
| inventory-svc     | SKU/stock CRUD                          | trigger   |
| cart-svc          | Shopping cart, calls inventory + pricing| dominant symptom |
| pricing-svc       | Price lookup                            | red herring (in call path, no errors) |
| payment-svc       | Charges                                 | red herring (sees rate drop, no errors) |
| notification-svc  | Email/SMS                               | red herring (downstream, unaffected) |

## Why this is hard for a human (and the old loop)

- The trigger is buried in `inventory-svc` but the user types "checkout broke" → they name `cart-svc` (or no service at all).
- The trigger log line is **INFO level** (`Migration 0042 added column...`). Searching only on ERRORs misses it.
- The first errors (inventory 500s at 22:00:47) precede the dominant errors (cart timeouts at 22:04:15) by ~3.5 minutes — so a tight time window centered on user-visible failure misses the cause.
- `pricing-svc` is in the cart call path. A naive correlator will flag it. The investigation must rule it out by noting it has zero errors.
- `payment-svc` shows a *symptom* (checkout rate dropped) that looks like an error but is actually downstream evidence.

## Starter query

```
why did checkout break friday night
```

Vague on time ("friday night" — 8-hour window) and vague on service ("checkout" — feature, not registered service). The overhauled loop should ask one consolidated clarification and then proceed.

## Run

```bash
make migrate
poetry run python eval/dataset_1_cascading_inventory_migration/seed.py
# Then fire the query via /investigate and POST clarification reply via /investigations/{id}/clarify
```

## Expected outcome

See `expected.json`. Grading priorities:

1. **Trigger correctly attributed to inventory-svc migration**, not to cart-svc.
2. **Propagation chain in correct order** with timestamps.
3. **Red herrings ruled out** with stated rationale (not omitted).
4. **Time window assumption echoed** in `assumptions`.
