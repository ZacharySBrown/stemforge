import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useProjectState } from "./useProjectState";
import { MockEventSource } from "../test/mockEventSource";
import type {
  SseLogEvent,
  SseProgressEvent,
  SseStateEvent,
} from "../lib/types";

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

  it("applies a `state` event to result.state", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    const evt: SseStateEvent = {
      type: "state",
      payload: {
        schema_version: 2,
        project_name: "test",
        songs: [],
      },
    };
    act(() => MockEventSource.instances[0].emit(evt));

    await waitFor(() => expect(result.current.state?.project_name).toBe("test"));
  });

  it("tracks progress events and clears on done", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    const start: SseProgressEvent = {
      type: "progress",
      payload: { operation: "export", fraction: 0.5, message: "rendering" },
    };
    act(() => MockEventSource.instances[0].emit(start));
    await waitFor(() =>
      expect(result.current.progress?.fraction).toBeCloseTo(0.5),
    );

    const done: SseProgressEvent = {
      type: "progress",
      payload: { operation: "export", fraction: 1, done: true },
    };
    act(() => MockEventSource.instances[0].emit(done));
    await waitFor(() => expect(result.current.progress).toBeNull());
  });

  it("appends log events to the logs queue", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    const log: SseLogEvent = {
      type: "log",
      payload: { level: "warn", message: "memory over budget" },
    };
    act(() => MockEventSource.instances[0].emit(log));

    await waitFor(() => expect(result.current.logs).toHaveLength(1));
    expect(result.current.logs[0].level).toBe("warn");
  });

  it("flags disconnected on transport error", async () => {
    const { result } = renderWithMock();
    await waitFor(() => expect(result.current.status).toBe("connected"));

    act(() => MockEventSource.instances[0].fail());
    await waitFor(() => expect(result.current.status).toBe("disconnected"));
  });
});
