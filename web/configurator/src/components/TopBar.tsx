import { motion } from "framer-motion";
import { Disc3, ExternalLink, Layers, Save, SaveAll, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useCloseCuration,
  useSaveAsCuration,
} from "@/hooks/useIntent";
import type { Curation } from "@/lib/api-types.generated";
import type { ConnectionStatus as ConnStatus } from "@/lib/popup-types";
import { ConnectionStatus } from "./ConnectionStatus";

interface TopBarProps {
  curation: Curation | null;
  activeCurationName: string | null;
  status: ConnStatus;
  error: string | null;
  /** Optional override for the pop-out behavior; primarily for tests. */
  onPopOut?: () => void;
}

/**
 * TopBar — sticky header with active-curation chip, save controls,
 * connection status, and the macOS+Chrome "Pop out" workaround from
 * spec §6.8.
 *
 * Composition:
 *   [brand]  ·  [curation name + target chip]   |   [save / save-as / close]
 *                                                   [pop-out] [connection]
 */
export function TopBar({
  curation,
  activeCurationName,
  status,
  error,
  onPopOut,
}: TopBarProps) {
  const saveAs = useSaveAsCuration();
  const closeCuration = useCloseCuration();

  const name = curation?.name ?? activeCurationName ?? null;
  const target = curation?.target;
  const groupCount = curation?.groups ? Object.keys(curation.groups).length : 0;
  const targetDevice = target?.device ?? "ep133";

  const targetChip =
    groupCount > 0
      ? `${groupCount} groups · ${targetDevice}`
      : targetDevice;

  function handlePopOut() {
    if (onPopOut) {
      onPopOut();
      return;
    }
    // spec §6.8: macOS+Chrome resists `open --new`, so the popup itself
    // does the new-window pop via window.open. window.open from a user
    // gesture is honored where the OS-level launcher is not.
    //
    // Chrome popup gotchas we've hit:
    //   - A bare "popup" feature is insufficient; recent Chrome treats
    //     window.open with a reused window name as "focus the named tab"
    //     even when "popup" is set, opening a tab instead of a chromeless
    //     window. Using "_blank" forces a fresh window; explicit width/
    //     height + chrome-flags push Chrome into popup-window mode rather
    //     than full-tab.
    //   - `popup=yes` (the modern feature key) is more reliable than the
    //     bare `popup` flag.
    const features = [
      "popup=yes",
      "width=1200",
      "height=900",
      "menubar=no",
      "toolbar=no",
      "location=no",
      "status=no",
      "scrollbars=yes",
      "resizable=yes",
    ].join(",");
    // Chrome dedupes `window.open(currentURL, ...)` and reuses the current
    // tab when the URL exactly matches. Append a transient query param so
    // Chrome treats it as a distinct target → opens a fresh popup window
    // rather than navigating the parent or focusing the current tab.
    const url = new URL(window.location.href);
    url.searchParams.set("popout", "1");
    const w = window.open(url.href, "_blank", features);
    if (w) {
      // Best-effort focus so the new window comes to the foreground even if
      // the OS stacked it behind Live.
      try {
        w.focus();
      } catch {
        // Cross-origin focus calls can throw; safe to ignore.
      }
    }
  }

  function handleSaveAs() {
    if (!name) return;
    const newName = window.prompt(
      "save as (new curation name)",
      `${name}_copy`,
    );
    if (newName && newName !== name) {
      saveAs.mutate({ name, new_name: newName });
    }
  }

  function handleClose() {
    if (!name) return;
    if (window.confirm(`close active curation "${name}"?`)) {
      closeCuration.mutate();
    }
  }

  return (
    <motion.header
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      className="glass sticky top-0 z-20 flex h-14 items-center gap-4 px-4"
      data-testid="top-bar"
    >
      <div className="flex items-center gap-2.5">
        <div className="grid h-7 w-7 place-items-center rounded-md bg-accent-muted text-[hsl(var(--accent))]">
          <Disc3 className="h-4 w-4" strokeWidth={2.25} />
        </div>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold tracking-tighter2">
            StemForge
          </div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            configurator
          </div>
        </div>
      </div>

      <Separator orientation="vertical" className="h-7" />

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Layers className="h-4 w-4 shrink-0 text-muted-foreground" />
        {name ? (
          <div className="flex min-w-0 flex-col">
            <div
              className="truncate text-[15px] font-semibold tracking-tighter2 text-foreground"
              data-testid="top-bar-curation-name"
            >
              {name}
            </div>
            <div className="truncate text-[11px] text-muted-foreground tabular">
              {targetChip}
            </div>
          </div>
        ) : (
          <div
            className="text-[13px] font-medium text-muted-foreground"
            data-testid="top-bar-no-curation"
          >
            no curation active
          </div>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        {/*
         * P0-8 — Save is permanently disabled. v1 has no popup-side save
         * intent: curation files are written exclusively by the device's
         * COMMIT action. The button stays visible so users who instinctively
         * look for "save" find it (and the tooltip teaches them where saves
         * really happen). When/if a popup-side save endpoint lands, this is
         * the wire point.
         */}
        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            {/*
             * Radix Tooltip won't open on a `disabled` <button> because the
             * browser swallows pointer events. Wrap in a span so hover still
             * works; the inner Button stays `disabled` for keyboard + a11y.
             */}
            <span
              tabIndex={0}
              data-testid="top-bar-save-wrap"
              aria-label="Save (disabled)"
              className="inline-flex"
            >
              <Button
                size="sm"
                variant="secondary"
                disabled
                data-testid="top-bar-save"
                aria-label="Save"
                tabIndex={-1}
                className="pointer-events-none"
              >
                <Save className="h-3.5 w-3.5" />
                save
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            Curation files are written by the device's COMMIT action. The
            popup doesn't save directly.
          </TooltipContent>
        </Tooltip>

        <Button
          size="sm"
          variant="secondary"
          onClick={handleSaveAs}
          disabled={!name || saveAs.isPending}
          data-testid="top-bar-save-as"
          aria-label="Save as"
        >
          <SaveAll className="h-3.5 w-3.5" />
          save as…
        </Button>

        <Button
          size="sm"
          variant="ghost"
          onClick={handleClose}
          disabled={!name || closeCuration.isPending}
          data-testid="top-bar-close"
          aria-label="Close"
        >
          <X className="h-3.5 w-3.5" />
          close
        </Button>

        <Separator orientation="vertical" className="h-6 mx-1" />

        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="sm"
              variant="outline"
              onClick={handlePopOut}
              data-testid="top-bar-popout"
              aria-label="Pop out"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              pop out
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            open in a new window (works around macOS + Chrome new-window
            resistance)
          </TooltipContent>
        </Tooltip>

        <Separator orientation="vertical" className="h-6 mx-1" />
        <Badge variant="default" className="uppercase">
          {targetDevice}
        </Badge>
        <ConnectionStatus status={status} error={error} />
      </div>
    </motion.header>
  );
}
