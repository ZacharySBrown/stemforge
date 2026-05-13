import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
});
