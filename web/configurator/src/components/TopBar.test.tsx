import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { TopBar } from "./TopBar";

function renderTopBar(props: Parameters<typeof TopBar>[0]) {
  return render(
    <TooltipProvider>
      <TopBar {...props} />
    </TooltipProvider>,
  );
}

describe("TopBar", () => {
  it("renders the no-project placeholder when state is null", () => {
    renderTopBar({ state: null, status: "connected", error: null });

    expect(screen.getByText(/no project loaded/i)).toBeInTheDocument();
    // Default target chip
    expect(screen.getByText(/ep133/i)).toBeInTheDocument();
    // Connection status copy
    expect(screen.getByText(/live/i)).toBeInTheDocument();
  });

  it("renders project metadata when state is loaded", () => {
    renderTopBar({
      state: {
        schema_version: 2,
        project_name: "verse_swap_v1",
        manifest_path: "/path/to/curated/manifest.json",
        clip_count: 46,
        songs: [],
        target: "ep133",
      },
      status: "connected",
      error: null,
    });

    expect(screen.getByText("verse_swap_v1")).toBeInTheDocument();
    expect(screen.getByText(/46 clips/)).toBeInTheDocument();
  });

  it("shows a connecting indicator when stream is establishing", () => {
    renderTopBar({ state: null, status: "connecting", error: null });
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });
});
