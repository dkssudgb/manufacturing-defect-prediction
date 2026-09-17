"""Data corrections shared by the modeling notebooks and the prediction server.

The raw KAMP molding data has two recording defects that must be repaired the
same way in training and in serving, otherwise the model receives values on a
different scale than it was fitted on.

Column names in this dataset do not reliably state the unit: `Average_Screw_RPM`
and `Max_Screw_RPM` are both mm/s, not RPM. Physical relations between column
pairs are therefore the only dependable check.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


SCREW_SPEED_SCALE_LIMIT = 100.0

BACK_PRESSURE_PAIR = ("Average_Back_Pressure", "Max_Back_Pressure")

DROPPED_COLUMNS = ["Clamp_Open_Position"]


def correct_screw_speed(df: pd.DataFrame) -> pd.DataFrame:
    """Undo the ten-fold recording of `Average_Screw_RPM`.

    2020-10-16 ~ 10-27 in the labeled data and the whole unlabeled set store this
    column ten times too large: `Average / Max` sits at 9.48 instead of 0.95, so
    the average exceeds the maximum of the same quantity. Dividing values above
    100 restores the ratio to 0.95 and removes every violation.
    """
    df = df.copy()
    column = "Average_Screw_RPM"
    if column in df.columns:
        df[column] = np.where(df[column] > SCREW_SPEED_SCALE_LIMIT,
                              df[column] / 10, df[column])
    return df


def correct_back_pressure(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the back-pressure pair so the average never exceeds the maximum.

    `Average_Back_Pressure` is larger than `Max_Back_Pressure` in 99.7% of the
    labeled rows and 41.8% of the CN7/RG3 unlabeled rows, which cannot happen for the
    average and maximum of one quantity. Which column holds which statistic is
    unknown, so only the weaker assumption is used: the pair is {average,
    maximum} in some order. Taking the row-wise minimum and maximum makes every
    row consistent without discarding either measurement.
    """
    df = df.copy()
    average_column, max_column = BACK_PRESSURE_PAIR
    if average_column in df.columns and max_column in df.columns:
        pair = df[[average_column, max_column]].to_numpy()
        df[average_column] = pair.min(axis=1)
        df[max_column] = pair.max(axis=1)
    return df


def drop_uninformative_columns(df: pd.DataFrame, columns: Sequence[str] = DROPPED_COLUMNS) -> pd.DataFrame:
    """Drop columns that carry no information beyond `Part`.

    `Clamp_Open_Position` takes three values in the labeled data (CN7 648.0,
    RG3 4.63, and 18 rows at 69.6) and is therefore determined by `Part`. In the
    CN7/RG3 unlabeled data 76.3% of the values fall outside the trained range, so keeping
    it only feeds unseen values to the model.
    """
    return df.drop(columns=[c for c in columns if c in df.columns])


def apply_data_corrections(df: pd.DataFrame, *, drop_columns: bool = True) -> pd.DataFrame:
    """Apply every correction in the order training and serving both use."""
    df = correct_screw_speed(df)
    df = correct_back_pressure(df)
    if drop_columns:
        df = drop_uninformative_columns(df)
    return df


def check_data_corrections(df: pd.DataFrame) -> dict[str, Any]:
    """Report the physical-relation violations left in a frame.

    Returned counts should all be zero after `apply_data_corrections`. Use this
    on incoming serving data to decide whether a row is trustworthy.
    """
    report: dict[str, Any] = {"rows": int(len(df))}

    if {"Average_Screw_RPM", "Max_Screw_RPM"} <= set(df.columns):
        report["screw_speed_violations"] = int((df["Average_Screw_RPM"] > df["Max_Screw_RPM"]).sum())
        report["screw_speed_above_limit"] = int((df["Average_Screw_RPM"] > SCREW_SPEED_SCALE_LIMIT).sum())

    average_column, max_column = BACK_PRESSURE_PAIR
    if {average_column, max_column} <= set(df.columns):
        report["back_pressure_violations"] = int((df[average_column] > df[max_column]).sum())

    missing_block = ["Max_Screw_RPM", "Average_Screw_RPM", "Average_Back_Pressure",
                     "Barrel_Temperature_1", "Mold_Temperature_3", "Mold_Temperature_4"]
    present = [c for c in missing_block if c in df.columns]
    if present:
        report["sensor_missing_rows"] = int((df[present] == 0).any(axis=1).sum())

    return report
