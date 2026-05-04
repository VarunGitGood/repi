# repi UI — Design Spec

**Date:** 2026-05-03  
**Status:** Approved

---

## Context

repi is a Python CLI + FastAPI backend for LLM-based log investigation. It has no frontend today. This spec defines a minimal, production-grade UI (Next.js 14 + shadcn/ui) with Vercel aesthetic and dark mode default.

**Goals:**
- Config page: edit all app settings (migrating from `.env` to `config.json`) + manage watchers
- Investigations page: trigger investigations and stream the full ReAct loop in real-time
- No auth (internal tool), deployed as a `web` service in docker compose

---

## Architecture

### Approach: Thin Next.js UI, browser calls FastAPI directly

- `web/` lives inside the monorepo
- Browser calls FastAPI (port 8000) for all data — no Next.js API routes
- SSE stream goes directly FastAPI → browser (no proxying)
- `NEXT_PUBLIC_API_URL=http://localhost:8000` (or `http://api:8000` within compose network)

### Frontend structure

```
web/
  app/
    layout.tsx                 # Root layout: ThemeProvider, nav
    config/page.tsx            # Config + watchers page
    investigations/
      page.tsx                 # Investigation list + new investigation
      [id]/page.tsx            # Single investigation (SSE consumer)
  components/
    ui/                        # shadcn/ui primitives
    investigation-step.tsx     # Step card: thought → tool → observation
    watcher-form.tsx           # Inline watcher add/edit row
    config-form.tsx            # Settings form with grouped sections
  lib/
    api.ts                     # Typed fetch wrappers
    sse.ts                     # useSSE hook
  next.config.ts
  tailwind.config.ts
  components.json
  package.json
```

### Backend additions

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/config` | Return parsed `config.json` |
| PUT | `/config` | Validate + write `config.json`, hot-reload Settings |
| GET | `/investigations` | List all investigations (id, query, status, created_at) |
| GET | `/investigations/{id}/stream` | SSE: replay from DB if done, stream live if running |

`POST /investigate` is decoupled to return `{investigation_id}` immediately (non-blocking).

### Config migration

- `config.json` at repo root replaces `.env`
- `repi/core/config.py` loads JSON first, env vars as fallback
- `Settings.reload()` re-reads `config.json` in place (hot-reload, no restart)
- DB URL changes warn in UI: "Requires restart to take effect"

### docker compose

New `web` service on port 3000, depends on `api`.

---

## Pages

### `/config` — Config + Watchers

Single form with grouped sections:

- **Database** — `DATABASE_URL` (restart warning on change)
- **LLM** — provider dropdown (openai/anthropic/mistral/gemini/ollama), model, API key (password input + reveal toggle)
- **Cache** — Redis URL, enable toggle, cache TTL, embedding TTL
- **Investigation** — TTL minutes, auto-delete toggle, delete-after days
- **Time Windows** — initial minutes, expansion sequence

**Watchers** section below settings:
- Table of `{path, service, enabled}` rows
- Inline add row, delete per row, enable/disable switch
- Calls existing `POST/PATCH/DELETE /watchers` endpoints

**Save Settings** button → `PUT /config` → toast on success/error

### `/investigations` — Investigations

**Left sidebar:**
- "New Investigation" button at top
- Scrollable list of past investigations: truncated query, relative timestamp, status badge (running / complete / failed)

**Main area — idle:** centered textarea + Run button

**Main area — detail view:**
- Query shown at top (muted badge)
- Steps animate in as SSE events arrive:
  - **Thought** — prose text
  - **Tool call** — collapsible block (tool name + args, collapsed by default)
  - **Observation** — syntax-highlighted JSON (collapsed by default)
- Pulsing dot on last step while running
- **Final answer** — rendered as markdown below a divider, appears on `done` event
- Error state: red banner with message

### Nav

Minimal top bar: "repi" logo + Investigations + Config links + theme toggle. Dark default via `next-themes`.

---

## Streaming Design

### SSE event shape

```json
{ "type": "step", "data": { "step_number": 1, "thought": "...", "action": { "tool": "search_logs", "input": {} }, "observation": {} } }
{ "type": "done", "data": { "answer": "..." } }
{ "type": "error", "data": { "message": "..." } }
```

### Backend (`GET /investigations/{id}/stream`)

- FastAPI `StreamingResponse` with `text/event-stream` content type
- If complete: emit stored steps from DB sequentially, then `done`, close
- If running: run ReAct loop with `on_step` callback emitting each step, emit `done` on finish
- Same UI path for both — no special cases in frontend

### Frontend `useSSE` hook

```ts
useSSE(url: string): {
  steps: Step[]
  answer: string | null
  error: string | null
  done: boolean
}
```

Opens `EventSource`, appends on `step`, sets answer on `done`, sets error on `error`. Closes on done or unmount.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Framework | Next.js 14 (App Router) |
| UI components | shadcn/ui |
| Styling | Tailwind CSS |
| Theme | next-themes (dark default) |
| Icons | lucide-react |
| Markdown | react-markdown |
| JSON highlight | react-syntax-highlighter |
| HTTP | native fetch (typed wrappers in `lib/api.ts`) |
| SSE | native EventSource |

---

## Implementation Steps

### Phase 1: Backend prep

1. **Migrate config to `config.json`**
   - Create `config.json` at repo root with all current Settings fields
   - Modify `repi/core/config.py` to load JSON first, env fallback
   - Add `reload()` method

2. **Add config endpoints** — `repi/api/config.py`
   - `GET /config`, `PUT /config` (validate schema, write, reload)

3. **Add investigations list** — `repi/api/investigate.py`
   - `GET /investigations`

4. **Add SSE endpoint** — `repi/api/investigate.py`
   - `GET /investigations/{id}/stream`
   - Decouple `POST /investigate` to return `investigation_id` immediately

### Phase 2: Next.js scaffold

5. Init `web/` with Next.js 14, shadcn/ui, next-themes, lucide-react, react-markdown
6. Root layout + top nav + theme provider (dark default)

### Phase 3: Config page

7. Config form with grouped sections, watchers table, save → `PUT /config`

### Phase 4: Investigations page

8. Sidebar + new investigation trigger → `POST /investigate` → navigate to `[id]`
9. Detail page with `useSSE`, step cards, final answer as markdown

### Phase 5: Docker + polish

10. `web/Dockerfile`, add `web` service to `docker-compose.yml`
11. Loading skeletons, empty states, error boundaries, `Cmd+Enter` to submit

---

## Critical Files

**Modify:**
- `repi/core/config.py` — JSON loader + reload()
- `repi/api/__init__.py` — register new routes
- `repi/api/investigate.py` — investigations list + SSE + decouple POST
- `docker-compose.yml` — add web service

**Create:**
- `repi/api/config.py` — config read/write endpoints
- `config.json` — full settings as JSON
- `web/` — entire Next.js app

---

## Verification

```bash
docker compose up

# Config
open http://localhost:3000/config
# → form loads with all settings, edit + save works, watchers add/delete/toggle

# Investigations
open http://localhost:3000/investigations
# → sidebar shows past investigations
# → submit query → steps stream in live
# → click completed investigation → steps replay instantly
# → final answer renders as markdown

# Backend tests unbroken
poetry run pytest tests/ -v
```
