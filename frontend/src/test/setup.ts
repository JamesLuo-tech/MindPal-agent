import '@testing-library/jest-dom/vitest'

// jsdom 不实现 matchMedia，Companion 组件用它判断 prefers-reduced-motion，测试环境下打个桩
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList
}
