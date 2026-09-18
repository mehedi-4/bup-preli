import math
from typing import List, Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ----------------- REQUEST SCHEMAS -----------------

class HourInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    demand_kwh: float = Field(..., ge=0, description="Campus electricity demand in kWh")
    solar_kwh: float = Field(..., ge=0, description="Available solar generation in kWh")
    tariff_bdt_per_kwh: float = Field(..., ge=0, description="Grid electricity tariff in BDT/kWh")

    @field_validator("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")
    @classmethod
    def validate_finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("numeric values must be finite")
        return value

class BatteryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity_kwh: float = Field(..., gt=0, description="Total battery capacity in kWh")
    initial_energy_kwh: float = Field(..., ge=0, description="Battery energy at start of day")
    minimum_energy_kwh: float = Field(..., ge=0, description="Base minimum allowable battery reserve")
    max_charge_kwh_per_hour: float = Field(..., ge=0, description="Maximum charge rate in kWh/hr")
    max_discharge_kwh_per_hour: float = Field(..., ge=0, description="Maximum discharge rate in kWh/hr")

    @field_validator(
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    )
    @classmethod
    def validate_finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_energy_relationships(self):
        if self.initial_energy_kwh > self.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if self.initial_energy_kwh < self.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh cannot be below minimum_energy_kwh")
        return self

class OptimizeEnergyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., min_length=1, description="Unique scenario ID")
    operator_notes: List[str] = Field(..., min_length=1, max_length=3, description="1-3 natural-language operator notes")
    hours: List[HourInput] = Field(..., min_length=24, max_length=24, description="Hourly data for 24 hours")
    battery: BatteryInput = Field(..., description="Battery configuration parameters")

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("scenario_id must be non-empty")
        return value

    @field_validator("operator_notes")
    @classmethod
    def validate_operator_notes(cls, value: List[str]) -> List[str]:
        cleaned = [note.strip() for note in value]
        if any(not note for note in cleaned):
            raise ValueError("operator_notes must contain non-empty strings")
        return cleaned

    @field_validator("hours")
    def validate_hours_sequence(cls, v: List[HourInput]) -> List[HourInput]:
        hours_seen = [h.hour for h in v]
        if len(set(hours_seen)) != 24 or set(hours_seen) != set(range(24)):
            raise ValueError("hours array must contain exactly one entry for every hour from 0 to 23")
        # The contract requires complete unique coverage, not caller ordering.
        # Normalize once so the optimizer and replay code can safely index by hour.
        return sorted(v, key=lambda item: item.hour)

# ----------------- DIRECTIVE SCHEMAS -----------------

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
]

class DirectiveHoursAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: List[int] = Field(..., description="Hours affected (0-23 in ascending order)")

    @field_validator("hours")
    @classmethod
    def validate_directive_hours(cls, value: List[int]) -> List[int]:
        if not value:
            raise ValueError("directive hours must not be empty")
        if any(isinstance(hour, bool) for hour in value):
            raise ValueError("directive hours must be integers")
        if value != sorted(set(value)) or any(hour < 0 or hour > 23 for hour in value):
            raise ValueError("directive hours must be unique ascending integers from 0 to 23")
        return value


class SolarReductionAdjustment(DirectiveHoursAdjustment):
    factor: float = Field(..., ge=0.0, le=1.0, description="Usable fraction remaining (0 to 1)")


class MinimumBatteryReserveAdjustment(DirectiveHoursAdjustment):
    minimum_energy_kwh: float = Field(..., ge=0.0, description="Required minimum battery reserve in kWh")


class WindowAdjustment(DirectiveHoursAdjustment):
    pass


class MaxGridAdjustment(DirectiveHoursAdjustment):
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

    @model_validator(mode="after")
    def validate_directive_shape(self):
        if self.directive_type == "no_op":
            if self.applies or self.structured_adjustment is not None:
                raise ValueError("no_op requires applies=false and structured_adjustment=null")
            return self

        if not self.applies or self.structured_adjustment is None:
            raise ValueError("active directives require applies=true and a structured adjustment")

        adjustment_model = {
            "solar_reduction": SolarReductionAdjustment,
            "minimum_battery_reserve": MinimumBatteryReserveAdjustment,
            "no_charge_window": WindowAdjustment,
            "no_discharge_window": WindowAdjustment,
            "max_grid_window": MaxGridAdjustment,
        }[self.directive_type]
        parsed = adjustment_model.model_validate(self.structured_adjustment)
        self.structured_adjustment = parsed.model_dump()
        return self

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
