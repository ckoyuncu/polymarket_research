# Parallel Analysis Tasks

**Branch:** `parallel-analysis`
**Context:** We're reverse-engineering Account88888's trading strategy on Polymarket. Key finding so far: **Orderbook imbalance is 77.8% predictive for BTC**.

---

## Task 1: Competitor Analysis

### Goal
Identify other successful traders and analyze their relationship to Account88888.

### Questions to Answer
1. Who else trades the same markets as Account88888?
2. Does Account88888 trade BEFORE or AFTER competitors?
3. Are there leader/follower patterns between accounts?
4. Is Account88888 leading the market or following others?

### How to Run
```bash
cd /Users/shem/Desktop/polymarket_starter/polymarket_starter
source venv/bin/activate
python scripts/reverse_engineer/competitor_tracker.py --limit 500000
```

### What to Look For
- Accounts with >60% win rates
- Timing correlation between Account88888 and other accounts
- Whether Account88888 trades in the same direction as competitors (copy trading?)
- Or opposite direction (adversarial?)

### Output Location
Results will be printed to stdout. Save interesting findings.

---

## Task 2: Dig Deeper into Orderbook Signal

### Goal
The orderbook imbalance signal shows **77.8% accuracy for BTC**. We need to understand:
1. WHY is this signal predictive?
2. Can we make it even more accurate?
3. How can we exploit it for trading?

### Background Data
- We have 90 final minute captures in `data/research_ec2_jan6/final_minute/`
- Each capture has ~300ms resolution Binance prices + orderbook snapshots
- The orderbook imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
- Positive imbalance (more bids) → predicted UP outcome

### Analysis to Perform

#### A. Time-Weighted Analysis
Does the signal get stronger closer to resolution? Check imbalance at:
- 60 seconds before
- 30 seconds before
- 10 seconds before

```python
# Load data from: data/research_ec2_jan6/final_minute/*.json
# Each file has 'orderbook_snapshots' with timestamps
# Compare imbalance accuracy at different time windows
```

#### B. Threshold Analysis
Is there a minimum imbalance threshold that improves accuracy?
- Currently using any imbalance (> 0 or < 0)
- Test thresholds: |imbalance| > 0.1, > 0.2, > 0.3
- Higher threshold = fewer trades but better accuracy?

#### C. Combined Signals
Does combining orderbook + price momentum improve accuracy?
- Current: Orderbook alone = 77.8%
- Current: Early momentum alone = 66.7%
- Combined: If both agree, what's accuracy?

#### D. Spread Analysis
Does the bid-ask spread correlate with signal reliability?
- Tight spread = more confident market?
- Wide spread = more uncertainty?

### Relevant Scripts
- `scripts/reverse_engineer/analyze_final_minute.py` - basic analysis (already run)
- `scripts/reverse_engineer/orderbook_imbalance_analyzer.py` - may have more features
- `scripts/reverse_engineer/spread_dynamics_analyzer.py` - spread analysis

### Key Data Structure
```json
{
  "orderbook_snapshots": [
    {
      "timestamp": 1767661500.123,
      "outcome": "up",
      "best_bid": 0.52,
      "best_ask": 0.54,
      "bid_depth": 1500.0,
      "ask_depth": 1200.0,
      "spread": 0.02,
      "mid_price": 0.53
    }
  ]
}
```

### Expected Output
Write findings to a new file or update analysis. Key deliverable:
- Refined signal with >80% accuracy if possible
- Clear trading rules (e.g., "trade when imbalance > 0.2 with 82% expected accuracy")

---

## Context: What We Know So Far

### Account88888 Stats
- Win rate: ~67% on BTC/ETH 15-min markets
- Trades near resolution (final minutes)
- Profitable despite -EV spread (market takes 3-5%)

### Analysis Done
| Analysis | Result |
|----------|--------|
| ML Model | 74% accuracy predicting direction |
| Orderbook Imbalance | **77.8% accuracy for BTC** |
| Early Momentum | 66.7% for BTC, 35.6% for ETH |
| Momentum Persistence | Only 16.7% of windows have consistent direction |

### Trackers Running on EC2
- `ubuntu@13.222.131.86` (SSH key: `~/.ssh/polymarket-bot-key-us-east.pem`)
- Final minute tracker: collecting data
- Multi-exchange tracker: running
- Orderbook tracker: running

---

## Notes for Agent
- Work on branch `parallel-analysis`
- Another agent is running gas/block analysis on `main` branch
- Commit your work when done
- Focus on actionable insights that can improve trading strategy
