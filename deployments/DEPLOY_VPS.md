# Deploying HOPEFX to a VPS (auto-deploy from GitHub `main`)

This sets up **push-to-deploy**: every push to `main` SSHes into your VPS, pulls
the latest code, and runs `docker compose build && up` with a health check.

- Workflow: `.github/workflows/deploy.yml`
- Server script: `deployments/deploy.sh`

---

## 0. VPS requirements

- **KVM VPS with root/sudo SSH** (Hostinger "VPS", *not* shared/web hosting).
- **RAM: 8 GB recommended** (4 GB is the bare minimum; the full stack runs
  FastAPI + Postgres + Redis + Celery + Prometheus/Grafana/Nginx).
- ~2 vCPU, ~40 GB disk, Ubuntu 22.04/24.04.

> Lean option: you can run just `app postgres redis nginx` to save RAM — see
> [§6](#6-run-a-lean-subset-optional).

---

## Quickest path: one-command bootstrap (recommended for a fresh VPS)

If you're starting from a **freshly (re)installed** Ubuntu 22.04/24.04 VPS with
nothing on it yet, `deployments/vps_bootstrap.sh` does everything in sections
1–5 below automatically — OS checks, DNS check, Docker install, firewall,
clone, `.env` generation with strong random secrets, TLS certificate (via a
temporary self-signed cert + Let's Encrypt webroot challenge — no manual
certbot dance), starts the stack, seeds the superadmin/admin accounts, and
schedules automatic certificate renewal. It is idempotent — safe to re-run if
anything fails partway.

```bash
curl -fsSL https://raw.githubusercontent.com/HACKLOVE340/HOPEFX-AI-TRADING/main/deployments/vps_bootstrap.sh -o vps_bootstrap.sh
chmod +x vps_bootstrap.sh
./vps_bootstrap.sh hopefx.site you@example.com
```

Read the comment header at the top of the script for exactly what it checks
and does, step by step. **Point your domain's DNS A record at the VPS first**
— the script checks this and stops with a clear message if it's not ready yet,
rather than failing confusingly at the certificate step.

The rest of this document (sections 1–7) explains the same steps manually, for
reference, troubleshooting, or if you'd rather do it by hand.

---

## 1. One-time server setup (run these on the VPS over SSH)

```bash
# --- 1a. Install Docker + compose plugin ---
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"     # log out/in after this so docker works without sudo

# --- 1b. Create a dedicated deploy user (recommended) ---
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo su - deploy                    # switch to the deploy user for the rest

# --- 1c. Clone the repo ---
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING

# --- 1d. Create the production .env (NEVER committed) ---
cp .env.example .env
nano .env
#   Set at minimum:
#     APP_ENV=production
#     DATABASE_URL=postgresql+asyncpg://hopefx:<db-pass>@postgres:5432/hopefx
#     REDIS_URL=redis://redis:6379/0
#     ALLOWED_ORIGINS=https://your-domain.com
#     JWT_SECRET / secret keys  (generate strong random values)
#     (optional) FINNHUB_API_KEY, TWELVE_API_KEY, etc.
```

> The DB/Redis hostnames are the **compose service names** (`postgres`, `redis`),
> because the app talks to them over the internal Docker network.

---

## 2. Create the deploy SSH key (lets GitHub log in to the VPS)

On the VPS, **as the `deploy` user**:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gh_deploy -N ""        # no passphrase (CI can't type one)
cat ~/.ssh/gh_deploy.pub >> ~/.ssh/authorized_keys      # trust the key
chmod 600 ~/.ssh/authorized_keys
cat ~/.ssh/gh_deploy                                    # <-- copy this PRIVATE key
```

Copy the **private** key (the whole `-----BEGIN…END-----` block) for the next step.

---

## 3. Add the GitHub secrets

GitHub → your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|--------|-------|
| `VPS_HOST` | your VPS IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | the **private** key from step 2 (full block) |
| `VPS_APP_DIR` | `/home/deploy/HOPEFX-AI-TRADING` |
| `VPS_PORT` | *(optional)* your SSH port if not `22` |

---

## 4. First deploy

Either push any commit to `main`, or trigger it manually:
GitHub → **Actions → Deploy to VPS → Run workflow**.

The job SSHes in, `git reset --hard origin/main`, and runs `deployments/deploy.sh`
which builds the images and starts the stack, then polls
`http://localhost:8000/api/health/live` until it's green.

Watch it under the repo's **Actions** tab.

---

## 5. Domain + HTTPS

Point your domain's DNS `A` record at the VPS IP first, then pick **one** of the
two TLS paths below. Both are supported; don't mix them, because both want
ports 80/443.

### 5a. Caddy on the host (recommended — automatic certificates)

Caddy issues and renews Let's Encrypt certificates on its own. No certbot, no
cron, no cert paths to get wrong.

```bash
sudo apt install -y caddy
sudo systemctl disable --now nginx          # a HOST nginx also holds :80
sudo cp deployments/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Then start the stack with the Caddy override, so the **bundled** nginx service
(which also publishes 80/443) is excluded:

```bash
docker compose -f docker-compose.yml \
               -f deployments/docker-compose.caddy.yml up -d
```

Set it once and plain `docker compose` picks both files up automatically:

```bash
echo 'COMPOSE_FILE=docker-compose.yml:deployments/docker-compose.caddy.yml' >> .env
```

Two things that bite here, both covered in the comments at the top of
`deployments/Caddyfile`:

- The upstream is **`127.0.0.1:8000`**, not `app:8000`. Caddy runs on the host,
  outside the Compose network, so the service name doesn't resolve.
- Never add `root`/`file_server` to the site block. That makes Caddy answer from
  disk and never reach the container — which is how a stray placeholder page
  ends up on the public site while the real React landing page sits unused
  inside the image.

### 5b. Bundled nginx + certbot

Keep the `nginx` service (don't use the override) and either put your certs
where `nginx/nginx.conf` expects them
(`/etc/letsencrypt/live/$HOPEFX_DOMAIN/fullchain.pem`), or let
`deployments/vps_bootstrap.sh` do the whole webroot-challenge dance for you.
Fronting the VPS with Cloudflare (orange-cloud) for edge TLS also works.

---

## 6. Run a lean subset (optional)

To save RAM, deploy only the essentials by setting an env override in the
deploy step (or exporting it on the server before running the script):

```bash
COMPOSE_ARGS="app postgres redis nginx" bash deployments/deploy.sh
```

---

## 7. Operating it

```bash
cd ~/HOPEFX-AI-TRADING
docker compose ps                 # status of every service
docker compose logs -f app        # tail the API logs
docker compose restart app        # restart one service
docker compose down               # stop everything (data volumes persist)
```

**Roll back** to a previous release:

```bash
git reset --hard <old-commit-sha>
bash deployments/deploy.sh
```

**Diagnose** anytime (writes a health report on the server):

```bash
python scripts/platform_doctor.py --log <(docker compose logs --no-color --tail=2000 app)
```

---

## 8. Troubleshooting: the site serves the wrong page

If the public URL shows a page that isn't the real landing page, run:

```bash
bash deployments/diagnose_served_page.sh
```

It's read-only. It compares three layers — the app container on
`127.0.0.1:8000`, the `static/` directory baked into the image, and the public
URL — then names the one that's lying and prints the fix. The real landing page
is `frontend/src/pages/LandingPage.tsx` (mounted at `/` in
`frontend/src/App.tsx`); its fingerprints in the served HTML/JS are the title
`HOPEFX — AI-Powered Gold & Forex Trading Platform` and the hero copy
`HOPEFX combines machine learning`.

The three failure modes it distinguishes:

| Symptom | Cause | Fix |
|---------|-------|-----|
| App on :8000 is correct, public URL isn't | The proxy answers from disk (`root`/`file_server`) or a stray vhost | Replace `/etc/caddy/Caddyfile` with `deployments/Caddyfile`, reload Caddy |
| Title says `HOPEFX GodMode v9.5` | `static/` is missing in the container, so `core/page_routes.py` fell back to the committed legacy `dashboard/dist/` | `docker compose build --no-cache app && docker compose up -d app` |
| Title says `HOPEFX — Build Required` | No frontend build at all — the `frontend-builder` stage didn't land | same rebuild |
| Both layers correct, browser still stale | The PWA service worker cached the old page | DevTools → Application → Service Workers → *Unregister*, then Clear site data |

---

## Security notes

- `.env` and secrets live **only on the server** — never commit them.
- The deploy key is scoped to the `deploy` user; consider restricting it in
  `authorized_keys` with `command=`/`from=` if you want to lock it down further.
- The workflow requests only `contents: read` and never exposes your secrets in
  logs (they're masked by GitHub Actions).
