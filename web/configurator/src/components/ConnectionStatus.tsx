import { motion } from "framer-motion";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ConnectionStatus as ConnStatus } from "@/lib/popup-types";
import { cn } from "@/lib/utils";

interface ConnectionStatusProps {
  status: ConnStatus;
  error: string | null;
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
      </TooltipContent>
    </Tooltip>
  );
}
