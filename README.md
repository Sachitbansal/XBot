# XBot — X content radar + draft generator

Personal pipeline: fetch (HN, arXiv, GitHub trending, RSS, X-via-search) → dedupe → LLM score →
draft posts only for items clearing `config.THRESHOLD` → Telegram approve/edit/reject → every
decision logged to Postgres.

## Setup (dev)

```bash
cp .env.example .env            # fill in keys
docker compose up -d            # Postgres on localhost:5440, schema auto-applied on first start
python3 -m venv venv && venv/bin/pip install -r requirements.txt
mkdir -p logs
```

Existing DB? Apply schema manually (idempotent): `psql "$DATABASE_URL" -f schema.sql`

## Run

```bash
venv/bin/python run_cycle.py     # one cycle (cron runs this hourly)
venv/bin/python telegram_bot.py  # long-running bot; send /start to get your chat id
```

## Tests

```bash
docker exec xbot-postgres psql -U xbot -c 'CREATE DATABASE xbot_test'
docker exec -i xbot-postgres psql -U xbot -d xbot_test < schema.sql
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 venv/bin/python -m pytest
```

## Deploy (server)

- Point `DATABASE_URL` at the server Postgres, run `schema.sql` once.
- Cron line: `deploy/crontab.txt`. Bot service: `deploy/xbot-telegram.service` (adjust paths).

## Layout

| file | role |
|---|---|
| `config.py` | every tunable: threshold, models, weights, sources, queries, angles |
| `llm.py` | only place that calls OpenRouter (scoring + generation modes, fallback models, retries) |
| `db.py` | raw-SQL helpers per table |
| `fetchers/` | one module per source, each `fetch() -> list[RawItem dict]` |
| `pipeline/` | `dedupe` → `score` → `generate` → `send`, plus `decide` (approve/edit/reject logging) |
| `run_cycle.py` | one cycle; advisory-locked so overlapping cron runs exit early |
| `telegram_bot.py` | button + edit-reply handling → `decisions` / `edit_pairs` |

## Models

Testing on free OpenRouter models (`config.SCORING_MODELS` / `GENERATION_MODELS`, fallback lists —
free tier 429s a lot). Switch both to `["qwen/qwen-2.5-72b-instruct"]` for real use.
