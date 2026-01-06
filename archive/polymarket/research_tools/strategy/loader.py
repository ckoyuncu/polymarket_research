"""Strategy loader and validator."""
from pathlib import Path
from typing import List
from .spec import StrategySpec


class StrategyLoader:
    """Load and validate strategies from files."""
    
    def __init__(self, strategies_dir: str = "strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.strategies_dir.mkdir(exist_ok=True)
    
    def load_all(self) -> List[StrategySpec]:
        """Load all strategies from directory."""
        strategies = []
        
        for filepath in self.strategies_dir.glob("*.json"):
            try:
                strategy = StrategySpec.load(str(filepath))
                strategies.append(strategy)
            except Exception as e:
                print(f"Error loading {filepath}: {e}")
        
        for filepath in self.strategies_dir.glob("*.yaml"):
            try:
                strategy = StrategySpec.load(str(filepath))
                strategies.append(strategy)
            except Exception as e:
                print(f"Error loading {filepath}: {e}")
        
        return strategies
    
    def load_by_name(self, name: str) -> StrategySpec:
        """Load a specific strategy by name."""
        for ext in ['.json', '.yaml', '.yml']:
            filepath = self.strategies_dir / f"{name}{ext}"
            if filepath.exists():
                return StrategySpec.load(str(filepath))
        
        raise FileNotFoundError(f"Strategy '{name}' not found")
    
    def save(self, strategy: StrategySpec, format: str = "json"):
        """Save a strategy to the strategies directory."""
        filename = f"{strategy.name}.{format}"
        filepath = self.strategies_dir / filename
        strategy.save(str(filepath), format=format)
        print(f"✓ Saved strategy: {filepath}")
        return filepath
