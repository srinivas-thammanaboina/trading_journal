# Bug Fix Tracker — Trading Journal

All bugs found and fixed during development, tracked for audit and regression awareness.

---

## 2026-03-16 — Broker Metrics Redesign

### BUG-001: Typo "Filed" instead of "Filled"
- **File**: `app/templates/broker_metrics.html` (line 340)
- **Severity**: Low
- **Found by**: Code review (reviewboard.md)
- **Fix**: Changed `Filed` → `Filled` in Fill Rate badge
- **Commit**: `81e1503`

### BUG-002: Dead code — `unknown_stale` never returned by API
- **File**: `app/templates/broker_metrics.html` (line 171)
- **Severity**: Low
- **Found by**: Code review (reviewboard.md)
- **Issue**: Template checked `order_flow.get('unknown_stale', 0)` but API never returned that key — row never displayed
- **Fix**: Removed the dead code block entirely
- **Commit**: `81e1503`

### BUG-003: "View All" link href="#" goes nowhere
- **File**: `app/templates/broker_metrics.html` (line 303)
- **Severity**: Low
- **Found by**: Code review (reviewboard.md)
- **Fix**: Removed the non-functional link
- **Commit**: `81e1503`

### BUG-004: Filter bar styling mismatch
- **File**: `app/templates/broker_metrics.html`
- **Severity**: Low (visual)
- **Found by**: Visual review (screenshot comparison with Trades page)
- **Issue**: Broker Metrics used raw `<div class="filter-bar">` with inline styles instead of the `.filters` CSS class and `<form>` pattern used by all other pages
- **Fix**: Changed to `<div class="filters"><form>` pattern matching trades.html
- **Commit**: `35f8ace`

### BUG-005: Gateway health query — `gateway_connected` column not reliably updated
- **File**: `app/api/broker_metrics.py` (line ~197)
- **Severity**: Medium
- **Found by**: Data audit — dashboard always showed "Disconnected", investigated root cause
- **Issue**: API queried `gateway_connected` from `system_state` table. The column exists in the schema but the bot doesn't actively update it on connect/disconnect events, so it always returned the default value, making the gateway status indicator unreliable
- **Fix**: Derive connection status from `updated_at` recency (within 5 min = connected) + `halted` status. More reliable than a stored boolean that isn't maintained
- **Commit**: uncommitted (staged in working tree)

### BUG-006: Chart.js canvas overflow on Analytics page
- **File**: `app/templates/analytics.html`
- **Severity**: Low (visual)
- **Found by**: Development — noticed charts overflowing containers
- **Issue**: Chart.js canvases for Cumulative P&L and Win/Loss charts were not wrapped in `position:relative; height:Xpx` containers, causing unbounded growth
- **Fix**: Wrapped both canvases in properly sized relative containers
- **Commit**: `81e1503`
