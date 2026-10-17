import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import App from "./App.jsx";
import { strings } from "./i18n/strings.js";
import { STATUS_PRESENTATION } from "./status.js";

// Fixture matching the FEAT-004 status + timeline contract, with simulated=true.
function makeFixture(level = "watch") {
  const ts = new Date().toISOString();
  return {
    status: {
      wound_id: "A-204",
      level,
      machine_code: null,
      data_level: level,
      red_flags: [],
      sensor_health: "ok",
      stale: false,
      simulated: true,
      trend: { ph: "rising", temp: "steady", status: "ok" },
      confidence: "normal",
      reason: "pH has risen a little over the last day.",
      last_updated: ts,
      config_snapshot: "sha256:test",
    },
    timeline: {
      wound_id: "A-204",
      readings: [
        {
          reading_id: 1,
          ts,
          ph: 7.9,
          skin_temp_c: 33.4,
          moisture_pct: 58,
          battery_pct: 72,
          sensor_status: "ok",
          simulated: true,
          field_flags: {},
        },
      ],
      statuses: [],
    },
  };
}

function renderApp(fixture) {
  const loader = vi.fn().mockResolvedValue(fixture);
  render(<App loader={loader} doseRequester={vi.fn()} />);
}

describe("Sushruta dashboard status presentation", () => {
  it("renders status as colour + icon + plain words together (not colour alone)", async () => {
    const fixture = makeFixture("watch");
    renderApp(fixture);

    const card = await screen.findByTestId("status-card");

    // Colour: the level-specific class is applied.
    expect(card).toHaveClass(STATUS_PRESENTATION.watch.className);

    // Icon: a non-empty icon glyph accompanies the colour.
    const icon = screen.getByTestId("status-icon");
    expect(icon.textContent.trim()).toBe(STATUS_PRESENTATION.watch.icon);
    expect(icon.textContent.trim().length).toBeGreaterThan(0);

    // Plain words: the status title and reason text are present, so the status
    // is never conveyed by colour alone.
    expect(screen.getByTestId("status-title")).toHaveTextContent(
      strings.en.status.watch.title,
    );
    const words = screen.getByTestId("status-words");
    expect(words.textContent.trim().length).toBeGreaterThan(0);
    expect(words).toHaveTextContent(fixture.status.reason);
  });

  it("shows the SIMULATED label when the data is simulated", async () => {
    renderApp(makeFixture("watch"));

    const sim = await screen.findByTestId("simulated-label");
    expect(sim).toHaveTextContent(strings.en.simulatedLabel);
  });

  it("renders a request-only dose button and a persistent emergency action", async () => {
    renderApp(makeFixture("normal"));

    await screen.findByTestId("status-card");

    expect(
      screen.getByRole("button", { name: strings.en.dose.request }),
    ).toBeInTheDocument();

    const emergency = screen.getByRole("link", {
      name: /Emergency/i,
    });
    expect(emergency).toHaveAttribute("href", "tel:112");
  });

  it("surfaces each status level with distinct colour + icon + words", async () => {
    for (const level of ["normal", "watch", "infection-risk", "escalate"]) {
      const { unmount } = renderInline(makeFixture(level));
      const card = await screen.findByTestId("status-card");
      expect(card).toHaveClass(STATUS_PRESENTATION[level].className);
      expect(screen.getByTestId("status-icon").textContent.trim()).toBe(
        STATUS_PRESENTATION[level].icon,
      );
      expect(screen.getByTestId("status-title").textContent.trim().length).toBeGreaterThan(0);
      unmount();
    }
  });
});

function renderInline(fixture) {
  const loader = vi.fn().mockResolvedValue(fixture);
  return render(<App loader={loader} doseRequester={vi.fn()} />);
}
