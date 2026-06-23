#!/usr/bin/env python3
"""
event_move.py  —  Options-implied expected move & binary-event calculator
=========================================================================

Auto-fetches a live option chain (via yfinance, no API key needed) and computes:

  • Expected move from the ATM straddle  (raw and 0.85-adjusted)
  • Cross-check via the IV formula:  spot * IV * sqrt(DTE/365)
  • Upper/lower 1-sigma bands and long-straddle breakevens
  • BINARY-EVENT analysis:
        - Volatility skew (are puts or calls richer? which way is the market leaning)
        - Market-implied (risk-neutral) probability the stock finishes
          below / above any threshold you choose  — e.g. a merger break level
          or a court-ruling downside target.

USAGE
-----
  Interactive:        python event_move.py
  One-liner:          python event_move.py ORCL
  Pick the expiry by event date (uses first expiration ON/AFTER the date):
                      python event_move.py ORCL --event 2026-06-10
  Pick an exact expiration:
                      python event_move.py ORCL --expiry 2026-06-12
  Binary threshold (implied prob of finishing below 180):
                      python event_move.py ORCL --event 2026-06-10 --threshold 180

NOTES
-----
  • Data is delayed (typically last close / ~15 min). It's a gut-check tool,
    not an execution feed.
  • "Implied probability" is RISK-NEUTRAL probability backed out of option
    prices. It bakes in risk premia, so it is the market's *priced* odds, not
    a pure real-world forecast. Still the standard way pros read binary events.
  • Not investment advice.
"""

import argparse
import math
import sys
from datetime import datetime, date

try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing dependency. Run:  pip install yfinance")


# ----------------------------- helpers ------------------------------------ #
def mid_price(row):
    """Best available price for an option row: mid of bid/ask, else lastPrice."""
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if last and last > 0:
        return float(last)
    return None


def nearest_row(df, target_strike):
    """Row whose strike is closest to target_strike."""
    idx = (df["strike"] - target_strike).abs().idxmin()
    return df.loc[idx]


def fmt(x, pct=False, dollar=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    if pct:
        return f"{x*100:.2f}%"
    if dollar:
        return f"${x:,.2f}"
    return f"{x:,.2f}"


def rule(title=""):
    line = "=" * 64
    if title:
        pad = (64 - len(title) - 2) // 2
        return f"{'='*pad} {title} {'='*pad}"
    return line


# ----------------------------- core --------------------------------------- #
def get_spot(tk):
    try:
        fi = tk.fast_info
        for key in ("lastPrice", "last_price"):
            v = fi.get(key) if hasattr(fi, "get") else getattr(fi, key, None)
            if v:
                return float(v)
    except Exception:
        pass
    hist = tk.history(period="1d")
    if len(hist):
        return float(hist["Close"].iloc[-1])
    raise RuntimeError("Could not fetch spot price.")


def choose_expiry(expirations, event=None, expiry=None):
    if not expirations:
        raise RuntimeError("No option expirations available for this ticker.")
    if expiry:
        if expiry in expirations:
            return expiry
        raise RuntimeError(f"{expiry} not in available expirations: {expirations[:8]}...")
    if event:
        ev = datetime.strptime(event, "%Y-%m-%d").date()
        after = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() >= ev]
        if not after:
            raise RuntimeError(f"No expiration on/after {event}. Latest is {expirations[-1]}.")
        return after[0]   # first expiration that brackets the event
    return expirations[0]  # default: front expiration


def dte(expiry):
    d = datetime.strptime(expiry, "%Y-%m-%d").date()
    return max((d - date.today()).days, 0)


def implied_cdf_below(puts, threshold):
    """
    Risk-neutral P(S_T < threshold) via the slope of put price wrt strike:
        P(S_T < K) ≈ d(Put)/dK   (digital put = derivative of put price)
    Estimated with a central difference across the strikes bracketing threshold.
    """
    p = puts.dropna(subset=["strike"]).copy()
    p["mid"] = p.apply(mid_price, axis=1)
    p = p.dropna(subset=["mid"]).sort_values("strike").reset_index(drop=True)
    if len(p) < 3:
        return None
    strikes = p["strike"].values
    if threshold <= strikes[0] or threshold >= strikes[-1]:
        return None
    # find bracketing index
    hi = next(i for i, k in enumerate(strikes) if k >= threshold)
    lo = hi - 1
    # widen by one strike each side for a smoother central difference
    lo2 = max(lo - 1, 0)
    hi2 = min(hi + 1, len(strikes) - 1)
    dPut = p["mid"].values[hi2] - p["mid"].values[lo2]
    dK = strikes[hi2] - strikes[lo2]
    if dK <= 0:
        return None
    prob = dPut / dK
    return min(max(prob, 0.0), 1.0)


def iv_at(df, strike):
    try:
        row = nearest_row(df, strike)
        iv = row.get("impliedVolatility")
        return float(iv) if iv and iv > 0 else None
    except Exception:
        return None


def analyze(ticker, event=None, expiry=None, threshold=None, skew_pct=0.05):
    tk = yf.Ticker(ticker)
    spot = get_spot(tk)
    expirations = list(tk.options)
    exp = choose_expiry(expirations, event, expiry)
    days = dte(exp)
    chain = tk.option_chain(exp)
    calls, puts = chain.calls, chain.puts
    if calls.empty or puts.empty:
        raise RuntimeError("Empty option chain for the chosen expiration.")

    # ATM strike = strike closest to spot (use the call grid)
    atm_strike = float(nearest_row(calls, spot)["strike"])
    atm_call = mid_price(nearest_row(calls, atm_strike))
    atm_put = mid_price(nearest_row(puts, atm_strike))
    if atm_call is None or atm_put is None:
        raise RuntimeError("Could not price the ATM call/put (no quotes).")

    straddle = atm_call + atm_put
    em_raw = straddle / spot
    em_adj = 0.85 * straddle / spot

    atm_iv = iv_at(calls, atm_strike) or iv_at(puts, atm_strike)
    em_iv = (spot * atm_iv * math.sqrt(days / 365.0)) if (atm_iv and days > 0) else None

    # ---- skew: compare IV of an OTM put vs OTM call equidistant from spot ----
    put_k = spot * (1 - skew_pct)
    call_k = spot * (1 + skew_pct)
    put_iv = iv_at(puts, put_k)
    call_iv = iv_at(calls, call_k)
    skew = (put_iv - call_iv) if (put_iv and call_iv) else None

    # ---- binary threshold probability ----
    prob_below = implied_cdf_below(puts, threshold) if threshold else None

    return {
        "ticker": ticker.upper(), "spot": spot, "expiry": exp, "days": days,
        "atm_strike": atm_strike, "atm_call": atm_call, "atm_put": atm_put,
        "straddle": straddle, "em_raw": em_raw, "em_adj": em_adj,
        "atm_iv": atm_iv, "em_iv": em_iv,
        "skew_pct": skew_pct, "put_k": put_k, "call_k": call_k,
        "put_iv": put_iv, "call_iv": call_iv, "skew": skew,
        "threshold": threshold, "prob_below": prob_below,
        "n_expirations": len(expirations), "expirations": expirations,
    }


# ----------------------------- report ------------------------------------- #
def report(r):
    out = []
    out.append(rule(f"{r['ticker']}  EXPECTED-MOVE REPORT"))
    out.append(f"Spot price          {fmt(r['spot'], dollar=True)}")
    out.append(f"Expiration used     {r['expiry']}   ({r['days']} days out)")
    out.append(f"ATM strike          {fmt(r['atm_strike'], dollar=True)}")
    out.append(f"  ATM call          {fmt(r['atm_call'], dollar=True)}")
    out.append(f"  ATM put           {fmt(r['atm_put'], dollar=True)}")
    out.append(f"  Straddle          {fmt(r['straddle'], dollar=True)}")
    out.append("")
    out.append(rule("EXPECTED MOVE"))
    out.append(f"Straddle method (raw)      ±{fmt(r['em_raw'], pct=True)}"
               f"   →  {fmt(r['spot']*(1-r['em_raw']), dollar=True)}  to  "
               f"{fmt(r['spot']*(1+r['em_raw']), dollar=True)}")
    out.append(f"Straddle x 0.85 (refined)  ±{fmt(r['em_adj'], pct=True)}"
               f"   →  {fmt(r['spot']*(1-r['em_adj']), dollar=True)}  to  "
               f"{fmt(r['spot']*(1+r['em_adj']), dollar=True)}")
    if r["em_iv"] is not None:
        em_iv_pct = r["em_iv"] / r["spot"]
        out.append(f"IV-formula cross-check     ±{fmt(em_iv_pct, pct=True)}"
                   f"   (ATM IV {fmt(r['atm_iv'], pct=True)}, "
                   f"spot×IV×√(dte/365))")
    out.append("")
    out.append(f"Long-straddle breakevens   {fmt(r['spot']-r['straddle'], dollar=True)}"
               f"  /  {fmt(r['spot']+r['straddle'], dollar=True)}")
    out.append(f"  (a long straddle only profits if the move EXCEEDS the priced-in move)")
    out.append("")
    out.append(rule("BINARY-EVENT ANALYSIS"))
    # directional lean
    lean = r["atm_call"] - r["atm_put"]
    if abs(lean) < 0.01 * r["spot"] * 0.05:
        lean_txt = "roughly balanced"
    elif lean > 0:
        lean_txt = "call richer than put (slight upside lean / rate & skew effects)"
    else:
        lean_txt = "put richer than call (downside lean — market paying up for protection)"
    out.append(f"ATM call vs put     {fmt(lean, dollar=True)}  →  {lean_txt}")
    # skew
    if r["skew"] is not None:
        if r["skew"] > 0.02:
            sk = "DOWNSIDE skew — OTM puts pricier than calls; market fears a drop."
        elif r["skew"] < -0.02:
            sk = "UPSIDE skew — OTM calls pricier than puts; market leans to a pop."
        else:
            sk = "near-symmetric — little directional fear priced in."
        out.append(f"Vol skew (±{int(r['skew_pct']*100)}% OTM)  "
                   f"put IV {fmt(r['put_iv'], pct=True)} vs call IV {fmt(r['call_iv'], pct=True)}"
                   f"  →  skew {fmt(r['skew'], pct=True)}")
        out.append(f"                    {sk}")
    else:
        out.append("Vol skew            n/a (missing IV at the OTM strikes)")
    # binary probability
    if r["threshold"] is not None:
        if r["prob_below"] is not None:
            pb = r["prob_below"]
            out.append("")
            out.append(f"Implied P(finish BELOW {fmt(r['threshold'], dollar=True)})   "
                       f"≈ {fmt(pb, pct=True)}")
            out.append(f"Implied P(finish ABOVE {fmt(r['threshold'], dollar=True)})   "
                       f"≈ {fmt(1-pb, pct=True)}")
            out.append("  (risk-neutral, from the slope of put prices across strikes;"
                       " reads as the market's *priced* odds.)")
        else:
            out.append("")
            out.append(f"Implied P(below {fmt(r['threshold'], dollar=True)})  n/a — "
                       f"threshold outside the quoted strike range, or too few quotes.")
    out.append("")
    out.append(rule())
    out.append("Data delayed. Risk-neutral probs include risk premia. Not investment advice.")
    return "\n".join(out)


# ----------------------------- cli ---------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Options-implied expected move & binary-event calculator")
    ap.add_argument("ticker", nargs="?", help="Stock ticker, e.g. ORCL")
    ap.add_argument("--event", help="Event date YYYY-MM-DD; uses first expiration on/after it")
    ap.add_argument("--expiry", help="Exact expiration date YYYY-MM-DD")
    ap.add_argument("--threshold", type=float, help="Price level for binary implied-probability read")
    ap.add_argument("--skew-pct", type=float, default=0.05, help="OTM distance for skew (default 0.05 = 5%%)")
    ap.add_argument("--list", action="store_true", help="Just list available expirations and exit")
    args = ap.parse_args()

    ticker = args.ticker or input("Ticker: ").strip().upper()
    if not ticker:
        sys.exit("No ticker given.")

    if args.list:
        exps = list(yf.Ticker(ticker).options)
        print(f"{ticker} expirations ({len(exps)}):")
        for e in exps:
            print(f"  {e}   ({dte(e)} days)")
        return

    # light interactive guidance when nothing was specified
    event, expiry = args.event, args.expiry
    if not event and not expiry and sys.stdin.isatty():
        exps = list(yf.Ticker(ticker).options)
        print(f"\n{ticker}: {len(exps)} expirations. Nearest few:")
        for e in exps[:6]:
            print(f"  {e}  ({dte(e)} days)")
        pick = input("\nEvent date (YYYY-MM-DD) or exact expiry [blank = front]: ").strip()
        if pick:
            # treat as event date (bracketing) by default
            event = pick
        th = input("Binary threshold price (blank to skip): ").strip()
        if th:
            try:
                args.threshold = float(th)
            except ValueError:
                pass

    try:
        r = analyze(ticker, event=event, expiry=expiry,
                    threshold=args.threshold, skew_pct=args.skew_pct)
    except Exception as e:
        sys.exit(f"Error: {e}")
    print()
    print(report(r))


if __name__ == "__main__":
    main()
