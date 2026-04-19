import '@testing-library/jest-dom';
import { configure } from '@testing-library/dom';

// Increase waitFor timeout to 3 s — the default 1 s is too tight for
// async React state updates in jsdom under CI load.
configure({ asyncUtilTimeout: 3000 });

// NOTE: Do NOT add a global vi.mock for useApi here.
// - hooks.test.ts needs the REAL api object to test its configuration.
// - pages.test.tsx defines its own vi.mock with the correct resolved values.
// Individual test files that need a mock should define it themselves.

// Mock lightweight-charts (canvas not available in jsdom)
vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn(), update: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn(), scrollToRealTime: vi.fn() })),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    resize: vi.fn(),
  })),
  AreaSeries:        { type: 'Area' },
  LineSeries:        { type: 'Line' },
  CandlestickSeries: { type: 'Candlestick' },
  ColorType: { Solid: 'solid', VerticalGradient: 'gradient' },
}));

// Mock ResizeObserver
(globalThis as typeof globalThis & { ResizeObserver: unknown }).ResizeObserver = class ResizeObserver {
  observe()    { /* noop */ }
  unobserve()  { /* noop */ }
  disconnect() { /* noop */ }
};

// Mock WebSocket
// After open, immediately delivers a 'connected' message (no auth_required)
// so useWebSocket transitions to 'connected' status synchronously within
// a single timer tick — matching what hooks.test.ts expects after
// vi.advanceTimersByTime(50).
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN       = 1;
  static CLOSING    = 2;
  static CLOSED     = 3;

  readyState = MockWebSocket.CONNECTING;
  onopen:    ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror:   ((e: Event) => void) | null = null;
  onclose:   ((e: CloseEvent) => void) | null = null;

  constructor(public url: string) {
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
      // Deliver 'connected' without auth_required so the hook subscribes
      // and sets wsStatus = 'connected' immediately.
      this.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({ type: 'connected', auth_required: false }),
        })
      );
    }, 0);
  }

  send(_data: string) { /* noop */ }
  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }
}

(globalThis as typeof globalThis & { WebSocket: unknown }).WebSocket = MockWebSocket as unknown as typeof WebSocket;

// Suppress console.error noise in tests
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    const msg = String(args[0] ?? '');
    if (
      msg.includes('Warning: ReactDOM.render') ||
      msg.includes('act(') ||
      msg.includes('Not implemented')
    ) return;
    originalError(...args);
  };
});
afterAll(() => { console.error = originalError; });
