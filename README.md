# GridWise LLM — Smart Campus Energy Optimization Service

**BUP CSE Fest 2026 Hackathon · Online Preliminary Round**  
*Challenge Type: LLM-Assisted Smart Campus Energy Scheduling & Optimization*

---

## 1. Overview & System Architecture

GridWise LLM is an HTTP service for the 24-hour campus energy scheduling problem under dynamic tariffs, solar generation, demand, and natural-language operator directives.

### The 4-Stage Processing Pipeline

```
                       Campus Operator Notes
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 1: LLM Directive Interpretation          │
         │ - Primary: Google Gemini (configured model)     │
         │ - Fallback: OpenAI (gpt-4o-mini)                │
         │ - Structured JSON Output with Pydantic schema  │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 2: Deterministic Guardrails              │
         │ - Validates allowed directive types            │
         │ - Enforces unique ascending hours [0..23]      │
         │ - Rejects invalid factors, caps, and reserves  │
         │ - Enforces Section 04 exact adjustment shapes  │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 3: MILP Mathematical Optimization        │
         │ - SciPy HiGHS MILP solver                     │
         │ - Physical Battery Dynamics & Rate Limits      │
         │ - End-of-Day State of Charge Neutrality        │
         │ - Minimizes Grid Cost in BDT                   │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 4: Schedule Replay Verification          │
         │ - Hourly energy balance verification           │
         │ - Solar curtailment & battery bounds replay    │
         │ - Summary totals recalculated to ±0.01 kWh/BDT │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
                      POST /optimize-energy
```

---

## 2. Model & Technology Disclosure

| Component | Technology / Provider | Role |
| :--- | :--- | :--- |
| **Primary LLM** | **Google Gemini (`gemini-3.5-flash-lite`)** | Structured directive extraction, paraphrase comprehension, and distractor filtering; selected after passing all public cases with lower measured latency. |
| **Fallback LLM** | **OpenAI (`gpt-4o-mini`)** | Automatic failover if the primary provider encounters quota or availability issues. |
| **Emergency Continuity Parser** | **Deterministic Heuristic Engine** | Local diagnostics during complete provider outages; it is not a replacement for the mandatory language-model interpretation path. |
| **Mathematical Solver** | **SciPy MILP (`HiGHS` solver)** | Exact global cost minimization under hourly linear and integrality constraints. |
| **API Framework** | **FastAPI + Uvicorn** | High-throughput asynchronous web server complying with the exact challenge schema. |

All runtime dependencies are declared in `requirements.txt`: FastAPI, Uvicorn,
Pydantic, OpenAI SDK, Google Gen AI SDK, SciPy/HiGHS, NumPy,
python-dotenv, Requests, and HTTPX. These projects provide the external API,
model-client, validation, numerical-optimization, configuration, and HTTP
components used by this submission.

---

## 3. Environment Variables & Configuration

The service uses standard environment variables. You can configure them via a `.env` file or export them directly:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | Paid OpenAI API key | *(Optional if Gemini provided)* |
| `GEMINI_API_KEY` | Google Gemini API key | *(Optional if OpenAI provided)* |
| `PRIMARY_PROVIDER` | Preferred provider (`openai` or `gemini`) | `gemini` when its key is available, otherwise `openai` |
| `OPENAI_MODEL` | OpenAI Model ID | `gpt-4o-mini` |
| `GEMINI_MODEL` | Gemini Model ID | `gemini-3.5-flash-lite` |
| `PORT` | HTTP service port | `8000` |
| `HOST` | Bind host address | `0.0.0.0` |
| `REQUEST_TIMEOUT_SECONDS` | OpenAI request timeout before provider fallback | `5.0` |
| `GEMINI_TIMEOUT_SECONDS` | Gemini deadline; its API requires at least 10 seconds | `10.0` |

> **Security Note:** No API keys, credentials, or secrets are baked into this repository or the Docker container. All keys are injected securely at runtime via environment variables. The judged deployment must provide at least one valid model key so a language-capable model interprets `operator_notes`.

---

## 4. Local Quickstart (Fresh Environment)

### Step 1: Enter the Submitted Repository & Create a Virtual Environment
```bash
cd bup-preli

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
```bash
cp .env.example .env
# Add at least one valid provider key for the challenge-compliant LLM path.
nano .env
```
Or export directly:
```bash
export OPENAI_API_KEY="your_openai_key"
export GEMINI_API_KEY="your_gemini_key"
```

### Step 3: Run the API Server
```bash
./run.sh
# Or directly via uvicorn:
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 5. Verification & Testing

### 1. Health Readiness Check (`GET /health`)
```bash
curl -i http://localhost:8000/health
```
**Expected Response:**
```json
{"status":"ok"}
```

### 2. Sample Request (`POST /optimize-energy`)
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "TEST-01",
    "operator_notes": [
      "Solar output will drop to about 25% from noon until 2 PM.",
      "The sports office moved next month registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 1, "demand_kwh": 160, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 2, "demand_kwh": 150, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 3, "demand_kwh": 140, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 4, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 5, "demand_kwh": 130, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 6, "demand_kwh": 120, "solar_kwh": 10, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 110, "solar_kwh": 30, "tariff_bdt_per_kwh": 9},
      {"hour": 8, "demand_kwh": 100, "solar_kwh": 70, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 90, "solar_kwh": 110, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 85, "solar_kwh": 130, "tariff_bdt_per_kwh": 15},
      {"hour": 11, "demand_kwh": 80, "solar_kwh": 160, "tariff_bdt_per_kwh": 15},
      {"hour": 12, "demand_kwh": 75, "solar_kwh": 180, "tariff_bdt_per_kwh": 14},
      {"hour": 13, "demand_kwh": 85, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 90, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 105, "solar_kwh": 90, "tariff_bdt_per_kwh": 12},
      {"hour": 16, "demand_kwh": 120, "solar_kwh": 40, "tariff_bdt_per_kwh": 10},
      {"hour": 17, "demand_kwh": 145, "solar_kwh": 10, "tariff_bdt_per_kwh": 9},
      {"hour": 18, "demand_kwh": 165, "solar_kwh": 0, "tariff_bdt_per_kwh": 14},
      {"hour": 19, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 16},
      {"hour": 20, "demand_kwh": 165, "solar_kwh": 0, "tariff_bdt_per_kwh": 16},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 15},
      {"hour": 22, "demand_kwh": 185, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 195, "solar_kwh": 0, "tariff_bdt_per_kwh": 8}
    ],
    "battery": {
      "capacity_kwh": 300,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 30,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

### 3. Run deterministic service and guardrail checks
These in-process checks validate request handling, optimization, exact output
shape, LLM authority, and adversarial time-window normalization:
```bash
OPENAI_API_KEY= GEMINI_API_KEY= ./.venv/bin/python tests/test_api.py
./.venv/bin/python tests/test_interpreter.py
```

### 4. Run the supplied 10-case public pack
Point the runner at the JSON file supplied with the participant documents:
```bash
GRIDWISE_SAMPLE_FILE="/path/to/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json" \
  ./.venv/bin/python tests/test_samples.py
```
The verified result for the supplied pack is `10/10 CASES PASSED`, with every directive matching, every replay valid, and every reference cost matched within tolerance.

### 5. Run the real HTTP contract check
With the service running, exercise both endpoints, malformed JSON, unknown-field
rejection, and a complete optimization request through HTTP:
```bash
GRIDWISE_BASE_URL=http://127.0.0.1:8000 \
  ./.venv/bin/python tests/test_http.py
```

The successful response contains `scenario_id`, one ordered `directive_interpretation` entry per note, 24 `hourly_plan` entries, and recalculated `total_grid_kwh`, `total_cost_bdt`, `peak_grid_kwh`, and `plan_summary` fields. The public sample runner independently checks those fields through `replay_and_verify_schedule`.

The repository includes a complete machine-valid example pair:

- Request: [`tests/samples/sample_request.json`](tests/samples/sample_request.json)
- Response: [`tests/samples/sample_response.json`](tests/samples/sample_response.json)

The response contains all 24 `hourly_plan` objects and every required top-level
field; no pseudo-JSON abbreviations are used.

---

## 6. Docker Fallback Instructions

A self-contained Dockerfile is provided to ensure full evaluation reproducibility.

### Build the Image
```bash
docker build -t gridwise-llm:latest .
```

### Run the Container
```bash
# Clean up any existing container with the same name
docker rm -f gridwise_service 2>/dev/null || true

docker run -d \
  --name gridwise_service \
  -p 8000:8000 \
  --env-file .env \
  gridwise-llm:latest
```

The `.env` file must supply at least one valid model credential. Keep it outside
the image and never commit it. The keyless emergency parser exists only for
local diagnostics and is not the mandatory LLM execution path used for judging.

Verify the container is responding:
```bash
curl http://localhost:8000/health
```

---

## 7. Supported Directives Reference

| Directive Type | Description | Required Adjustment Format |
| :--- | :--- | :--- |
| `solar_reduction` | Degrades usable solar generation | `{"hours": [int, ...], "factor": float}` |
| `minimum_battery_reserve` | Raises reserve floor | `{"hours": [int, ...], "minimum_energy_kwh": float}` |
| `no_charge_window` | Prohibits battery charging | `{"hours": [int, ...]}` |
| `no_discharge_window` | Prohibits battery discharging | `{"hours": [int, ...]}` |
| `max_grid_window` | Enforces feeder/substation cap | `{"hours": [int, ...], "max_grid_kwh": float}` |
| `no_op` | Distractor / non-actionable note | `applies: false`, `structured_adjustment: null` |

*All hour intervals are start-inclusive and end-exclusive (e.g. 1 PM to 3 PM $\rightarrow$ `[13, 14]`).*

---

## 8. Known Limitations & Notes
- Campus export back into the main grid is not supported per challenge rules.
- Scenarios assume hourly intervals ($h=0 \dots 23$).
- Hosted-model credentials, quota, cost, rate limits, and availability remain the team's responsibility.
- If both hosted providers are unavailable, the emergency parser preserves service continuity but does not replace the challenge requirement to operate with a language-capable model during judging.
- The exact public endpoint, repository URL, registry tag/digest, and video URL are supplied through the official submission fields and must remain reachable throughout evaluation.
