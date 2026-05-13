/**
 * MockEventSource — minimal stand-in for the platform EventSource so hook
 * tests can deterministically push typed events.
 *
 * Supports `addEventListener("state", ...)` semantics — the server emits
 * `event: state\ndata: <json>` SSE frames and the client subscribes by name.
 */

type Listener = (ev: MessageEvent) => unknown;

export class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  withCredentials = false;
  readyState = 0;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;
  closed = false;

  private listeners: Map<string, Set<Listener>> = new Map();

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
    // Defer the open so subscribers can attach handlers first.
    queueMicrotask(() => this._open());
  }

  _open() {
    if (this.closed) return;
    this.readyState = MockEventSource.OPEN;
    this.onopen?.call(this as unknown as EventSource, new Event("open"));
  }

  addEventListener(type: string, cb: EventListener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(cb as Listener);
  }

  removeEventListener(type: string, cb: EventListener): void {
    this.listeners.get(type)?.delete(cb as Listener);
  }

  /** Push a JSON-stringified payload as a TYPED event (event: <type>). */
  emit(type: string, data: unknown) {
    if (this.closed) return;
    const evt = new MessageEvent(type, { data: JSON.stringify(data) });
    // Typed listeners — the real path popup code uses now.
    const set = this.listeners.get(type);
    if (set) for (const cb of set) cb(evt);
    // Backwards-compat: still drive `onmessage` for type="message".
    if (type === "message" && this.onmessage) {
      this.onmessage.call(this as unknown as EventSource, evt);
    }
  }

  /** Simulate a transport error (auto-reconnect semantics handled by hook). */
  fail() {
    this.onerror?.call(this as unknown as EventSource, new Event("error"));
  }

  close() {
    this.closed = true;
    this.readyState = MockEventSource.CLOSED;
  }

  static reset() {
    MockEventSource.instances = [];
  }
}
