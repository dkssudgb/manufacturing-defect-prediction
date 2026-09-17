"""Turn the 07_2 walk-forward results into a reference table the API can serve.

`07_2_WalkForward_common.csv` compares retraining cadences on one fixed
evaluation set (4,730 rows / 43 defects), so the rows are directly comparable.
`07_2_WalkForward_horizon.csv` supplies the wall-clock gap each cadence implies;
the cadence itself is counted in shots, not minutes, and the two are only
related through the production rate of the source period.

Lift@10% is Recall@10% divided by the 10% inspection ratio. That is the "효율"
column in REPORT.md 4.13 and ANALYSIS_RESULTS.md 7-1.
"""

import json
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parents[1]
COMMON_CSV = PROJECT_ROOT / "data" / "07_2_WalkForward_common.csv"
HORIZON_CSV = PROJECT_ROOT / "data" / "07_2_WalkForward_horizon.csv"
OUTPUT = BACKEND_DIR / "models" / "walkforward_cadence.json"

INSPECT_RATIO = 0.10


def main() -> None:
    common = pd.read_csv(COMMON_CSV)
    horizon = pd.read_csv(HORIZON_CSV)

    # 두 파일 모두 한국어 컬럼명이라 위치로 읽는다.
    # common : 비교조건, 총 수, 총 불량, AP, AP 랜덤 대비, Recall@10%, 에피소드 감지
    # horizon: 재학습 주기, 재학습 횟수, 예측 시간(분), 총 수, 총 불량, AP, ...
    minutes_by_cadence = {
        str(row.iloc[0]): (None if pd.isna(row.iloc[2]) else float(row.iloc[2]))
        for _, row in horizon.iterrows()
    }

    # ANALYSIS_RESULTS.md 7-1: 주기 사이의 미세한 차이는 노이즈이고, 의미 있는
    # 구분은 세 구간뿐이다. 특정 주기 하나를 "최적"으로 읽으면 안 된다.
    def band_of(minutes):
        if minutes is None:
            return None
        if minutes <= 25:
            return "25분 이내"
        if minutes <= 35 * 60:
            return "1시간 ~ 35시간"
        return "하루"

    rows = []
    for _, row in common.iterrows():
        label = str(row.iloc[0])
        cadence = label.replace("Walk-forward ", "").replace(" 재학습", "").strip()
        recall = float(row.iloc[5])
        rows.append(
            {
                "label": label,
                "cadence": cadence,
                "is_baseline": label.startswith("["),
                "horizon_minutes": minutes_by_cadence.get(cadence),
                "band": "하루" if cadence == "생산일" else band_of(minutes_by_cadence.get(cadence)),
                "records": int(row.iloc[1]),
                "defects": int(row.iloc[2]),
                "average_precision": round(float(row.iloc[3]), 4),
                "ap_vs_random": round(float(row.iloc[4]), 1),
                "recall_at_10": round(recall, 4),
                "lift_at_10": round(recall / INSPECT_RATIO, 1),
                "episode_detection": str(row.iloc[6]),
            }
        )

    payload = {
        "source": "07_2_WalkForward_Validation.ipynb",
        # 화면에 그대로 나가는 문구다. 다른 화면 문구와 같은 존댓말로 쓰고,
        # 시연에서 분석 문서를 함께 제출하지 않으므로 문서 참조는 넣지 않는다.
        "evaluation": (
            "제품을 생산시각 순으로 놓고, 각 구간을 그 직전까지의 데이터로만 학습한 모델로 예측. "
            "모든 행이 같은 평가 집합(4,730건 / 불량 43건) 기준이라 주기끼리 비교 가능"
        ),
        "inspect_ratio": INSPECT_RATIO,
        "note": (
            "재학습 주기는 검사 건수가 아니라 생산 샷 단위이며, 50샷이 약 25분. "
            "구간 안의 차이(AP 0.071~0.078)는 노이즈라 특정 주기 하나를 최적으로 읽으면 안 됨. "
            "의미 있는 구분은 25분 이내 / 1시간~35시간 / 하루 세 구간"
        ),
        "best_band": "25분 이내",
        "rows": rows,
    }

    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved={OUTPUT}")
    for row in rows:
        print(
            f"  {row['cadence']:>8} | horizon {str(row['horizon_minutes']):>7} min "
            f"| Recall@10% {row['recall_at_10']:.3f} | Lift {row['lift_at_10']}x"
        )


if __name__ == "__main__":
    main()
