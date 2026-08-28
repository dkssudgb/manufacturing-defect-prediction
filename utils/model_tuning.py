"""Leakage-safe hyperparameter tuning helpers for notebook experiments."""

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline
from sklearn.ensemble import BaggingClassifier, RandomForestClassifier
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.preprocessing import StandardScaler


def grid_search_random_forest_smote(
    x_train: Any,
    y_train: Any,
    *,
    param_grid: Mapping[str, Sequence[Any]],
    sampling_strategy: float = 0.1,
    smote_k_neighbors: int = 3,
    n_splits: int = 5,
    scoring: str = "average_precision",
    random_state: int = 0,
    n_jobs: int = -1,
    verbose: int = 1,
) -> tuple[GridSearchCV, pd.DataFrame]:
    """Tune a Random Forest while applying scaling and SMOTE inside each CV fold.

    Parameter names may be provided as regular Random Forest names such as
    ``n_estimators``. They are prefixed with ``rf__`` for the pipeline.
    """
    class_counts = pd.Series(y_train).value_counts()
    if len(class_counts) != 2:
        raise ValueError("y_train must contain exactly two classes.")
    if class_counts.min() < n_splits:
        raise ValueError(
            f"The minority class has {class_counts.min()} rows, fewer than "
            f"n_splits={n_splits}."
        )

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "smote",
                SMOTE(
                    sampling_strategy=sampling_strategy,
                    k_neighbors=smote_k_neighbors,
                    random_state=random_state,
                ),
            ),
            (
                "rf",
                RandomForestClassifier(random_state=random_state, n_jobs=1),
            ),
        ]
    )
    pipeline_param_grid = {
        key if key.startswith("rf__") else f"rf__{key}": values
        for key, values in param_grid.items()
    }
    cv = StratifiedKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )
    grid_search = GridSearchCV(
        estimator=pipeline,
        param_grid=pipeline_param_grid,
        scoring=scoring,
        cv=cv,
        n_jobs=n_jobs,
        refit=True,
        verbose=verbose,
        return_train_score=False,
        error_score="raise",
    )
    grid_search.fit(x_train, y_train)

    cv_results = (
        pd.DataFrame(grid_search.cv_results_)[
            [
                "rank_test_score",
                "mean_test_score",
                "std_test_score",
                "mean_fit_time",
                "params",
            ]
        ]
        .sort_values("rank_test_score")
        .reset_index(drop=True)
    )
    return grid_search, cv_results


def grid_search_random_forest_balanced(
    x_train: Any,
    y_train: Any,
    *,
    param_grid: Mapping[str, Sequence[Any]],
    n_splits: int = 5,
    scoring: str = "average_precision",
    random_state: int = 0,
    n_jobs: int = -1,
    verbose: int = 1,
) -> tuple[GridSearchCV, pd.DataFrame]:
    """Tune a class-weighted Random Forest inside stratified CV folds."""
    class_counts = pd.Series(y_train).value_counts()
    if len(class_counts) != 2:
        raise ValueError("y_train must contain exactly two classes.")
    if class_counts.min() < n_splits:
        raise ValueError(
            f"The minority class has {class_counts.min()} rows, fewer than "
            f"n_splits={n_splits}."
        )

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "rf",
                RandomForestClassifier(
                    class_weight="balanced",
                    random_state=random_state,
                    n_jobs=1,
                ),
            ),
        ]
    )
    pipeline_param_grid = {
        key if key.startswith("rf__") else f"rf__{key}": values
        for key, values in param_grid.items()
    }
    cv = StratifiedKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )
    grid_search = GridSearchCV(
        estimator=pipeline,
        param_grid=pipeline_param_grid,
        scoring=scoring,
        cv=cv,
        n_jobs=n_jobs,
        refit=True,
        verbose=verbose,
        return_train_score=False,
        error_score="raise",
    )
    grid_search.fit(x_train, y_train)

    cv_results = (
        pd.DataFrame(grid_search.cv_results_)[
            [
                "rank_test_score",
                "mean_test_score",
                "std_test_score",
                "mean_fit_time",
                "params",
            ]
        ]
        .sort_values("rank_test_score")
        .reset_index(drop=True)
    )
    return grid_search, cv_results


def grid_search_bagging_smote(
    x_train: Any,
    y_train: Any,
    *,
    param_grid: Mapping[str, Sequence[Any]],
    sampling_strategy: float = 0.1,
    smote_k_neighbors: int = 3,
    n_splits: int = 5,
    scoring: str = "average_precision",
    random_state: int = 0,
    n_jobs: int = -1,
    verbose: int = 1,
) -> tuple[GridSearchCV, pd.DataFrame]:
    """Tune Bagging while applying scaling and SMOTE inside each CV fold."""
    class_counts = pd.Series(y_train).value_counts()
    if len(class_counts) != 2:
        raise ValueError("y_train must contain exactly two classes.")
    if class_counts.min() < n_splits:
        raise ValueError(
            f"The minority class has {class_counts.min()} rows, fewer than "
            f"n_splits={n_splits}."
        )

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "smote",
                SMOTE(
                    sampling_strategy=sampling_strategy,
                    k_neighbors=smote_k_neighbors,
                    random_state=random_state,
                ),
            ),
            (
                "bagging",
                BaggingClassifier(random_state=random_state, n_jobs=1),
            ),
        ]
    )
    pipeline_param_grid = {
        key if key.startswith("bagging__") else f"bagging__{key}": values
        for key, values in param_grid.items()
    }
    cv = StratifiedKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )
    grid_search = GridSearchCV(
        estimator=pipeline,
        param_grid=pipeline_param_grid,
        scoring=scoring,
        cv=cv,
        n_jobs=n_jobs,
        refit=True,
        verbose=verbose,
        return_train_score=False,
        error_score="raise",
    )
    grid_search.fit(x_train, y_train)

    cv_results = (
        pd.DataFrame(grid_search.cv_results_)[
            [
                "rank_test_score",
                "mean_test_score",
                "std_test_score",
                "mean_fit_time",
                "params",
            ]
        ]
        .sort_values("rank_test_score")
        .reset_index(drop=True)
    )
    return grid_search, cv_results
