import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { CURATION_FRESH } from "@/test/fixtures";
import { StatusBar } from "./StatusBar";

describe("StatusBar", () => {
  it("renders the no-curation placeholder when curation is null", () => {
    renderWithProviders(<StatusBar curation={null} progress={null} />);
    expect(screen.getByTestId("status-bar")).toBeInTheDocument();
    expect(screen.getByText(/no curation active/i)).toBeInTheDocument();
  });

  it("renders the active curation name + filled/total pads", () => {
    renderWithProviders(
      <StatusBar curation={CURATION_FRESH} progress={null} />,
    );
    expect(screen.getByText(/verse_swap_v1/)).toBeInTheDocument();
    // The fixture has at least one filled pad; the summary line carries it.
    expect(
      screen.getByText(/pads filled/i),
    ).toBeInTheDocument();
  });

  // P2-2: progress empty-state coverage. Two cases land here:
  //   (a) progress === null  → idle UI renders, no progress bar.
  //   (b) progress.fraction === 0 → progress UI renders but shows 0%
  //       without crashing on the Progress component's edge case.

  it("shows the idle indicator when progress is null", () => {
    renderWithProviders(<StatusBar curation={null} progress={null} />);
    expect(screen.queryByTestId("status-progress")).toBeNull();
    expect(screen.getByText(/idle/i)).toBeInTheDocument();
  });

  it("renders the progress bar at 0% without crashing when fraction is 0", () => {
    renderWithProviders(
      <StatusBar
        curation={null}
        progress={{ operation: "bounce:verse_swap_v1", fraction: 0 }}
      />,
    );
    // The progress block is present (it replaces the idle pill).
    expect(screen.getByTestId("status-progress")).toBeInTheDocument();
    // Operation name renders even with no `message`.
    expect(screen.getByText("bounce:verse_swap_v1")).toBeInTheDocument();
    // Idle pill is gone.
    expect(screen.queryByText(/^idle$/i)).toBeNull();
  });

  it("prefers the message string over the operation key when both are set", () => {
    renderWithProviders(
      <StatusBar
        curation={null}
        progress={{
          operation: "bounce:foo",
          fraction: 0.5,
          message: "rendered A02 (1/2)",
        }}
      />,
    );
    expect(screen.getByText("rendered A02 (1/2)")).toBeInTheDocument();
    // The raw operation key should NOT be shown when the message is set.
    expect(screen.queryByText("bounce:foo")).toBeNull();
  });
});
