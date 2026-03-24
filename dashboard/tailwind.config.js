/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  // 'class' strategy: add/remove 'dark' class on <html> to toggle
  darkMode: 'class',
  theme: {
    extend: {},
  },
  plugins: [],
}
