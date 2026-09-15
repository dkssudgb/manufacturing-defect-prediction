"""Recording-defect corrections applied to every incoming process record.

These rules mirror the corrections applied in `02_EDA.ipynb`, which is the source
of truth: it writes `data/labeled_modeling.csv` and every modeling notebook reads
that file instead of re-deriving the corrections. The model was trained on data
passed through those corrections, so serving must repeat them or the model
receives values on a different scale than it was fitted on.

Column names in this dataset do not state the unit: `Average_Screw_RPM` and
`Max_Screw_RPM` are both mm/s. Physical relations between column pairs are the
only dependable check, and they are what the corrections below are based on.
"""

from typing import Any


SCREW_SPEED_SCALE_LIMIT = 100.0

BACK_PRESSURE_PAIR = ("Average_Back_Pressure", "Max_Back_Pressure")

# 이 6개는 수집 채널이 끊길 때 함께 0이 된다. 0은 물리적으로 불가능한 값이다.
SENSOR_MISSING_COLUMNS = (
    "Max_Screw_RPM",
    "Average_Screw_RPM",
    "Average_Back_Pressure",
    "Barrel_Temperature_1",
    "Mold_Temperature_3",
    "Mold_Temperature_4",
)


def detect_missing_features(row: dict[str, Any]) -> list[str]:
    """Return the sensor columns that arrived as 0, i.e. missing."""
    return [column for column in SENSOR_MISSING_COLUMNS if row.get(column) == 0]


def apply_record_corrections(row: dict[str, float]) -> tuple[dict[str, float], list[str]]:
    """Correct one record and report what was changed.

    `Average_Screw_RPM` above 100 was recorded ten times too large: the average
    then exceeds the maximum of the same quantity. Dividing by ten restores the
    `Average / Max` ratio to about 0.95.

    The back-pressure pair is stored with the average above the maximum in most
    rows, which cannot happen for one quantity. Which column holds which
    statistic is unknown, so the pair is rebuilt as {min, max}.
    """
    corrected = dict(row)
    warnings: list[str] = []

    speed = corrected.get("Average_Screw_RPM")
    if speed is not None and speed > SCREW_SPEED_SCALE_LIMIT:
        corrected["Average_Screw_RPM"] = speed / 10
        warnings.append(
            f"Average_Screw_RPM {speed:.1f} -> {speed / 10:.2f} (10배 기록 보정)"
        )

    average_column, max_column = BACK_PRESSURE_PAIR
    average_value = corrected.get(average_column)
    max_value = corrected.get(max_column)
    if average_value is not None and max_value is not None and average_value > max_value:
        corrected[average_column] = max_value
        corrected[max_column] = average_value
        warnings.append(
            f"{average_column} {average_value:.1f} > {max_column} {max_value:.1f} (쌍 재구성)"
        )

    speed = corrected.get("Average_Screw_RPM")
    max_speed = corrected.get("Max_Screw_RPM")
    if speed is not None and max_speed is not None and max_speed > 0 and speed > max_speed:
        warnings.append(
            f"보정 후에도 Average_Screw_RPM {speed:.2f} > Max_Screw_RPM {max_speed:.2f} (입력 확인 필요)"
        )

    return corrected, warnings
