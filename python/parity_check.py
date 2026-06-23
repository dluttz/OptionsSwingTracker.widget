#!/usr/bin/env python3
"""Parity check between the preserved original script and the widget wrapper."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import event_move_core


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference" / "event_move_original.py"


PRICE_FIELDS = [
    "spot",
    "atm_strike",
    "atm_call",
    "atm_put",
    "straddle",
]
PCT_FIELDS = [
    "em_raw",
    "em_adj",
    "put_iv",
    "call_iv",
    "skew",
    "prob_below",
]


def load_reference():
    spec = importlib.util.spec_from_file_location("parity_reference_event_move", REFERENCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {REFERENCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def next_monthly_expiry(ticker: str, ref_module: Any) -> str:
    expirations = list(ref_module.yf.Ticker(ticker).options)
    today = event_move_core.eastern_market_date()
    parsed = [(datetime.strptime(e, "%Y-%m-%d").date(), e) for e in expirations]
    for exp_date, exp in parsed:
        if exp_date >= today and exp_date.weekday() == 4 and 15 <= exp_date.day <= 21:
            return exp
    if parsed:
        return parsed[0][1]
    raise RuntimeError(f"No expirations available for {ticker}")


def close_enough(field: str, a: Any, b: Any) -> tuple[bool, str]:
    if a is None and b is None:
        return True, ""
    if a is None or b is None:
        return False, f"{field}: one value is None ({a!r} vs {b!r})"
    a_f = float(a)
    b_f = float(b)
    diff = abs(a_f - b_f)
    if field in PCT_FIELDS:
        tolerance = 0.025
    else:
        tolerance = max(0.25, abs(a_f) * 0.03)
    if diff <= tolerance:
        return True, ""
    return False, f"{field}: {a_f:.6f} vs {b_f:.6f}, diff {diff:.6f} > {tolerance:.6f}"


def run_reference_cli(
    ticker: str,
    *,
    event: str,
    expiry: str,
    threshold: float | None,
    skew_pct: float,
) -> None:
    cmd = [
        sys.executable,
        str(REFERENCE),
        ticker,
        "--event",
        event,
        "--expiry",
        expiry,
        "--skew-pct",
        str(skew_pct),
    ]
    if threshold is not None:
        cmd.extend(["--threshold", str(threshold)])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run original-vs-widget parity check")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--event")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--skew-pct", type=float, default=0.05)
    parser.add_argument("--verbose", action="store_true", help="Print ticker/event/expiry diagnostics")
    parser.add_argument("--json", action="store_true", help="Print diagnostic JSON before PASS/FAIL")
    args = parser.parse_args(argv)

    diagnostics: dict[str, Any] = {
        "ticker": args.ticker.upper(),
        "event": args.event,
        "threshold": args.threshold,
        "passed": False,
        "failures": [],
    }

    try:
        ref = load_reference()
        event = args.event or next_monthly_expiry(args.ticker, ref)
        expiry = ref.choose_expiry(list(ref.yf.Ticker(args.ticker).options), event=event, expiry=None)
        diagnostics["event"] = event
        diagnostics["pinned_expiry"] = expiry

        run_reference_cli(
            args.ticker,
            event=event,
            expiry=expiry,
            threshold=args.threshold,
            skew_pct=args.skew_pct,
        )

        reference = ref.analyze(
            args.ticker,
            event=event,
            expiry=expiry,
            threshold=args.threshold,
            skew_pct=args.skew_pct,
        )
        previous_disable_extended = os.environ.get("OPTIONS_SWING_DISABLE_EXTENDED_HOURS")
        os.environ["OPTIONS_SWING_DISABLE_EXTENDED_HOURS"] = "1"
        try:
            wrapped = event_move_core.analyze(
                args.ticker,
                event=event,
                expiry=expiry,
                threshold=args.threshold,
                skew_pct=args.skew_pct,
            )
        finally:
            if previous_disable_extended is None:
                os.environ.pop("OPTIONS_SWING_DISABLE_EXTENDED_HOURS", None)
            else:
                os.environ["OPTIONS_SWING_DISABLE_EXTENDED_HOURS"] = previous_disable_extended

        diagnostics["reference_days"] = reference.get("days")
        diagnostics["wrapped_days"] = wrapped.get("days")

        for field in ["ticker", "expiry"]:
            if reference.get(field) != wrapped.get(field):
                diagnostics["failures"].append(
                    f"{field}: {reference.get(field)!r} vs {wrapped.get(field)!r}"
                )
        for field in PRICE_FIELDS + PCT_FIELDS:
            ok, message = close_enough(field, reference.get(field), wrapped.get(field))
            if not ok:
                diagnostics["failures"].append(message)

        atm_iv = wrapped.get("atm_iv")
        spot = wrapped.get("spot")
        days = wrapped.get("days")
        em_iv = wrapped.get("em_iv")
        if atm_iv is not None and spot is not None and days is not None and days > 0:
            expected_em_iv = spot * atm_iv * math.sqrt(days / 365.0)
            ok, message = close_enough("em_iv_formula", expected_em_iv, em_iv)
            if not ok:
                diagnostics["failures"].append(message)
            if atm_iv <= 0.01:
                diagnostics["failures"].append(f"atm_iv repair failed: {atm_iv!r}")

        diagnostics["passed"] = not diagnostics["failures"]
    except Exception as exc:
        diagnostics["failures"].append(str(exc) or exc.__class__.__name__)

    if args.json:
        print(json.dumps(diagnostics, indent=2, sort_keys=True))
    elif args.verbose:
        print(f"ticker={diagnostics['ticker']} event={diagnostics.get('event')} pinned_expiry={diagnostics.get('pinned_expiry')}")
        if diagnostics["failures"]:
            for failure in diagnostics["failures"]:
                print(f"FAIL_DETAIL {failure}")

    print("PASS" if diagnostics["passed"] else "FAIL")
    return 0 if diagnostics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
