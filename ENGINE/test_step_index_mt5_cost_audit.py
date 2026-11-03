from ENGINE.step_index_mt5_cost_audit import audit


def test_history_transcription_and_contract_arithmetic():
    report = audit()
    summary = report["history_summary"]
    assert summary["closed_deals_sampled"] == 8
    assert summary["gross_profit_usd"] == 8.90
    assert summary["wins"] == 6
    assert summary["losses"] == 2
    assert summary["pnl_contract_model_consistent"] is True


def test_unknown_costs_and_tick_conversion_remain_blocked():
    report = audit()
    assert report["cost_gate"]["spread_observed_price_units"] == 0.1
    assert report["cost_gate"]["commission_price_units"] is None
    assert report["cost_gate"]["slippage_price_units"] is None
    assert report["cost_gate"]["round_trip_cost_price_units"] is None
    assert report["cost_gate"]["backtest_net_enabled"] is False
    assert report["monetary_risk_gate"]["enabled"] is False
    assert report["decision"] == "NO_TRADE"
