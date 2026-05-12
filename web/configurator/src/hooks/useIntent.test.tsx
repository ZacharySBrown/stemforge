import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCommit, useExport } from "./useIntent";

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useIntent", () => {
  beforeEach(() => {
    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      const body = init?.body ? JSON.parse(init.body as string) : null;
      // Stash for assertions.
      (globalThis as Record<string, unknown>).__lastFetch = { url, body };
      return new Response(
        JSON.stringify({ ok: true, state: null, warnings: [], errors: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("useCommit posts to /intent/commit with empty body", async () => {
    const { result } = renderHook(() => useCommit(), { wrapper: wrapper() });

    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const last = (globalThis as Record<string, unknown>).__lastFetch as {
      url: string;
      body: unknown;
    };
    expect(last.url).toContain("/intent/commit");
    expect(last.body).toEqual({});
  });

  it("useExport posts to /intent/export with the body shape", async () => {
    const { result } = renderHook(() => useExport(), { wrapper: wrapper() });

    result.current.mutate({ target: "ep133", out_path: "/tmp/out.ppak" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const last = (globalThis as Record<string, unknown>).__lastFetch as {
      url: string;
      body: unknown;
    };
    expect(last.url).toContain("/intent/export");
    expect(last.body).toEqual({ target: "ep133", out_path: "/tmp/out.ppak" });
  });

  it("propagates server errors as mutation errors", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ errors: ["bad path"] }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { result } = renderHook(() => useCommit(), { wrapper: wrapper() });
    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("bad path");
  });
});
