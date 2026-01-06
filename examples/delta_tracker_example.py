"""
Example usage of the DeltaTracker for monitoring delta-neutral positions.

This script demonstrates how to:
1. Initialize a DeltaTracker
2. Add delta-neutral positions
3. Monitor delta exposure
4. Detect when rebalancing is needed
5. Generate position reports
6. Reconcile with exchange records
"""

from src.maker import DeltaTracker


def main():
    """Run DeltaTracker example."""
    print("=" * 70)
    print("Delta Tracker Example")
    print("=" * 70)
    print()

    # Initialize tracker with 5% max delta
    tracker = DeltaTracker(max_delta_pct=0.05)
    print(f"Initialized tracker: {tracker}")
    print()

    # Example 1: Add perfectly balanced positions
    print("Example 1: Adding balanced delta-neutral positions")
    print("-" * 70)

    tracker.add_position(
        market_id="btc-updown-15m-1736000000",
        yes_size=50,
        no_size=50,
        prices={"yes": 0.50, "no": 0.50},
    )
    print(f"Added position 1: delta={tracker.get_delta():.2f}")

    tracker.add_position(
        market_id="eth-updown-15m-1736000000",
        yes_size=30,
        no_size=30,
        prices={"yes": 0.60, "no": 0.40},
    )
    print(f"Added position 2: delta={tracker.get_delta():.2f}")
    print(f"Total exposure: ${tracker.get_total_exposure():.2f}")
    print(f"Needs rebalancing: {tracker.needs_rebalance()}")
    print()

    # Example 2: Add imbalanced position
    print("Example 2: Adding imbalanced position")
    print("-" * 70)

    tracker.add_position(
        market_id="btc-updown-15m-1736001000",
        yes_size=80,
        no_size=20,
        prices={"yes": 0.50, "no": 0.50},
    )
    print(f"Added imbalanced position: delta={tracker.get_delta():.2f}")
    print(f"Needs rebalancing: {tracker.needs_rebalance()}")
    print()

    # Example 3: Get position report
    print("Example 3: Position Report")
    print("-" * 70)

    report = tracker.get_position_report()
    print(f"Total positions: {report['total_positions']}")
    print(f"Total exposure: ${report['total_exposure']}")
    print(f"Current delta: {report['total_delta']}")
    print(f"Delta percentage: {report['delta_pct']}%")
    print(f"Max allowed delta: {report['max_delta_pct']}%")
    print(f"YES exposure: ${report['yes_exposure']}")
    print(f"NO exposure: ${report['no_exposure']}")
    print(f"Exposure imbalance: ${report['exposure_imbalance']}")
    print(f"Non-neutral positions: {report['non_neutral_positions']}")
    print()

    # Example 4: Rebalancing suggestion
    print("Example 4: Rebalancing Suggestion")
    print("-" * 70)

    suggestion = tracker.get_rebalancing_suggestion()
    if suggestion["needs_rebalancing"]:
        print(f"Status: REBALANCING REQUIRED")
        print(f"Current delta: {suggestion['current_delta']}")
        print(f"Threshold: {suggestion['threshold']}")
        print(f"Excess delta: {suggestion['excess_delta']}")
        print(f"Suggestion: {suggestion['suggested_trade']}")
        print(f"Estimated trade size: {suggestion['estimated_trade_size']}")
    else:
        print(f"Status: {suggestion['message']}")
    print()

    # Example 5: Individual position details
    print("Example 5: Individual Position Details")
    print("-" * 70)

    for market_id, position in tracker.positions.items():
        print(f"\nMarket: {market_id}")
        print(f"  YES: {position.yes_size} @ {position.yes_price}")
        print(f"  NO:  {position.no_size} @ {position.no_price}")
        print(f"  Delta: {position.delta}")
        print(f"  Total cost: ${position.total_cost}")
        print(f"  Is delta-neutral: {position.is_delta_neutral}")
    print()

    # Example 6: Reconciliation with exchange
    print("Example 6: Exchange Reconciliation")
    print("-" * 70)

    # Simulate exchange positions (with a small discrepancy)
    exchange_positions = {
        "btc-updown-15m-1736000000": {"yes_size": 50, "no_size": 50},
        "eth-updown-15m-1736000000": {"yes_size": 30, "no_size": 30},
        "btc-updown-15m-1736001000": {"yes_size": 78, "no_size": 22},  # Discrepancy!
    }

    reconciliation = tracker.reconcile_with_exchange(exchange_positions)
    print(f"Reconciled: {reconciliation['reconciled']}")
    print(f"Total checked: {reconciliation['total_checked']}")

    if reconciliation["discrepancies"]:
        print(f"\nDiscrepancies found: {len(reconciliation['discrepancies'])}")
        for disc in reconciliation["discrepancies"]:
            print(f"  Market: {disc['market_id']}")
            print(f"    Tracker: YES={disc['tracker_yes']}, NO={disc['tracker_no']}")
            print(f"    Exchange: YES={disc['exchange_yes']}, NO={disc['exchange_no']}")
            print(f"    Diff: YES={disc['yes_diff']}, NO={disc['no_diff']}")
    print()

    # Example 7: Remove position
    print("Example 7: Remove Position (market resolves)")
    print("-" * 70)

    removed = tracker.remove_position("btc-updown-15m-1736000000")
    print(f"Removed position: {removed.market_id}")
    print(f"New delta: {tracker.get_delta():.2f}")
    print(f"Remaining positions: {len(tracker)}")
    print(f"Needs rebalancing: {tracker.needs_rebalance()}")
    print()

    # Example 8: Final status
    print("Example 8: Final Status")
    print("-" * 70)
    print(f"Final tracker state: {tracker}")
    print()

    print("=" * 70)
    print("Example complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()
