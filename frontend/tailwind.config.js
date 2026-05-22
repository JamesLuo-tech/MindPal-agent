/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        coral: {
          50:  '#fef3ed',
          100: '#fde8d8',
          200: '#fbd0b5',
          300: '#f5a87a',
          400: '#f0935f',
          500: '#E8845A',
          600: '#d4704a',
          700: '#be5c3a',
        },
        peach: {
          50:  '#fdf8f4',
          100: '#fdf0e8',
          200: '#fde5d4',
          300: '#fad9c0',
          400: '#f8c9b0',
          500: '#f4b896',
        },
      },
      fontFamily: {
        sans: ['PingFang SC', 'Microsoft YaHei', 'sans-serif'],
      },
      borderRadius: {
        '3xl': '1.5rem',
        '4xl': '2rem',
      },
    },
  },
  plugins: [],
}
