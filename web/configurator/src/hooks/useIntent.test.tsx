import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { buildClient } from "@/test/render";
import { QueryClientProvider } from "@tanstack/react-query";
import {
  useDeleteCuration,
  useLoadForge,
  useOpenCuration,
  useSetGroupTemplate,
  useTriggerBounce,
} from "./useIntent";

function wrapper() {
  const client = buildClient();
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

describe("useIntent", () => {
  it("useLoadForge POSTs to /forges/{slug}/load", async () => {
    let lastUrl = "";
    server.use(
      http.post("/forges/:slug/load", ({ request, params }) => {
        lastUrl = new URL(request.url).pathname;
        return HttpResponse.json({ ok: true, slug: params.slug });
      }),
    );

    const { result } = renderHook(() => useLoadForge(), { wrapper: wrapper() });
    result.current.mutate("definition-of-sound");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(lastUrl).toBe("/forges/definition-of-sound/load");
  });

  it("useOpenCuration POSTs to /curations/{name}/open", async () => {
    let lastUrl = "";
    server.use(
      http.post("/curations/:name/open", ({ request }) => {
        lastUrl = new URL(request.url).pathname;
        return HttpResponse.json({ ok: true });
      }),
    );

    const { result } = renderHook(() => useOpenCuration(), {
      wrapper: wrapper(),
    });
    result.current.mutate("verse_swap_v1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastUrl).toBe("/curations/verse_swap_v1/open");
  });

  it("useSetGroupTemplate PATCHes /curations/{name}/template", async () => {
    let lastBody: unknown = null;
    server.use(
      http.patch("/curations/:name/template", async ({ request }) => {
        lastBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );

    const { result } = renderHook(() => useSetGroupTemplate(), {
      wrapper: wrapper(),
    });
    result.current.mutate({
      name: "verse_swap_v1",
      group: "A",
      template_name: "VOCAL_HI_KEY",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // Phase 3A: the hook now translates `group` → `group_letter` to
    // match the server's PatchTemplateBody wire shape.
    expect(lastBody).toEqual({
      group_letter: "A",
      template_name: "VOCAL_HI_KEY",
    });
  });

  it("useTriggerBounce POSTs to /curations/{name}/trigger-bounce", async () => {
    let lastUrl = "";
    server.use(
      http.post("/curations/:name/trigger-bounce", ({ request }) => {
        lastUrl = new URL(request.url).pathname;
        return HttpResponse.json({ ok: true });
      }),
    );

    const { result } = renderHook(() => useTriggerBounce(), {
      wrapper: wrapper(),
    });
    result.current.mutate("verse_swap_v1");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(lastUrl).toBe("/curations/verse_swap_v1/trigger-bounce");
  });

  it("propagates server errors as mutation errors", async () => {
    server.use(
      http.delete("/curations/:name", () =>
        HttpResponse.json(
          { errors: ["cannot delete active curation"] },
          { status: 400 },
        ),
      ),
    );

    const { result } = renderHook(() => useDeleteCuration(), {
      wrapper: wrapper(),
    });
    result.current.mutate("verse_swap_v1");
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain(
      "cannot delete active curation",
    );
  });
});
