const BASE = process.env.REACT_APP_API_URL || "http://localhost:5000";
const SECRET = process.env.REACT_APP_DASHBOARD_SECRET || "";

function headers(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-Dashboard-Token": SECRET,
    ...extra,
  };
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: headers(),
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "Request failed");
  }
  return res.json();
}

export const api = {
  getUsers: () => request("/users"),

  getMessages: (phone, search = "") =>
    request(`/messages/${phone}${search ? `?search=${encodeURIComponent(search)}` : ""}`),

  sendMessage: (phone, message) =>
    request("/send", {
      method: "POST",
      body: JSON.stringify({ phone, message }),
    }),

  sendFile: (phone, file, caption = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("phone", phone);
    if (caption) form.append("caption", caption);
    return fetch(`${BASE}/send-file`, {
      method: "POST",
      headers: { "X-Dashboard-Token": SECRET },
      body: form,
    }).then((r) => {
      if (!r.ok) throw new Error("Failed to send file");
      return r.json();
    });
  },

  toggleMode: (phone) =>
    request(`/toggle/${phone}`, { method: "POST" }),

  updateUser: (phone, tags, notes) =>
    request("/update-user", {
      method: "POST",
      body: JSON.stringify({ phone, tags, notes }),
    }),

  deleteUser: (phone) =>
    request(`/delete-user/${phone}`, { method: "DELETE" }),

  getAnalytics: () => request("/analytics"),

  getConsultations: () => request("/consultations"),

  exportCsv: (phone = null) => {
    const params = new URLSearchParams({ token: SECRET });
    if (phone) params.append("phone", phone);
    window.open(`${BASE}/export/csv?${params.toString()}`, "_blank");
  },

  reloadKnowledge: () =>
    request("/reload-knowledge", { method: "POST" }),
};

export { BASE, SECRET };