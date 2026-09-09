from .quant import atr, win_rate, profit_factor
from .predictive import build_hour_scenarios
from .live_pipeline import analyze_rows, direction, ema, rsi

assert atr([2, 3, 4, 5], [1, 2, 3, 4], [1.5, 2.5, 3.5, 4.5], period=2) is not None
assert round(win_rate([1, -1, 1]), 6) == round(2 / 3, 6)
assert profit_factor([1, -1, 2]) == 3.0
sc = build_hour_scenarios(True, True, True)
assert len(sc) == 3
assert abs(sum(x.score for x in sc) - 100.0) < 0.2
assert ema(list(range(1, 25)), 10) is not None
assert rsi(list(range(1, 30)), 14) == 100.0

rows = []
for i in range(40):
    p = 100.0 + i * 0.1
    rows.append({"timestamp": str(1_700_000_000 + i * 60), "open": str(p), "high": str(p + 0.2), "low": str(p - 0.1), "close": str(p)})
assert direction(rows) == "BULLISH"
frames = {tf: rows for tf in ("D1", "H1", "M15", "M5", "M1")}
result = analyze_rows(frames)
assert result["data_complete"] is True
assert result["decision"] in {"LONG", "SHORT", "WAIT", "NO_TRADE"}
assert set(result["timeframes"]) == {"D1", "H1", "M15", "M5", "M1"}
print("SQAO tests: OK")
