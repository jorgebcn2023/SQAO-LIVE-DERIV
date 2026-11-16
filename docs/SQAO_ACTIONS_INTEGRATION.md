# SQAO Actions integration — read-only security branch

## Purpose

This branch adds an explicit OpenAPI contract and offline regression tests for the existing SQAO Live API. It is based on the repository main branch and is intentionally not deployed or merged.

The API service reports version 2.6.0. The SQAO instruction/skill bundle label 3.1.3 is a separate client-side version and must not be presented as the API server version.

## Verified server routes

The paths below were confirmed against API/app.py on the base branch:

| Method | Path | Authentication |
|---|---|---|
| GET | /health | Public health metadata |
| GET | /market/active-symbols | X-SQAO-Key |
| GET | /market/ohlc | X-SQAO-Key |
| GET | /analysis/snapshot | X-SQAO-Key |

Only these four paths are published in GPT/openapi.yaml. No request bodies, trading paths, account paths, balance paths, or mutating HTTP methods are included.

## Symbol-resolution hardening

The prior implementation returned an explicit symbol without checking the active Step Index list, and AUTO selected the first candidate when several existed. This branch changes the behavior:

- An explicit symbol must match exactly one currently active Step Index symbol.
- AUTO is accepted only if one unique active candidate exists.
- DERIV_STEP_NAME may select a candidate only when the preference matches exactly one candidate.
- Multiple matches return HTTP 409.
- An explicit symbol that is not verified returns HTTP 422.
- Repeated provider rows for the same symbol identifier are deduplicated before resolution.

These conditions are fail-closed and do not select a substitute instrument.

## Authentication and safety

- /health is intentionally unauthenticated and exposes service/readiness metadata only.
- All market-data and analysis endpoints require X-SQAO-Key.
- The API key is configured server-side through SQAO_ACTION_KEY; it is never stored in the OpenAPI document, repository or query string.
- The contract exposes GET only.
- decision remains NO_TRADE and execution_eligible remains false.
- No order placement, modification, cancellation, account or balance operations are introduced.

## Local validation

Install the existing API and engine dependencies, then run:

    python -m compileall -q API
    python -m API.test_app
    python -m API.test_openapi_security

The new OpenAPI security tests are offline. They validate the YAML path/method subset, compare the runtime FastAPI schema to the published contract, verify header authentication declarations and test fail-closed symbol resolution using mocked symbol lists. They do not call Deriv or Render.

The existing repository CI workflow is updated to run both API test modules. Its Deriv public WebSocket smoke test remains an external connectivity test and is separate from these offline tests.

## Actions integration checklist

1. Confirm the target deployment reports API version 2.6.0 from /health.
2. Configure the Action base URL as https://sqao-live-api-v2.onrender.com.
3. Configure the Action custom header authentication for X-SQAO-Key; do not paste the key into the OpenAPI file or conversation.
4. Import GPT/openapi.yaml.
5. Confirm exactly four GET operations are visible.
6. Test /health first, then authenticated symbol discovery, then OHLC/snapshot.
7. Treat HTTP 409 symbol ambiguity and HTTP 422 unverified explicit symbols as hard stops.
8. Keep the system READ-ONLY / RESEARCH-ONLY. Do not add POST/PUT/PATCH/DELETE operations or execution Actions.

## Non-goals

This branch does not change trading logic, indicator calculations, strategy thresholds, backtesting methodology, Render configuration, deployment workflows or production secrets. It does not claim that the remote service has been deployed or that a live endpoint has passed health checks.
