# SQAO V3.2.1-ALT stochastic diagnostics

This module adds a parallel research-only statistical layer to the existing Step Index snapshot. It consumes only the API's normalized, completed OHLC candles. Each timeframe is analyzed independently; this module does not infer MTF synchronization.

## Diagnostics
- Empirical increment distribution: mean, sample standard deviation, skew, excess kurtosis and zero fraction.
- Wald-Wolfowitz runs test.
- Lo-MacKinlay-style variance ratios at q = 2, 5, 10 and 20.
- Rescaled-range Hurst and DFA-1 scaling diagnostics.
- Arcsine occupation fraction.
- Seeded moving-block bootstrap of the empirical increment mean.
- Conservative exploratory regime label.

## Gates and provenance
Each timeframe requires at least 100 valid closed candles, positive finite OHLC values, valid high/low ranges, strictly increasing unique timestamps, and contiguous epochs. Failed checks are recorded as blocked; no values are interpolated. SHA-256 hashes preserve the exact normalized input series.

The ALT module never supplies a BUY/SELL signal, a win probability, an MTF synchronization claim, monetary position sizing, or execution permission. The parent API continues to return decision=NO_TRADE and execution_eligible=false.

## Limitations
These are exploratory diagnostics with asymptotic and finite-sample limitations. The bootstrap is a distribution of resampled sample means, not a forecast of price. Regime labels are not calibrated probabilities. Use independent out-of-sample strategy validation and verified all-in transaction costs before considering any strategy conclusion.
