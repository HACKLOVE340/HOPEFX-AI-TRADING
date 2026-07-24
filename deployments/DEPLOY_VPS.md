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

The `nginx` service publishes ports **80/443**. Point your domain's DNS `A`
record at the VPS IP. For TLS, either:

- put your certs where `nginx/nginx.conf` expects them, **or**
- run Certbot on the host and mount the certs into the nginx container, **or**
- front the VPS with Cloudflare (orange-cloud) for automatic edge TLS.

(Tell me which you prefer and I'll wire the exact nginx/certbot config.)

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

## Security notes

- `.env` and secrets live **only on the server** — never commit them.
- The deploy key is scoped to the `deploy` user; consider restricting it in
  `authorized_keys` with `command=`/`from=` if you want to lock it down further.
- The workflow requests only `contents: read` and never exposes your secrets in
  logs (they're masked by GitHub Actions).
