#!/usr/bin/env python3
"""Actions invoked from the Übersicht widget UI."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Any

import event_move_core
import widget_data


ROOT = Path(__file__).resolve().parents[1]
DATA_CACHE = ROOT / "cache" / "data_cache.json"
CONFIG_PATH = ROOT / "config.json"


def emit(data: Any) -> int:
    print(json.dumps(data, separators=(",", ":"), sort_keys=True))
    return 0


def clear_data_cache() -> None:
    try:
        DATA_CACHE.unlink()
    except FileNotFoundError:
        pass


def read_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(config: dict[str, Any]) -> None:
    widget_data.write_json_atomic(CONFIG_PATH, config)


def normalized_display_payload(config: dict[str, Any]) -> dict[str, Any]:
    return widget_data.display_settings(config)


def upsert_watchlist(config: dict[str, Any], ticker: str, event: dict[str, Any], threshold: float | None) -> None:
    watchlist = config.setdefault("watchlist", [])
    ticker = ticker.upper()
    row = None
    for existing in watchlist:
        if isinstance(existing, dict) and str(existing.get("ticker", "")).upper() == ticker:
            row = existing
            break
    if row is None:
        row = {"ticker": ticker, "enabled": True}
        watchlist.append(row)
    row["ticker"] = ticker
    row["label"] = event.get("label") or "Catalyst"
    row["event"] = event["date"]
    row["event_source"] = event.get("source")
    row["event_confidence"] = event.get("confidence")
    row["event_url"] = event.get("url")
    row["timing"] = event.get("timing") or row.get("timing") or "unknown"
    row["enabled"] = True
    row["threshold"] = threshold


def validate_ticker_for_widget(ticker: str, event: str, timing: str | None = None) -> None:
    try:
        tk = event_move_core.original.yf.Ticker(ticker)
        quote = event_move_core.preferred_spot_quote(tk)
        if not quote.get("price"):
            raise RuntimeError("missing spot")
        expirations = list(tk.options)
        expiry = event_move_core.choose_expiry(ticker, event=event, timing=timing)
        chain = tk.option_chain(expiry)
        if chain.calls.empty or chain.puts.empty:
            raise RuntimeError("empty option chain")
    except Exception as exc:
        detail = str(exc)
        if detail:
            raise RuntimeError(f"{ticker} is not a usable option ticker: {detail}") from exc
        raise RuntimeError(f"{ticker} is not a usable option ticker.") from exc


def cmd_set(args: argparse.Namespace) -> int:
    ticker = args.ticker.strip().upper()
    if not ticker:
        return emit({"ok": False, "error": "Enter a ticker."})
    event = {
        "date": args.event,
        "label": args.label,
        "source": args.source,
        "confidence": args.confidence,
        "url": args.url,
        "timing": args.timing,
    }
    try:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            validate_ticker_for_widget(ticker, args.event, timing=args.timing)
        noise = captured.getvalue().strip()
        if noise:
            widget_data.log(f"{ticker} validation emitted: {noise}")
        config = read_config()
        upsert_watchlist(config, ticker, event, args.threshold)
        write_config(config)
        clear_data_cache()
        envelope = widget_data.build_envelope(config, force=True)
        return emit({"ok": True, "ticker": ticker, "data": envelope})
    except Exception as exc:
        return emit({"ok": False, "ticker": ticker, "error": str(exc) or exc.__class__.__name__})


def cmd_remove(args: argparse.Namespace) -> int:
    ticker = args.ticker.strip().upper()
    try:
        config = read_config()
        for row in config.get("watchlist", []):
            if isinstance(row, dict) and str(row.get("ticker", "")).upper() == ticker:
                row["enabled"] = False
        write_config(config)
        clear_data_cache()
        envelope = widget_data.build_envelope(config, force=True)
        return emit({"ok": True, "ticker": ticker, "data": envelope})
    except Exception as exc:
        return emit({"ok": False, "ticker": ticker, "error": str(exc) or exc.__class__.__name__})


def cmd_theme(args: argparse.Namespace) -> int:
    theme = widget_data.normalize_theme(args.theme)
    try:
        config = read_config()
        display = config.setdefault("display", {})
        if not isinstance(display, dict):
            display = {}
            config["display"] = display
        display["theme"] = theme
        write_config(config)
        return emit({"ok": True, "display": normalized_display_payload(config)})
    except Exception as exc:
        return emit({"ok": False, "error": str(exc) or exc.__class__.__name__})


def cmd_compact(args: argparse.Namespace) -> int:
    compact = widget_data.clean_bool(args.compact, True)
    try:
        config = read_config()
        display = config.setdefault("display", {})
        if not isinstance(display, dict):
            display = {}
            config["display"] = display
        display["compact"] = compact
        write_config(config)
        return emit({"ok": True, "display": normalized_display_payload(config)})
    except Exception as exc:
        return emit({"ok": False, "error": str(exc) or exc.__class__.__name__})


def cmd_layout(args: argparse.Namespace) -> int:
    try:
        config = read_config()
        display = config.setdefault("display", {})
        if not isinstance(display, dict):
            display = {}
            config["display"] = display

        if args.reset:
            display["position"] = dict(widget_data.DEFAULT_POSITION)
        else:
            current = widget_data.normalize_display_position(display)
            top = widget_data.css_px_number(current.get("top"), 185)
            left = widget_data.css_px_number(current.get("left"), 28)
            width = widget_data.css_px_number(current.get("width"), 420)
            height = widget_data.css_px_number(current.get("max_height"), 640) if current.get("max_height") else None
            if args.top is not None:
                top = args.top
            if args.left is not None:
                left = args.left
            if args.width is not None:
                width = args.width
            if args.height is not None:
                height = args.height
            top += args.dy or 0
            left += args.dx or 0
            width += args.dw or 0
            if args.dh:
                height = (height if height is not None else 640) + args.dh
            next_position = {
                "top": top,
                "left": left,
                "width": width,
            }
            if height is not None:
                next_position["max_height"] = height
            normalized = widget_data.normalize_display_position(
                next_position
            )
            display["position"] = normalized

        write_config(config)
        return emit({"ok": True, "display": normalized_display_payload(config)})
    except Exception as exc:
        return emit({"ok": False, "error": str(exc) or exc.__class__.__name__})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Widget UI action command")
    sub = parser.add_subparsers(dest="command", required=True)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("--ticker", required=True)
    set_cmd.add_argument("--event", required=True)
    set_cmd.add_argument("--label", required=True)
    set_cmd.add_argument("--source", default="manual")
    set_cmd.add_argument("--confidence", default="user")
    set_cmd.add_argument("--url")
    set_cmd.add_argument("--threshold", type=float)
    set_cmd.add_argument("--timing", choices=["unknown", "bmo", "amc", "intraday"], default="unknown")
    set_cmd.set_defaults(func=cmd_set)

    remove = sub.add_parser("remove")
    remove.add_argument("--ticker", required=True)
    remove.set_defaults(func=cmd_remove)

    theme = sub.add_parser("theme")
    theme.add_argument("--theme", required=True)
    theme.set_defaults(func=cmd_theme)

    compact = sub.add_parser("compact")
    compact.add_argument("--compact", required=True)
    compact.set_defaults(func=cmd_compact)

    layout = sub.add_parser("layout")
    layout.add_argument("--top", type=float)
    layout.add_argument("--left", type=float)
    layout.add_argument("--width", type=float)
    layout.add_argument("--height", type=float)
    layout.add_argument("--dx", type=float, default=0.0)
    layout.add_argument("--dy", type=float, default=0.0)
    layout.add_argument("--dw", type=float, default=0.0)
    layout.add_argument("--dh", type=float, default=0.0)
    layout.add_argument("--reset", action="store_true")
    layout.set_defaults(func=cmd_layout)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
