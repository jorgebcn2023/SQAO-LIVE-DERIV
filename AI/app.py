from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

from AI.gpt_vision import analyze_images

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DATA"
UPLOADS = DATA / "uploads"
DEFAULT_API = "https://sqao-live-api.onrender.com"

st.set_page_config(page_title="SQAO GPT Vision", layout="wide")
st.title("SQAO-LIVE-DERIV · GPT Vision + Live Quant")
st.caption("Sube D1/H1/M15/M5/M1. El sistema confronta los gráficos con el snapshot cuantitativo vivo de Deriv.")

api_url = os.getenv("SQAO_API_URL", DEFAULT_API).rstrip("/")
api_key = os.getenv("SQAO_ACTION_KEY", "").strip()


def fetch_live_snapshot() -> tuple[dict, str]:
    url = f"{api_url}/analysis/snapshot"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if api_key:
        request.add_header("X-SQAO-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload, "LIVE_DERIV_API"
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        snapshot_path = DATA / "live_analysis.json"
        if snapshot_path.exists():
            try:
                return json.loads(snapshot_path.read_text(encoding="utf-8")), "LOCAL_SQAO_FALLBACK"
            except Exception:
                pass
        return {"error": str(exc)}, "NO_QUANT_SNAPSHOT"

snapshot, snapshot_source = fetch_live_snapshot()
if snapshot_source == "LIVE_DERIV_API":
    st.success(f"Snapshot cuantitativo LIVE cargado desde {api_url}.")
elif snapshot_source == "LOCAL_SQAO_FALLBACK":
    st.warning("API LIVE no disponible: usando DATA/live_analysis.json local como fallback.")
else:
    st.info("No hay snapshot cuantitativo disponible. Se hará análisis visual únicamente.")

uploaded = st.file_uploader(
    "Gráficos MTF",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
    help="Idealmente sube D1, H1, M15, M5 y M1. Usa nombres como D1.png, H1.png, M15.png, M5.png y M1.png.",
)

if uploaded:
    st.write(f"{len(uploaded)} gráfico(s) recibido(s).")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    cols = st.columns(min(len(uploaded), 5))
    image_items: list[tuple[Path, str]] = []
    for i, item in enumerate(uploaded):
        target = UPLOADS / f"upload_{i}_{item.name}"
        target.write_bytes(item.getbuffer())
        image_items.append((target, item.name))
        with cols[i % len(cols)]:
            st.image(item, caption=item.name, use_container_width=True)

    st.caption("El modelo detecta el timeframe por etiqueta visible y/o nombre del archivo y marca inconsistencias temporales.")

    if st.button("Analizar con SQAO + GPT", type="primary"):
        if not os.getenv("OPENAI_API_KEY"):
            st.error("Falta OPENAI_API_KEY en el entorno.")
        else:
            with st.spinner("Confrontando Deriv LIVE + SQAO + gráficos MTF..."):
                try:
                    result = analyze_images(image_items, snapshot)
                    (DATA / "gpt_analysis.md").write_text(result, encoding="utf-8")
                    st.subheader("Análisis combinado")
                    st.markdown(result)
                    st.download_button("Descargar análisis", result, file_name="sqao_combined_analysis.md")
                except Exception as exc:
                    st.error(f"Error de análisis: {exc}")
