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

if __name__=="__main__": unittest.main()
