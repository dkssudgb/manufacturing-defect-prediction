from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .corrections import apply_record_corrections, detect_missing_features
from .model_loader import load_feature_columns, load_model
from .settings import MODEL_VERSION, SUPPORTED_EQUIPMENT, SUPPORTED_PARTS, SUPPORTED_PREFIXES


DISPLAY_PROCESS_COLUMNS = (
    "Injection_Time",
    "Filling_Time",
    "Cycle_Time",
    "Cushion_Position",
    "Max_Injection_Speed",
    "Max_Injection_Pressure",
    "Mold_Temperature_3",
    "Mold_Temperature_4",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.generic):
        return value.item()
    return value


def record_to_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        data = record.model_dump(by_alias=True)
        extras = getattr(record, "model_extra", None) or {}
        data.update(extras)
        return {key: clean_value(value) for key, value in data.items()}
    return {key: clean_value(value) for key, value in dict(record).items()}


def derive_part(part_name: str) -> str | None:
    name = (part_name or "").strip()
    if not name.startswith(SUPPORTED_PREFIXES) or len(name) < 5:
        return None
    return f"{name[:3]}{name[-2:]}"


def prepare_record(
    record: Any, threshold: float, model_version: str | None = None
) -> tuple[dict[str, Any], dict[str, float] | None]:
    """예측 직전까지의 판정을 수행한다.

    반환값이 (결과, None)이면 모델을 부르지 않고 끝난 건이다(미지원 품명,
    미학습 설비, 센서 결측 등). (골격, 입력행)이면 호출부가 확률을 채워야 한다.
    모델 호출을 분리해 두면 여러 건을 한 번에 예측할 수 있다. RandomForest는
    한 건씩 부르면 건당 42ms지만 500건을 한 번에 넣으면 전체 0.05초다.
    """
    data = record_to_dict(record)
    record_id = str(data.get("record_id") or data.get("_id") or "manual-record")
    part_name = str(data.get("PART_NAME") or "")
    part = derive_part(part_name)
    created_at = utc_now()

    common = {
        "record_id": record_id,
        "produced_at": clean_value(data.get("TimeStamp")),
        "part": part,
        "part_no": clean_value(data.get("PART_NO")),
        "part_name": part_name,
        "equip_cd": clean_value(data.get("EQUIP_CD")),
        "equip_name": clean_value(data.get("EQUIP_NAME")),
        "threshold": float(threshold),
        "model_version": model_version or MODEL_VERSION,
        "created_at": created_at,
    }

    if not part_name.startswith(SUPPORTED_PREFIXES):
        return {
            **common,
            "supported": False,
            "predictable": False,
            "unsupported_reason": "현재 모델은 CN7과 RG3 제품만 지원합니다.",
            "defect_probability": None,
            "predicted_label": None,
            "prediction": "모델 지원 대상 아님",
            "inspection_status": None,
            "process_values": {},
            "missing_features": [],
            "input_warnings": [],
        }, None

    if part not in SUPPORTED_PARTS:
        return {
            **common,
            "supported": False,
            "predictable": False,
            "unsupported_reason": f"학습되지 않은 Part 범주입니다: {part or '확인 불가'}",
            "defect_probability": None,
            "predicted_label": None,
            "prediction": "모델 입력 범주 미지원",
            "inspection_status": None,
            "process_values": {},
            "missing_features": [],
            "input_warnings": [],
        }, None

    equip_cd = clean_value(data.get("EQUIP_CD"))
    if equip_cd and equip_cd not in SUPPORTED_EQUIPMENT:
        return {
            **common,
            "supported": False,
            "predictable": False,
            "unsupported_reason": (
                f"학습하지 않은 설비입니다({equip_cd}). 지원 설비는 "
                f"{', '.join(f'{code}({name})' for code, name in SUPPORTED_EQUIPMENT.items())}입니다."
            ),
            "defect_probability": None,
            "predicted_label": None,
            "prediction": "모델 지원 대상 아님",
            "inspection_status": None,
            "process_values": {},
            "missing_features": [],
            "input_warnings": [],
        }, None

    feature_columns = load_feature_columns()
    numeric_columns = [column for column in feature_columns if not column.startswith("Part_")]
    missing = [column for column in numeric_columns if clean_value(data.get(column)) is None]
    if missing:
        raise ValueError(f"필수 공정 변수가 누락되었습니다: {', '.join(missing)}")

    row: dict[str, float] = {}
    invalid: list[str] = []
    for column in numeric_columns:
        try:
            row[column] = float(data[column])
        except (TypeError, ValueError):
            invalid.append(column)
    if invalid:
        raise ValueError(f"숫자형 공정 변수 형식이 올바르지 않습니다: {', '.join(invalid)}")

    # 수집 채널이 끊기면 6개 변수가 함께 0으로 들어온다. 이 경우 예측하지 않는다.
    missing_features = detect_missing_features(row)
    process_values = {
        column: clean_value(data.get(column)) for column in DISPLAY_PROCESS_COLUMNS
    }
    if missing_features:
        return {
            **common,
            "supported": True,
            "predictable": False,
            "unsupported_reason": None,
            "defect_probability": None,
            "predicted_label": None,
            "prediction": "데이터 결측",
            "inspection_status": None,
            "process_values": process_values,
            "missing_features": missing_features,
            "input_warnings": [
                f"센서 데이터 {len(missing_features)}개 항목 결측 (수집 채널 확인 필요)"
            ],
        }, None

    # 학습과 같은 규칙으로 기록 오류를 보정한다 (utils/preprocessing.py)
    row, input_warnings = apply_record_corrections(row)


    for column in (column for column in feature_columns if column.startswith("Part_")):
        row[column] = float(part == column.removeprefix("Part_"))

    skeleton = {
        **common,
        "supported": True,
        "predictable": True,
        "unsupported_reason": None,
        "process_values": process_values,
        "missing_features": [],
        "input_warnings": input_warnings,
    }
    return skeleton, {column: row[column] for column in feature_columns}


def apply_probability(
    skeleton: dict[str, Any],
    probability: float,
    threshold: float,
    model_features: dict[str, float] | None = None,
) -> dict[str, Any]:
    """확률을 채워 결과를 완성한다.

    모델에 실제로 들어간 26개 피처를 함께 싣는다. 재학습은 이 값을 쓴다.
    검사 결과만으로는 학습 행을 만들 수 없고, 예측 시점을 놓치면 보정까지
    끝난 입력을 다시 복원할 방법이 없다.
    """
    predicted_label = int(probability >= threshold)
    return {
        **skeleton,
        "defect_probability": probability,
        "predicted_label": predicted_label,
        "prediction": "불량 위험" if predicted_label else "정상",
        "inspection_status": "검사 대기" if predicted_label else None,
        "model_features": model_features or {},
    }


def predict_records(
    records: list[Any], threshold: float, model_version: str | None = None
) -> list[dict[str, Any]]:
    """여러 건을 예측한다. 모델은 한 번만 호출한다.

    개별 건에서 ValueError가 나면 그 자리에 예외를 담아 돌려준다. 호출부가
    건별로 처리할 수 있어야 재생이 한 건 때문에 멈추지 않는다.
    """
    feature_columns = load_feature_columns()
    prepared: list[Any] = []
    for record in records:
        try:
            prepared.append(prepare_record(record, threshold, model_version))
        except ValueError as error:
            prepared.append(error)

    pending = [
        (index, row)
        for index, item in enumerate(prepared)
        if not isinstance(item, ValueError) and item[1] is not None
        for row in (item[1],)
    ]
    if pending:
        matrix = pd.DataFrame([row for _, row in pending], columns=feature_columns)
        probabilities = load_model().predict_proba(matrix)[:, 1]
        for (index, row), probability in zip(pending, probabilities):
            skeleton, _ = prepared[index]
            prepared[index] = (
                apply_probability(skeleton, float(probability), threshold, row),
                None,
            )

    return [item if isinstance(item, ValueError) else item[0] for item in prepared]


def predict_record(
    record: Any, threshold: float, model_version: str | None = None
) -> dict[str, Any]:
    """한 건을 예측한다. 기존 호출부 호환을 위해 유지한다."""
    result, row = prepare_record(record, threshold, model_version)
    if row is None:
        return result
    feature_columns = load_feature_columns()
    matrix = pd.DataFrame([row], columns=feature_columns)
    probability = float(load_model().predict_proba(matrix)[0, 1])
    return apply_probability(result, probability, threshold, row)

