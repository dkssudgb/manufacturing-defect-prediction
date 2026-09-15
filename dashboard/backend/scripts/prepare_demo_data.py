"""Create a 150-record, model-focused replay sample from the original data.

The sample contains 145 model-supported records balanced across the four
trained Part categories and five unsupported records. Rows are selected across
the source timeline without using prediction scores, then replayed in timestamp
order. At least one same-timestamp LH/RH pair per product family is retained
when the source contains one.
"""

from pathlib import Path

import pandas as pd
import joblib
import numpy as np


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parents[1]
SOURCE = PROJECT_ROOT / "data" / "unlabeled_data.csv"
OUTPUT = BACKEND_DIR / "data" / "realtime_sample.csv"
FEATURE_COLUMNS = BACKEND_DIR / "models" / "final_feature_columns.pkl"

# 05/11절에서 확정한 재생 구간. 이 구간은 센서 결측이 0%이고 전량이 학습된 품명이다.
DEMO_START = "2020-10-18"
DEMO_END = "2020-10-22"

# 수집 채널이 끊기면 함께 0이 되는 변수들. 이 행은 예측할 수 없으므로 시연 표본에서 제외한다.
SENSOR_MISSING_COLUMNS = (
    "Max_Screw_RPM",
    "Average_Screw_RPM",
    "Average_Back_Pressure",
    "Barrel_Temperature_1",
    "Mold_Temperature_3",
    "Mold_Temperature_4",
)
TARGET_COUNTS = {"CN7LH": 37, "CN7RH": 36, "RG3LH": 36, "RG3RH": 36}
UNSUPPORTED_COUNT = 5


def evenly_spaced(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    if len(frame) < count:
        raise ValueError(f"요청한 {count}건보다 선택 가능한 데이터가 적습니다: {len(frame)}")
    positions = np.linspace(0, len(frame) - 1, num=count, dtype=int)
    return frame.iloc[positions]


def same_timestamp_pair(frame: pd.DataFrame, left: str, right: str) -> pd.DataFrame:
    family = frame[frame["Part"].isin((left, right))]
    counts = family.groupby("TimeStamp")["Part"].nunique()
    candidates = counts[counts >= 2]
    if candidates.empty:
        return frame.iloc[0:0]
    timestamp = candidates.index[len(candidates) // 2]
    pair = family[family["TimeStamp"] == timestamp].drop_duplicates("Part")
    return pair[pair["Part"].isin((left, right))].head(2)


def main() -> None:
    frame = pd.read_csv(SOURCE, low_memory=False)
    frame["Part"] = frame["PART_NAME"].astype(str).str[:3] + frame["PART_NAME"].astype(str).str[-2:]

    # 확정한 재생 구간으로 제한
    produced_on = pd.to_datetime(frame["TimeStamp"], errors="coerce").dt.date
    window = (produced_on >= pd.Timestamp(DEMO_START).date()) & (produced_on <= pd.Timestamp(DEMO_END).date())
    frame = frame[window].copy()

    # 센서 결측 행 제외
    missing_present = [column for column in SENSOR_MISSING_COLUMNS if column in frame.columns]
    if missing_present:
        frame = frame[~(frame[missing_present] == 0).any(axis=1)].copy()

    feature_columns = joblib.load(FEATURE_COLUMNS)
    numeric_features = [column for column in feature_columns if not column.startswith("Part_")]
    numeric = frame[numeric_features].apply(pd.to_numeric, errors="coerce")
    valid_input = numeric.notna().all(axis=1)
    supported = frame[frame["Part"].isin(TARGET_COUNTS) & valid_input].copy()

    required = pd.concat(
        [
            same_timestamp_pair(supported, "CN7LH", "CN7RH"),
            same_timestamp_pair(supported, "RG3LH", "RG3RH"),
        ]
    ).drop_duplicates("_id")

    supported_rows = []
    for part, target_count in TARGET_COUNTS.items():
        required_part = required[required["Part"] == part]
        candidates = supported[
            (supported["Part"] == part) & ~supported["_id"].isin(required_part["_id"])
        ]
        remaining = target_count - len(required_part)
        supported_rows.append(pd.concat([required_part, evenly_spaced(candidates, remaining)]))

    unsupported = frame[
        ~frame["PART_NAME"].astype(str).str.startswith(("CN7", "RG3"), na=False)
    ]
    unsupported_rows = evenly_spaced(unsupported, UNSUPPORTED_COUNT)

    selected = pd.concat([*supported_rows, unsupported_rows], ignore_index=True)
    selected["_sort_time"] = pd.to_datetime(selected["TimeStamp"], errors="coerce")
    selected = selected.sort_values(["_sort_time", "_id"], kind="stable")
    selected = selected.drop(columns=["Part", "_sort_time"])
    selected.to_csv(OUTPUT, index=False, encoding="utf-8")

    parts = selected["PART_NAME"].astype(str).str[:3] + selected["PART_NAME"].astype(str).str[-2:]
    supported_count = int(parts.isin(TARGET_COUNTS).sum())
    print(f"saved={OUTPUT}")
    print(f"records={len(selected)} supported={supported_count} unsupported={len(selected) - supported_count}")
    print(parts.value_counts().to_string())


if __name__ == "__main__":
    main()
