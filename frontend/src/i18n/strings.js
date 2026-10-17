// i18n-ready string catalogue. English now; the structure is ready for Hindi
// (add an `hi` block with the same keys and switch via setLang). No user-facing
// copy is hardcoded in components — everything routes through `t`.
import { APP_NAME, EMERGENCY_NUMBER } from "../config.js";

export const strings = {
  en: {
    appName: APP_NAME,
    tagline: "Smart bandage companion",
    pageTitle: "Your wound today",
    skipToContent: "Skip to main content",

    textSizeLabel: "Text size",
    languageLabel: "Language",
    emergency: "Emergency",
    emergencyAria: `Call the emergency number ${EMERGENCY_NUMBER}`,

    loading: "Loading your latest readings…",
    loadError:
      "We could not reach the monitoring service. Please check your connection and try again.",
    retry: "Try again",

    simulatedLabel: "SIMULATED DATA",
    simulatedTitle: "This view is showing simulated demo data, not live sensor data.",
    lastUpdated: "Last updated",
    sensors: "Sensors",
    staleWarning: "Readings are out of date",

    // Status levels: plain words shown alongside colour + icon (never colour alone).
    status: {
      normal: {
        title: "Looking good",
        words: "Healing looks on track",
      },
      watch: {
        title: "Keep watching",
        words: "Mostly fine, but worth checking again soon",
      },
      "infection-risk": {
        title: "Possible infection risk",
        words: "Some signs need attention — review carefully",
      },
      escalate: {
        title: "See a doctor today",
        words: "Signs suggest you should seek care now",
      },
      unknown: {
        title: "Status unavailable",
        words: "We do not have a fresh, usable reading yet",
      },
    },

    sensorHealth: {
      ok: "All OK",
      drifting: "Drifting",
      disconnected: "Offline",
      unknown: "Unknown",
    },

    readings: {
      heading: "Latest readings",
      ph: "Wound pH",
      skin_temp_c: "Skin temperature",
      moisture_pct: "Moisture",
      battery_pct: "Bandage battery",
      noData: "No readings yet",
    },

    trend: {
      heading: "Trend",
      rising: "rising",
      falling: "falling",
      steady: "steady",
      insufficient_data: "not enough data yet",
    },

    dose: {
      heading: "405 nm violet light therapy",
      intro:
        "One guided session can be requested. The bandage enforces safe limits automatically.",
      request: "Request a light session",
      requesting: "Requesting…",
      note: "Daily and per-session limits are enforced by the device for your safety and cannot be overridden from the app.",
      granted: "Session approved. The device will run it within its safe limits.",
      denied: "Request declined for your safety.",
      error: "We could not send the request. Please try again.",
    },

    apollo: {
      heading: "Ask Apollo",
      role: "Wound-care assistant · explains, never diagnoses",
      placeholder: "Apollo is coming soon.",
      body: "Apollo will explain your readings in plain words and point you to trusted guidance. It never diagnoses — always consult a doctor if you are unsure.",
    },

    disclaimer:
      "Proof of concept — not a medical device. All data shown may be simulated. This software does not diagnose. Always seek professional medical care, and call your local emergency number for urgent symptoms.",
  },
};

// Simple translator. Dotted keys resolve into the nested catalogue; unknown
// keys fall back to the key itself so a missing translation is obvious.
export function makeTranslator(lang = "en") {
  const dict = strings[lang] || strings.en;
  return function t(key) {
    const parts = String(key).split(".");
    let node = dict;
    for (const part of parts) {
      if (node && typeof node === "object" && part in node) {
        node = node[part];
      } else {
        return key;
      }
    }
    return typeof node === "string" ? node : key;
  };
}

export const AVAILABLE_LANGS = ["en"];
