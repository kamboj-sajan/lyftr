# Deployment

Backend on **Render** (Docker, free plan) and frontend on **Vercel** (static Vite build).
Total time: about 20 minutes, most of it waiting for the first Docker build.

Order matters, because each side needs the other's URL:

1. Deploy the backend → get its URL.
2. Deploy the frontend with `VITE_API_BASE_URL` = backend URL → get the frontend URL.
3. Set the backend's `ALLOWED_ORIGINS` = frontend URL (CORS) → redeploy the backend.

You need: the two LLM API keys, a GitHub login, and the repo `kamboj-sajan/lyftr` (public).

---

## 1. Backend on Render

The repo root has a `render.yaml` Blueprint that defines the service, so most settings are pre-filled.

1. Go to <https://dashboard.render.com> and sign in with **GitHub**.
2. Click **New +** → **Blueprint**.
3. Under **Connect a repository**, connect GitHub if asked, give Render access to `kamboj-sajan/lyftr`, then pick it. Branch: `main`.
4. Render reads `render.yaml` and shows one service, `lyftr-backend` (Docker, Free). Give the Blueprint a name, e.g. `lyftr`.
5. Render asks for the two values marked `sync: false`:
   - `LLM_API_KEYS` → `gsk_key1,gsk_key2` (comma, no spaces, no quotes)
   - `ALLOWED_ORIGINS` → `http://localhost:3000` for now (a placeholder; you replace it in step 3)
6. Click **Deploy Blueprint** (or **Apply**). The first build takes about 5–8 minutes. In the service's **Logs**, wait for:
   ```
   INFO app startup ok keys_configured=2 model=groq/openai/gpt-oss-120b ...
   ```
7. Copy the service URL at the top of the service page, e.g. `https://lyftr-backend.onrender.com`. (Render adds a suffix if the name is taken; use whatever it shows.)
8. Open `https://<backend-url>/health`. You should see:
   ```json
   {"status":"ok","keys_configured":2,"cache_enabled":true}
   ```

## 2. Frontend on Vercel

1. Go to <https://vercel.com/new> and sign in with **GitHub**.
2. Find `kamboj-sajan/lyftr` and click **Import** (grant access to the repo if asked).
3. On **Configure Project**:
   - **Project Name**: e.g. `lyftr`
   - **Root Directory**: click **Edit** → choose `frontend` → **Continue**
   - **Framework Preset**: Vite (detected). Build, install and output settings come from `frontend/vercel.json`.
   - **Environment Variables**: add `VITE_API_BASE_URL` = `https://<backend-url>` (no trailing slash)
4. Click **Deploy** (about 1 minute).
5. Copy the **production** domain from the project page (**Domains**), e.g. `https://lyftr.vercel.app`.
   Use this domain, not a per-deployment URL like `lyftr-a1b2c3-user.vercel.app`; CORS only allows the exact origin you configure.

`VITE_API_BASE_URL` is baked in at build time. If you change it later: **Settings → Environment Variables** → edit, then **Deployments** → latest → **⋯** → **Redeploy**.

## 3. Connect them (CORS)

1. Render dashboard → **lyftr-backend** → **Environment**.
2. Edit `ALLOWED_ORIGINS` → `https://lyftr.vercel.app` (your exact frontend origin: `https://`, no trailing slash).
   To keep local development working too: `https://lyftr.vercel.app,http://localhost:3000,http://localhost:5173`.
3. Click **Save, rebuild, and deploy** (or **Save and deploy**) and wait until the service is **Live** again.
4. Open the frontend and send a message. You should get a reply with a `LIVE_INFERENCE` badge.

## 4. Verify

```bash
./scripts/smoke_test.sh https://<backend-url>     # expect: All 20 checks passed
```

In the browser:

- **Cache hit**: send a message, click **New chat** (or reload), send the identical message → `LLM_CACHE`, `key none`, a few ms.
- **Failover**: `curl` with `X-Simulate-Failure: key_1=429` (see README) → `key_id: "key_2"`, `fallback_attempts: 1`.
- **Readable error**: send a message over 4000 characters → a red error bubble, not a blank screen.

## Before recording the demo or submitting

- **Wake the backend first.** The Render free plan sleeps after 15 minutes without traffic, and the first request then takes up to about a minute. Open `https://<backend-url>/health` and wait for `"status":"ok"` before you start. The smoke script also waits up to 120 seconds for it.
- **History is not persistent on the free plan.** Free Render services cannot attach a disk, so `/data` (SQLite history and cache) is wiped on every redeploy, restart or spin-down. History works normally while the service is awake. For persistence, switch the service to a paid plan and uncomment the `disk:` block in `render.yaml` (mount path `/data`).

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Frontend shows "Could not reach the server … (CORS)" | `ALLOWED_ORIGINS` doesn't exactly match the frontend origin (scheme, host, no trailing slash), or the backend is asleep or redeploying. Check `/health`, then the env var. |
| `503 all providers unavailable` | Both keys failed. In Render **Logs**, the `llm_attempt` lines show the status per key: `401` = bad key, `429` = rate limit. |
| Deploy fails, log says `LLM_API_KEYS must contain at least 2` | Fix the env var (two keys, comma-separated) and redeploy. |
| Frontend calls `localhost:8000` in production | `VITE_API_BASE_URL` was missing at build time. Set it and **Redeploy**. |

## Alternative: Netlify for the frontend

**Add new site → Import an existing project** → GitHub → `kamboj-sajan/lyftr` → **Base directory** `frontend` (build command and publish directory come from `frontend/netlify.toml`) → add `VITE_API_BASE_URL` under environment variables → **Deploy**. Then use the Netlify domain in `ALLOWED_ORIGINS`.
