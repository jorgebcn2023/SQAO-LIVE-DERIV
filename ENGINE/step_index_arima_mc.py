"""ARIMA + Monte Carlo research for Deriv Step Index. Read-only; no order execution."""
from __future__ import annotations
import asyncio, json, os, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import websockets
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

WS=os.getenv("DERIV_PUBLIC_WS","wss://api.derivws.com/trading/v1/options/ws/public")
SYMBOL=os.getenv("SQAO_ARIMA_SYMBOL","stpRNG")
DATA=Path(os.getenv("SQAO_DATA_DIR","DATA")); DATA.mkdir(parents=True,exist_ok=True)
N_SIM=int(os.getenv("SQAO_MC_PATHS","10000"))
COUNT=int(os.getenv("SQAO_ARIMA_CANDLES","5000"))
HORIZON=int(os.getenv("SQAO_ARIMA_HORIZON","5"))
GRAN=int(os.getenv("SQAO_ARIMA_GRANULARITY","300"))

async def fetch_candles():
    req={"ticks_history":SYMBOL,"end":"latest","count":COUNT,"style":"candles","granularity":GRAN,"req_id":1}
    async with websockets.connect(WS,open_timeout=20,close_timeout=5) as ws:
        await ws.send(json.dumps(req))
        while True:
            msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=30))
            if msg.get("req_id")==1 or msg.get("msg_type")=="candles":
                if msg.get("error"): raise RuntimeError(msg["error"].get("message","Deriv API error"))
                candles=msg.get("candles",[])
                if candles: break
            if msg.get("error"): raise RuntimeError(msg["error"].get("message","Deriv API error"))
    now=int(datetime.now(timezone.utc).timestamp())
    rows=[]
    for c in candles:
        try:
            epoch=int(c["epoch"]); close=float(c["close"]); op=float(c["open"]); hi=float(c["high"]); lo=float(c["low"])
            if epoch+GRAN<=now and all(math.isfinite(v) for v in (close,op,hi,lo)) and close>0:
                rows.append({"epoch":epoch,"open":op,"high":hi,"low":lo,"close":close})
        except (KeyError,TypeError,ValueError): pass
    rows=sorted({r["epoch"]:r for r in rows}.values(),key=lambda r:r["epoch"])
    if len(rows)<500: raise RuntimeError(f"Insufficient closed candles: {len(rows)}")
    return rows

def main():
    import pandas as pd
    rows=asyncio.run(fetch_candles())
    df=pd.DataFrame(rows); close=df.close.to_numpy(float)
    lr=np.diff(np.log(close)); n=len(lr)
    split=int(n*.8); train,test=lr[:split],lr[split:]
    # Select ARIMA(p,0,q) on chronological training segment by AIC, then evaluate test forecasts one-step expanding.
    candidates=[]
    for p in range(0,4):
        for q in range(0,4):
            if p==q==0: continue
            try:
                fit=ARIMA(train,order=(p,0,q),trend="c").fit()
                if np.isfinite(fit.aic): candidates.append((fit.aic,p,q,fit))
            except Exception: pass
    if not candidates: raise RuntimeError("No ARIMA model converged")
    _,p,q,fit=min(candidates,key=lambda x:x[0])
    # Refit on training only; rolling one-step forecasts update with observed returns.
    history=list(train); preds=[]
    for actual in test:
        try:
            m=ARIMA(history,order=(p,0,q),trend="c").fit()
            preds.append(float(m.forecast(1)[0]))
        except Exception: preds.append(float(np.mean(history[-50:])))
        history.append(float(actual))
    preds=np.asarray(preds); err=test-preds
    rmse=float(np.sqrt(np.mean(err**2))); mae=float(np.mean(np.abs(err)))
    direction=float(np.mean((preds>0)==(test>0)))
    try: adf_p=float(adfuller(train,autolag="AIC")[1])
    except Exception: adf_p=None
    final_fit=ARIMA(lr,order=(p,0,q),trend="c").fit()
    fc=final_fit.get_forecast(steps=HORIZON)
    mean_lr=np.asarray(fc.predicted_mean,float)
    ci=np.asarray(fc.conf_int(),float)
    last=float(close[-1]); forecast_price=last*float(np.exp(np.sum(mean_lr)))
    # Bootstrap historical returns; simulate 10k paths, horizon is candles. Resampling retains empirical tails.
    rng=np.random.default_rng(20261012)
    sims=rng.choice(lr,size=(N_SIM,HORIZON),replace=True)
    paths=last*np.exp(np.cumsum(sims,axis=1))
    terminal=paths[:,-1]
    up=float(np.mean(terminal>last)); down=float(np.mean(terminal<last))
    q05,q50,q95=[float(x) for x in np.quantile(terminal,[.05,.5,.95])]
    max_dd=np.min(paths/np.maximum.accumulate(np.column_stack([np.full(N_SIM,last),paths]),axis=1)[:,1:]-1,axis=1)
    dd95=float(np.quantile(max_dd,.05))
    vol=float(np.std(lr,ddof=1)); drift=float(np.mean(lr))
    # Basic decision gate: predictive directional signal must be nontrivial and ARIMA must beat zero-return benchmark on OOS RMSE.
    baseline=float(np.sqrt(np.mean(test**2)))
    arima_better=rmse<baseline
    direction_signal="LONG" if forecast_price>last else "SHORT" if forecast_price<last else "WAIT"
    decision=direction_signal if arima_better and max(up,down)>=.60 else "NO_TRADE"
    ts=datetime.now(timezone.utc).isoformat()
    report={"generated_at_utc":ts,"symbol":SYMBOL,"timeframe":f"M{GRAN//60}" if GRAN<3600 else f"H{GRAN//3600}","candles_closed":len(rows),"last_epoch":int(df.epoch.iloc[-1]),"last_close":last,"horizon_candles":HORIZON,"arima":{"order":[p,0,q],"aic":float(final_fit.aic),"adf_pvalue_train":adf_p,"oos_n":len(test),"oos_rmse":rmse,"zero_return_rmse":baseline,"oos_mae":mae,"directional_accuracy":direction,"beats_zero_return_rmse":arima_better,"forecast_log_returns":mean_lr.tolist(),"forecast_price_compounded":forecast_price,"log_return_volatility":vol,"mean_log_return":drift,"forecast_ci_log_return":ci.tolist()},"monte_carlo":{"paths":N_SIM,"method":"iid bootstrap of historical closed-candle log returns; empirical distribution","probability_terminal_up":up,"probability_terminal_down":down,"terminal_price_p05":q05,"terminal_price_median":q50,"terminal_price_p95":q95,"max_drawdown_5th_percentile":dd95},"decision":decision,"limitations":["Monte Carlo probabilities are historical-bootstrap scenario frequencies, not calibrated win probabilities.","ARIMA forecast is not a trading signal unless it beats the zero-return OOS benchmark.","No spread/slippage/commission included; do not infer 70% trading effectiveness.","Read-only research; no order placement."]}
    (DATA/"step_index_arima_mc.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    fig,ax=plt.subplots(figsize=(9,4.5))
    for i in range(min(100,N_SIM)): ax.plot(range(HORIZON+1),np.r_[last,paths[i]],alpha=.12,linewidth=.6)
    ax.axhline(last,linestyle="--",linewidth=1); ax.set_title(f"Monte Carlo bootstrap — {SYMBOL}, {N_SIM:,} paths"); ax.set_xlabel("Candles ahead"); ax.set_ylabel("Price"); fig.tight_layout()
    chart1=DATA/"step_index_mc_paths.png"; fig.savefig(chart1,dpi=150); plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    ax.hist(terminal,bins=60); ax.axvline(last,linestyle="--",label="Last close"); ax.axvline(q50,linestyle=":",label="Median terminal"); ax.legend(); ax.set_title("Distribution of simulated terminal prices"); fig.tight_layout()
    chart2=DATA/"step_index_mc_distribution.png"; fig.savefig(chart2,dpi=150); plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4))
    ax.plot(test,label="Realized OOS log returns",linewidth=.8); ax.plot(preds,label="ARIMA one-step forecast",linewidth=.8); ax.legend(); ax.set_title("ARIMA rolling OOS forecasts"); fig.tight_layout()
    chart3=DATA/"step_index_arima_oos.png"; fig.savefig(chart3,dpi=150); plt.close(fig)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="T",parent=styles["Title"],fontSize=19,leading=23))
    story=[Paragraph("SQAO — ARIMA + MONTE CARLO",styles["T"]),Paragraph(f"Step Index {SYMBOL} · generado {ts}",styles["Normal"]),Spacer(1,10)]
    verdict_color=colors.HexColor("#b91c1c") if decision=="NO_TRADE" else colors.HexColor("#92400e")
    story.append(Paragraph(f"<b>DECISIÓN: {decision}</b>",ParagraphStyle("v",parent=styles["Heading1"],textColor=verdict_color)))
    story.append(Paragraph("El resultado es investigación cuantitativa, no garantía de rendimiento ni instrucción automática de trading.",styles["BodyText"]))
    rows_table=[["Métrica","Resultado"],["Velas cerradas",str(len(rows))],["Último cierre",f"{last:.5f}"],["ARIMA(p,d,q)",f"({p},0,{q})"],["RMSE ARIMA OOS",f"{rmse:.8g}"],["RMSE benchmark cero",f"{baseline:.8g}"],["Acierto direccional OOS",f"{direction*100:.2f}%"],["Pronóstico compuesto",f"{forecast_price:.5f}"],["Monte Carlo paths",f"{N_SIM:,}"],["P(terminal > actual)",f"{up*100:.2f}%"],["P(terminal < actual)",f"{down*100:.2f}%"],["Terminal p05 / mediana / p95",f"{q05:.5f} / {q50:.5f} / {q95:.5f}"],["Max drawdown 5% peor cola",f"{dd95*100:.3f}%"],["Costes incluidos","No"]]
    t=Table(rows_table,colWidths=[8*cm,8*cm]); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#23364d")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#cbd5e1")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f1f5f9")]),("PADDING",(0,0),(-1,-1),5)])); story += [t,Spacer(1,8),Paragraph("1. Monte Carlo: trayectorias",styles["Heading1"]),Image(str(chart1),width=16*cm,height=8*cm),PageBreak(),Paragraph("2. Distribución terminal",styles["Heading1"]),Image(str(chart2),width=16*cm,height=8*cm),Paragraph("3. ARIMA: validación OOS",styles["Heading1"]),Image(str(chart3),width=16*cm,height=8*cm),Paragraph("Interpretación y limitaciones",styles["Heading1"])]
    for item in report["limitations"]: story.append(Paragraph("• "+item,styles["BodyText"]))
    SimpleDocTemplate(str(DATA/"step_index_arima_mc.pdf"),pagesize=A4,rightMargin=1.5*cm,leftMargin=1.5*cm,topMargin=1.5*cm,bottomMargin=1.5*cm).build(story)
    print(json.dumps({"decision":decision,"report":str(DATA/"step_index_arima_mc.json"),"pdf":str(DATA/"step_index_arima_mc.pdf"),"oos_rmse":rmse,"baseline_rmse":baseline,"mc_paths":N_SIM,"p_up":up,"p_down":down},indent=2))
if __name__=="__main__": main()
