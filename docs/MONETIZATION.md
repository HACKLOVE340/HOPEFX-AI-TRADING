# HOPEFX Monetization & Pricing

> HOPEFX is a paid, subscription-based AI trading platform.
> Last updated: 2026-07-14

---

## Pricing Tiers

| Feature | Starter | Pro | Elite | Enterprise |
|---------|---------|-----|-------|------------|
| **Price** | $49/mo | $149/mo | $349/mo | Custom |
| **Signals** | 5/day | Unlimited | Unlimited | Unlimited |
| **Symbols** | 1 (XAUUSD) | 5 | 7 | Unlimited |
| **Strategies** | 3 built-in | All 10 | All 10 + custom | All + white-label |
| **ML model** | Basic (65 feat) | Advanced (176 feat) | Advanced + online learning | Custom model training |
| **Backtesting** | 1 year | 10 years | 50 years | Unlimited |
| **Broker connections** | 1 | 3 | Unlimited | Unlimited |
| **Prop firm mode** | — | ✅ | ✅ | ✅ |
| **Social trading** | View only | Full | Full | Full |
| **API access** | — | ✅ | ✅ | ✅ |
| **Mobile app** | ✅ | ✅ | ✅ | ✅ |
| **Grafana dashboards** | — | ✅ | ✅ | ✅ |
| **Priority support** | — | — | ✅ | ✅ |
| **SLA** | — | — | 99.9% | 99.99% |
| **White-label** | — | — | — | ✅ |

Annual billing: 2 months free (pay 10, get 12).

---

## Payment Methods

### Credit/Debit Card (Stripe)
Visa, Mastercard, American Express, Discover.

```bash
# Stripe webhook endpoint (Stripe calls this — not for direct use)
POST /api/billing/webhook/stripe
```

### Crypto (BTC, ETH, USDT)
```bash
# Generate a payment address
POST /api/payments/crypto/address
{
  "currency": "USDT",
  "amount": 149.00,
  "plan": "pro"
}

# Check payment status
GET /api/payments/crypto/status/{payment_id}

# Current exchange rates
GET /api/payments/crypto/rates
```

### Flutterwave (Africa & emerging markets)
```bash
# Initialize payment
POST /api/billing/payments/flutterwave/init

# Verify payment
POST /api/billing/payments/flutterwave/verify
```

---

## Subscription Management

### Subscribe
```bash
POST /api/monetization/subscribe
{
  "plan": "pro",
  "billing_cycle": "monthly",
  "payment_method": "stripe"
}
```

### Check Subscription Status
```bash
GET /api/monetization/subscription/{user_id}
```

Response:
```json
{
  "plan": "pro",
  "status": "active",
  "billing_cycle": "monthly",
  "current_period_end": "2026-08-14T00:00:00Z",
  "features": {
    "signals_per_day": -1,
    "symbols": 5,
    "strategies": 10,
    "backtesting_years": 10,
    "broker_connections": 3,
    "prop_firm_mode": true,
    "api_access": true
  }
}
```

### Cancel Subscription
```bash
POST /api/monetization/subscription/{subscription_id}/cancel
```

Cancellation takes effect at the end of the current billing period.
No refunds for partial months.

### Check Feature Limits
```bash
GET /api/monetization/subscription/{user_id}/limits
```

The platform enforces limits at the API layer. Requests that exceed your
plan's limits return `403 Forbidden` with `error_code: PLAN_LIMIT_EXCEEDED`.

---

## Access Codes

Access codes allow one-time or time-limited access without a recurring subscription.
Used for: trial periods, promotional access, partner integrations.

```bash
# Activate an access code
POST /api/monetization/activate-code
{ "code": "HOPEFX-TRIAL-30D" }

# Validate without activating
GET /api/monetization/validate-code/{code}
```

---

## Affiliate Program

Earn 30% recurring commission on every subscriber you refer.

```bash
# Sign up as an affiliate
POST /api/monetization/affiliate/signup

# Generate your referral link
POST /api/billing/affiliate/generate-link
{ "campaign": "youtube" }

# Response
{ "referral_link": "https://hopefx.app/ref/YOUR_CODE?utm_source=youtube" }
```

Commission is paid monthly via Stripe, crypto, or Flutterwave.
Minimum payout: $50.

---

## White-Label (Enterprise)

Enterprise subscribers can white-label the entire platform:

- Custom domain (`trading.yourbrand.com`)
- Custom logo, colors, and branding
- Your own pricing tiers and payment processing
- Separate user database
- Custom ML model training on your data
- Dedicated infrastructure (no shared resources)
- SLA: 99.99% uptime

Contact: open a GitHub Issue with label `enterprise` or email via the repository contact.

---

## Feature Gating Implementation

Features are gated at the API layer via the subscription middleware.

```python
# How feature gating works internally
from monetization.subscription import require_plan

@router.post("/api/ml/retrain")
@require_plan("elite")  # Only Elite and Enterprise can retrain
async def retrain_model(user=Depends(get_current_user)):
    ...

@router.get("/api/signals/latest")
@require_plan("starter")  # All paid plans
async def get_signal(user=Depends(get_current_user)):
    ...
```

Unauthenticated requests to any trading endpoint return `401 Unauthorized`.
Authenticated requests from users without an active subscription return
`403 Forbidden` with `error_code: SUBSCRIPTION_REQUIRED`.

---

## Billing FAQ

**Can I try before I buy?**
Use an access code for a 7-day trial. Contact us via GitHub Issues with label `trial-request`.

**What happens when my subscription expires?**
API access is suspended. Your data (trades, journal, settings) is retained for 90 days.
Resubscribe within 90 days to restore full access.

**Can I switch plans mid-cycle?**
Yes. Upgrading is immediate and prorated. Downgrading takes effect at the next billing cycle.

**Do you offer refunds?**
No refunds for partial months. If the platform is unavailable for > 24 hours due to our
infrastructure (not your broker or internet), we credit the affected days.

**Is there a free tier?**
No. HOPEFX is a professional paid platform. The source code is available under AGPL-3.0
for self-hosting, but the hosted service requires a subscription.

**What is the AGPL-3.0 license?**
The source code is open-source under AGPL-3.0. You can self-host it for personal use.
If you build a commercial product on top of it (SaaS, white-label, proprietary), you need
a Commercial License. See [LICENSE-COMMERCIAL.md](https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/LICENSE-COMMERCIAL.md).

---

## Revenue Model Summary

| Stream | Description |
|--------|-------------|
| Subscriptions | Monthly/annual recurring (Starter/Pro/Elite) |
| Enterprise | Custom contracts, white-label, dedicated infra |
| Affiliate | 30% recurring commission on referred subscribers |
| Access codes | One-time or time-limited access |
| API usage | Per-call billing for high-volume API consumers (Enterprise) |

---

*Last updated: 2026-07-14*
