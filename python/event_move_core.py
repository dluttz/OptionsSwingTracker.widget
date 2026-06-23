#!/usr/bin/env python3
"""Thin wrapper around the preserved event_move.py implementation."""

from __future__ import annotations

import importlib.util
import math
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference" / "event_move_original.py"


def _load_original():
    if not REFERENCE.exists():
        raise RuntimeError(f"Missing reference script: {REFERENCE}")
    spec = importlib.util.spec_from_file_location("event_move_original", REFERENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load reference script: {REFERENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


original = _load_original()


MIN_SANE_ATM_IV = 0.05
MAX_SANE_ATM_IV = 3.0
EASTERN = ZoneInfo("America/New_York")
YAHOO_PLACEHOLDER_IVS = (0.125, 0.1875, 0.25)


def _clean_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _sane_iv(value: Any) -> float | None:
    number = _clean_number(value)
    if number is None or number < MIN_SANE_ATM_IV or number > MAX_SANE_ATM_IV:
        return None
    return number


def _looks_like_yahoo_placeholder_iv(value: Any) -> bool:
    iv = _clean_number(value)
    if iv is None:
        return False
    return any(abs(iv - placeholder) < 0.00025 for placeholder in YAHOO_PLACEHOLDER_IVS)


def _iv_credibility_issue(values: list[float], move_status: str | None = None) -> str | None:
    if not values:
        return None
    rounded = {round(value, 6) for value in values}
    if all(_looks_like_yahoo_placeholder_iv(value) for value in values):
        return "chain placeholder"
    if len(values) > 1 and len(rounded) == 1:
        return "chain placeholder"
    if move_status and move_status != "live":
        return "chain placeholder"
    return None


def eastern_now() -> datetime:
    return datetime.now(EASTERN)


def eastern_market_date() -> datetime.date:
    return eastern_now().date()


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year, 12, 31)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _equity_market_holidays_for_year(year: int) -> dict[date, str]:
    return {
        _observed_fixed_holiday(year, 1, 1): "New Year's Day",
        _nth_weekday(year, 1, 0, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "Presidents' Day",
        _easter_date(year) - timedelta(days=2): "Good Friday",
        _last_weekday(year, 5, 0): "Memorial Day",
        _observed_fixed_holiday(year, 6, 19): "Juneteenth",
        _observed_fixed_holiday(year, 7, 4): "Independence Day",
        _nth_weekday(year, 9, 0, 1): "Labor Day",
        _nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        _observed_fixed_holiday(year, 12, 25): "Christmas Day",
    }


def equity_market_holiday(day: date) -> str | None:
    for year in (day.year - 1, day.year, day.year + 1):
        holiday = _equity_market_holidays_for_year(year).get(day)
        if holiday:
            return holiday
    return None


def equity_market_early_close(day: date) -> str | None:
    if equity_market_holiday(day) or day.weekday() >= 5:
        return None
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    if day == thanksgiving + timedelta(days=1):
        return "day after Thanksgiving"
    christmas_eve = date(day.year, 12, 24)
    if day == christmas_eve:
        return "Christmas Eve"
    july_3 = date(day.year, 7, 3)
    if day == july_3 and day.weekday() < 5 and not equity_market_holiday(day):
        return "day before Independence Day"
    return None


def market_status(now: datetime | None = None) -> dict[str, Any]:
    now = now or eastern_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=EASTERN)
    else:
        now = now.astimezone(EASTERN)
    pre_open_time = time(4, 0)
    open_time = time(9, 30)
    regular_close_time = time(16, 0)
    early_close_reason = equity_market_early_close(now.date())
    close_time = time(13, 0) if early_close_reason else regular_close_time
    post_close_time = time(20, 0)
    is_weekday = now.weekday() < 5
    current_time = now.time()

    holiday = equity_market_holiday(now.date())
    if holiday:
        return {
            "is_open": False,
            "state": "closed",
            "label": "market holiday",
            "holiday": holiday,
            "early_close": False,
            "early_close_reason": None,
            "eastern_time": now.isoformat(timespec="seconds"),
            "basis": "US/Eastern equity market hours with standard NYSE/Nasdaq holidays",
        }

    is_open = is_weekday and open_time <= current_time < close_time
    if is_open:
        state = "open"
        label = "market open" if not early_close_reason else "market open · early close 1 PM"
    elif is_weekday and pre_open_time <= current_time < open_time:
        state = "premarket"
        label = "pre-market" if not early_close_reason else "pre-market · early close 1 PM"
    elif is_weekday and close_time <= current_time < post_close_time:
        state = "afterhours"
        label = "after hours"
    else:
        state = "closed"
        label = "market closed"
    return {
        "is_open": is_open,
        "state": state,
        "label": label,
        "holiday": None,
        "early_close": bool(early_close_reason),
        "early_close_reason": early_close_reason,
        "eastern_time": now.isoformat(timespec="seconds"),
        "basis": "US/Eastern equity market hours with standard NYSE/Nasdaq holidays",
    }


def _quote_info(tk: Any) -> dict[str, Any]:
    try:
        info = tk.info
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def preferred_spot_quote(tk: Any) -> dict[str, Any]:
    """
    Prefer Yahoo extended-hours stock prices outside the regular session.

    Options prices still come from the option chain, so rows using stale option
    quotes remain marked low confidence by quote-quality checks.
    """
    if os.environ.get("OPTIONS_SWING_DISABLE_EXTENDED_HOURS") == "1":
        return {"price": original.get_spot(tk), "source": "regular/last", "is_extended": False}

    status = market_status()
    info = _quote_info(tk)
    extended_key = None
    extended_source = None
    if status["state"] == "premarket":
        extended_key = "preMarketPrice"
        extended_source = "pre-market"
    elif status["state"] == "afterhours":
        extended_key = "postMarketPrice"
        extended_source = "after hours"

    if extended_key:
        price = _clean_number(info.get(extended_key))
        if price is not None and price > 0:
            return {"price": price, "source": extended_source, "is_extended": True}

    for key, source in (
        ("regularMarketPrice", "regular"),
        ("currentPrice", "regular/current"),
        ("bid", "bid"),
        ("ask", "ask"),
    ):
        price = _clean_number(info.get(key))
        if price is not None and price > 0:
            return {"price": price, "source": source, "is_extended": False}

    return {"price": original.get_spot(tk), "source": "regular/last", "is_extended": False}


def eastern_dte(expiry: str) -> int:
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    return max((exp_date - eastern_market_date()).days, 0)


def _parse_expiry_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def event_expiry_gap(event: str | None, expiry: str | None, timing: str | None = None) -> dict[str, Any]:
    if not event or not expiry:
        return {"days": None, "label": None, "severity": "unknown", "warning": None, "event_passed": False}
    try:
        event_date = _parse_expiry_date(event)
        expiry_date = _parse_expiry_date(expiry)
    except ValueError:
        return {"days": None, "label": None, "severity": "unknown", "warning": "bad event date", "event_passed": False}
    gap = (expiry_date - event_date).days
    normalized_timing = (timing or "unknown").strip().lower()
    event_passed = event_date < eastern_market_date()
    if gap < 0:
        severity = "invalid"
        warning = "selected expiry is before the event; expected move does not cover the catalyst"
    elif normalized_timing == "amc" and gap <= 0:
        severity = "timing"
        warning = "after-close event needs an expiry after the event date"
    elif normalized_timing in ("unknown", "") and gap == 0:
        severity = "timing"
        warning = "event timing unknown on expiry day"
    elif gap <= 1:
        severity = "clean"
        warning = None
    elif gap <= 7:
        severity = "padded"
        warning = f"expiry is {gap}d after event"
    else:
        severity = "wide"
        warning = f"expiry is {gap}d after event; straddle includes extra volatility"
    return {
        "days": gap,
        "label": "exp before event" if gap < 0 else ("same day" if gap == 0 else f"+{gap}d"),
        "severity": severity,
        "warning": warning,
        "timing": normalized_timing or "unknown",
        "event_passed": event_passed,
    }


def choose_expiry(ticker: str, event: str | None = None, expiry: str | None = None, timing: str | None = None) -> str:
    """Resolve expiry using original semantics, except AMC events require a later expiry."""
    tk = original.yf.Ticker(ticker)
    return choose_expiry_from_expirations(list(tk.options), event=event, expiry=expiry, timing=timing)


def choose_expiry_from_expirations(
    expirations: list[str],
    event: str | None = None,
    expiry: str | None = None,
    timing: str | None = None,
) -> str:
    if not expirations:
        raise RuntimeError("No option expirations available for this ticker.")
    if expiry:
        return original.choose_expiry(expirations, event=event, expiry=expiry)
    if event:
        ev = _parse_expiry_date(event)
        if (timing or "").strip().lower() == "amc":
            after = [e for e in expirations if _parse_expiry_date(e) > ev]
            if not after:
                raise RuntimeError(f"No listed expiry after the after-close event date {event}.")
            return after[0]
        after = [e for e in expirations if _parse_expiry_date(e) >= ev]
        if not after:
            raise RuntimeError(f"No listed expiry on or after the event date {event}.")
        return after[0]
    return expirations[0]


def _fetch_chain(ticker: str, expiry: str):
    try:
        return original.yf.Ticker(ticker).option_chain(expiry)
    except Exception:
        return None


def _chain_atm_iv(chain: Any, atm_strike: float) -> tuple[float | None, str | None, str | None]:
    """Read a sane per-contract ATM IV from the chain when Yahoo provides one."""
    if chain is None:
        return None, None, None

    values: list[float] = []
    for df in (chain.calls, chain.puts):
        if getattr(df, "empty", True) or "impliedVolatility" not in df:
            continue
        row = original.nearest_row(df, atm_strike)
        iv = _sane_iv(row.get("impliedVolatility"))
        if iv is not None:
            values.append(iv)
    if not values:
        return None, None, None
    return sum(values) / len(values), "atm-chain", _iv_credibility_issue(values)


def _nearby_chain_iv(result: dict[str, Any]) -> tuple[float | None, str | None, str | None]:
    values = []
    for key in ("put_iv", "call_iv"):
        iv = _sane_iv(result.get(key))
        if iv is not None:
            values.append(iv)
    if not values:
        return None, None, None
    return sum(values) / len(values), "nearby-chain", _iv_credibility_issue(values)


def _parse_last_trade(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if hasattr(value, "to_pydatetime"):
            dt = value.to_pydatetime()
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_label(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 3600:
        return f"{int(seconds // 60)}m old"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h old"
    return f"{seconds / 86400:.1f}d old"


def _quote_leg(row: Any) -> dict[str, Any]:
    bid = _clean_number(row.get("bid"))
    ask = _clean_number(row.get("ask"))
    last = _clean_number(row.get("lastPrice"))
    last_trade_at = _parse_last_trade(row.get("lastTradeDate"))
    age_seconds = None
    if last_trade_at is not None:
        age_seconds = max((datetime.now(timezone.utc) - last_trade_at).total_seconds(), 0)
    detail: dict[str, Any] = {
        "bid": bid,
        "ask": ask,
        "last": last,
        "last_trade_at": last_trade_at.isoformat(timespec="seconds") if last_trade_at else None,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "age_label": _age_label(age_seconds),
        "source": None,
        "spread_pct": None,
        "warnings": [],
    }
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid if mid > 0 else None
        detail["source"] = "mid"
        detail["mid"] = mid
        detail["spread_pct"] = spread_pct
        if spread_pct is not None and spread_pct > 0.25:
            detail["warnings"].append(f"wide spread {spread_pct * 100:.0f}%")
        return detail
    if last is not None and last > 0:
        detail["source"] = "lastPrice"
        detail["mid"] = None
        detail["warnings"].append("last trade used; bid/ask missing")
        if age_seconds is not None and age_seconds > 36 * 3600:
            detail["warnings"].append(f"stale option trade {detail['age_label']}")
        return detail
    detail["warnings"].append("missing option quote")
    if age_seconds is not None and age_seconds > 36 * 3600:
        detail["warnings"].append(f"stale option trade {detail['age_label']}")
    return detail


def _bid_ask_mid(row: Any) -> float | None:
    bid = _clean_number(row.get("bid"))
    ask = _clean_number(row.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0


def _activity_score(row: Any) -> float:
    volume = _clean_number(row.get("volume")) or 0.0
    open_interest = _clean_number(row.get("openInterest")) or 0.0
    return max(volume, 0.0) + max(open_interest, 0.0)


def _same_strike_row(df: Any, strike: float) -> Any | None:
    if getattr(df, "empty", True) or "strike" not in df:
        return None
    try:
        row = original.nearest_row(df, strike)
    except Exception:
        return None
    row_strike = _clean_number(row.get("strike"))
    if row_strike is None or abs(row_strike - strike) > 0.0001:
        return None
    return row


def nearest_liquid_pair(chain: Any, spot: float | None, current_strike: float | None) -> dict[str, Any] | None:
    """Find the nearest quoted strike when the distance-nearest strike is empty."""
    if chain is None or spot is None or current_strike is None:
        return None
    calls = getattr(chain, "calls", None)
    puts = getattr(chain, "puts", None)
    if getattr(calls, "empty", True) or getattr(puts, "empty", True):
        return None

    try:
        current_call = original.nearest_row(calls, current_strike)
    except Exception:
        current_call = None
    current_put = _same_strike_row(puts, current_strike)
    current_call_mid = _bid_ask_mid(current_call) if current_call is not None else None
    current_put_mid = _bid_ask_mid(current_put) if current_put is not None else None
    current_activity = (
        (_activity_score(current_call) if current_call is not None else 0.0)
        + (_activity_score(current_put) if current_put is not None else 0.0)
    )
    if current_call_mid is not None and current_put_mid is not None:
        return None
    if current_activity > 0:
        return None

    candidates: list[dict[str, Any]] = []
    try:
        ordered_calls = calls.assign(_dist=(calls["strike"] - spot).abs()).sort_values(["_dist", "strike"])
    except Exception:
        return None

    for _, call_row in ordered_calls.iterrows():
        strike = _clean_number(call_row.get("strike"))
        if strike is None:
            continue
        put_row = _same_strike_row(puts, strike)
        if put_row is None:
            continue
        call_mid = _bid_ask_mid(call_row)
        put_mid = _bid_ask_mid(put_row)
        if call_mid is None or put_mid is None:
            continue
        activity = _activity_score(call_row) + _activity_score(put_row)
        candidates.append(
            {
                "strike": float(strike),
                "call": float(call_mid),
                "put": float(put_mid),
                "distance": abs(float(strike) - float(spot)),
                "activity": activity,
                "nearest_strike": float(current_strike),
            }
        )
        if len(candidates) >= 8:
            break

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["distance"], -item["activity"]))
    selected = candidates[0]
    if abs(selected["strike"] - current_strike) < 0.0001:
        return None
    return selected


def quote_quality(chain: Any, atm_strike: float) -> dict[str, Any]:
    if chain is None:
        return {"confidence": "unknown", "warnings": ["could not re-check option quotes"], "legs": {}}
    legs: dict[str, Any] = {}
    warnings: list[str] = []
    for name, df in (("call", chain.calls), ("put", chain.puts)):
        if getattr(df, "empty", True):
            legs[name] = {"warning": "empty option side"}
            warnings.append(f"{name}: empty option side")
            continue
        detail = _quote_leg(original.nearest_row(df, atm_strike))
        legs[name] = detail
        for warning in detail.get("warnings") or []:
            warnings.append(f"{name}: {warning}")
    sources = {leg.get("source") for leg in legs.values() if isinstance(leg, dict)}
    if sources == {"mid"}:
        basis = "live_mid"
        move_status = "live"
    elif "lastPrice" in sources:
        basis = "last_trade"
        move_status = "indicative"
    else:
        basis = "unpriced"
        move_status = "stale"
    confidence = "ok" if basis == "live_mid" and not warnings else "low"
    oldest_age = max(
        [leg.get("age_seconds") for leg in legs.values() if isinstance(leg, dict) and leg.get("age_seconds") is not None],
        default=None,
    )
    return {
        "confidence": confidence,
        "warnings": warnings,
        "legs": legs,
        "basis": basis,
        "move_status": move_status,
        "oldest_age_seconds": oldest_age,
        "oldest_age_label": _age_label(oldest_age),
    }


def session_adjusted_quote_quality(qq: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    if status.get("state") != "closed" or qq.get("move_status") != "live":
        return qq
    adjusted = dict(qq)
    warnings = list(adjusted.get("warnings") or [])
    label = status.get("label") or "market closed"
    warnings.insert(0, f"{label}; option mids not live")
    adjusted["warnings"] = warnings
    adjusted["basis"] = "closed_mid"
    adjusted["move_status"] = "stale"
    adjusted["confidence"] = "low"
    return adjusted


def raw_implied_cdf_below(chain: Any, threshold: Any) -> dict[str, Any]:
    threshold_f = _clean_number(threshold)
    if chain is None or threshold_f is None:
        return {"raw": None, "clamped": None, "warning": None}
    try:
        p = chain.puts.dropna(subset=["strike"]).copy()
        p["mid"] = p.apply(original.mid_price, axis=1)
        p = p.dropna(subset=["mid"]).sort_values("strike").reset_index(drop=True)
        if len(p) < 3:
            return {"raw": None, "clamped": None, "warning": "too few put strikes"}
        mids = list(p["mid"].values)
        monotonic_warning = None
        if any(curr < prev for prev, curr in zip(mids, mids[1:])):
            monotonic_warning = "put prices not monotonic"
        strikes = p["strike"].values
        if threshold_f <= strikes[0] or threshold_f >= strikes[-1]:
            return {"raw": None, "clamped": None, "warning": None}
        hi = next(i for i, k in enumerate(strikes) if k >= threshold_f)
        lo = hi - 1
        lo2 = max(lo - 1, 0)
        hi2 = min(hi + 1, len(strikes) - 1)
        d_put = p["mid"].values[hi2] - p["mid"].values[lo2]
        d_k = strikes[hi2] - strikes[lo2]
        if d_k <= 0:
            return {"raw": None, "clamped": None, "warning": None}
        raw = float(d_put / d_k)
        clamped = min(max(raw, 0.0), 1.0)
        warning = None
        if raw < 0.0 or raw > 1.0:
            warning = f"raw probability {raw:.2f} clamped"
        return {"raw": raw, "clamped": clamped, "warning": warning or monotonic_warning}
    except Exception:
        return {"raw": None, "clamped": None, "warning": None}


def repair_iv_cross_check(
    ticker: str,
    result: dict[str, Any],
    event: str | None = None,
    timing: str | None = None,
) -> dict[str, Any]:
    """Preserve the original formula while making the ATM IV input reliable."""
    repaired = dict(result)
    expiry = str(repaired.get("expiry"))
    atm_strike = _clean_number(repaired.get("atm_strike"))
    chain = _fetch_chain(ticker, expiry)
    spot = _clean_number(repaired.get("spot"))
    status = market_status()

    days = eastern_dte(expiry)
    repaired["days"] = days
    repaired["dte_basis"] = "US/Eastern market date"
    gap = event_expiry_gap(event, expiry, timing=timing)
    repaired["event_gap_days"] = gap["days"]
    repaired["event_gap_label"] = gap["label"]
    repaired["event_gap_severity"] = gap["severity"]
    repaired["event_gap_warning"] = gap["warning"]
    repaired["event_passed"] = gap["event_passed"]

    repaired["atm_selection"] = "nearest"
    if os.environ.get("OPTIONS_SWING_DISABLE_EXTENDED_HOURS") != "1":
        liquid_pair = nearest_liquid_pair(chain, spot, atm_strike)
        if liquid_pair is not None and spot is not None and spot > 0:
            atm_strike = liquid_pair["strike"]
            atm_call = liquid_pair["call"]
            atm_put = liquid_pair["put"]
            straddle = atm_call + atm_put
            repaired["atm_strike"] = atm_strike
            repaired["atm_call"] = atm_call
            repaired["atm_put"] = atm_put
            repaired["straddle"] = straddle
            repaired["em_raw"] = straddle / spot
            repaired["em_adj"] = 0.85 * straddle / spot
            repaired["atm_selection"] = "nearest_liquid"
            repaired["atm_selection_note"] = (
                f"using nearest liquid strike ${atm_strike:g} "
                f"(nearest ${liquid_pair['nearest_strike']:g} had no quotes)"
            )

    qq: dict[str, Any] = {}
    if atm_strike is not None:
        qq = session_adjusted_quote_quality(quote_quality(chain, atm_strike), status)
        repaired["quote_quality"] = qq
        repaired["quote_basis"] = qq.get("basis")
        repaired["move_status"] = qq.get("move_status")

    atm_iv = _sane_iv(repaired.get("atm_iv"))
    source = "chain" if atm_iv is not None else None
    iv_issue = _iv_credibility_issue([atm_iv]) if atm_iv is not None else None

    if atm_iv is None and atm_strike is not None:
        atm_iv, source, iv_issue = _chain_atm_iv(chain, atm_strike)
    nearby_iv, nearby_source, nearby_issue = _nearby_chain_iv(repaired)
    if nearby_iv is not None and (atm_iv is None or atm_iv < nearby_iv * 0.60):
        atm_iv, source, iv_issue = nearby_iv, nearby_source, nearby_issue

    if atm_iv is not None and iv_issue is None:
        iv_issue = _iv_credibility_issue([atm_iv], move_status=qq.get("move_status"))

    if iv_issue:
        repaired["atm_iv_invalid_reason"] = iv_issue
        repaired["atm_iv_rejected_source"] = source
        atm_iv = None
    else:
        repaired["atm_iv_invalid_reason"] = None
        repaired["atm_iv_rejected_source"] = None

    if atm_iv is not None and spot is not None and days is not None and days > 0:
        repaired["atm_iv"] = atm_iv
        repaired["atm_iv_source"] = source
        repaired["em_iv"] = spot * atm_iv * math.sqrt(days / 365.0)
    else:
        repaired["atm_iv"] = None
        repaired["atm_iv_source"] = None
        repaired["em_iv"] = None

    if os.environ.get("OPTIONS_SWING_DISABLE_EXTENDED_HOURS") != "1":
        skew_values = [
            value
            for value in (
                _sane_iv(repaired.get("put_iv")),
                _sane_iv(repaired.get("call_iv")),
            )
            if value is not None
        ]
        skew_issue = _iv_credibility_issue(skew_values, move_status=qq.get("move_status"))
        if skew_issue:
            repaired["skew"] = None
            repaired["skew_unavailable_reason"] = skew_issue
        else:
            repaired["skew_unavailable_reason"] = None
    prob = raw_implied_cdf_below(chain, repaired.get("threshold"))
    repaired["prob_below_raw"] = prob["raw"]
    repaired["prob_below_clamped"] = prob["clamped"]
    repaired["prob_warning"] = prob["warning"]
    return repaired


def available_expirations(ticker: str) -> list[str]:
    return list(original.yf.Ticker(ticker).options)


def analyze_with_spot_quote(
    ticker: str,
    *,
    event: str | None = None,
    expiry: str | None = None,
    threshold: float | None = None,
    skew_pct: float = 0.05,
    timing: str | None = None,
) -> dict[str, Any]:
    """Thread-safe wrapper copy of original.analyze using preferred spot quote."""
    tk = original.yf.Ticker(ticker)
    spot_quote = preferred_spot_quote(tk)
    spot = float(spot_quote["price"])
    expirations = list(tk.options)
    exp = choose_expiry_from_expirations(expirations, event=event, expiry=expiry, timing=timing)
    days = original.dte(exp)
    chain = tk.option_chain(exp)
    calls, puts = chain.calls, chain.puts
    if calls.empty or puts.empty:
        raise RuntimeError("Empty option chain for the chosen expiration.")

    atm_strike = float(original.nearest_row(calls, spot)["strike"])
    atm_call = original.mid_price(original.nearest_row(calls, atm_strike))
    atm_put = original.mid_price(original.nearest_row(puts, atm_strike))
    if atm_call is None or atm_put is None:
        raise RuntimeError("Could not price the ATM call/put (no quotes).")

    straddle = atm_call + atm_put
    em_raw = straddle / spot
    em_adj = 0.85 * straddle / spot

    atm_iv = original.iv_at(calls, atm_strike) or original.iv_at(puts, atm_strike)
    em_iv = (spot * atm_iv * math.sqrt(days / 365.0)) if (atm_iv and days > 0) else None

    put_k = spot * (1 - skew_pct)
    call_k = spot * (1 + skew_pct)
    put_iv = original.iv_at(puts, put_k)
    call_iv = original.iv_at(calls, call_k)
    skew = (put_iv - call_iv) if (put_iv and call_iv) else None
    prob_below = original.implied_cdf_below(puts, threshold) if threshold else None

    return {
        "ticker": ticker.upper(),
        "spot": spot,
        "expiry": exp,
        "days": days,
        "atm_strike": atm_strike,
        "atm_call": atm_call,
        "atm_put": atm_put,
        "straddle": straddle,
        "em_raw": em_raw,
        "em_adj": em_adj,
        "atm_iv": atm_iv,
        "em_iv": em_iv,
        "skew_pct": skew_pct,
        "put_k": put_k,
        "call_k": call_k,
        "put_iv": put_iv,
        "call_iv": call_iv,
        "skew": skew,
        "threshold": threshold,
        "prob_below": prob_below,
        "n_expirations": len(expirations),
        "expirations": expirations,
        "spot_source": spot_quote.get("source"),
        "spot_is_extended": spot_quote.get("is_extended"),
    }


def analyze(
    ticker: str,
    *,
    event: str | None = None,
    expiry: str | None = None,
    threshold: float | None = None,
    skew_pct: float = 0.05,
    timing: str | None = None,
) -> dict[str, Any]:
    """Run the original analysis function unchanged."""
    resolved_expiry = expiry
    if resolved_expiry is None and event:
        resolved_expiry = choose_expiry(ticker, event=event, timing=timing)

    if os.environ.get("OPTIONS_SWING_DISABLE_EXTENDED_HOURS") == "1":
        result = original.analyze(
            ticker,
            event=event,
            expiry=resolved_expiry,
            threshold=threshold,
            skew_pct=skew_pct,
        )
        result["spot_source"] = "regular/last"
        result["spot_is_extended"] = False
        return repair_iv_cross_check(ticker, result, event=event, timing=timing)

    result = analyze_with_spot_quote(
        ticker,
        event=event,
        expiry=resolved_expiry,
        threshold=threshold,
        skew_pct=skew_pct,
        timing=timing,
    )
    return repair_iv_cross_check(ticker, result, event=event, timing=timing)


def report(result: dict[str, Any]) -> str:
    return original.report(result)


def fmt(value: Any, *, pct: bool = False, dollar: bool = False) -> str:
    return original.fmt(value, pct=pct, dollar=dollar)
