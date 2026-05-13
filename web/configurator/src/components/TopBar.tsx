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
    window.open(
      window.location.href,
      "stemforge",
      "popup,width=1200,height=800",
    );
  }

  function handleSave() {
    // For v1 there is no explicit "save" intent — committing happens on
    // the device (COMMIT button). The Save button surfaces in the
    // TopBar to remind the user that the device is the writer. We
    // surface a tooltip and noop.
    // Lane 1B may eventually add /intent/save-active for popup-side
    // metadata writes; we shim with a stale-info toast until then.
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
        <Tooltip delayDuration={200}>
          <TooltipTrigger asChild>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleSave}
              disabled={!name}
              data-testid="top-bar-save"
              aria-label="Save"
            >
              <Save className="h-3.5 w-3.5" />
              save
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            curation writes happen on device COMMIT — this is a status
            indicator only
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
