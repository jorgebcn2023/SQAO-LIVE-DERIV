from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import streamlit as st

from AI.gpt_vision import analyze_images

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DATA"
UPLOADS = DATA / "uploads"
DEFAULT_API = "https://sqao-live-api.onrender.com"

st.set_page_config(page_title="SQAO Live Deriv", layout="wide")
st.title("SQAO-LIVE-DERIV · MTF Live + GPT Vision")
st.caption("Deriv LIVE → SQAO cuantitativo → D1/H1/M15/M5/M1 → reconciliación visual → LONG / SHORT / WAIT / NO_TRADE")

with st.sidebar:
    st.header("Configuración")
    api_url = st.text_input("SQAO API", value=os.getenv("SQAO_API_URL", DEFAULT_API)).strip().rstrip("/")
    api_key = st.text_input("SQAO API key (opcional)", value=os.getenv("SQAO_ACTION_KEY", ""), type="password").strip()
    openai_key = st.text_input("OpenAI API key", value="", type="password", help="Se usa durante esta sesión y no se guarda en GitHub.").strip()
    model = st.text_input("Modelo OpenAI", value=os.getenv("OPENAI_MODEL", "gpt-5.6")).strip()
    symbol = st.text_input("Step Index", value="AUTO", help="AUTO detecta automáticamente un Step Index activo.").strip() or "AUTO"
    count = st.slider("Velas por timeframe", 50, 300, 120, 10)
    refresh = st.button("↻ Actualizar datos LIVE")


def fetch_live_snapshot() -> tuple[dict, str]:
    query = urllib.parse.urlencode({"symbol": symbol, "count": count})
    request = urllib.request.Request(f"{api_url}/analysis/snapshot?{query}", headers={"Accept": "application/json"})
    if api_key:
        request.add_header("X-SQAO-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("source") != "Deriv public market data":
            raise ValueError("API returned an unexpected data source")
        return payload, "LIVE_DERIV_API"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        snapshot_path = DATA / "live_analysis.json"
        if snapshot_path.exists():
            try:
                return json.loads(snapshot_path.read_text(encoding="utf-8")), "LOCAL_SQAO_FALLBACK"
            except Exception:
                pass
        return {"error": str(exc), "source": "NONE"}, "NO_QUANT_SNAPSHOT"

if refresh or "snapshot" not in st.session_state:
    st.session_state.snapshot, st.session_state.snapshot_source = fetch_live_snapshot()
snapshot = st.session_state.snapshot
snapshot_source = st.session_state.snapshot_source

if snapshot_source == "LIVE_DERIV_API":
    st.success(f"LIVE Deriv conectado · símbolo: {snapshot.get('symbol', symbol)}")
elif snapshot_source == "LOCAL_SQAO_FALLBACK":
    st.warning("API LIVE no disponible. Se está usando snapshot local y se marcará como fallback.")
else:
    st.error("No hay snapshot cuantitativo. No se presentará como dato LIVE.")

if snapshot.get("timeframes"):
    cols = st.columns(5)
    for col, tf in zip(cols, ("D1", "H1", "M15", "M5", "M1")):
        data = snapshot["timeframes"].get(tf, {})
        col.metric(tf, data.get("direction", "UNKNOWN"), data.get("latest_close"))
    st.caption(f"Decisión cuantitativa conservadora: **{snapshot.get('decision', 'NO_TRADE')}** · generado: {snapshot.get('generated_at_utc', 'n/d')}")

uploaded = st.file_uploader(
    "Gráficos MTF",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
    help="Sube D1, H1, M15, M5 y M1. Los nombres deben incluir el timeframe cuando no sea visible.",
)

if uploaded:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    cols = st.columns(min(len(uploaded), 5))
    image_items: list[tuple[Path, str]] = []
    for i, item in enumerate(uploaded):
        target = UPLOADS / f"upload_{i}_{item.name}"
        target.write_bytes(item.getbuffer())
        image_items.append((target, item.name))
        with cols[i % len(cols)]:
            st.image(item, caption=item.name, use_container_width=True)

    if len(uploaded) < 5:
        st.warning("Faltan timeframes para una validación MTF completa. El sistema podrá devolver WAIT/NO_TRADE.")

    if st.button("Analizar con SQAO + GPT", type="primary"):
        key = openai_key or os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            st.error("Introduce una OpenAI API key en la barra lateral o configúrala como secret del Codespace.")
        else:
            with st.spinner("Confrontando Deriv LIVE + SQAO + visión MTF..."):
                try:
                    result = analyze_images(image_items, snapshot, model=model or None, api_key=key)
                    (DATA / "gpt_analysis.md").write_text(result, encoding="utf-8")
                    st.subheader("Análisis combinado")
                    st.markdown(result)
                    st.download_button("Descargar análisis", result, file_name="sqao_combined_analysis.md")
                except Exception as exc:
                    st.error(f"Error de análisis: {exc}")
