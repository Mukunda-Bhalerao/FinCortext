import '@testing-library/jest-dom';

// jsdom does not implement ResizeObserver; recharts (ResponsiveContainer) needs it.
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;
}
