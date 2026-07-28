import React, { useRef } from "react";
import s from "../styles/Modal.module.css";
import a from "../styles/Analytics.module.css";

export default function AnalyticsModal({ stats, onClose }) {
  const modalRef = useRef(null);
  const handleOverlay = (e) => { if (!modalRef.current?.contains(e.target)) onClose(); };

  const maxActivity = Math.max(...(stats.daily_activity || []).map((d) => d.messages), 1);

  return (
    <div className={s.overlay} onMouseDown={handleOverlay}>
      <div className={`${s.modal} ${s.wide}`} ref={modalRef}>
        <div className={s.header}>
          <h2>Analytics</h2>
          <button className={s.closeBtn} onClick={onClose}>×</button>
        </div>
        <div className={`${s.body} ${s.scrollable}`}>

          <div className={a.cards}>
            {[
              { label: "Total users", value: stats.total_users || 0 },
              { label: "Total messages", value: stats.total_messages || 0 },
              { label: "Avg response", value: `${stats.avg_response_time || 0} min` },
              { label: "Today", value: stats.messages_today || 0 },
            ].map((c) => (
              <div key={c.label} className={a.card}>
                <div className={a.cardValue}>{c.value}</div>
                <div className={a.cardLabel}>{c.label}</div>
              </div>
            ))}
          </div>

          <div className={a.section}>
            <h3>Mode distribution</h3>
            <div className={a.row}>
              {[
                { label: "AI mode users", count: stats.ai_users || 0, color: "#4caf50" },
                { label: "Human mode users", count: stats.human_users || 0, color: "#ff9800" },
              ].map((item) => (
                <div key={item.label} className={a.statBox}>
                  <div className={a.statNum}>{item.count}</div>
                  <div className={a.statLabel}>{item.label}</div>
                  <div className={a.bar}>
                    <div
                      className={a.barFill}
                      style={{
                        width: `${(item.count / (stats.total_users || 1)) * 100}%`,
                        background: item.color,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {stats.daily_activity?.length > 0 && (
            <div className={a.section}>
              <h3>Daily activity (last 7 days)</h3>
              {stats.daily_activity.map((day, i) => (
                <div key={i} className={a.chartRow}>
                  <span className={a.chartDate}>{new Date(day.date).toLocaleDateString()}</span>
                  <div className={a.chartTrack}>
                    <div
                      className={a.chartFill}
                      style={{ width: `${(day.messages / maxActivity) * 100}%` }}
                    />
                    <span className={a.chartVal}>{day.messages}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {stats.top_users?.length > 0 && (
            <div className={a.section}>
              <h3>Top active users</h3>
              {stats.top_users.map((u, i) => (
                <div key={i} className={a.topRow}>
                  <span className={a.rank}>#{i + 1}</span>
                  <span className={a.topPhone}>{u.phone}</span>
                  <span className={a.topMsgs}>{u.messages} messages</span>
                </div>
              ))}
            </div>
          )}

          {stats.top_questions?.length > 0 && (
            <div className={a.section}>
              <h3>Most asked questions</h3>
              {stats.top_questions.map((q, i) => (
                <div key={i} className={a.qItem}>
                  <div className={a.qText}>"{q.question}"</div>
                  <div className={a.qCount}>Asked {q.count} times</div>
                </div>
              ))}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
