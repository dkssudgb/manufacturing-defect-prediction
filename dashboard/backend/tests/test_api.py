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
    assert len(records) == 150
    assert parts.count("CN7LH") == 37
    assert parts.count("CN7RH") == 36
    assert parts.count("RG3LH") == 36
    assert parts.count("RG3RH") == 36
    assert sum(part not in {"CN7LH", "CN7RH", "RG3LH", "RG3RH"} for part in parts) == 5


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
        assert filtered_summary["received"] == len(filtered_predictions)
        assert all(item["equip_cd"] == equip_cd for item in filtered_predictions)
        assert all(item["equip_cd"] == equip_cd for item in filtered_queue)


def test_prediction_events_accumulate_and_paginate(client):
    """재생은 순환하지 않으므로 매 건이 새 제품이고, 이벤트 이력은 누적된다.

    이전에는 표본을 한 바퀴 돌면 같은 제품이 다시 들어오는 구조여서 예측 행과
    이벤트 이력을 분리해 검증했다. 재생이 표본 끝에서 멈추도록 바뀐 뒤에는
    같은 제품이 다시 들어오지 않는다.
    """
    client.post("/demo/reset")
    unique_before = len(client.get("/predictions?limit=500").json())
    events_before = client.get("/prediction-events?limit=10&offset=0").json()["total"]

    client.post("/demo/next", json={"count": 20})

    unique_after = len(client.get("/predictions?limit=500").json())
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
