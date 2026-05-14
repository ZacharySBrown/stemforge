import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/server";
import { emptyHandlers, failingHandlers } from "@/test/handlers";
import { renderWithProviders } from "@/test/render";
import { CurationList } from "./CurationList";

describe("CurationList", () => {
  it("renders the populated curation list", async () => {
    renderWithProviders(<CurationList activeCurationName="verse_swap_v1" />);

    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    // The active curation is highlighted (active=true on the row).
    const rows = screen.getAllByTestId("curation-row");
    const active = rows.find(
      (r) => r.getAttribute("data-curation-name") === "verse_swap_v1",
    );
    expect(active?.getAttribute("data-active")).toBe("true");
    expect(screen.getByTestId("active-badge")).toBeInTheDocument();
  });

  it("renders the empty state when the server returns zero curations", async () => {
    server.use(...emptyHandlers);
    renderWithProviders(<CurationList activeCurationName={null} />);

    await waitFor(() =>
      expect(screen.getByTestId("curation-list-empty")).toBeInTheDocument(),
    );
  });

  it("renders the loading skeleton on initial mount", () => {
    renderWithProviders(<CurationList activeCurationName={null} />);
    expect(screen.queryByTestId("curation-list-skeleton")).toBeInTheDocument();
    expect(screen.queryAllByTestId("curation-row")).toHaveLength(0);
  });

  it("renders error UI + retry button on 500", async () => {
    server.use(...failingHandlers);
    renderWithProviders(<CurationList activeCurationName={null} />);

    await waitFor(() =>
      expect(screen.getByTestId("curation-list-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("curation-list-retry")).toBeInTheDocument();
  });

  // ── P0-7 — Clickable row body ───────────────────────────────────────────

  it("clicking the row body fires the open-curation intent", async () => {
    const opens: string[] = [];
    server.use(
      http.post("/curations/:name/open", ({ params }) => {
        opens.push(String(params.name));
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    // Mount with NO active curation so the inactive row is clickable.
    renderWithProviders(<CurationList activeCurationName={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    const inactiveRow = screen
      .getAllByTestId("curation-row")
      .find((r) => r.getAttribute("data-curation-name") === "live_set_oct_2026");
    expect(inactiveRow).toBeDefined();
    const body = within(inactiveRow!).getByTestId("curation-row-body");

    const user = userEvent.setup();
    await user.click(body);

    await waitFor(() => expect(opens).toContain("live_set_oct_2026"));
  });

  it("clicking the BookOpen icon still fires the open-curation intent", async () => {
    const opens: string[] = [];
    server.use(
      http.post("/curations/:name/open", ({ params }) => {
        opens.push(String(params.name));
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    renderWithProviders(<CurationList activeCurationName={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    const inactiveRow = screen
      .getAllByTestId("curation-row")
      .find((r) => r.getAttribute("data-curation-name") === "live_set_oct_2026");
    const bookOpenBtn = within(inactiveRow!).getByRole("button", {
      name: /^Open live_set_oct_2026$/,
    });

    const user = userEvent.setup();
    await user.click(bookOpenBtn);

    await waitFor(() => expect(opens).toContain("live_set_oct_2026"));
  });

  it("clicking the Duplicate icon does NOT fire the open-curation intent", async () => {
    const opens: string[] = [];
    server.use(
      http.post("/curations/:name/open", ({ params }) => {
        opens.push(String(params.name));
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );
    // Duplicate prompts the user — make it cancel so it doesn't fire either.
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue(null);

    renderWithProviders(<CurationList activeCurationName={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    const inactiveRow = screen
      .getAllByTestId("curation-row")
      .find((r) => r.getAttribute("data-curation-name") === "live_set_oct_2026");
    const dupeBtn = within(inactiveRow!).getByRole("button", {
      name: /^Duplicate live_set_oct_2026$/,
    });

    const user = userEvent.setup();
    await user.click(dupeBtn);

    // Allow any pending mutation to settle.
    await new Promise((r) => setTimeout(r, 25));
    expect(opens).toHaveLength(0);
    expect(promptSpy).toHaveBeenCalled();
    promptSpy.mockRestore();
  });

  it("already-active row does NOT fire the open-curation intent on click", async () => {
    const opens: string[] = [];
    server.use(
      http.post("/curations/:name/open", ({ params }) => {
        opens.push(String(params.name));
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    renderWithProviders(<CurationList activeCurationName="verse_swap_v1" />);
    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    const activeRow = screen
      .getAllByTestId("curation-row")
      .find((r) => r.getAttribute("data-curation-name") === "verse_swap_v1");
    expect(activeRow?.getAttribute("data-active")).toBe("true");
    const body = within(activeRow!).getByTestId("curation-row-body");
    expect(body.getAttribute("aria-disabled")).toBe("true");

    const user = userEvent.setup();
    await user.click(body);

    await new Promise((r) => setTimeout(r, 25));
    expect(opens).toHaveLength(0);
  });

  it("pressing Enter on a focused row fires the open-curation intent", async () => {
    const opens: string[] = [];
    server.use(
      http.post("/curations/:name/open", ({ params }) => {
        opens.push(String(params.name));
        return HttpResponse.json({ ok: true, warnings: [], errors: [] });
      }),
    );

    renderWithProviders(<CurationList activeCurationName={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("curation-row")).toHaveLength(2),
    );

    const inactiveRow = screen
      .getAllByTestId("curation-row")
      .find((r) => r.getAttribute("data-curation-name") === "live_set_oct_2026");
    const body = within(inactiveRow!).getByTestId("curation-row-body") as HTMLElement;

    body.focus();
    const user = userEvent.setup();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(opens).toContain("live_set_oct_2026"));
  });
});
