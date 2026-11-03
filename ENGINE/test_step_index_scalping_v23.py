import unittest
from ENGINE.step_index_scalping_v23 import ema, direction, validate, detect

class ScalpingV23Tests(unittest.TestCase):
    def test_ema(self):
        self.assertAlmostEqual(ema([1,2,3],3),2.0)
    def test_direction(self):
        self.assertEqual(direction([{"close":float(x)} for x in range(1,50)]),"LONG")
    def test_closed_and_geometry_validation(self):
        rows=[{"epoch":0,"open":2,"high":3,"low":1,"close":2},{"epoch":60,"open":2,"high":1,"low":0,"close":2}]
        self.assertEqual(len(validate(rows,"M1",120)),1)
    def test_no_data_is_no_trade(self):
        self.assertFalse(detect({})["confirmed"])


    def test_paginated_history_returns_requested_closed_candles(self):
        import asyncio
        from unittest.mock import patch
        import ENGINE.step_index_scalping_v23 as engine

        rows = [
            {"epoch": 60 * i, "open": 10+i, "high": 11+i, "low": 9+i, "close": 10.5+i}
            for i in range(1, 13)
        ]

        async def fake_req(_ws, payload):
            end = payload["end"]
            count = payload["count"]
            eligible = rows if end == "latest" else [r for r in rows if r["epoch"] <= end]
            # Simulate an upstream API cap below the requested page size.
            return {"candles": eligible[-min(count, 3):]}

        async def run():
            with patch.object(engine, "req", fake_req):
                return await engine.fetch_candles(object(), "TEST", "M1", 8, 50, page_size=4)

        result = asyncio.run(run())
        self.assertEqual(len(result), 8)
        epochs = [r["epoch"] for r in result]
        self.assertEqual(epochs, sorted(epochs))
        self.assertEqual(len(set(epochs)), len(epochs))

    def test_execution_levels_long_and_short(self):
        from ENGINE.step_index_scalping_v23 import execution_levels
        long_levels=execution_levels("LONG",100,2)
        self.assertEqual(long_levels["entry"],100)
        self.assertAlmostEqual(long_levels["stop_loss"],97.6)
        self.assertAlmostEqual(long_levels["take_profit"],103.6)
        short_levels=execution_levels("SHORT",100,2)
        self.assertAlmostEqual(short_levels["stop_loss"],102.4)
        self.assertAlmostEqual(short_levels["take_profit"],96.4)

    def test_execution_levels_reject_invalid_inputs(self):
        from ENGINE.step_index_scalping_v23 import execution_levels
        self.assertIsNone(execution_levels("SHORT",None,2))
        self.assertIsNone(execution_levels("FLAT",100,2))

if __name__=="__main__": unittest.main()
