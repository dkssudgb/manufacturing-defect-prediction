import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = BACKEND_DIR / "models"
DATA_DIR = BACKEND_DIR / "data"

MODEL_PATH = MODEL_DIR / "final_rf_part_balanced.pkl"
FEATURE_COLUMNS_PATH = MODEL_DIR / "final_feature_columns.pkl"
MODEL_INFO_PATH = MODEL_DIR / "model_info.json"
THRESHOLD_METRICS_PATH = MODEL_DIR / "threshold_metrics.json"
DEMO_DATA_PATH = DATA_DIR / "realtime_sample.csv"
DATABASE_PATH = (
    BACKEND_DIR / "tests" / "test_dashboard_data.db"
    if os.getenv("DASHBOARD_TEST") == "1"
    else DATA_DIR / "dashboard_data.db"
)

MODEL_VERSION = "v1.1.0"

# 05_Operating_Point에서 확정한 운영점. 0.163은 검사 물량 10%, 불량 검출률 79% 지점이다.
# 허용 범위는 검사 물량 15%(0.079) ~ 1%(0.639)에 대응한다.
DEFAULT_THRESHOLD = 0.163
MIN_THRESHOLD = 0.079
MAX_THRESHOLD = 0.639
SUPPORTED_PREFIXES = ("CN7", "RG3")
SUPPORTED_PARTS = ("CN7LH", "CN7RH", "RG3LH", "RG3RH")
# 화면에 이름을 보여줄 설비 목록. 지원 여부와 무관하게 표시한다.
KNOWN_EQUIPMENT = {
    "S06": "550TON-도시바",
    "S14": "650톤-우진2호기",
}

# 모델이 학습하고 지원하는 설비는 650톤-우진2호기 한 대뿐이다.
# labeled 데이터 5,230건이 전부 S14이며, 도시바(S06)는 같은 품목을 만들지만
# 2020-03-17 ~ 07-21 기간에만 생산해 학습에 포함되지 않았다.
# 학습하지 않은 설비의 예측은 설비 외삽이므로 지원 대상에서 제외한다.
SUPPORTED_EQUIPMENT = {"S14": KNOWN_EQUIPMENT["S14"]}
TRAINED_EQUIPMENT = tuple(SUPPORTED_EQUIPMENT)
