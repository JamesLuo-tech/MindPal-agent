/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 墨色 — 正文与标题
        ink: {
          DEFAULT: '#2B2229',
          soft: '#8A7A82',
        },
        // 纸色 — 背景与卡片层级
        paper: {
          DEFAULT: '#F4EAEC', // 页面底色（雾玫瑰）
          surface: '#FFFDFC', // 卡片 / 气泡
          sunk: '#EDE0DF', // 输入框等凹陷区域
        },
        // 琥珀 — 主行动色（用户气泡、按钮、品牌）
        accent: {
          50: '#FBF1E4',
          100: '#F3DCB4',
          200: '#E9C48A',
          300: '#DBA85F',
          400: '#C48F3E',
          500: '#A6631F',
          600: '#8C4F18',
          700: '#703D12',
        },
        // 鼠尾草 — 次要 / 系统反馈色（工具调用、图表、当日高亮）
        sage: {
          300: '#B7CFC1',
          400: '#8FB09E',
          500: '#5F8C7B',
          600: '#496B5D',
        },
      },
      fontFamily: {
        display: ['"Baloo 2"', '"Noto Sans SC"', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        sans: ['"Noto Sans SC"', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        '3xl': '1.5rem',
        '4xl': '1.75rem',
      },
      boxShadow: {
        ambient: '0 20px 60px -18px rgba(43, 34, 41, 0.35)',
        soft: '0 8px 24px -10px rgba(43, 34, 41, 0.22)',
      },
    },
  },
  plugins: [],
}
