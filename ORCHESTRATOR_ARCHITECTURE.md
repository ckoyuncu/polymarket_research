# Grand Orchestrator Architecture
## Autonomous Multi-Agent Futures Trading System

**Goal:** Build a fully autonomous system that runs without user intervention until reaching a solid, production-ready state.

---

## System Overview

```
                    ┌─────────────────────────────────────┐
                    │         GRAND ORCHESTRATOR          │
                    │   (Monitors, Coordinates, Decides)  │
                    └──────────────┬──────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
    ┌───────────┐           ┌───────────┐           ┌───────────┐
    │  PHASE 1  │           │  PHASE 2  │           │  PHASE 3  │
    │Foundation │──────────▶│  Feeds &  │──────────▶│ Strategy  │
    │ Exchange  │           │ Backtest  │           │   & Live  │
    └───────────┘           └───────────┘           └───────────┘
          │                        │                        │
    ┌─────┴─────┐            ┌─────┴─────┐            ┌─────┴─────┐
    │           │            │           │            │           │
 Agent 1    Agent 2       Agent 3    Agent 4       Agent 5    Agent 6
 Exchange   Paper         Data       Backtest      Strategy   Live
 Client     Trading       Feeds      Engine        Framework  Trading
    │           │            │           │            │           │
    └─────┬─────┘            └─────┬─────┘            └─────┬─────┘
          │                        │                        │
          ▼                        ▼                        ▼
    ┌───────────┐           ┌───────────┐           ┌───────────┐
    │    QA     │           │    QA     │           │    QA     │
    │ Validator │           │ Validator │           │ Validator │
    └───────────┘           └───────────┘           └───────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │       SENTINEL AGENT        │
                    │  (Continuous Error Monitor) │
                    └─────────────────────────────┘
```

---

## Agent Definitions

### 🎯 GRAND ORCHESTRATOR (Master Controller)

**Location:** `.claude/commands/orchestrator.md`

**Role:**
- Monitors all agents' progress
- Makes GO/NO-GO decisions between phases
- Handles errors and rollbacks
- Generates status reports
- Knows when the system is "complete"

**Triggers:**
- Runs continuously in a loop
- Checks agent status every completion
- Advances phases when conditions are met

---

### 📦 PHASE 1: Foundation (Exchange Infrastructure)

#### Agent 1: Exchange Client Builder
**File:** `.claude/agents/exchange-client.md`
**Purpose:** Build the core Hyperliquid exchange interface
**Deliverables:**
- `src/exchanges/base.py` - Abstract interface
- `src/exchanges/hyperliquid.py` - Full implementation
- `tests/test_exchanges.py` - Comprehensive tests
**Success Criteria:**
- [ ] Can connect to Hyperliquid testnet
- [ ] Can fetch account balance
- [ ] Can place/cancel orders
- [ ] Can fetch positions
- [ ] All tests pass

#### Agent 2: Paper Trading Simulator
**File:** `.claude/agents/paper-trading.md`
**Purpose:** Build paper trading mode for safe testing
**Deliverables:**
- `src/exchanges/paper.py` - Paper trading implementation
- Simulated order matching
- Position tracking
- P&L calculation
**Success Criteria:**
- [ ] Can simulate trades without real money
- [ ] Tracks virtual positions accurately
- [ ] Logs all simulated trades

#### QA-1: Phase 1 Validator
**File:** `.claude/agents/qa-phase1.md`
**Purpose:** Validate all Phase 1 deliverables
**Checks:**
- Run all exchange tests
- Verify testnet connectivity
- Test paper trading simulation
- Check code quality (types, docs)
**Gate:** Must pass 100% before Phase 2

---

### 📡 PHASE 2: Data & Backtesting

#### Agent 3: Data Feeds Builder
**File:** `.claude/agents/data-feeds.md`
**Purpose:** Build real-time data infrastructure
**Deliverables:**
- `src/feeds/orderbook.py` - L2 orderbook WebSocket
- `src/feeds/trades.py` - Trade stream
- `src/feeds/funding.py` - Funding rate feed
- `scripts/fetch_data.py` - Historical data fetcher
**Success Criteria:**
- [ ] WebSocket connects and streams data
- [ ] Auto-reconnect on disconnect
- [ ] Can fetch historical OHLCV
- [ ] Data stored in `data/historical/`

#### Agent 4: Backtest Engine Builder
**File:** `.claude/agents/backtest-engine.md`
**Purpose:** Build backtesting infrastructure with pwb-toolbox
**Deliverables:**
- `src/backtest/engine.py` - Core backtest engine
- `src/backtest/metrics.py` - Performance metrics (Sharpe, DD, etc.)
- `scripts/run_backtest.py` - CLI runner
- Integration with pwb-toolbox
**Success Criteria:**
- [ ] Can run backtest on historical data
- [ ] Calculates accurate metrics
- [ ] Generates performance reports
- [ ] Matches pwb-toolbox patterns

#### QA-2: Phase 2 Validator
**File:** `.claude/agents/qa-phase2.md`
**Purpose:** Validate data feeds and backtest engine
**Checks:**
- WebSocket stability test (10 min continuous)
- Historical data completeness
- Backtest accuracy validation
- Performance metric verification

---

### 🧠 PHASE 3: Strategy & Live Trading

#### Agent 5: Strategy Framework Builder
**File:** `.claude/agents/strategy-framework.md`
**Purpose:** Build the strategy development framework
**Deliverables:**
- `src/strategies/base.py` - BaseStrategy class
- `src/risk/position.py` - Position sizing
- `src/risk/limits.py` - Risk limits (kill switch, max loss)
- `config/risk.yaml` - Risk parameters
- Example strategy in `src/strategies/examples/`
**Success Criteria:**
- [ ] Clean strategy interface
- [ ] Risk controls enforced
- [ ] Kill switch functional
- [ ] Example strategy runs in backtest

#### Agent 6: Live Trading Runner
**File:** `.claude/agents/live-trading.md`
**Purpose:** Build the live trading infrastructure
**Deliverables:**
- `scripts/run_live.py` - Live trading CLI
- Integration with exchange client
- Real-time signal processing
- Trade logging and monitoring
**Success Criteria:**
- [ ] Can run in paper mode safely
- [ ] Connects to exchange feeds
- [ ] Executes strategy signals
- [ ] Logs all activity

#### QA-3: Phase 3 Validator
**File:** `.claude/agents/qa-phase3.md`
**Purpose:** Final validation before "complete" state
**Checks:**
- Full system integration test
- Paper trading 1-hour burn-in
- Risk controls verification
- Documentation completeness

---

### 🛡️ SENTINEL AGENT (Continuous Monitor)

**File:** `.claude/agents/sentinel.md`
**Purpose:** Runs alongside all phases, monitors for errors
**Responsibilities:**
- Watch for Python exceptions in any agent
- Monitor test failures
- Check for circular imports
- Verify no secrets in code
- Alert on critical issues

**Runs:** In background, checks every agent completion

---

## Skill Definitions

### Core Skills (Used by Multiple Agents)

| Skill | Location | Purpose |
|-------|----------|---------|
| `test-runner` | `.claude/skills/test-runner/` | Run pytest, report results |
| `code-quality` | `.claude/skills/code-quality/` | Black, mypy, lint checks |
| `git-operations` | `.claude/skills/git-operations/` | Commit, branch, PR creation |
| `status-reporter` | `.claude/skills/status-reporter/` | Generate phase status reports |
| `error-handler` | `.claude/skills/error-handler/` | Standard error handling patterns |

---

## Orchestration Flow

```python
# Pseudo-code for Grand Orchestrator logic

def orchestrate():
    # Phase 1: Foundation
    run_parallel([Agent1_Exchange, Agent2_Paper])
    wait_for_completion()

    result = run(QA1_Validator)
    if not result.passed:
        run(ErrorHandler, context=result.errors)
        retry_phase(1)
        return

    # Phase 2: Data & Backtest
    run_parallel([Agent3_DataFeeds, Agent4_BacktestEngine])
    wait_for_completion()

    result = run(QA2_Validator)
    if not result.passed:
        run(ErrorHandler, context=result.errors)
        retry_phase(2)
        return

    # Phase 3: Strategy & Live
    run_parallel([Agent5_Strategy, Agent6_LiveTrading])
    wait_for_completion()

    result = run(QA3_Validator)
    if not result.passed:
        run(ErrorHandler, context=result.errors)
        retry_phase(3)
        return

    # System Complete
    generate_final_report()
    update_status("COMPLETE - Ready for strategy development")
```

---

## File Structure After Implementation

```
.claude/
├── commands/
│   └── orchestrator.md          # Grand Orchestrator skill
├── agents/
│   ├── exchange-client.md       # Agent 1
│   ├── paper-trading.md         # Agent 2
│   ├── data-feeds.md            # Agent 3
│   ├── backtest-engine.md       # Agent 4
│   ├── strategy-framework.md    # Agent 5
│   ├── live-trading.md          # Agent 6
│   ├── qa-phase1.md             # QA Validator 1
│   ├── qa-phase2.md             # QA Validator 2
│   ├── qa-phase3.md             # QA Validator 3
│   └── sentinel.md              # Error Monitor
└── skills/
    ├── test-runner/
    │   └── SKILL.md
    ├── code-quality/
    │   └── SKILL.md
    ├── git-operations/
    │   └── SKILL.md
    ├── status-reporter/
    │   └── SKILL.md
    └── error-handler/
        └── SKILL.md
```

---

## Success Metrics

### Phase Completion Criteria

| Phase | Metric | Target |
|-------|--------|--------|
| Phase 1 | Exchange tests pass | 100% |
| Phase 1 | Testnet connection | Working |
| Phase 2 | WebSocket uptime | >99% over 10 min |
| Phase 2 | Backtest runs | No errors |
| Phase 3 | Paper trade session | 1 hour clean |
| Phase 3 | Risk controls | All enforced |

### System "Complete" Definition

The system is considered **complete** when:
1. All 6 agents have delivered their components
2. All 3 QA validators pass
3. A 1-hour paper trading session runs without errors
4. Documentation is complete (CLAUDE.md, README.md updated)
5. All code has type hints and docstrings
6. Test coverage >80%

---

## Execution Commands

### Start Full Orchestration
```bash
# This runs everything autonomously
claude /orchestrator
```

### Run Single Phase
```bash
claude /orchestrator --phase 1
claude /orchestrator --phase 2
claude /orchestrator --phase 3
```

### Check Status
```bash
claude /orchestrator --status
```

### Run Specific Agent
```bash
claude "Run Agent 1: Exchange Client Builder"
claude "Run Agent 3: Data Feeds Builder"
```

---

## Error Recovery

### Automatic Retry Logic
- Each phase can retry up to 3 times
- Errors are logged to `logs/orchestrator.log`
- Sentinel agent can pause execution on critical errors

### Manual Intervention Points
- Kill switch: Create `.kill_switch` file
- Pause: Create `.pause_orchestrator` file
- Resume: Remove pause file

### Rollback Capability
- Each phase creates a git branch
- Failed phases can rollback to branch start
- Clean state preserved

---

## Timeline Estimate

| Phase | Agents | Parallel? |
|-------|--------|-----------|
| Phase 1 | 2 + QA | Yes |
| Phase 2 | 2 + QA | Yes |
| Phase 3 | 2 + QA | Yes |
| **Total** | **9 agents** | **3 parallel batches** |

---

## Next Steps

1. **Approve this architecture**
2. **Create all agent definition files** (`.claude/agents/*.md`)
3. **Create all skill files** (`.claude/skills/*/SKILL.md`)
4. **Create the Grand Orchestrator** (`.claude/commands/orchestrator.md`)
5. **Run `/orchestrator` and let it build everything**

---

*This architecture maximizes Claude Code's agent parallelism, provides quality gates between phases, includes continuous error monitoring, and defines clear completion criteria.*
