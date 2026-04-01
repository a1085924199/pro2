/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Noto Sans SC', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        primary: {
          50:  '#eef6ff',
          100: '#d9ebff',
          200: '#bbdaff',
          300: '#8ec2ff',
          400: '#599eff',
          500: '#3378ff',
          600: '#1a57f5',
          700: '#1440e1',
          800: '#1735b6',
          900: '#19308f',
          950: '#141f57',
        },
        accent: {
          DEFAULT: '#00d4aa',
          dark:    '#00a884',
          light:   '#4fffd7',
        },
        surface: {
          DEFAULT: '#0d1117',
          card:    '#161b22',
          border:  '#21262d',
          hover:   '#1c2128',
        },
      },
      backgroundImage: {
        'grid-pattern': "url(\"data:image/svg+xml,%3Csvg width='40' height='40' viewBox='0 0 40 40' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.03'%3E%3Cpath d='M0 0h40v1H0zM0 0v40h1V0z'/%3E%3C/g%3E%3C/svg%3E\")",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float': 'float 6s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        glow: {
          'from': { boxShadow: '0 0 10px #3378ff40' },
          'to':   { boxShadow: '0 0 30px #3378ff80, 0 0 60px #3378ff20' },
        },
      },
    },
  },
  plugins: [],
  corePlugins: {
    preflight: false,
  },
}
