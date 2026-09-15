from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .demo_data import get_demo_data
from .model_loader import load_feature_columns, load_model, load_model_info, load_threshold_metrics
from .prediction import predict_record
from .repository import repository
from .schemas import (
    BatchPredictionRequest,
    DemoAdvance,
    InspectionComplete,
    InspectionStart,
    PredictionResponse,
    ProcessRecord,
    ThresholdUpdate,
)
from .settings import KNOWN_EQUIPMENT, MAX_THRESHOLD, MIN_THRESHOLD, SUPPORTED_EQUIPMENT, TRAINED_EQUIPMENT


def advance_demo(count: int) -> list[dict]:
    """요청한 만큼 재생하되 표본 끝을 넘지 않는다.

    표본을 한 바퀴 돌면 처음으로 되돌아가지 않고 멈춘다. 다시 보려면
    `/demo/reset`으로 초기화한다.
    """
    demo = get_demo_data()
    sequence = repository.demo_sequence()
    remaining = max(0, len(demo) - sequence)
    count = min(count, remaining)
    results: list[dict] = []
    for offset in range(count):
        event_sequence = sequence + offset
        record = demo.at(event_sequence)
        try:
            result = predict_record(record, repository.current_threshold())
        except ValueError as error:
            result = {
                "record_id": str(record.get("_id") or f"demo-{event_sequence % len(demo)}"),
                "produced_at": record.get("TimeStamp"),
                "part": None,
                "part_no": record.get("PART_NO"),
                "part_name": str(record.get("PART_NAME") or ""),
                "equip_cd": record.get("EQUIP_CD"),
                "equip_name": record.get("EQUIP_NAME"),
                "supported": False,
                "unsupported_reason": str(error),
                "defect_probability": None,
                "threshold": repository.current_threshold(),
                "predicted_label": None,
                "prediction": "예측 불가",
                "inspection_status": None,
                "model_version": load_model_info()["model_version"],
                "process_values": {},
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
        results.append(
            repository.save_prediction(
                result,
                replay_sequence=event_sequence,
                replay_cycle=event_sequence // len(demo),
            )
        )
    repository.set_state("demo_sequence", sequence + count)
    repository.set_state("demo_cursor", min(sequence + count, len(demo)))
    return results


def demo_progress() -> dict[str, Any]:
    demo = get_demo_data()
    played = min(repository.demo_sequence(), len(demo))
    return {
        "played": played,
        "total": len(demo),
        "remaining": len(demo) - played,
        "finished": played >= len(demo),
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.init()
    load_model()
    load_feature_columns()
    if not repository.list_predictions(limit=1):
        advance_demo(12)
    yield


app = FastAPI(
    title="제조 공정 품질 예측 API",
    version="1.0.0",
    description="CN7·RG3 사출 제품의 불량 가능성 예측 및 검사 업무 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": True,
        "model_version": load_model_info()["model_version"],
        "demo_records": len(get_demo_data()),
    }


@app.get("/model/info")
def model_info():
    return {
        **load_model_info(),
        "current_threshold": repository.current_threshold(),
        "threshold_metrics": load_threshold_metrics(),
    }


@app.post("/predict", response_model=PredictionResponse)
def predict(record: ProcessRecord):
    try:
        result = predict_record(record, repository.current_threshold())
        return repository.save_prediction(result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/predict/batch", response_model=list[PredictionResponse])
def predict_batch(payload: BatchPredictionRequest):
    results = []
    for record in payload.records:
        try:
            results.append(repository.save_prediction(predict_record(record, repository.current_threshold())))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=f"{record.resolved_id}: {error}") from error
    return results


@app.get("/demo/progress")
def demo_progress_view():
    return demo_progress()


@app.get("/dashboard/summary")
def dashboard_summary(equip_cd: str | None = None):
    demo = get_demo_data()
    return repository.summary(len(demo), equip_cd)


@app.get("/equipment/summary")
def equipment_summary():
    observed = {row["equip_cd"]: row for row in repository.equipment_summary()}
    result = []
    for code, name in KNOWN_EQUIPMENT.items():
        row = observed.pop(code, {})
        result.append({
            "equip_cd": code,
            "equip_name": name,
            "model_supported": code in SUPPORTED_EQUIPMENT,
            "trained": code in TRAINED_EQUIPMENT,
            "received": int(row.get("received") or 0),
            "supported": int(row.get("supported") or 0),
            "risk": int(row.get("risk") or 0),
            "waiting": int(row.get("waiting") or 0),
            "inspecting": int(row.get("inspecting") or 0),
            "last_received": row.get("last_received"),
        })
    for code, row in observed.items():
        result.append({
            **row,
            "equip_cd": code,
            "model_supported": False,
            "trained": False,
            "received": int(row.get("received") or 0),
            "supported": int(row.get("supported") or 0),
            "risk": int(row.get("risk") or 0),
            "waiting": int(row.get("waiting") or 0),
            "inspecting": int(row.get("inspecting") or 0),
        })
    return result


@app.get("/predictions")
def predictions(
    limit: int = Query(default=50, ge=1, le=500), equip_cd: str | None = None
):
    return repository.list_predictions(limit, equip_cd)


@app.get("/predictions/search")
def search_predictions(
    keyword: str | None = Query(default=None, max_length=80),
    prediction_state: str = Query(default="all", pattern="^(all|risk|normal|unavailable)$"),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    equip_cd: str | None = None,
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return repository.search_predictions(
        keyword=keyword,
        prediction_state=prediction_state,
        date_from=date_from,
        date_to=date_to,
        equip_cd=equip_cd,
        limit=limit,
        offset=offset,
    )


@app.get("/predictions/{record_id}")
def prediction_detail(record_id: str):
    result = repository.get_prediction(record_id)
    if not result:
        raise HTTPException(status_code=404, detail="해당 제품의 예측 이력이 없습니다.")
    return result


@app.get("/prediction-events")
def prediction_events(
    limit: int = Query(default=60, ge=10, le=200),
    offset: int = Query(default=0, ge=0),
    equip_cd: str | None = None,
):
    return repository.list_prediction_events(limit, offset, equip_cd)


@app.get("/inspection-queue")
def inspection_queue(
    limit: int = Query(default=500, ge=1, le=2000), equip_cd: str | None = None
):
    return repository.list_inspection_queue(limit, equip_cd)


@app.post("/demo/next")
def demo_next(payload: DemoAdvance):
    processed = advance_demo(payload.count)
    return {"processed": processed, **demo_progress()}


@app.post("/demo/reset")
def demo_reset():
    repository.reset_demo()
    seeded = advance_demo(12)
    return {"status": "reset", "seeded": len(seeded), **demo_progress()}


@app.patch("/threshold")
def change_threshold(payload: ThresholdUpdate):
    if not MIN_THRESHOLD <= payload.threshold <= MAX_THRESHOLD:
        raise HTTPException(
            status_code=422,
            detail=f"Threshold는 {MIN_THRESHOLD:.2f}~{MAX_THRESHOLD:.2f} 범위여야 합니다.",
        )
    return repository.update_threshold(payload.threshold, payload.actor, payload.reason)


@app.get("/threshold/history")
def threshold_history(limit: int = Query(default=20, ge=1, le=100)):
    return repository.threshold_history(limit)


@app.post("/inspections/{record_id}/start")
def start_inspection(record_id: str, payload: InspectionStart):
    try:
        return repository.start_inspection(record_id, payload.worker_id, payload.worker_name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/inspections/{record_id}/complete")
def complete_inspection(record_id: str, payload: InspectionComplete):
    try:
        return repository.complete_inspection(record_id, payload.model_dump())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/inspections")
def inspections(limit: int = Query(default=50, ge=1, le=500)):
    return repository.list_inspections(limit)
