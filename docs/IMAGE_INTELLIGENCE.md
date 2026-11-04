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
