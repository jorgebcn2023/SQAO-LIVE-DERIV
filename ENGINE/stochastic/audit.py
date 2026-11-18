"""Research-only audit orchestration."""
from .increment_distribution import increments, describe
from .runs_test import runs_test
from .variance_ratio import variance_ratio
from .hurst_rolling import hurst_rs, hurst_dfa
from .arcsine_diagnostics import occupation_fraction
from .monte_carlo import block_bootstrap
from .regime_classifier import classify
from .instrument_profile import InstrumentProfile

def run_stochastic_audit(closes, *, profile=None, q_values=(2,5,10,20), paths=2000, seed=20261118):
    profile=(profile or InstrumentProfile()).validate()
    px=[float(v) for v in closes]
    if len(px)<100: return {"status":"INSUFFICIENT_DATA","decision":"NO_TRADE","execution_eligible":False,"n_prices":len(px)}
    r=increments(px)
    if len(r)<99: return {"status":"INSUFFICIENT_DATA","decision":"NO_TRADE","execution_eligible":False}
    dist=describe(r); rt=runs_test(r)
    log_r=increments(px, log=True)
    log_dist=describe(log_r)
    log_bp_dist=describe([v*10000.0 for v in log_r])
    vr={str(q):variance_ratio(r,q) for q in q_values}
    h1=hurst_rs(r); h2=hurst_dfa(r)
    arcs=occupation_fraction(r)
    mc=block_bootstrap(r,paths=paths,block=8,seed=seed)
    primary=vr.get("5", next(iter(vr.values())))
    # 500 closed prices produce 499 one-step increments; align the minimum to that sample.
    regime=classify(primary,h2,rt.get("p_two_sided"),min_n=499)
    return {"schema_version":"1.0.0","system_version":"3.2.1-ALT","module":"stochastic_diagnostics",
      "status":"COMPLETED_RESEARCH_ONLY","instrument_profile":profile.to_dict(),
      "source_class":"INPUT_OHLC_DERIVED","n_prices":len(px),"n_increments":len(r),
      "distribution":dist,"log_return_distribution":log_dist,"log_return_basis_points_distribution":log_bp_dist,"runs_test":rt,"variance_ratio":vr,
      "hurst":{"rs":h1,"dfa1":h2},"arcsine_occupation":arcs,"monte_carlo":mc,
      "regime":regime,"decision":"NO_TRADE","execution_eligible":False,
      "limitations":["Diagnostics are not a trade signal.","No win probability is inferred.","No monetary risk conversion without verified tick metadata.","Use synchronized closed OHLC candles only.","Confirm findings out-of-sample and with costs."],
      "audit_flags":{"live_data_verified":False,"mtf_sync_verified":False,"backtest_executed":False,"costs_verified":False}}
