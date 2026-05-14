import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useProjectState } from "./useProjectState";
import { MockEventSource } from "../test/mockEventSource";
import type { Curation } from "../lib/api-types.generated";

describe("useProjectState", () => {
  beforeEach(() => {
    MockEventSource.reset();
  });

  function renderWithMock() {
    return renderHook(() =>
      useProjectState({
        EventSourceCtor: MockEventSource as unknown as typeof EventSource,
        url: "/state/stream",
      }),
    );
  }

  it("opens an EventSource and reports connected", async () => {
    const { result } = renderWithMock();

    expect(MockEventSource.instances).toHaveLength(1);
    expect(result.current.status).toBe("connecting");

    await waitFor(() => expect(result.current.status).toBe("connected"));
  });

  it("routes a typed `state` event to result.curation", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    const curation: Curation = {
      name: "verse_swap_v1",
      created_at: "2026-05-13T00:00:00Z",
      modified_at: "2026-05-13T00:00:00Z",
      target: { device: "ep133", groups: 4, pads_per_group: 12 },
    };
    act(() =>
      MockEventSource.instances[0].emit("state", {
        curation,
        active_curation_name: "verse_swap_v1",
      }),
    );

    await waitFor(() =>
      expect(result.current.curation?.name).toBe("verse_swap_v1"),
    );
    expect(result.current.activeCurationName).toBe("verse_swap_v1");
  });

  it("tracks progress events and clears on done", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() =>
      MockEventSource.instances[0].emit("progress", {
        operation: "export",
        fraction: 0.5,
        message: "rendering",
      }),
    );
    await waitFor(() =>
      expect(result.current.progress?.fraction).toBeCloseTo(0.5),
    );

    act(() =>
      MockEventSource.instances[0].emit("progress", {
        operation: "export",
        fraction: 1,
        done: true,
      }),
    );
    await waitFor(() => expect(result.current.progress).toBeNull());
  });

  it("appends log events to the logs queue", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() =>
      MockEventSource.instances[0].emit("log", {
        level: "warn",
        message: "memory over budget",
      }),
    );

    await waitFor(() => expect(result.current.logs).toHaveLength(1));
    expect(result.current.logs[0].level).toBe("warn");
  });

  it("flags disconnected on transport error", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() => MockEventSource.instances[0].fail());
    await waitFor(() => expect(result.current.status).toBe("disconnected"));
  });

  it("ignores `message`-typed payloads (no onmessage fallback)", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    // Server should NEVER emit unnamed events; if it does, the hook stays
    // unchanged. This test guards against accidentally re-introducing the
    // `onmessage` swallow-everything fallback.
    act(() =>
      MockEventSource.instances[0].emit("message", {
        type: "state",
        payload: { curation: null },
      }),
    );

    expect(result.current.curation).toBeNull();
  });

  // ── P0-4: Phase 4B broadcaster shape ──────────────────────────────────────
  // The Phase 4B server emits `{kind: "curations", curations, active_curations,
  // stale_by_curation}` rather than the legacy `{curation, active_curation_name}`
  // snapshot. The handler must recognize both shapes and, when the popup is
  // the active host, hydrate the full Curation via `fetchCuration(name)`.

  it("handles kind:'curations' shape — resolves popup sentinel + fetches curation", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() =>
      MockEventSource.instances[0].emit("state", {
        kind: "curations",
        active_curations: { __popup__: "verse_swap_v1" },
      }),
    );

    // Name updates synchronously.
    await waitFor(() =>
      expect(result.current.activeCurationName).toBe("verse_swap_v1"),
    );
    // Then the fetched curation lands (msw handler returns CURATION_FRESH).
    await waitFor(() =>
      expect(result.current.curation?.name).toBe("verse_swap_v1"),
    );
  });

  it("handles kind:'curations' shape — empty active_curations clears state", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    // Seed some state so we can observe it being cleared.
    act(() =>
      MockEventSource.instances[0].emit("state", {
        curation: {
          name: "verse_swap_v1",
          created_at: "2026-05-13T00:00:00Z",
          modified_at: "2026-05-13T00:00:00Z",
          target: { device: "ep133", groups: 4, pads_per_group: 12 },
        } satisfies Curation,
        active_curation_name: "verse_swap_v1",
      }),
    );
    await waitFor(() =>
      expect(result.current.activeCurationName).toBe("verse_swap_v1"),
    );

    // Phase 4B broadcaster with no active hosts clears the popup's view.
    act(() =>
      MockEventSource.instances[0].emit("state", {
        kind: "curations",
        active_curations: {},
      }),
    );

    await waitFor(() => expect(result.current.curation).toBeNull());
    expect(result.current.activeCurationName).toBeNull();
  });

  it("does NOT fall back to other-host curation entries (regression for explicit close)", async () => {
    // When the user closes the popup's active curation, the server removes
    // POPUP_ALS_SENTINEL from `active_curations`. Earlier handler code fell
    // back to `Object.values(active).find(...)` which incorrectly re-bound
    // the popup to a stale entry from a different `.als` host (or leftover
    // dev/test fixtures like `/tmp/demo.als`), so the close looked like a
    // noop. The popup must ONLY honor its own sentinel.
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    // Seed a popup-active curation first.
    act(() =>
      MockEventSource.instances[0].emit("state", {
        kind: "curations",
        active_curations: { __popup__: "verse_swap_v1" },
      }),
    );
    await waitFor(() =>
      expect(result.current.activeCurationName).toBe("verse_swap_v1"),
    );

    // Server broadcasts after `__popup__` is cleared but another host still
    // has an active curation. Popup should clear, NOT pick up the other host.
    act(() =>
      MockEventSource.instances[0].emit("state", {
        kind: "curations",
        active_curations: { "/tmp/demo.als": "partial" },
      }),
    );

    await waitFor(() => expect(result.current.activeCurationName).toBeNull());
    expect(result.current.curation).toBeNull();
  });

  it("legacy snapshot shape still routes to curation state (backward compat)", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    const curation: Curation = {
      name: "verse_swap_v1",
      created_at: "2026-05-13T00:00:00Z",
      modified_at: "2026-05-13T00:00:00Z",
      target: { device: "ep133", groups: 4, pads_per_group: 12 },
    };
    act(() =>
      MockEventSource.instances[0].emit("state", {
        curation,
        active_curation_name: "verse_swap_v1",
      }),
    );

    await waitFor(() =>
      expect(result.current.curation?.name).toBe("verse_swap_v1"),
    );
    expect(result.current.activeCurationName).toBe("verse_swap_v1");
  });
});
