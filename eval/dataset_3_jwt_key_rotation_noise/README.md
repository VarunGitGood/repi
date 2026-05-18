# Dataset 3 — JWT Key Rotation with Heavy Noise

## Story

Monday morning, 09:15:02 UTC. `auth-svc` ran its scheduled 90-day JWT key rotation and generated a new signing key (`k-2026-05`). The automated push of the new public key to `verification-svc` timed out silently — auth-svc logged only a WARNING. All new tokens are now signed with `k-2026-05`, but `verification-svc` still only knows `k-2025` and `k-2024`.

Within 28 seconds, `api-gateway` starts returning 401 Unauthorized to all authenticated requests. `billing-svc` sees checkout failures from 09:15:42 onward. The incident runs for ~30 minutes until an operator manually triggers the key sync at 09:45:02.

The twist: **auth-svc logs zero ERROR-level lines**. The rotation was "successful" from its perspective. The push failure is a single WARNING buried in dozens of INFO health-check and metrics lines. Meanwhile, `cache-svc` has a coincidental eviction spike at 09:14 and `user-svc` logs a one-off slow query at 09:15:10 — both appearing suspicious in the same window.

## Services

| Service           | Role                                         | Affected?           |
|-------------------|----------------------------------------------|---------------------|
| auth-svc          | Issues and rotates JWT signing keys          | trigger             |
| verification-svc  | Verifies JWT signatures for api-gateway      | propagation         |
| api-gateway       | Routes requests, enforces auth               | dominant symptom    |
| billing-svc       | Processes payments, calls api-gateway        | downstream symptom  |
| user-svc          | User profiles and sessions                   | red herring (slow query coincidence) |
| cache-svc         | In-memory caching layer                      | red herring (eviction spike coincidence) |

## Why this is hard

- **No ERROR in auth-svc**: the trigger is two INFO lines + one WARNING. An ERROR-only scan never finds it.
- **~70% noise**: health checks every 2 minutes per service, per-minute token/validation counters, metrics exports, and cache stats flood every service's log.
- **Two temporal red herrings**: `cache-svc` eviction spike starts at 09:14 (just before the incident) and `user-svc` has a slow query at 09:15:10 (exactly at onset). Both look suspicious but are causally unrelated.
- **Push failure is the crux**: rotation alone wouldn't have caused 401s if the push had succeeded. An investigation that mentions only "key rotation" without the push failure misses the mechanism.

## Starter query

```
why are users getting 401 errors this morning
```

"This morning" requires temporal grounding. The last Monday is the incident date.

## Run

```bash
make migrate
uv run python eval/dataset_3_jwt_key_rotation_noise/seed.py
# Then fire the query via /investigate
```

## Expected outcome

See `expected.json`. Grading priorities:

1. **Trigger correctly attributed to auth-svc key rotation + failed push**, not to api-gateway or billing-svc.
2. **Propagation chain**: auth-svc → verification-svc → api-gateway → billing-svc.
3. **Red herrings ruled out** with rationale (cache-svc eviction, user-svc slow query).
4. **Time window assumption echoed** in `assumptions`.
