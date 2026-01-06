"""Strategy specification format."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Any, Optional
import json
import yaml


class StrategyType(Enum):
    """Types of strategies."""
    ALPHA_MINED = "alpha_mined"
    WALLET_CLONED = "wallet_cloned"


@dataclass
class Condition:
    """A condition that must be met to trigger an action."""
    # Feature to evaluate
    feature: str  # e.g., "spread_bps", "mid_delta", "t_since_start"
    
    # Comparison operator
    operator: str  # "gt", "lt", "eq", "gte", "lte"
    
    # Threshold value
    value: float
    
    # Optional: time window (seconds)
    time_window: Optional[int] = None
    
    def evaluate(self, feature_value: float) -> bool:
        """Evaluate this condition."""
        ops = {
            "gt": lambda x, y: x > y,
            "lt": lambda x, y: x < y,
            "eq": lambda x, y: x == y,
            "gte": lambda x, y: x >= y,
            "lte": lambda x, y: x <= y,
        }
        return ops[self.operator](feature_value, self.value)


@dataclass
class Action:
    """Action to take when conditions are met."""
    type: str  # "buy", "sell", "close", "noop"
    
    # Position sizing
    size: Optional[float] = None  # Absolute size
    size_pct: Optional[float] = None  # Percentage of capital
    
    # Price constraints
    limit_price: Optional[float] = None
    max_slippage_bps: Optional[int] = 100  # Max 1% slippage default
    
    # Risk management
    stop_loss_bps: Optional[int] = None
    take_profit_bps: Optional[int] = None


@dataclass
class StrategySpec:
    """
    Deterministic, replayable strategy specification.
    
    Can be serialized to JSON/YAML and executed deterministically.
    """
    # Metadata
    name: str
    version: str
    type: StrategyType
    created_at: int
    
    # Source information
    source: Dict[str, Any] = field(default_factory=dict)  # Wallet address, miner config, etc.
    
    # Market filters
    market_filters: Dict[str, Any] = field(default_factory=dict)
    
    # Entry conditions (ALL must be true)
    entry_conditions: List[Condition] = field(default_factory=list)
    
    # Exit conditions (ANY can be true)
    exit_conditions: List[Condition] = field(default_factory=list)
    
    # Actions
    entry_action: Optional[Action] = None
    exit_action: Optional[Action] = None
    
    # Performance metrics (from backtesting)
    metrics: Dict[str, float] = field(default_factory=dict)
    
    # Audit trail
    backtest_period: Optional[Dict[str, int]] = None  # start_ts, end_ts
    
    def to_json(self) -> str:
        """Serialize to JSON."""
        data = asdict(self)
        # Convert enums to strings
        data["type"] = self.type.value
        return json.dumps(data, indent=2)
    
    def to_yaml(self) -> str:
        """Serialize to YAML."""
        data = asdict(self)
        data["type"] = self.type.value
        return yaml.dump(data, default_flow_style=False)
    
    @classmethod
    def from_json(cls, json_str: str):
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return cls._from_dict(data)
    
    @classmethod
    def from_yaml(cls, yaml_str: str):
        """Deserialize from YAML."""
        data = yaml.safe_load(yaml_str)
        return cls._from_dict(data)
    
    @classmethod
    def _from_dict(cls, data: Dict):
        """Convert dict to StrategySpec."""
        # Convert type string back to enum
        data["type"] = StrategyType(data["type"])
        
        # Convert conditions
        data["entry_conditions"] = [
            Condition(**c) for c in data.get("entry_conditions", [])
        ]
        data["exit_conditions"] = [
            Condition(**c) for c in data.get("exit_conditions", [])
        ]
        
        # Convert actions
        if data.get("entry_action"):
            data["entry_action"] = Action(**data["entry_action"])
        if data.get("exit_action"):
            data["exit_action"] = Action(**data["exit_action"])
        
        return cls(**data)
    
    def save(self, filepath: str, format: str = "json"):
        """Save to file."""
        with open(filepath, 'w') as f:
            if format == "json":
                f.write(self.to_json())
            elif format == "yaml":
                f.write(self.to_yaml())
            else:
                raise ValueError(f"Unsupported format: {format}")
    
    @classmethod
    def load(cls, filepath: str):
        """Load from file."""
        with open(filepath, 'r') as f:
            content = f.read()
            if filepath.endswith('.json'):
                return cls.from_json(content)
            elif filepath.endswith('.yaml') or filepath.endswith('.yml'):
                return cls.from_yaml(content)
            else:
                raise ValueError(f"Unsupported file extension: {filepath}")
