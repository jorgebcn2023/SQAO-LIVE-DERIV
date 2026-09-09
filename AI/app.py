from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from AI.gpt_vision import analyze_images

st.set_page_config(page_title="SQAO GPT Vision", layout="wide")
st.title("SQAO — GPT Vision")
st.caption("Sube D1/H1/M15/M5/M1. GPT analiza las imágenes junto con el snapshot cuantitativo de SQAO.")

uploaded = st.file_uploader(
    "Gráficos",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
    help="Idealmente sube D1, H1, M15, M5 y M1. No es obligatorio subir los cinco.",
)

snapshot_path = Path("DATA/live_analysis.json")
snapshot = {}
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
    cols = st.columns(min(len(uploaded), 5))
    temp_paths = []
    for i, item in enumerate(uploaded):
        target = Path("DATA") / f"upload_{i}_{item.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.getbuffer())
        temp_paths.append(target)
        with cols[i % len(cols)]:
            st.image(item, caption=item.name, use_container_width=True)

    if st.button("Analizar con GPT", type="primary"):
        with st.spinner("Analizando gráficos + datos SQAO..."):
            result = analyze_images(temp_paths, snapshot)
        st.subheader("Análisis GPT")
        st.markdown(result)
        Path("DATA/gpt_analysis.md").write_text(result, encoding="utf-8")
        st.download_button("Descargar análisis", result, file_name="gpt_analysis.md")
