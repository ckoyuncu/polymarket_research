#!/usr/bin/env python3
"""
Replicability Assessment for Account88888 Strategy

Evaluates whether the strategy can be replicated based on:
1. Entry signal clarity - Can we identify what triggers trades?
2. Execution feasibility - Do we have the infrastructure?
3. Capital requirements - How much money is needed?
4. Edge sustainability - Will the edge persist?
5. Risk assessment - What can go wrong?

Usage:
    python scripts/analysis/replicability_assessment.py
    python scripts/analysis/replicability_assessment.py --output reports/replicability_assessment.json
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
import statistics


def load_data(trades_path: str, metadata_path: str):
    """Load trades and metadata."""
    print("Loading data...")

    with open(trades_path, 'r') as f:
        data = json.load(f)
    if isinstance(data, dict):
        trades = data.get("trades", list(data.values()))
        if isinstance(trades, dict):
            trades = list(trades.values())
    else:
        trades = data

    with open(metadata_path, 'r') as f:
        data = json.load(f)
    metadata = data.get("token_to_market", data) if isinstance(data, dict) else data

    return trades, metadata


def assess_entry_signal_clarity(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    Assess how clear the entry signals are.

    Questions:
    - Can we determine WHEN to trade?
    - Can we determine WHAT to trade?
    - Is there a clear pattern?
    """
    print("\n[1] ENTRY SIGNAL CLARITY")
    print("-" * 50)

    # Analyze timing pattern
    timing_data = []
    for trade in trades[:100000]:  # Sample
        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        slug = market.get("slug", "")
        if "-15m-" not in slug:
            continue

        try:
            resolution_ts = int(slug.split("-15m-")[1])
        except:
            continue

        trade_ts = trade.get("timestamp", 0)
        if trade_ts and resolution_ts:
            timing_data.append(trade_ts - resolution_ts)

    # Analyze pricing pattern
    prices = [t.get("price", 0) for t in trades if t.get("price", 0) > 0 and t.get("price", 0) < 10]

    findings = {
        "timing_analysis": {
            "total_sampled": len(timing_data),
            "after_resolution_pct": sum(1 for t in timing_data if t > 0) / len(timing_data) * 100 if timing_data else 0,
            "median_seconds_after": statistics.median(timing_data) if timing_data else 0,
        },
        "price_analysis": {
            "median_entry_price": statistics.median(prices) if prices else 0,
            "price_std_dev": statistics.stdev(prices) if len(prices) > 1 else 0,
        }
    }

    # Score 1-5
    # Clear timing (after resolution): +2
    # Consistent timing window: +1
    # Clear price level: +1
    # Pattern is simple: +1

    score = 0
    reasons = []

    if findings["timing_analysis"]["after_resolution_pct"] > 99:
        score += 2
        reasons.append("Clear: Trade after resolution (99%+)")
    else:
        reasons.append("Unclear timing pattern")

    median_timing = findings["timing_analysis"]["median_seconds_after"]
    if 60 < median_timing < 900:  # 1-15 min window
        score += 1
        reasons.append(f"Consistent timing window (~{median_timing/60:.1f} min after)")
    else:
        reasons.append("Inconsistent timing")

    if 0.4 < findings["price_analysis"]["median_entry_price"] < 0.6:
        score += 1
        reasons.append(f"Buying near fair value (${findings['price_analysis']['median_entry_price']:.2f})")
    else:
        reasons.append("Unclear price pattern")

    # The pattern is relatively simple
    score += 1
    reasons.append("Simple pattern: post-resolution market making")

    findings["score"] = score
    findings["max_score"] = 5
    findings["reasons"] = reasons

    print(f"  Score: {score}/5")
    for r in reasons:
        print(f"    - {r}")

    return findings


def assess_execution_feasibility(trades: List[dict]) -> dict:
    """
    Assess if we can execute the strategy.

    Questions:
    - How fast do trades happen?
    - What infrastructure is needed?
    - Are there API limitations?
    """
    print("\n[2] EXECUTION FEASIBILITY")
    print("-" * 50)

    # Analyze trade frequency
    timestamps = sorted([t.get("timestamp", 0) for t in trades if t.get("timestamp")])

    # Calculate gaps between trades
    gaps = []
    for i in range(1, min(len(timestamps), 100000)):
        gap = timestamps[i] - timestamps[i-1]
        if 0 < gap < 60:  # Within same minute
            gaps.append(gap)

    findings = {
        "trade_frequency": {
            "total_trades": len(timestamps),
            "trades_per_day": len(timestamps) / 31 if timestamps else 0,  # 31 days
            "median_gap_seconds": statistics.median(gaps) if gaps else 0,
            "min_gap_seconds": min(gaps) if gaps else 0,
        },
        "infrastructure_needs": [
            "WebSocket connection to Polymarket",
            "Fast blockchain transaction submission",
            "Market resolution monitoring",
            "Automated trading bot",
        ]
    }

    # Score 1-5
    score = 0
    reasons = []

    # Trade frequency is high but manageable
    if findings["trade_frequency"]["trades_per_day"] > 50000:
        score += 1
        reasons.append(f"High volume ({findings['trade_frequency']['trades_per_day']:.0f} trades/day) - requires automation")
    else:
        score += 2
        reasons.append("Manageable trade volume")

    # Gap between trades
    if findings["trade_frequency"]["median_gap_seconds"] >= 1:
        score += 2
        reasons.append(f"Reasonable pace ({findings['trade_frequency']['median_gap_seconds']:.0f}s between trades)")
    else:
        score += 1
        reasons.append("Very fast trading required")

    # WebSocket is standard
    score += 1
    reasons.append("Standard API infrastructure needed")

    findings["score"] = min(score, 5)
    findings["max_score"] = 5
    findings["reasons"] = reasons

    print(f"  Score: {findings['score']}/5")
    for r in reasons:
        print(f"    - {r}")

    return findings


def assess_capital_requirements(trades: List[dict]) -> dict:
    """
    Assess capital requirements.

    Questions:
    - How much capital is deployed?
    - What's the minimum viable capital?
    - Is there position sizing?
    """
    print("\n[3] CAPITAL REQUIREMENTS")
    print("-" * 50)

    usdc_amounts = [t.get("usdc_amount", 0) for t in trades if t.get("usdc_amount", 0) > 0]

    findings = {
        "observed_capital": {
            "total_volume": sum(usdc_amounts),
            "median_trade": statistics.median(usdc_amounts) if usdc_amounts else 0,
            "mean_trade": statistics.mean(usdc_amounts) if usdc_amounts else 0,
            "max_trade": max(usdc_amounts) if usdc_amounts else 0,
            "p90_trade": sorted(usdc_amounts)[int(len(usdc_amounts) * 0.9)] if len(usdc_amounts) > 10 else 0,
        }
    }

    # Estimate minimum capital
    # Assume 50 concurrent positions at median size
    min_capital = findings["observed_capital"]["median_trade"] * 50
    comfortable_capital = findings["observed_capital"]["mean_trade"] * 100

    findings["estimated_minimum"] = min_capital
    findings["estimated_comfortable"] = comfortable_capital

    # Score 1-5 (higher = more accessible)
    score = 0
    reasons = []

    if min_capital < 500:
        score += 2
        reasons.append(f"Low minimum (~${min_capital:.0f})")
    elif min_capital < 5000:
        score += 1
        reasons.append(f"Moderate minimum (~${min_capital:.0f})")
    else:
        reasons.append(f"High minimum (~${min_capital:.0f})")

    if findings["observed_capital"]["median_trade"] < 20:
        score += 2
        reasons.append(f"Small position sizes (${findings['observed_capital']['median_trade']:.2f} median)")
    elif findings["observed_capital"]["median_trade"] < 100:
        score += 1
        reasons.append(f"Moderate position sizes (${findings['observed_capital']['median_trade']:.2f} median)")
    else:
        reasons.append(f"Large position sizes (${findings['observed_capital']['median_trade']:.2f} median)")

    # Can scale up/down
    score += 1
    reasons.append("Position sizing appears flexible")

    findings["score"] = min(score, 5)
    findings["max_score"] = 5
    findings["reasons"] = reasons

    print(f"  Score: {findings['score']}/5")
    for r in reasons:
        print(f"    - {r}")
    print(f"\n  Estimated minimum capital: ${min_capital:.0f}")
    print(f"  Recommended capital: ${comfortable_capital:.0f}")

    return findings


def assess_edge_sustainability(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    Assess if the edge will persist.

    Questions:
    - Why does this edge exist?
    - Will competition erode it?
    - Is it capacity constrained?
    """
    print("\n[4] EDGE SUSTAINABILITY")
    print("-" * 50)

    findings = {
        "edge_source_hypothesis": [
            "Post-resolution market making",
            "Providing liquidity to exiting traders",
            "Capturing spread on resolved tokens",
        ],
        "competition_analysis": {
            "barriers_to_entry": "Low - anyone can trade post-resolution",
            "competitive_moat": "Speed and automation",
            "market_capacity": "Limited by Polymarket volume",
        }
    }

    # Score 1-5
    score = 0
    reasons = []

    # Edge source is unclear
    score += 1
    reasons.append("Edge source: likely liquidity provision (unclear profitability)")

    # Low barriers to entry
    score += 1
    reasons.append("Low barriers - competition could erode edge")

    # Market is growing
    score += 1
    reasons.append("Polymarket volumes growing - more opportunity")

    # Capacity constrained
    score += 0
    reasons.append("Capacity constrained by market liquidity")

    findings["score"] = score
    findings["max_score"] = 5
    findings["reasons"] = reasons

    print(f"  Score: {findings['score']}/5")
    for r in reasons:
        print(f"    - {r}")

    return findings


def assess_risks(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    Assess risks of the strategy.

    Questions:
    - Smart contract risk?
    - Execution risk?
    - Market risk?
    """
    print("\n[5] RISK ASSESSMENT")
    print("-" * 50)

    findings = {
        "identified_risks": [
            {
                "risk": "Smart Contract Risk",
                "description": "Polymarket contracts could have bugs",
                "mitigation": "Use small positions, monitor contracts",
                "severity": "Medium"
            },
            {
                "risk": "Execution Risk",
                "description": "Trades may fail or be front-run",
                "mitigation": "Use appropriate gas, monitor success rate",
                "severity": "Medium"
            },
            {
                "risk": "Market Structure Risk",
                "description": "Post-resolution trading rules may change",
                "mitigation": "Monitor Polymarket announcements",
                "severity": "High"
            },
            {
                "risk": "Profitability Risk",
                "description": "Strategy may not be profitable after fees",
                "mitigation": "Paper trade first, calculate all costs",
                "severity": "High"
            },
            {
                "risk": "Competition Risk",
                "description": "Others may adopt same strategy",
                "mitigation": "Speed advantage, larger capital",
                "severity": "Medium"
            },
        ]
    }

    # Score 1-5 (higher = lower risk)
    high_risks = sum(1 for r in findings["identified_risks"] if r["severity"] == "High")
    medium_risks = sum(1 for r in findings["identified_risks"] if r["severity"] == "Medium")

    if high_risks >= 2:
        score = 2
        reasons = ["Multiple high-severity risks identified"]
    elif high_risks == 1:
        score = 3
        reasons = ["One high-severity risk, manageable"]
    else:
        score = 4
        reasons = ["Risks are manageable"]

    findings["score"] = score
    findings["max_score"] = 5
    findings["reasons"] = reasons

    print(f"  Score: {score}/5 (higher = lower risk)")
    print(f"  High severity risks: {high_risks}")
    print(f"  Medium severity risks: {medium_risks}")

    for risk in findings["identified_risks"]:
        print(f"\n  {risk['risk']} ({risk['severity']})")
        print(f"    {risk['description']}")
        print(f"    Mitigation: {risk['mitigation']}")

    return findings


def calculate_overall_score(assessments: dict) -> dict:
    """Calculate overall replicability score."""
    scores = [
        assessments["entry_signals"]["score"],
        assessments["execution"]["score"],
        assessments["capital"]["score"],
        assessments["sustainability"]["score"],
        assessments["risks"]["score"],
    ]

    total = sum(scores)
    max_total = 25

    return {
        "total_score": total,
        "max_score": max_total,
        "percentage": total / max_total * 100,
        "individual_scores": {
            "entry_signals": assessments["entry_signals"]["score"],
            "execution": assessments["execution"]["score"],
            "capital": assessments["capital"]["score"],
            "sustainability": assessments["sustainability"]["score"],
            "risks": assessments["risks"]["score"],
        },
        "recommendation": get_recommendation(total, max_total)
    }


def get_recommendation(total: int, max_total: int) -> str:
    """Get recommendation based on score."""
    pct = total / max_total * 100

    if pct >= 80:
        return "HIGHLY REPLICABLE - Strong signals, manageable execution, good risk/reward"
    elif pct >= 60:
        return "MODERATELY REPLICABLE - Some challenges but potentially viable"
    elif pct >= 40:
        return "CHALLENGING - Significant obstacles, proceed with caution"
    else:
        return "NOT RECOMMENDED - Too many unknowns or risks"


def main():
    parser = argparse.ArgumentParser(description="Replicability Assessment")
    parser.add_argument("--trades", type=str, default="data/account88888_trades_joined.json")
    parser.add_argument("--metadata", type=str, default="data/token_to_market_full.json")
    parser.add_argument("--output", type=str, help="Output JSON file")
    args = parser.parse_args()

    print("=" * 70)
    print("REPLICABILITY ASSESSMENT - Account88888 Strategy")
    print("=" * 70)

    trades, metadata = load_data(args.trades, args.metadata)
    print(f"Loaded {len(trades):,} trades, {len(metadata):,} tokens")

    assessments = {
        "entry_signals": assess_entry_signal_clarity(trades, metadata),
        "execution": assess_execution_feasibility(trades),
        "capital": assess_capital_requirements(trades),
        "sustainability": assess_edge_sustainability(trades, metadata),
        "risks": assess_risks(trades, metadata),
    }

    overall = calculate_overall_score(assessments)

    print("\n" + "=" * 70)
    print("OVERALL REPLICABILITY SCORE")
    print("=" * 70)
    print(f"\n  Total Score: {overall['total_score']}/{overall['max_score']} ({overall['percentage']:.0f}%)")
    print(f"\n  Breakdown:")
    for category, score in overall["individual_scores"].items():
        print(f"    {category.replace('_', ' ').title()}: {score}/5")

    print(f"\n  RECOMMENDATION: {overall['recommendation']}")

    # Key unknowns
    print("\n" + "=" * 70)
    print("KEY UNKNOWNS (Need More Data)")
    print("=" * 70)
    print("""
1. PROFITABILITY: We don't know if this is actually profitable
   - Need complete USDC data (currently 21%)
   - Need to calculate entry vs redemption value
   - Need to account for gas fees

2. COUNTERPARTY: Who is on the other side of these trades?
   - Market makers exiting?
   - Retail panic selling?
   - Protocol liquidity?

3. EDGE SOURCE: Why does this opportunity exist?
   - Is it a real arbitrage or liquidity provision?
   - Are they making money or losing money?

4. SUSTAINABILITY: Will it persist?
   - If profitable, competition will increase
   - Polymarket may change rules
""")

    results = {
        "assessments": assessments,
        "overall": overall,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if args.output:
        Path(args.output).parent.mkdir(exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
