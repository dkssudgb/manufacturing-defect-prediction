"""재학습 산출물을 Supabase Storage와 맞춘다.

배포 서버의 디스크는 재시작·재배포 때 비워진다. DB(model_registry)는 남는데
모델 파일이 사라지면 기동 시 초기 모델로 되돌아가며 재학습 이력이 지워진다.
그래서 재학습 모델(`models/retrained/*.pkl`)과 누적 라벨(`retrain_labels.csv`)을
비공개 버킷에 올려두고 기동할 때 내려받는다.

객체 키는 모델은 `model_registry.model_file`(MODEL_DIR 기준 상대 경로) 그대로,
라벨은 `retrain_labels.csv`다. SUPABASE_URL·SUPABASE_SECRET_KEY가 없으면
(로컬 개발, 테스트) 모든 함수가 아무 일도 하지 않는다.
"""

from pathlib import Path

import httpx

from .settings import (
    ARTIFACT_BUCKET,
    MODEL_DIR,
    RETRAIN_LABELS_PATH,
    RETRAINED_MODEL_DIR,
    SUPABASE_SECRET_KEY,
    SUPABASE_URL,
)

LABELS_KEY = "retrain_labels.csv"
_TIMEOUT = httpx.Timeout(60.0)


def enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SECRET_KEY)


def _headers() -> dict[str, str]:
    headers = {"apikey": SUPABASE_SECRET_KEY}
    # 예전 service_role 키는 JWT라 Authorization에도 싣는다. 새 sb_secret_ 키는
    # apikey 헤더만 보낸다.
    if SUPABASE_SECRET_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SUPABASE_SECRET_KEY}"
    return headers


def _url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/{path}"


def ensure_bucket() -> None:
    if not enabled():
        return
    response = httpx.post(
        _url("bucket"),
        headers=_headers(),
        json={"id": ARTIFACT_BUCKET, "name": ARTIFACT_BUCKET, "public": False},
        timeout=_TIMEOUT,
    )
    # 이미 있으면 400/409가 온다
    if response.status_code not in (200, 400, 409):
        response.raise_for_status()


def _list(prefix: str) -> list[str]:
    response = httpx.post(
        _url(f"object/list/{ARTIFACT_BUCKET}"),
        headers=_headers(),
        json={"prefix": prefix, "limit": 1000, "offset": 0},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    # 폴더 항목은 id가 없다
    return [item["name"] for item in response.json() if item.get("id")]


def _download(key: str, destination: Path) -> bool:
    response = httpx.get(
        _url(f"object/{ARTIFACT_BUCKET}/{key}"), headers=_headers(), timeout=_TIMEOUT
    )
    if response.status_code in (400, 404):
        return False
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(response.content)
    return True


def upload(local_path: Path, key: str) -> None:
    if not enabled():
        return
    response = httpx.post(
        _url(f"object/{ARTIFACT_BUCKET}/{key}"),
        headers={**_headers(), "x-upsert": "true", "Content-Type": "application/octet-stream"},
        content=local_path.read_bytes(),
        timeout=_TIMEOUT,
    )
    response.raise_for_status()


def upload_model(model_file: str) -> None:
    upload(MODEL_DIR / model_file, model_file)


def upload_labels() -> None:
    upload(RETRAIN_LABELS_PATH, LABELS_KEY)


def restore() -> None:
    """버킷의 산출물을 로컬로 내려받는다. 네트워크 오류는 그대로 올린다.

    조용히 넘기면 기동 루틴이 모델 파일이 없다고 보고 재학습 이력을 지운다.
    기동을 실패시키는 편이 데이터를 잃는 것보다 낫다.
    """
    if not enabled():
        return
    ensure_bucket()
    prefix = RETRAINED_MODEL_DIR.relative_to(MODEL_DIR).as_posix()
    for name in _list(prefix):
        destination = RETRAINED_MODEL_DIR / name
        if not destination.exists():
            _download(f"{prefix}/{name}", destination)
    if not RETRAIN_LABELS_PATH.exists():
        _download(LABELS_KEY, RETRAIN_LABELS_PATH)


def clear() -> None:
    """초기화 시 버킷의 산출물을 모두 지운다."""
    if not enabled():
        return
    prefix = RETRAINED_MODEL_DIR.relative_to(MODEL_DIR).as_posix()
    keys = [f"{prefix}/{name}" for name in _list(prefix)] + [LABELS_KEY]
    response = httpx.request(
        "DELETE",
        _url(f"object/{ARTIFACT_BUCKET}"),
        headers=_headers(),
        json={"prefixes": keys},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
