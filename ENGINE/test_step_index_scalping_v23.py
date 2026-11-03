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

if __name__=="__main__": unittest.main()
