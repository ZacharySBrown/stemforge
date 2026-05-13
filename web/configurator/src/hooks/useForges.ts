/**
 * useForges — TanStack Query wrapper for `GET /forges`.
 *
 * The forge index is scan-driven on the server; we poll on mount and
 * invalidate on lifecycle mutations (load / unload / re-anchor / re-curate
 * surface via SSE state events when the device acknowledges the
 * transition, but the index itself comes from the filesystem scan).
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ForgeIndexResponse } from "@/lib/popup-types";

export function useForges() {
  return useQuery<ForgeIndexResponse, Error>({
    queryKey: ["forges"],
    queryFn: () => api.fetchForges(),
    staleTime: 10_000,
  });
}
