/**
 * api.ts — request-shape contract tests for the popup HTTP client.
 *
 * Coverage focus: the `__popup__` als_path sentinel that the popup must send
 * on intent endpoints which key per-host state on `als_path`. Caught during
 * the 2026-05-13 pre-UAT review (P0-4):
 *   - `openCuration(name)` previously POSTed `{}` and 422'd against the
 *     server that demanded `als_path`.
 *   - `closeActiveCuration()` had the same bug on TopBar's Close button.
 *
 * The Phase 4B server now defaults the sentinel server-side, but the popup
 * sends it explicitly anyway — both for forward compat with stricter
 * builds and to declare intent ("this is the popup, not a Live host").
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { closeActiveCuration, openCuration } from "./api";

interface CapturedRequest {
  url: string;
  method: string;
  body: string;
}

function captureFetch(): { calls: CapturedRequest[]; restore: () => void } {
  const calls: CapturedRequest[] = [];
  const original = globalThis.fetch;
  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    calls.push({
      url,
      method: (init?.method ?? "GET").toUpperCase(),
      body: typeof init?.body === "string" ? init.body : "",
    });
    return new Response(JSON.stringify({ ok: true, warnings: [], errors: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  globalThis.fetch = stub as unknown as typeof fetch;
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

describe("api — popup als_path sentinel", () => {
  let captured: ReturnType<typeof captureFetch>;

  beforeEach(() => {
    captured = captureFetch();
  });

  afterEach(() => {
    captured.restore();
  });

  it("openCuration POSTs {als_path: '__popup__'}", async () => {
    await openCuration("verse_swap_v1");

    expect(captured.calls).toHaveLength(1);
    const call = captured.calls[0];
    expect(call.method).toBe("POST");
    expect(call.url).toContain("/curations/verse_swap_v1/open");
    expect(call.body).toBe(JSON.stringify({ als_path: "__popup__" }));
    // And the body must round-trip parse cleanly (i.e. not "{}" or empty).
    const parsed = JSON.parse(call.body) as { als_path: string };
    expect(parsed.als_path).toBe("__popup__");
  });

  it("openCuration URL-encodes curation names with special characters", async () => {
    await openCuration("a curation/with weird chars");

    const call = captured.calls[0];
    expect(call.url).toContain(
      `/curations/${encodeURIComponent("a curation/with weird chars")}/open`,
    );
    // Sentinel body is independent of the path.
    expect(call.body).toBe(JSON.stringify({ als_path: "__popup__" }));
  });

  it("closeActiveCuration POSTs {als_path: '__popup__'}", async () => {
    await closeActiveCuration();

    expect(captured.calls).toHaveLength(1);
    const call = captured.calls[0];
    expect(call.method).toBe("POST");
    expect(call.url).toContain("/curations/active/close");
    expect(call.body).toBe(JSON.stringify({ als_path: "__popup__" }));
    const parsed = JSON.parse(call.body) as { als_path: string };
    expect(parsed.als_path).toBe("__popup__");
  });
});
