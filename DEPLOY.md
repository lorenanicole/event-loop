# Deploying EventLoop on Railway

Two services share one Railway Postgres database:

| Service | Dockerfile | Purpose |
|---|---|---|
| `api` | `backend/Dockerfile` | FastAPI + PydanticAI chat backend (Python 3.15) |
| `scraper` | `backend/Dockerfile.scraper` | Playwright venue scraper cron (Python 3.14, Playwright 1.63) |

---

## One-time setup

### 1. Install the Railway CLI

```bash
brew install railway
railway login
```

### 2. Create the project and link it

```bash
railway init        # creates a new Railway project
railway link        # link this directory to that project
```

Or skip the CLI: **New Project → Deploy from GitHub repo → select `lorenanicole/event-loop`**

---

## Add a Postgres database

1. In the Railway dashboard: **+ Add → Database → PostgreSQL**
2. Railway creates a Postgres service and exposes `${{Postgres.DATABASE_URL}}`

---

## Create the API service

1. **+ Add → GitHub Repo** → pick this repo
2. Service name: `api`
3. **Settings → Source → Root Directory**: `backend`
4. **Settings → Variables** — add:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ADMIN_KEY=something-secret
   SERPAPI_KEY=...
   TICKETMASTER_API_KEY=...
   LOG_LEVEL=INFO
   ```
5. **Settings → Networking → Generate Domain** — gives you a public URL

---

## Create the Scraper service

1. **+ Add → GitHub Repo** → same repo, create a **new service**
2. Service name: `scraper`
3. **Settings → Source → Root Directory**: `backend`
4. **Settings → Variables** — add:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ANTHROPIC_API_KEY=sk-ant-...
   TICKETMASTER_API_KEY=...
   SERPAPI_KEY=...
   ```
5. **Settings → Deploy → Start Command**:
   ```
   uv run python scripts/additive_scrape.py --only external
   ```
6. **Settings → Deploy → Cron Schedule**: `0 */6 * * *` (every 6 hours)

---

## Seed the database (one-time)

After Postgres is provisioned, load local SQLite data into Railway Postgres:

```bash
cd backend
uv run python scripts/migrate_sqlite_to_postgres.py \
  --sqlite data/events.db \
  --postgres 'postgresql+asyncpg://<railway-public-postgres-url>'
```

Get the Railway Postgres URL from: Postgres service → **Connect → Public URL**.
Replace `postgresql://` with `postgresql+asyncpg://`.

---

## Deploy

```bash
git push origin main
```

Railway auto-deploys on push to `main`. Or trigger manually:

```bash
railway up --service api
```

---

## Verify

```bash
curl https://your-railway-domain.up.railway.app/health
# -> {"status": "healthy"}

open https://your-railway-domain.up.railway.app/docs
```

---

## Cost estimate (Railway Hobby plan)

| | Notes |
|---|---|
| API service | Always-on, ~$2-4/mo depending on traffic |
| Scraper service | Cron only - runs 4x/day, minimal cost |
| Postgres (1GB) | ~$5/mo on Hobby plan |
| **Total** | **~$10-12/mo** |

Anthropic API (Claude) costs are billed separately at pay-per-token rates.

---

## Useful Railway CLI commands

```bash
railway logs --service api          # tail API logs
railway logs --service scraper      # tail scraper logs
railway shell --service api         # open a shell in the running container
railway run --service scraper -- uv run python scripts/health.py
```

---

## Scraper sources (8 active)

| Source | Method | Notes |
|---|---|---|
| `ticketmaster` | API | General Chicago events + sports teams (Sky, Fire, Stars, Cubs, Sox, Bears, Bulls, Blackhawks). Requires `TICKETMASTER_API_KEY` |
| `do312` | API | Chicago music and nightlife |
| `chicago_park_district` | Playwright | Park District events calendar |
| `broadway_in_chicago` | Playwright | Broadway shows |
| `techinmotion` | httpx | Tech in Motion Chicago events |
| `mahjongsociety` | httpx | The Mahjong Society Chicago events |
| `illinoisscience` | Playwright | Illinois Science Council events |
| `cuddlebunny` | Playwright | Cuddle Bunny CCC (Lakeview rabbit cafe) |
