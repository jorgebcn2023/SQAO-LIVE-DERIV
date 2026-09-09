from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from AI.gpt_vision import analyze_images

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DATA"
UPLOADS = DATA / "uploads"

st.set_page_config(page_title="SQAO GPT Vision", layout="wide")
st.title("SQAO-LIVE-DERIV · GPT Vision")
st.caption("Sube D1/H1/M15/M5/M1. GPT analiza las imágenes junto con el snapshot cuantitativo de SQAO.")

uploaded = st.file_uploader(
    "Gráficos MTF",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
    help="Idealmente sube D1, H1, M15, M5 y M1. No es obligatorio subir los cinco.",
)

snapshot_path = DATA / "live_analysis.json"
snapshot: dict = {}
if snapshot_path.exists():
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        st.success("Snapshot SQAO en vivo cargado.")
    except Exception:
        st.warning("Existe DATA/live_analysis.json pero no se pudo leer.")
else:
    st.info("No hay snapshot cuantitativo todavía. GPT analizará solamente los gráficos.")

if uploaded:
    st.write(f"{len(uploaded)} gráfico(s) recibido(s).")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    cols = st.columns(min(len(uploaded), 5))
    temp_paths: list[Path] = []
    for i, item in enumerate(uploaded):
        target = UPLOADS / f"upload_{i}_{item.name}"
        target.write_bytes(item.getbuffer())
        temp_paths.append(target)
        with cols[i % len(cols)]:
            st.image(item, caption=item.name, use_container_width=True)

    st.caption("Consejo: incluye el timeframe en el nombre del archivo o que sea visible en el gráfico.")

    if st.button("Analizar con GPT", type="primary"):
        if not os.getenv("OPENAI_API_KEY"):
            st.error("Falta OPENAI_API_KEY en el entorno del Codespace.")
        else:
            with st.spinner("Analizando gráficos + datos SQAO..."):
                try:
                    result = analyze_images(temp_paths, snapshot)
                    (DATA / "gpt_analysis.md").write_text(result, encoding="utf-8")
                    st.subheader("Análisis GPT")
                    st.markdown(result)
                    st.download_button("Descargar análisis", result, file_name="gpt_analysis.md")
                except Exception as exc:
                    st.error(f"Error de análisis: {exc}")
