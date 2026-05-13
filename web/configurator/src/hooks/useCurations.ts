/**
 * useCurations — TanStack Query wrapper for `GET /curations`.
 *
 * Returns the index of curation files under `~/stemforge/curations/`.
 * Invalidated on lifecycle mutations (open/save-as/rename/delete).
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CurationIndexResponse } from "@/lib/popup-types";

export function useCurations() {
  return useQuery<CurationIndexResponse, Error>({
    queryKey: ["curations"],
    queryFn: () => api.fetchCurations(),
    staleTime: 10_000,
  });
}
