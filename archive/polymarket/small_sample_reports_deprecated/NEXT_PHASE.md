# Next Phase: Round 2 Development Plan

**Generated:** 2026-01-06
**Status:** Ready for Round 2 Agents

---

## Round 1 Accomplishments

### Agent 1: Test & Production Readiness
- Created 50 comprehensive tests (executor + risk controls)
- Identified 5 critical gaps in executor layer
- Documented all P0/P1/P2 fixes needed
- Deliverable: `LIVE_READINESS_ASSESSMENT.md`, `tests/`

### Agent 2: Live Trading Bot
- Built conservative $300-capital trading bot
- Implemented kill switches, loss limits, cooldowns
- Uses ORDERBOOK_SIGNAL_FINDINGS.md rules
- Deliverable: `src/trading/live_bot.py`

### Agent 3: Model Improvements
- Fixed V1's data leakage (74% was wrong, true: 67.7%)
- Implemented proper time-series validation
- Discovered confidence thresholds: >= 0.4 achieves 90%+ accuracy
- Deliverable: `signal_discovery_model_v2.py`, `MODEL_IMPROVEMENTS.md`

### Agent 4: Market Mechanics Research
- Documented complete fee structure (0-3% variable taker)
- Calculated break-even thresholds (52% at 50% odds)
- Confirmed economics work (84% >> 52%)
- Deliverable: `MARKET_CONSTRAINTS_AND_FEES.md`

### Agent 5: Meta-Synthesis (This Agent)
- Synthesized all findings into CONDITIONAL GO recommendation
- Updated CLAUDE.md with new context
- Created Round 2 agent prompts
- Deliverable: `SYSTEM_SYNTHESIS.md`, `NEXT_PHASE.md`, `agents_round2.md`

---

## Round 2 Agents (Priority Order)

### Agent 6: Executor Hardening (P0 - Critical)
**Priority:** HIGHEST
**Objective:** Fix all P0 gaps identified by Agent 1

Tasks:
1. Add 5s timeout to all API calls in `executor.py`
2. Implement retry with exponential backoff (3 attempts)
3. Add kill switch file check (`.kill_switch`)
4. Update tests to verify fixes

### Agent 7: Balance Checker (P0 - Critical)
**Priority:** HIGHEST
**Objective:** Implement working balance pre-check

Tasks:
1. Implement on-chain USDC balance query using web3.py
2. Add balance caching with 30s TTL
3. Pre-check balance before every order
4. Add test coverage

### Agent 8: Paper Trading Validator (P1)
**Priority:** HIGH
**Objective:** Run 3-7 day paper trading validation

Tasks:
1. Configure live_bot.py for paper trading
2. Run continuous paper trading
3. Log all decisions and outcomes
4. Generate performance report
5. Validate model accuracy matches expectations (90%+ at conf >= 0.4)

### Agent 9: WebSocket Reliability (P1)
**Priority:** MEDIUM
**Objective:** Add auto-reconnect to WebSocket client

Tasks:
1. Implement reconnect with exponential backoff
2. Add heartbeat/ping-pong detection
3. Handle subscription resubscription on reconnect
4. Add connection health monitoring

### Agent 10: Monitoring & Alerts (P2)
**Priority:** LOWER
**Objective:** Add operational visibility

Tasks:
1. Implement Discord webhook for critical alerts
2. Add health endpoint for external monitoring
3. Centralized logging setup
4. Daily summary reports

---

## Recommended Round 2 Sequence

```
Agents 6 + 7 (Parallel): Fix P0 executor gaps
    ↓
Agent 8: Paper trading validation (3-7 days)
    ↓
Agent 9: WebSocket reliability
    ↓
Agent 10: Monitoring (if time permits)
```

### Launch Command
```bash
# Run agents 6 and 7 in parallel first
./launch_agents_round2.sh
```

---

## Blockers Requiring Human Decision

### Blocker 1: py-clob-client Balance Bug
**Issue:** The `get_balance_allowance` method in py-clob-client returns incorrect data.
**Options:**
1. Fork and fix py-clob-client (complex)
2. Use web3.py for on-chain balance check (recommended)
3. Trust API will reject insufficient funds (risky)

**Human Decision Needed:** Approve Option 2 (web3.py balance check)

### Blocker 2: Paper Trading Duration
**Issue:** How long to paper trade before live?
**Options:**
1. 3 days (minimum, aggressive)
2. 7 days (recommended, conservative)
3. Until 100 trades complete (milestone-based)

**Human Decision Needed:** Choose paper trading duration

### Blocker 3: Initial Live Capital
**Issue:** How much capital for initial live testing?
**Options:**
1. $50 (most conservative)
2. $100 (moderate)
3. Full $300 (aggressive)

**Human Decision Needed:** Choose initial live capital amount

---

## Success Metrics for Round 2

| Metric | Target | Validation |
|--------|--------|------------|
| P0 fixes complete | 100% | All 4 items from synthesis |
| Test coverage | > 70% | pytest --cov |
| Paper trade win rate | > 70% | Live signal tester logs |
| Paper trade days | >= 3 | Timestamp validation |
| Model confidence hit rate | > 40% | Signal with conf >= 0.4 |
| WebSocket uptime | > 99% | Connection logs |

---

## Files to Create in Round 2

| Agent | Files |
|-------|-------|
| Agent 6 | Modified `executor.py` |
| Agent 7 | New `src/trading/balance_checker.py` |
| Agent 8 | `PAPER_TRADING_REPORT.md` |
| Agent 9 | Modified `src/api/clob_ws.py` |
| Agent 10 | `src/monitoring/alerts.py`, `src/monitoring/health.py` |

---

## Post Round 2: Go-Live Checklist

After Round 2 completes, verify:

- [ ] All P0 fixes merged
- [ ] Paper trading shows > 70% win rate
- [ ] Paper trading shows positive P&L
- [ ] Model accuracy at conf >= 0.4 is > 85%
- [ ] Balance checking works
- [ ] WebSocket reconnects properly
- [ ] Kill switch tested and working
- [ ] Human approves go-live

---

*Document created by Agent 5 - Meta-Agent*
