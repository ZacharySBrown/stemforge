import { Skeleton } from "@/components/ui/skeleton";

/**
 * Pad-canvas skeleton — rendered while the SSE stream is still warming up
 * and we have no ProjectSpec snapshot yet. Mirrors the 4×12 grid shape so
 * layout doesn't jump when state lands.
 */
export function PadCanvasSkeleton() {
  return (
    <section className="flex h-full min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-5">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-7 w-40" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-5 w-16" />
        </div>
      </div>
      <div className="flex flex-col gap-5">
        {Array.from({ length: 4 }).map((_, gi) => (
          <div key={gi} className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Skeleton className="h-6 w-6 rounded-md" />
                <div className="space-y-1.5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-2.5 w-12" />
                </div>
              </div>
              <div className="flex gap-2">
                <Skeleton className="h-5 w-14" />
                <Skeleton className="h-5 w-10" />
              </div>
            </div>
            <div className="grid grid-cols-12 gap-2">
              {Array.from({ length: 12 }).map((_, pi) => (
                <Skeleton key={pi} className="aspect-square rounded-lg" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
