/**
 * msw setup for unit/component tests.
 *
 * The server starts in tests via `server.listen()` (called from setup.ts).
 * Per-test, callers can `server.use(...)` to override defaults.
 */

import { setupServer } from "msw/node";
import { okHandlers } from "./handlers";

export const server = setupServer(...okHandlers);
