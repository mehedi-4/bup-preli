from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field, field_validator

# ----------------- REQUEST SCHEMAS -----------------

class HourInput(BaseModel):
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0, description="Campus electricity demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Available solar generation in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity tariff in BDT/kWh")

class BatteryInput(BaseModel):
    capacity_kwh: float = Field(..., gt=0, description="Total battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at start of day")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base minimum allowable battery reserve")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum charge rate in kWh/hr")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum discharge rate in kWh/hr")

class OptimizeEnergyRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, description="Unique scenario ID")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural-language operator notes")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="Hourly data for 24 hours")
    battery: BatteryInput = Field(..., description="Battery configuration parameters")

    @field_validator("hours")
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        hours_seen = [h.hour for h in v]
        if hours_seen != list(range(24)):
            raise ValueError("hours array must contain exactly 24 entries from 0 to 23 in order")
        return v

# ----------------- DIRECTIVE SCHEMAS -----------------

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

class SolarReductionAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    factor: float = Field(..., ge=0.0, le=1.0, description="Usable fraction remaining (0 to 1)")

class MinimumBatteryReserveAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Required minimum battery reserve in kWh")

class WindowAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")

class MaxGridAdjustment(BaseModel):
    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")
    max_grid_kwh: float = Field(..., ge=0.0, description="Grid import upper limit in kWh")

StructuredAdjustment = Union[
    SolarReductionAdjustment,
    MinimumBatteryReserveAdjustment,
    WindowAdjustment,
    MaxGridAdjustment,
    None
]

class DirectiveInterpretationEntry(BaseModel):
    note_index: int = Field(..., ge=0, description="Index of the corresponding operator note")
    applies: bool = Field(..., description="true for active directives, false only for no_op")
    directive_type: DirectiveType = Field(..., description="Interpreted directive type")
    structured_adjustment: Optional[Dict[str, Any]] = Field(None, description="Directive parameters or null for no_op")
    explanation: str = Field(..., description="Human-readable rationale for the interpretation")

# ----------------- RESPONSE SCHEMAS -----------------

BatteryAction = Literal["charge", "discharge", "idle"]

class HourlyPlanEntry(BaseModel):
    hour: int = Field(..., ge=0, le=23)
    grid_kwh: float = Field(..., ge=0.0)
    solar_used_kwh: float = Field(..., ge=0.0)
    battery_action: BatteryAction
    battery_kwh: float = Field(..., ge=0.0)
    battery_energy_after_kwh: float = Field(..., ge=0.0)

class OptimizeEnergyResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationEntry]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str

class HealthResponse(BaseModel):
    status: str = "ok"
