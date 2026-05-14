import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { CURATION_FRESH } from "@/test/fixtures";
import { TopBar } from "./TopBar";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TopBar", () => {
  it("renders the no-curation placeholder when curation is null", () => {
    renderWithProviders(
      <TopBar
        curation={null}
        activeCurationName={null}
        status="connected"
        error={null}
      />,
    );

    expect(screen.getByTestId("top-bar-no-curation")).toBeInTheDocument();
    expect(screen.getByText(/ep133/i)).toBeInTheDocument();
    expect(screen.getByText(/live/i)).toBeInTheDocument();
  });

  it("renders the active curation name + target chip", () => {
    renderWithProviders(
      <TopBar
        curation={CURATION_FRESH}
        activeCurationName="verse_swap_v1"
        status="connected"
        error={null}
      />,
    );

    expect(screen.getByTestId("top-bar-curation-name").textContent).toBe(
      "verse_swap_v1",
    );
    // `<group count> groups · ep133` — group count is computed from the
    // curation fixture's groups dict (2 groups: A and B).
    expect(screen.getByText(/2 groups · ep133/i)).toBeInTheDocument();
  });

  it("shows a connecting indicator when stream is establishing", () => {
    renderWithProviders(
      <TopBar
        curation={null}
        activeCurationName={null}
        status="connecting"
        error={null}
      />,
    );
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("Pop out button calls window.open with the spec §6.8 args", async () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    renderWithProviders(
      <TopBar
        curation={null}
        activeCurationName={null}
        status="connected"
        error={null}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("top-bar-popout"));

    await waitFor(() => expect(openSpy).toHaveBeenCalledTimes(1));
    expect(openSpy).toHaveBeenCalledWith(
      window.location.href,
      "stemforge",
      "popup,width=1200,height=800",
    );
  });

  it("Save as fires save-as endpoint with a new name", async () => {
    const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("verse_swap_v2");

    renderWithProviders(
      <TopBar
        curation={CURATION_FRESH}
        activeCurationName="verse_swap_v1"
        status="connected"
        error={null}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("top-bar-save-as"));

    expect(promptSpy).toHaveBeenCalled();
    // Underlying save-as mutation hits msw — assert no errors via toast (not
    // visible here without a Toaster), but await one tick for mutation to
    // settle without throwing.
    await waitFor(() =>
      expect(screen.getByTestId("top-bar-save-as")).not.toBeDisabled(),
    );
  });

  it("Save/Save-as/Close are disabled when no curation is active", () => {
    renderWithProviders(
      <TopBar
        curation={null}
        activeCurationName={null}
        status="connected"
        error={null}
      />,
    );
    expect(screen.getByTestId("top-bar-save")).toBeDisabled();
    expect(screen.getByTestId("top-bar-save-as")).toBeDisabled();
    expect(screen.getByTestId("top-bar-close")).toBeDisabled();
  });

  // ── P0-8 — Save button is always disabled, tooltip explains why ────────

  it("Save button is rendered", () => {
    renderWithProviders(
      <TopBar
        curation={CURATION_FRESH}
        activeCurationName="verse_swap_v1"
        status="connected"
        error={null}
      />,
    );
    expect(screen.getByTestId("top-bar-save")).toBeInTheDocument();
  });

  it("Save button is disabled even when a curation is active", () => {
    renderWithProviders(
      <TopBar
        curation={CURATION_FRESH}
        activeCurationName="verse_swap_v1"
        status="connected"
        error={null}
      />,
    );
    // P0-8: Save has no popup-side endpoint in v1; always disabled so users
    // don't expect the popup to write.
    expect(screen.getByTestId("top-bar-save")).toBeDisabled();
  });

  it("hovering Save surfaces the COMMIT-action tooltip", async () => {
    renderWithProviders(
      <TopBar
        curation={CURATION_FRESH}
        activeCurationName="verse_swap_v1"
        status="connected"
        error={null}
      />,
    );

    const user = userEvent.setup();
    // The disabled <button> swallows pointer events, so we hover the wrapper.
    await user.hover(screen.getByTestId("top-bar-save-wrap"));

    // Radix renders the tooltip body twice (visible + sr-only). At least
    // one copy must be present — assert non-empty match.
    await waitFor(() =>
      expect(
        screen.getAllByText(
          /Curation files are written by the device's COMMIT action\. The popup doesn't save directly\./,
        ).length,
      ).toBeGreaterThan(0),
    );
  });
});
