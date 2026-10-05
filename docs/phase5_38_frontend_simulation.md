# Phase 5.38 — Interactive frontend and simulation workspace

## Architecture

The frontend is a small same-origin web application made of static HTML, CSS and
vanilla JavaScript. There was no existing frontend framework or frontend build
pipeline to extend, so this avoids introducing a second stack or a scientific
implementation in JavaScript.

```text
Browser presentation / state / SVG visualization
                    |
                    v
       agri_twin.interfaces.frontend_api
                    |
                    v
       InteractiveSimulationService (5.37)
                    |
                    v
  ScenarioRunner / orchestrator / existing domain
```

The browser only talks to the HTTP adapter. It does not import application or
domain code, calculate crop variables, mutate scientific state, generate
weather, or reconstruct hashes. The adapter gets crop, variety, plot,
environment, scenario, model, availability and scientific-status information
from the existing 5.37 contract and canonical request path.

The adapter runs the synchronous service in a local in-process thread so HTTP
requests remain responsive and the UI can request progress or cooperative
cancellation. This is deliberately not a durable worker, distributed executor,
or production deployment. A `BACKGROUND` plan remains an advisory long-run
classification and is displayed as such.

Operational timing is supplied by the runner (`time.perf_counter`) to the
service and adapter as an injected callback. The API service and frontend
adapter do not read a clock themselves.

## Run locally

Install the project and development extra if they are not already installed:

```powershell
python -m pip install -e ".[dev]"
```

Start the timed, local-only server from the repository root:

```powershell
python tools\run_phase5_38_frontend.py --host 127.0.0.1 --port 8765
```

Then open <http://127.0.0.1:8765>. The HTTP adapter refuses non-loopback bind
addresses and serves only the three named frontend assets; it does not resolve
user-controlled filesystem paths.

## HTTP adapter surface

| Method and route | Contract behavior |
|---|---|
| `GET /api/capabilities` | Project `contract_description()` and canonical crop defaults; no duplicated crop/scenario lists in the UI |
| `POST /api/plan` | Canonicalize and plan without running a simulation |
| `POST /api/simulations` | Call `create_simulation` and return the canonical created response |
| `POST /api/simulations/{id}/start` | Start the existing service in a local worker thread |
| `GET /api/simulations/{id}` | Return the service response, status, progress, checkpoint and result |
| `GET /api/simulations/{id}/progress` | Return operational progress |
| `GET /api/simulations/{id}/result` | Return a completed result or the structured service error |
| `POST /api/simulations/{id}/cancel` | Request cooperative service cancellation |
| `POST /api/simulations/resume` | Call `resume_simulation` with the API checkpoint unchanged, then start it |

Requests are limited to 1 MB and JSON is validated by the 5.37 canonicalizer.
Structured API errors retain their code, message and field path. Unexpected
worker errors are logged locally and surfaced as `INTERNAL_EXECUTION_ERROR`;
stack traces are not returned to the browser.

## Frontend state and behavior

The browser keeps four concerns separate:

- **Request configuration:** selected crop, canonical variety/plot, supported
  environment, scenario, short/full horizon, requested dormancy model and
  trajectory-hash preference.
- **Execution state:** simulation ID, execution status, API progress and
  checkpoint. Polling is at the contract-advertised interval (750 ms), only
  while execution is active.
- **Result state:** API result, variable availability, warnings, hashes and
  scientific status.
- **UI state:** rendering timings and visible errors; it is never fed into
  request hashes or simulation state.

The crop and environment selectors are populated from backend capabilities.
The current contract exposes one configured variety and plot per crop, so those
are shown as backend-resolved values rather than invented alternatives. The
short run is seven simulated days; full season uses the canonical campaign end.
The API remains authoritative for validity and returns the structured error if
a request is rejected.

Chilling model selection is available for crops whose API-backed capability
marks dormancy applicable. The UI sends the requested model and `STRICT`
fallback policy. Requested/effective model and fallback status are taken from
the response; model selection is not represented as scientific
parameterization. No cultivar requirement is invented.

Cancellation calls the service, is shown as `CANCELLED` (not `FAILED`), and
keeps the API checkpoint. Resume sends the returned checkpoint object without
reading or changing its payload. A resumed run can only be requested while the
checkpoint precedes the configured campaign end; the backend validates the
checkpoint and matching configuration.

## Results and visualization

The summary shows the canonical request, execution class, status, period and
API hashes. Final-state values and charts are projections of the result's
`variables` catalogue and `trajectory`. `AVAILABLE`, `NOT_APPLICABLE` and
`NOT_SUPPORTED` are displayed separately; no zero or context-free `null` is
used as a substitute.

The essential charts cover temperature, humidity, VPD, radiation, soil water,
water fluxes, biomass and stress where each variable is available. Each plotted
point is an API sample at its API timestamp. The frontend does not smooth,
interpolate, derive, or recalculate values. SVG point tooltips and textual
summaries are available to assist inspection and screen-reader use; categorical
phenological stages are displayed as API-reported stage intervals. A
`NOT_SUPPORTED` availability explanation comes from the API catalogue.

Greenhouse results can display indoor variables when available. Actuator
commands and actuated-greenhouse behavior are not exposed by 5.37 and are not
implemented here.

## Warnings and scientific-status policy

Software/execution warnings are visually separated from scientific status.
Every result retains the API statement and flags, including:

- real agricultural data verified: **No**;
- calibration performed: **No**;
- experimental validation performed: **No**;
- biological validity claimed: **No**;
- field accuracy claimed: **No**;
- data assimilation implemented: **No**.

Scenarios use synthetic forcing and are not presented as real climatology.
The UI does not use claims such as “validated crop model”, “accurate
prediction”, or “field validated”.

## Performance

Operational performance is kept distinct from model result hashes:

- `MODEL_TIME`: service-provided execution timing from the injected adapter
  timer;
- `API_TIME`: browser time for the latest adapter request;
- `SERIALIZATION_TIME`: adapter JSON serialization duration;
- `FRONTEND_RENDER_TIME`: browser-measured result rendering duration.

The execution plan's cost is advisory and machine-dependent. Performance is
software/UX characterization only and is not evidence of scientific validity.
The reproducible phase report is
[`data/frontend/interactive_frontend_report.json`](../data/frontend/interactive_frontend_report.json).

## Tests and limitations

`tests/test_frontend_api.py` exercises the capabilities/plan adapter, all
execution states that can be deterministically reached, structured errors,
hash settings, result availability, checkpoint/resume equivalence, static
frontend constraints, accessibility/responsive markers and an actual local
HTTP-to-service short-run flow. The UI has no third-party chart/build
dependency. Visual browser rendering should be smoke-tested at desktop, tablet
and mobile widths.

The server is a development-only loopback adapter: state and checkpoints are
in memory and are lost on process exit. It has no authentication, TLS,
durability, cross-origin support, or distributed execution. Do not expose it
outside the local machine.
