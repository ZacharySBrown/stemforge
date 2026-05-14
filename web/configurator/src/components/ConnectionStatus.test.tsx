import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { ConnectionStatus } from "./ConnectionStatus";

describe("ConnectionStatus", () => {
  it("renders the status copy for each connection state", () => {
    const { rerender } = renderWithProviders(
      <ConnectionStatus status="connected" error={null} />,
    );
    expect(screen.getByText("live")).toBeInTheDocument();

    rerender(<ConnectionStatus status="connecting" error={null} />);
    expect(screen.getByText("connecting…")).toBeInTheDocument();

    rerender(<ConnectionStatus status="disconnected" error={null} />);
    expect(screen.getByText("reconnecting")).toBeInTheDocument();

    rerender(<ConnectionStatus status="error" error="oops" />);
    expect(screen.getByText("stream error")).toBeInTheDocument();

    rerender(<ConnectionStatus status="idle" error={null} />);
    expect(screen.getByText("idle")).toBeInTheDocument();
  });

  // P2-1: hovering the dot must surface the actual server URL so operators
  // can confirm which endpoint the popup is bound to (matters in dev when
  // multiple Live instances + ports float around).
  //
  // Note: Radix Tooltip renders its content twice (the visible popper +
  // a hidden a11y span), so we use getAllByTestId and assert against the
  // first match.
  it("tooltip surfaces the active server URL when hovered", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ConnectionStatus status="connected" error={null} />);

    // The TooltipProvider in renderWithProviders has delayDuration=0, so a
    // hover should reveal the tooltip immediately.
    await user.hover(screen.getByText("live"));

    await waitFor(() =>
      expect(screen.getAllByTestId("connection-status-tooltip").length).toBeGreaterThan(0),
    );

    // jsdom defaults window.location.origin to "http://localhost:3000" so
    // the resolver falls back to that (no API_BASE in this env). The
    // test asserts the tooltip renders *some* URL; the exact host is
    // environment-defined but must include the protocol so operators can
    // copy/paste.
    const urlNodes = screen.getAllByTestId("connection-status-url");
    expect(urlNodes[0].textContent).toMatch(/^https?:\/\//);
  });

  it("tooltip surfaces last error when one is present", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ConnectionStatus status="error" error="ECONNREFUSED" />,
    );

    await user.hover(screen.getByText("stream error"));
    await waitFor(() => {
      const tooltips = screen.getAllByTestId("connection-status-tooltip");
      expect(tooltips.length).toBeGreaterThan(0);
      expect(tooltips[0].textContent).toMatch(/ECONNREFUSED/);
    });
  });
});
