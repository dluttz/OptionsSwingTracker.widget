# Options Swing Tracker.widget

Self-refreshing Übersicht widget for options-implied expected moves around manually entered catalyst dates.

The widget is a glanceable gut-check tool. It is not an execution feed, not a trading platform, and not a forecast of real-world odds.

This project is for informational and educational use only. It is not financial advice.

## Setup

Install [Übersicht](https://tracesof.net/uebersicht/), then clone or download this folder onto your Mac. The recommended location is your Desktop:

```sh
cd "$HOME/Desktop"
git clone <repo-url> OptionsSwingTracker.widget
cd "$HOME/Desktop/OptionsSwingTracker.widget"
./bin/setup.sh
```

The setup script:

- creates `config.json` from `config.example.json` if needed;
- writes your local widget path into `config.json` so Übersicht can run commands reliably;
- creates `python/.venv`;
- installs Python dependencies;
- links this folder into Übersicht's widgets folder.

`config.json`, `python/.venv`, `cache/`, and `logs/` are local runtime files and are intentionally ignored by Git.

If you open the widget before running setup, it shows a setup-required state instead of trying to use a hard-coded path.

## Edit The Watchlist

Use the inline `Edit tickers` button in the widget. Übersicht only sends click events while its interaction shortcut is active and after Accessibility access is granted, so enable that in Übersicht preferences if the button does not respond.

Inside the widget editor:

- Enter `Ticker`, `Reaction date`, optional `Threshold`, and a typed `Event`, then click `Add event`.
- `Remove` on a row hides that ticker from the dashboard.

You can also edit local `config.json` directly. Enabled rows are validated before fetch; malformed rows render as clear error rows instead of blanking the widget. Duplicate enabled rows with the same ticker, event date, and threshold are flagged because they collide in the row caches.

Each enabled watchlist row supports:

- `ticker`: stock symbol.
- `event`: catalyst/reaction date, `YYYY-MM-DD`.
- `timing`: optional catalyst timing, one of `unknown`, `bmo`, `intraday`, or `amc`.
- `label`: short catalyst note shown in the row.
- `threshold`: optional price level for risk-neutral below/above odds.
- `enabled`: `true` or `false`.
- `event_source` / `event_confidence`: shown in the widget; manual editor entries use `manual` / `user`.

The editor is manual-first: type the catalyst and choose the reaction/deadline date. The calculation then resolves the first listed options expiration that covers that event date, with `AMC` requiring an expiry strictly after the event date.

`display.compact` controls the row density. The default is `true`, which shows the minimal row: ticker/spot, adjusted move, quote-basis badge, delta, event date, and expiry. Use the header `Details` / `Minimal` toggle to persistently switch between compact rows and full details.

`display.theme` controls the color theme. The header palette button cycles through `graphite`, `light`, `midnight`, and `mono`; invalid values fall back to `graphite`.

`display.position` controls the widget frame. Use the header `↔` layout button to reveal arrows for moving the widget, width controls for narrowing/widening it, height controls for making it shorter/taller, and `Reset` for the default frame. The widget persists `top`, `left`, `width`, and optional `max_height` in `config.json`, with safe bounds so it cannot be shrunk below a readable size through the UI.

`display.refresh_seconds` controls the Übersicht command timer. `display.cache_ttl_seconds` controls how often Yahoo/yfinance data is actually refetched; the default is 300 seconds. The widget caps its height to the visible screen and scrolls ticker rows when the watchlist grows.

## Methodology

The headline move is the preserved script's ATM-straddle expected move around the selected catalyst:

- Raw expected move: `em_raw = straddle / spot`, where `straddle = ATM call + ATM put`.
- Adjusted move: `em_adj = 0.85 * em_raw`. This fixed 15% haircut is preserved from `event_move.py`; it is not a separate market quote.
- Expiry bracketing: the event date is bracketed to the first listed options expiry that covers the catalyst. The UI shows the gap when the expiry lands after the event, because the straddle then includes post-event volatility too.

ATM IV is an independent cross-check, not the source of the headline number:

- Annualized `ATM IV` is shown only when the option-chain IV is credible.
- Yahoo placeholder/default-looking IVs such as `0.125`, `0.1875`, `0.25`, equal call/put IVs, duplicate cross-ticker ATM IVs, and IVs from non-live quote bases are rejected.
- `IV move` is the horizon move from the IV formula: `spot * ATM IV * sqrt(DTE / 365)`, shown as a percentage of spot. It is suppressed when ATM IV is unavailable.
- The widget does not back-solve IV from the straddle, because that would make the cross-check circular.

Quote basis is explicit:

- Option leg priority is live bid/ask mid -> cached regular-session mid -> indicative last trade -> no usable leg.
- `Live mid` means both ATM legs used current bid/ask mids.
- `Prior close` means the widget reused the last stored regular-session option mids.
- `Indicative` means one or both option legs fell back to last trade, often during pre-market or after-hours.
- `Cached` means the row came from the local data cache and was not rechecked against Yahoo on this UI refresh.

Risk-neutral odds are optional and shown only when you set `threshold`:

- `prob_below` / `prob_above` are risk-neutral option-price reads, not real-world probabilities.
- Odds are suppressed or flagged when quotes are not live mids, the chain is sparse, the finite-difference read is unreliable, or the raw probability needed clamping.

Skew is a put/call IV read from the configured skew strikes:

- `skew_label` is `downside skew`, `upside skew`, `balanced`, or `skew n/a`.
- `skew n/a` appears when the IV inputs are missing, placeholder-looking, equal/default Yahoo values, or not from a clean live option basis.

Catalyst timing affects whether same-day expiry is acceptable:

- `bmo` and `intraday`: same-day expiry can cover the catalyst.
- `amc`: same-day expiry does not cover an after-close catalyst, so the wrapper requires a later expiry.
- `unknown`: same-day reads are allowed but flagged as timing-ambiguous.

## What The Flags Mean

| Flag / State | Meaning |
| --- | --- |
| `Live mid` | ATM option legs used current bid/ask mids. This is the cleanest quote basis. |
| `Prior close` | Current option mids were unavailable, so the row reused the last stored regular-session mids. |
| `Indicative` | Option bid/ask mids were unavailable and one or both legs used last trade. Treat the move as indicative. |
| `stale` / `last_good` | Current fetch failed and the widget served the last successful row for that key. |
| `cached` | The local data cache was still fresh; this refresh did not recheck Yahoo. |
| `ATM IV n/a (chain placeholder)` | The chain IV looked like a Yahoo placeholder/default or came from a non-live quote basis. |
| `skew n/a` | The skew IV inputs were not credible enough to show a directional skew read. |
| `event passed` | The catalyst date is before the current US/Eastern market date. |
| `expiry before event` | The selected expiry does not cover the catalyst, so the move is not a valid forward event read. |
| `odds unreliable` | Threshold odds were suppressed because chain/quote quality was not good enough. |
| `+Nd padded` / `+Nd wide` | The expiry is N days after the event, so the straddle includes non-event volatility after the catalyst. |
| `market holiday` | US equity markets are modeled as closed for a standard NYSE/Nasdaq full holiday. |
| `early close 1 PM` | The session is modeled as a standard 1 PM ET early close. |

Data caveats:

- Yahoo/yfinance data is delayed, can rate-limit, and can return empty option bid/ask or placeholder IV fields.
- Pre-market and after-hours stock prices can be current while option legs are still prior-session last trades.
- Holiday and early-close logic is rule-based for standard NYSE/Nasdaq closures; it is not a downloaded exchange calendar.
- Event isolation is a visible caveat, not a decomposition. A padded expiry still includes non-event volatility.

## Commands

```sh
./bin/setup.sh
```

Creates/updates `python/.venv`, installs dependencies, marks scripts executable, and symlinks this folder into Übersicht's widget folder.

```sh
./bin/run_tests.sh
```

Runs the pytest suite under the project venv. Tests use synthetic data and should not make live Yahoo calls.

```sh
./bin/verify_parity.sh
```

Compares the wrapper against `reference/event_move_original.py`. It defaults to AAPL and the next monthly expiry/event date, resolves the pinned expiration internally, and ends with `PASS` or `FAIL`.

```sh
./bin/doctor.sh
```

Runs a local health report for the venv, required imports, enabled watchlist validation, writable cache/log folders, Übersicht symlink, and optional quick Yahoo reachability. Yahoo reachability warnings do not fail the doctor.

```sh
./bin/run_widget.sh
```

The Übersicht command. It invokes `python/.venv/bin/python` directly and emits compact JSON for `index.jsx`.

The header controls call:

```sh
./bin/widget_action.sh theme --theme graphite
./bin/widget_action.sh compact --compact true
./bin/widget_action.sh layout --dx 20 --dy 0 --dw -20 --dh -60
```

These atomically persist `display.theme`, `display.compact`, and `display.position` in `config.json`.

## JSON Fields

Main per-row fields rendered by `index.jsx`:

| Field | Meaning |
| --- | --- |
| `key`, `ok`, `error`, `stale` | Row identity, health, and fallback state. |
| `ticker`, `label`, `event`, `expiry`, `days` | Watchlist and resolved expiry metadata. |
| `event_source`, `event_confidence` | Source/confidence text shown in the row. |
| `spot`, `spot_source`, `spot_is_extended` | Stock price and whether it came from extended-hours data. |
| `straddle` | ATM call + ATM put price used for the raw expected move. |
| `em_raw`, `em_adj` | Raw straddle move and preserved `×0.85` adjusted move. |
| `adj_low`, `adj_high` | Adjusted expected price range around spot. |
| `atm_iv`, `atm_iv_pct`, `atm_iv_unavailable_reason` | Annualized ATM IV state. `atm_iv_pct` is null unless IV is credible. |
| `iv_move_pct`, `iv_check_available` | IV-formula move over the selected horizon, only available with credible ATM IV. |
| `move_status`, `move_status_label`, `quote_basis`, `quote_warnings`, `option_quote_age` | Quote basis and row confidence metadata rendered as badges/details/warnings. |
| `skew_label` | Rendered skew text. |
| `threshold`, `prob_below`, `prob_above`, `prob_reliable`, `prob_warning`, `prob_unreliable_reason` | Optional risk-neutral threshold odds and reliability flags. |
| `event_gap_days`, `event_gap_label`, `event_gap_severity`, `event_gap_warning`, `event_passed` | Event/expiry coverage and past-event flags. |
| `cache_status`, `not_rechecked`, `delta` | Cache and change-tracking state. |

Emitted row diagnostics not rendered directly by the current JSX include `timing`, `event_url`, `dte_basis`, `atm_strike`, `atm_selection`, `atm_selection_note`, `atm_call`, `atm_put`, `em_raw_dollars`, `em_adj_dollars`, `raw_low`, `raw_high`, `atm_iv_valid`, `atm_iv_source`, `em_iv`, `em_iv_pct`, `skew`, `skew_pct`, `put_k`, `call_k`, `put_iv`, `call_iv`, `prob_below_raw`, `prob_below_clamped`, `risk_neutral`, `quote_quality`, `quote_confidence`, `basis_note`, `option_mid_cache_used`, `option_mid_cache_stored_at`, and `fetched_at`. These remain useful for cache/fallback behavior, tests, and debugging.

Envelope fields include `generated_at`, `served_at`, `cache_status`, `cache_ttl_seconds`, `cache_age_seconds`, `data_schema_version`, `market_status`, `rows`, `summary`, and `display`.

## Troubleshooting

- Widget blank or setup message: run `./bin/setup.sh`, then `./bin/doctor.sh`.
- Buttons do nothing: enable Übersicht interaction/accessibility permissions, then reload widgets.
- Stale rows: Yahoo/yfinance failed temporarily, so the widget served `cache/last_good.json`.
- Cached rows: the cache TTL has not expired; use `./bin/run_widget.sh --force-refresh` only when you need to force a fresh command result.
- Logs live in `logs/widget.log` and `logs/widget.err.log`.

## Repository Hygiene

Do not commit local runtime state:

- `config.json`
- `python/.venv/`
- `cache/`
- `logs/`
- `__pycache__/`
- `.pytest_cache/`

Use `config.example.json` for public defaults.
