// Thin client over the FastAPI status/timeline/dose endpoints (FEAT-004).
// Returns parsed JSON or throws so the UI can show a plain-words error.
import { API_BASE } from "../config.js";

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Request failed (${res.status})`);
  }
  return res.json();
}

export function fetchStatus(woundId) {
  return getJson(`/wounds/${encodeURIComponent(woundId)}/status`);
}

export function fetchTimeline(woundId, { limit = 20 } = {}) {
  return getJson(
    `/wounds/${encodeURIComponent(woundId)}/timeline?limit=${limit}`,
  );
}

// Dose is REQUEST-ONLY from the UI: the device/backend enforce every cap.
// The UI never sends dose/duration parameters it chose itself; the backend
// decides what a "guided session" means. We send its documented minimal body.
export async function requestDose(woundId, requested) {
  const res = await fetch(
    `${API_BASE}/wounds/${encodeURIComponent(woundId)}/dose-requests`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(requested),
    },
  );
  const payload = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, payload };
}
