# FRIDAY — Build Prompt & Validation Spec (view-only)

**Hand this to an agentic coding tool (Antigravity / Jules / Claude Code).**
Build in the numbered phases. **Do not proceed past a phase until its validation gate passes.** If a gate cannot be met, stop and report — do not work around it.

**Scope:** This is a **research & visualization tool only**. It generates forecasts and shows them in a UI. It does **not** place orders, connect to a broker, or automate trading. Do not add execution, OpenAlgo, or any order-routing capability.

---

## 0. Mission

Build a personal (single-user) NSE equity research tool called **FRIDAY**: a hierarchical 5-day forecast dashboard powered by the **Kronos** time-series foundation model, with an inbuilt screener.

- Drill-through: **Market (Nifty 50) → sector index → individual stock**.
- Each instrument shows a **5-day forecast** drawn as an **uncertainty cone**, plus a compact fundamentals snapshot at stock level.
- A **screener** ranks stocks by forecast.

A working HTML/JS UI mockup with synthetic data already exists and defines the target UX and the data shape. The job is to make it real: pull live NSE data, run Kronos, and render it.

---

## 1. Non-negotiable principles (read first, never violate)

1. **Kronos is a time-series model, NOT an LLM.** Input = numeric OHLCV; output = numeric forecast. No language model is required anywhere. Do not add one unless explicitly told to.
2. **Forecasts are independent per instrument.** The Nifty forecast does NOT drive index or stock forecasts. They may disagree. Never present the hierarchy as a causal cascade — it is an organizational tree.
3. **Forecast = horizon of 5 daily candles. Bars = daily (EOD).** Do not mix frequencies. Do not extend the horizon to make charts look better.
4. **Always represent uncertainty.** Show the forecast as a cone (sampled-path spread), never a single confident line. Default screener sort = **risk-adjusted** (forecast return ÷ cone width), not raw return. (A view-only tool that shows confident single lines is *more* dangerous, because the user eye-trades off it manually.)
5. **No look-ahead, no survivorship bias.** Use split/bonus/dividend-**adjusted** prices and **point-in-time** index membership and fundamentals.
6. **The screener output is a WATCHLIST, not a buy list.** Label signals "WATCH/AVOID", never "BUY". The user makes all decisions manually.
7. **Personal, view-only tool.** No multi-user, no distribution, no order execution. Add a "not investment advice" notice in the UI.

---

## 2. Tech stack (use unless you justify a change)

- **Language:** Python 3.11+ (pipeline), JavaScript (frontend already in HTML; React optional later).
- **Data:** `jugaad-data` / `nsepython` for NSE EOD; pandas. Optional `yfinance` cross-check.
- **Model:** Kronos (`shiyu-coder/Kronos`) — start with `Kronos-base` pretrained, zero-shot, then optionally fine-tune.
- **Storage:** SQLite for local dev (single file). Schema designed to migrate to Supabase later.
- **Scheduling:** cron / GitHub Actions for the nightly forecast batch (free; fine since nothing trades).
- **GPU:** Kronos-base runs on a single T4 (free Colab) for ~50–250 instruments.

---

## 3. Data contracts (the UI already expects these)

**Instrument forecast (per symbol), JSON:**
```json
{
  "code": "TCS",
  "name": "Tata Consultancy",
  "level": "stock",            // "market" | "index" | "stock"
  "last": 4120.5,
  "hist": [/* N daily closes, adjusted */],
  "med": [d1,d2,d3,d4,d5],     // forecast median path
  "up":  [d1,d2,d3,d4,d5],     // upper cone (e.g. P90)
  "lo":  [d1,d2,d3,d4,d5],     // lower cone (e.g. P10)
  "ret": 2.31,                 // % change last -> med[4]
  "cone_width_pct": 6.4,       // (up[4]-lo[4]) / last * 100
  "asof": "2026-06-05"
}
```

**Stock fundamentals (point-in-time), JSON:**
```json
{ "code":"TCS","mcap_cr":1500000,"pe":28.4,"roe":44.2,"de":0.05,
  "sales_growth_yoy":7.1,"hi_52w":4600,"lo_52w":3100,"asof":"2026-06-05" }
```

**Hierarchy:** market (NIFTY 50) → list of sector indices → each index's constituent symbols. Index membership is point-in-time.

---

## 4. Phased build with validation gates

### Phase 1 — Data layer  *(no ML)*
**Scope:** Fetch NSE EOD OHLCV for Nifty 50, the sector indices, and their constituents. Apply corporate-action adjustment. Build a point-in-time index-membership table. Write to SQLite. Emit the `hist`/`last` fields of the forecast contract (leave `med/up/lo` empty for now). Include an NSE trading-holiday calendar so "next 5 days" means 5 *sessions*.
**Deliverables:** `fetch_eod.py`, `adjust_corporate_actions.py`, `schema.sql`, a CLI to refresh data.
**✅ Validation gate:**
- Re-running the fetcher is idempotent (no dupes).
- A known historical split is correctly adjusted — assert pre/post continuity in a unit test.
- A delisted symbol from a past index is present in history (proves no survivorship hole).
- Holiday calendar: assert the day after a known holiday is treated as the next session.
- The existing UI, pointed at this data, renders real prices (empty cones OK).

### Phase 2 — Forecast batch  *(Kronos)*
**Scope:** Load Kronos-base. For each instrument, feed the lookback window (start: 180 sessions), sample `sample_count≈30` paths over a 5-session horizon, and write `med` (median), `up`/`lo` (P90/P10), `ret`, `cone_width_pct`. Make lookback, horizon, and sample_count config values.
**Deliverables:** `forecast_batch.py`, `config.yaml`, batch run writing forecasts to SQLite.
**✅ Validation gate:**
- Runs end-to-end for the full universe within a documented time/VRAM budget on a single T4.
- Cones widen monotonically with horizon (assert `up-lo` at d5 > at d1) — uncertainty must grow.
- Output JSON validates against the Phase 3 contract schema (add a JSON-schema check).
- UI now shows real forecast cones via the same code path as the mockup.

### Phase 3 — Frontend (productionize the mockup)
**Scope:** Wire the existing UI to read from SQLite/API instead of the synthetic `series()` generator. Keep the lean feature set: drill-through, 5-day cone, 6-metric fundamentals, screener with Direction + Index filters and risk-adjusted default sort. Add a small read-only "data status" per stock (e.g. liquidity OK / earnings-within-horizon) so the user knows when a forecast is less reliable.
**Deliverables:** API endpoints (or static JSON export), updated frontend, "not investment advice" notice.
**✅ Validation gate:**
- No synthetic data remains; every number traces to the DB.
- Drill levels, screener filters, and risk-adjusted sort work against real data.
- Data-status flags render correctly.

---

## 5. Optional — Forecast sanity check  *(not a gate; do only if asked)*
Since nothing is traded, a full cost-aware backtest is **not required**. But to know whether the forecasts carry any signal, optionally measure **directional hit-rate**: over a historical span, how often did `med[4]`'s direction match the actual 5-session move? Compare against a naive baseline (e.g. "tomorrow = today"). Report honestly; do not tune the model to look good. This informs how much to trust the screen — it does not block any phase.

---

## 6. Global requirements
- **Tests:** every phase ships unit tests for its validation gate; CI runs them.
- **Config over hardcoding:** lookback, horizon, sample_count, filters all in config.
- **Reproducibility:** seed randomness; log model version, data as-of date, and config with every run.
- **Document assumptions:** especially which data source supplies fundamentals.

## 7. Explicitly out of scope (do not build)
Order execution / OpenAlgo / broker APIs; automated or live trading; intraday/scalping; F&O; multi-user accounts; selling or sharing signals; an LLM layer; any "guaranteed returns" framing.

## 8. Definition of done
Phases 1–3 complete with all gates green; the dashboard runs on real NSE data, showing 5-day Kronos forecast cones across the market → index → stock drill-through plus the screener. The tool only generates and displays — it never trades.

---

*FRIDAY is a personal research tool. Forecasts are probabilistic and shown as uncertainty cones. Nothing it outputs is investment advice.*
