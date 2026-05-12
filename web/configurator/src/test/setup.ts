import "@testing-library/jest-dom/vitest";

/**
 * Vitest setup. happy-dom + RTL matchers, no JSDOM.
 *
 * happy-dom is fast and supports everything we need (EventSource is mocked
 * per-test, not relied on globally).
 */
