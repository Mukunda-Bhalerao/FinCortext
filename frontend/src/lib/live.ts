// Browser side of the live relay: one socket, reference-counted subscriptions,
// automatic reconnection. Ticks only ever come from the backend; nothing is synthesized here.

import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { Freshness, Quote, StatusMessage, Tick } from "./types";

type Listener = () => void;

export type SocketState = "connecting" | "open" | "closed";

class LiveClient {
  private ws: WebSocket | null = null;
  private refs = new Map<string, number>();
  private ticks = new Map<string, Tick>();
  private keyListeners = new Map<string, Set<Listener>>();
  private statusListeners = new Set<Listener>();
  private status: StatusMessage | null = null;
  private socketState: SocketState = "closed";
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  private url(): string {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/api/ws/live`;
  }

  private connect(): void {
    if (this.ws) return;
    this.setSocketState("connecting");
    const ws = new WebSocket(this.url());
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setSocketState("open");
      const keys = [...this.refs.keys()];
      if (keys.length) ws.send(JSON.stringify({ action: "subscribe", keys }));
    };
    ws.onmessage = (ev: MessageEvent<string>) => {
      let msg: Tick | StatusMessage;
      try {
        msg = JSON.parse(ev.data) as Tick | StatusMessage;
      } catch {
        return;
      }
      if (msg.type === "tick") {
        this.ticks.set(msg.key, msg);
        this.keyListeners.get(msg.key)?.forEach((l) => l());
      } else if (msg.type === "status") {
        this.status = msg;
        this.statusListeners.forEach((l) => l());
      }
    };
    ws.onclose = () => {
      this.ws = null;
      this.setSocketState("closed");
      const delay = Math.min(15000, 1000 * 2 ** this.retry++);
      this.timer = setTimeout(() => this.connect(), delay);
    };
  }

  private setSocketState(s: SocketState): void {
    this.socketState = s;
    this.statusListeners.forEach((l) => l());
  }

  private send(action: "subscribe" | "unsubscribe", keys: string[]): void {
    if (keys.length && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action, keys }));
    }
  }

  start(): void {
    if (!this.ws && !this.timer) this.connect();
  }

  /** Reconnect immediately (e.g. after the user reconnects Upstox). */
  kick(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.retry = 0;
    if (!this.ws) this.connect();
  }

  subscribe(keys: string[]): () => void {
    this.start();
    const added: string[] = [];
    for (const k of keys) {
      const n = this.refs.get(k) ?? 0;
      this.refs.set(k, n + 1);
      if (n === 0) added.push(k);
    }
    this.send("subscribe", added);
    return () => {
      const removed: string[] = [];
      for (const k of keys) {
        const n = (this.refs.get(k) ?? 1) - 1;
        if (n <= 0) {
          this.refs.delete(k);
          removed.push(k);
        } else this.refs.set(k, n);
      }
      this.send("unsubscribe", removed);
    };
  }

  onKey(key: string, l: Listener): () => void {
    let set = this.keyListeners.get(key);
    if (!set) this.keyListeners.set(key, (set = new Set()));
    set.add(l);
    return () => set.delete(l);
  }

  onStatus(l: Listener): () => void {
    this.statusListeners.add(l);
    return () => this.statusListeners.delete(l);
  }

  tick(key: string): Tick | undefined {
    return this.ticks.get(key);
  }

  getStatus(): StatusMessage | null {
    return this.status;
  }

  getSocketState(): SocketState {
    return this.socketState;
  }
}

export const live = new LiveClient();

/** Subscribe the given instrument keys for as long as the component is mounted. */
export function useLiveSubscription(keys: (string | null | undefined)[]): void {
  const list = useMemo(
    () => [...new Set(keys.filter((k): k is string => !!k))].sort(),
    [keys.join(",")],
  );
  useEffect(() => (list.length ? live.subscribe(list) : undefined), [list]);
}

export function useTick(key: string | null | undefined): Tick | undefined {
  return useSyncExternalStore(
    (l) => (key ? live.onKey(key, l) : () => undefined),
    () => (key ? live.tick(key) : undefined),
  );
}

export function useLiveStatus(): { status: StatusMessage | null; socket: SocketState } {
  // Pages without subscriptions still need the socket for feed and market status.
  useEffect(() => live.start(), []);
  const status = useSyncExternalStore(
    (l) => live.onStatus(l),
    () => live.getStatus(),
  );
  const socket = useSyncExternalStore(
    (l) => live.onStatus(l),
    () => live.getSocketState(),
  );
  return { status, socket };
}

const STALE_MS = 2 * 60 * 1000;

export interface DisplayQuote {
  ltp: number | null;
  prevClose: number | null;
  change: number | null;
  changePct: number | null;
  volume: number | null;
  observedAt: string | null;
  freshness: Freshness;
  source: string | null;
}

/** Combine a REST snapshot with the latest tick (whichever is newer). */
export function mergeQuote(
  quote: Quote | null | undefined,
  tick: Tick | undefined,
  marketOpen: boolean,
  now = Date.now(),
): DisplayQuote {
  const tickNewer =
    tick && (!quote || new Date(tick.received_at).getTime() > new Date(quote.fetched_at).getTime());
  if (tickNewer && tick) {
    const age = now - new Date(tick.received_at).getTime();
    const freshness: Freshness = !marketOpen
      ? "last_close"
      : age > STALE_MS
        ? "stale"
        : tick.transport === "stream"
          ? "live"
          : "delayed";
    return {
      ltp: tick.ltp,
      prevClose: tick.prev_close ?? quote?.prev_close ?? null,
      change: tick.change,
      changePct: tick.change_pct,
      volume: tick.volume ?? quote?.volume ?? null,
      observedAt: tick.received_at,
      freshness,
      source: tick.transport === "stream" ? "Upstox market data feed" : "Upstox quotes (polled)",
    };
  }
  if (!quote) {
    return {
      ltp: null,
      prevClose: null,
      change: null,
      changePct: null,
      volume: null,
      observedAt: null,
      freshness: "unavailable",
      source: null,
    };
  }
  let freshness = quote.freshness;
  if (marketOpen && freshness !== "unavailable" && now - new Date(quote.fetched_at).getTime() > STALE_MS) {
    freshness = "stale";
  }
  return {
    ltp: quote.ltp,
    prevClose: quote.prev_close,
    change: quote.change,
    changePct: quote.change_pct,
    volume: quote.volume,
    observedAt: quote.fetched_at,
    freshness,
    source: "Upstox quotes",
  };
}
