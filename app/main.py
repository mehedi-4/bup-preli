import logging
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import (
    OptimizeEnergyRequest,
    OptimizeEnergyResponse,
    HealthResponse
)
from app.interpreter.llm_service import llm_service
from app.optimizer.solver import solve_energy_schedule
from app.utils.replay import replay_and_verify_schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gridwise.api")

app = FastAPI(
    title="GridWise LLM - Smart Campus Energy Optimization Service",
    description="API for interpreting operator directives and generating optimal 24-hour campus energy schedules.",
    version="1.0.0"
)

# Exception handler for malformed / structurally invalid input (HTTP 400 per section 6.1)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning("Request validation error with %d issue(s)", len(exc.errors()))
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed or structurally invalid request.", "errors": exc.errors()}
    )

@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Readiness endpoint required by judging harness."""
    return HealthResponse(status="ok")

@app.post("/optimize-energy", response_model=OptimizeEnergyResponse, tags=["Optimization"])
def optimize_energy(req: OptimizeEnergyRequest):
    """
    Main challenge endpoint:
    1. Interprets operator notes via LLM with deterministic guardrails.
    2. Solves MILP optimization for 24-hour campus energy scheduling.
    3. Replays schedule for guaranteed physical and accounting validity.
    """
    try:
        logger.info(f"Processing scenario {req.scenario_id} with {len(req.operator_notes)} notes...")

        # 1. LLM Directive Interpretation & Guardrail Validation
        directives = llm_service.interpret_notes(req.operator_notes, req.battery)

        # 2. MILP Energy Optimization
        hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary = solve_energy_schedule(
            scenario_id=req.scenario_id,
            hours=req.hours,
            battery=req.battery,
            directives=directives
        )

        # 3. Schedule Replay Verification
        is_valid, errors = replay_and_verify_schedule(
            hours=req.hours,
            battery=req.battery,
            directives=directives,
            hourly_plan=hourly_plan,
            total_grid_kwh=total_grid_kwh,
            total_cost_bdt=total_cost_bdt,
            peak_grid_kwh=peak_grid_kwh
        )
        if not is_valid:
            logger.error(f"Schedule replay verification issues for {req.scenario_id}: {errors}")
            # Never return a plan that failed the same replay contract the
            # judge uses. The solver is expected to make this unreachable for
            # valid organizer scenarios.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Generated schedule failed deterministic validation."
            )

        return OptimizeEnergyResponse(
            scenario_id=req.scenario_id,
            directive_interpretation=directives,
            hourly_plan=hourly_plan,
            total_grid_kwh=total_grid_kwh,
            total_cost_bdt=total_cost_bdt,
            peak_grid_kwh=peak_grid_kwh,
            plan_summary=plan_summary
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Controlled internal error in scenario %s: %s", req.scenario_id, type(e).__name__)
        # Return controlled 500 without exposing secrets or raw stack traces.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A controlled error occurred during scenario optimization."
        )
