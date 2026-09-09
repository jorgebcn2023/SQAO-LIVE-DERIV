# GPT Vision layer

This module adds a multimodal analysis layer to SQAO-LIVE-DERIV.

## Configuration

Set the OpenAI API key outside the repository:

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='gpt-5.6-luna'
```

Never commit the key.

## Start the upload interface

```bash
streamlit run AI/app.py --server.address 0.0.0.0 --server.port 8501
```

Upload D1/H1/M15/M5/M1 screenshots. The app also reads `DATA/live_analysis.json` when available and gives GPT the quantitative snapshot together with the images.

The result is displayed in the UI and saved as `DATA/gpt_analysis.md`.

GPT output is an analysis layer, not a guarantee of future market movement or profitability.
