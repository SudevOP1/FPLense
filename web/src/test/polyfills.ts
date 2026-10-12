// jsdom replaces AbortController/AbortSignal, but Node's fetch/Request (undici) only accepts its
// own AbortSignal, so TanStack Query's and React Router's signals would make every request throw.
// Tests don't need cancellation, so signals are dropped before they reach undici. This is its own
// setup file so it runs before MSW is imported and wraps fetch.
const NativeRequest = globalThis.Request;
const withoutSignal = (init?: RequestInit) => (init?.signal ? { ...init, signal: undefined } : init);

globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(input, withoutSignal(init));
  }
} as typeof Request;

const nativeFetch = globalThis.fetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
  nativeFetch(input, withoutSignal(init))) as typeof fetch;

export {};
