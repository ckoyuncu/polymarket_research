# Delta Tracker Documentation

## Overview

The `DeltaTracker` is a position management system for tracking delta-neutral YES/NO position pairs in the Polymarket Maker Rebates Bot. It monitors all open positions, calculates portfolio-wide delta exposure, and alerts when rebalancing is needed to maintain delta-neutrality.

## Purpose

In a delta-neutral maker strategy:
- You place equal-sized YES and NO positions on the same market
- This eliminates directional risk (you don't care which outcome wins)
- The goal is to earn maker rebates while maintaining zero delta

The DeltaTracker ensures your portfolio stays delta-neutral by:
1. Tracking all YES/NO position pairs
2. Calculating total delta across the portfolio
3. Alerting when delta exceeds the configured threshold (default 5%)
4. Providing rebalancing suggestions
5. Reconciling positions with exchange records

## Key Concepts

### Delta

**Delta** = YES size - NO size

- **Delta = 0**: Perfectly balanced (no directional exposure)
- **Positive delta**: Net long YES (portfolio favors UP outcomes)
- **Negative delta**: Net long NO (portfolio favors DOWN outcomes)

Example:
```python
# Position 1: Delta = 50 - 50 = 0 (neutral)
# Position 2: Delta = 60 - 40 = 20 (long YES)
# Portfolio delta = 0 + 20 = 20
```

### Delta Threshold

The delta threshold is calculated as:

**Threshold** = `max_delta_pct` × Total Exposure

Example with 5% threshold:
- Total exposure: $100
- Threshold: $100 × 0.05 = $5
- Alert if |delta| > $5

## Installation

The DeltaTracker is part of the `src.maker` module:

```python
from src.maker import DeltaTracker, TrackedPosition
```

## Basic Usage

### Initialize Tracker

```python
from src.maker import DeltaTracker

# Default: 5% max delta
tracker = DeltaTracker()

# Custom threshold: 1% max delta (stricter)
tracker = DeltaTracker(max_delta_pct=0.01)
```

### Add Positions

```python
# Add a delta-neutral position
tracker.add_position(
    market_id="btc-updown-15m-1736000000",
    yes_size=50,
    no_size=50,
    prices={"yes": 0.50, "no": 0.50}
)

# Check status
print(f"Delta: {tracker.get_delta()}")  # 0.0
print(f"Total exposure: ${tracker.get_total_exposure()}")  # 50.0
print(f"Needs rebalancing: {tracker.needs_rebalance()}")  # False
```

### Monitor Delta

```python
# Get current delta
delta = tracker.get_delta()

# Check if rebalancing needed
if tracker.needs_rebalance():
    print("WARNING: Portfolio delta exceeds threshold!")

    # Get rebalancing suggestion
    suggestion = tracker.get_rebalancing_suggestion()
    print(f"Suggestion: {suggestion['suggested_trade']}")
    print(f"Estimated size: {suggestion['estimated_trade_size']}")
```

### Remove Positions

```python
# When a market resolves, remove the position
removed = tracker.remove_position("btc-updown-15m-1736000000")

if removed:
    print(f"Removed position with delta: {removed.delta}")
```

## Advanced Features

### Position Reports

Generate comprehensive portfolio reports:

```python
report = tracker.get_position_report()

# Report includes:
print(f"Total positions: {report['total_positions']}")
print(f"Total exposure: ${report['total_exposure']}")
print(f"Current delta: {report['total_delta']}")
print(f"Delta %: {report['delta_pct']}%")
print(f"YES exposure: ${report['yes_exposure']}")
print(f"NO exposure: ${report['no_exposure']}")
print(f"Non-neutral positions: {report['non_neutral_positions']}")
print(f"Needs rebalancing: {report['needs_rebalance']}")
```

### Exchange Reconciliation

Verify tracker positions match exchange records:

```python
# Fetch positions from exchange
exchange_positions = {
    "btc-updown-15m-1736000000": {"yes_size": 50, "no_size": 50},
    "eth-updown-15m-1736000000": {"yes_size": 30, "no_size": 30},
}

# Reconcile
result = tracker.reconcile_with_exchange(exchange_positions)

if not result["reconciled"]:
    print(f"Discrepancies: {len(result['discrepancies'])}")
    print(f"Missing in tracker: {result['missing_in_tracker']}")
    print(f"Missing in exchange: {result['missing_in_exchange']}")
```

### Individual Position Access

```python
# Get specific position
position = tracker.get_position("btc-updown-15m-1736000000")

if position:
    print(f"YES: {position.yes_size} @ {position.yes_price}")
    print(f"NO: {position.no_size} @ {position.no_price}")
    print(f"Delta: {position.delta}")
    print(f"Is neutral: {position.is_delta_neutral}")
    print(f"Total cost: ${position.total_cost}")
```

### Iterate All Positions

```python
for market_id, position in tracker.positions.items():
    print(f"{market_id}: delta={position.delta}")
```

## API Reference

### DeltaTracker

#### Constructor

```python
DeltaTracker(max_delta_pct: float = 0.05)
```

- `max_delta_pct`: Maximum allowed delta as percentage of total exposure (default 5%)

#### Methods

##### add_position()

```python
add_position(
    market_id: str,
    yes_size: float,
    no_size: float,
    prices: dict[str, float]
) -> TrackedPosition
```

Add a new position to track.

**Raises:**
- `DeltaTrackerError`: If market_id already exists or validation fails

##### remove_position()

```python
remove_position(market_id: str) -> Optional[TrackedPosition]
```

Remove a position when market resolves.

**Returns:** The removed position, or None if not found

##### get_position()

```python
get_position(market_id: str) -> Optional[TrackedPosition]
```

Get a specific position by market_id.

##### get_delta()

```python
get_delta() -> float
```

Calculate total delta across all positions.

**Returns:** Sum of (yes_size - no_size) for all positions

##### get_total_exposure()

```python
get_total_exposure() -> float
```

Calculate total capital at risk.

**Returns:** Sum of total_cost for all positions

##### get_yes_exposure()

```python
get_yes_exposure() -> float
```

Calculate total YES side exposure.

##### get_no_exposure()

```python
get_no_exposure() -> float
```

Calculate total NO side exposure.

##### needs_rebalance()

```python
needs_rebalance() -> bool
```

Check if rebalancing is needed.

**Returns:** True if |delta| exceeds max_delta_pct × total_exposure

##### get_position_report()

```python
get_position_report() -> dict[str, Any]
```

Generate comprehensive position report.

**Returns:** Dictionary with portfolio statistics

##### reconcile_with_exchange()

```python
reconcile_with_exchange(
    exchange_positions: dict[str, dict[str, float]]
) -> dict[str, Any]
```

Reconcile positions with exchange records.

**Args:**
- `exchange_positions`: Dict mapping market_id to {"yes_size": X, "no_size": Y}

**Returns:** Reconciliation report with discrepancies

##### get_rebalancing_suggestion()

```python
get_rebalancing_suggestion() -> dict[str, Any]
```

Generate rebalancing suggestions.

**Returns:** Dictionary with current delta, threshold, and trade suggestions

##### reset()

```python
reset() -> None
```

Clear all tracked positions.

#### Magic Methods

- `len(tracker)`: Returns number of positions
- `market_id in tracker`: Check if market is tracked
- `repr(tracker)`: String representation

### TrackedPosition

Dataclass representing a single position.

#### Properties

- `delta`: YES size - NO size
- `is_delta_neutral`: True if delta < 1% of total size
- `yes_exposure`: YES size × YES price
- `no_exposure`: NO size × NO price

#### Methods

- `to_dict()`: Convert to dictionary representation

## Configuration

### From config.py

The tracker uses configuration from `src/config.py`:

```python
# Maximum delta exposure before rebalancing (percentage of total)
MAX_DELTA_PCT = float(os.getenv("MAX_DELTA_PCT", "0.05"))
```

Set via environment variable:
```bash
export MAX_DELTA_PCT=0.05  # 5% threshold
```

## Examples

See `examples/delta_tracker_example.py` for a complete working example.

Run the example:
```bash
cd /Users/shem/Desktop/polymarket_research
python examples/delta_tracker_example.py
```

## Testing

Comprehensive test suite with 100+ tests:

```bash
# Run delta tracker tests
pytest tests/test_delta_tracker.py -v

# Run with coverage
pytest tests/test_delta_tracker.py --cov=src.maker.delta_tracker
```

Test coverage includes:
- Position addition/removal
- Delta calculation
- Rebalancing detection
- Exchange reconciliation
- Exposure calculations
- Edge cases and error handling
- Validation logic

## Best Practices

### 1. Monitor Delta Regularly

```python
# Check delta before adding new positions
if tracker.needs_rebalance():
    print("WARNING: Already need rebalancing, don't add more positions")
```

### 2. Set Appropriate Threshold

```python
# Stricter threshold for smaller portfolios
if total_capital < 500:
    tracker = DeltaTracker(max_delta_pct=0.01)  # 1%
else:
    tracker = DeltaTracker(max_delta_pct=0.05)  # 5%
```

### 3. Reconcile Periodically

```python
# Reconcile every hour
import time

while True:
    exchange_positions = fetch_positions_from_exchange()
    result = tracker.reconcile_with_exchange(exchange_positions)

    if not result["reconciled"]:
        alert_team(result)

    time.sleep(3600)  # 1 hour
```

### 4. Handle Resolution Carefully

```python
# When market resolves, remove position immediately
def on_market_resolution(market_id: str, outcome: str):
    removed = tracker.remove_position(market_id)

    if removed:
        logger.info(f"Resolved {market_id}: delta was {removed.delta}")
    else:
        logger.warning(f"Market {market_id} not in tracker!")
```

### 5. Log Rebalancing Events

```python
import logging

if tracker.needs_rebalance():
    suggestion = tracker.get_rebalancing_suggestion()
    logging.warning(
        f"Rebalancing required: delta={suggestion['current_delta']}, "
        f"threshold={suggestion['threshold']}, "
        f"action={suggestion['suggested_trade']}"
    )
```

## Integration with Paper Simulator

The DeltaTracker can be used alongside the `MakerPaperSimulator`:

```python
from src.maker import DeltaTracker, MakerPaperSimulator

# Initialize both
simulator = MakerPaperSimulator(initial_balance=300)
tracker = DeltaTracker(max_delta_pct=0.05)

# Place position in simulator
position = simulator.place_delta_neutral(
    market_id="btc-updown-15m-1736000000",
    size=50,
    yes_price=0.50,
    no_price=0.50
)

# Track in delta tracker
tracker.add_position(
    market_id=position.market_id,
    yes_size=float(position.yes_size),
    no_size=float(position.no_size),
    prices={"yes": float(position.yes_price), "no": float(position.no_price)}
)

# Monitor both
print(f"Simulator balance: {simulator.balance}")
print(f"Tracker delta: {tracker.get_delta()}")
```

## Troubleshooting

### Issue: Delta not zero for equal YES/NO sizes

**Cause:** Floating point precision
**Solution:** Delta < 0.01 is considered neutral

```python
position = tracker.get_position(market_id)
if abs(position.delta) < 0.01:
    print("Position is effectively delta-neutral")
```

### Issue: Reconciliation fails with tiny differences

**Cause:** Rounding differences between tracker and exchange
**Solution:** Tolerance of 0.0001 is built-in

The reconciler allows differences up to 0.0001 shares.

### Issue: Threshold too strict or too loose

**Cause:** Inappropriate max_delta_pct for portfolio size
**Solution:** Adjust based on total exposure

```python
# For $100 portfolio with 5% threshold:
# Threshold = $100 × 0.05 = $5
# This might be too loose or too strict depending on strategy

# Adjust accordingly:
tracker = DeltaTracker(max_delta_pct=0.02)  # 2% = $2 threshold
```

## File Locations

- **Implementation**: `/Users/shem/Desktop/polymarket_research/src/maker/delta_tracker.py`
- **Tests**: `/Users/shem/Desktop/polymarket_research/tests/test_delta_tracker.py`
- **Example**: `/Users/shem/Desktop/polymarket_research/examples/delta_tracker_example.py`
- **Config**: `/Users/shem/Desktop/polymarket_research/src/config.py`

## Related Documentation

- [Paper Simulator](../src/maker/paper_simulator.py) - Delta-neutral paper trading
- [Config](../src/config.py) - Configuration management
- [Market Finder](../src/maker/market_finder.py) - Finding 15-minute markets

## Success Criteria

- [x] Tracks all positions accurately
- [x] Delta calculation correct
- [x] Alerts when delta > threshold
- [x] Reconciliation works
- [x] All tests pass (100+ tests)
- [x] Comprehensive documentation
- [x] Example code provided
