/**
 * Design-system primitives — contract tests.
 *
 * Each assertion corresponds to a measured failure across the 82 routes, so a
 * regression here re-opens a specific audit finding.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { PageHeader, Section, DataTable, EmptyState, RelatedPages } from '../components/ds';
import type { Column } from '../components/ds';

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('PageHeader / Section — document outline (F173)', () => {
  it('renders exactly one h1 for the page', () => {
    wrap(<PageHeader title="Portfolio" subtitle="Open positions and allocation" />);
    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent('Portfolio');
  });

  it('renders section titles as h2, below the page h1', () => {
    wrap(<Section title="Open positions"><div>rows</div></Section>);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Open positions');
  });
});

interface Row { id: string; symbol: string; pnl: number }
const rows: Row[] = [
  { id: '1', symbol: 'XAUUSD', pnl: -20 },
  { id: '2', symbol: 'EURUSD', pnl: 150 },
  { id: '3', symbol: 'GBPUSD', pnl: 40 },
];
const cols: Column<Row>[] = [
  { key: 'symbol', header: 'Symbol', render: (r) => r.symbol, sortValue: (r) => r.symbol },
  { key: 'pnl', header: 'P&L', align: 'right', render: (r) => r.pnl, sortValue: (r) => r.pnl },
];

describe('DataTable — semantics, sorting, drill-down (F174/F187/F190)', () => {
  it('renders a real table with a caption for assistive tech', () => {
    wrap(<DataTable caption="Open positions" columns={cols} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveAccessibleName('Open positions');
  });

  it('sorts on header click and announces direction via aria-sort', async () => {
    const u = userEvent.setup();
    wrap(<DataTable caption="Positions" columns={cols} rows={rows} rowKey={(r) => r.id} />);
    await u.click(screen.getByRole('button', { name: /P&L/i }));
    const header = screen.getByRole('columnheader', { name: /P&L/i });
    expect(header).toHaveAttribute('aria-sort', 'descending');
    const first = screen.getAllByRole('row')[1];
    expect(within(first).getByText('150')).toBeInTheDocument();   // desc => 150 first
  });

  it('does not mutate the caller’s rows array when sorting', async () => {
    const u = userEvent.setup();
    const original = [...rows];
    wrap(<DataTable caption="Positions" columns={cols} rows={rows} rowKey={(r) => r.id} />);
    await u.click(screen.getByRole('button', { name: /Symbol/i }));
    expect(rows).toEqual(original);
  });

  it('makes drill-down rows reachable and activatable by keyboard', async () => {
    const onRowClick = vi.fn();
    const u = userEvent.setup();
    wrap(<DataTable caption="Positions" columns={cols} rows={rows} rowKey={(r) => r.id} onRowClick={onRowClick} />);
    const row = screen.getAllByRole('link')[0];
    row.focus();
    expect(row).toHaveFocus();
    await u.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });

  it('leaves rows inert when no drill-down is given', () => {
    wrap(<DataTable caption="Positions" columns={cols} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.queryAllByRole('link')).toHaveLength(0);
  });

  it('shows the empty state instead of an empty body', () => {
    wrap(
      <DataTable caption="Positions" columns={cols} rows={[]} rowKey={(r) => r.id}
        empty={<EmptyState title="No open positions" />} />,
    );
    expect(screen.getByText('No open positions')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('sortable headers meet the 44px touch target', () => {
    wrap(<DataTable caption="Positions" columns={cols} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByRole('button', { name: /Symbol/i }).className).toMatch(/min-h-\[44px\]/);
  });
});

describe('EmptyState — say what is missing and how to fix it (F189/F194/F195)', () => {
  it('surfaces the server’s own explanation verbatim', () => {
    const note = 'Correlation matrix requires OHLCV history for at least 2 symbols.';
    wrap(<EmptyState title="Not enough history" serverNote={note} />);
    expect(screen.getByText(note)).toBeInTheDocument();
  });

  it('offers a route out rather than a dead end', () => {
    wrap(<EmptyState title="No results" action={{ label: 'Run a backtest', to: '/backtest' }} />);
    expect(screen.getByRole('link', { name: 'Run a backtest' })).toHaveAttribute('href', '/backtest');
  });

  it('actions meet the 44px touch target', () => {
    wrap(<EmptyState title="x" action={{ label: 'Go', to: '/trade' }} />);
    expect(screen.getByRole('link', { name: 'Go' }).className).toMatch(/min-h-\[44px\]/);
  });
});

describe('RelatedPages — no page is a dead end (F188/F196)', () => {
  it('renders a labelled nav landmark with working links', () => {
    wrap(<RelatedPages links={[{ to: '/journal', label: 'Trade journal', hint: 'The trades behind this' }]} />);
    const nav = screen.getByRole('navigation', { name: 'Where to next' });
    expect(within(nav).getByRole('link', { name: /Trade journal/ })).toHaveAttribute('href', '/journal');
  });

  it('renders nothing when there is nowhere to go', () => {
    const { container } = wrap(<RelatedPages links={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
