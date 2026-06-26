# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Dealbot scrapes promotion offers from Telegram channels and surfaces them in a web app. Data flows one direction:

```
Telegram → Bot (Python, Telethon) → Supabase (Postgres + Storage) → API (Node/Express MVC) → Frontend (Next.js)
```

Supabase is the single shared datastore; the three services never call each other directly, they all read/write Supabase. The codebase (identifiers, comments, error strings) is in **Portuguese** — match it when editing.

## Three components, three directories

- `bot/` — Python capture worker. Listens to Telegram, extracts structured product data, applies filters, writes to Supabase.
- `backend/` — Express REST API (`/api/*`). Layered MVC, serves the frontend.
- `frontend/` — Next.js 14 App Router dashboard (login, product list, filter CRUD).
- `supabase/schema.sql` — run once in the Supabase SQL Editor to create tables, RLS policies, and the `produtos` storage bucket.

## Commands

```bash
# Backend (Node 20, see backend/.nvmrc) — serves on :3333
cd backend && npm install
npm start          # production
npm run dev        # node --watch (auto-reload)

# Frontend — http://localhost:3000, talks to NEXT_PUBLIC_API_URL
cd frontend && npm install
npm run dev
npm run build
npm run lint

# Bot
cd bot && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python gerar_sessao.py     # one-time: generates TG_SESSION_STRING
python -m src.main         # run the live worker
```

There are **no automated tests** and no linters beyond `next lint`.

## CRITICAL: two divergent bot implementations

The `bot/` directory contains two separate, non-equivalent entrypoints. Know which one you are touching:

- **`bot/src/` (current, active)** — modular: `config.py`, `db.py`, `extractor.py`, `filters.py`, `repository.py`, `main.py`. `extractor.py` is **pure regex/heuristics — no AI**. This is what `dealbot.service` (systemd) runs via `python -m src.main`, and the only path supported by `requirements.txt` (telethon, supabase, python-dotenv). **Live mode only.** The AI extractor was deliberately removed (commit "Remoção de filtro por IA").
- **`bot/bot.py` (legacy, dead)** — self-contained monolith using Gemini (`google.generativeai`, `gemini-1.5-flash`) for extraction, supporting both `live` and `polling` modes. It depends on `google-generativeai` and `requests`, which are **not in `requirements.txt`**, so it will not run as-is. This is the **only file still referencing AI** — the project no longer uses it. Treat as dead code; do not assume it reflects current behavior, and don't copy its Gemini/`MODO=polling` patterns into new code.

Docs (`README.md`, `.env.example`, `bot/.env.example`) have been scrubbed of Gemini/`MODO` references and now describe the regex-only `src/` worker. The `bot_state` table remains in `schema.sql` but is only used by the dead polling path in `bot.py`.

Also note: README diagrams show `frontend/src/app/...` and `backend` deployed to a VPS, but files actually live at `frontend/app|components|lib|hooks/` (no `src/`) and `backend/railway.toml` configures Railway (nixpacks) deployment. Trust the files over the README.

## Auth & the two-key Supabase model (get this right)

Two API keys with different trust levels — never swap them:

- **service_role key** — used by `bot/` and `backend` (`supabaseAdmin` client). Bypasses RLS, full read/write. Stays server-side only.
- **anon key** — used by `frontend` (login via Supabase Auth) and by `backend`'s `supabaseAuth` client, whose only job is validating user JWTs.

Request flow: frontend logs in via Supabase Auth → gets a JWT → sends `Authorization: Bearer <jwt>` on every API call (`frontend/lib/api.ts`) → backend `autenticar` middleware validates it with `supabaseAuth.auth.getUser(token)` → handlers then hit the DB through `supabaseAdmin`. Every `/api/*` route is behind `autenticar` except `/api/health` (see `backend/src/routes/index.js`).

## Backend layering

Strict one-way MVC — keep new code in the matching layer:

```
routes/ → controllers/ → services/ → models/ → Supabase
```

- `routes/` wire paths to controllers; auth is applied centrally in `routes/index.js`.
- `services/` hold business rules and **Zod** input validation (see `filtro.service.js`). Validation belongs here, not in controllers or models.
- `models/` are the only place that touches the Supabase client.
- Throw via the helpers in `utils/errors.js` (e.g. `NaoEncontrado`, `RequisicaoInvalida`, `NaoAutorizado`); `error.middleware.js` turns them into HTTP responses.

## Data model essentials (`supabase/schema.sql`)

- `produtos` — captured offers. Deduplicated by a unique index + upsert on `(canal_origem, telegram_msg_id)`, so re-processing the same Telegram message is idempotent.
- `filtros` — user-editable capture rules (`palavras_chave`, `palavras_bloqueio`, `categoria`, `preco_max`, `ativo`). The bot loads active filters per message; `passa_no_filtro` accepts a product if it passes **at least one** active filter (no filters = accept everything).
- `canais` — Telegram channels to monitor (only `ativo=true` are watched). Add channels here, not in code.
- `bot_state` — last processed message id per channel; only the legacy polling path uses it.
- Categories are a fixed set (`eletronicos, casa, moda, alimentos, beleza, games, outros`), defined both in `extractor.py` keyword maps and `frontend/lib/types.ts` `CATEGORIAS` — keep the two in sync.
