from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .demo_data import get_demo_data
from .model_loader import (
    activate_model,
    load_feature_columns,
    load_model,
    load_model_info,
    load_threshold_metrics,
    load_walkforward_reference,
)
from .prediction import predict_record, predict_records
from .repository import repository
from .retraining import RetrainError, clear_retrained_artifacts, retrain, retrain_status
from .schemas import (
    BatchPredictionRequest,
    DemoAdvance,
    InspectionComplete,
    InspectionStart,
    PredictionResponse,
    ProcessRecord,
    RetrainRequest,
    ThresholdUpdate,
)
from .settings import (
    AUTO_RETRAIN_ENABLED,
    AUTO_RETRAIN_MIN_LABELS,
    DEMO_SEED_RECORDS,
    INITIAL_MODEL_VERSION,
    KNOWN_EQUIPMENT,
    MAX_THRESHOLD,
    MIN_THRESHOLD,
    SUPPORTED_EQUIPMENT,
    SUPPORTED_PART_NAMES,
    TRAINED_EQUIPMENT,
)


def advance_demo(count: int) -> list[dict]:
    """요청한 만큼 재생하되 표본 끝을 넘지 않는다.

    표본을 한 바퀴 돌면 처음으로 되돌아가지 않고 멈춘다. 다시 보려면
    `/demo/reset`으로 초기화한다.
    """
    demo = get_demo_data()
    # 재생 위치를 먼저 원자적으로 잡는다. 동시에 들어온 초기화나 다른 재생
    # 요청과 구간이 겹치지 않는다.
    sequence, count = repository.reserve_demo_sequence(count, len(demo))
    if not count:
        return []
    active = repository.active_model()
    model_version = active["version"] if active else load_model_info()["model_version"]
    threshold = repository.current_threshold()
    # 모델을 건별로 부르면 건당 42ms라 500건 시드에 21초가 걸린다. 한 번에 묶는다.
    batch = [demo.at(sequence + offset) for offset in range(count)]
    predicted = predict_records(batch, threshold, model_version)
    results: list[dict] = []
    for offset in range(count):
        event_sequence = sequence + offset
        record = batch[offset]
        outcome = predicted[offset]
        if isinstance(outcome, ValueError):
            error = outcome
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
                "threshold": threshold,
                "predicted_label": None,
                "prediction": "예측 불가",
                "inspection_status": None,
                "model_version": model_version,
                "process_values": {},
                "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
        else:
            result = outcome
        results.append(
            repository.save_prediction(
                result,
                replay_sequence=event_sequence,
                replay_cycle=event_sequence // len(demo),
            )
        )
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


def seed_model_registry() -> None:
    """초기 배포 모델을 레지스트리에 등록하고 active 모델을 서빙에 반영한다."""
    info = load_model_info()
    validation = info.get("validation", {})
    repository.seed_initial_model(
        version=info.get("model_version", INITIAL_MODEL_VERSION),
        model_file=info.get("model_file", "final_rf_part_balanced.pkl"),
        train_records=int(validation.get("records", 0)),
        train_defects=int(validation.get("defects", 0)),
    )
    active = repository.active_model()
    if active:
        try:
            activate_model(active["model_file"])
        except FileNotFoundError:
            # 재학습 산출물이 지워졌으면 초기 배포 모델로 되돌린다.
            repository.clear_retrained_models()
            fallback = repository.active_model()
            if fallback:
                activate_model(fallback["model_file"])


def maybe_auto_retrain() -> dict[str, Any] | None:
    """검사 결과가 기준만큼 쌓이면 자동으로 재학습한다."""
    if not AUTO_RETRAIN_ENABLED:
        return None
    demo = get_demo_data()
    summary = repository.summary(len(demo))
    status = retrain_status(repository, repository.current_threshold(), summary["operating"])
    if status["pending_inspections"] < AUTO_RETRAIN_MIN_LABELS:
        return None
    try:
        return retrain(
            repository,
            actor="자동 재학습",
            reason=f"검사 결과 {status['pending_inspections']}건 누적 (자동 기준 {AUTO_RETRAIN_MIN_LABELS}건)",
            trigger="자동",
        )
    except RetrainError:
        # 쌓인 검사가 전부 학습에 못 쓰는 건일 수 있다. 조용히 넘긴다.
        return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository.init()
    seed_model_registry()
    load_model()
    load_feature_columns()
    if not repository.list_predictions(limit=1):
        advance_demo(DEMO_SEED_RECORDS)
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
    active = repository.active_model()
    return {
        "status": "ok",
        "model_loaded": True,
        "model_version": active["version"] if active else load_model_info()["model_version"],
        "demo_records": len(get_demo_data()),
    }


@app.get("/model/info")
def model_info():
    """서빙 중인 모델 정보. 재학습된 모델이면 버전과 학습 규모를 갈아끼운다.

    검증 성능(AP, threshold 성능표)은 초기 모델을 교차검증해 얻은 값이라
    재학습 모델에 그대로 적용할 수 없다. 그래서 재학습 모델일 때는
    validation_stale 플래그를 함께 내려보낸다.
    """
    info = load_model_info()
    active = repository.active_model()
    retrained = bool(active and active["source"] != "초기 배포")
    if active:
        info = {
            **info,
            "model_version": active["version"],
            "model_source": active["source"],
            "trained_at": active["created_at"],
            "train_records": active["train_records"],
            "train_defects": active["train_defects"],
            "added_records": active["added_records"],
            "added_defects": active["added_defects"],
        }
    return {
        **info,
        "validation_stale": retrained,
        "supported_part_names": SUPPORTED_PART_NAMES,
        "current_threshold": repository.current_threshold(),
        "threshold_metrics": load_threshold_metrics(),
    }


@app.get("/model/registry")
def model_registry(limit: int = Query(default=50, ge=1, le=200)):
    return repository.model_registry(limit)


@app.get("/model/walkforward")
def model_walkforward():
    """07_2에서 측정한 재학습 주기별 성능. 재학습 필요성의 근거 자료다."""
    return load_walkforward_reference()


@app.get("/model/retrain/status")
def model_retrain_status():
    demo = get_demo_data()
    summary = repository.summary(len(demo))
    return {
        **retrain_status(repository, repository.current_threshold(), summary["operating"]),
        "auto_enabled": AUTO_RETRAIN_ENABLED,
    }


@app.post("/model/retrain")
def model_retrain(payload: RetrainRequest):
    try:
        return retrain(repository, payload.actor, payload.reason, trigger="수동")
    except RetrainError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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
    clear_retrained_artifacts()
    seed_model_registry()
    seeded = advance_demo(DEMO_SEED_RECORDS)
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
        result = repository.complete_inspection(record_id, payload.model_dump())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    # 검사 결과가 기준만큼 쌓였으면 여기서 바로 재학습한다 (약 0.5초).
    retrained = maybe_auto_retrain()
    return {**result, "auto_retrained": retrained}


@app.get("/inspections")
def inspections(limit: int = Query(default=50, ge=1, le=500)):
    return repository.list_inspections(limit)
