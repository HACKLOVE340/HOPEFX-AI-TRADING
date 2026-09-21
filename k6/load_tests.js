/**
 * k6/load_tests.js
 * ================
 * Production load test for HOPEFX API.
 *
 * Scenarios
 * ---------
 *   smoke      — 1 VU, 30 s  (CI gate: verify endpoints respond)
 *   load       — ramp 0→50 VUs over 2 min, hold 5 min, ramp down 1 min
 *   soak       — 100 VUs for 30 min  (memory leak / connection pool exhaustion)
 *   spike      — ramp to 500 VUs in 30 s, recover  (thundering herd)
 *   stress     — ramp 0→200 VUs in 5 min, hold 10 min  (find breaking point)
 *   breakpoint — ramp 0→1000 VUs over 20 min  (find absolute limit)
 *
 * Usage
 * -----
 *   k6 run k6/load_tests.js
 *   k6 run --env BASE_URL=https://staging.hopefx.io --env SCENARIO=load k6/load_tests.js
 *   k6 run --env SCENARIO=soak --out json=results/soak.json k6/load_tests.js
 *
 * Environment variables
 * ---------------------
 *   BASE_URL      API base URL (default: http://localhost:8000)
 *   SCENARIO      smoke | load | soak | spike | stress | breakpoint
 *   AUTH_TOKEN    Bearer token for authenticated endpoints
 *   SIGNAL_SYMBOL Symbol for signal/ML tests (default: XAUUSD)
 *   THINK_TIME    Sleep multiplier in seconds (default: 1.0)
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import ws from 'k6/ws';
import { Counter, Rate, Trend } from 'k6/metrics';

// ── Custom metrics ────────────────────────────────────────────────────────────
const errorRate      = new Rate('error_rate');
const orderLatency   = new Trend('order_latency_ms',   true);
const signalLatency  = new Trend('signal_latency_ms',  true);
const mlLatency      = new Trend('ml_latency_ms',      true);
const macroLatency   = new Trend('macro_latency_ms',   true);
const wsConnects     = new Counter('ws_connects');
const wsMessages     = new Counter('ws_messages_received');
const authFailures   = new Counter('auth_failures');
const riskBlocks     = new Counter('risk_blocks');
const ordersFilled   = new Counter('orders_filled');
const rateLimitHits  = new Counter('rate_limit_hits');

// ── Config ────────────────────────────────────────────────────────────────────
const BASE_URL   = __ENV.BASE_URL     || 'http://localhost:8000';
const WS_URL     = BASE_URL.replace(/^http/, 'ws');
const AUTH_TOKEN = __ENV.AUTH_TOKEN   || '';
const SCENARIO   = __ENV.SCENARIO    || 'smoke';
const SIGNAL_SYM = __ENV.SIGNAL_SYMBOL || 'XAUUSD';
const THINK_TIME = parseFloat(__ENV.THINK_TIME || '1.0');
const SYMBOLS    = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'];

function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// ── Scenario definitions ──────────────────────────────────────────────────────
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
      { duration: '2m',  target: 50  },
      { duration: '5m',  target: 50  },
      { duration: '1m',  target: 0   },
    ],
    gracefulRampDown: '30s',
  },
  soak: {
    executor: 'constant-vus',
    vus: 100,
    duration: '30m',
  },
  spike: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '30s', target: 10  },
      { duration: '30s', target: 500 },
      { duration: '1m',  target: 10  },
      { duration: '30s', target: 0   },
    ],
    gracefulRampDown: '30s',
  },
  stress: {
    executor: 'ramping-vus',
    startVUs: 0,
    stages: [
      { duration: '2m',  target: 50  },
      { duration: '2m',  target: 100 },
      { duration: '2m',  target: 150 },
      { duration: '2m',  target: 200 },
      { duration: '10m', target: 200 },
      { duration: '2m',  target: 0   },
    ],
    gracefulRampDown: '30s',
  },
  breakpoint: {
    executor: 'ramping-arrival-rate',
    startRate: 10,
    timeUnit: '1s',
    preAllocatedVUs: 100,
    maxVUs: 1000,
    stages: [
      { duration: '5m',  target: 50  },
      { duration: '5m',  target: 100 },
      { duration: '5m',  target: 200 },
      { duration: '5m',  target: 500 },
    ],
  },
};

// http_req_failed counts every 4xx as a failure by default, but this suite's own
// checks accept 401/403/404 as valid outcomes (unauthenticated probes, endpoints
// that vary by deployment). Counting them made a <1% threshold unreachable no
// matter how healthy the server was. Narrowing "failed" to 5xx makes the metric
// mean what a load test should measure — the server erroring under load — while
// the per-group checks keep asserting the semantic expectations.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

export const options = {
  scenarios: {
    default: SCENARIOS[SCENARIO] || SCENARIOS.smoke,
  },
  thresholds: {
    http_req_duration:  ['p(95)<500'],   // p95 < 500 ms
    order_latency_ms:   ['p(99)<1000'],  // p99 order < 1 s
    signal_latency_ms:  ['p(95)<300'],   // p95 signal < 300 ms
    ml_latency_ms:      ['p(95)<800'],   // p95 ML inference < 800 ms
    macro_latency_ms:   ['p(95)<400'],   // p95 macro endpoint < 400 ms
    error_rate:         ['rate<0.01'],   // < 1% errors
    http_req_failed:    ['rate<0.01'],
  },
  gracefulStop: '30s',
  noConnectionReuse: false,
  userAgent: 'k6-hopefx-loadtest/2.0',
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function headers(extra) {
  const h = { 'Content-Type': 'application/json', 'Accept': 'application/json' };
  if (AUTH_TOKEN) h['Authorization'] = 'Bearer ' + AUTH_TOKEN;
  return Object.assign(h, extra || {});
}

function checkOk(res, name, allowed) {
  allowed = allowed || [200];
  const ok = check(res, {
    [name + ': status in allowed']: (r) => allowed.indexOf(r.status) !== -1,
    [name + ': not 500']:           (r) => r.status !== 500,
    [name + ': not 502/503/504']:   (r) => [502, 503, 504].indexOf(r.status) === -1,
  });
  errorRate.add(!ok);
  if (res.status === 429) rateLimitHits.add(1);
  return ok;
}

// ── Test functions ────────────────────────────────────────────────────────────

function testHealth() {
  group('health', () => {
    const res = http.get(BASE_URL + '/health', { tags: { name: 'health' }, timeout: '5s' });
    checkOk(res, 'health', [200]);
  });
}

function testPublicStatus() {
  group('public_status', () => {
    const res = http.get(BASE_URL + '/api/status', { tags: { name: 'status' } });
    checkOk(res, 'status', [200, 404]);
  });
}

function testMarketData() {
  group('market_data', () => {
    const symbol = randomItem(SYMBOLS);
    // /api/market-data/<symbol> does not exist and never did — every request
    // to it 404'd, and checkOk accepted 404, so this scenario reported
    // comfortable latency for a route that does no work. The real
    // bid/ask endpoint is /api/trading/prices; OHLCV takes the symbol.
    const res = http.get(BASE_URL + '/api/trading/ohlcv/' + symbol + '?timeframe=M5&limit=100', {
      headers: headers(), tags: { name: 'market_data' },
    });
    checkOk(res, 'market_data', [200, 401, 403, 503]);
  });
}

function testSignalEndpoint() {
  group('signal', () => {
    const start = Date.now();
    const res = http.get(BASE_URL + '/api/signals/latest?symbol=' + SIGNAL_SYM, {
      headers: headers(), tags: { name: 'signal_latest' },
    });
    signalLatency.add(Date.now() - start);
    checkOk(res, 'signal', [200, 401, 403, 404, 503]);
  });
}

function testMLPredict() {
  group('ml_predict', () => {
    const start = Date.now();
    // POST, not GET: /api/ml/predict/{symbol} is registered for POST only, so
    // the GET this used to send never reached the handler and the ML latency
    // budget measured a routing miss.
    const res = http.post(BASE_URL + '/api/ml/predict/' + SIGNAL_SYM, '{}', {
      headers: headers(), tags: { name: 'ml_predict' },
    });
    mlLatency.add(Date.now() - start);
    checkOk(res, 'ml_predict', [200, 401, 403, 404, 503]);
  });
}

function testMLStatus() {
  group('ml_status', () => {
    // /api/ml/status is not a registered route — the app serves
    // /api/ml/drift/status, /api/ml/anomaly/status and /api/ml/rl/status, plus
    // /api/superadmin/ml/status behind the superadmin gate. This probed a 404
    // on every iteration and counted it as a pass.
    const res = http.get(BASE_URL + '/api/ml/drift/status', {
      headers: headers(), tags: { name: 'ml_status' },
    });
    checkOk(res, 'ml_status', [200, 503]);
  });
}

function testMacroSnapshot() {
  group('macro_snapshot', () => {
    const start = Date.now();
    const res = http.get(BASE_URL + '/api/macro/snapshot', {
      headers: headers(), tags: { name: 'macro_snapshot' },
    });
    macroLatency.add(Date.now() - start);
    checkOk(res, 'macro_snapshot', [200, 503]);
  });
}

function testMacroStore() {
  group('macro_store', () => {
    const start = Date.now();
    const res = http.get(BASE_URL + '/api/macro/store', {
      headers: headers(), tags: { name: 'macro_store' },
    });
    macroLatency.add(Date.now() - start);
    checkOk(res, 'macro_store', [200, 503]);
  });
}

function testMacroFeatures() {
  group('macro_features', () => {
    const res = http.get(BASE_URL + '/api/macro/features', {
      headers: headers(), tags: { name: 'macro_features' },
    });
    checkOk(res, 'macro_features', [200, 503]);
  });
}

function testAuthLogin() {
  group('auth_login', () => {
    const res = http.post(
      BASE_URL + '/auth/login',
      JSON.stringify({ email: 'loadtest@example.com', password: 'LoadTest123!' }),  // pragma: allowlist secret
      { headers: headers(), tags: { name: 'auth_login' } },
    );
    const ok = check(res, {
      'login: responds (not 500)': (r) => r.status !== 500,
      'login: responds fast':      (r) => r.timings.duration < 3000,
    });
    if (res.status === 401) authFailures.add(1);
    errorRate.add(!ok);
  });
}

function testOrderEndpoint() {
  if (!AUTH_TOKEN) return;
  group('place_order', () => {
    const symbol = randomItem(SYMBOLS);
    const side   = randomItem(['buy', 'sell']);
    const start  = Date.now();
    const res = http.post(
      BASE_URL + '/api/trading/order',
      JSON.stringify({ symbol, side, quantity: 0.01, order_type: 'market' }),
      { headers: headers(), tags: { name: 'place_order' } },
    );
    orderLatency.add(Date.now() - start);
    const ok = check(res, {
      'order: not 500':         (r) => r.status !== 500,
      'order: expected status': (r) => [201, 400, 401, 403, 422, 429, 503].indexOf(r.status) !== -1,
    });
    errorRate.add(!ok);
    if (res.status === 201) ordersFilled.add(1);
    if (res.status === 403) riskBlocks.add(1);
    if (res.status === 429) rateLimitHits.add(1);
  });
}

function testPositions() {
  if (!AUTH_TOKEN) return;
  group('positions', () => {
    const res = http.get(BASE_URL + '/api/trading/positions', {
      headers: headers(), tags: { name: 'positions' },
    });
    checkOk(res, 'positions', [200, 401, 403, 503]);
  });
}

function testAccountInfo() {
  if (!AUTH_TOKEN) return;
  group('account_info', () => {
    const res = http.get(BASE_URL + '/api/trading/account', {
      headers: headers(), tags: { name: 'account_info' },
    });
    checkOk(res, 'account_info', [200, 401, 403, 404, 503]);
  });
}

function testRiskStatus() {
  group('risk_status', () => {
    // Was /api/risk/status, which is not a registered route. The /api/risk
    // prefix belongs to the prop-firm and calculator routers; the risk metrics
    // snapshot is /api/trading/risk.
    const res = http.get(BASE_URL + '/api/trading/risk', {
      headers: headers(), tags: { name: 'risk_status' },
    });
    checkOk(res, 'risk_status', [200, 401, 403, 503]);
  });
}

function testPrometheusMetrics() {
  group('prometheus', () => {
    const res = http.get(BASE_URL + '/metrics', { tags: { name: 'prometheus_metrics' } });
    checkOk(res, 'prometheus', [200, 403, 404]);
  });
}

/**
 * Rate-limit probe: send 15 rapid requests to an auth endpoint and verify
 * that at least one 429 is returned (rate limiter is active).
 * Only runs in smoke/load scenarios to avoid inflating error counts.
 */
function testRateLimitEnforced() {
  if (SCENARIO !== 'smoke' && SCENARIO !== 'load') return;
  group('rate_limit_probe', () => {
    let got429 = false;
    for (let i = 0; i < 15; i++) {
      const res = http.post(
        BASE_URL + '/auth/login',
        JSON.stringify({ email: 'ratelimit@example.com', password: 'wrong' }),  // pragma: allowlist secret
        {
          headers: headers(),
          tags: { name: 'rate_limit_probe' },
          // This group sends deliberately-wrong credentials and wants a 429.
          // Its rejections are counted by the module-level responseCallback
          // above, which treats every 4xx as expected; enumerating statuses
          // here instead is how this got it wrong first time (the app answers
          // 403, not 401, so all 60 probe requests were counted as failures).
        },
      );
      if (res.status === 429) { got429 = true; break; }
    }
    check({ got429 }, {
      'rate limiter active (got 429 after rapid requests)': (d) => d.got429,
    });
  });
}

/**
 * WebSocket smoke test: connect to /ws/live, wait for one message, disconnect.
 * Counts successful connections and messages received.
 */
function testWebSocket() {
  if (SCENARIO !== 'smoke') return;  // WS test only in smoke to avoid VU exhaustion
  group('websocket', () => {
    const url = WS_URL + '/ws/live';
    const params = AUTH_TOKEN ? { headers: { Authorization: 'Bearer ' + AUTH_TOKEN } } : {};
    const res = ws.connect(url, params, (socket) => {
      wsConnects.add(1);
      socket.on('open', () => {
        socket.send(JSON.stringify({ type: 'subscribe', symbol: SIGNAL_SYM }));
      });
      socket.on('message', (msg) => {
        wsMessages.add(1);
        socket.close();
      });
      socket.on('error', () => { socket.close(); });
      socket.setTimeout(() => { socket.close(); }, 5000);
    });
    check(res, {
      'ws: connected (101 or 200)': (r) => r && (r.status === 101 || r.status === 200),
    });
  });
}

// ── Main VU function ──────────────────────────────────────────────────────────
export default function () {
  testHealth();              sleep(0.1 * THINK_TIME);
  testPublicStatus();        sleep(0.1 * THINK_TIME);
  testMarketData();          sleep(0.2 * THINK_TIME);
  testSignalEndpoint();      sleep(0.2 * THINK_TIME);
  testMLStatus();            sleep(0.1 * THINK_TIME);
  testMLPredict();           sleep(0.3 * THINK_TIME);
  testMacroSnapshot();       sleep(0.1 * THINK_TIME);
  testMacroStore();          sleep(0.1 * THINK_TIME);
  testMacroFeatures();       sleep(0.1 * THINK_TIME);
  testRiskStatus();          sleep(0.1 * THINK_TIME);
  testPrometheusMetrics();   sleep(0.1 * THINK_TIME);
  testAuthLogin();           sleep(0.3 * THINK_TIME);
  testWebSocket();           sleep(0.2 * THINK_TIME);
  testOrderEndpoint();       sleep(0.2 * THINK_TIME);
  testPositions();           sleep(0.2 * THINK_TIME);
  testAccountInfo();         sleep(0.2 * THINK_TIME);
  // Last, deliberately. The limiter is per caller, not per endpoint, so once
  // this group trips it every request after it in the same iteration is 429'd.
  // Running it mid-iteration made all nine later groups fail 5 of 9 checks and
  // read as endpoint outages rather than as the probe doing its job.
  testRateLimitEnforced();   sleep(0.5 * THINK_TIME);
}

// ── Setup ─────────────────────────────────────────────────────────────────────
export function setup() {
  const res = http.get(BASE_URL + '/health', { timeout: '10s' });
  if (res.status !== 200) {
    console.warn('WARNING: /health returned ' + res.status + ' — server may not be ready');
  }
  console.log('Load test starting: scenario=' + SCENARIO + ' base_url=' + BASE_URL);
  if (!AUTH_TOKEN) {
    console.log('INFO: AUTH_TOKEN not set — authenticated endpoints will be skipped');
  }
  return { base_url: BASE_URL, scenario: SCENARIO, started_at: new Date().toISOString() };
}

// ── Teardown ──────────────────────────────────────────────────────────────────
export function teardown(data) {
  console.log(
    'Load test complete: scenario=' + data.scenario +
    ' base_url=' + data.base_url +
    ' started_at=' + data.started_at,
  );
}
