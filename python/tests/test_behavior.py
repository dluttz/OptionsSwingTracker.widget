from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import event_move_core as core
import widget_action
import widget_data


ROOT = Path(__file__).resolve().parents[2]


def chain(call_rows, put_rows):
    return SimpleNamespace(calls=pd.DataFrame(call_rows), puts=pd.DataFrame(put_rows))


def option_row(
    strike,
    *,
    bid=1.0,
    ask=1.2,
    last=1.1,
    iv=0.52,
    volume=10,
    open_interest=50,
):
    return {
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": last,
        "impliedVolatility": iv,
        "volume": volume,
        "openInterest": open_interest,
    }


def open_status(now=None):
    return {
        "is_open": True,
        "state": "open",
        "label": "market open",
        "holiday": None,
        "early_close": False,
        "early_close_reason": None,
        "eastern_time": "2026-06-22T09:45:00-04:00",
        "basis": "test",
    }


def base_result(**overrides):
    result = {
        "ticker": "TEST",
        "spot": 100.0,
        "expiry": "2099-01-16",
        "days": 30,
        "atm_strike": 100.0,
        "atm_call": 4.0,
        "atm_put": 5.0,
        "straddle": 9.0,
        "em_raw": 0.09,
        "em_adj": 0.0765,
        "atm_iv": None,
        "em_iv": None,
        "skew_pct": 0.05,
        "put_k": 95.0,
        "call_k": 105.0,
        "put_iv": 0.58,
        "call_iv": 0.52,
        "skew": 0.06,
        "threshold": None,
        "prob_below": None,
        "spot_source": "regular",
        "spot_is_extended": False,
    }
    result.update(overrides)
    return result


def normalized(result, item=None):
    item = item or {"ticker": result.get("ticker", "TEST"), "event": "2099-01-01"}
    return widget_data.normalize_result(
        item,
        result,
        key="test-key",
        fetched_at="2026-06-17T13:30:00+00:00",
        previous=None,
        min_valid_iv=0.05,
    )


@pytest.mark.parametrize(
    ("call_iv", "put_iv"),
    [
        (0.125, 0.1875),
        (0.25, 0.25),
        (0.52, 0.52),
    ],
)
def test_placeholder_and_equal_iv_are_rejected(monkeypatch, call_iv, put_iv):
    synthetic = chain(
        [option_row(100, iv=call_iv)],
        [option_row(100, iv=put_iv)],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check(
        "TEST",
        base_result(call_iv=call_iv, put_iv=put_iv, skew=put_iv - call_iv),
        event="2099-01-01",
    )
    row = normalized(repaired)

    assert row["atm_iv_valid"] is False
    assert row["atm_iv_unavailable_reason"] == "chain placeholder"
    assert row["iv_move_pct"] is None


def test_iv_from_indicative_legs_is_rejected(monkeypatch):
    synthetic = chain(
        [option_row(100, bid=0, ask=0, last=4.0, iv=0.52)],
        [option_row(100, bid=0, ask=0, last=5.0, iv=0.58)],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check("TEST", base_result(), event="2099-01-01")
    row = normalized(repaired)

    assert repaired["move_status"] == "indicative"
    assert row["atm_iv_valid"] is False
    assert row["atm_iv_unavailable_reason"] == "chain placeholder"
    assert row["iv_move_pct"] is None


def test_distinct_live_iv_is_valid(monkeypatch):
    synthetic = chain(
        [option_row(100, iv=0.52)],
        [option_row(100, iv=0.58)],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check("TEST", base_result(), event="2099-01-01")
    row = normalized(repaired)

    assert row["atm_iv_valid"] is True
    assert row["atm_iv_unavailable_reason"] is None
    assert row["atm_iv"] == pytest.approx(0.55)
    assert row["iv_move_pct"] is not None


def test_skew_is_hidden_for_placeholder_inputs(monkeypatch):
    synthetic = chain(
        [option_row(100, iv=0.125)],
        [option_row(100, iv=0.25)],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check(
        "TEST",
        base_result(call_iv=0.125, put_iv=0.25, skew=0.125),
        event="2099-01-01",
    )
    row = normalized(repaired)

    assert row["skew"] is None
    assert row["skew_label"] == "skew n/a"


def test_skew_survives_for_credible_live_inputs(monkeypatch):
    synthetic = chain(
        [option_row(100, iv=0.52)],
        [option_row(100, iv=0.58)],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check("TEST", base_result(), event="2099-01-01")
    row = normalized(repaired)

    assert row["skew"] == pytest.approx(0.06)
    assert row["skew_label"] == "downside skew"


def test_quote_basis_priority_live_mid():
    q = core.quote_quality(
        chain([option_row(100)], [option_row(100)]),
        100,
    )

    assert q["basis"] == "live_mid"
    assert q["move_status"] == "live"


def test_quote_basis_priority_prior_close_from_tmp_cache(tmp_path):
    cache_path = tmp_path / "regular_option_mids.json"
    result = base_result(
        ticker="LMT",
        expiry="2099-01-16",
        atm_strike=540.0,
        spot=536.0,
        quote_basis="last_trade",
        move_status="indicative",
        spot_is_extended=True,
        spot_source="pre-market",
    )
    mid_cache = {}
    for side, mid in (("call", 6.1), ("put", 7.2)):
        key = widget_data.option_mid_cache_key("LMT", "2099-01-16", 540.0, side)
        mid_cache[key] = {"mid": mid, "stored_at": "2026-06-17T14:00:00+00:00"}
    cache_path.write_text(json.dumps(mid_cache), encoding="utf-8")

    loaded = widget_data.read_json(cache_path, {})
    assert widget_data.apply_regular_mid_cache_to_result(result, loaded) is True

    assert result["quote_basis"] == "prior_close_mid"
    assert result["move_status"] == "prior_close"
    assert result["straddle"] == pytest.approx(13.3)
    assert "options prior close" in result["basis_note"]


def test_quote_basis_priority_last_trade_and_no_quote():
    last_q = core.quote_quality(
        chain(
            [option_row(100, bid=0, ask=0, last=4.0)],
            [option_row(100, bid=0, ask=0, last=5.0)],
        ),
        100,
    )
    no_q = core.quote_quality(
        chain(
            [option_row(100, bid=0, ask=0, last=0, volume=0, open_interest=0)],
            [option_row(100, bid=0, ask=0, last=0, volume=0, open_interest=0)],
        ),
        100,
    )

    assert last_q["basis"] == "last_trade"
    assert last_q["move_status"] == "indicative"
    assert no_q["basis"] == "unpriced"
    assert no_q["move_status"] == "stale"
    assert no_q["legs"]["call"].get("mid") is None


def test_market_status_holidays_and_early_close():
    juneteenth = core.market_status(datetime(2026, 6, 19, 10, 0, tzinfo=core.EASTERN))
    observed_independence = core.market_status(datetime(2026, 7, 3, 10, 0, tzinfo=core.EASTERN))
    weekday = core.market_status(datetime(2026, 6, 22, 9, 45, tzinfo=core.EASTERN))
    black_friday_open = core.market_status(datetime(2026, 11, 27, 12, 30, tzinfo=core.EASTERN))
    black_friday_after = core.market_status(datetime(2026, 11, 27, 13, 30, tzinfo=core.EASTERN))

    assert juneteenth["state"] == "closed"
    assert juneteenth["label"] == "market holiday"
    assert observed_independence["state"] == "closed"
    assert observed_independence["label"] == "market holiday"
    assert weekday["state"] == "open"
    assert weekday["is_open"] is True
    assert black_friday_open["early_close"] is True
    assert black_friday_open["is_open"] is True
    assert "early close 1 PM" in black_friday_open["label"]
    assert black_friday_after["state"] == "afterhours"
    assert black_friday_after["is_open"] is False


def test_liquidity_aware_atm_selection_substitutes_empty_nearest(monkeypatch):
    synthetic = chain(
        [
            option_row(100, bid=0, ask=0, last=0, volume=0, open_interest=0),
            option_row(105, bid=1.0, ask=1.2, last=1.1, volume=10, open_interest=50),
        ],
        [
            option_row(100, bid=0, ask=0, last=0, volume=0, open_interest=0),
            option_row(105, bid=2.0, ask=2.4, last=2.2, volume=10, open_interest=50),
        ],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check(
        "TEST",
        base_result(spot=101.0, atm_strike=100.0, atm_call=0.0, atm_put=0.0, straddle=0.0),
        event="2099-01-01",
    )

    assert repaired["atm_selection"] == "nearest_liquid"
    assert "nearest liquid strike $105" in repaired["atm_selection_note"]
    assert "nearest $100 had no quotes" in repaired["atm_selection_note"]
    assert repaired["quote_basis"] == "live_mid"
    assert repaired["atm_strike"] == 105.0


def test_liquidity_aware_atm_selection_keeps_liquid_nearest(monkeypatch):
    synthetic = chain(
        [
            option_row(100, bid=1.0, ask=1.2, last=1.1, volume=0, open_interest=0),
            option_row(105, bid=2.0, ask=2.2, last=2.1, volume=10, open_interest=50),
        ],
        [
            option_row(100, bid=1.4, ask=1.6, last=1.5, volume=0, open_interest=0),
            option_row(105, bid=3.0, ask=3.2, last=3.1, volume=10, open_interest=50),
        ],
    )
    monkeypatch.setattr(core, "_fetch_chain", lambda ticker, expiry: synthetic)
    monkeypatch.setattr(core, "market_status", open_status)

    repaired = core.repair_iv_cross_check(
        "TEST",
        base_result(spot=101.0, atm_strike=100.0),
        event="2099-01-01",
    )

    assert repaired["atm_selection"] == "nearest"
    assert repaired.get("atm_selection_note") is None
    assert repaired["quote_basis"] == "live_mid"
    assert repaired["atm_strike"] == 100.0


def test_risk_neutral_probability_unreliable_for_sparse_chain():
    sparse = chain(
        [option_row(100), option_row(105)],
        [option_row(90), option_row(100)],
    )
    prob = core.raw_implied_cdf_below(sparse, 95)
    result = base_result(
        threshold=95.0,
        prob_below=prob["clamped"],
        prob_below_raw=prob["raw"],
        prob_below_clamped=prob["clamped"],
        prob_warning=prob["warning"],
        quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": []},
        quote_basis="live_mid",
        move_status="live",
    )
    row = normalized(result, {"ticker": "TEST", "event": "2099-01-01", "threshold": 95.0})

    assert prob["warning"] == "too few put strikes"
    assert row["prob_reliable"] is False
    assert row["prob_below"] is None
    assert "odds unreliable" in row["prob_unreliable_reason"]


def test_config_keeps_lmt_enabled():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    lmt = next(row for row in config["watchlist"] if row.get("ticker") == "LMT")

    assert lmt["enabled"] is True


def test_negative_event_gap_is_invalid(monkeypatch):
    monkeypatch.setattr(core, "eastern_market_date", lambda: date(2026, 6, 17))

    gap = core.event_expiry_gap("2026-06-30", "2026-06-20")

    assert gap["days"] == -10
    assert gap["label"] == "exp before event"
    assert gap["severity"] == "invalid"
    assert "does not cover the catalyst" in gap["warning"]
    assert gap["event_passed"] is False


def test_past_event_sets_row_flag(monkeypatch):
    monkeypatch.setattr(core, "eastern_market_date", lambda: date(2026, 6, 17))
    gap = core.event_expiry_gap("2026-06-16", "2026-06-18")
    result = base_result(
        event_gap_days=gap["days"],
        event_gap_label=gap["label"],
        event_gap_severity=gap["severity"],
        event_gap_warning=gap["warning"],
        event_passed=gap["event_passed"],
        quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": []},
        quote_basis="live_mid",
        move_status="live",
    )
    row = normalized(result, {"ticker": "TEST", "event": "2026-06-16"})

    assert gap["event_passed"] is True
    assert row["event_passed"] is True


def test_event_today_is_not_past(monkeypatch):
    monkeypatch.setattr(core, "eastern_market_date", lambda: date(2026, 6, 17))

    gap = core.event_expiry_gap("2026-06-17", "2026-06-17")

    assert gap["event_passed"] is False


def test_choose_expiry_errors_when_event_after_last_listed_expiry(monkeypatch):
    class FakeTicker:
        options = ["2026-06-19", "2026-06-26"]

    monkeypatch.setattr(core.original.yf, "Ticker", lambda ticker: FakeTicker())

    with pytest.raises(RuntimeError, match="No listed expiry on or after the event date"):
        core.choose_expiry("TEST", event="2026-07-10")


def test_concurrent_build_preserves_order_and_isolates_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_data, "DATA_CACHE", tmp_path / "data_cache.json")
    monkeypatch.setattr(widget_data, "LAST_GOOD", tmp_path / "last_good.json")
    monkeypatch.setattr(widget_data, "REGULAR_MIDS", tmp_path / "regular_option_mids.json")
    monkeypatch.setattr(widget_data.event_move_core, "market_status", open_status)

    def fake_analyze(ticker, **kwargs):
        if ticker == "SLOW":
            time.sleep(0.2)
        return base_result(
            ticker=ticker,
            quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": [], "legs": {}},
            quote_basis="live_mid",
            move_status="live",
        )

    monkeypatch.setattr(widget_data.event_move_core, "analyze", fake_analyze)

    config = {
        "display": {"cache_ttl_seconds": 0},
        "defaults": {"fetch_timeout_seconds": 0.05, "max_workers": 3},
        "watchlist": [
            {"ticker": "FAST1", "event": "2099-01-01", "enabled": True},
            {"ticker": "SLOW", "event": "2099-01-01", "enabled": True},
            {"ticker": "FAST2", "event": "2099-01-01", "enabled": True},
        ],
    }

    envelope = widget_data.build_envelope(config, force=True)
    rows = envelope["rows"]

    assert [row["ticker"] for row in rows] == ["FAST1", "SLOW", "FAST2"]
    assert rows[0]["ok"] is True
    assert rows[1]["ok"] is False
    assert "timed out" in rows[1]["error"]
    assert rows[2]["ok"] is True


def test_regular_mid_cache_pruning_removes_past_expiries():
    cache = {
        "LMT|2026-06-16|540.0000|call": {
            "ticker": "LMT",
            "expiry": "2026-06-16",
            "strike": 540,
            "side": "call",
            "mid": 1.0,
            "stored_at": "2026-06-15T14:00:00+00:00",
        },
        "LMT|2026-06-17|540.0000|put": {
            "ticker": "LMT",
            "expiry": "2026-06-17",
            "strike": 540,
            "side": "put",
            "mid": 2.0,
            "stored_at": "2026-06-16T14:00:00+00:00",
        },
        "LMT|2026-06-18|540.0000|call": {
            "ticker": "LMT",
            "expiry": "2026-06-18",
            "strike": 540,
            "side": "call",
            "mid": 3.0,
            "stored_at": "2026-06-17T14:00:00+00:00",
        },
    }

    changed = widget_data.prune_regular_mid_cache(cache, today=date(2026, 6, 17))

    assert changed is True
    assert list(cache.keys()) == [
        "LMT|2026-06-17|540.0000|put",
        "LMT|2026-06-18|540.0000|call",
    ]


def test_data_cache_ttl_short_circuit_avoids_refetch(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_data, "DATA_CACHE", tmp_path / "data_cache.json")
    monkeypatch.setattr(widget_data, "LAST_GOOD", tmp_path / "last_good.json")
    monkeypatch.setattr(widget_data, "REGULAR_MIDS", tmp_path / "regular_option_mids.json")
    monkeypatch.setattr(widget_data.event_move_core, "market_status", open_status)

    calls = {"count": 0}

    def fake_analyze(ticker, **kwargs):
        calls["count"] += 1
        return base_result(
            ticker=ticker,
            quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": [], "legs": {}},
            quote_basis="live_mid",
            move_status="live",
        )

    monkeypatch.setattr(widget_data.event_move_core, "analyze", fake_analyze)
    config = {
        "display": {"cache_ttl_seconds": 300},
        "defaults": {"fetch_timeout_seconds": 1, "max_workers": 2},
        "watchlist": [{"ticker": "FAST1", "event": "2099-01-01", "enabled": True}],
    }

    first = widget_data.build_envelope(config, force=True)
    second = widget_data.build_envelope(config, force=False)

    assert first["cache_status"] == "refresh"
    assert second["cache_status"] == "hit"
    assert calls["count"] == 1


def test_malformed_enabled_watchlist_row_yields_error_without_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_data, "DATA_CACHE", tmp_path / "data_cache.json")
    monkeypatch.setattr(widget_data, "LAST_GOOD", tmp_path / "last_good.json")
    monkeypatch.setattr(widget_data, "REGULAR_MIDS", tmp_path / "regular_option_mids.json")
    monkeypatch.setattr(widget_data.event_move_core, "market_status", open_status)

    def fake_analyze(ticker, **kwargs):
        return base_result(
            ticker=ticker,
            quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": [], "legs": {}},
            quote_basis="live_mid",
            move_status="live",
        )

    monkeypatch.setattr(widget_data.event_move_core, "analyze", fake_analyze)
    config = {
        "display": {"cache_ttl_seconds": 0},
        "defaults": {"fetch_timeout_seconds": 1, "max_workers": 2},
        "watchlist": [
            {"ticker": "", "event": "not-a-date", "enabled": True},
            {"ticker": "GOOD", "event": "2099-01-01", "enabled": True},
        ],
    }

    envelope = widget_data.build_envelope(config, force=True)
    rows = envelope["rows"]

    assert rows[0]["ok"] is False
    assert "invalid watchlist entry" in rows[0]["error"]
    assert "ticker must be a non-empty string" in rows[0]["error"]
    assert rows[1]["ok"] is True
    assert rows[1]["ticker"] == "GOOD"


def test_duplicate_watchlist_keys_are_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(widget_data, "DATA_CACHE", tmp_path / "data_cache.json")
    monkeypatch.setattr(widget_data, "LAST_GOOD", tmp_path / "last_good.json")
    monkeypatch.setattr(widget_data, "REGULAR_MIDS", tmp_path / "regular_option_mids.json")
    monkeypatch.setattr(widget_data.event_move_core, "market_status", open_status)

    def fake_analyze(ticker, **kwargs):
        return base_result(
            ticker=ticker,
            quote_quality={"basis": "live_mid", "move_status": "live", "confidence": "ok", "warnings": [], "legs": {}},
            quote_basis="live_mid",
            move_status="live",
        )

    monkeypatch.setattr(widget_data.event_move_core, "analyze", fake_analyze)
    config = {
        "display": {"cache_ttl_seconds": 0},
        "defaults": {"fetch_timeout_seconds": 1, "max_workers": 2},
        "watchlist": [
            {"ticker": "DUP", "event": "2099-01-01", "threshold": 100, "enabled": True},
            {"ticker": "dup", "event": "2099-01-01", "threshold": 100.0, "enabled": True},
        ],
    }

    envelope = widget_data.build_envelope(config, force=True)
    rows = envelope["rows"]

    assert rows[0]["ok"] is True
    assert rows[0]["ticker"] == "DUP"
    assert rows[1]["ok"] is False
    assert "duplicate watchlist key" in rows[1]["error"]
    assert envelope["summary"]["errors"] == 1


def test_doctor_reports_bad_config_row(tmp_path):
    bad_config = tmp_path / "config.json"
    bad_config.write_text(
        json.dumps(
            {
                "watchlist": [
                    {"ticker": "GOOD", "event": "2099-01-01", "enabled": True},
                    {"ticker": "BAD", "event": "2099/01/01", "threshold": "nope", "enabled": True},
                ]
            }
        ),
        encoding="utf-8",
    )

    ok, lines = widget_data.doctor_checks(
        config_path=bad_config,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        symlink_path=None,
        skip_yahoo=True,
    )
    report = "\n".join(lines)

    assert ok is False
    assert "FAIL config" in report
    assert "row 2" in report
    assert "event must be YYYY-MM-DD" in report
    assert "threshold must be numeric or null" in report
    assert "RESULT FAIL" in report


def test_widget_action_theme_command_writes_display_theme(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"display": {"title": "Test"}, "watchlist": []}), encoding="utf-8")
    monkeypatch.setattr(widget_action, "CONFIG_PATH", config_path)

    rc = widget_action.main(["theme", "--theme", "light"])
    payload = json.loads(capsys.readouterr().out)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["ok"] is True
    assert payload["display"]["theme"] == "light"
    assert config["display"]["theme"] == "light"


def test_display_theme_validation_accepts_valid_and_falls_back_invalid():
    valid = widget_data.display_settings({"display": {"theme": "midnight", "compact": False}})
    invalid = widget_data.display_settings({"display": {"theme": "neon", "compact": True}})

    assert valid["theme"] == "midnight"
    assert valid["compact"] is False
    assert invalid["theme"] == "graphite"
    assert invalid["compact"] is True


def test_widget_action_compact_round_trips_through_config(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"display": {"theme": "mono"}, "watchlist": []}), encoding="utf-8")
    monkeypatch.setattr(widget_action, "CONFIG_PATH", config_path)

    rc = widget_action.main(["compact", "--compact", "false"])
    payload = json.loads(capsys.readouterr().out)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["ok"] is True
    assert payload["display"]["compact"] is False
    assert widget_data.display_settings(config)["compact"] is False


def test_display_position_validation_normalizes_and_clamps():
    settings = widget_data.display_settings(
        {
            "display": {
                "position": {
                    "top": "-50px",
                    "left": "77.4px",
                    "width": "9999px",
                    "max_height": "9999px",
                }
            }
        }
    )

    assert settings["position"]["top"] == "0px"
    assert settings["position"]["left"] == "77px"
    assert settings["position"]["width"] == f"{widget_data.MAX_WIDGET_WIDTH}px"
    assert settings["position"]["max_height"] == f"{widget_data.MAX_WIDGET_HEIGHT}px"


def test_widget_action_layout_command_writes_display_position(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"display": {"position": {"top": "100px", "left": "30px", "width": "420px"}}, "watchlist": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(widget_action, "CONFIG_PATH", config_path)

    rc = widget_action.main(["layout", "--dx", "25", "--dy", "-10", "--dw", "-40"])
    payload = json.loads(capsys.readouterr().out)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["ok"] is True
    assert payload["display"]["position"] == {"left": "55px", "top": "90px", "width": "380px"}
    assert config["display"]["position"] == {"left": "55px", "top": "90px", "width": "380px"}


def test_widget_action_layout_height_round_trips(monkeypatch, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"display": {"position": {"top": "100px", "left": "30px", "width": "420px"}}, "watchlist": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(widget_action, "CONFIG_PATH", config_path)

    rc = widget_action.main(["layout", "--height", "560", "--dh", "-80"])
    payload = json.loads(capsys.readouterr().out)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["ok"] is True
    assert payload["display"]["position"]["max_height"] == "480px"
    assert config["display"]["position"]["max_height"] == "480px"
