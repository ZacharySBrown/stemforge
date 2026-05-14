import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/server";
import { emptyHandlers, failingHandlers } from "@/test/handlers";
import { renderWithProviders } from "@/test/render";
import { CURATION_FRESH, CURATION_STALE } from "@/test/fixtures";
import { ForgeList } from "./ForgeList";

describe("ForgeList", () => {
  it("renders the populated list from GET /forges", async () => {
    renderWithProviders(<ForgeList curation={null} />);

    await waitFor(() =>
      expect(screen.getAllByTestId("forge-row")).toHaveLength(3),
    );

    // Loaded forge surfaces the "loaded" badge.
    expect(screen.getAllByText(/loaded/i).length).toBeGreaterThan(0);

    // BPM tabulation present.
    expect(screen.getByText(/90\.0 bpm/i)).toBeInTheDocument();
  });

  it("renders the empty state when the server returns zero forges", async () => {
    server.use(...emptyHandlers);
    renderWithProviders(<ForgeList curation={null} />);

    await waitFor(() =>
      expect(screen.getByText(/no forges yet/i)).toBeInTheDocument(),
    );
  });

  it("renders the skeleton while the request is in-flight", () => {
    // Skeleton only shows while isLoading — easiest assertion is on the
    // initial render before microtask resolution (msw responds async, so
    // synchronously the query is `isLoading=true`).
    const { container } = renderWithProviders(<ForgeList curation={null} />);
    expect(container.querySelector("[data-testid='forge-list']")).toBeInTheDocument();
    // No rows yet.
    expect(screen.queryAllByTestId("forge-row")).toHaveLength(0);
  });

  it("renders error UI + retry button on 500", async () => {
    server.use(...failingHandlers);
    renderWithProviders(<ForgeList curation={null} />);

    await waitFor(() =>
      expect(screen.getByTestId("forge-list-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("forge-list-retry")).toBeInTheDocument();
  });

  it("renders the StaleBadge only on forges whose hash diverges from the curation's reference", async () => {
    // CURATION_STALE references `definition-of-sound` at an OLD hash;
    // the index returns `definition-of-sound` at a FRESH hash → stale=true.
    // Other forges have no curation ref → stale=false.
    renderWithProviders(<ForgeList curation={CURATION_STALE} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("forge-row").length).toBeGreaterThan(0),
    );

    const badges = screen.getAllByTestId("stale-badge");
    expect(badges).toHaveLength(1);

    // Confirm it's attached to definition-of-sound row.
    const staleRow = badges[0].closest("[data-testid='forge-row']");
    expect(staleRow?.getAttribute("data-forge-slug")).toBe(
      "definition-of-sound",
    );
  });

  it("renders NO stale badge when the curation's reference matches", async () => {
    // CURATION_FRESH references definition-of-sound at sha256:abc123fresh,
    // which is exactly the index's hash → not stale.
    const { rerender } = renderWithProviders(<ForgeList curation={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("forge-row").length).toBeGreaterThan(0),
    );
    rerender(<ForgeList curation={CURATION_FRESH} />);
    expect(screen.queryAllByTestId("stale-badge")).toHaveLength(0);
  });

  it("renders a rail-level stale count badge that totals per-forge stales", async () => {
    // CURATION_STALE has one stale ref (definition-of-sound).
    renderWithProviders(<ForgeList curation={CURATION_STALE} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("forge-row").length).toBeGreaterThan(0),
    );

    const count = screen.getByTestId("forge-list-stale-count");
    expect(count).toHaveTextContent("1 stale");
  });

  it("hides the refresh button when no curation is open or nothing is stale", async () => {
    renderWithProviders(<ForgeList curation={null} />);
    await waitFor(() =>
      expect(screen.getAllByTestId("forge-row").length).toBeGreaterThan(0),
    );
    expect(screen.queryByTestId("forge-list-refresh")).toBeNull();
  });

  it("shows the Refresh button when curation has a stale ref and POSTs the right endpoint on click", async () => {
    const refreshSpy = vi.fn();
    server.use(
      http.post("/curations/:name/refresh", ({ params }) => {
        refreshSpy(params.name);
        return HttpResponse.json(CURATION_FRESH);
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(<ForgeList curation={CURATION_STALE} />);

    const button = await screen.findByTestId("forge-list-refresh");
    await user.click(button);

    await waitFor(() =>
      expect(refreshSpy).toHaveBeenCalledWith(CURATION_STALE.name),
    );
  });
});
