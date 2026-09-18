# GridWise LLM — Smart Campus Energy Optimization Service

**BUP CSE Fest 2026 Hackathon · Online Preliminary Round**  
*Challenge Type: LLM-Assisted Smart Campus Energy Scheduling & Optimization*

---

## 1. Overview & System Architecture

GridWise LLM is an enterprise-grade, high-performance HTTP microservice designed to solve the 24-hour campus energy scheduling problem under dynamic tariffs, solar generation, demand, and unstructured natural language operator directives.

### The 4-Stage Processing Pipeline

```
                       Campus Operator Notes
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 1: LLM Directive Interpretation          │
         │ - Dual-engine: OpenAI (gpt-4o-mini)            │
         │ - Fallback: Google Gemini (gemini-3.5-flash)   │
         │ - Structured JSON Output with Pydantic schema  │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 2: Deterministic Guardrails              │
         │ - Validates allowed directive types            │
         │ - Enforces unique ascending hours [0..23]      │
         │ - Clamps solar factors (0-1) and battery caps  │
         │ - Enforces Section 04 exact adjustment shapes  │
         └───────────────────────┬────────────────────────┘
                                 │
                                 ▼
         ┌────────────────────────────────────────────────┐
         │ Stage 3: MILP Mathematical Optimization        │
         │ - SciPy HiGHS Solver (sub-10ms dispatch)       │
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
| **Primary LLM** | **OpenAI (`gpt-4o-mini`)** | Structured directive extraction, paraphrase comprehension, distractor filtering. |
| **Fallback LLM** | **Google Gemini (`gemini-3.5-flash-lite`)** | Automatic failover if primary provider encounters quota/latency issues. |
| **Catastrophic Fallback** | **Deterministic Heuristic Engine** | Failsafe rule-based parsing ensuring the service never crashes on complete external network outages. |
| **Mathematical Solver** | **SciPy MILP (`HiGHS` solver)** | Exact global cost minimization under hourly linear and integrality constraints. |
| **API Framework** | **FastAPI + Uvicorn** | High-throughput asynchronous web server complying with the exact challenge schema. |

---

## 3. Environment Variables & Configuration

The service uses standard environment variables. You can configure them via a `.env` file or export them directly:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OPENAI_API_KEY` | Paid OpenAI API key | *(Optional if Gemini provided)* |
| `GEMINI_API_KEY` | Google Gemini API key | *(Optional if OpenAI provided)* |
| `PRIMARY_PROVIDER` | Preferred provider (`openai` or `gemini`) | `openai` (if key set) else `gemini` |
| `OPENAI_MODEL` | OpenAI Model ID | `gpt-4o-mini` |
| `GEMINI_MODEL` | Gemini Model ID | `gemini-3.5-flash-lite` |
| `PORT` | HTTP service port | `8000` |
| `HOST` | Bind host address | `0.0.0.0` |

> **Security Note:** No API keys, credentials, or secrets are baked into this repository or the Docker container. All keys are injected securely at runtime via environment variables.

---

## 4. Local Quickstart (Fresh Environment)

### Step 1: Clone Repository & Create Virtual Environment
```bash
git clone <repository-url>
cd bup-preli

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
```bash
cp .env.example .env
# Edit .env and insert your API key(s):
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

### 3. Run Automated Validation Test Suite
Execute the test runner against the 10 official public sample cases:
```bash
python tests/test_samples.py
```
**Results:** `10/10 CASES PASSED` with 0.0000 cost error and 100% semantic directive accuracy.

---

## 6. Docker Fallback Instructions

A self-contained Dockerfile is provided to ensure full evaluation reproducibility.

### Build the Image
```bash
docker build -t gridwise-llm:latest .
```

### Run the Container
```bash
docker run -d \
  --name gridwise_service \
  -p 8000:8000 \
  -e OPENAI_API_KEY="your_openai_key" \
  -e GEMINI_API_KEY="your_gemini_key" \
  gridwise-llm:latest
```

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
