import { run } from "uebersicht";
import config from "./config.json";

const display = config.display || {};
const position = display.position || {};
const runtime = config.runtime || {};
const ROOT = String(runtime.root || "").trim();
const ACTION = ROOT ? `"${ROOT}/bin/widget_action.sh"` : "";
const setupRequiredJson = JSON.stringify({
  generated_at: "",
  source: "widget",
  cache_status: "setup_required",
  rows: [],
  summary: { total: 0, ok: 0, stale: 0, errors: 1 },
  error: "Setup required. Run bin/setup.sh from the widget folder.",
});
const DEFAULT_POSITION = { top: "185px", left: "28px", width: "420px" };
const MIN_WIDGET_WIDTH = 300;
const MAX_WIDGET_WIDTH = 760;
const MIN_WIDGET_HEIGHT = 340;
const MAX_WIDGET_HEIGHT = 1100;
const THEMES = ["graphite", "light", "midnight", "mono"];
const DEFAULT_THEME = "graphite";

const shellSafeJson = value => `'${String(value).replace(/'/g, `'\\''`)}'`;
const normalizeTheme = theme => THEMES.includes(String(theme || "").toLowerCase()) ? String(theme).toLowerCase() : DEFAULT_THEME;
const cleanCompact = value => value === undefined || value === null ? true : Boolean(value);
const clampNumber = (value, min, max) => Math.max(min, Math.min(max, value));
const pxNumber = (value, fallback) => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = parseFloat(String(value || "").replace("px", ""));
  return Number.isFinite(parsed) ? parsed : fallback;
};
const px = value => `${Math.round(value)}px`;
const normalizePosition = value => {
  const raw = value || {};
  const top = clampNumber(pxNumber(raw.top, pxNumber(DEFAULT_POSITION.top, 185)), 0, 1400);
  const left = clampNumber(pxNumber(raw.left, pxNumber(DEFAULT_POSITION.left, 28)), 0, 3000);
  const width = clampNumber(pxNumber(raw.width, pxNumber(DEFAULT_POSITION.width, 420)), MIN_WIDGET_WIDTH, MAX_WIDGET_WIDTH);
  const normalized = { top: px(top), left: px(left), width: px(width) };
  if (raw.max_height) {
    normalized.max_height = px(clampNumber(pxNumber(raw.max_height, 640), MIN_WIDGET_HEIGHT, MAX_WIDGET_HEIGHT));
  }
  return normalized;
};
const basePosition = normalizePosition(position);
const widgetTop = basePosition.top;
const widgetMaxHeight = basePosition.max_height || display.max_height || `calc(100vh - ${widgetTop} - 16px)`;

export const command = ROOT ? `"${ROOT}/bin/run_widget.sh"` : `printf ${shellSafeJson(setupRequiredJson)}`;
export const refreshFrequency = Math.max(15, Number(display.refresh_seconds || 60)) * 1000;

export const initialState = {
  output: "",
  data: null,
  editorOpen: false,
  tickerInput: "",
  eventInput: "",
  dateInput: "",
  thresholdInput: "",
  timingInput: "unknown",
  themeOverride: null,
  compactOverride: null,
  positionOverride: null,
  layoutOpen: false,
  loading: false,
  actionError: null,
};

const parseJson = text => {
  try { return JSON.parse(text); } catch (e) { return null; }
};

const patchDisplayState = (state, patch) => {
  const current = state.data || parseJson(state.output) || {};
  const nextData = { ...current, display: { ...(current.display || {}), ...patch } };
  return { ...state, data: nextData, output: JSON.stringify(nextData), actionError: null };
};

export const updateState = (event, previousState = initialState) => {
  if (event.type === "TOGGLE_EDITOR") {
    return { ...previousState, editorOpen: !previousState.editorOpen, actionError: null };
  }
  if (event.type === "TOGGLE_LAYOUT") {
    return { ...previousState, layoutOpen: !previousState.layoutOpen, actionError: null };
  }
  if (event.type === "TICKER_INPUT") {
    return { ...previousState, tickerInput: event.value.toUpperCase(), actionError: null };
  }
  if (event.type === "EVENT_INPUT") {
    return { ...previousState, eventInput: event.value, actionError: null };
  }
  if (event.type === "DATE_INPUT") {
    return { ...previousState, dateInput: event.value, actionError: null };
  }
  if (event.type === "THRESHOLD_INPUT") {
    return { ...previousState, thresholdInput: event.value, actionError: null };
  }
  if (event.type === "TIMING_INPUT") {
    return { ...previousState, timingInput: event.value, actionError: null };
  }
  if (event.type === "ACTION_LOADING") {
    return { ...previousState, loading: true, actionError: null };
  }
  if (event.type === "THEME_LOCAL") {
    return { ...patchDisplayState(previousState, { theme: normalizeTheme(event.theme) }), themeOverride: normalizeTheme(event.theme) };
  }
  if (event.type === "THEME_SAVED") {
    const payload = parseJson(event.output);
    if (!payload || !payload.ok) {
      return { ...previousState, actionError: (payload && payload.error) || "Could not save theme." };
    }
    const theme = normalizeTheme(payload.display && payload.display.theme);
    return { ...patchDisplayState(previousState, { ...(payload.display || {}), theme }), themeOverride: theme };
  }
  if (event.type === "COMPACT_LOCAL") {
    const compact = cleanCompact(event.compact);
    return { ...patchDisplayState(previousState, { compact }), compactOverride: compact };
  }
  if (event.type === "COMPACT_SAVED") {
    const payload = parseJson(event.output);
    if (!payload || !payload.ok) {
      return { ...previousState, actionError: (payload && payload.error) || "Could not save display mode." };
    }
    const compact = cleanCompact(payload.display && payload.display.compact);
    return { ...patchDisplayState(previousState, { ...(payload.display || {}), compact }), compactOverride: compact };
  }
  if (event.type === "LAYOUT_LOCAL") {
    const nextPosition = normalizePosition(event.position);
    return { ...patchDisplayState(previousState, { position: nextPosition }), positionOverride: nextPosition };
  }
  if (event.type === "LAYOUT_SAVED") {
    const payload = parseJson(event.output);
    if (!payload || !payload.ok) {
      return { ...previousState, actionError: (payload && payload.error) || "Could not save layout." };
    }
    const nextPosition = normalizePosition(payload.display && payload.display.position);
    return { ...patchDisplayState(previousState, { ...(payload.display || {}), position: nextPosition }), positionOverride: nextPosition };
  }
  if (event.type === "SET_WATCHLIST") {
    const payload = parseJson(event.output);
    if (!payload || !payload.ok) {
      return { ...previousState, loading: false, actionError: (payload && payload.error) || "Could not update watchlist." };
    }
    return {
      ...previousState,
      loading: false,
      data: payload.data,
      output: JSON.stringify(payload.data),
      editorOpen: false,
      tickerInput: "",
      eventInput: "",
      dateInput: "",
      thresholdInput: "",
      timingInput: "unknown",
      actionError: null,
    };
  }
  if (event.type === "REMOVE_WATCHLIST") {
    const payload = parseJson(event.output);
    if (!payload || !payload.ok) {
      return { ...previousState, loading: false, actionError: (payload && payload.error) || "Could not remove ticker." };
    }
    return {
      ...previousState,
      loading: false,
      data: payload.data,
      output: JSON.stringify(payload.data),
      actionError: null,
    };
  }
  if (event.type === "ACTION_FAILED") {
    return { ...previousState, loading: false, actionError: String(event.error || "Action failed.") };
  }
  if (event.error) {
    return { ...previousState, error: event.error };
  }
  const data = parseJson(event.output);
  return { ...previousState, output: event.output, data: data || previousState.data, error: null };
};

export const className = `
  top: ${widgetTop};
  left: ${basePosition.left};
  right: auto;
  width: ${basePosition.width};
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased;
  button, input { font: inherit; }
  .panel {
    --panel-bg: linear-gradient(160deg, rgba(18, 22, 20, 0.94), rgba(31, 33, 29, 0.89));
    --text: #f4f6ef;
    --muted: #9ca39a;
    --soft: #c1c8bd;
    --faint: #798278;
    --panel-border: rgba(255,255,255,0.10);
    --divider: rgba(255,255,255,0.075);
    --field-bg: rgba(255,255,255,0.08);
    --chip-bg: rgba(255,255,255,0.055);
    --tooltip-bg: rgba(17,20,18,0.98);
    --shadow: 0 18px 46px rgba(0,0,0,0.34);
    --accent: #9fd7b2;
    --accent-bg: rgba(120,214,154,0.10);
    --live: #75d494;
    --live-bg: rgba(120,214,154,0.10);
    --warn: #e7b762;
    --warn-bg: rgba(231,183,98,0.12);
    --danger: #e78375;
    --danger-bg: rgba(231,131,117,0.12);
    --delta-up: #4fb979;
    --delta-down: #dd735c;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    width: 100%;
    max-height: ${widgetMaxHeight};
    overflow: hidden;
    color: var(--text);
    background: var(--panel-bg);
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    box-shadow: var(--shadow);
    padding: 14px 15px 11px;
    backdrop-filter: blur(22px) saturate(150%);
    -webkit-backdrop-filter: blur(22px) saturate(150%);
    transition: transform 140ms ease, width 140ms ease, max-height 140ms ease;
    will-change: transform, width;
  }
  .panel[data-theme="light"] {
    --panel-bg: linear-gradient(160deg, rgba(250,251,247,0.96), rgba(238,241,234,0.92));
    --text: #1c211e;
    --muted: #657066;
    --soft: #374039;
    --faint: #7b857b;
    --panel-border: rgba(34,42,36,0.13);
    --divider: rgba(34,42,36,0.095);
    --field-bg: rgba(34,42,36,0.055);
    --chip-bg: rgba(34,42,36,0.045);
    --tooltip-bg: rgba(250,251,247,0.98);
    --shadow: 0 16px 40px rgba(44,51,46,0.18);
    --accent: #236c43;
    --accent-bg: rgba(35,108,67,0.10);
    --live: #14733d;
    --live-bg: rgba(20,115,61,0.10);
    --warn: #9b6407;
    --warn-bg: rgba(155,100,7,0.12);
    --danger: #a53424;
    --danger-bg: rgba(165,52,36,0.11);
    --delta-up: #14733d;
    --delta-down: #a53424;
  }
  .panel[data-theme="midnight"] {
    --panel-bg: linear-gradient(160deg, rgba(9, 14, 24, 0.95), rgba(18, 25, 38, 0.91));
    --text: #f0f5ff;
    --muted: #9da8b9;
    --soft: #c7d1df;
    --faint: #737f91;
    --panel-border: rgba(170,190,220,0.14);
    --divider: rgba(170,190,220,0.09);
    --field-bg: rgba(255,255,255,0.075);
    --chip-bg: rgba(255,255,255,0.055);
    --tooltip-bg: rgba(11,16,26,0.98);
    --shadow: 0 18px 46px rgba(0,0,0,0.40);
    --accent: #9bc7ff;
    --accent-bg: rgba(112,159,220,0.13);
    --live: #73d89b;
    --live-bg: rgba(115,216,155,0.11);
    --warn: #f0bd63;
    --warn-bg: rgba(240,189,99,0.12);
    --danger: #ff927e;
    --danger-bg: rgba(255,146,126,0.12);
    --delta-up: #73d89b;
    --delta-down: #ff927e;
  }
  .panel[data-theme="mono"] {
    --panel-bg: linear-gradient(160deg, rgba(22,22,22,0.95), rgba(38,38,38,0.91));
    --text: #f3f3f0;
    --muted: #a7a7a1;
    --soft: #d0d0ca;
    --faint: #7c7c77;
    --panel-border: rgba(245,245,240,0.12);
    --divider: rgba(245,245,240,0.08);
    --field-bg: rgba(245,245,240,0.07);
    --chip-bg: rgba(245,245,240,0.06);
    --tooltip-bg: rgba(24,24,24,0.98);
    --shadow: 0 18px 46px rgba(0,0,0,0.36);
    --accent: #deded8;
    --accent-bg: rgba(222,222,216,0.09);
    --live: #e9f6ec;
    --live-bg: rgba(233,246,236,0.10);
    --warn: #d4c7a8;
    --warn-bg: rgba(212,199,168,0.12);
    --danger: #f0b8ae;
    --danger-bg: rgba(240,184,174,0.12);
    --delta-up: #f2f2ee;
    --delta-down: #d1d1ca;
  }
  .head { flex: 0 0 auto; display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }
  .title { color: var(--text); font-size: 12px; font-weight: 760; letter-spacing: 0; }
  .subtitle { font-size: 9.5px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .headRight { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; }
  .controls { display: flex; gap: 6px; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
  .meta { font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .market { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 760; }
  .market.open { color: var(--live); }
  .market.premarket, .market.afterhours { color: var(--warn); }
  .market.closed { color: var(--warn); }
  .editButton, .modeButton, .themeButton, .layoutButton {
    color: var(--accent);
    background: var(--accent-bg);
    border: 1px solid color-mix(in srgb, var(--accent) 34%, transparent);
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 9px;
    font-weight: 780;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .themeButton { min-width: 26px; padding-left: 7px; padding-right: 7px; }
  .layoutButton { min-width: 26px; padding-left: 7px; padding-right: 7px; }
  .layoutPanel {
    flex: 0 0 auto;
    display: grid;
    grid-template-columns: 1fr;
    gap: 9px;
    margin: -4px 0 11px;
    padding: 10px;
    border: 1px solid var(--divider);
    border-radius: 8px;
    background: color-mix(in srgb, var(--chip-bg) 78%, transparent);
  }
  .layoutHeader {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: var(--muted);
    font-size: 9px;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-weight: 740;
  }
  .layoutBody {
    display: grid;
    grid-template-columns: 104px minmax(0, 1fr);
    gap: 12px;
    align-items: center;
  }
  .layoutNudges {
    display: grid;
    grid-template-columns: repeat(3, 30px);
    grid-template-rows: repeat(3, 30px);
    gap: 4px;
    place-content: center;
  }
  .layoutNudges .up { grid-column: 2; }
  .layoutNudges .left { grid-column: 1; grid-row: 2; }
  .layoutNudges .right { grid-column: 3; grid-row: 2; }
  .layoutNudges .down { grid-column: 2; grid-row: 3; }
  .layoutSizer {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .layoutControl {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--soft);
    background: var(--field-bg);
    border: 1px solid var(--divider);
    border-radius: 7px;
    min-width: 30px;
    height: 30px;
    padding: 0 8px;
    font-size: 10px;
    font-weight: 760;
    cursor: pointer;
  }
  .layoutControl.wide { width: 100%; }
  .layoutControl.reset { grid-column: 1 / -1; }
  .removeButton {
    margin-top: 8px;
    color: var(--danger);
    background: var(--danger-bg);
    border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
    border-radius: 999px;
    padding: 3px 7px;
    font-size: 9px;
    font-weight: 760;
    cursor: pointer;
  }
  .editor {
    flex: 0 0 auto;
    border: 1px solid var(--divider);
    background: var(--chip-bg);
    border-radius: 8px;
    padding: 9px;
    margin-bottom: 10px;
  }
  .editorGrid { display: grid; grid-template-columns: 1fr; gap: 8px; align-items: stretch; }
  .fieldRow { display: grid; grid-template-columns: 0.72fr 0.9fr 0.78fr 0.8fr; gap: 7px; }
  .fieldGroup { display: grid; gap: 4px; min-width: 0; }
  .fieldLabel { display: flex; align-items: center; gap: 4px; font-size: 8.5px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; font-weight: 740; }
  .helpBubble {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 12px;
    height: 12px;
    color: var(--warn);
    border: 1px solid color-mix(in srgb, var(--warn) 38%, transparent);
    border-radius: 50%;
    font-size: 8px;
    font-weight: 850;
    letter-spacing: 0;
    cursor: help;
  }
  .helpBubble:focus { outline: none; box-shadow: 0 0 0 2px color-mix(in srgb, var(--warn) 18%, transparent); }
  .helpTip {
    position: absolute;
    z-index: 20;
    left: 50%;
    top: 16px;
    transform: translateX(-50%);
    width: 210px;
    color: var(--text);
    background: var(--tooltip-bg);
    border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
    border-radius: 7px;
    box-shadow: 0 10px 24px rgba(0,0,0,0.34);
    padding: 7px 8px;
    font-size: 10px;
    font-weight: 520;
    letter-spacing: 0;
    line-height: 1.35;
    text-transform: none;
    white-space: normal;
    opacity: 0;
    pointer-events: none;
    transition: opacity 120ms ease;
  }
  .helpBubble:hover .helpTip,
  .helpBubble:focus .helpTip {
    opacity: 1;
  }
  .editorActions { display: flex; gap: 7px; align-items: center; margin-top: 8px; }
  .fieldInput {
    min-width: 0;
    width: 100%;
    box-sizing: border-box;
    color: var(--text);
    background: var(--field-bg);
    border: 1px solid var(--divider);
    border-radius: 7px;
    padding: 7px 8px;
    font-size: 12px;
    outline: none;
  }
  .fieldInput::placeholder { color: var(--faint); }
  input[type="date"].fieldInput::-webkit-calendar-picker-indicator { filter: invert(1); opacity: 0.7; }
  input[type="number"].fieldInput, select.fieldInput { font-variant-numeric: tabular-nums; }
  .tickerInput { text-transform: uppercase; }
  .hint, .actionError { font-size: 10px; color: var(--muted); margin-top: 7px; line-height: 1.35; }
  .actionError { color: var(--danger); }
  .rows {
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    gap: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 5px;
    margin-right: -5px;
    scrollbar-width: thin;
    scrollbar-color: color-mix(in srgb, var(--accent) 36%, transparent) transparent;
  }
  .rows::-webkit-scrollbar { width: 6px; }
  .rows::-webkit-scrollbar-track { background: transparent; }
  .rows::-webkit-scrollbar-thumb { background: color-mix(in srgb, var(--accent) 34%, transparent); border-radius: 999px; }
  .row { display: grid; grid-template-columns: 64px minmax(0, 1fr) 78px; column-gap: 10px; padding: 11px 0; border-top: 1px solid var(--divider); }
  .panel.detailsMode .row { padding: 12px 0; }
  .row:first-child { border-top: 0; padding-top: 0; }
  .ticker { color: var(--text); font-size: 18px; line-height: 1; font-weight: 820; letter-spacing: 0; }
  .spotMini { font-size: 10px; color: var(--muted); margin-top: 6px; font-variant-numeric: tabular-nums; }
  .main { min-width: 0; }
  .event { display: flex; align-items: center; gap: 6px; min-width: 0; margin-bottom: 6px; }
  .eventName { font-size: 11px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pill { flex: 0 0 auto; font-size: 9px; color: var(--accent); background: var(--accent-bg); border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent); border-radius: 999px; padding: 2px 6px; text-transform: uppercase; letter-spacing: 0.04em; }
  .moveLine { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
  .move { font-size: 27px; font-weight: 820; letter-spacing: 0; line-height: 1; color: var(--live); font-variant-numeric: tabular-nums; }
  .moveLabel { font-size: 11px; color: var(--muted); font-weight: 560; }
  .panel.compactMode .moveLabel { display: none; }
  .confidenceBadge {
    color: var(--warn);
    background: var(--warn-bg);
    border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
    border-radius: 999px;
    padding: 2px 5px;
    font-size: 9px;
    font-weight: 780;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    line-height: 1.1;
  }
  .confidenceBadge.live { color: var(--live); border-color: color-mix(in srgb, var(--live) 35%, transparent); background: var(--live-bg); }
  .confidenceBadge.indicative, .confidenceBadge.prior_close, .confidenceBadge.cached { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 35%, transparent); background: var(--warn-bg); }
  .confidenceBadge.stale { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, transparent); background: var(--danger-bg); }
  .stateBadge {
    color: var(--danger);
    background: var(--danger-bg);
    border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
    border-radius: 999px;
    padding: 2px 5px;
    font-size: 9px;
    font-weight: 780;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    line-height: 1.1;
  }
  .flagCount {
    color: var(--warn);
    border: 1px solid color-mix(in srgb, var(--warn) 26%, transparent);
    border-radius: 999px;
    padding: 2px 5px;
    font-size: 9px;
    font-weight: 740;
    line-height: 1.1;
  }
  .row.eventMuted .move { color: var(--muted); }
  .delta { font-size: 11px; font-weight: 730; font-variant-numeric: tabular-nums; }
  .delta.up { color: var(--delta-up); }
  .delta.down { color: var(--delta-down); }
  .delta.flat, .delta.new { color: var(--muted); }
  .delta.cached, .delta.stale { color: var(--warn); }
  .detailsBlock { display: block; }
  .sideDetails { display: block; }
  .detail { font-size: 11px; color: var(--soft); line-height: 1.35; white-space: normal; overflow: visible; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
  .detail.compact { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .muted { color: var(--muted); }
  .odds { color: var(--warn); font-weight: 650; }
  .side { text-align: right; font-variant-numeric: tabular-nums; min-width: 78px; }
  .date { font-size: 12px; color: var(--text); font-weight: 650; }
  .expiry { font-size: 10px; color: var(--muted); margin-top: 4px; }
  .source { font-size: 9px; color: var(--faint); margin-top: 5px; white-space: normal; overflow: visible; overflow-wrap: anywhere; max-width: 96px; }
  .badge { display: inline-block; font-size: 9px; color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent); border-radius: 999px; padding: 2px 5px; margin-top: 6px; }
  .gap { display: inline-block; font-size: 9px; color: var(--muted); border: 1px solid var(--divider); border-radius: 999px; padding: 2px 5px; margin-top: 5px; }
  .gap.clean { color: var(--live); border-color: color-mix(in srgb, var(--live) 26%, transparent); }
  .gap.timing, .gap.padded { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 35%, transparent); }
  .gap.wide, .gap.invalid { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 40%, transparent); background: var(--danger-bg); }
  .warnings { margin-top: 3px; display: flex; gap: 4px; flex-wrap: wrap; overflow: visible; }
  .warn { font-size: 9px; color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 28%, transparent); background: var(--warn-bg); border-radius: 999px; padding: 2px 5px; white-space: normal; max-width: 100%; overflow: visible; overflow-wrap: anywhere; line-height: 1.25; }
  .warn.low { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 34%, transparent); background: var(--danger-bg); }
  .error { color: var(--danger); font-size: 11px; line-height: 1.35; }
  .empty { color: var(--muted); font-size: 12px; padding: 10px 0 2px; }
  .foot { flex: 0 0 auto; display: flex; justify-content: space-between; gap: 12px; color: var(--faint); font-size: 9.5px; border-top: 1px solid var(--divider); padding-top: 8px; margin-top: 9px; }
`;

const shellQuote = value => `'${String(value).replace(/'/g, `'\\''`)}'`;
const fmtMoney = value => Number.isFinite(+value) ? "$" + (+value).toFixed(2) : "n/a";
const fmtPct = value => Number.isFinite(+value) ? ((+value) * 100).toFixed(1) + "%" : "n/a";
const fmtPp = value => {
  if (!Number.isFinite(+value)) return "new";
  const pp = (+value) * 100;
  if (Math.abs(pp) < 0.05) return "flat";
  return `${pp > 0 ? "↗" : "↘"}${Math.abs(pp).toFixed(1)}pp`;
};
const deltaClass = (value, row = {}) => {
  if (row.stale) return "stale";
  if (row.not_rechecked) return "cached";
  if (!Number.isFinite(+value)) return "new";
  if (Math.abs((+value) * 100) < 0.05) return "flat";
  return +value > 0 ? "up" : "down";
};
const deltaText = (value, row = {}) => {
  if (row.stale) return "last good";
  if (row.not_rechecked) return "cached";
  if (row.delta && row.delta.label) return row.delta.label;
  return fmtPp(value);
};
const fmtDate = value => {
  if (!value) return "n/a";
  const parts = String(value).split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : value;
};
const fmtTime = iso => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
};
const fmtAge = seconds => {
  const value = Number(seconds);
  if (!Number.isFinite(value)) return "";
  if (value < 60) return `${Math.round(value)}s old`;
  const minutes = Math.round(value / 60);
  if (minutes < 60) return `${minutes}m old`;
  return `${(minutes / 60).toFixed(1)}h old`;
};
const spotText = row => {
  const base = fmtMoney(row.spot);
  if (row.spot_is_extended && row.spot_source) return `${base} · ${row.spot_source}`;
  return base;
};
const ivText = row => {
  if (!row.iv_check_available) {
    const reason = row.atm_iv_unavailable_reason ? ` (${row.atm_iv_unavailable_reason})` : "";
    return `ATM IV n/a${reason}`;
  }
  return `ATM IV ${fmtPct(row.atm_iv_pct || row.atm_iv)}`;
};
const ivMoveText = row => {
  if (!Number.isFinite(+row.iv_move_pct)) return null;
  return `IV move ±${fmtPct(row.iv_move_pct)}`;
};
const rangeText = row => {
  if (!Number.isFinite(+row.adj_low) || !Number.isFinite(+row.adj_high)) return "range n/a";
  return `${fmtMoney(row.adj_low)}–${fmtMoney(row.adj_high)}`;
};
const gapText = row => {
  let text = "gap n/a";
  if (row.event_gap_warning && String(row.event_gap_warning).includes("timing unknown")) {
    text = `${row.event_gap_label || "same day"} · timing unknown`;
  } else if (row.event_gap_label) {
    text = `${row.event_gap_label} ${row.event_gap_severity || ""}`.trim();
  } else if (Number.isFinite(+row.event_gap_days)) {
    text = `+${row.event_gap_days}d`;
  }
  return row.event_passed ? `${text} · event passed` : text;
};
const rowWarnings = row => {
  const warnings = [];
  if (row.event_passed) warnings.push({ text: "event passed", level: "low" });
  if (row.event_gap_warning && !String(row.event_gap_warning).includes("timing unknown")) {
    warnings.push({ text: row.event_gap_warning, level: ["wide", "invalid"].includes(row.event_gap_severity) ? "low" : "" });
  }
  if (row.prob_warning) warnings.push({ text: row.prob_warning, level: "low" });
  if (row.prob_unreliable_reason) warnings.push({ text: row.prob_unreliable_reason, level: "low" });
  (Array.isArray(row.quote_warnings) ? row.quote_warnings : []).forEach(text => warnings.push({ text, level: "low" }));
  return warnings.slice(0, 4);
};
const compactBasisNote = row => {
  const pieces = [];
  const spot = String(row.spot_source || "").replace("stock ", "").trim();
  if (row.spot_is_extended && spot) pieces.push(spot);
  const basis = row.quote_basis;
  if (basis === "live_mid") pieces.push("live mids");
  else if (basis === "prior_close_mid") pieces.push("prior close");
  else if (basis === "last_trade") pieces.push("last trade");
  else if (basis === "closed_mid") pieces.push("closed mids");
  else pieces.push("quote basis n/a");
  if (row.option_quote_age) pieces.push(String(row.option_quote_age).replace(" old", ""));
  return pieces.filter(Boolean).join(" · ");
};
const secondaryDetail = row => {
  const parts = [
    `raw ±${fmtPct(row.em_raw)} → adj ±${fmtPct(row.em_adj)}`,
    `straddle ${fmtMoney(row.straddle)}`,
    ivText(row),
    ivMoveText(row),
    compactBasisNote(row),
    row.skew_label,
    row.cache_status === "hit" ? "not rechecked" : "fresh",
  ];
  return parts.filter(Boolean).join(" · ");
};
const tertiaryDetail = row => {
  if (row.threshold !== null && row.threshold !== undefined) {
    if (row.prob_reliable) {
      return `P below ${fmtMoney(row.threshold)} ${fmtPct(row.prob_below)} · above ${fmtPct(row.prob_above)}`;
    }
    return `Threshold ${fmtMoney(row.threshold)} · odds unreliable`;
  }
  return `Range ${rangeText(row)}`;
};
const stateLabel = row => {
  if (row.event_gap_severity === "invalid") return "expiry before event";
  if (row.event_passed) return "event passed";
  return null;
};
const basisClass = row => String(row.move_status || row.quote_basis || "stale").replace(/[^a-z0-9_ -]/gi, "").replace(/\s+/g, "_");
const basisLabel = row => row.move_status_label || (row.quote_basis === "live_mid" ? "Live mid" : "Indicative");
const sideMeta = row => {
  const pieces = [`exp ${fmtDate(row.expiry)}`, row.days !== null && row.days !== undefined ? `${row.days}d` : null];
  return pieces.filter(Boolean).join(" · ");
};
const footerText = (summary = {}, market = {}) => {
  const statuses = summary.move_status || {};
  const parts = [
    ["live", statuses.live || 0],
    ["indicative", statuses.indicative || 0],
    ["prior", statuses.prior_close || 0],
    ["stale", statuses.stale || 0],
    ["cached", statuses.cached || 0],
  ]
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${count} ${label}`);
  return [market.label || "session", ...parts].join(" · ");
};

const themeLabel = theme => ({
  graphite: "Graphite",
  light: "Light",
  midnight: "Midnight",
  mono: "Mono",
})[normalizeTheme(theme)];

const nextTheme = theme => {
  const current = normalizeTheme(theme);
  const index = THEMES.indexOf(current);
  return THEMES[(index + 1) % THEMES.length];
};

const setTheme = (theme, dispatch) => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  const safeTheme = normalizeTheme(theme);
  dispatch({ type: "THEME_LOCAL", theme: safeTheme });
  run(`${ACTION} theme --theme ${shellQuote(safeTheme)}`)
    .then(output => dispatch({ type: "THEME_SAVED", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const setCompact = (compact, dispatch) => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  const value = cleanCompact(compact);
  dispatch({ type: "COMPACT_LOCAL", compact: value });
  run(`${ACTION} compact --compact ${shellQuote(value ? "true" : "false")}`)
    .then(output => dispatch({ type: "COMPACT_SAVED", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const setLayout = (positionValue, dispatch) => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  const safePosition = normalizePosition(positionValue);
  dispatch({ type: "LAYOUT_LOCAL", position: safePosition });
  const heightArg = safePosition.max_height ? ` --height ${pxNumber(safePosition.max_height, 640)}` : "";
  run(
    `${ACTION} layout --top ${pxNumber(safePosition.top, 185)} ` +
    `--left ${pxNumber(safePosition.left, 28)} --width ${pxNumber(safePosition.width, 420)}${heightArg}`
  )
    .then(output => dispatch({ type: "LAYOUT_SAVED", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const adjustLayout = (current, patch, dispatch) => {
  const safe = normalizePosition(current);
  const currentHeight = safe.max_height ? pxNumber(safe.max_height, 640) : 640;
  setLayout(
    {
      top: pxNumber(safe.top, 185) + (patch.dy || 0),
      left: pxNumber(safe.left, 28) + (patch.dx || 0),
      width: pxNumber(safe.width, 420) + (patch.dw || 0),
      max_height: patch.dh ? currentHeight + patch.dh : safe.max_height,
    },
    dispatch
  );
};

const resetLayout = dispatch => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  dispatch({ type: "LAYOUT_LOCAL", position: DEFAULT_POSITION });
  run(`${ACTION} layout --reset`)
    .then(output => dispatch({ type: "LAYOUT_SAVED", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const panelLayoutStyle = positionValue => {
  const safe = normalizePosition(positionValue);
  const dx = pxNumber(safe.left, 28) - pxNumber(basePosition.left, 28);
  const dy = pxNumber(safe.top, 185) - pxNumber(basePosition.top, 185);
  return {
    width: safe.width,
    maxHeight: safe.max_height || display.max_height || `calc(100vh - ${safe.top} - 16px)`,
    transform: `translate(${Math.round(dx)}px, ${Math.round(dy)}px)`,
  };
};

const LayoutControls = ({ position, dispatch }) => {
  const width = pxNumber(position.width, 420);
  const heightLabel = position.max_height ? `${Math.round(pxNumber(position.max_height, 640))}px tall` : "auto height";
  return (
    <div className="layoutPanel">
      <div className="layoutHeader">
        <span>Layout</span>
        <span>{Math.round(width)}px wide · {heightLabel}</span>
      </div>
      <div className="layoutBody">
        <div className="layoutNudges" aria-label="Move widget">
          <button className="layoutControl up" title="Move up" onClick={() => adjustLayout(position, { dy: -20 }, dispatch)}>↑</button>
          <button className="layoutControl left" title="Move left" onClick={() => adjustLayout(position, { dx: -20 }, dispatch)}>←</button>
          <button className="layoutControl right" title="Move right" onClick={() => adjustLayout(position, { dx: 20 }, dispatch)}>→</button>
          <button className="layoutControl down" title="Move down" onClick={() => adjustLayout(position, { dy: 20 }, dispatch)}>↓</button>
        </div>
        <div className="layoutSizer">
          <button className="layoutControl wide" title="Shrink widget width" onClick={() => adjustLayout(position, { dw: -40 }, dispatch)}>Narrow</button>
          <button className="layoutControl wide" title="Widen widget width" onClick={() => adjustLayout(position, { dw: 40 }, dispatch)}>Wider</button>
          <button className="layoutControl wide" title="Shrink widget height" onClick={() => adjustLayout(position, { dh: -60 }, dispatch)}>Shorter</button>
          <button className="layoutControl wide" title="Increase widget height" onClick={() => adjustLayout(position, { dh: 60 }, dispatch)}>Taller</button>
          <button className="layoutControl wide reset" title="Reset widget layout" onClick={() => resetLayout(dispatch)}>Reset</button>
        </div>
      </div>
    </div>
  );
};

const setTickerEvent = (ticker, event, dispatch, threshold, timing = "unknown") => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  dispatch({ type: "ACTION_LOADING" });
  const thresholdArg = threshold !== undefined && threshold !== null && String(threshold).trim() !== ""
    ? ` --threshold ${shellQuote(threshold)}`
    : "";
  run(
    `${ACTION} set --ticker ${shellQuote(ticker)} --event ${shellQuote(event.date)} ` +
    `--label ${shellQuote(event.label || "Catalyst")} --source ${shellQuote(event.source || "manual")} ` +
    `--confidence ${shellQuote(event.confidence || "user")} --timing ${shellQuote(timing || "unknown")}${thresholdArg}`
  )
    .then(output => dispatch({ type: "SET_WATCHLIST", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const removeTicker = (ticker, dispatch) => {
  if (!ACTION) {
    dispatch({ type: "ACTION_FAILED", error: "Setup required. Run bin/setup.sh from the widget folder." });
    return;
  }
  dispatch({ type: "ACTION_LOADING" });
  run(`${ACTION} remove --ticker ${shellQuote(ticker)}`)
    .then(output => dispatch({ type: "REMOVE_WATCHLIST", output }))
    .catch(error => dispatch({ type: "ACTION_FAILED", error }));
};

const addManualEvent = (state, dispatch) => {
  const ticker = String(state.tickerInput || "").trim().toUpperCase();
  const label = String(state.eventInput || "").trim();
  const date = String(state.dateInput || "").trim();
  const threshold = String(state.thresholdInput || "").trim();
  const timing = String(state.timingInput || "unknown").trim();
  if (!ticker || !label || !date) {
    dispatch({ type: "ACTION_FAILED", error: "Ticker, event, and reaction date are required." });
    return;
  }
  setTickerEvent(ticker, { date, label, source: "manual", confidence: "user" }, dispatch, threshold, timing);
};

const Editor = ({ state, dispatch }) => {
  const ticker = state.tickerInput || "";
  return (
    <form className="editor" onSubmit={event => { event.preventDefault(); addManualEvent(state, dispatch); }}>
      <div className="editorGrid">
        <div className="fieldRow">
          <label className="fieldGroup">
            <span className="fieldLabel">Ticker</span>
            <input
              className="fieldInput tickerInput"
              placeholder="LMT"
              value={ticker}
              onChange={event => dispatch({ type: "TICKER_INPUT", value: event.target.value })}
            />
          </label>
          <label className="fieldGroup">
            <span className="fieldLabel">Timing</span>
            <select
              className="fieldInput"
              value={state.timingInput || "unknown"}
              onChange={event => dispatch({ type: "TIMING_INPUT", value: event.target.value })}
            >
              <option value="unknown">Unknown</option>
              <option value="bmo">BMO</option>
              <option value="intraday">Intraday</option>
              <option value="amc">AMC</option>
            </select>
          </label>
          <label className="fieldGroup">
            <span className="fieldLabel">Reaction date</span>
            <input
              className="fieldInput"
              type="date"
              value={state.dateInput || ""}
              onChange={event => dispatch({ type: "DATE_INPUT", value: event.target.value })}
            />
          </label>
          <label className="fieldGroup">
            <span className="fieldLabel">
              Threshold
              <span
                className="helpBubble"
                tabIndex="0"
                aria-label="Threshold help"
              >
                ?
                <span className="helpTip">
                  Optional price level for risk-neutral odds. Enter a stock price to show the option-implied chance of finishing below or above it at expiry.
                </span>
              </span>
            </span>
            <input
              className="fieldInput"
              type="number"
              step="0.01"
              placeholder="optional"
              value={state.thresholdInput || ""}
              onChange={event => dispatch({ type: "THRESHOLD_INPUT", value: event.target.value })}
            />
          </label>
        </div>
        <label className="fieldGroup">
          <span className="fieldLabel">Event</span>
          <input
            className="fieldInput"
            placeholder="Type the catalyst, e.g. Pentagon contract award"
            value={state.eventInput || ""}
            onChange={event => dispatch({ type: "EVENT_INPUT", value: event.target.value })}
          />
        </label>
      </div>
      <div className="editorActions">
        <button className="editButton" type="submit">
          {state.loading ? "Adding" : "Add event"}
        </button>
      </div>
      {state.actionError ? <div className="actionError">{state.actionError}</div> : null}
      <div className="hint">Type the ticker, catalyst, and reaction/deadline date. The widget brackets that date to the first listed options expiry on or after it.</div>
    </form>
  );
};

const Row = ({ row, dispatch, detailsMode }) => {
  if (!row.ok) {
    return (
      <div className="row">
        <div>
          <div className="ticker">{row.ticker}</div>
          {detailsMode ? <button className="removeButton" onClick={() => removeTicker(row.ticker, dispatch)}>Remove</button> : null}
        </div>
        <div className="main"><div className="error">{row.error || "Could not load this ticker"}</div></div>
        <div className="side"><div className="date">{fmtDate(row.event)}</div></div>
      </div>
    );
  }
  const delta = row.delta || {};
  const moveDelta = delta.em_adj;
  const eventSource = [row.event_source, row.event_confidence].filter(Boolean).join(" · ");
  const warnings = rowWarnings(row);
  const currentStateLabel = stateLabel(row);
  const trustLabel = currentStateLabel || (row.stale ? "last good" : null);
  return (
    <div className={`row ${currentStateLabel ? "eventMuted" : ""}`}>
      <div>
        <div className="ticker">{row.ticker}</div>
        <div className="spotMini">{spotText(row)}</div>
        {row.stale ? <span className="badge">stale</span> : null}
        {detailsMode ? <button className="removeButton" onClick={() => removeTicker(row.ticker, dispatch)}>Remove</button> : null}
      </div>
      <div className="main">
        {detailsMode ? (
          <div className="event">
            <span className="pill">{row.event_confidence || "event"}</span>
            <span className="eventName">{row.label || "Catalyst"}</span>
          </div>
        ) : null}
        <div className="moveLine">
          <span className="move">±{fmtPct(row.em_adj)}</span>
          <span className="moveLabel">adjusted (×0.85)</span>
          <span className={`confidenceBadge ${basisClass(row)}`}>{basisLabel(row)}</span>
          {trustLabel ? <span className="stateBadge">{trustLabel}</span> : null}
          <span className={`delta ${deltaClass(moveDelta, row)}`}>{deltaText(moveDelta, row)}</span>
          {!detailsMode && warnings.length ? <span className="flagCount">{warnings.length} flag{warnings.length === 1 ? "" : "s"}</span> : null}
        </div>
        {detailsMode ? (
          <div className="detailsBlock">
            <div className="detail muted compact">{secondaryDetail(row)}</div>
            <div className={`detail ${row.threshold !== null && row.threshold !== undefined && row.prob_reliable ? "odds" : "muted"}`}>{tertiaryDetail(row)}</div>
            {warnings.length ? (
              <div className="warnings">
                {warnings.map((warning, index) => <span className={`warn ${warning.level}`} key={`${warning.text}-${index}`}>{warning.text}</span>)}
              </div>
            ) : null}
            {row.error ? <div className="detail error">{row.error}</div> : null}
          </div>
        ) : null}
      </div>
      <div className="side">
        <div className="date">{fmtDate(row.event)}</div>
        <div className="expiry">{sideMeta(row)}</div>
        {detailsMode ? (
          <div className="sideDetails">
            <div className={`gap ${row.event_gap_severity || ""}`}>{gapText(row)}</div>
            <div className="source">{eventSource}</div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export const render = (props, dispatch) => {
  const data = props.data || parseJson(props.output) || {};
  const rows = Array.isArray(data.rows) ? data.rows : [];
  const summary = data.summary || {};
  const market = data.market_status || {};
  const dataDisplay = data.display || {};
  const theme = normalizeTheme(props.themeOverride || dataDisplay.theme || display.theme);
  const compact = props.compactOverride !== null && props.compactOverride !== undefined
    ? props.compactOverride
    : cleanCompact(dataDisplay.compact !== undefined ? dataDisplay.compact : display.compact);
  const detailsMode = !compact;
  const activePosition = normalizePosition(props.positionOverride || dataDisplay.position || display.position || position);
  const cacheText = data.cache_status === "hit" ? `cached ${fmtAge(data.cache_age_seconds)}` : (data.cache_status || "refresh");
  return (
    <div className={`panel ${compact ? "compactMode" : "detailsMode"}`} data-theme={theme} style={panelLayoutStyle(activePosition)}>
      <div className="head">
        <div>
          <div className="title">{(data.display && data.display.title) || display.title || "Options Swing Tracker"}</div>
          <div className="subtitle">catalyst swing monitor</div>
        </div>
        <div className="headRight">
          <div className="controls">
            <button className="themeButton" title={`Theme: ${themeLabel(theme)}`} onClick={() => setTheme(nextTheme(theme), dispatch)}>
              ◐
            </button>
            <button className="layoutButton" title="Move or resize widget" onClick={() => dispatch({ type: "TOGGLE_LAYOUT" })}>
              ↔
            </button>
            <button className="modeButton" onClick={() => setCompact(!compact, dispatch)}>
              {compact ? "Details" : "Minimal"}
            </button>
            <button className="editButton" onClick={() => dispatch({ type: "TOGGLE_EDITOR" })}>
              {props.editorOpen ? "Close editor" : "Edit tickers"}
            </button>
          </div>
          <div className={`market ${market.state || ""}`}>{market.label || "market status n/a"}</div>
          <div className="meta">fetched {fmtTime(data.generated_at)} · served {fmtTime(data.served_at || data.generated_at)}</div>
          <div className="meta">{cacheText}</div>
        </div>
      </div>
      {props.layoutOpen ? <LayoutControls position={activePosition} dispatch={dispatch} /> : null}
      {props.editorOpen ? <Editor state={props} dispatch={dispatch} /> : null}
      {data.error ? <div className="error">{data.error}</div> : null}
      <div className="rows">
        {rows.length ? rows.map(row => <Row row={row} dispatch={dispatch} detailsMode={detailsMode} key={row.key || row.ticker} />) : <div className="empty">No enabled watchlist rows.</div>}
      </div>
      <div className="foot">
        <span>{footerText(summary, market)}</span>
        <span>{summary.ok || 0}/{summary.total || rows.length} ok</span>
      </div>
    </div>
  );
};
