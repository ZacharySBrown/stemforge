import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { CURATION_FRESH, CURATION_STALE } from "@/test/fixtures";
import { ActiveCuration } from "./ActiveCuration";

describe("ActiveCuration", () => {
  it("renders the empty state when no curation is active", () => {
    renderWithProviders(<ActiveCuration curation={null} />);
    expect(screen.getByTestId("active-curation-empty")).toBeInTheDocument();
    expect(screen.getByText(/no active curation/i)).toBeInTheDocument();
  });

  it("renders the curation name + groups when populated", async () => {
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    expect(screen.getByText("verse_swap_v1")).toBeInTheDocument();

    const groups = screen.getAllByTestId("active-curation-group");
    expect(groups).toHaveLength(2); // A, B per fixture

    // pads from group A.
    const padCells = screen.getAllByTestId("pad-cell");
    expect(padCells.length).toBeGreaterThan(0);

    // Template selectors hydrate from group.template.
    const aTemplate = screen.getByTestId("group-A-template") as HTMLSelectElement;
    expect(aTemplate.value).toBe("VOCAL_HI_KEY");

    // Label inputs hydrate.
    const aLabel = screen.getByTestId("group-A-label") as HTMLInputElement;
    expect(aLabel.value).toBe("vocal hi");
  });

  it("renders a stale dot on pads whose source-forge hash has diverged", async () => {
    // CURATION_STALE references definition-of-sound at OLD hash; the
    // mocked /forges returns it at FRESH. Pads sourced from
    // definition-of-sound should surface the stale-badge-pad marker.
    renderWithProviders(<ActiveCuration curation={CURATION_STALE} />);

    await waitFor(() =>
      expect(
        screen.queryAllByTestId("stale-badge-pad").length,
      ).toBeGreaterThan(0),
    );
  });

  it("renders NO stale dot when the curation's refs match the forges' hashes", async () => {
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    // Let the forges query resolve, then assert no stale pads.
    await waitFor(() => {
      // The pads are there.
      expect(screen.getAllByTestId("pad-cell").length).toBeGreaterThan(0);
    });
    // After resolution there should be no stale markers.
    expect(screen.queryAllByTestId("stale-badge-pad")).toHaveLength(0);
  });

  // ── Phase 3A: template selector wired to GET /templates + PATCH ──────────

  it("template selector populates options from GET /templates", async () => {
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    const aTemplate = (await screen.findByTestId(
      "group-A-template",
    )) as HTMLSelectElement;
    // The msw-mocked TEMPLATE_INDEX_OK has three entries; we surface each
    // as an <option>. The "VOCAL_HI_KEY" option lets the fixture's saved
    // template render without falling into the "(missing)" branch.
    await waitFor(() => {
      const optionValues = Array.from(aTemplate.options).map((o) => o.value);
      expect(optionValues).toContain("drum-rack-classic");
      expect(optionValues).toContain("vocal-bloom");
      expect(optionValues).toContain("VOCAL_HI_KEY");
    });
    // The empty "no template" option is always first.
    expect(aTemplate.options[0].value).toBe("");
  });

  it("selecting a template fires PATCH /curations/{name}/template with group_letter", async () => {
    const calls: Array<{ name: string; body: unknown }> = [];
    server.use(
      http.patch("/curations/:name/template", async ({ params, request }) => {
        const body = await request.json();
        calls.push({ name: String(params.name), body });
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    const aTemplate = (await screen.findByTestId(
      "group-A-template",
    )) as HTMLSelectElement;
    // Wait until the populated options have hydrated.
    await waitFor(() => {
      expect(
        Array.from(aTemplate.options).some(
          (o) => o.value === "drum-rack-classic",
        ),
      ).toBe(true);
    });

    const user = userEvent.setup();
    await user.selectOptions(aTemplate, "drum-rack-classic");

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[calls.length - 1].name).toBe("verse_swap_v1");
    expect(calls[calls.length - 1].body).toEqual({
      group_letter: "A",
      template_name: "drum-rack-classic",
    });
  });

  it("selecting '— no template —' clears via template_name: null", async () => {
    const calls: Array<{ body: unknown }> = [];
    server.use(
      http.patch("/curations/:name/template", async ({ request }) => {
        calls.push({ body: await request.json() });
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    const aTemplate = (await screen.findByTestId(
      "group-A-template",
    )) as HTMLSelectElement;
    // CURATION_FRESH has group A → "VOCAL_HI_KEY"; wait for that to be the
    // dropdown's current value before clearing, so the selectOptions
    // genuinely produces a change event.
    await waitFor(() => expect(aTemplate.value).toBe("VOCAL_HI_KEY"));

    const user = userEvent.setup();
    await user.selectOptions(aTemplate, "");

    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[calls.length - 1].body).toMatchObject({
      group_letter: "A",
      template_name: null,
    });
  });
});

describe("ActiveCuration — EXPORT button (Phase 3C)", () => {
  it("clicking export calls pick-save-path then exportCuration", async () => {
    const pickCalls: Array<Record<string, unknown>> = [];
    const exportCalls: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/intent/pick-save-path", async ({ request }) => {
        pickCalls.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({
          ok: true,
          path: "/Users/test/Desktop/verse_swap_v1.ppak",
        });
      }),
      http.post("/curations/:name/export", async ({ request, params }) => {
        exportCalls.push({
          name: params.name as string,
          ...((await request.json()) as Record<string, unknown>),
        });
        return HttpResponse.json({
          ok: true,
          name: params.name,
          stdout: "wrote 1024 bytes",
          stderr: "",
          last_export: {
            exported_at: "2026-05-13T17:00:00Z",
            target_format: "ppak",
            output_path: "/Users/test/Desktop/verse_swap_v1.ppak",
          },
        });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);

    const exportBtn = screen.getByTestId("export-curation");
    await user.click(exportBtn);

    // The picker fired with a default filename derived from curation.name.
    await waitFor(() => expect(pickCalls.length).toBe(1));
    expect(pickCalls[0]).toMatchObject({ default_name: "verse_swap_v1.ppak" });

    // The export call followed with the path the picker returned.
    await waitFor(() => expect(exportCalls.length).toBe(1));
    expect(exportCalls[0]).toMatchObject({
      name: "verse_swap_v1",
      out_path: "/Users/test/Desktop/verse_swap_v1.ppak",
      target_format: "ppak",
    });
  });

  it("skips the export call when the save dialog is cancelled", async () => {
    let exportFired = false;
    let pickFired = false;
    server.use(
      http.post("/intent/pick-save-path", () => {
        pickFired = true;
        return HttpResponse.json({ ok: true, path: null });
      }),
      http.post("/curations/:name/export", () => {
        exportFired = true;
        return HttpResponse.json({ ok: true });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);

    await user.click(screen.getByTestId("export-curation"));
    await waitFor(() => expect(pickFired).toBe(true));
    // Give the (non-firing) export call a chance to be issued — it must not.
    await new Promise((r) => setTimeout(r, 50));
    expect(exportFired).toBe(false);
  });

  it("surfaces server stderr in a toast on subprocess failure", async () => {
    server.use(
      http.post("/intent/pick-save-path", () =>
        HttpResponse.json({ ok: true, path: "/tmp/x.ppak" }),
      ),
      http.post("/curations/:name/export", () =>
        HttpResponse.json({
          ok: false,
          stdout: "",
          stderr: "exporter crashed: missing fixture",
          error: "subprocess",
        }),
      ),
    );
    const toastErrorSpy = vi.spyOn(toast, "error");

    const user = userEvent.setup();
    renderWithProviders(<ActiveCuration curation={CURATION_FRESH} />);
    await user.click(screen.getByTestId("export-curation"));

    // The mutation hook calls toast.error("export failed", { description: stderr }).
    await waitFor(() => expect(toastErrorSpy).toHaveBeenCalled());
    const lastCall = toastErrorSpy.mock.calls.at(-1);
    expect(lastCall?.[0]).toMatch(/export failed/i);
    expect((lastCall?.[1] as { description?: string } | undefined)?.description).toMatch(
      /exporter crashed/i,
    );
    toastErrorSpy.mockRestore();
  });
});
