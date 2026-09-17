import os
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).parent / "test_dashboard_data.db"
os.environ.setdefault("DASHBOARD_TEST", "1")

from app.main import app  # noqa: E402
from app.demo_data import get_demo_data  # noqa: E402
from app.repository import repository  # noqa: E402


@pytest.fixture(scope="module")
def client():
    """TestClient를 테스트 모듈 전체에서 재사용한다.

    테스트마다 새로 만들면 Windows에서 이벤트 루프 소켓 자원이 고갈되어
    `OSError: [WinError 10014]`가 간헐적으로 발생한다. 각 테스트가 시작할 때
    `/demo/reset`으로 상태를 초기화하므로 클라이언트를 공유해도 무방하다.
    """
    with TestClient(app) as test_client:
        yield test_client


def advance_until_alarm(client, max_batches: int = 10, count: int = 20) -> list[dict]:
    """알람이 나올 때까지 재생을 진행한다.

    확정한 시연 구간(2020-10-18 ~ 10-22)은 앞의 3일이 알람률 3.5 ~ 3.9%인 안정
    구간이고 10-21 이후에 20% 이상으로 올라간다. 따라서 재생 직후 몇 건만 보고
    알람을 기대하면 안 되고, 재생을 진행하며 확인해야 한다.
    """
    for _ in range(max_batches):
        predictions = client.get("/predictions?limit=200").json()
        if any(item["prediction"] == "불량 위험" for item in predictions):
            return predictions
        assert client.post("/demo/next", json={"count": count}).status_code == 200
    raise AssertionError("시연 표본을 모두 재생했으나 알람이 없습니다.")


def test_health_and_model_info(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["model_loaded"] is True

    info = client.get("/model/info")
    assert info.status_code == 200
    assert info.json()["model_file"] == "final_rf_part_balanced.pkl"
    assert info.json()["feature_count"] == 26
    assert info.json()["default_threshold"] == pytest.approx(0.163)
    assert "data_corrections" in info.json()


def test_demo_sample_has_requested_composition():
    records = get_demo_data().records
    parts = [f"{item['PART_NAME'][:3]}{item['PART_NAME'][-2:]}" for item in records]
    assert len(records) == 1000
    assert parts.count("CN7LH") == 245
    assert parts.count("CN7RH") == 245
    assert parts.count("RG3LH") == 245
    assert parts.count("RG3RH") == 245
    assert sum(part not in {"CN7LH", "CN7RH", "RG3LH", "RG3RH"} for part in parts) == 20


def test_demo_predictions_include_real_model_result(client):
    client.post("/demo/reset")
    predictions = advance_until_alarm(client)
    assert predictions
    supported = [item for item in predictions if item["supported"]]
    assert supported

    predictable = [item for item in supported if item["predictable"]]
    assert predictable
    assert all(0 <= item["defect_probability"] <= 1 for item in predictable)
    assert any(item["prediction"] == "불량 위험" for item in predictable)

    # 센서 결측 행은 예측하지 않고 사유를 남긴다
    for item in supported:
        if not item["predictable"]:
            assert item["defect_probability"] is None
            assert item["prediction"] == "데이터 결측"
            assert item["missing_features"]


def test_waiting_items_do_not_disappear_when_recent_feed_rolls_over(client):
    client.post("/demo/reset")
    advance_until_alarm(client)
    original_queue = client.get("/inspection-queue").json()
    assert original_queue
    original_ids = {item["record_id"] for item in original_queue}

    for _ in range(5):
        response = client.post("/demo/next", json={"count": 20})
        assert response.status_code == 200

    recent_ids = {item["record_id"] for item in client.get("/predictions?limit=60").json()}
    active_ids = {item["record_id"] for item in client.get("/inspection-queue").json()}

    assert original_ids <= active_ids
    assert original_ids - recent_ids


def test_equipment_summary_and_filter_are_consistent(client):
    client.post("/demo/reset")
    for _ in range(5):
        client.post("/demo/next", json={"count": 20})

    equipment = client.get("/equipment/summary")
    assert equipment.status_code == 200
    known = {item["equip_cd"]: item for item in equipment.json()}
    assert known["S06"]["equip_name"] == "550TON-도시바"
    assert known["S14"]["equip_name"] == "650톤-우진2호기"

    for equip_cd in ("S06", "S14"):
        filtered_predictions = client.get(
            f"/predictions?limit=500&equip_cd={equip_cd}"
        ).json()
        filtered_summary = client.get(
            f"/dashboard/summary?equip_cd={equip_cd}"
        ).json()
        filtered_queue = client.get(
            f"/inspection-queue?limit=500&equip_cd={equip_cd}"
        ).json()
        # 목록은 limit 500에서 잘리므로 총 건수는 검색 total로 확인한다
        searched = client.get(
            f"/predictions/search?prediction_state=all&limit=1&offset=0&equip_cd={equip_cd}"
        ).json()
        assert filtered_summary["received"] == searched["total"]
        assert all(item["equip_cd"] == equip_cd for item in filtered_predictions)
        assert all(item["equip_cd"] == equip_cd for item in filtered_queue)


def test_prediction_events_accumulate_and_paginate(client):
    """재생은 순환하지 않으므로 매 건이 새 제품이고, 이벤트 이력은 누적된다.

    이전에는 표본을 한 바퀴 돌면 같은 제품이 다시 들어오는 구조여서 예측 행과
    이벤트 이력을 분리해 검증했다. 재생이 표본 끝에서 멈추도록 바뀐 뒤에는
    같은 제품이 다시 들어오지 않는다.
    """
    client.post("/demo/reset")
    # /predictions는 limit 상한이 500이라 시드 건수가 그 이상이면 잘린다.
    # 전체 건수는 검색의 total로 센다.
    def unique_total():
        return client.get("/predictions/search?prediction_state=all&limit=1&offset=0").json()["total"]

    unique_before = unique_total()
    events_before = client.get("/prediction-events?limit=10&offset=0").json()["total"]

    client.post("/demo/next", json={"count": 20})

    unique_after = unique_total()
    events_after = client.get("/prediction-events?limit=10&offset=0").json()["total"]
    assert unique_after == unique_before + 20
    assert events_after == events_before + 20

    latest = client.get("/prediction-events?limit=10&offset=0").json()
    older = client.get("/prediction-events?limit=10&offset=10").json()
    assert latest["total"] > 10
    assert {item["event_id"] for item in latest["items"]}.isdisjoint(
        {item["event_id"] for item in older["items"]}
    )


def test_threshold_and_inspection_flow(client):
    reset = client.post("/demo/reset")
    assert reset.status_code == 200

    # 확정 운영점(0.163, 검사 물량 10%)으로 바꿔 검사 대기가 생기는지 확인한다
    changed = client.patch(
        "/threshold",
        json={"threshold": 0.163, "actor": "테스트 관리자", "reason": "검사 흐름 테스트"},
    )
    assert changed.status_code == 200
    assert changed.json()["new_threshold"] == pytest.approx(0.163)

    predictions = advance_until_alarm(client)
    target = next(item for item in predictions if item["inspection_status"] == "검사 대기")

    started = client.post(
        f"/inspections/{target['record_id']}/start",
        json={"worker_id": "worker-01", "worker_name": "김현장"},
    )
    assert started.status_code == 200

    completed = client.post(
        f"/inspections/{target['record_id']}/complete",
        json={
            "worker_id": "worker-01",
            "actual_label": "정상",
            "checked_items": ["금형", "사출 압력"],
            "action": "공정값 확인 후 정상 복귀",
            "additional_inspection": False,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["evaluation"] == "FP"


def _sample_record(**overrides) -> dict:
    """시연 표본의 첫 지원 제품을 기반으로 요청 본문을 만든다."""
    demo = get_demo_data()
    row = next(
        record
        for record in demo.records
        if str(record.get("PART_NAME", "")).startswith(("CN7", "RG3"))
    )
    record = dict(row)
    record.update(overrides)
    return record


def test_screw_speed_scale_is_corrected_before_prediction(client):
    """Average_Screw_RPM이 10배로 기록돼 들어오면 보정하고 경고를 남긴다."""
    record = _sample_record(Average_Screw_RPM=292.5)
    response = client.post("/predict", json=record)
    assert response.status_code == 200
    body = response.json()

    assert body["predictable"] is True
    assert body["defect_probability"] is not None
    assert any("Average_Screw_RPM" in warning for warning in body["input_warnings"])

    # 보정된 값(29.25)으로 직접 넣으면 같은 확률이 나와야 한다
    same = client.post("/predict", json=_sample_record(Average_Screw_RPM=29.25, record_id="scale-check")).json()
    assert same["defect_probability"] == pytest.approx(body["defect_probability"])


def test_back_pressure_pair_is_rebuilt(client):
    """평균 배압이 최대 배압보다 크게 들어오면 쌍을 재구성한다."""
    record = _sample_record(Average_Back_Pressure=59.5, Max_Back_Pressure=37.9, record_id="bp-check")
    response = client.post("/predict", json=record)
    assert response.status_code == 200
    assert any("Back_Pressure" in warning for warning in response.json()["input_warnings"])


def test_sensor_missing_record_is_not_predicted(client):
    """수집 채널이 끊겨 6개 변수가 0으로 들어오면 예측하지 않는다."""
    record = _sample_record(
        record_id="missing-check",
        Max_Screw_RPM=0,
        Average_Screw_RPM=0,
        Average_Back_Pressure=0,
        Barrel_Temperature_1=0,
        Mold_Temperature_3=0,
        Mold_Temperature_4=0,
    )
    response = client.post("/predict", json=record)
    assert response.status_code == 200
    body = response.json()

    assert body["supported"] is True
    assert body["predictable"] is False
    assert body["prediction"] == "데이터 결측"
    assert body["defect_probability"] is None
    assert len(body["missing_features"]) == 6


def test_untrained_part_category_is_rejected(client):
    """학습 범주에 없는 Part는 기준 범주로 조용히 예측되지 않아야 한다."""
    record = _sample_record(
        record_id="part-check",
        PART_NAME="RG3 MLD'G-RR GLS LWR CVR ASS'Y",
    )
    response = client.post("/predict", json=record)
    assert response.status_code == 200
    body = response.json()

    assert body["supported"] is False
    assert body["predictable"] is False
    assert body["prediction"] == "모델 입력 범주 미지원"
    assert body["defect_probability"] is None


def test_prediction_search_filters(client):
    """검색은 기간·판정 상태·키워드를 조합해 걸러낸다."""
    client.post("/demo/reset")
    advance_until_alarm(client)

    total = client.get("/predictions/search?limit=1").json()
    assert total["total"] > 0

    risk = client.get("/predictions/search?prediction_state=risk&limit=200").json()
    assert risk["total"] > 0
    assert all(item["prediction"] == "불량 위험" for item in risk["items"])
    assert risk["total"] < total["total"]

    unavailable = client.get("/predictions/search?prediction_state=unavailable&limit=200").json()
    assert all(item["defect_probability"] is None for item in unavailable["items"])

    keyword = client.get("/predictions/search?keyword=CN7&limit=200").json()
    assert keyword["total"] > 0
    assert all("CN7" in item["part_name"] for item in keyword["items"])

    window = client.get("/predictions/search?date_from=2020-10-21&date_to=2020-10-22&limit=200").json()
    assert all("2020-10-21" <= item["produced_at"][:10] <= "2020-10-22" for item in window["items"])

    combined = client.get(
        "/predictions/search?keyword=CN7&prediction_state=risk&date_from=2020-10-18&date_to=2020-10-22&limit=200"
    ).json()
    assert combined["total"] <= min(risk["total"], keyword["total"])

    missing = client.get("/predictions/search?keyword=존재하지않는제품&limit=10").json()
    assert missing["total"] == 0
    assert missing["items"] == []


def test_prediction_search_paginates(client):
    client.post("/demo/reset")
    advance_until_alarm(client)

    first = client.get("/predictions/search?limit=5&offset=0").json()
    second = client.get("/predictions/search?limit=5&offset=5").json()

    assert first["total"] == second["total"]
    assert len(first["items"]) == 5
    first_ids = {item["record_id"] for item in first["items"]}
    second_ids = {item["record_id"] for item in second["items"]}
    assert not (first_ids & second_ids)


def test_demo_stops_at_end_of_sample(client):
    """표본을 한 바퀴 재생하면 순환하지 않고 멈춘다."""
    reset = client.post("/demo/reset").json()
    total = reset["total"]
    assert reset["finished"] is False

    # 남은 건수를 모두 재생한다 (한 번에 최대 20건)
    for _ in range(total // 20 + 2):
        progress = client.post("/demo/next", json={"count": 20}).json()
        if progress["finished"]:
            break

    assert progress["played"] == total
    assert progress["remaining"] == 0
    assert progress["finished"] is True

    # 완료 후 요청해도 새로 처리하지 않는다
    after = client.post("/demo/next", json={"count": 20}).json()
    assert after["processed"] == []
    assert after["played"] == total

    # 순환 재생이 없으므로 예측 건수가 표본 크기를 넘지 않는다
    assert client.get("/predictions/search?limit=1").json()["total"] == total
    assert client.get("/demo/progress").json()["finished"] is True


def test_prediction_detail_endpoint(client):
    """추이 그래프의 점을 눌렀을 때 쓰는 단건 조회."""
    client.post("/demo/reset")
    advance_until_alarm(client)

    events = client.get("/prediction-events?limit=10&offset=0").json()["items"]
    assert events
    # 이벤트 행에는 공정값이 없으므로 상세는 원본 예측 행에서 가져와야 한다
    assert "process_values" not in events[0]

    detail = client.get(f"/predictions/{events[0]['record_id']}").json()
    assert detail["record_id"] == events[0]["record_id"]
    assert detail["process_values"]
    assert "predictable" in detail

    assert client.get("/predictions/no-such-record").status_code == 404

    # 경로가 검색·목록 엔드포인트를 가리지 않는다
    assert client.get("/predictions/search?limit=1").status_code == 200
    assert client.get("/predictions?limit=5").status_code == 200


def test_untrained_equipment_is_not_supported(client):
    """학습하지 않은 설비는 예측하지 않고 지원 대상 아님으로 반환한다."""
    supported = _sample_record(record_id="equip-supported", EQUIP_CD="S14")
    result = client.post("/predict", json=supported).json()
    assert result["supported"] is True
    assert result["predictable"] is True
    assert result["defect_probability"] is not None

    other = _sample_record(record_id="equip-unsupported", EQUIP_CD="S06")
    blocked = client.post("/predict", json=other).json()
    assert blocked["supported"] is False
    assert blocked["predictable"] is False
    assert blocked["prediction"] == "모델 지원 대상 아님"
    assert blocked["defect_probability"] is None
    assert "학습하지 않은 설비" in blocked["unsupported_reason"]


def test_equipment_summary_marks_supported_machine(client):
    # 앞선 테스트가 수동으로 넣은 예측을 지우고 시연 표본 상태에서 확인한다
    client.post("/demo/reset")
    summary = {row["equip_cd"]: row for row in client.get("/equipment/summary").json()}

    assert summary["S14"]["model_supported"] is True
    assert summary["S14"]["trained"] is True

    # 도시바는 학습 데이터가 없어 지원 대상이 아니며, 목록에는 남아 화면에서 비활성으로 보인다
    assert summary["S06"]["model_supported"] is False
    assert summary["S06"]["trained"] is False
    assert summary["S06"]["received"] == 0


# ---- 재학습 -------------------------------------------------------------


def advance_until_queue(client, needed: int, max_batches: int = 40) -> list[dict]:
    """검사 대기열이 needed건 이상이 될 때까지 재생한다.

    advance_until_alarm은 알람이 하나라도 나오면 멈추므로 대기열이 1~2건뿐이다.
    재학습 테스트는 여러 건의 라벨이 필요하다.
    """
    for _ in range(max_batches):
        queue = client.get(f"/inspection-queue?limit=500").json()
        if len(queue) >= needed:
            return queue
        assert client.post("/demo/next", json={"count": 20}).status_code == 200
    raise AssertionError(f"재생을 마쳤으나 검사 대기가 {needed}건에 못 미칩니다.")


def complete_inspections(client, count: int) -> list[dict]:
    """검사 대기열에서 count건을 시작하고 완료한다. 3건마다 한 번 불량으로 기록한다."""
    queue = advance_until_queue(client, count)
    results = []
    for index, record in enumerate(queue[:count]):
        client.post(
            f"/inspections/{record['record_id']}/start",
            json={"worker_id": "worker-01", "worker_name": "김현장"},
        )
        defect = index % 3 == 0
        response = client.post(
            f"/inspections/{record['record_id']}/complete",
            json={
                "worker_id": "worker-01",
                "actual_label": "불량" if defect else "정상",
                "defect_type": "미성형" if defect else None,
                "checked_items": ["금형"],
                "action": "확인 후 조치 기록",
                "additional_inspection": False,
            },
        )
        assert response.status_code == 200
        results.append(response.json())
    return results


def test_model_registry_seeds_initial_model(client):
    client.post("/demo/reset")
    registry = client.get("/model/registry").json()
    assert len(registry) == 1
    assert registry[0]["version"] == "v1.1.0"
    assert registry[0]["source"] == "초기 배포"
    assert registry[0]["active"] is True
    assert registry[0]["train_records"] == 5230


def test_retrain_without_labels_is_rejected(client):
    client.post("/demo/reset")
    response = client.post(
        "/model/retrain", json={"actor": "박품질", "reason": "표본 없이 시도"}
    )
    assert response.status_code == 409
    assert "검사 결과가 없습니다" in response.json()["detail"]


def test_retrain_uses_inspection_labels_and_swaps_model(client):
    from app.retraining import next_version
    from app.settings import AUTO_RETRAIN_MIN_LABELS

    client.post("/demo/reset")
    labels = AUTO_RETRAIN_MIN_LABELS - 1
    complete_inspections(client, labels)

    before = client.get("/model/retrain/status").json()
    assert before["pending_inspections"] == labels
    assert before["recommended"] is False

    response = client.post(
        "/model/retrain", json={"actor": "이분석", "reason": "검사 결과 반영"}
    )
    assert response.status_code == 200
    entry = response.json()
    assert entry["version"] == next_version("v1.1.0")
    assert entry["trigger"] == "수동"
    # 기준 5,230건에 검사로 확보한 라벨이 더해진다
    assert entry["train_records"] == 5230 + labels
    assert entry["added_records"] == labels
    assert entry["skipped"] == []

    # 서버 재시작 없이 운영 모델이 바뀐다
    expected = next_version("v1.1.0")
    assert client.get("/health").json()["model_version"] == expected
    info = client.get("/model/info").json()
    assert info["model_version"] == expected
    assert info["validation_stale"] is True

    client.post("/demo/next", json={"count": 1})
    latest = client.get("/predictions?limit=1").json()
    assert latest[0]["model_version"] == expected


def test_auto_retrain_fires_at_threshold(client):
    """기준 건수에 도달하는 그 검사에서 발동해야 한다.

    기준은 settings.AUTO_RETRAIN_MIN_LABELS이며 07_2의 반영 지연 구간에서
    나온 값이다. 숫자를 하드코딩하지 않고 상수를 따라간다.
    """
    from app.settings import AUTO_RETRAIN_MIN_LABELS as threshold

    client.post("/demo/reset")
    results = complete_inspections(client, threshold)

    # 기준 직전까지는 발동하지 않는다
    assert all(item.get("auto_retrained") is None for item in results[:-1])
    auto = results[-1]["auto_retrained"]
    assert auto is not None
    assert auto["trigger"] == "자동"
    assert auto["added_records"] == threshold

    status = client.get("/model/retrain/status").json()
    assert status["active_source"] == "재학습"
    assert status["pending_inspections"] == 0


def test_reset_restores_initial_model(client):
    from app.retraining import next_version
    from app.settings import AUTO_RETRAIN_MIN_LABELS

    client.post("/demo/reset")
    complete_inspections(client, AUTO_RETRAIN_MIN_LABELS - 1)
    client.post("/model/retrain", json={"actor": "이분석", "reason": "초기화 점검"})
    assert client.get("/health").json()["model_version"] == next_version("v1.1.0")

    client.post("/demo/reset")
    registry = client.get("/model/registry").json()
    assert [row["version"] for row in registry] == ["v1.1.0"]
    assert client.get("/health").json()["model_version"] == "v1.1.0"


def test_walkforward_reference_matches_report(client):
    payload = client.get("/model/walkforward").json()
    rows = {row["cadence"]: row for row in payload["rows"]}
    # REPORT.md 4.13의 세 숫자
    assert rows["50샷"]["recall_at_10"] == pytest.approx(0.628, abs=1e-3)
    assert rows["50샷"]["lift_at_10"] == pytest.approx(6.3, abs=0.05)
    assert rows["100샷"]["lift_at_10"] == pytest.approx(4.9, abs=0.05)
    assert rows["생산일"]["lift_at_10"] == pytest.approx(2.1, abs=0.05)


def test_validation_numbers_stay_tied_to_initial_model(client):
    """재학습해도 검증 수치는 v1.1.0 것이며, 그 사실이 플래그로 드러나야 한다.

    AP와 Threshold 성능표는 초기 모델을 교차검증해 얻은 값이라 재학습으로
    자동 갱신될 수 없다. 화면이 새 버전 옆에 옛 수치를 그대로 보여주면
    오해를 만들기 때문에 validation_stale로 구분한다.
    """
    from app.retraining import next_version
    from app.settings import AUTO_RETRAIN_MIN_LABELS

    client.post("/demo/reset")
    base = client.get("/model/info").json()
    assert base["validation_stale"] is False
    assert base["train_records"] == 5230

    # 자동 발동에 걸리지 않도록 기준보다 적게 검사한다
    labels = AUTO_RETRAIN_MIN_LABELS - 1
    complete_inspections(client, labels)
    client.post("/model/retrain", json={"actor": "이분석", "reason": "검증 표시 점검"})
    after = client.get("/model/info").json()

    # 운영 모델을 따라 바뀌는 값
    assert after["model_version"] == next_version("v1.1.0")
    assert after["train_records"] == 5230 + labels
    assert after["validation_stale"] is True

    # 초기 모델에 묶여 그대로인 값
    assert after["validation"]["records"] == base["validation"]["records"]
    assert after["validation"]["defects"] == base["validation"]["defects"]
    assert after["validation"]["average_precision_mean"] == base["validation"]["average_precision_mean"]
    assert after["threshold_metrics"] == base["threshold_metrics"]
    assert after["default_threshold"] == base["default_threshold"]


def test_retrain_artifacts_are_isolated_from_dev_instance():
    """테스트는 개발 인스턴스의 재학습 산출물 경로를 건드리면 안 된다."""
    from app.settings import RETRAIN_LABELS_PATH, RETRAINED_MODEL_DIR

    assert "test" in RETRAIN_LABELS_PATH.name
    assert RETRAINED_MODEL_DIR.name == "retrained_test"


def test_reset_seeds_enough_records_for_the_retrain_demo(client):
    """초기화 직후 바로 재학습 시연을 시작할 수 있어야 한다.

    위험 제품은 표본에 고르게 있지 않다. 첫 위험이 164번째에야 나오고
    301~500번째는 200건 내리 0건이다. 시드가 모자라면 검사 대기열이 비어
    자동 재학습 기준(10건)을 채울 수 없다.
    """
    from app.settings import AUTO_RETRAIN_MIN_LABELS, DEMO_SEED_RECORDS

    reset = client.post("/demo/reset").json()
    assert reset["played"] == DEMO_SEED_RECORDS

    summary = client.get("/dashboard/summary").json()
    assert summary["received"] == DEMO_SEED_RECORDS
    # 자동 재학습 기준을 채우고도 남을 만큼 대기열이 있어야 한다
    assert summary["waiting"] >= AUTO_RETRAIN_MIN_LABELS

    # 추이 차트가 그리는 최근 60건에 threshold를 넘는 점이 있어야 한다.
    # 시드가 위험 0건 구간(301~500번째)에 걸리면 차트가 바닥에 붙은 평평한
    # 선으로 보여 첫 화면이 비어 보인다.
    threshold = summary["current_threshold"]
    recent = client.get("/prediction-events?limit=60&offset=0").json()["items"]
    above = [
        item for item in recent
        if item["defect_probability"] is not None and item["defect_probability"] >= threshold
    ]
    assert above, "시드 지점의 최근 60건에 위험 판정이 하나도 없어 차트가 비어 보인다"


def test_inspection_queue_exposes_inspector(client):
    """검사 중인 제품은 담당자 이름이 함께 나와야 한다.

    worker_name은 inspections에만 있어 predictions 단독 조회로는 알 수 없다.
    화면에 쓰는 조회는 모두 조인해서 inspector를 내려준다.
    """
    client.post("/demo/reset")
    queue = advance_until_queue(client, 1)
    record_id = queue[0]["record_id"]
    client.post(
        f"/inspections/{record_id}/start",
        json={"worker_id": "manager-01", "worker_name": "박품질"},
    )

    in_progress = next(
        item for item in client.get("/inspection-queue?limit=500").json()
        if item["record_id"] == record_id
    )
    assert in_progress["inspection_status"] == "검사 중"
    assert in_progress["inspector"] == "박품질"
    assert in_progress["inspection_started_at"]

    assert client.get(f"/predictions/{record_id}").json()["inspector"] == "박품질"

    searched = client.get(
        f"/predictions/search?prediction_state=all&limit=5&offset=0&keyword={record_id}"
    ).json()
    assert searched["items"][0]["inspector"] == "박품질"

    # 검사가 시작되지 않은 제품은 담당자가 비어 있다
    untouched = next(
        item for item in client.get("/inspection-queue?limit=500").json()
        if item["record_id"] != record_id
    )
    assert untouched["inspector"] is None


def test_walkforward_rows_carry_performance_bands(client):
    """특정 주기 하나가 아니라 성능 구간으로 읽혀야 한다.

    ANALYSIS_RESULTS.md 7-1: 구간 안의 차이는 노이즈이며 의미 있는 구분은
    25분 이내 / 1시간~35시간 / 하루 세 가지다.
    """
    payload = client.get("/model/walkforward").json()
    assert payload["best_band"] == "25분 이내"
    bands = {row["cadence"]: row["band"] for row in payload["rows"]}
    assert bands["10샷"] == bands["25샷"] == bands["50샷"] == "25분 이내"
    assert bands["100샷"] == bands["500샷"] == "1시간 ~ 35시간"
    assert bands["생산일"] == "하루"


def test_concurrent_replay_does_not_rewind_the_cursor(client):
    """재생 중에 초기화가 들어와도 커서가 과거로 되감기지 않아야 한다.

    예전에는 advance가 진입 시점의 sequence를 들고 있다가 예측을 마친 뒤
    덮어써서, 초기화 직후 이미 저장된 제품을 다시 재생하는 상태가 됐다.
    그 상태에서는 재생을 눌러도 수신 건수가 늘지 않는다.
    """
    from app.settings import DEMO_SEED_RECORDS

    client.post("/demo/reset")
    before = client.get("/dashboard/summary").json()
    assert before["received"] == DEMO_SEED_RECORDS
    assert before["demo_cursor"] == DEMO_SEED_RECORDS

    client.post("/demo/next", json={"count": 5})
    after = client.get("/dashboard/summary").json()

    # 재생은 항상 새 제품을 가져와야 한다
    assert after["demo_cursor"] == DEMO_SEED_RECORDS + 5
    assert after["received"] == before["received"] + 5


def test_reserve_demo_sequence_hands_out_disjoint_ranges():
    """동시에 예약해도 구간이 겹치지 않아야 한다."""
    from app.repository import repository

    repository.set_state("demo_sequence", 0)
    first_start, first_count = repository.reserve_demo_sequence(10, 100)
    second_start, second_count = repository.reserve_demo_sequence(10, 100)
    assert (first_start, first_count) == (0, 10)
    assert (second_start, second_count) == (10, 10)

    # 표본 끝을 넘겨 달라고 해도 남은 만큼만 준다
    repository.set_state("demo_sequence", 95)
    start, count = repository.reserve_demo_sequence(10, 100)
    assert (start, count) == (95, 5)
    start, count = repository.reserve_demo_sequence(10, 100)
    assert count == 0


def test_predictions_store_the_model_input_features(client):
    """예측 시점에 26개 학습 피처를 남겨야 재학습이 가능하다.

    검사 결과만으로는 학습 행을 만들 수 없다. 예전에는 record_id로 재생 CSV를
    조인해 복원했는데 실제 라인에는 그런 파일이 없다.
    """
    import json as _json
    import sqlite3

    from app.model_loader import load_feature_columns
    from app.settings import DATABASE_PATH

    client.post("/demo/reset")
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT predictable, model_features FROM predictions"
    ).fetchall()
    connection.close()

    expected = set(load_feature_columns())
    predictable = [row for row in rows if row["predictable"]]
    assert predictable
    for row in predictable:
        assert set(_json.loads(row["model_features"])) == expected

    # 예측하지 않은 행에는 남기지 않는다
    for row in rows:
        if not row["predictable"]:
            assert _json.loads(row["model_features"]) == {}

    # 화면 응답에는 싣지 않는다. 행마다 26개 실수가 붙으면 순수한 낭비다.
    assert "model_features" not in client.get("/predictions?limit=1").json()[0]


def test_retraining_does_not_read_the_replay_sample():
    """재학습 경로가 재생 CSV를 참조하면 실제 라인에서 돌지 않는다."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app" / "retraining.py"
    text = source.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    for forbidden in ("get_demo_data", "DEMO_DATA_PATH", "realtime_sample"):
        assert forbidden not in body, f"재학습이 여전히 {forbidden}에 의존한다"


# ---- 검증 재측정 ---------------------------------------------------------


def test_retrain_bumps_the_patch_position(client):
    """재학습은 패치 자리를 올린다.

    검사 5건마다 돌 수 있어 시연 한 번에도 여러 번 일어난다. 라벨 5건 추가가
    마이너 버전 하나만큼의 변화는 아니다.
    """
    from app.retraining import next_version

    assert next_version("v1.1.0") == "v1.1.1"
    assert next_version("v1.1.9") == "v1.1.10"
    assert next_version(None) == "v1.1.1"


def test_validation_replaces_the_numbers_and_clears_the_stale_flag(client):
    """검증을 실행하면 그 모델 기준 수치로 바뀌고 경고가 사라진다."""
    from app.retraining import next_version
    from app.settings import AUTO_RETRAIN_MIN_LABELS

    client.post("/demo/reset")
    base = client.get("/model/info").json()
    assert base["validation_stale"] is False
    assert base["validated_at"] is None

    complete_inspections(client, AUTO_RETRAIN_MIN_LABELS)
    retrained = client.get("/model/info").json()
    assert retrained["model_version"] == next_version("v1.1.0")
    # 재학습 직후에는 옛 모델의 수치가 그대로 남고 경고가 뜬다
    assert retrained["validation_stale"] is True
    assert retrained["validation"]["records"] == base["validation"]["records"]

    response = client.post("/model/validate")
    assert response.status_code == 200
    entry = response.json()
    assert entry["version"] == next_version("v1.1.0")
    assert entry["validated"] is True

    validated = client.get("/model/info").json()
    assert validated["validation_stale"] is False
    assert validated["validated_at"]
    # 이제 수치가 이 모델의 학습 규모를 따른다
    assert validated["validation"]["records"] == 5230 + AUTO_RETRAIN_MIN_LABELS
    assert validated["threshold_metrics"] != base["threshold_metrics"]

    ratios = [row["inspect_ratio"] for row in validated["threshold_metrics"]]
    assert ratios == sorted(ratios)
    for row in validated["threshold_metrics"]:
        assert 0 <= row["recall_at_k"] <= 1
        assert 0 <= row["precision_at_k"] <= 1
        # Lift는 검출률을 검사 물량으로 나눈 값이다
        assert row["lift"] == pytest.approx(row["recall_at_k"] / row["inspect_ratio"], abs=0.02)


def test_validation_is_recorded_per_model_version(client):
    """검증 여부는 모델 행에 남고 초기화하면 함께 사라진다."""
    from app.retraining import next_version
    from app.settings import AUTO_RETRAIN_MIN_LABELS

    client.post("/demo/reset")
    complete_inspections(client, AUTO_RETRAIN_MIN_LABELS)
    client.post("/model/validate")

    registry = {row["version"]: row for row in client.get("/model/registry").json()}
    assert registry[next_version("v1.1.0")]["validated"] is True
    assert registry["v1.1.0"]["validated"] is False

    client.post("/demo/reset")
    registry = client.get("/model/registry").json()
    assert [row["version"] for row in registry] == ["v1.1.0"]
    assert registry[0]["validated"] is False


def test_inspection_queue_keeps_probability_order_across_families(client):
    """대기열 정렬은 확률 내림차순을 유지해야 한다.

    제품군이 섞이는 것은 금형 교체 후 이전 제품군의 미검사 건이 남기 때문이고,
    화면에서 제품군 필터로 해결한다. 정렬 자체를 제품군 우선으로 바꾸면
    다른 제품군의 높은 확률 건이 뒤로 밀려 운영 원칙(plan.md 7절)이 깨진다.
    """
    client.post("/demo/reset")
    # 금형이 바뀌는 지점(500번째) 이후까지 재생해 두 제품군이 함께 남게 한다
    for _ in range(25):
        client.post("/demo/next", json={"count": 20})

    queue = client.get("/inspection-queue?limit=500").json()
    waiting = [item for item in queue if item["inspection_status"] == "검사 대기"]
    assert len(waiting) > 1

    probabilities = [item["defect_probability"] for item in waiting]
    assert probabilities == sorted(probabilities, reverse=True)

    families = {item["part"][:3] for item in waiting}
    assert families == {"CN7", "RG3"}, "두 제품군이 함께 남는 상황이어야 의미가 있다"

    # 제품군으로 거르면 그 안에서도 확률 순서가 유지된다
    for family in families:
        subset = [item for item in waiting if item["part"].startswith(family)]
        assert subset
        values = [item["defect_probability"] for item in subset]
        assert values == sorted(values, reverse=True)


def test_inference_path_matches_the_code(client):
    """화면의 추론 경로가 실제 예측 경로와 어긋나면 안 된다.

    model_info.json의 pipeline은 pkl 안의 sklearn 단계 2개일 뿐이라
    보정과 관문이 화면에서 통째로 빠져 있었다. inference_path가 실제
    분기를 설명하므로, 관문이 말하는 판정 문구가 코드에 실재하는지 본다.
    """
    from pathlib import Path

    info = client.get("/model/info").json()
    path = info["inference_path"]
    assert len(path) >= 10

    # 모델 내부 단계는 pkl의 단계 수와 같아야 한다
    assert sum(1 for step in path if step.get("model")) == len(info["pipeline"])

    backend = Path(__file__).resolve().parents[1] / "app"
    sources = (backend / "prediction.py").read_text(encoding="utf-8") + (
        backend / "main.py"
    ).read_text(encoding="utf-8")
    for step in path:
        gate = step.get("gate")
        if not gate:
            continue
        # "예측 불가 (입력 오류)"처럼 괄호 설명이 붙은 경우 앞부분만 본다
        label = gate.split(" (")[0]
        assert f'"{label}"' in sources, f"{step['label']} 관문의 판정 문구가 코드에 없다: {label}"
