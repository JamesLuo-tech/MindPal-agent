import { vi } from 'vitest'
import '@testing-library/jest-dom/vitest'

// jsdom 不实现 navigator.clipboard；在全局装一次桩，测试里按需 vi.mocked(...).mockResolvedValue(...)
if (typeof navigator !== 'undefined' && !navigator.clipboard) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  })
}

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
