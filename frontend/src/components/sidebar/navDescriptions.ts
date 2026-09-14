/**
 * One line per destination, written from the reader's side.
 *
 * The sidebar could only ever show a label, so "TCA" and "Walk-Forward" were
 * navigable only by people who already knew what they were. A hub page and a
 * related-pages footer both have room for the sentence that makes them
 * findable by everyone else — and they must not each keep their own copy of
 * it, or the two drift and the same page acquires two identities.
 *
 * `nav_hub_reachability.test.ts` fails if a hubbed page has no line here.
 */

export const NAV_DESCRIPTIONS: Record<string, string> = {
  '/ai-assistant': 'Ask about the book, a position, or a signal in plain language.',
  '/ai-chart': 'The model annotates the chart: levels it sees, and why.',
  '/ai-chart-dashboard': 'Every annotated chart at once, across timeframes.',
  '/nuclear': 'The high-conviction engine and what it is currently refusing.',
  '/intelligence': 'Regime, sentiment and flow read together rather than separately.',
  '/ai-strategy': 'Generate a strategy from a description, then see it backtested.',
  '/pattern-detector': 'Recurring formations the model has found in this instrument.',
  '/strategy-builder': 'Compose entry, exit and sizing rules without writing code.',
  '/ai-core': 'Which model answered, what it cost, and what was refused.',

  '/performance': 'Win rate, drawdown and risk-adjusted return over time.',
  '/pnl': 'Realised and unrealised profit, by day, instrument and strategy.',
  '/transparency': 'Every claim this platform makes, with the measurement behind it.',
  '/correlation': 'What in your book moves together — and is therefore one bet.',
  '/indicators': 'Build and test your own indicators against real history.',
  '/walk-forward': 'Does the strategy survive out of sample, or only in it?',
  '/ab-testing': 'Two strategies, the same market, side by side.',
  '/tca': 'Execution quality: slippage, spread and commission versus expected.',
  '/replay': 'Replay a session tick by tick and watch the decisions again.',
  '/research': 'Long-form analysis and the data behind it.',
  '/geopolitical': 'Events that move gold, and how much they have historically.',
  '/news': 'Headlines scored for sentiment, newest first.',
  '/calendar': 'Scheduled releases that move the market, with prior impact.',
  '/prop-firm': 'Challenge progress against the daily loss and drawdown rules.',
  '/risk-calculator': 'Size a position from your stop and the risk you accept.',

  '/leaderboard': 'Who is performing, over what period, on what risk.',
  '/feed': 'Signals and commentary from traders you follow.',
  '/signals': 'Live model signals with confidence, entry and bracket.',
  '/marketplace': 'Strategies and indicators published by other traders.',
  '/affiliate': 'Your referrals, conversions and commission.',
  '/teams': 'Shared books and desks you belong to.',
  '/chat': 'Talk to other traders in real time.',
  '/copy-trading': 'Mirror another trader, with your own sizing and limits.',
  '/social': 'The public feed.',

  '/profile': 'Your public trader profile and what others can see.',
  '/wallet': 'Balance, deposits, withdrawals and payout history.',
  '/notifications': 'What you are told about, and where it reaches you.',
  '/kyc': 'Identity verification — required before a withdrawal.',
  '/sub-accounts': 'Separate books under one login.',
  '/mobile': 'Get the app, and pair this account with it.',
  '/upgrade': 'Compare plans and change yours.',
  '/academy': 'Learn the platform and the strategy behind it.',
  '/elite': 'Elite tier tools and the desk that comes with them.',
  '/support': 'Reach a human, and see your open tickets.',
  '/docs': 'Reference for every endpoint, flag and setting.',

  '/admin': 'User, plan and platform administration.',
  '/audit': 'Every privileged action, who took it and when.',
  '/security': 'Threats seen, blocked and pending review.',
  '/auto-heal': 'What the platform repaired without being asked.',
  '/observability': 'Metrics, traces and the health of every component.',
  '/ml-ops': 'Training runs, model registry and promotion gates.',
  '/support-console': 'The operator side of the support queue.',
  '/whitelabel': 'Tenant branding and per-tenant configuration.',
  '/master-control': 'Superadmin control plane.',
  '/reliability': 'SLOs, error budgets and incident history.',
  '/status': 'Live component status, as customers see it.',
};
