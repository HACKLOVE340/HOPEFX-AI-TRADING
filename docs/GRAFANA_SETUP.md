# Grafana Setup

> Monitoring dashboards for HOPEFX AI Trading.
> Grafana is available on Professional, Enterprise, and Elite plans.
> Last updated: 2026-04-01

---

## Subscription Requirement

Grafana dashboards require a **Professional subscription or above**.

| Feature | Starter | Professional | Enterprise | Elite |
|---------|---------|-------------|------------|-------|
| Grafana access | — | 4 dashboards | 4 dashboards | 4 dashboards + custom |
| Dashboard editing | — | Read-only | Read-only | Full edit |
| Alert rules | — | 10 | 50 | Unlimited |
| Data retention | — | 30 days | 90 days | 1 year |

Attempting to access Grafana without a qualifying plan returns `403 Plan Limit Exceeded`
from the reverse proxy.

---

## Architecture

```
HOPEFX App (:8000)
    │
    ├── /metrics  ──────────────► Prometheus (:9090)
    │                                  │
    │                                  ▼
    │                            Grafana (:3000)
    │                                  │
    └── /health ◄────────────── Alert Manager
```

- **Prometheus** scrapes `/metrics` every 15 seconds
- **Grafana** queries Prometheus for all dashboard data
- **Alert Manager** routes alerts to Telegram, email, or PagerDuty
- All services run in the same Docker Compose network (`hopefx-net`)

---

## Quick Start (Docker Compose)

The full monitoring stack is included in `docker-compose.yml`. No separate installation needed.

```bash
# Start everything including Grafana
docker compose up -d

# Verify Grafana is running
curl -s http://localhost:3000/api/health | python3 -m json.tool
```

Grafana is available at `http://localhost:3000`.

Default credentials (change immediately):
- Username: `admin`
- Password: set via `GRAFANA_ADMIN_PASSWORD` in `.env`

---

## Environment Variables

Add these to `.env` before starting:

```env
# Grafana admin password (required — no default)
GRAFANA_ADMIN_PASSWORD=change_me_strong_password

# Grafana secret key (used for session signing — generate with: openssl rand -hex 32)
GRAFANA_SECRET_KEY=your_32_char_hex_string

# Optional: external URL if behind a reverse proxy
GRAFANA_ROOT_URL=https://monitoring.yourdomain.com

# Optional: SMTP for alert emails
GRAFANA_SMTP_HOST=smtp.gmail.com:587
GRAFANA_SMTP_USER=alerts@yourdomain.com
GRAFANA_SMTP_PASSWORD=your_smtp_password
GRAFANA_SMTP_FROM=alerts@yourdomain.com
```

Generate secrets:
```bash
openssl rand -hex 32   # for GRAFANA_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(24))"  # for GRAFANA_ADMIN_PASSWORD
```

---

## Dashboards

Four dashboards are provisioned automatically from `grafana/dashboards/`:

### 1. Trading Performance (`trading_performance.json`)

The primary operational dashboard. Panels:

| Panel | Metric | Description |
|-------|--------|-------------|
| Equity Curve | `hopefx_equity` | Account equity over time |
| Open Positions | `hopefx_active_positions` | Current open position count |
| Daily P&L | `hopefx_pnl_realized` | Realized P&L for the day |
| Win Rate | `hopefx_win_rate_pct` | Win rate over last 100 trades |
| Drawdown | `hopefx_drawdown_pct` | Current drawdown from peak |
| Sharpe Ratio | `hopefx_sharpe_ratio` | Rolling 30-day Sharpe |
| Signal Count | `hopefx_signals_total` | Signals generated today |
| Fill Rate | `hopefx_fill_rate_pct` | Order fill rate |

### 2. ML Model Metrics (`ml_model_metrics.json`)

Tracks model health and prediction quality:

| Panel | Metric | Description |
|-------|--------|-------------|
| Model Accuracy | `hopefx_ml_accuracy` | OOS accuracy (current: 56.5%) |
| Prediction Confidence | `hopefx_ml_confidence_avg` | Average confidence score |
| Abstain Rate | `hopefx_ml_abstain_rate` | % of bars where model abstains |
| Feature Count | `hopefx_ml_feature_count` | Active features (current: 193) |
| Online Learner Updates | `hopefx_online_learner_updates_total` | Hourly update count |
| Regime | `hopefx_market_regime` | Current regime (0=ranging, 1=trending, 2=volatile) |
| Fallback Active | `hopefx_ml_fallback_active` | 1 if fallback model is in use |
| Macro Features | `hopefx_macro_features_age_seconds` | Age of macro data (alert if > 86400s) |

### 3. System Health (`system_health.json`)

Infrastructure and API performance:

| Panel | Metric | Description |
|-------|--------|-------------|
| API Latency p99 | `hopefx_request_duration_seconds` | p99 latency (target: < 200ms) |
| API Error Rate | `hopefx_http_errors_total` | 4xx/5xx per minute |
| Redis Hit Rate | `hopefx_cache_hit_rate` | Cache hit % (target: > 90%) |
| DB Query Time | `hopefx_db_query_duration_seconds` | Slow query detection |
| Memory Usage | `process_resident_memory_bytes` | App memory (alert if > 2GB) |
| CPU Usage | `process_cpu_seconds_total` | CPU utilization |
| Kill Switch | `hopefx_kill_switch_active` | 1 if kill switch is active |
| Uptime | `process_start_time_seconds` | Application uptime |

### 4. Broker Connectivity (`broker_connectivity.json`)

Broker connection health and order routing:

| Panel | Metric | Description |
|-------|--------|-------------|
| Broker Status | `hopefx_broker_connected` | 1 = connected, 0 = disconnected |
| Orders Placed | `hopefx_orders_placed_total` | Total orders sent to broker |
| Orders Filled | `hopefx_orders_filled_total` | Total orders filled |
| Rejected Orders | `hopefx_orders_rejected_total` | Orders rejected by broker |
| Spread | `hopefx_spread_pips` | Current bid/ask spread |
| Latency to Broker | `hopefx_broker_latency_ms` | Round-trip to broker API |
| Reconciliation Errors | `hopefx_reconciliation_errors_total` | OMS vs broker mismatches |
| Last Price Update | `hopefx_price_update_age_seconds` | Age of last price tick |

---

## Prometheus Metrics Reference

HOPEFX exposes metrics at `GET /metrics` in Prometheus text format.

### Trading Metrics

```
hopefx_equity                    # Current account equity (USD)
hopefx_balance                   # Account balance (USD)
hopefx_pnl_realized              # Realized P&L today (USD)
hopefx_pnl_unrealized            # Unrealized P&L (USD)
hopefx_drawdown_pct              # Current drawdown from peak (%)
hopefx_active_positions          # Number of open positions
hopefx_win_rate_pct              # Win rate last 100 trades (%)
hopefx_sharpe_ratio              # Rolling 30-day Sharpe ratio
hopefx_signals_total             # Total signals generated (counter)
hopefx_orders_placed_total       # Total orders placed (counter)
hopefx_orders_filled_total       # Total orders filled (counter)
hopefx_orders_rejected_total     # Total orders rejected (counter)
hopefx_fill_rate_pct             # Fill rate (%)
```

### ML Metrics

```
hopefx_ml_accuracy               # Current model OOS accuracy
hopefx_ml_confidence_avg         # Average prediction confidence
hopefx_ml_abstain_rate           # Abstain rate (0.0–1.0)
hopefx_ml_feature_count          # Number of active features
hopefx_ml_fallback_active        # 1 if fallback model active
hopefx_online_learner_updates_total  # Online learner update count
hopefx_market_regime             # Market regime (0/1/2)
hopefx_macro_features_age_seconds    # Age of macro data
```

### Risk Metrics

```
hopefx_kill_switch_active        # 1 if kill switch is active
hopefx_cvar_pct                  # Current CVaR (%)
hopefx_daily_loss_pct            # Daily loss as % of account
hopefx_risk_gate_blocks_total    # Orders blocked by risk gate
```

### System Metrics

```
hopefx_request_duration_seconds  # API request latency (histogram)
hopefx_http_errors_total         # HTTP errors by status code (counter)
hopefx_cache_hit_rate            # Redis cache hit rate
hopefx_db_query_duration_seconds # Database query time (histogram)
hopefx_broker_connected          # Broker connection status
hopefx_broker_latency_ms         # Broker API round-trip latency
hopefx_spread_pips               # Current spread in pips
hopefx_reconciliation_errors_total  # OMS reconciliation errors
```

---

## Provisioning

Dashboards and datasources are provisioned automatically via:

```
grafana/
├── dashboards/
│   ├── broker_connectivity.json
│   ├── ml_model_metrics.json
│   ├── system_health.json
│   └── trading_performance.json
└── provisioning/
    ├── dashboards/
    │   └── dashboards.yaml      # Points Grafana at the dashboards/ directory
    └── datasources/
        └── prometheus.yaml      # Configures Prometheus as the default datasource
```

`grafana/provisioning/datasources/prometheus.yaml`:
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: "15s"
```

`grafana/provisioning/dashboards/dashboards.yaml`:
```yaml
apiVersion: 1
providers:
  - name: hopefx
    type: file
    disableDeletion: true
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

---

## Alert Rules

### Default Alerts

Configure these alert rules in Grafana (Alerting → Alert rules):

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| Kill Switch Active | `hopefx_kill_switch_active == 1` | Critical | Telegram + email |
| High Drawdown | `hopefx_drawdown_pct > 5` | Warning | Telegram |
| Critical Drawdown | `hopefx_drawdown_pct > 8` | Critical | Telegram + email |
| ML Fallback Active | `hopefx_ml_fallback_active == 1` | Warning | Email |
| Broker Disconnected | `hopefx_broker_connected == 0` for 2m | Critical | Telegram + email |
| API p99 High | `hopefx_request_duration_seconds{quantile="0.99"} > 0.5` | Warning | Email |
| Stale Macro Data | `hopefx_macro_features_age_seconds > 86400` | Warning | Email |
| High Error Rate | `rate(hopefx_http_errors_total[5m]) > 1` | Warning | Email |

### Telegram Notifications

```bash
# In .env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

In Grafana: Alerting → Contact points → Add contact point → Telegram.
Enter your bot token and chat ID.

### Email Notifications

Configure SMTP in `.env` (see Environment Variables above), then:
Grafana → Alerting → Contact points → Add contact point → Email.

---

## Production Deployment

### Behind Nginx

Add to your Nginx config:

```nginx
location /grafana/ {
    proxy_pass http://localhost:3000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Set `GRAFANA_ROOT_URL=https://yourdomain.com/grafana/` in `.env`.

### Kubernetes (Helm)

Grafana is included in the HOPEFX Helm chart:

```bash
helm upgrade --install hopefx helm/hopefx/ \
  --set grafana.enabled=true \
  --set grafana.adminPassword="$(openssl rand -base64 24)" \
  --set grafana.persistence.enabled=true \
  --set grafana.persistence.size=5Gi
```

### Data Persistence

In production, mount a persistent volume for Grafana data:

```yaml
# docker-compose.yml (already configured)
volumes:
  grafana_data:
    driver: local

services:
  grafana:
    volumes:
      - grafana_data:/var/lib/grafana
```

Without persistence, dashboards and alert rules are lost on container restart.
The provisioned dashboards (from `grafana/dashboards/`) are always restored automatically,
but any dashboards you create manually in the UI will be lost.

---

## Accessing Grafana

### Local Development

```
http://localhost:3000
```

### Production (with Nginx)

```
https://yourdomain.com/grafana/
```

### Direct API Access

```bash
# List dashboards
curl -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://localhost:3000/api/search?type=dash-db

# Get dashboard JSON
curl -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://localhost:3000/api/dashboards/uid/hopefx-trading

# Check datasource health
curl -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://localhost:3000/api/datasources/1/health
```

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `No data` on all panels | Prometheus not scraping | Check `curl http://localhost:9090/targets` — app target must be `UP` |
| `Datasource not found` | Provisioning failed | Check `docker compose logs grafana` for provisioning errors |
| Login fails | Wrong password | Reset: `docker compose exec grafana grafana-cli admin reset-admin-password newpass` |
| Dashboards missing | Volume not mounted | Check `docker compose ps` — grafana container must be running |
| Alerts not firing | Contact point not configured | Grafana → Alerting → Contact points → test the contact point |
| Metrics stale | App not running | Check `curl http://localhost:8000/metrics` returns data |
| High memory in Grafana | Too many panels open | Reduce time range or close unused dashboards |

---

## Custom Dashboards (Elite)

Elite subscribers can create and save custom dashboards. All Prometheus metrics are
available as data sources. Use the Grafana dashboard editor to:

1. Add panels with custom PromQL queries
2. Set custom alert thresholds
3. Create team-specific views
4. Export dashboards as JSON for version control

To export a custom dashboard:
```bash
curl -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://localhost:3000/api/dashboards/uid/your-dashboard-uid \
  | python3 -m json.tool > grafana/dashboards/my_custom_dashboard.json
```

Commit the JSON to version control so it is provisioned automatically on next deploy.

---

*Last updated: 2026-04-01*
