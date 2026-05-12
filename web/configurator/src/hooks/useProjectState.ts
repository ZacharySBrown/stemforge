/**
 * useProjectState — subscribes to the SSE event stream and exposes the
 * canonical ProjectSpec, connection status, last error, and active progress.
 *
 * Why a custom hook (vs TanStack Query):
 *   The server pushes state via SSE — there's no polling cadence to manage.
 *   TanStack Query is reserved for the intent mutations.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { streamUrl } from "@/lib/api";
import type {
  ConnectionStatus,
  ProjectSpec,
  SseEvent,
} from "@/lib/types";

export interface ProgressState {
  operation: string;
  fraction: number;
  message?: string;
}

export interface UseProjectStateResult {
  state: ProjectSpec | null;
  status: ConnectionStatus;
  error: string | null;
  progress: ProgressState | null;
  /** Push events that the UI surfaces as toasts. */
  logs: Array<{
    id: string;
    level: "info" | "warn" | "error";
    message: string;
    at: number;
  }>;
  /** Acknowledge a log event so the toast doesn't fire again. */
  clearLog: (id: string) => void;
  /** Force-reconnect the SSE stream. */
  reconnect: () => void;
}

/** Inject a custom EventSource constructor for testing. */
export interface UseProjectStateOptions {
  EventSourceCtor?: typeof EventSource;
  url?: string;
}

export function useProjectState(
  opts: UseProjectStateOptions = {},
): UseProjectStateResult {
  const [state, setState] = useState<ProjectSpec | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [logs, setLogs] = useState<UseProjectStateResult["logs"]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTokenRef = useRef(0);

  const handleEvent = useCallback((evt: MessageEvent<string>) => {
    let parsed: SseEvent | null = null;
    try {
      parsed = JSON.parse(evt.data) as SseEvent;
    } catch {
      // Bad payload — record as an error event.
      setError("malformed SSE payload");
      return;
    }
    if (!parsed || typeof parsed !== "object" || !("type" in parsed)) return;

    switch (parsed.type) {
      case "state":
        setState(parsed.payload);
        break;
      case "progress":
        if (parsed.payload.done) {
          setProgress(null);
        } else {
          setProgress({
            operation: parsed.payload.operation,
            fraction: parsed.payload.fraction,
            message: parsed.payload.message,
          });
        }
        break;
      case "log":
        setLogs((prev) => [
          ...prev,
          {
            id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            level: parsed.payload.level,
            message: parsed.payload.message,
            at: Date.now(),
          },
        ]);
        break;
      case "error":
        setError(parsed.payload.message);
        break;
    }
  }, []);

  useEffect(() => {
    const Ctor = opts.EventSourceCtor ?? globalThis.EventSource;
    if (!Ctor) {
      setStatus("error");
      setError("EventSource API not available in this environment");
      return;
    }

    setStatus("connecting");
    setError(null);
    const es = new Ctor(opts.url ?? streamUrl());
    esRef.current = es;

    es.onopen = () => setStatus("connected");
    es.onerror = () => {
      setStatus("disconnected");
      // EventSource auto-reconnects; we just surface state.
    };
    es.onmessage = (evt) => handleEvent(evt as MessageEvent<string>);

    return () => {
      es.close();
      esRef.current = null;
    };
    // reconnectTokenRef triggers re-running this effect when reconnect() is
    // invoked imperatively.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handleEvent, opts.EventSourceCtor, opts.url, reconnectTokenRef.current]);

  const reconnect = useCallback(() => {
    esRef.current?.close();
    reconnectTokenRef.current += 1;
    setStatus("connecting");
  }, []);

  const clearLog = useCallback((id: string) => {
    setLogs((prev) => prev.filter((l) => l.id !== id));
  }, []);

  return { state, status, error, progress, logs, clearLog, reconnect };
}
