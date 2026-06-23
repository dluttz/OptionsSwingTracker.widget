#!/usr/bin/env python3
"""Data command for the Options Swing Tracker Übersicht widget."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import event_move_core


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
CACHE_DIR = ROOT / "cache"
LOG_DIR = ROOT / "logs"
DATA_CACHE = CACHE_DIR / "data_cache.json"
LAST_GOOD = CACHE_DIR / "last_good.json"
REGULAR_MIDS = CACHE_DIR / "regular_option_mids.json"
LOG_FILE = LOG_DIR / "widget.log"
UBERSICHT_LINK = Path.home() / "Library/Application Support/Übersicht/widgets/OptionsSwingTracker.widget"
VALID_TIMINGS = {"unknown", "bmo", "intraday", "amc"}
DATA_SCHEMA_VERSION = 2
VALID_THEMES = {"graphite", "light", "midnight", "mono"}
DEFAULT_THEME = "graphite"
DEFAULT_POSITION = {"top": "185px", "left": "28px", "width": "420px"}
MIN_WIDGET_WIDTH = 300
MAX_WIDGET_WIDTH = 760
MIN_WIDGET_HEIGHT = 340
MAX_WIDGET_HEIGHT = 1100


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = iso_now()
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as exc:
        log(f"Could not read {path.name}: {exc}")
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def load_config() -> dict[str, Any]:
    cfg = read_json(CONFIG_PATH, None)
    if not isinstance(cfg, dict):
        raise RuntimeError(f"Missing or invalid config: {CONFIG_PATH}")
    return cfg


def load_config_from_path(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"missing config: {path}"
    except Exception as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(cfg, dict):
        return None, "config root must be an object"
    return cfg, None


def cache_age_seconds(path: Path) -> float | None:
    try:
        return utc_now().timestamp() - path.stat().st_mtime
    except FileNotFoundError:
        return None


def is_fresh(path: Path, ttl: int) -> bool:
    age = cache_age_seconds(path)
    return age is not None and age >= 0 and age < ttl


def config_cache_key(config: dict[str, Any]) -> str:
    relevant = {
        "data_schema_version": DATA_SCHEMA_VERSION,
        "defaults": config.get("defaults") or {},
        "watchlist": [
            item
            for item in config.get("watchlist", [])
            if isinstance(item, dict) and item.get("enabled") is not False
        ],
    }
    payload = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clean_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "compact", "minimal"}:
            return True
        if text in {"0", "false", "no", "n", "details", "detail"}:
            return False
    if value is None:
        return default
    return bool(value)


def normalize_theme(value: Any) -> str:
    theme = str(value or DEFAULT_THEME).strip().lower()
    return theme if theme in VALID_THEMES else DEFAULT_THEME


def css_px_number(value: Any, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().lower()
        if text.endswith("px"):
            text = text[:-2].strip()
        try:
            number = float(text)
        except ValueError:
            number = float(default)
    else:
        number = float(default)
    if math.isnan(number) or math.isinf(number):
        return float(default)
    return number


def clamp_number(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def px_string(value: Any, default: float, *, minimum: float, maximum: float) -> str:
    number = clamp_number(css_px_number(value, default), minimum, maximum)
    return f"{int(round(number))}px"


def normalize_display_position(display: dict[str, Any] | Any) -> dict[str, Any]:
    raw = display if isinstance(display, dict) else {}
    position = raw.get("position") if isinstance(raw.get("position"), dict) else raw
    position = position if isinstance(position, dict) else {}
    top_default = css_px_number(DEFAULT_POSITION["top"], 185)
    left_default = css_px_number(DEFAULT_POSITION["left"], 28)
    width_default = css_px_number(DEFAULT_POSITION["width"], 420)
    normalized = {
        "top": px_string(position.get("top"), top_default, minimum=0, maximum=1400),
        "left": px_string(position.get("left"), left_default, minimum=0, maximum=3000),
        "width": px_string(position.get("width"), width_default, minimum=MIN_WIDGET_WIDTH, maximum=MAX_WIDGET_WIDTH),
    }
    max_height = position.get("max_height") or raw.get("max_height")
    if max_height not in (None, ""):
        normalized["max_height"] = px_string(max_height, 640, minimum=MIN_WIDGET_HEIGHT, maximum=MAX_WIDGET_HEIGHT)
    return normalized


def display_settings(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("display") if isinstance(config.get("display"), dict) else {}
    return {
        "title": raw.get("title", "Options Swing Tracker"),
        "theme": normalize_theme(raw.get("theme")),
        "compact": clean_bool(raw.get("compact"), True),
        "position": normalize_display_position(raw),
    }


def clean_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_event_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return text


def threshold_key(value: Any) -> str:
    number = clean_float(value)
    if number is None:
        return ""
    return f"{number:.10g}"


def watchlist_duplicate_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("ticker", "")).strip().upper(),
            str(item.get("event", "")).strip(),
            threshold_key(item.get("threshold")),
        ]
    )


def validation_row_key(index: int, item: dict[str, Any]) -> str:
    ticker = str(item.get("ticker", "")).strip().upper() or "UNKNOWN"
    event = str(item.get("event", "")).strip()
    return f"invalid|{index}|{ticker}|{event}|{threshold_key(item.get('threshold'))}"


def validate_watchlist_item(raw: Any, index: int) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw, dict):
        return {"ticker": "UNKNOWN", "enabled": True}, ["entry must be an object"]

    item = dict(raw)
    if item.get("enabled") is False:
        return item, []

    issues: list[str] = []
    ticker = item.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        issues.append("ticker must be a non-empty string")
    else:
        item["ticker"] = ticker.strip().upper()

    event = parse_event_date(item.get("event"))
    if event is None:
        issues.append("event must be YYYY-MM-DD")
    else:
        item["event"] = event

    threshold = item.get("threshold")
    if threshold == "":
        threshold = None
    if threshold is None:
        item["threshold"] = None
    else:
        threshold_f = clean_float(threshold)
        if threshold_f is None:
            issues.append("threshold must be numeric or null")
        else:
            item["threshold"] = threshold_f

    timing = item.get("timing") or "unknown"
    if not isinstance(timing, str):
        issues.append("timing must be one of unknown, bmo, intraday, amc")
    else:
        timing = timing.strip().lower() or "unknown"
        if timing not in VALID_TIMINGS:
            issues.append("timing must be one of unknown, bmo, intraday, amc")
        else:
            item["timing"] = timing

    return item, issues


def prepare_watchlist_entries(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    watchlist = config.get("watchlist", [])
    if watchlist is None:
        watchlist = []
    if not isinstance(watchlist, list):
        item = {"ticker": "UNKNOWN", "enabled": True}
        message = "invalid watchlist entry: watchlist must be a list"
        return [{"kind": "error", "row": error_row(item, key="invalid|watchlist", error=message)}], [message]

    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(watchlist):
        if isinstance(raw, dict) and raw.get("enabled") is False:
            continue
        item, item_issues = validate_watchlist_item(raw, index)
        if item_issues:
            message = f"invalid watchlist entry: {', '.join(item_issues)}"
            entries.append(
                {
                    "kind": "error",
                    "row": error_row(item, key=validation_row_key(index, item), error=message),
                }
            )
            issues.append(f"row {index + 1}: {message}")
            continue

        duplicate_key = watchlist_duplicate_key(item)
        if duplicate_key in seen:
            message = f"invalid watchlist entry: duplicate watchlist key already used by row {seen[duplicate_key] + 1}"
            entries.append(
                {
                    "kind": "error",
                    "row": error_row(item, key=validation_row_key(index, item), error=message),
                }
            )
            issues.append(f"row {index + 1}: {message}")
            continue

        seen[duplicate_key] = index
        entries.append({"kind": "fetch", "item": item})
    return entries, issues


def row_key(item: dict[str, Any]) -> str:
    threshold = item.get("threshold")
    threshold_s = "" if threshold is None else str(threshold)
    return "|".join(
        [
            str(item.get("ticker", "")).upper(),
            str(item.get("event", "")),
            str(item.get("timing", "unknown")),
            threshold_s,
            str(item.get("skew_pct", "")),
        ]
    )


def skew_label(skew: float | None) -> str:
    if skew is None:
        return "skew n/a"
    if skew > 0.02:
        return "downside skew"
    if skew < -0.02:
        return "upside skew"
    return "balanced"


def pct_delta(now: float | None, before: float | None) -> float | None:
    if now is None or before is None:
        return None
    return now - before


def quote_basis_label(row: dict[str, Any]) -> str:
    status = row.get("move_status")
    basis = row.get("quote_basis")
    if row.get("cache_status") == "hit" or row.get("not_rechecked"):
        return "Cached"
    if row.get("stale"):
        return "Stale"
    if status == "stale":
        return "Stale"
    if status == "live" or basis == "live_mid":
        return "Live mid"
    if status == "prior_close" or basis == "prior_close_mid":
        return "Prior close"
    if status == "indicative" or basis == "last_trade":
        return "Indicative"
    return "Low confidence"


def compute_deltas(row: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "em_adj": None,
        "em_raw": None,
        "spot": None,
        "prob_below": None,
        "basis_match": False,
        "label": "no prior clean read",
    }
    if not isinstance(previous, dict):
        return empty
    if row.get("cache_status") == "hit" or row.get("not_rechecked"):
        copy = dict(empty)
        copy["label"] = "cached"
        return copy
    if row.get("quote_basis") != previous.get("quote_basis"):
        return empty
    if row.get("move_status") != previous.get("move_status"):
        return empty
    return {
        "em_adj": pct_delta(row.get("em_adj"), previous.get("em_adj")),
        "em_raw": pct_delta(row.get("em_raw"), previous.get("em_raw")),
        "spot": pct_delta(row.get("spot"), previous.get("spot")),
        "prob_below": pct_delta(row.get("prob_below"), previous.get("prob_below")),
        "basis_match": True,
        "label": None,
    }


def has_live_mid(row: dict[str, Any]) -> bool:
    return row.get("quote_basis") == "live_mid" and row.get("move_status") == "live"


def apply_prior_mid_fallback(row: dict[str, Any], previous: dict[str, Any] | None) -> None:
    if row.get("quote_basis") == "prior_close_mid":
        return
    if not isinstance(previous, dict) or has_live_mid(row) or not has_live_mid(previous):
        return
    if row.get("expiry") != previous.get("expiry"):
        return
    call = clean_float(previous.get("atm_call"))
    put = clean_float(previous.get("atm_put"))
    spot = clean_float(row.get("spot"))
    if call is None or put is None or spot is None or spot <= 0:
        return
    straddle = call + put
    em_raw = straddle / spot
    em_adj = 0.85 * straddle / spot
    row["atm_call"] = call
    row["atm_put"] = put
    row["straddle"] = straddle
    row["em_raw"] = em_raw
    row["em_adj"] = em_adj
    row["em_raw_dollars"] = spot * em_raw
    row["em_adj_dollars"] = spot * em_adj
    row["raw_low"] = spot * (1 - em_raw)
    row["raw_high"] = spot * (1 + em_raw)
    row["adj_low"] = spot * (1 - em_adj)
    row["adj_high"] = spot * (1 + em_adj)
    row["quote_basis"] = "prior_close_mid"
    row["move_status"] = "prior_close"
    row["move_status_label"] = "Prior close"
    row["basis_note"] = "stock live/extended · options prior live mid"
    row["option_quote_age"] = previous.get("option_quote_age")
    warnings = list(row.get("quote_warnings") or [])
    warnings.insert(0, "using last good regular-hours option mids")
    row["quote_warnings"] = warnings


def invalidate_atm_iv(row: dict[str, Any], reason: str) -> None:
    row["atm_iv"] = None
    row["atm_iv_pct"] = None
    row["atm_iv_valid"] = False
    row["iv_check_available"] = False
    row["em_iv"] = None
    row["iv_move_pct"] = None
    row["em_iv_pct"] = None
    row["atm_iv_unavailable_reason"] = reason


def mark_duplicate_atm_ivs(rows: list[dict[str, Any]]) -> None:
    buckets: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("ok") or not row.get("atm_iv_valid"):
            continue
        atm_iv = clean_float(row.get("atm_iv"))
        if atm_iv is None:
            continue
        buckets.setdefault(round(atm_iv, 6), []).append(row)
    for matches in buckets.values():
        tickers = {row.get("ticker") for row in matches}
        if len(tickers) > 1:
            for row in matches:
                invalidate_atm_iv(row, "chain placeholder")


def option_mid_cache_key(ticker: str, expiry: Any, strike: Any, side: str) -> str | None:
    strike_f = clean_float(strike)
    if not ticker or not expiry or strike_f is None:
        return None
    return "|".join([ticker.upper(), str(expiry), f"{strike_f:.4f}", side])


def current_leg_mid(detail: Any) -> float | None:
    if not isinstance(detail, dict) or detail.get("source") != "mid":
        return None
    mid = clean_float(detail.get("mid"))
    return mid if mid is not None and mid > 0 else None


def store_regular_session_mids(result: dict[str, Any], mid_cache: dict[str, Any], fetched_at: str) -> bool:
    quote_quality = result.get("quote_quality") if isinstance(result.get("quote_quality"), dict) else {}
    legs = quote_quality.get("legs") if isinstance(quote_quality.get("legs"), dict) else {}
    ticker = str(result.get("ticker") or "").upper()
    expiry = result.get("expiry")
    strike = result.get("atm_strike")
    changed = False
    for side in ("call", "put"):
        key = option_mid_cache_key(ticker, expiry, strike, side)
        mid = current_leg_mid(legs.get(side))
        if key is None or mid is None:
            continue
        mid_cache[key] = {
            "ticker": ticker,
            "expiry": expiry,
            "strike": clean_float(strike),
            "side": side,
            "mid": mid,
            "stored_at": fetched_at,
        }
        changed = True
    return changed


def apply_regular_mid_cache_to_result(result: dict[str, Any], mid_cache: dict[str, Any]) -> bool:
    if result.get("quote_basis") == "live_mid":
        return False
    ticker = str(result.get("ticker") or "").upper()
    expiry = result.get("expiry")
    strike = result.get("atm_strike")
    call_key = option_mid_cache_key(ticker, expiry, strike, "call")
    put_key = option_mid_cache_key(ticker, expiry, strike, "put")
    if call_key is None or put_key is None:
        return False
    call_entry = mid_cache.get(call_key) if isinstance(mid_cache, dict) else None
    put_entry = mid_cache.get(put_key) if isinstance(mid_cache, dict) else None
    call = clean_float(call_entry.get("mid")) if isinstance(call_entry, dict) else None
    put = clean_float(put_entry.get("mid")) if isinstance(put_entry, dict) else None
    spot = clean_float(result.get("spot"))
    if call is None or put is None or spot is None or spot <= 0:
        return False

    straddle = call + put
    result["atm_call"] = call
    result["atm_put"] = put
    result["straddle"] = straddle
    result["em_raw"] = straddle / spot
    result["em_adj"] = 0.85 * straddle / spot
    result["quote_basis"] = "prior_close_mid"
    result["move_status"] = "prior_close"
    if result.get("spot_is_extended"):
        result["basis_note"] = f"stock {result.get('spot_source') or 'extended'} · options prior close"
    else:
        result["basis_note"] = "stock regular/current · options prior close"
    result["option_mid_cache_used"] = True
    result["option_mid_cache_stored_at"] = call_entry.get("stored_at") or put_entry.get("stored_at")
    result["quote_quality"] = {
        "confidence": "low",
        "warnings": ["using last regular-session option mids"],
        "basis": "prior_close_mid",
        "move_status": "prior_close",
        "oldest_age_seconds": None,
        "oldest_age_label": None,
        "legs": {
            "call": {
                "source": "regular_mid_cache",
                "mid": call,
                "stored_at": call_entry.get("stored_at"),
                "warnings": ["using last regular-session option mid"],
            },
            "put": {
                "source": "regular_mid_cache",
                "mid": put,
                "stored_at": put_entry.get("stored_at"),
                "warnings": ["using last regular-session option mid"],
            },
        },
    }
    return True


def prune_regular_mid_cache(
    mid_cache: dict[str, Any],
    *,
    today: datetime.date | None = None,
    max_entries: int = 2000,
) -> bool:
    today = today or event_move_core.eastern_market_date()
    kept: dict[str, Any] = {}
    changed = False
    for key, entry in mid_cache.items():
        expiry = entry.get("expiry") if isinstance(entry, dict) else None
        if not expiry:
            parts = str(key).split("|")
            expiry = parts[1] if len(parts) >= 2 else None
        try:
            expiry_date = datetime.strptime(str(expiry), "%Y-%m-%d").date()
        except Exception:
            changed = True
            continue
        if expiry_date < today:
            changed = True
            continue
        kept[key] = entry

    if len(kept) > max_entries:
        ordered = sorted(
            kept.items(),
            key=lambda item: str(item[1].get("stored_at", "")) if isinstance(item[1], dict) else "",
            reverse=True,
        )
        kept = dict(ordered[:max_entries])
        changed = True

    if changed:
        mid_cache.clear()
        mid_cache.update(kept)
    return changed


def normalize_result(
    item: dict[str, Any],
    result: dict[str, Any],
    *,
    key: str,
    fetched_at: str,
    previous: dict[str, Any] | None,
    min_valid_iv: float,
) -> dict[str, Any]:
    spot = clean_float(result.get("spot"))
    em_raw = clean_float(result.get("em_raw"))
    em_adj = clean_float(result.get("em_adj"))
    straddle = clean_float(result.get("straddle"))
    threshold = clean_float(result.get("threshold"))
    prob_below = clean_float(result.get("prob_below"))
    prob_above = 1.0 - prob_below if prob_below is not None else None
    prob_below_raw = clean_float(result.get("prob_below_raw"))
    atm_iv = clean_float(result.get("atm_iv"))
    em_iv = clean_float(result.get("em_iv"))
    atm_iv_unavailable_reason = result.get("atm_iv_invalid_reason")
    atm_iv_valid = atm_iv is not None and atm_iv >= min_valid_iv and not atm_iv_unavailable_reason
    if not atm_iv_valid:
        em_iv = None
    em_iv_pct = (em_iv / spot) if em_iv is not None and spot else None
    skew = clean_float(result.get("skew"))
    quote_quality = result.get("quote_quality") if isinstance(result.get("quote_quality"), dict) else {}
    quote_basis = result.get("quote_basis") or quote_quality.get("basis") or "unknown"
    move_status = result.get("move_status") or quote_quality.get("move_status") or "stale"
    quote_warnings = list(quote_quality.get("warnings") if isinstance(quote_quality.get("warnings"), list) else [])
    if result.get("atm_selection_note"):
        quote_warnings.append(str(result.get("atm_selection_note")))
    prob_reliable = (
        threshold is not None
        and prob_below is not None
        and quote_basis == "live_mid"
        and not result.get("prob_warning")
        and clean_float(result.get("days")) not in (None, 0)
    )
    prob_unreliable_reason = None
    if threshold is not None and not prob_reliable:
        if quote_basis != "live_mid":
            prob_unreliable_reason = "odds unreliable: option quotes are not live mids"
        elif result.get("prob_warning"):
            prob_unreliable_reason = f"odds unreliable: {result.get('prob_warning')}"
        else:
            prob_unreliable_reason = "odds unreliable for this chain"

    row = {
        "key": key,
        "ok": True,
        "stale": False,
        "ticker": str(result.get("ticker") or item.get("ticker", "")).upper(),
        "label": item.get("label") or "",
        "event": item.get("event"),
        "event_source": item.get("event_source") or item.get("source") or "manual",
        "event_confidence": item.get("event_confidence") or "user",
        "event_url": item.get("event_url"),
        "timing": item.get("timing") or "unknown",
        "expiry": result.get("expiry"),
        "days": result.get("days"),
        "dte_basis": result.get("dte_basis"),
        "event_gap_days": result.get("event_gap_days"),
        "event_gap_label": result.get("event_gap_label"),
        "event_gap_severity": result.get("event_gap_severity"),
        "event_gap_warning": result.get("event_gap_warning"),
        "event_passed": bool(result.get("event_passed")),
        "spot": spot,
        "spot_source": result.get("spot_source") or "regular/last",
        "spot_is_extended": bool(result.get("spot_is_extended")),
        "atm_strike": clean_float(result.get("atm_strike")),
        "atm_selection": result.get("atm_selection") or "nearest",
        "atm_selection_note": result.get("atm_selection_note"),
        "atm_call": clean_float(result.get("atm_call")),
        "atm_put": clean_float(result.get("atm_put")),
        "straddle": straddle,
        "em_raw": em_raw,
        "em_adj": em_adj,
        "em_raw_dollars": spot * em_raw if spot is not None and em_raw is not None else None,
        "em_adj_dollars": spot * em_adj if spot is not None and em_adj is not None else None,
        "raw_low": spot * (1 - em_raw) if spot is not None and em_raw is not None else None,
        "raw_high": spot * (1 + em_raw) if spot is not None and em_raw is not None else None,
        "adj_low": spot * (1 - em_adj) if spot is not None and em_adj is not None else None,
        "adj_high": spot * (1 + em_adj) if spot is not None and em_adj is not None else None,
        "atm_iv": atm_iv,
        "atm_iv_pct": atm_iv if atm_iv_valid else None,
        "atm_iv_source": result.get("atm_iv_source"),
        "atm_iv_valid": atm_iv_valid,
        "atm_iv_unavailable_reason": atm_iv_unavailable_reason,
        "iv_check_available": atm_iv_valid,
        "em_iv": em_iv,
        "iv_move_pct": em_iv_pct,
        "em_iv_pct": em_iv_pct,
        "skew_pct": clean_float(result.get("skew_pct")),
        "put_k": clean_float(result.get("put_k")),
        "call_k": clean_float(result.get("call_k")),
        "put_iv": clean_float(result.get("put_iv")),
        "call_iv": clean_float(result.get("call_iv")),
        "skew": skew,
        "skew_label": skew_label(skew),
        "threshold": threshold,
        "prob_below": prob_below if prob_reliable else None,
        "prob_above": prob_above if prob_reliable else None,
        "prob_below_raw": prob_below_raw,
        "prob_below_clamped": clean_float(result.get("prob_below_clamped")),
        "prob_warning": result.get("prob_warning"),
        "prob_reliable": prob_reliable,
        "prob_unreliable_reason": prob_unreliable_reason,
        "risk_neutral": threshold is not None,
        "quote_quality": quote_quality,
        "quote_basis": quote_basis,
        "move_status": move_status,
        "move_status_label": "",
        "quote_confidence": quote_quality.get("confidence") or "unknown",
        "quote_warnings": quote_warnings,
        "option_quote_age": quote_quality.get("oldest_age_label"),
        "basis_note": result.get("basis_note"),
        "option_mid_cache_used": bool(result.get("option_mid_cache_used")),
        "option_mid_cache_stored_at": result.get("option_mid_cache_stored_at"),
        "cache_status": "refresh",
        "not_rechecked": False,
        "fetched_at": fetched_at,
        "error": None,
    }
    row["move_status_label"] = quote_basis_label(row)
    if row.get("basis_note") is None:
        if row.get("spot_is_extended") and quote_basis == "last_trade":
            row["basis_note"] = f"stock {row.get('spot_source')} · options last trade"
        elif row.get("spot_is_extended") and quote_basis == "live_mid":
            row["basis_note"] = f"stock {row.get('spot_source')} · options live mid"
        elif quote_basis == "live_mid":
            row["basis_note"] = "stock regular · options live mid"
        elif quote_basis == "last_trade":
            row["basis_note"] = "stock regular · options last trade"
        else:
            row["basis_note"] = "quote basis unclear"
    if row.get("option_quote_age") and row.get("quote_basis") != "prior_close_mid":
        row["basis_note"] = f"{row['basis_note']} · option age {row['option_quote_age']}"
    apply_prior_mid_fallback(row, previous)
    row["move_status_label"] = quote_basis_label(row)
    row["delta"] = compute_deltas(row, previous)
    return row


def stale_row_from_last_good(
    item: dict[str, Any],
    *,
    key: str,
    error: str,
    last_good: dict[str, Any],
) -> dict[str, Any] | None:
    row = last_good.get(key)
    if not isinstance(row, dict):
        return None
    copy = dict(row)
    copy["stale"] = True
    copy["error"] = error
    copy["served_at"] = iso_now()
    copy["cache_status"] = "last_good"
    copy["not_rechecked"] = True
    copy["move_status"] = "stale"
    copy["move_status_label"] = "Stale"
    return copy


def error_row(item: dict[str, Any], *, key: str, error: str) -> dict[str, Any]:
    return {
        "key": key,
        "ok": False,
        "stale": False,
        "ticker": str(item.get("ticker", "")).upper() or "UNKNOWN",
        "label": item.get("label") or "",
        "event": item.get("event"),
        "expiry": None,
        "threshold": clean_float(item.get("threshold")),
        "cache_status": "error",
        "not_rechecked": False,
        "error": error,
    }


def degraded_row_from_error(item: dict[str, Any], *, error: str, last_good: dict[str, Any]) -> dict[str, Any]:
    key = row_key(item)
    stale = stale_row_from_last_good(item, key=key, error=error, last_good=last_good)
    if stale is not None:
        return stale
    return error_row(item, key=key, error=error)


def mark_cached_rows(envelope: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in envelope.get("rows", []):
        if isinstance(row, dict):
            copy = dict(row)
            copy["cache_status"] = "hit"
            copy["not_rechecked"] = True
            copy["move_status"] = "cached"
            copy["move_status_label"] = "Cached"
            copy["delta"] = {
                "em_adj": None,
                "em_raw": None,
                "spot": None,
                "prob_below": None,
                "basis_match": False,
                "label": "cached",
            }
            rows.append(copy)
        else:
            rows.append(row)
    envelope["rows"] = rows
    summary = envelope.get("summary")
    if isinstance(summary, dict):
        total = sum(1 for row in rows if isinstance(row, dict) and row.get("ok"))
        summary["move_status"] = {"cached": total}
    return envelope


def analyze_item(
    item: dict[str, Any],
    *,
    default_skew_pct: float,
    min_valid_iv: float,
    last_good: dict[str, Any],
    regular_mid_cache: dict[str, Any],
    market: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    key = row_key(item)
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker:
        return error_row(item, key=key, error="Missing ticker"), None

    event = item.get("event")
    threshold = clean_float(item.get("threshold"))
    skew_pct = clean_float(item.get("skew_pct"))
    if skew_pct is None:
        skew_pct = default_skew_pct
    previous = last_good.get(key) if isinstance(last_good.get(key), dict) else None

    try:
        fetched_at = iso_now()
        result = event_move_core.analyze(
            ticker,
            event=event,
            threshold=threshold,
            skew_pct=skew_pct,
            timing=item.get("timing"),
        )
        if result.get("quote_basis") != "live_mid":
            apply_regular_mid_cache_to_result(result, regular_mid_cache)
        row = normalize_result(
            item,
            result,
            key=key,
            fetched_at=fetched_at,
            previous=previous,
            min_valid_iv=min_valid_iv,
        )
        return row, row
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        log(f"{ticker} failed: {message}")
        stale = stale_row_from_last_good(item, key=key, error=message, last_good=last_good)
        if stale is not None:
            return stale, None
        return error_row(item, key=key, error=message), None


def build_envelope(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    display = config.get("display") or {}
    normalized_display = display_settings(config)
    defaults = config.get("defaults") or {}
    ttl = int(display.get("cache_ttl_seconds", 900))
    cache_key = config_cache_key(config)
    entries, validation_issues = prepare_watchlist_entries(config)

    if not force and is_fresh(DATA_CACHE, ttl):
        cached = read_json(DATA_CACHE, None)
        if isinstance(cached, dict) and cached.get("cache_key") == cache_key:
            cached_summary = cached.get("summary") if isinstance(cached.get("summary"), dict) else {}
            cached_validation_issues = cached_summary.get("validation_issues") or []
            if validation_issues and cached_validation_issues != validation_issues:
                cached = None
            else:
                cached["cache_status"] = "hit"
                cached["served_at"] = iso_now()
                cached["cache_age_seconds"] = round(cache_age_seconds(DATA_CACHE) or 0, 1)
                cached["market_status"] = event_move_core.market_status()
                cached["display"] = normalized_display
                mark_cached_rows(cached)
                return cached

    last_good = read_json(LAST_GOOD, {})
    if not isinstance(last_good, dict):
        last_good = {}
    regular_mid_cache = read_json(REGULAR_MIDS, {})
    if not isinstance(regular_mid_cache, dict):
        regular_mid_cache = {}
    regular_mid_cache_changed = False
    market = event_move_core.market_status()

    default_skew_pct = clean_float(defaults.get("skew_pct"))
    if default_skew_pct is None:
        default_skew_pct = 0.05
    min_valid_iv = clean_float(defaults.get("min_valid_iv"))
    if min_valid_iv is None:
        min_valid_iv = 0.01
    fetch_timeout_seconds = clean_float(defaults.get("fetch_timeout_seconds"))
    if fetch_timeout_seconds is None:
        fetch_timeout_seconds = clean_float(display.get("fetch_timeout_seconds"))
    if fetch_timeout_seconds is None:
        fetch_timeout_seconds = 20.0
    max_workers = clean_float(defaults.get("max_workers"))
    if max_workers is None:
        max_workers = clean_float(display.get("max_workers"))
    if max_workers is None:
        max_workers = 6
    max_workers = max(1, int(max_workers))

    rows: list[dict[str, Any] | None] = [None] * len(entries)
    updated_last_good = dict(last_good)
    timed_out = False
    futures: list[tuple[int, dict[str, Any], concurrent.futures.Future]] = []
    fetch_count = sum(1 for entry in entries if entry.get("kind") == "fetch")
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, max(fetch_count, 1)))
    try:
        for index, entry in enumerate(entries):
            if entry.get("kind") == "error":
                rows[index] = entry.get("row")
                continue
            item = entry["item"]
            future = executor.submit(
                analyze_item,
                item,
                default_skew_pct=default_skew_pct,
                min_valid_iv=min_valid_iv,
                last_good=last_good,
                regular_mid_cache=regular_mid_cache,
                market=market,
            )
            futures.append((index, item, future))

        for index, item, future in futures:
            ticker = str(item.get("ticker", "")).strip().upper() or "UNKNOWN"
            try:
                row, good = future.result(timeout=fetch_timeout_seconds)
            except concurrent.futures.TimeoutError:
                timed_out = True
                future.cancel()
                message = f"{ticker} fetch timed out after {fetch_timeout_seconds:g}s"
                log(f"{ticker} failed: {message}")
                row, good = degraded_row_from_error(item, error=message, last_good=last_good), None
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                log(f"{ticker} future failed: {message}")
                row, good = degraded_row_from_error(item, error=message, last_good=last_good), None

            rows[index] = row
            if good is not None:
                updated_last_good[good["key"]] = good
            if market.get("state") == "open" and row.get("quote_basis") == "live_mid":
                regular_mid_cache_changed = store_regular_session_mids(row, regular_mid_cache, row.get("fetched_at") or iso_now()) or regular_mid_cache_changed
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=True)

    final_rows = [row for row in rows if row is not None]
    mark_duplicate_atm_ivs(final_rows)

    regular_mid_cache_changed = prune_regular_mid_cache(regular_mid_cache) or regular_mid_cache_changed

    ok_count = sum(1 for row in final_rows if row.get("ok"))
    stale_count = sum(1 for row in final_rows if row.get("stale"))
    error_count = sum(1 for row in final_rows if not row.get("ok"))
    status_counts: dict[str, int] = {}
    for row in final_rows:
        if not row.get("ok"):
            continue
        status = str(row.get("move_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    envelope = {
        "generated_at": iso_now(),
        "served_at": iso_now(),
        "cache_key": cache_key,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "source": "yfinance",
        "cache_status": "refresh",
        "cache_ttl_seconds": ttl,
        "cache_age_seconds": 0,
        "market_status": market,
        "rows": final_rows,
        "summary": {
            "total": len(final_rows),
            "ok": ok_count,
            "stale": stale_count,
            "errors": error_count,
            "move_status": status_counts,
            "validation_issues": validation_issues,
        },
        "display": normalized_display,
    }

    write_json_atomic(LAST_GOOD, updated_last_good)
    if regular_mid_cache_changed:
        write_json_atomic(REGULAR_MIDS, regular_mid_cache)
    write_json_atomic(DATA_CACHE, envelope)
    return envelope


def check_writable_dir(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".doctor-", dir=path)
        os.close(fd)
        os.unlink(tmp_name)
    except Exception as exc:
        return False, str(exc)
    return True, str(path)


def doctor_checks(
    *,
    config_path: Path = CONFIG_PATH,
    cache_dir: Path = CACHE_DIR,
    log_dir: Path = LOG_DIR,
    symlink_path: Path | None = UBERSICHT_LINK,
    skip_yahoo: bool = False,
    yahoo_timeout: float = 3.0,
) -> tuple[bool, list[str]]:
    lines = ["Options Swing Tracker doctor"]
    critical_failures = 0

    def add(status: str, name: str, detail: str, *, critical: bool = False) -> None:
        nonlocal critical_failures
        lines.append(f"{status} {name}: {detail}")
        if status == "FAIL" and critical:
            critical_failures += 1

    expected_venv = ROOT / "python" / ".venv"
    expected_python = expected_venv / "bin" / "python"
    current_python = Path(sys.executable)
    if not expected_python.exists():
        add("FAIL", "venv", f"missing {expected_python}", critical=True)
    elif Path(sys.prefix).resolve() != expected_venv.resolve():
        add("FAIL", "venv", f"running {current_python} with prefix {sys.prefix}, expected {expected_venv}", critical=True)
    else:
        add("PASS", "venv", f"{current_python} (prefix {sys.prefix})")

    missing_deps: list[str] = []
    for package in ("yfinance", "pandas", "numpy", "pytest"):
        try:
            __import__(package)
        except Exception:
            missing_deps.append(package)
    if missing_deps:
        add("FAIL", "deps", f"missing imports: {', '.join(missing_deps)}", critical=True)
    else:
        add("PASS", "deps", "yfinance, pandas, numpy, pytest importable")

    config, config_error = load_config_from_path(config_path)
    if config_error:
        add("FAIL", "config", config_error, critical=True)
    else:
        entries, issues = prepare_watchlist_entries(config)
        enabled_count = sum(1 for entry in entries if entry.get("kind") == "fetch")
        if issues:
            add("FAIL", "config", f"{len(issues)} enabled-row issue(s)", critical=True)
            for issue in issues:
                lines.append(f"  - {issue}")
        else:
            add("PASS", "config", f"{enabled_count} enabled row(s) valid")

    for label, path in (("cache", cache_dir), ("logs", log_dir)):
        ok, detail = check_writable_dir(path)
        add("PASS" if ok else "FAIL", f"{label} writable", detail, critical=not ok)

    if symlink_path is None:
        add("SKIP", "ubersicht symlink", "not checked")
    elif not symlink_path.exists():
        add("FAIL", "ubersicht symlink", f"missing {symlink_path}", critical=True)
    elif not symlink_path.is_symlink():
        add("FAIL", "ubersicht symlink", f"{symlink_path} exists but is not a symlink", critical=True)
    elif symlink_path.resolve() != ROOT:
        add("FAIL", "ubersicht symlink", f"{symlink_path} -> {symlink_path.resolve()}, expected {ROOT}", critical=True)
    else:
        add("PASS", "ubersicht symlink", f"{symlink_path} -> {ROOT}")

    if skip_yahoo:
        add("SKIP", "yahoo", "skipped")
    else:
        try:
            import urllib.request

            url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d"
            with urllib.request.urlopen(url, timeout=yahoo_timeout) as response:
                add("PASS", "yahoo", f"reachable, HTTP {response.status}")
        except Exception as exc:
            add("WARN", "yahoo", f"quick check failed/skipped: {exc}")

    lines.append("RESULT PASS" if critical_failures == 0 else "RESULT FAIL")
    return critical_failures == 0, lines


def cmd_render(args: argparse.Namespace) -> int:
    try:
        config = load_config()
        envelope = build_envelope(config, force=args.force_refresh)
    except Exception as exc:
        log(f"fatal render error: {exc}\n{traceback.format_exc()}")
        envelope = {
            "generated_at": iso_now(),
            "served_at": iso_now(),
            "source": "widget",
            "cache_status": "fatal",
            "market_status": event_move_core.market_status(),
            "rows": [],
            "summary": {"total": 0, "ok": 0, "stale": 0, "errors": 1},
            "error": str(exc),
        }
    print(json.dumps(envelope, separators=(",", ":"), sort_keys=True))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    result = event_move_core.analyze(
        args.ticker,
        event=args.event,
        threshold=args.threshold,
        skew_pct=args.skew_pct,
        timing=args.timing,
    )
    print(json.dumps(result, default=str, indent=2, sort_keys=True))
    return 0


def cmd_resolve_expiry(args: argparse.Namespace) -> int:
    print(event_move_core.choose_expiry(args.ticker, event=args.event, expiry=args.expiry, timing=args.timing))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    ok, lines = doctor_checks(skip_yahoo=args.skip_yahoo, yahoo_timeout=args.yahoo_timeout)
    print("\n".join(lines))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Options Swing Tracker data command")
    sub = parser.add_subparsers(dest="command")

    render = sub.add_parser("render", help="Emit widget JSON")
    render.add_argument("--force-refresh", action="store_true")
    render.set_defaults(func=cmd_render)

    analyze = sub.add_parser("analyze", help="Run one analysis as JSON")
    analyze.add_argument("--ticker", required=True)
    analyze.add_argument("--event")
    analyze.add_argument("--threshold", type=float)
    analyze.add_argument("--skew-pct", type=float, default=0.05)
    analyze.add_argument("--timing", choices=["unknown", "bmo", "amc", "intraday"], default="unknown")
    analyze.set_defaults(func=cmd_analyze)

    resolve = sub.add_parser("resolve-expiry", help="Resolve bracketing expiry")
    resolve.add_argument("--ticker", required=True)
    resolve.add_argument("--event")
    resolve.add_argument("--expiry")
    resolve.add_argument("--timing", choices=["unknown", "bmo", "amc", "intraday"], default="unknown")
    resolve.set_defaults(func=cmd_resolve_expiry)

    doctor = sub.add_parser("doctor", help="Check local widget health")
    doctor.add_argument("--skip-yahoo", action="store_true", help="Skip the optional Yahoo reachability check")
    doctor.add_argument("--yahoo-timeout", type=float, default=3.0)
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["render"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
