// Maps a backend status level to its presentation: a CSS class (colour),
// an icon, and a plain-words key. Status is ALWAYS conveyed by colour + icon +
// words together — never colour alone (safety/accessibility invariant #10).
export const STATUS_PRESENTATION = {
  normal: { className: "status-ok", icon: "✓" },
  watch: { className: "status-watch", icon: "👀" },
  "infection-risk": { className: "status-risk", icon: "⚠" },
  escalate: { className: "status-escalate", icon: "✚" },
  unknown: { className: "status-unknown", icon: "?" },
};

export function presentationForLevel(level) {
  return STATUS_PRESENTATION[level] || STATUS_PRESENTATION.unknown;
}

// Reading metadata: unit + icon per metric. Values + units are shown together.
export const READING_META = {
  ph: { unit: "pH", icon: "🧪", decimals: 1 },
  skin_temp_c: { unit: "°C", icon: "🌡️", decimals: 1 },
  moisture_pct: { unit: "%", icon: "💧", decimals: 0 },
  battery_pct: { unit: "%", icon: "🔋", decimals: 0 },
};

export const READING_ORDER = ["ph", "skin_temp_c", "moisture_pct", "battery_pct"];

// Human "x min ago" from an ISO timestamp. Pure + deterministic given `now`.
export function relativeTime(iso, now = Date.now()) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const diffMs = Math.max(0, now - then);
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function trendKey(direction) {
  if (direction === "rising" || direction === "up") return "rising";
  if (direction === "falling" || direction === "down") return "falling";
  if (direction === "insufficient_data") return "insufficient_data";
  return "steady";
}
