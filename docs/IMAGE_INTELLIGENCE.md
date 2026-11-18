# SQAO Image Intelligence v1.0

Research-only screenshot extraction for MT5 chart images.

## Run
```bash
python -m ENGINE.image_intelligence path/to/chart.png --timeframe M5
```

Optional dependencies:
- Pillow: image metadata.
- pytesseract + Tesseract OCR: visible text extraction.
- opencv-python + numpy: red/green component detection.

The module emits `DATA/step_index_image_audit.json`. It processes every image independently, retains failures and provenance, and labels OCR and pixel findings as estimates.

## Calibration
For controlled pixel-to-price conversion, call `analyze_chart_image` with:
- `chart_roi=[x,y,width,height]`
- exactly two `price_axis_anchors=[{"y": pixel_y, "price": axis_price}, ...]`

This calibration only maps vertical pixel positions to price. It does not recover candle timestamps, reliably separate candle bodies from wicks, or establish exact OHLC.

## Evidence policy
- Screenshot/OCR/pixel-derived values: visual estimates only.
- Timestamped closed Deriv OHLC: authoritative input for chronological backtests.
- Do not insert screenshot-derived candles into OOS backtests.
- Never infer hidden indicator values or exact trade prices from chart appearance.
- Monetary conversion uses the user's provisional declaration (USD 0.10 per 0.1 price units at 0.10 lots); it is not a broker-verified tick value.
- No trading API or order placement is implemented.

## Tests
```bash
python -m unittest ENGINE.test_image_intelligence
```

## SQAO Indicator Vision V3.2.0

The existing OCR/geometry audit optionally analyzes colored traces in explicitly configured indicator-pane regions. Supported panes: EMA, Bollinger, RSI, MACD, ADX and Stochastic. The visual audit can be run independently for D1/H4/H1/M15/M5/M1.

Example:

```python
from ENGINE.chart_visual_extraction import build_visual_audit
report = build_visual_audit({
  'M5': {'path': 'charts/StepIndex_M5.png', 'timeframe': 'M5', 'pane_rois': {
    'EMA': [80, 80, 900, 360], 'BOLLINGER': [80, 80, 900, 360],
    'MACD': [80, 450, 900, 130], 'RSI': [80, 590, 900, 110],
    'ADX': [80, 710, 900, 100], 'STOCHASTIC': [80, 820, 900, 100]
  }}
})
```

ROI coordinates are [x, y, width, height] in original image pixels. Configure actual chart layout; example coordinates are illustrative only. The engine reports trace coverage and image-space rising/falling/flat evolution. Bollinger reports a geometric band-width change when two boundary traces are present.

EMA9/20/50, +DI/-DI and signal-line identities are not assigned from color alone; verified legend-color mapping is required. Pixel direction is not an exact price or indicator value. No screenshot-derived OHLC is created.

The OpenCV module is ENGINE/chart_indicator_vision.py. Run tests with python -m ENGINE.test_chart_indicator_vision. The GPT vision entry point accepts an optional visual_panes mapping keyed by uploaded image label.

### Legend and scale recognition extension

Pass `legend_roi=[x,y,width,height]` alongside `pane_rois` for a chart-level indicator legend. OCR groups legend text, then samples the rendered text hue and associates it with trace hues only within a conservative hue tolerance. Unmatched or ambiguous identities remain null. Each configured pane also attempts OCR calibration from numeric labels in its rightmost 28%; a calibration needs at least two distinct labels and is tagged `CALIBRATED` or `LOW_CONFIDENCE`. Pixel-to-value points are `VISUAL_ESTIMATE_FROM_OCR_AXIS`, never API/DERIVED values.

When the scale and legend both pass, RSI/Stochastic/ADX/MACD can receive a visual threshold/zero-line classification; EMA9/20/50 stack order is reported only if all three legend identities are independently mapped. These classifications are not quantitative signals and must not alter the OHLC engine decision.
