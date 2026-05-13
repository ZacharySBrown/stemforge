import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

/**
 * Vitest setup. happy-dom + RTL matchers + msw HTTP mocking.
 *
 * msw runs in `node` interception mode (no service worker), so fetch
 * calls in tests hit our handlers without leaving the test process.
 */

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
