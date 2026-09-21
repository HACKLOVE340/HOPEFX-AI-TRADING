/**
 * frontend/src/lib/ws.ts
 * ======================
 * Opening an authenticated WebSocket, in one place.
 *
 * Every page used to build its own URL:
 *
 *     new WebSocket(`${getWsBase()}/ws/notifications?token=${token}`)
 *
 * which puts a live access token in the query string. A URL is not a private
 * channel: it is written to nginx and load-balancer access logs, kept in
 * browser history, forwarded in `Referer` on later navigations, and attached
 * to APM and error-reporting spans. Anyone with log read access ends up
 * holding a replayable credential.
 *
 * Headers avoid all of that, but the browser `WebSocket` constructor cannot
 * set one. What it can set is the subprotocol list, which the handshake sends
 * as `Sec-WebSocket-Protocol` — a header. So the token goes there:
 *
 *     new WebSocket(url, ['hopefx.auth.bearer', token])
 *
 * The server echoes `hopefx.auth.bearer` back on accept (see
 * `api/ws_live.py::ws_accept_subprotocol`); without that echo the browser
 * closes the socket immediately, which is why this must not be reimplemented
 * per call site.
 */

import { getWsBase } from './utils';

/** Must match `WS_AUTH_SUBPROTOCOL` in api/ws_live.py. */
export const WS_AUTH_SUBPROTOCOL = 'hopefx.auth.bearer';

/**
 * Open an authenticated WebSocket to `path` (e.g. `/ws/notifications`).
 *
 * `path` may carry its own query string for non-secret parameters; the token
 * is never appended to it.
 *
 * Falls back to an unauthenticated connection when `token` is empty, so a
 * caller that has not finished refreshing its session gets the server's
 * auth-required handshake rather than a malformed subprotocol list.
 */
export function openAuthenticatedWebSocket(path: string, token?: string | null): WebSocket {
  const url = `${getWsBase()}${path.startsWith('/') ? path : `/${path}`}`;
  if (!token) return new WebSocket(url);
  return new WebSocket(url, [WS_AUTH_SUBPROTOCOL, token]);
}
