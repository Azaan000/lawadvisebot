import React, { useEffect, useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";
import c from "../styles/Consultations.module.css";
import { playNotificationSound } from "../utils/notificationSound";

export default function ConsultationsModal({ onClose, onSelectUser, users, onUserDeleted, latestBooking }) {
  const [consultations, setConsultations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmPhone, setConfirmPhone] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [justBookedPhone, setJustBookedPhone] = useState(null);
  const modalRef = useRef(null);
  const mountedAtRef = useRef(Date.now());

  const refresh = () => {
    api.getConsultations()
      .then(setConsultations)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    refresh();
  }, []);

  // Previously this modal only ever fetched once, on mount — a booking
  // that came in while staff already had it open wouldn't appear (or
  // make a sound) until they closed and reopened it. Now it reacts live.
  useEffect(() => {
    if (!latestBooking) return;
    // Ignore whatever the parent's initial/leftover state was BEFORE
    // this modal was even opened — only react to bookings that happen
    // while it's actually mounted.
    if (latestBooking.at <= mountedAtRef.current) return;

    playNotificationSound();
    setJustBookedPhone(latestBooking.phone);
    refresh();

    const t = setTimeout(() => setJustBookedPhone(null), 4000);
    return () => clearTimeout(t);
  }, [latestBooking]);

  const handleOverlay = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  const handleClick = (phone) => {
    const user = users.find((u) => u.phone === phone);
    if (user) {
      onSelectUser(user);
      onClose();
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteUser(confirmPhone);
      setConsultations((prev) => prev.filter((c) => c.phone !== confirmPhone));
      onUserDeleted(confirmPhone);
      setConfirmPhone(null);
    } catch {
      alert("Failed to delete user.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={`${s.modal} ${s.wide}`} ref={modalRef}>
        <div className={s.header}>
          <h2>📋 Consultation Requests</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>
        <div className={`${s.body} ${s.scrollable}`}>
          {loading && <div className={c.loading}>Loading...</div>}

          {!loading && consultations.length === 0 && (
            <div className={c.empty}>No consultation requests yet.</div>
          )}

          {!loading && consultations.length > 0 && (
            <>
              <div className={c.count}>
                {consultations.length} user{consultations.length !== 1 ? "s" : ""} requested a consultation
              </div>
              <div className={c.list}>
                {consultations.map((item) => (
                  <div key={item.phone} className={`${c.card} ${item.phone === justBookedPhone ? c.justBooked : ""}`}>
                    <div className={c.cardLeft}>
                      <div className={c.avatar}>
                        {(item.name || item.phone).charAt(0).toUpperCase()}
                      </div>
                    </div>
                    <div className={c.cardBody} onClick={() => handleClick(item.phone)}>
                      <div className={c.nameRow}>
                        <span className={c.name}>{item.name || item.phone}</span>
                        {item.name && <span className={c.phone}>{item.phone}</span>}
                        {item.tags && <span className={c.tag}>{item.tags}</span>}
                      </div>
                      <div className={c.lastMsg}>"{item.last_consult_message}"</div>
                      <div className={c.meta}>
                        <span>🕐 {new Date(item.last_request).toLocaleString()}</span>
                        <span>📨 {item.consult_count} request{item.consult_count !== 1 ? "s" : ""}</span>
                      </div>
                    </div>
                    <div className={c.cardRight}>
                      <button className={c.openBtn} onClick={() => handleClick(item.phone)}>
                        Open Chat →
                      </button>
                      <button
                        className={c.deleteBtn}
                        onClick={() => setConfirmPhone(item.phone)}
                        title="Delete user"
                      >
                        🗑 Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Confirm delete */}
      {confirmPhone && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2000,
        }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 24,
            width: 320, boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
          }}>
            <h3 style={{ marginBottom: 8, color: "#333" }}>Delete user?</h3>
            <p style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
              This will permanently delete <strong>{confirmPhone}</strong> and all their messages. This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmPhone(null)}
                style={{ padding: "8px 16px", background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                style={{ padding: "8px 16px", background: "#f44336", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}