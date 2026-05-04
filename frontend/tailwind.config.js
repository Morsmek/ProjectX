/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'aegis-green':  '#00ff9d',
        'aegis-blue':   '#0ea5e9',
        'aegis-red':    '#ef4444',
        'aegis-amber':  '#f59e0b',
        'aegis-bg':     '#030712',
        'aegis-panel':  '#0f172a',
        'aegis-border': '#1e293b',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', '"Cascadia Code"', 'monospace'],
      },
    },
  },
  plugins: [],
}
