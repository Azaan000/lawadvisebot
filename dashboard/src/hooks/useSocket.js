import { useEffect, useRef, useState } from "react";
import io from "socket.io-client";
import { BASE } from "../api/client";

// Same flag as App.js — set window.DEBUG_CONSULT = true in the browser
// console to see socket-level trace logs. Off by default.
const trace = (...args) => {
  if (window.DEBUG_CONSULT) console.log(...args);
};

export function useSocket({
  onNewUser, onUserUpdate, onNewMessage, onStatusUpdate,
  onModeChanged, onUserUpdated, onUserTyping, onUserDeleted,
  onWaTokenError, onConsultationBooked,
}) {
  const socketRef = useRef(null);
  const [connected, setConnected] = useState(false);

  const cbRefs = useRef({});
  cbRefs.current = {
    onNewUser, onUserUpdate, onNewMessage, onStatusUpdate,
    onModeChanged, onUserUpdated, onUserTyping, onUserDeleted,
    onWaTokenError, onConsultationBooked,
  };

  useEffect(() => {
    const socket = io(BASE, {
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: 10,
    });
    socketRef.current = socket;

    socket.on("connect",              () => { trace("[TRACE 0] Socket connected, id:", socket.id); setConnected(true); });
    socket.on("disconnect",           (reason) => { trace("[TRACE 0] Socket disconnected:", reason); setConnected(false); });
    socket.on("new_user",             (d) => cbRefs.current.onNewUser?.(d));
    socket.on("user_update",          (d) => cbRefs.current.onUserUpdate?.(d));
    socket.on("new_message",          (d) => cbRefs.current.onNewMessage?.(d));
    socket.on("status_update",        (d) => cbRefs.current.onStatusUpdate?.(d));
    socket.on("mode_changed",         (d) => cbRefs.current.onModeChanged?.(d));
    socket.on("user_updated",         (d) => cbRefs.current.onUserUpdated?.(d));
    socket.on("user_typing",          (d) => cbRefs.current.onUserTyping?.(d));
    socket.on("user_deleted",         (d) => cbRefs.current.onUserDeleted?.(d));
    socket.on("wa_token_error",       (d) => cbRefs.current.onWaTokenError?.(d));
    socket.on("consultation_booked",  (d) => { trace("[TRACE 1] Raw socket event received:", d); cbRefs.current.onConsultationBooked?.(d); });

    return () => socket.disconnect();
  }, []);

  return { connected, socketRef };
}