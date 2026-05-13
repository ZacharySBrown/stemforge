import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
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
});
