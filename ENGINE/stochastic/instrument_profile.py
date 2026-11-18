"""Instrument profile and explicit separation of quote units from money."""
from dataclasses import dataclass, asdict
@dataclass(frozen=True)
class InstrumentProfile:
    name: str = "Step Index"
    symbol: str | None = None
    quote_unit: str = "quoted_price_units"
    tick_size: float | None = None
    tick_value: float | None = None
    monetary_conversion_verified: bool = False
    source: str = "user/API supplied metadata; not inferred"
    def validate(self):
        if self.tick_size is not None and self.tick_size <= 0: raise ValueError("tick_size must be positive")
        if self.tick_value is not None and self.tick_value <= 0: raise ValueError("tick_value must be positive")
        if self.monetary_conversion_verified and (self.tick_size is None or self.tick_value is None): raise ValueError("verified monetary conversion requires tick_size and tick_value")
        return self
    def to_dict(self): return asdict(self)
