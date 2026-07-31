import { useState, useCallback, useRef } from "react";
import { api } from "../api/client";

export function useMessages(selectedPhone) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [unreadCounts, setUnreadCounts] = useState({});
  const [highlightedUsers, setHighlightedUsers] = useState(new Set());
  const selectedPhoneRef = useRef(selectedPhone);
  selectedPhoneRef.current = selectedPhone;

  const loadMessages = useCallback(async (phone, search = "") => {
    if (!phone) return;
    setLoading(true);
    try {
      const data = await api.getMessages(phone, search);
      setMessages(data);
      markAsRead(phone);
    } catch (e) {
      console.error("loadMessages:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const markAsRead = useCallback((phone) => {
    setUnreadCounts((prev) => ({ ...prev, [phone]: 0 }));
    setHighlightedUsers((prev) => {
      const s = new Set(prev);
      s.delete(phone);
      return s;
    });
    // Persist to the backend too — unreadCounts here is just React
    // state, so without this, anything the customer sent while the
    // dashboard was closed (or before this tab loaded) would show as
    // read locally but the server would still think it's unread the
    // next time /users is fetched (new tab, refresh, restart).
    api.markRead(phone).catch((e) => console.error("markRead:", e));
  }, []);

  // Seed unread counts from the server on initial load (or reconnect),
  // since /users now returns each user's real unread_count computed
  // from the DB — this is what actually surfaces messages that arrived
  // while the dashboard was closed, which live socket events alone
  // can never do.
  const seedUnreadCounts = useCallback((usersData) => {
    setUnreadCounts((prev) => {
      const next = { ...prev };
      for (const u of usersData) {
        if (typeof u.unread_count === "number") next[u.phone] = u.unread_count;
      }
      return next;
    });
    setHighlightedUsers((prev) => {
      const s = new Set(prev);
      for (const u of usersData) {
        if (u.unread_count > 0) s.add(u.phone);
      }
      return s;
    });
  }, []);

  const incrementUnread = useCallback((phone) => {
    if (selectedPhoneRef.current === phone) return;
    setUnreadCounts((prev) => ({ ...prev, [phone]: (prev[phone] || 0) + 1 }));
    setHighlightedUsers((prev) => new Set(prev).add(phone));
  }, []);

  const appendMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateMessageStatus = useCallback((waId, status) => {
    if (!waId) return;
    setMessages((prev) => {
      // Try to find message by whatsapp_message_id
      const hasMatch = prev.some(
        (m) => m.whatsapp_message_id && m.whatsapp_message_id === waId
      );

      if (hasMatch) {
        return prev.map((m) =>
          m.whatsapp_message_id === waId ? { ...m, status } : m
        );
      }

      // Fallback — this only fires for messages that don't yet carry a
      // whatsapp_message_id at all (e.g. a broadcast from another
      // dashboard tab that never got the id attached client-side).
      // Match the OLDEST bot message still missing an id, not the most
      // recent — sends resolve roughly in the order they were made, so
      // picking "most recent" can misattribute a status update meant for
      // an earlier message onto a newer one if two sends are in flight
      // at once. `prev` is chronological (oldest first), so the first
      // match here is the oldest pending one.
      const pendingIndex = prev.findIndex(
        (m) => m.direction === "bot" && !m.whatsapp_message_id
      );

      if (pendingIndex !== -1) {
        return prev.map((m, i) =>
          i === pendingIndex
            ? { ...m, status, whatsapp_message_id: waId }
            : m
        );
      }

      return prev;
    });
  }, []);

  // extra: optional fields to merge in alongside status, e.g.
  // { whatsapp_message_id } — lets the sender attach the real id the
  // moment the API call resolves, instead of relying on the fallback
  // above to guess which pending message a later broadcast belongs to.
  const updateTempStatus = useCallback((tempId, status, extra = {}) => {
    setMessages((prev) =>
      prev.map((m) => (m._id === tempId ? { ...m, status, ...extra } : m))
    );
  }, []);

  const removeMessage = useCallback((ref) => {
    setMessages((prev) => prev.filter((m) => m !== ref));
  }, []);

  return {
    messages,
    setMessages,
    loading,
    unreadCounts,
    highlightedUsers,
    loadMessages,
    markAsRead,
    seedUnreadCounts,
    incrementUnread,
    appendMessage,
    updateMessageStatus,
    updateTempStatus,
    removeMessage,
    selectedPhoneRef,
  };
}