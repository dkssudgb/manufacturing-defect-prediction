import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parents[1]
MODEL_DIR = BACKEND_DIR / "models"
DATA_DIR = BACKEND_DIR / "data"

MODEL_PATH = MODEL_DIR / "final_rf_part_balanced.pkl"
FEATURE_COLUMNS_PATH = MODEL_DIR / "final_feature_columns.pkl"
MODEL_INFO_PATH = MODEL_DIR / "model_info.json"
THRESHOLD_METRICS_PATH = MODEL_DIR / "threshold_metrics.json"
WALKFORWARD_PATH = MODEL_DIR / "walkforward_cadence.json"
DEMO_DATA_PATH = DATA_DIR / "realtime_sample.csv"
DATABASE_PATH = (
    BACKEND_DIR / "tests" / "test_dashboard_data.db"
    if os.getenv("DASHBOARD_TEST") == "1"
    else DATA_DIR / "dashboard_data.db"
)

# 06_Final_Model.ipynb이 학습에 쓰는 원본. 재학습도 같은 파일을 기준으로 시작한다.
# 이 파일은 02_EDA가 쓰는 분석 산출물이므로 재학습이 덮어쓰지 않는다.
BASE_TRAINING_DATA_PATH = PROJECT_ROOT / "data" / "labeled_modeling.csv"
# 검사로 확보한 라벨은 별도 파일에 누적한다. 초기화하면 이 파일도 지운다.
# DB와 마찬가지로 테스트는 별도 경로를 쓴다. 같은 경로를 쓰면 pytest의 초기화가
# 개발 서버가 서빙 중인 재학습 모델 파일을 지워버린다.
_TESTING = os.getenv("DASHBOARD_TEST") == "1"
RETRAIN_LABELS_PATH = (
    BACKEND_DIR / "tests" / "test_retrain_labels.csv" if _TESTING else DATA_DIR / "retrain_labels.csv"
)
RETRAINED_MODEL_DIR = MODEL_DIR / ("retrained_test" if _TESTING else "retrained")

INITIAL_MODEL_VERSION = "v1.1.0"
# 예전 코드 호환용. 실제 서빙 버전은 model_registry의 active 행에서 읽는다.
MODEL_VERSION = INITIAL_MODEL_VERSION

# 시연 시작 시 미리 재생해둘 건수.
#
# 위험 제품은 표본 전반에 고르게 있지 않다. 첫 위험이 164번째에야 나오고
# 301~500번째는 200건 내리 0건이다. 시드가 너무 작으면 검사 대기열이 비고,
# 위험 0건 구간에 걸리면 추이 차트가 바닥에 붙은 평평한 선으로 보인다.
#
# 250에서는 대기열 10건(자동 기준 5건의 두 배), 차트가 그리는 최근 60건에
# threshold 초과 8점, 재생을 누르면 1초 뒤 다음 위험이 들어온다.
# 자동 재학습 기준(AUTO_RETRAIN_MIN_LABELS)을 올리면 이 값도 같이 본다.
DEMO_SEED_RECORDS = 250

# 자동 재학습: 마지막 재학습 이후 검사 완료가 이만큼 쌓이면 실행한다.
#
# 5건으로 잡은 근거. 07_2(ANALYSIS_RESULTS.md 7-1)는 재학습 반영 지연이
# 25분 이내 / 1시간~35시간 / 하루 세 구간으로 갈린다고 측정했고, 구간 안의
# 차이는 노이즈다. threshold 0.163에서 검사 물량이 생산의 10%이므로
# 검사 1건 = 생산 10샷이고, 생산은 분당 약 2샷이다.
#   검사  5건 = 생산  50샷 = 약 25분  -> 25분 이내 구간
#   검사 10건 = 생산 100샷 = 약 51분  -> 1시간~35시간 구간
# threshold를 바꾸면 검사 물량 비율이 달라지므로 이 환산도 다시 해야 한다.
AUTO_RETRAIN_MIN_LABELS = 5
AUTO_RETRAIN_ENABLED = True

# 검증 재측정 설정. 05_Operating_Point와 같은 검사 물량 지점을 쓴다.
# 재학습(0.53초)의 14배인 7.6초가 걸리므로 자동 재학습에 끼우지 않고
# 분석 담당자가 명시적으로 실행한다.
VALIDATION_FOLDS = 5
VALIDATION_REPEATS = 3
VALIDATION_INSPECT_RATIOS = (0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20)
# 라벨 데이터 5,230건 / 생산일 13일 = 하루 평균 402건
DAILY_PRODUCTION_BASELINE = 402

# 06_Final_Model.ipynb 셀 12와 같은 하이퍼파라미터. 재학습도 동일 구성을 쓴다.
RETRAIN_ESTIMATOR_PARAMS = {
    "n_estimators": 300,
    "max_depth": 20,
    "min_samples_split": 2,
    "min_samples_leaf": 4,
    "class_weight": "balanced",
    "n_jobs": -1,
    "random_state": 0,
}
# 학습에서 제외하는 식별 컬럼 (06_Final_Model.ipynb 셀 10과 동일)
TRAINING_DROP_COLUMNS = (
    "TimeStamp",
    "PART_FACT_PLAN_DATE",
    "PART_FACT_SERIAL",
    "PART_NAME",
    "EQUIP_CD",
)

# 05_Operating_Point에서 확정한 운영점. 0.163은 검사 물량 10%, 불량 검출률 79% 지점이다.
# 허용 범위는 검사 물량 15%(0.079) ~ 1%(0.639)에 대응한다.
DEFAULT_THRESHOLD = 0.163
MIN_THRESHOLD = 0.079
MAX_THRESHOLD = 0.639
SUPPORTED_PREFIXES = ("CN7", "RG3")
SUPPORTED_PARTS = ("CN7LH", "CN7RH", "RG3LH", "RG3RH")
# 모델이 쓰는 Part 범주는 PART_NAME의 앞 3글자 + 뒤 2글자다. 화면에는 범주 코드
# 대신 전체 품명을 보여준다. 학습 데이터와 시연 표본 모두 범주 하나당 품명이
# 정확히 하나씩이라 고정 매핑으로 둔다.
SUPPORTED_PART_NAMES = {
    "CN7LH": "CN7 W/S SIDE MLD'G LH",
    "CN7RH": "CN7 W/S SIDE MLD'G RH",
    "RG3LH": "RG3 MOLD'G W/SHLD, LH",
    "RG3RH": "RG3 MOLD'G W/SHLD, RH",
}
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
