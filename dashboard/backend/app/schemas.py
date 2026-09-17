from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProcessRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_id: str | None = None
    id: str | None = Field(default=None, alias="_id")
    TimeStamp: str | None = None
    PART_FACT_PLAN_DATE: str | None = None
    PART_FACT_SERIAL: str | int | None = None
    PART_NO: str | None = None
    PART_NAME: str
    EQUIP_CD: str | None = None
    EQUIP_NAME: str | None = None
    ERR_FACT_QTY: float | None = None

    @property
    def resolved_id(self) -> str:
        return self.record_id or self.id or "manual-record"


class PredictionResponse(BaseModel):
    record_id: str
    produced_at: str | None
    part: str | None
    part_no: str | None
    part_name: str
    equip_cd: str | None
    equip_name: str | None
    supported: bool
    predictable: bool = True
    unsupported_reason: str | None = None
    defect_probability: float | None
    threshold: float
    predicted_label: int | None
    prediction: str
    inspection_status: str | None
    model_version: str
    process_values: dict[str, float | None] = Field(default_factory=dict)
    missing_features: list[str] = Field(default_factory=list)
    input_warnings: list[str] = Field(default_factory=list)
    created_at: str


class BatchPredictionRequest(BaseModel):
    records: list[ProcessRecord] = Field(min_length=1, max_length=500)


class ThresholdUpdate(BaseModel):
    threshold: float
    actor: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=2, max_length=300)


class InspectionStart(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    worker_name: str = Field(min_length=1, max_length=80)


class InspectionComplete(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    actual_label: Literal["정상", "불량"]
    defect_type: str | None = Field(default=None, max_length=100)
    checked_items: list[str] = Field(default_factory=list)
    action: str = Field(min_length=2, max_length=500)
    additional_inspection: bool = False

    @model_validator(mode="after")
    def require_defect_type(self):
        if self.actual_label == "불량" and not self.defect_type:
            raise ValueError("불량 판정 시 불량 유형을 선택해야 합니다.")
        if self.actual_label == "정상":
            self.defect_type = None
        return self


class DemoAdvance(BaseModel):
    count: int = Field(default=1, ge=1, le=20)



class RetrainRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=2, max_length=500)
