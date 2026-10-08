# Deploying EventLoop on Railway

Two services share one persistent volume (the SQLite database):

| Service | Dockerfile | Purpose |
|---|---|---|
| `api` | `backend/Dockerfile` | FastAPI + PydanticAI chat backend (Python 3.15) |
| `scraper` | `backend/Dockerfile.scraper` | Playwright venue scraper cron (Python 3.14) |

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

Or skip the CLI and connect via the Railway dashboard:
**New Project → Deploy from GitHub repo → select `lorenanicole/event-loop`**

---

## Create the API service

In the Railway dashboard:

1. **+ Add → GitHub Repo** → pick this repo
2. Service name: `api`
3. **Settings → Source → Root Directory**: `/backend`
   - Railway will find `backend/Dockerfile` automatically (it's named `Dockerfile`)
   - It will also find `backend/railway.toml` for build/deploy config
4. **Settings → Variables** — add:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   SERPAPI_KEY=...
   ADMIN_KEY=something-secret
   LOG_LEVEL=INFO
   DATABASE_URL=sqlite+aiosqlite:////data/events.db
   ```
5. **Settings → Networking → Generate Domain** — gives you a public URL

---

## Create the Scraper service

1. **+ Add → GitHub Repo** → same repo, but create a **new service**
2. Service name: `scraper`
3. **Settings → Source → Root Directory**: `/backend`
4. **Settings → Source → Config File Path**: `/backend/railway.scraper.toml`
   - This tells Railway to use `Dockerfile.scraper` and set the cron schedule
5. **Settings → Variables** — add:
   ```
   DATABASE_URL=sqlite+aiosqlite:////data/events.db
   ANTHROPIC_API_KEY=sk-ant-...
   SERPAPI_KEY=...
   ```
6. **Settings → Cron Schedule**: `0 */6 * * *` (every 6 hours)
   - Verify this is set — the `railway.scraper.toml` sets it but the dashboard is the source of truth for cron services

---

## Create the shared volume

Both services read/write the same `events.db`. Railway volumes persist across deploys.

1. **+ Add → Volume**
2. Name: `eventloop-data`
3. Attach to the **api** service → mount path: `/data`
4. Attach to the **scraper** service → mount path: `/data`

> ⚠️ Do this before the first deploy. If the API starts without a volume, it
> writes to ephemeral storage and the DB is lost on every redeploy.

---

## Deploy

Once everything is configured, deploy both services:

```bash
# From the repo root
git push origin main
```

Railway auto-deploys on push to `main`. Or trigger manually:

```bash
railway up --service api
```

---

## Verify

```bash
# Check the API is up
curl https://your-railway-domain.up.railway.app/health
# → {"status": "healthy"}

# Check the docs
open https://your-railway-domain.up.railway.app/docs
```

---

## Cost estimate (Railway Hobby plan, $5/mo)

| | Notes |
|---|---|
| API service | Always-on, ~$2–4/mo depending on traffic |
| Scraper service | Cron only — runs ~4×/day, minimal cost |
| Volume (10GB) | $0.25/GB/mo → ~$2.50/mo |
| **Total** | **~$5–8/mo** |

Anthropic API (Claude) costs are billed separately at pay-per-token rates.

---

## Useful Railway CLI commands

```bash
railway logs --service api          # tail API logs
railway logs --service scraper      # tail scraper logs
railway shell --service api         # open a shell in the running container
railway run --service api -- python scripts/health.py  # run a one-off script
```
