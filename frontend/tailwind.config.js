/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        gemini: {
          bg: '#131314',
          surface: '#1E1F20',
          border: '#282A2C',
          hover: '#2A2B2E',
          card: '#1E1F20',
          text: '#E3E3E3',
          secondary: '#C4C7C5',
          muted: '#8E918F',
          blue: '#8AB4F8',
          accent: '#4285F4',
          purple: '#9B72CB',
          coral: '#D96570',
        },
      },
      fontFamily: {
        sans: ['"Google Sans"', '"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
        arabic: ['"Google Sans"', 'Cairo', 'Tahoma', 'sans-serif'],
      },
      borderRadius: {
        '3xl': '24px',
        'pill': '28px',
      },
      animation: {
        'spin-slow': 'spin 8s linear infinite',
      },
    },
  },
  plugins: [],
}
