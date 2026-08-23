/**
 * components/ds — the HOPEFX design-system primitives.
 *
 * Each exists because the audit measured a specific, repeated failure across
 * the 82 routes. Use these rather than re-styling a div:
 *
 *   PageHeader / Section  — every page gets one <h1> and each block an <h2>.
 *                           /dashboard rendered 0 headings, /landing 24 (F173).
 *   DataTable             — semantic, sortable, keyboard-operable, row drill-down.
 *                           Only 7 of 82 routes rendered a <table> (F174/F190).
 *   EmptyState            — states what is missing, why, and the route to fix
 *                           it; surfaces the server's own note (F189/F194/F195).
 *   RelatedPages          — 31 of 82 routes had no outbound link at all (F188).
 */
export { PageHeader, Section } from './PageHeader';
export type { PageHeaderProps, SectionProps } from './PageHeader';
export { DataTable } from './DataTable';
export type { Column, DataTableProps } from './DataTable';
export { EmptyState } from './EmptyState';
export type { EmptyStateProps } from './EmptyState';
export { RelatedPages } from './RelatedPages';
export type { RelatedLink } from './RelatedPages';
