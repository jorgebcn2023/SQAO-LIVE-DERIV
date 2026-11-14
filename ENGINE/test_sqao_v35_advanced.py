"""Tests for advanced SQAO V3.5 diagnostics."""
import math
from ENGINE.sqao_v35_advanced import (
    ljung_box, adx_di, atr_value, market_structure, fair_value_gaps,
    order_block_candidates, walk_forward_splits, evaluate_walk_forward,
)


def test_ljung_box_white_noise_and_limits():
    assert ljung_box([1,2,3])["status"] == "INSUFFICIENT_SAMPLE"
    result=ljung_box([math.sin(i*2.399) for i in range(300)],10)
    assert result["status"] == "OK"
    assert 0 <= result["p_value"] <= 1


def test_atr_adx_sample_guard():
    assert atr_value([{"high":2,"low":1,"close":1.5}],14) is None
    assert adx_di([{"high":2,"low":1,"close":1.5}],14)["status"] == "INSUFFICIENT_SAMPLE"


def test_fvg_mechanical_definitions():
    rows=[{"high":10,"low":8},{"high":11,"low":9},{"high":13,"low":12}]
    zones=fair_value_gaps(rows)
    assert zones == [{"type":"BULLISH_FVG","lower":10.0,"upper":12.0,"formed_index":2}]


def test_structure_needs_confirmed_swings():
    assert market_structure([{"high":1,"low":0,"close":0.5}]*5)["status"] == "INSUFFICIENT_SAMPLE"


def test_order_block_is_only_candidate():
    rows=[]
    for i in range(30):
        p=100+math.sin(i)*0.2
        rows.append({"open":p,"high":p+0.1,"low":p-0.1,"close":p})
    assert isinstance(order_block_candidates(rows,5),list)


def test_walk_forward_is_chronological():
    splits=walk_forward_splits(300,0.6,0.2,3)
    assert splits
    for s in splits:
        assert s["train_end"] <= s["validation_end"] <= s["test_end"]
        assert s["train_end"] == s["validation_start"]
        assert s["validation_end"] == s["test_start"]


def test_walk_forward_evaluator_receives_disjoint_time_order():
    out=evaluate_walk_forward(list(range(100)),lambda tr,va,te:{"n_train":len(tr),"n_val":len(va),"n_test":len(te)},folds=2)
    assert out["status"] == "OK"
    assert all(x["metrics"]["n_test"]>0 for x in out["folds"])
