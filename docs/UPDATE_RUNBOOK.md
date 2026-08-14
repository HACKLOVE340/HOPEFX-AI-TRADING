# Update runbook — pull and restart a running deployment

For an existing server. First-time provisioning is `deploy.sh` (installs Docker,
clones the repo, installs `hopefx.service`); do not re-run it to update.

Defaults from `deploy.sh`: app dir `/opt/hopefx`, systemd unit `hopefx.service`,
start command `docker compose up -d`.

**`--scale nginx=0` is no longer needed.** The `nginx` service now sits behind
the `standalone-proxy` compose profile, so a plain `docker compose up -d` skips
it. The flag was folklore — forget it once and Docker creates a container that
can never start, because something else already owns ports 80 and 443. That is
what left `hopefx-ai-trading-nginx-1` sitting in `Created` on the production
box, with an audit reasonably reading it as "the site's entry point is down".
Start it explicitly with `docker compose --profile standalone-proxy up -d` only
on a host where nothing else is listening on 80/443.

---

## `pull` is not enough — you must rebuild

`docker compose pull` refreshes only third-party images (postgres, redis,
prometheus, grafana). Every application service — `app`, `trading`,
`celery-worker`, `celery-beat` — is declared with `build:`, not `image:`, so new
code reaches them **only** through `docker compose build`.

This matters most for the frontend. `Dockerfile` stage 1 runs `npm run build`
and stage 2 copies the result to `./static`; `frontend/dist` is not committed.
A frontend fix that is not rebuilt is not deployed, however many times you
restart the container.

---

## The update

```bash
cd /opt/hopefx

# 1. Get the code. --ff-only refuses to create a merge commit if the server
#    has local edits — if it fails, resolve that first rather than forcing.
git pull --ff-only origin main

# 2. Refresh third-party base images.
docker compose pull

# 3. Rebuild the application images. This is the step that ships the change.
docker compose build

# 4. Restart. The containerised nginx is profile-gated and stays out of the
#    way; the host proxy (Traefik) keeps terminating SSL.
docker compose up -d
```

Database migrations need no separate step — the app container runs
`scripts/preflight.sh && python app.py`, and preflight applies Alembic
migrations before the app starts.

If a build behaves as though it ignored your changes, force a clean one:

```bash
docker compose build --no-cache
```

Slower (several minutes), and rarely needed — Docker invalidates its cache from
the first changed `COPY` layer onward.

---

## Verify

```bash
# All services up, none restarting.
docker compose ps

# API is live.
curl -fsS http://localhost:8000/api/health/live

# Nothing failing at startup.
docker compose logs --since 5m app | grep -iE "error|traceback" | head
```

Then check the two things most recently fixed:

```bash
# Drift monitoring should now report active, with real coverage.
docker compose exec -T app python -c "
from ml.inference_engine import InferenceEngine
print(InferenceEngine().drift_status())"
```

Before the fix this reported `active: False`. It should now reach
`{'active': True, 'reason': 'ok', ...}` once the engine has scored a window;
`reason: 'no_training_stats'` means `ml/saved_models/feature_stats.json` did not
make it into the image, and `reason: 'insufficient_coverage'` means the stats
describe a different feature schema than the model produces.

**The Watchlist page needs a hard refresh in the browser.** The frontend
registers a PWA service worker (`registerType: 'autoUpdate'`), so the old
bundle can be served from cache until the new worker activates. If the page
still crashes after the rebuild, that is a stale cache rather than a failed
deploy: hard-reload (Ctrl/Cmd+Shift+R), or clear site data for the domain.

---

## Reboot the host

`hopefx.service` is enabled, so everything comes back automatically:

```bash
sudo reboot
```

To restart the stack without rebooting the machine:

```bash
sudo systemctl restart hopefx
```

---

## Rollback

Images are rebuilt in place, so roll back by rebuilding the previous commit:

```bash
cd /opt/hopefx
git log --oneline -5          # find the commit to return to
git checkout <commit>
docker compose build
docker compose up -d
```

Postgres and Redis data live in named volumes and are untouched by a rebuild.
