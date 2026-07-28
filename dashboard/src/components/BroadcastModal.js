import React, { useState, useRef } from "react";
import { api } from "../api/client";
import s from "../styles/Modal.module.css";

export default function BroadcastModal({ users, onClose }) {
  const [message, setMessage] = useState("");
  const [broadcasting, setBroadcasting] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [result, setResult] = useState(null);
  const cancelRef = useRef(false);
  const modalRef = useRef(null);

  const handleOverlayClick = (e) => {
    if (!modalRef.current?.contains(e.target)) onClose();
  };

  const send = async () => {
    if (!message.trim() || users.length === 0) return;
    setBroadcasting(true);
    cancelRef.current = false;
    setProgress({ current: 0, total: users.length });

    let ok = 0;
    let fail = 0;

    for (let i = 0; i < users.length; i++) {
      if (cancelRef.current) break;
      setProgress({ current: i + 1, total: users.length });
      try {
        await api.sendMessage(users[i].phone, message);
        ok++;
      } catch {
        fail++;
      }
      await new Promise((r) => setTimeout(r, 500));
    }

    setBroadcasting(false);
    setResult({ ok, fail });
  };

  return (
    <div className={s.overlay} onMouseDown={handleOverlayClick}>
      <div className={s.modal} ref={modalRef}>
        <div className={s.header}>
          <h2>Broadcast message</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>
        <div className={s.body}>
          {result ? (
            <div>
              <p>Broadcast complete.</p>
              <p>Sent: {result.ok} &nbsp; Failed: {result.fail}</p>
              <button className={s.primaryBtn} onClick={onClose} style={{ marginTop: 16 }}>Close</button>
            </div>
          ) : (
            <>
              <p className={s.info}>Will be sent to <strong>{users.length}</strong> user(s)</p>
              <textarea
                className={s.textarea}
                rows={6}
                placeholder="Type your broadcast message..."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
              {broadcasting && (
                <div className={s.progressWrap}>
                  <div className={s.progressBar}>
                    <div
                      className={s.progressFill}
                      style={{ width: `${(progress.current / progress.total) * 100}%` }}
                    />
                  </div>
                  <div className={s.progressText}>{progress.current} / {progress.total}</div>
                </div>
              )}
            </>
          )}
        </div>
        {!result && (
          <div className={s.footer}>
            {broadcasting
              ? <button className={s.cancelBtn} onClick={() => { cancelRef.current = true; }}>Stop</button>
              : <button className={s.cancelBtn} onClick={onClose}>Cancel</button>
            }
            <button className={s.primaryBtn} onClick={send} disabled={broadcasting || !message.trim()}>
              {broadcasting ? "Sending..." : "Send broadcast"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
