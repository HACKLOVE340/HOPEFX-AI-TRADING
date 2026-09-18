import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Override default screens to add xs breakpoint for very small phones
    screens: {
      xs:  '375px',
      sm:  '640px',
      md:  '768px',
      lg:  '1024px',
      xl:  '1280px',
      '2xl': '1536px',
    },
    extend: {
      colors: {
        // Terminal palette
        terminal: {
          bg:       '#080c14',
          surface:  '#0d1421',
          raised:   '#111827',
          border:   '#1e2d3d',
          muted:    '#1a2535',
        },
        // Neon accents
        neon: {
          blue:   '#00d4ff',
          green:  '#00ff88',
          amber:  '#ffb800',
          red:    '#ff3b5c',
          purple: '#a855f7',
          cyan:   '#06b6d4',
        },
        // P&L
        bull:  '#00e676',
        bear:  '#ff1744',
        // Signal confidence
        conf: {
          high:   '#00e676',
          medium: '#ffb800',
          low:    '#ff6b35',
        },
      },
      fontFamily: {
        mono:  ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'monospace'],
        sans:  ['Inter', 'system-ui', 'sans-serif'],
        display: ['Inter', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      animation: {
        'pulse-fast':   'pulse 0.8s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink':        'blink 1s step-end infinite',
        'slide-in-up':  'slideInUp 0.2s ease-out',
        'fade-in':      'fadeIn 0.15s ease-out',
        'ticker-scroll': 'tickerScroll 30s linear infinite',
        'glow':         'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0' },
        },
        slideInUp: {
          from: { transform: 'translateY(8px)', opacity: '0' },
          to:   { transform: 'translateY(0)',   opacity: '1' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        tickerScroll: {
          from: { transform: 'translateX(0)' },
          to:   { transform: 'translateX(-50%)' },
        },
        glow: {
          from: { boxShadow: '0 0 4px currentColor' },
          to:   { boxShadow: '0 0 12px currentColor, 0 0 24px currentColor' },
        },
      },
      // ── Semantic scale, 2026-09-14 ────────────────────────────────────
      //
      // Every entry below resolves to a token in src/index.css rather than to
      // a literal, so a class written here follows the theme and the surface.
      // `bg-surface` is correct in dark, in light, and on an AI page; the
      // `terminal-*` and `neon-*` groups above are fixed literals and are not
      // — they are kept because 201 files reference them, and they are the
      // thing new code should stop reaching for.
      //
      // Naming is by ROLE, never by appearance: `text-dim`, not `text-grey`.
      // Five different greys were doing "muted" before there were names for
      // the jobs, which is how the pages drifted apart in the first place.
      textColor: {
        ink:       'var(--text)',
        strong:    'var(--text-strong)',
        dim:       'var(--text-dim)',
        muted:     'var(--text-muted)',
        faint:     'var(--text-faint)',
        accent:    'var(--accent)',
        'on-accent': 'var(--accent-ink)',
        link:      'var(--link)',
        gain:      'var(--gain)',
        loss:      'var(--loss)',
        warn:      'var(--warn)',
        info:      'var(--info)',
        model:     'var(--ai-model)',
      },
      backgroundColor: {
        base:      'var(--bg)',
        surface:   'var(--surface)',
        raised:    'var(--raised)',
        sunken:    'var(--sunken)',
        hover:     'var(--surface-hover)',
        accent:    'var(--accent)',
        'accent-soft': 'var(--accent-soft)',
        overlay:   'var(--overlay)',
      },
      borderColor: {
        edge:      'var(--border)',
        'edge-strong': 'var(--border-strong)',
        hairline:  'var(--hairline)',
        accent:    'var(--accent)',
        focus:     'var(--focus)',
      },
      ringColor: {
        focus:     'var(--focus)',
        accent:    'var(--accent)',
      },
      fontSize: {
        // The seven-step scale. A page picks a ROLE; it does not pick a number.
        micro: ['var(--fs-micro)', { lineHeight: 'var(--lh-snug)' }],
        label: ['var(--fs-label)', { lineHeight: 'var(--lh-snug)', letterSpacing: 'var(--tracking-label)' }],
        body:  ['var(--fs-body)',  { lineHeight: 'var(--lh-body)' }],
        value: ['var(--fs-value)', { lineHeight: 'var(--lh-snug)' }],
        title: ['var(--fs-title)', { lineHeight: 'var(--lh-snug)' }],
        head:  ['var(--fs-head)',  { lineHeight: 'var(--lh-tight)' }],
        hero:  ['var(--fs-hero)',  { lineHeight: 'var(--lh-tight)' }],
        // Display — above hero. For a page title or the one figure the screen
        // is for, never for sizing an emoji: see index.css.
        'display-sm': ['var(--fs-display-sm)', { lineHeight: 'var(--lh-tight)' }],
        display:      ['var(--fs-display)',    { lineHeight: 'var(--lh-tight)' }],
        'display-lg': ['var(--fs-display-lg)', { lineHeight: 'var(--lh-tight)' }],
      },
      borderRadius: {
        sm2:  'var(--r-sm)',
        md2:  'var(--r-md)',
        lg2:  'var(--r-lg)',
        pill: 'var(--r-pill)',
      },
      transitionDuration: {
        fast: 'var(--dur-fast)',
        base: 'var(--dur-base)',
        slow: 'var(--dur-slow)',
      },
      transitionTimingFunction: {
        out:    'var(--ease-out)',
        smooth: 'var(--ease-in-out)',
      },
      boxShadow: {
        e1: 'var(--e-1)',
        e2: 'var(--e-2)',
        e3: 'var(--e-3)',
        'terminal': '0 0 0 1px rgba(0,212,255,0.1), 0 4px 24px rgba(0,0,0,0.6)',
        'neon-blue': '0 0 8px rgba(0,212,255,0.4)',
        'neon-green': '0 0 8px rgba(0,255,136,0.4)',
        'neon-red':   '0 0 8px rgba(255,59,92,0.4)',
        'panel':      '0 1px 3px rgba(0,0,0,0.4), 0 0 0 1px rgba(30,45,61,0.8)',
      },
      backgroundImage: {
        'grid-terminal': `
          linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px)
        `,
        'gradient-bull': 'linear-gradient(135deg, rgba(0,230,118,0.15), transparent)',
        'gradient-bear': 'linear-gradient(135deg, rgba(255,23,68,0.15), transparent)',
      },
      backgroundSize: {
        'grid-terminal': '32px 32px',
      },
      spacing: {
        // Density scale — pro-max. Tighter than a consumer app on purpose:
        // this is an instrument, and a trader wants more of the book on
        // screen rather than more air around less of it.
        s1: 'var(--sp-1)', s2: 'var(--sp-2)', s3: 'var(--sp-3)', s4: 'var(--sp-4)',
        s5: 'var(--sp-5)', s6: 'var(--sp-6)', s7: 'var(--sp-7)', s8: 'var(--sp-8)',
        card: 'var(--pad-card)',
        row:  'var(--pad-row)',
        grid: 'var(--gap-grid)',
        // Safe-area aware spacing tokens
        'safe-top':    'env(safe-area-inset-top,    0px)',
        'safe-right':  'env(safe-area-inset-right,  0px)',
        'safe-bottom': 'env(safe-area-inset-bottom, 0px)',
        'safe-left':   'env(safe-area-inset-left,   0px)',
        // Sidebar widths
        'sidebar':           '224px',
        'sidebar-collapsed': '60px',
        // Mobile top bar
        'topbar': '56px',
      },
      minHeight: {
        'touch': '44px',
      },
      minWidth: {
        'touch': '44px',
      },
      zIndex: {
        'sidebar':  '20',
        'backdrop': '30',
        'topbar':   '40',
        'modal':    '50',
        'toast':    '60',
        'tooltip':  '70',
      },
    },
  },
  plugins: [],
};

export default config;
