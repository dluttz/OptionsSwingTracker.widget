# Design / Progress

## Choices

- Platform: Übersicht `.jsx` widget using command-on-a-timer.
- Location: one self-contained folder at `~/Desktop/OptionsSwingTracker.widget`.
- Math source: preserved the original `event_move.py` implementation in `reference/event_move_original.py`.
- Preservation strategy: Python wrapper imports and calls the original `analyze()`, `choose_expiry()`, and `report()` instead of rewriting formulas.
- Runtime: `bin/setup.sh` creates `python/.venv`; `bin/run_widget.sh` invokes that venv directly so Übersicht does not depend on shell `PATH`.
- Data source: yfinance/Yahoo, cached locally with per-ticker error isolation and last-good fallback.
- Event entry: widget editor is manual-first. User types the ticker, event/catalyst, and reaction/deadline date; no candidate/template selector is shown in the widget.
- Event discovery/picker scaffolding was removed after the product direction settled on manual catalyst entry.
- IV display: placeholder/tiny IV values from the ATM option chain are treated as missing. The widget rejects Yahoo default-looking IVs such as `0.125`, `0.1875`, `0.25`, equal call/put IVs, duplicate cross-ticker ATM IVs, and IVs from non-live option quote bases. It shows annualized `ATM IV` plus a separate `IV move` only when the IV is credible; it never inverts the straddle to force agreement.
- Change display: rows compare the latest successful reading with the previous successful row for the same ticker/event/timing/threshold and only when quote basis matches; cache hits are labeled as not rechecked.
- DTE/session basis: wrapper metadata uses the US/Eastern market date so Übersicht's local process timezone cannot shift days-to-expiry. Market status now models standard NYSE/Nasdaq holidays and 1 PM early closes, so full-holiday chain data cannot render as `Live mid`.
- Event isolation: rows show how many days the resolved expiry falls after the event and flag padded/wide windows.
- Event edge cases: expiry-before-event is invalid, past events are flagged, and an event beyond the listed options chain returns a clear row error instead of using a non-covering expiry.
- Event timing: manual entries can be marked `unknown`, `BMO`, `intraday`, or `AMC`; AMC events require an options expiry after the event date.
- Ticker validation: widget add actions validate spot, bracketing expiry, and non-empty option chains before writing to `config.json`.
- Spot source: outside regular hours, Yahoo pre-market/after-hours stock prices are used when available and labeled in the row.
- Quote basis: rows distinguish live option mids, indicative last-trade option prices, prior clean mids, stale fallbacks, and cached/not-rechecked data.
- Regular-session mid cache: when the market is open and the ATM option legs have valid bid/ask mids, the widget stores per-leg mids in `cache/regular_option_mids.json`; outside that condition, rows may reuse those mids as `Prior close` before falling back to indicative last trades.
- Regular-session mid cache is pruned on write so expired option expiries do not accumulate indefinitely.
- Per-ticker timeout: each yfinance analyze call has an independent timeout so one slow symbol degrades to an error/stale row instead of blocking the whole refresh.
- Fetch concurrency: enabled watchlist rows are fetched with a bounded `ThreadPoolExecutor`; row order is restored to config order, and cache TTL short-circuit still returns cached JSON without submitting fetches.
- Config robustness: enabled watchlist rows are validated before fetch. Invalid rows and duplicate ticker/event/threshold keys render as explicit error rows instead of crashing or colliding in caches.
- Health check: `bin/doctor.sh` runs a local pass/fail report for the venv, imports, enabled watchlist validation, writable cache/log directories, Übersicht symlink, and optional Yahoo reachability.
- README now documents the current methodology, quote/IV/probability flags, command surface, JSON row fields, and caveats instead of the earlier minimal setup/troubleshooting notes.
- Display mode: rows default to Minimal via `display.compact=true`; the header toggle persists Minimal/Details globally while keeping basis, stale, event-passed/invalid, delta, and warning-count indicators visible in Minimal mode.
- Themes: the header palette button persists `display.theme`; supported themes are `graphite`, `light`, `midnight`, and `mono`, all using CSS variables while preserving semantic state colors for live/prior/indicative/stale and delta direction.
- Layout controls: the header `↔` button exposes move arrows, width narrow/widen, height shorter/taller, and reset. Changes persist to `display.position` through `widget_action.py layout`, while the UI applies the current position immediately.
- Public packaging: `index.jsx` no longer hard-codes a user-specific path. `bin/setup.sh` creates local `config.json` from `config.example.json` when needed and writes `runtime.root` so Übersicht commands use the installed folder. Local config, venv, caches, logs, and Python artifacts are ignored for GitHub.

## Milestones

- Milestone 1: source capture, wrapper, parity verifier.
- Milestone 2: config, cached data command, bad-ticker resilience.
- Milestone 3a: Übersicht command/render handshake.
- Milestone 3b: compact styling, README, logs, setup polish.

## Verification

- `python3 -m py_compile reference/event_move_original.py python/event_move_core.py python/widget_data.py python/parity_check.py`
- `./bin/run_tests.sh`
- `./bin/setup.sh`
- `./bin/verify_parity.sh`
- `./bin/run_widget.sh`

## Current Status

- Setup completed and symlinked the widget into Übersicht's widgets folder.
- Parity checks passed for default AAPL and AAPL with `--threshold 300`.
- Widget command returns valid JSON for the configured watchlist.
- Bad-ticker test returns an isolated error row instead of breaking output.
- Cache hit path and last-good stale-row fallback were verified.
- Pytest suite added under `python/tests/` to lock IV/skew credibility, quote-basis priority, market holidays/early closes, liquidity-aware ATM selection, risk-neutral gating, expiry/event edge cases, per-ticker timeout/concurrency, regular-mid cache pruning, cache TTL short-circuit, LMT enabled state, watchlist validation, duplicate detection, and doctor reporting without live network calls.

## Critique Fixes Added

- Modern dark/glass widget UI focused on catalyst date and priced move.
- Widget rows include event source/confidence, `IV n/a`, and expected-move deltas.
- Widget header includes a visible inline `Edit tickers` editor using Übersicht's `run` helper.
- Each ticker row has a live `Remove` button.
- Primary editor flow is now manual: ticker, event label, reaction/deadline date, optional threshold, Add event.
- Uncertainty visibility pass: event-expiry gap, generated/served timestamps, market open/closed status, cache-hit/not-rechecked status, low-confidence quote warnings, and risk-neutral probability clamp warnings are included in the data contract and UI.
- Display caveats now wrap instead of truncating, and rows surface quote confidence through the headline basis badge plus warning chips.
- Invalid tickers are rejected before add, error rows have a remove control, and the threshold field has an inline help bubble.
- Widget height is capped to the viewport and the ticker rows scroll internally for longer watchlists.
- Accuracy/clarity pass: annualized ATM IV is no longer mislabeled as the IV move, nearest liquid ATM fallback is labeled when used, option quote age is surfaced, probabilities are hidden when chain quality is unreliable, skew is hidden when its IV inputs are placeholder/non-live, and the adjusted move is labeled as the preserved `×0.85` haircut.
- Documentation pass: README updated to explain the preserved ATM-straddle math, fixed `×0.85` adjustment, IV credibility gates, quote-basis priority, risk-neutral odds suppression, skew gating, event timing/gap flags, commands, and UI JSON contract.
- UI consolidation pass: default rows are trimmed to essentials, full analytics move into Details mode, and theme/display settings now round-trip through `widget_action.py` into `config.json`.
- Layout pass: the widget can now be nudged around the desktop and narrowed/widened from the header without manually editing `config.json`; bounds keep the panel readable and prevent negative top/left positions.
- Layout polish pass: panel text now explicitly inherits the active theme text color, the move/resize dashboard uses a symmetric D-pad plus equal-width size controls, minimum width is lowered to 300px, and optional max height can be shortened so rows scroll inside a smaller widget.
- GitHub-readiness pass: added `.gitignore`, `config.example.json`, MIT license, setup-time runtime path generation, README public-install notes, and repository hygiene guidance.

## Known Limitations

- Expected move still uses the preserved spot-based math from `event_move.py`; no forward-price or dividend adjustment is applied.
- ATM interpolation is intentionally not added; the original nearest-strike behavior is preserved.
- Risk-neutral probability remains the original finite-difference read without a discount-factor adjustment.
- Risk-neutral odds are suppressed when the current chain basis is not clean live mids, when the finite-difference read is flagged, or when the event horizon is too short for stale quotes.
- Event isolation is a visible caveat, not a decomposition. A padded expiry still contains non-event volatility; the widget flags the gap instead of trying to strip that volatility out.
- Market status uses US/Eastern equity-market hours with standard NYSE/Nasdaq full holidays and common 1 PM early closes. It is still rule-based, not a downloaded exchange calendar.

## Summary & Known Limitations

- Final accuracy model: the headline read is the preserved ATM-straddle expected move, with raw `straddle / spot` and the original fixed `0.85` adjusted move shown explicitly as a haircut rather than a separate market quote.
- Final IV model: annualized ATM IV and IV-implied move are displayed only when the option-chain IV input is credible. Placeholder Yahoo values, equal/default call-put IVs, duplicate cross-ticker IVs, and non-live quote-basis IVs are rejected instead of back-solving from the straddle.
- Final quote-basis model: rows distinguish `Live mid`, `Prior close`, `Indicative`, `Stale`, and `Cached`; the data layer now normalizes `move_status` to `live`, `prior_close`, `indicative`, `stale`, or `cached` so labels, footer counts, and CSS classes stay aligned.
- Final skew model: skew is shown only when put/call IV inputs are credible and live; otherwise `skew n/a` is shown.
- Final timing/session model: DTE and event-pass checks use US/Eastern market date, with a rule-based NYSE/Nasdaq holiday and early-close calendar. `BMO`/`intraday`/`AMC`/`unknown` timing controls whether same-day expiry is considered valid or ambiguous.
- Final reliability model: enabled watchlist rows are validated before fetch; duplicate ticker/event/threshold rows are flagged; fetches run concurrently with per-ticker future timeouts; cache TTL short-circuits avoid unnecessary Yahoo hits; last-good and regular-session option-mid caches keep the widget from blanking.
- Final display model: Minimal is the default row layout; Details restores raw/adjusted math, straddle, ATM IV, IV move, skew, basis notes, range, source, gap, and warning chips. Theme choice is persisted in config and validated with fallback to Graphite.
- Final layout model: position, width, and optional max height live under `display.position`, are normalized in the data contract, and are saved by the widget action command so move/resize choices survive Übersicht refreshes.
- Data caveats remain: Yahoo/yfinance can return delayed, missing, stale, or placeholder fields; pre-market stock prices can be mixed with prior-session option legs; event/expiry gap flags expose but do not remove non-event volatility; risk-neutral odds are option-price reads, not real-world probabilities.
