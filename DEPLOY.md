# Deploying FinCortext

The whole app ships as **one container**: the interface is built and then served by the API
process. One URL, no CORS, no second service to configure.

```
browser ──► https://your-app.onrender.com
                 ├── /            the interface (built React files)
                 ├── /api/...     the REST API
                 └── /api/ws/live the live price feed (WebSocket)
```

---

## Which host

The backend keeps a WebSocket open to the exchange feed and runs six background workers
(order matching, strategy runs, research queue, IPO history, alerts, reference data). It must
run as a **long-lived process**, so serverless hosting does not fit.

| Host | Fits? | Why |
|---|---|---|
| **Render** (Docker web service) | **Recommended** | Long-running, WebSockets, free plan, deploys from the repo with `render.yaml`. |
| **Fly.io** | Best if you need data to survive restarts | Free allowance includes a volume, so portfolios persist. Asks for a card. |
| Railway, Koyeb | Work the same way | Also run the Dockerfile; free credit rather than a free plan. |
| **Vercel / Netlify** | Interface only | Serverless functions cannot hold a WebSocket open or run background workers. You would still need a second host for the API. |

Free plans change often — check the current terms before you rely on one.

### What the free plan costs you

On Render's free plan the service **sleeps after about 15 minutes of inactivity**; the next
request wakes it and takes roughly a minute. There is also **no persistent disk**, so the
DuckDB file starts empty after each restart or deploy. In practice:

- Cached prices, instruments and IPO history **rebuild themselves** from the providers.
- Practice portfolios, orders and journals **are lost**. Fine for a demo; not for a term's use.

To keep data, either use Fly.io with the volume in `fly.toml`, or move to Render's Starter
plan and uncomment the `disk:` block in `render.yaml`.

---

## Deploy on Render

1. **Get a market-data token.** In the
   [Upstox developer console](https://account.upstox.com/developer/apps), generate an
   **Analytics Token** (read-only, valid about a year). It covers quotes, candles, market
   status and the live feed, and it cannot trade. This avoids setting up OAuth entirely.

2. **Push this repository to GitHub**, including `Dockerfile` and `render.yaml`.

3. In Render, choose **New → Blueprint**, pick the repository and apply. It reads
   `render.yaml` and creates the service.

4. Open the service's **Environment** tab and add:

   | Key | Value |
   |---|---|
   | `UPSTOX_ACCESS_TOKEN` | the Analytics Token from step 1 |

   The other variables come from `render.yaml`. Never put the token in the repository.

5. Wait for the first build (a few minutes: it builds the interface, then installs Python),
   then open the URL. `/api/health` should report `ok`.

### If you want the "Connect Upstox" button to work

Only needed for the OAuth flow; the Analytics Token above is simpler. Add
`UPSTOX_API_KEY`, `UPSTOX_API_SECRET` and
`UPSTOX_REDIRECT_URI=https://your-app.onrender.com/api/auth/upstox/callback`, and register
that exact redirect URL on the Upstox app.

---

## Deploy on Fly.io

```bash
fly launch --no-deploy --copy-config        # edit `app` in fly.toml to a free name first
fly volumes create fincortext_data --size 1 --region sin
fly secrets set UPSTOX_ACCESS_TOKEN=paste-your-token
fly deploy
```

`fly.toml` keeps one machine awake, because stopping it would drop the live feed.

---

## Run the container locally

```bash
docker build -t fincortext .
docker run -p 8000:8000 -e UPSTOX_ACCESS_TOKEN=... -v fincortext-data:/data fincortext
```

Then open <http://localhost:8000>. This is exactly what the host runs, so it is the best way
to check a deployment problem.

---

## Environment variables

| Variable | Needed | Notes |
|---|---|---|
| `UPSTOX_ACCESS_TOKEN` | For any market data | Read-only Analytics Token. Without it the app runs and says it is not connected. |
| `DUCKDB_PATH` | Set by the image | `/data/fincortext.duckdb`. Mount a volume at `/data` to keep data. |
| `PORT` | Set by the host | The container honours it; defaults to 8000. |
| `LIVE_MODE` | No | `stream` (default) or `poll`. |
| `NEWS_ENABLED` | No | `true` by default. |
| `LLM_PROVIDER` | No | Stays `none`. See below. |
| `UPSTOX_API_KEY` / `_SECRET` / `_REDIRECT_URI` | Only for OAuth | See above. |

---

## Before you make the repository public

- **Rotate the Ollama API key.** An earlier commit put a real key in `.env.example`; it has
  been removed from the file, but **it is still in the git history**. Revoke it at
  ollama.com and issue a new one. Removing a secret from the latest commit does not remove it
  from history.
- `.env` is ignored by git. Check with `git log --all -p -- .env` that it was never committed.
- Secrets belong in the host's dashboard, never in `render.yaml` or `fly.toml`.

---

## No language model in the deployment

`LLM_PROVIDER` is `none` and the image sets it that way, so nothing tries to reach Ollama.

This costs less than it sounds. The assistant routes every question to a tool that computes
its own answer from real data, and the model was only ever allowed to reword that answer —
any figure it added that was not in the computed facts was thrown away. With it off, answers
come straight from the engine and say so: *"Calculated by FinCortext from the data shown."*
The research brief falls back to its built-in wording in the same way.

Running Ollama in the container is not an option worth taking: the smallest useful model
needs more memory than the whole free instance has, there is no GPU, and with no persistent
disk the weights would download again on every cold start.

## What a deployed instance is, and is not

- **There is no sign-in.** Anyone with the URL shares the same portfolios and watchlist. That
  is fine for a demo or an interview: the money is virtual and the Upstox token stays on the
  server, never reaching the browser. Do not treat it as a personal account.
- **No real orders are ever placed.** Upstox is used for market data only.
- A sleeping free instance misses the market while it is asleep: strategy runs that should
  happen after the close will not fire unless something wakes the service.

---

## Checks that run on every push

`.github/workflows/ci.yml` runs on GitHub Actions without any credentials:

- backend: `ruff check`, `ruff format --check`, `pytest` (143 tests)
- interface: `tsc -b`, `vitest`, `vite build`
- the Docker image builds

A green tick means a deploy of that commit should succeed.
