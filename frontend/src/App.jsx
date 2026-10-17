import { useCallback, useEffect, useMemo, useState } from "react";
import {
  APP_NAME,
  DEFAULT_WOUND_ID,
  EMERGENCY_NUMBER,
} from "./config.js";
import { makeTranslator } from "./i18n/strings.js";
import {
  fetchStatus,
  fetchTimeline,
  requestDose as apiRequestDose,
} from "./api/client.js";
import {
  presentationForLevel,
  READING_META,
  READING_ORDER,
  relativeTime,
  trendKey,
} from "./status.js";

const TEXT_SIZES = ["normal", "large", "xlarge"];

// The dashboard REQUESTS a guided session; it never chooses the dose. The
// backend/device enforce every cap and may decline. We send the minimal
// documented body; a real device profile would supply the guided defaults.
const DOSE_REQUEST_BODY = { requested_dose_mj: 0, requested_duration_s: 0 };

/**
 * App accepts an optional `loader` so tests can inject fixtures. In the browser
 * it defaults to the real API client reading the status + timeline endpoints.
 */
export default function App({
  woundId = DEFAULT_WOUND_ID,
  lang = "en",
  loader,
  doseRequester = apiRequestDose,
  now = Date.now(),
}) {
  const t = useMemo(() => makeTranslator(lang), [lang]);

  const load = useMemo(
    () =>
      loader ||
      (async (id) => {
        const [status, timeline] = await Promise.all([
          fetchStatus(id),
          fetchTimeline(id),
        ]);
        return { status, timeline };
      }),
    [loader],
  );

  const [state, setState] = useState({ phase: "loading" });
  const [textSize, setTextSize] = useState("normal");
  const [dose, setDose] = useState({ phase: "idle" });

  useEffect(() => {
    document.documentElement.setAttribute("data-size", textSize);
  }, [textSize]);

  const refresh = useCallback(() => {
    let active = true;
    setState({ phase: "loading" });
    Promise.resolve(load(woundId))
      .then((data) => {
        if (active) setState({ phase: "ready", ...data });
      })
      .catch(() => {
        if (active) setState({ phase: "error" });
      });
    return () => {
      active = false;
    };
  }, [load, woundId]);

  useEffect(() => refresh(), [refresh]);

  const onRequestDose = useCallback(async () => {
    setDose({ phase: "requesting" });
    try {
      const res = await doseRequester(woundId, DOSE_REQUEST_BODY);
      setDose({
        phase: res.ok ? "granted" : "denied",
        reason: res.payload && res.payload.reason,
      });
    } catch {
      setDose({ phase: "error" });
    }
  }, [doseRequester, woundId]);

  return (
    <>
      <a className="skip-link" href="#main-content">
        {t("skipToContent")}
      </a>

      <header className="app-bar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            {APP_NAME.charAt(0)}
          </span>
          <span>
            {t("appName")}
            <small>{t("tagline")}</small>
          </span>
        </div>

        <span className="spacer" />

        <div className="controls">
          <div className="size-group" role="group" aria-label={t("textSizeLabel")}>
            {TEXT_SIZES.map((size, i) => (
              <button
                key={size}
                type="button"
                aria-pressed={textSize === size}
                aria-label={`${t("textSizeLabel")} ${i + 1}`}
                style={{ fontSize: `${1 + i * 0.15}em` }}
                onClick={() => setTextSize(size)}
              >
                A
              </button>
            ))}
          </div>

          {/* Persistent emergency action, default number 112. */}
          <a
            className="btn emergency"
            href={`tel:${EMERGENCY_NUMBER}`}
            aria-label={t("emergencyAria")}
          >
            <span aria-hidden="true">☎</span> {t("emergency")} {EMERGENCY_NUMBER}
          </a>
        </div>
      </header>

      <main id="main-content">
        <h1 className="page-title">{t("pageTitle")}</h1>

        {state.phase === "loading" && (
          <div className="notice" role="status" aria-live="polite">
            {t("loading")}
          </div>
        )}

        {state.phase === "error" && (
          <div className="notice" role="alert">
            <p style={{ marginTop: 0 }}>{t("loadError")}</p>
            <button type="button" onClick={refresh}>
              {t("retry")}
            </button>
          </div>
        )}

        {state.phase === "ready" && (
          <Dashboard
            t={t}
            now={now}
            status={state.status}
            timeline={state.timeline}
            dose={dose}
            onRequestDose={onRequestDose}
          />
        )}

        <p className="disclaimer">
          <strong>{APP_NAME}</strong> — {t("disclaimer")}
        </p>
      </main>
    </>
  );
}

function Dashboard({ t, now, status, timeline, dose, onRequestDose }) {
  const level = status.level || "unknown";
  const presentation = presentationForLevel(level);
  const simulated = status.simulated === true;
  const sensorHealth = status.sensor_health || "unknown";
  const readings = latestReadings(timeline);

  return (
    <>
      {/* Primary status: colour (class) + icon + plain words — never colour alone. */}
      <div
        className={`status-card ${presentation.className}`}
        role="status"
        aria-live="polite"
        data-testid="status-card"
      >
        <span className="icon" aria-hidden="true" data-testid="status-icon">
          {presentation.icon}
        </span>
        <div>
          <h2 data-testid="status-title">{t(`status.${level}.title`)}</h2>
          <p data-testid="status-words">
            {status.reason || t(`status.${level}.words`)}
          </p>
        </div>
      </div>

      <div className="meta-row">
        <span className="pill">
          {t("lastUpdated")}:{" "}
          <strong>{relativeTime(status.last_updated, now) || "—"}</strong>
        </span>
        <span className="pill">
          {t("sensors")}:{" "}
          <span className={`sensor-${sensorHealth}`}>
            {t(`sensorHealth.${sensorHealth}`)}
          </span>
        </span>
        {status.stale === true && (
          <span className="pill stale-tag">{t("staleWarning")}</span>
        )}
        {simulated && (
          <span
            className="pill sim-tag"
            title={t("simulatedTitle")}
            data-testid="simulated-label"
          >
            {t("simulatedLabel")}
          </span>
        )}
      </div>

      <section aria-labelledby="readings-title">
        <h3 className="section-title" id="readings-title">
          {t("readings.heading")}
        </h3>
        <div className="grid">
          {readings ? (
            READING_ORDER.map((metric) => (
              <ReadingCard
                key={metric}
                t={t}
                now={now}
                metric={metric}
                reading={readings}
                trend={status.trend}
              />
            ))
          ) : (
            <div className="reading">{t("readings.noData")}</div>
          )}
        </div>
      </section>

      <section aria-labelledby="dose-title">
        <h3 className="section-title" id="dose-title">
          {t("dose.heading")}
        </h3>
        <div className="dose-card">
          <p style={{ marginTop: 0 }}>{t("dose.intro")}</p>
          {/* REQUEST-ONLY: no parameters chosen in the UI. */}
          <button
            type="button"
            className="btn-primary"
            onClick={onRequestDose}
            disabled={dose.phase === "requesting"}
          >
            {dose.phase === "requesting"
              ? t("dose.requesting")
              : t("dose.request")}
          </button>
          {dose.phase === "granted" && (
            <p className="dose-outcome">{t("dose.granted")}</p>
          )}
          {dose.phase === "denied" && (
            <p className="dose-outcome">
              {t("dose.denied")}
              {dose.reason ? ` ${dose.reason}` : ""}
            </p>
          )}
          {dose.phase === "error" && (
            <p className="dose-outcome">{t("dose.error")}</p>
          )}
          <div className="dose-note">{t("dose.note")}</div>
        </div>
      </section>

      <section aria-labelledby="apollo-title">
        <h3 className="section-title" id="apollo-title">
          {t("apollo.heading")}
        </h3>
        <div className="apollo">
          <div className="head">
            <span className="avatar" aria-hidden="true">
              A
            </span>
            <div>
              <strong>Apollo</strong>
              <div style={{ fontSize: "0.85em", color: "var(--ink-soft)" }}>
                {t("apollo.role")}
              </div>
            </div>
          </div>
          <div className="body">{t("apollo.body")}</div>
        </div>
      </section>
    </>
  );
}

function ReadingCard({ t, now, metric, reading, trend }) {
  const meta = READING_META[metric];
  const raw = reading[metric];
  const value =
    typeof raw === "number" ? raw.toFixed(meta.decimals) : "—";
  const direction = trendDirectionFor(metric, trend);

  return (
    <div className="reading">
      <div className="label">
        <span aria-hidden="true">{meta.icon}</span> {t(`readings.${metric}`)}
      </div>
      <div className="value">
        {value} <span className="unit">{meta.unit}</span>
      </div>
      {direction && (
        <div className="trend">
          {t("trend.heading")}: {t(`trend.${trendKey(direction)}`)}
        </div>
      )}
      <div className="updated">
        {t("lastUpdated")}: {relativeTime(reading.ts, now) || "—"}
      </div>
    </div>
  );
}

// The backend trend only covers ph + temp; other metrics have no trend yet.
function trendDirectionFor(metric, trend) {
  if (!trend) return null;
  if (metric === "ph") return trend.ph;
  if (metric === "skin_temp_c") return trend.temp;
  return null;
}

// Timeline readings are ts-ascending; the last one is the most recent.
function latestReadings(timeline) {
  if (!timeline || !Array.isArray(timeline.readings) || !timeline.readings.length) {
    return null;
  }
  return timeline.readings[timeline.readings.length - 1];
}
