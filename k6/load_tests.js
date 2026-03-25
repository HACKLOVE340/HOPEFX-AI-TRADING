/**
 * k6/load_tests.js
 * ================
 * Production load test for HOPEFX API.
 *
 * Usage:
 *   # Smoke test (1 VU, 30 s)
 *   k6 run --env BASE_URL=https://api.hopefx.io k6/load_tests.js
 *
 *   # Full load test (50 VUs, 8 min ramp)
 *   k6 run --env BASE_URL=https://api.hopefx.io \
 *           --env SCENARIO=load k6/load_tests.js
 *
 *   # Soak test (100 VUs, 10 min)
 *   k6 run --env BASE_URL=https://api.hopefx.io \
 *           --env SCENARIO=soak k6/load_tests.js
 *
 *   # Spike test (ramp to 500 VUs)
 *   k6 run --env BASE_URL=https://api.hopefx.io \
 *           --env SCENARIO=spike k6/load_tests.js
 *
 * Environment variables:
 *   BASE_URL   — API base URL (default: http://localhost:8000)
 *   SCENARIO   — smoke | load | soak | spike (default: smoke)
 *   AUTH_TOKEN — Bearer token for authenticated endpoints
 */

import { check, sleep } from 'k6';
import http from 'k6/http';
import { Rate, Trend } from 'k6/metrics';

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate    = new Rate('error_rate');
const orderLatency = new Trend('order_latency_ms', true);

// ── Config ────────────────────────────────────────────────────────────────────
const BASE_URL   = __ENV.BASE_URL   || 'http://localhost:8000';
const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';
const SCENARIO   = __ENV.SCENARIO   || 'smoke';

const SCENARIOS = {
  smoke: {
    executor: 'constant-vus',
    vus: 1,
    duration: '30s',
  },
  load: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '2m', target: 50 },   // ramp up
      { duration: '5m', target: 50 },   // hold
      { duration: '1m', target: 0  },   // ramp down
    ],
  },
  soak: {
    executor: 'constant-vus',
    vus: 100,
    duration: '10m',
  },
  spike: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '30s', target: 10  },
      { duration: '30s', target: 500 },  // spike
      { duration: '1m',  target: 10  },  // recover
      { duration: '30s', target: 0   },
    ],
  },
};

export const options = {
  scenarios: {
    default: SCENARIOS[SCENARIO] || SCENARIOS.smoke,
  },
  thresholds: {
    // 95th-percentile response time under 500 ms
    http_req_duration: ['p(95)<500'],
    // Error rate below 1%
    error_rate: ['rate<0.01'],
    // Order latency p99 under 1 s
    order_latency_ms: ['p(99)<1000'],
  },
};

// ── Shared headers ────────────────────────────────────────────────────────────
function headers(extra = {}) {
  const h = { 'Content-Type': 'application/json' };
  if (AUTH_TOKEN) h['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  return Object.assign(h, extra);
}

// ── Individual scenario functions ─────────────────────────────────────────────

function testHealth() {
  const res = http.get(`${BASE_URL}/health`, { tags: { name: 'health' } });
  const ok = check(res, {
    'health: status 200': (r) => r.status === 200,
    'health: has status field': (r) => {
      try { return JSON.parse(r.body).status !== undefined; } catch (e) { return false; }
    },
  });
  errorRate.add(!ok);
}

function testPublicStatus() {
  const res = http.get(`${BASE_URL}/api/status`, { tags: { name: 'status' } });
  const ok = check(res, {
    'status: 200 or 404': (r) => [200, 404].includes(r.status),
  });
  errorRate.add(!ok);
}

function testMarketData() {
  const res = http.get(
    `${BASE_URL}/api/market-data/XAUUSD`,
    { headers: headers(), tags: { name: 'market_data' } },
  );
  const ok = check(res, {
    'market_data: not 500': (r) => r.status !== 500,
  });
  errorRate.add(!ok);
}

function testAuthLogin() {
  const res = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({ email: 'loadtest@example.com', password: 'LoadTest123!' }),
    { headers: headers(), tags: { name: 'auth_login' } },
  );
  // 401 is expected for a non-existent user — testing the endpoint responds
  const ok = check(res, {
    'login: responds (not 500)': (r) => r.status !== 500,
    'login: responds fast':      (r) => r.timings.duration < 2000,
  });
  errorRate.add(!ok);
}

function testOrderEndpoint() {
  if (!AUTH_TOKEN) return;  // skip if no token provided

  const start = Date.now();
  const res = http.post(
    `${BASE_URL}/api/trading/order`,
    JSON.stringify({
      symbol: 'XAUUSD',
      side: 'buy',
      quantity: 0.01,
      order_type: 'market',
    }),
    { headers: headers(), tags: { name: 'place_order' } },
  );
  orderLatency.add(Date.now() - start);

  const ok = check(res, {
    'order: not 500': (r) => r.status !== 500,
    // 201=filled, 403=risk blocked, 401=auth, 422=validation — all acceptable
    'order: expected status': (r) => [201, 400, 401, 403, 422, 503].includes(r.status),
  });
  errorRate.add(!ok);
}

function testPositions() {
  if (!AUTH_TOKEN) return;

  const res = http.get(
    `${BASE_URL}/api/trading/positions`,
    { headers: headers(), tags: { name: 'positions' } },
  );
  const ok = check(res, {
    'positions: not 500': (r) => r.status !== 500,
  });
  errorRate.add(!ok);
}

// ── Main VU function ──────────────────────────────────────────────────────────
export default function () {
  testHealth();        sleep(0.1);
  testPublicStatus();  sleep(0.1);
  testMarketData();    sleep(0.2);
  testAuthLogin();     sleep(0.3);
  testOrderEndpoint(); sleep(0.2);
  testPositions();     sleep(0.5);
}

// ── Setup: verify the server is reachable before starting ────────────────────
export function setup() {
  const res = http.get(`${BASE_URL}/health`);
  if (res.status !== 200) {
    console.warn(`WARNING: /health returned ${res.status} — server may not be ready`);
  }
  return { base_url: BASE_URL };
}

export function teardown(data) {
  console.log(`Load test complete against ${data.base_url}`);
}