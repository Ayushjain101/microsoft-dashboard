"use client";
import { useEffect, useRef, useCallback, useState } from "react";
import { WSEvent } from "@/lib/types";

const MAX_RETRIES = 20;
const INITIAL_DELAY = 3000;
const MAX_DELAY = 30000;

function getWsUrl() {
  if (typeof window === "undefined") return "ws://localhost:8000";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

export function useWebSocket(onMessage?: (event: WSEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const [connected, setConnected] = useState(false);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);
  const retriesRef = useRef(0);

  // Keep ref in sync without triggering reconnects
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (retriesRef.current >= MAX_RETRIES) return;

    const ws = new WebSocket(`${getWsUrl()}/ws/live`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      retriesRef.current = 0;
    };

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as WSEvent;
        onMessageRef.current?.(data);
      } catch (err) {
        console.warn("WebSocket message parse error:", err);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (retriesRef.current < MAX_RETRIES) {
        const delay = Math.min(INITIAL_DELAY * Math.pow(2, retriesRef.current), MAX_DELAY);
        retriesRef.current++;
        reconnectTimeout.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimeout.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected };
}
