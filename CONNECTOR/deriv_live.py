"""READ-ONLY Deriv market-data connector for SQAO.

Autodetects a Step Index, seeds completed M1/M5/M15/H1/D1 candles,
streams ticks, maintains all five live timeframes, and writes a fresh
analysis snapshot after each completed M1 candle.

No trading/account calls are present.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import websockets

PUBLIC_WS = "wss://api.derivws.com/trading/v1/options/ws/public"
TIMEFRAME_LABELS = {1: "M1", 5: "M5", 15: "M15", 60: "H1", 240: "H4"}


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    timeframe: str

    def to_dict(self):
        return asdict(self)


class CandleAggregator:
    """Build completed OHLC candles for every timeframe consumed by SQAO."""

    def __init__(self, timeframes=(1, 5, 15, 60, 240)):
        unknown = set(timeframes) - set(TIMEFRAME_LABELS)
        if unknown:
            raise ValueError(f"Unsupported candle timeframes: {sorted(unknown)}")
        self.timeframes = tuple(timeframes)
        self.current: dict[int, Candle] = {}

    @staticmethod
    def bucket(epoch: int, minutes: int) -> int:
        size = minutes * 60
        return epoch - (epoch % size)

    def update(self, epoch: int, price: float):
        emitted = []
        for tf in self.timeframes:
            start = self.bucket(epoch, tf)
            candle = self.current.get(tf)
            if candle is None or candle.timestamp != start:
                if candle is not None:
                    emitted.append(candle)
                candle = Candle(start, price, price, price, price, TIMEFRAME_LABELS[tf])
                self.current[tf] = candle
            else:
                candle.high = max(candle.high, price)
                candle.low = min(candle.low, price)
                candle.close = price
        return emitted


async def receive_matching(ws, req_id: int):
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("error"):
            error = msg["error"]
            raise RuntimeError(error.get("message", str(error)))
        if msg.get("req_id") == req_id or msg.get("msg_type") in {"active_symbols", "candles", "history"}:
            return msg


async def autodetect_symbol(ws):
    req_id = 1001
    await ws.send(json.dumps({"active_symbols": "brief", "req_id": req_id}))
    msg = await receive_matching(ws, req_id)
    candidates = []
    for item in msg.get("active_symbols", []):
        name = str(item.get("underlying_symbol_name", item.get("display_name", "")))
        symbol = str(item.get("underlying_symbol", item.get("symbol", "")))
        text = f"{name} {symbol}".lower()
        if "step index" in text:
            candidates.append((name, symbol))
    if not candidates:
        raise RuntimeError("No active Step Index symbol found")

    preferred = os.getenv("DERIV_STEP_NAME", "").strip().lower()
    if preferred:
        for name, symbol in candidates:
            if preferred == symbol.lower() or preferred in name.lower():
                return symbol
    return candidates[0][1]


async def seed_history(ws, symbol: str, output: Path, count: int = 500):
    now = int(datetime.now(timezone.utc).timestamp())
    for tf, granularity, label in (
        (1, 60, "M1"),
        (5, 300, "M5"),
        (15, 900, "M15"),
        (60, 3600, "H1"),
        (240, 14400, "H4"),
    ):
        req_id = 1100 + tf
        payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": count,
            "style": "candles",
            "granularity": granularity,
            "adjust_start_time": 1,
            "subscribe": 1,
            "req_id": req_id,
        }
        await ws.send(json.dumps(payload))
        msg = await receive_matching(ws, req_id)
        candles = msg.get("candles", [])
        if not candles:
            raise RuntimeError(f"No historical candles returned for {label} / {symbol}")

        path = output / f"ohlc_{label}.csv"
        written = 0
        with path.open("w", encoding="utf-8") as f:
            f.write("timestamp,open,high,low,close,timeframe\n")
            for c in candles:
                epoch = int(c["epoch"])
                # Do not seed an in-progress candle and then append a duplicate
                # when the live aggregator closes that same time bucket.
                if epoch + granularity > now:
                    continue
                f.write(
                    f"{epoch},{float(c['open'])},{float(c['high'])},"
                    f"{float(c['low'])},{float(c['close'])},{label}\n"
                )
                written += 1
        if written == 0:
            raise RuntimeError(f"No completed historical candles returned for {label} / {symbol}")
    print(f"HISTORY_SEEDED symbol={symbol} count={count} completed_only=true", flush=True)


def load_engine_frames(output: Path):
    """Load only completed, timestamped candles for the canonical v23 detector."""
    frames = {}
    for tf in ("M1", "M5", "M15", "H1", "H4"):
        path = output / f"ohlc_{tf}.csv"
        rows = {}
        if path.exists():
            import csv
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    try:
                        epoch = int(row["timestamp"])
                        values = {k: float(row[k]) for k in ("open", "high", "low", "close")}
                        if not all(math.isfinite(v) for v in values.values()):
                            continue
                        rows[epoch] = {"epoch": epoch, **values}
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
        frames[tf] = [rows[k] for k in sorted(rows)]
    return frames


def run_analysis(output: Path, next_open=None):
    """Use the same v23 detector as research; fail closed without verified costs."""
    try:
        from ENGINE.step_index_scalping_v23 import TF, detect, synchronize_frames

        frames = load_engine_frames(output)
        if not frames["M1"]:
            result = {"decision": "NO_TRADE", "state": "INSUFFICIENT_DATA"}
        else:
            decision_epoch = int(frames["M1"][-1]["epoch"]) + TF["M1"]
            aligned = synchronize_frames(frames, decision_epoch)
            setup = detect(aligned, next_open=next_open)
            result = {
                "decision": "NO_TRADE",
                "strategy": "SQAO_STEP_INDEX_V23_CANONICAL",
                "state": setup.get("state", "NO_TRADE"),
                "setup": setup,
                "cost_gate": "BLOCKED_MISSING_VERIFIABLE_ALL_IN_COST",
                "read_only": True,
                "decision_epoch": decision_epoch,
                "data_counts": {tf: len(rows) for tf, rows in aligned.items()},
                "latest_closed": {tf: rows[-1] if rows else None for tf, rows in aligned.items()},
            }
        result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = output / "live_analysis.json.tmp"
        target = output / "live_analysis.json"
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        tmp.replace(target)
        print(f"ANALYSIS_UPDATED decision=NO_TRADE state={result.get('state')}", flush=True)
    except Exception as exc:
        print(f"ANALYSIS_ERROR: {exc}", flush=True)


async def run():
    symbol = os.getenv("DERIV_SYMBOL", "AUTO")
    output = Path(os.getenv("SQAO_DATA_DIR", "DATA"))
    output.mkdir(parents=True, exist_ok=True)
    history_count = int(os.getenv("SQAO_HISTORY_CANDLES", "500"))
    delay = 1

    while True:
        try:
            # Reset the aggregator after reconnect so candles from a previous
            # socket session cannot be emitted into the new session.
            aggregator = CandleAggregator()
            async with websockets.connect(PUBLIC_WS, ping_interval=20, ping_timeout=20) as ws:
                if symbol.upper() == "AUTO":
                    symbol = await autodetect_symbol(ws)
                    print(f"AUTO_SYMBOL={symbol}", flush=True)

                await seed_history(ws, symbol, output, history_count)
                run_analysis(output)

                await ws.send(json.dumps({"ticks": symbol, "subscribe": 1, "req_id": 1}))
                print(f"CONNECTED symbol={symbol}", flush=True)
                delay = 1

                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("error"):
                        error = msg["error"]
                        raise RuntimeError(error.get("message", str(error)))
                    if msg.get("msg_type") != "tick":
                        continue

                    tick = msg["tick"]
                    epoch = int(tick["epoch"])
                    price = float(tick["quote"])

                    with (output / "ticks.ndjson").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"timestamp": epoch, "price": price, "symbol": symbol}) + "\n")

                    emitted = aggregator.update(epoch, price)
                    for candle in emitted:
                        path = output / f"ohlc_{candle.timeframe}.csv"
                        with path.open("a", encoding="utf-8") as f:
                            f.write(
                                f"{candle.timestamp},{candle.open},{candle.high},"
                                f"{candle.low},{candle.close},{candle.timeframe}\n"
                            )
                    # Persist every timeframe that closed on this tick before
                    # reading the files for analysis (M5/M15/H1/D1 can close
                    # on the same tick as M1).
                    if any(candle.timeframe == "M1" for candle in emitted):
                        current_m1 = aggregator.current.get(1)
                        next_open = None
                        if current_m1 is not None:
                            next_open = {"epoch": current_m1.timestamp, "open": current_m1.open}
                        run_analysis(output, next_open=next_open)

                    print(
                        datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
                        price,
                        flush=True,
                    )
        except KeyboardInterrupt:
            return
        except Exception as exc:
            print(f"CONNECTOR_ERROR: {exc}; reconnecting in {delay}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


if __name__ == "__main__":
    asyncio.run(run())
