import { motion } from "framer-motion";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { API_BASE } from "@/lib/api";
import type { ConnectionStatus as ConnStatus } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface ConnectionStatusProps {
  status: ConnStatus;
  error: string | null;
}

/** Resolve the URL the popup is actually talking to. `API_BASE` is empty
 *  when same-origin requests are used (the typical case when the popup is
 *  served by the configurator server); in that case we fall back to
 *  `window.location.origin` so the tooltip still surfaces a concrete URL.
 *  Defaults to the documented dev port when neither is available
 *  (test/jsdom environments without a real location). */
function resolveServerUrl(): string {
  if (API_BASE) return API_BASE;
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://localhost:8765";
}

const STATUS_COPY: Record<ConnStatus, string> = {
  idle: "idle",
  connecting: "connecting…",
  connected: "live",
  disconnected: "reconnecting",
  error: "stream error",
};

/**
 * A small dot + label that reports the SSE stream's health.
 *
 * Pulses when connecting/reconnecting; solid when connected.
 * Tooltip surfaces detail (last error or version).
 */
export function ConnectionStatus({ status, error }: ConnectionStatusProps) {
  const colorClass =
    status === "connected"
      ? "bg-[hsl(var(--success))]"
      : status === "connecting" || status === "disconnected"
        ? "bg-[hsl(var(--warning))]"
        : status === "error"
          ? "bg-[hsl(var(--destructive))]"
          : "bg-muted-foreground";

  const isPulsing = status === "connecting" || status === "disconnected";

  return (
    <Tooltip delayDuration={120}>
      <TooltipTrigger asChild>
        <div className="inline-flex select-none items-center gap-2 text-xs text-muted-foreground">
          <div className="relative flex h-2.5 w-2.5 items-center justify-center">
            {isPulsing && (
              <motion.span
                className={cn(
                  "absolute inset-0 rounded-full opacity-60",
                  colorClass,
                )}
                animate={{ scale: [1, 1.9, 1], opacity: [0.6, 0, 0.6] }}
                transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
              />
            )}
            <span
              className={cn("relative h-2 w-2 rounded-full", colorClass)}
            />
          </div>
          <span className="tabular tracking-tightish">
            {STATUS_COPY[status]}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        <div className="space-y-0.5" data-testid="connection-status-tooltip">
          <div>
            {error
              ? `last error: ${error}`
              : status === "connected"
                ? "SSE stream open · receiving project state in real time"
                : status === "connecting"
                  ? "establishing SSE stream to the configurator server"
                  : status === "disconnected"
                    ? "stream dropped; auto-reconnecting"
                    : status === "error"
                      ? "stream error — check the server logs"
                      : "idle"}
          </div>
          <div
            className="font-mono text-[10px] text-muted-foreground"
            data-testid="connection-status-url"
          >
            {resolveServerUrl()}
          </div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
