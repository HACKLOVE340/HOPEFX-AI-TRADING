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
      boxShadow: {
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
