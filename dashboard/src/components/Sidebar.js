import React, { useState } from "react";
import { api } from "../api/client";
import s from "../styles/Sidebar.module.css";
import bizLogo from "../assets/logos/bizadvise-logo.png";
import lawLogo from "../assets/logos/lawadvise-logo.png";

function getInitials(name, phone) {
  if (name) {
    const parts = name.trim().split(" ");
    return parts.length >= 2
      ? (parts[0][0] + parts[1][0]).toUpperCase()
      : parts[0][0].toUpperCase();
  }
  return phone?.slice(-2) || "?";
}

const AVATAR_COLORS = [
  "#667eea", "#764ba2", "#f093fb", "#4facfe",
  "#43e97b", "#fa709a", "#fd7043", "#26c6da",
];
function avatarColor(phone) {
  let sum = 0;
  for (const ch of (phone || "")) sum += ch.charCodeAt(0);
  return AVATAR_COLORS[sum % AVATAR_COLORS.length];
}

export default function Sidebar({
  users, selectedPhone, connected, unreadCounts,
  highlightedUsers, bookedConsultPhones, onSelect, onExportAll, onUserDeleted, onMarkAllRead,
}) {
  const [confirmPhone, setConfirmPhone] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = search.trim()
    ? users.filter((u) =>
        u.phone.includes(search) ||
        (u.name || "").toLowerCase().includes(search.toLowerCase())
      )
    : users;

  const totalUnread = users.reduce((acc, u) => acc + (unreadCounts[u.phone] || 0), 0);

  const handleDelete = async (e, phone) => {
    e.stopPropagation();
    setConfirmPhone(phone);
  };

  const confirmDelete = async () => {
    setDeleting(true);
    try {
      await api.deleteUser(confirmPhone);
      onUserDeleted(confirmPhone);
    } catch {
      alert("Failed to delete user.");
    } finally {
      setDeleting(false);
      setConfirmPhone(null);
    }
  };

  return (
    <aside className={s.sidebar}>

      {/* Brand header — both logos, premium navy/gold treatment */}
      <div className={s.brandHeader}>
        <img src={bizLogo} alt="BizAdvise Consulting" className={s.brandLogo} />
        <span className={s.brandDivider} />
        <img src={lawLogo} alt="LawAdvise Consulting" className={`${s.brandLogo} ${s.brandLogoSecond}`} />
      </div>

      {/* Header */}
      <div className={s.header}>
        <div className={s.headerTop}>
          <span className={s.title}>Chats</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Live dot */}
            <span
              className={s.connDot}
              style={{ background: connected ? "#4caf50" : "#f44336" }}
              title={connected ? "Live" : "Reconnecting..."}
            />
            {/* Mark all read */}
            {totalUnread > 0 && (
              <button className={s.markAllBtn} onClick={onMarkAllRead}>
                ✓ All read
              </button>
            )}
          </div>
        </div>

        {/* Search */}
        <div className={s.searchWrap}>
          <span className={s.searchIcon}>🔍</span>
          <input
            className={s.searchInput}
            placeholder="Search by name or number..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button className={s.searchClear} onClick={() => setSearch("")}>✕</button>
          )}
        </div>

        <button className={s.exportBtn} onClick={onExportAll}>
          ↓ Export all
        </button>
      </div>

      {/* User list */}
      <div className={s.list}>
        {filtered.length === 0 && (
          <p className={s.empty}>
            {search ? "No chats match your search." : "No users yet. Waiting for messages..."}
          </p>
        )}

        {filtered.map((user) => {
          const isUnread = highlightedUsers.has(user.phone);
          const isBooked = bookedConsultPhones?.has(user.phone);
          const count = unreadCounts[user.phone] || 0;
          const active = selectedPhone === user.phone;
          const initials = getInitials(user.name, user.phone);
          const color = avatarColor(user.phone);

          return (
            <div
              key={user.phone}
              className={`${s.user} ${active ? s.active : ""} ${isUnread && !active ? s.unread : ""} ${isBooked && !active ? s.booked : ""}`}
              onClick={() => onSelect(user)}
            >
              {/* Avatar with mode dot */}
              <div className={s.avatarWrap}>
                <div className={s.avatar} style={{ background: color }}>
                  {initials}
                </div>
                {/* Mode dot — green = AI, orange = Human */}
                <span
                  className={s.modeDot}
                  style={{ background: user.human_mode ? "#ff9800" : "#4caf50" }}
                  title={user.human_mode ? "Human mode — AI paused" : "AI mode — bot is active"}
                />
              </div>

              {/* Content */}
              <div className={s.content}>
                {/* Name + time + badge row */}
                <div className={s.topRow}>
                  <div className={s.nameGroup}>
                    <span className={`${s.name} ${isUnread && !active ? s.nameUnread : ""}`}>
                      {user.name || user.phone}
                    </span>
                    {user.name && (
                      <span className={s.subPhone}>{user.phone}</span>
                    )}
                    {isBooked && (
                      <span className={s.bookedBadge} title="Consultation booked">📋</span>
                    )}
                  </div>
                  <div className={s.rightCol}>
                    {user.last_seen && (
                      <span className={s.time}>
                        {new Date(user.last_seen).toLocaleTimeString([], {
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </span>
                    )}
                    {count > 0 && (
                      <span className={s.badge}>{count > 99 ? "99+" : count}</span>
                    )}
                  </div>
                </div>

                {/* Last message + delete */}
                <div className={s.bottomRow}>
                  <span className={`${s.last} ${isUnread && !active ? s.lastUnread : ""}`}>
                    {user.last || "No messages yet"}
                  </span>
                  <button
                    className={s.deleteBtn}
                    onClick={(e) => handleDelete(e, user.phone)}
                    title="Delete user"
                  >
                    🗑
                  </button>
                </div>

                {/* Tags */}
                {user.tags && (
                  <span className={s.tag}>{user.tags}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Confirm delete */}
      {confirmPhone && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 2000,
        }}>
          <div style={{
            background: "#fff", borderRadius: 12, padding: 24,
            width: 320, boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
          }}>
            <h3 style={{ marginBottom: 8, color: "#333" }}>Delete user?</h3>
            <p style={{ fontSize: 13, color: "#666", marginBottom: 20 }}>
              This will permanently delete <strong>{confirmPhone}</strong> and all
              their messages. This cannot be undone.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setConfirmPhone(null)}
                style={{ padding: "8px 16px", background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 8, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                style={{ padding: "8px 16px", background: "#f44336", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}