"use client";

import { useEffect, useRef, useState } from "react";
import type { RealtimeEvent } from "./types";
import { wsUrl } from "./api";

/**
 * One socket per tab.
 *
 * The cursor is the point of this hook. A tab that sleeps for two minutes
 * reconnects with its last event id and the server replays the gap, so an
 * inbox never silently skips a thread. Reconnection backs off exponentially
 * and caps at 30s — a server restart shouldn't produce a thundering herd from
 * every open tab at once.
 */
export function useRealtime(
  session: string | null,
  onEvent: (e: RealtimeEvent) => void,
) {
  const [connected, setConnected] = useState(false);
  const cursor = useRef("$");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!session) return;
    let socket: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout>;
    let closed = false;

    const open = () => {
      socket = new WebSocket(wsUrl(session, cursor.current));

      socket.onopen = () => {
        retry = 0;
        setConnected(true);
      };

      socket.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as RealtimeEvent;
        if (event.cursor) cursor.current = event.cursor;
        if (event.event !== "ping") handler.current(event);
      };

      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        timer = setTimeout(open, Math.min(1000 * 2 ** retry++, 30_000));
      };

      socket.onerror = () => socket?.close();
    };

    open();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [session]);

  return { connected };
}
