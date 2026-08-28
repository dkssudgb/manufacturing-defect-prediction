"""Cross-validation helpers for imbalanced Random Forest experiments."""

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.preprocessing import StandardScaler


METRIC_COLUMNS = ["Average Precision", "Defect Precision", "Defect Recall", "Defect F1", "Accuracy"]


def build_random_forest_smote_pipeline(
    rf_params: Mapping[str, Any],
    *,
    sampling_strategy: float = 0.1,
    smote_k_neighbors: int = 3,
    random_state: int = 0,
    rf_n_jobs: int = -1,
) -> Pipeline:
    """Build a scaler-SMOTE-RandomForest pipeline for fold-safe evaluation."""
    params = dict(rf_params)
    params.setdefault("random_state", random_state)
    params.setdefault("n_jobs", rf_n_jobs)
    return Pipeline(
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
            ("rf", RandomForestClassifier(**params)),
        ]
    )


def _take_rows(data: Any, indices: np.ndarray) -> Any:
    return data.iloc[indices] if hasattr(data, "iloc") else data[indices]


def _score_estimator(estimator: Any, x_test: Any, y_test: Any) -> dict[str, float]:
    predictions = estimator.predict(x_test)
    probabilities = estimator.predict_proba(x_test)
    classes = list(estimator.classes_)
    positive_probabilities = probabilities[:, classes.index(1)]
    return {
        "Average Precision": average_precision_score(y_test, positive_probabilities),
        "Defect Precision": precision_score(y_test, predictions, pos_label=1, zero_division=0),
        "Defect Recall": recall_score(y_test, predictions, pos_label=1, zero_division=0),
        "Defect F1": f1_score(y_test, predictions, pos_label=1, zero_division=0),
        "Accuracy": accuracy_score(y_test, predictions),
    }


def _summarize_fold_results(fold_results: pd.DataFrame) -> pd.DataFrame:
    summary = fold_results.groupby("Model")[METRIC_COLUMNS].agg(["mean", "std"])
    summary.columns = [f"{metric} {stat}" for metric, stat in summary.columns]
    return summary.reset_index()


def evaluate_fixed_models_stratified(
    model_data: Mapping[str, Any],
    model_params: Mapping[str, Mapping[str, Any]],
    y: Any,
    cv_splits: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    sampling_strategy: float = 0.1,
    smote_k_neighbors: int = 3,
    random_state: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate fixed model candidates on the same precomputed stratified folds."""
    if set(model_data) != set(model_params):
        raise ValueError("model_data and model_params must have identical model names.")

    rows = []
    for model_name, x in model_data.items():
        if len(x) != len(y):
            raise ValueError(f"{model_name!r} has a different row count from y.")
        for fold, (train_idx, test_idx) in enumerate(cv_splits, start=1):
            estimator = build_random_forest_smote_pipeline(
                model_params[model_name],
                sampling_strategy=sampling_strategy,
                smote_k_neighbors=smote_k_neighbors,
                random_state=random_state,
            )
            x_train = _take_rows(x, train_idx)
            x_test = _take_rows(x, test_idx)
            y_train = _take_rows(y, train_idx)
            y_test = _take_rows(y, test_idx)
            estimator.fit(x_train, y_train)
            rows.append(
                {"Model": model_name, "Fold": fold, **_score_estimator(estimator, x_test, y_test)}
            )
            print(f"{model_name} - fold {fold}/{len(cv_splits)} complete")

    fold_results = pd.DataFrame(rows)
    return fold_results, _summarize_fold_results(fold_results)


def nested_grid_search_random_forest_smote(
    model_name: str,
    x: Any,
    y: Any,
    param_grid: Mapping[str, Sequence[Any]],
    outer_splits: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    inner_n_splits: int = 3,
    sampling_strategy: float = 0.1,
    smote_k_neighbors: int = 3,
    random_state: int = 0,
    n_jobs: int = -1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run inner GridSearchCV and evaluate its winner on every outer fold."""
    pipeline_param_grid = {
        key if key.startswith("rf__") else f"rf__{key}": values
        for key, values in param_grid.items()
    }
    rows = []

    for fold, (train_idx, test_idx) in enumerate(outer_splits, start=1):
        x_train = _take_rows(x, train_idx)
        x_test = _take_rows(x, test_idx)
        y_train = _take_rows(y, train_idx)
        y_test = _take_rows(y, test_idx)
        estimator = build_random_forest_smote_pipeline(
            {},
            sampling_strategy=sampling_strategy,
            smote_k_neighbors=smote_k_neighbors,
            random_state=random_state,
            rf_n_jobs=1,
        )
        inner_cv = StratifiedKFold(
            n_splits=inner_n_splits,
            shuffle=True,
            random_state=random_state + fold,
        )
        grid_search = GridSearchCV(
            estimator=estimator,
            param_grid=pipeline_param_grid,
            scoring="average_precision",
            cv=inner_cv,
            n_jobs=n_jobs,
            refit=True,
            verbose=0,
            error_score="raise",
        )
        grid_search.fit(x_train, y_train)
        rows.append(
            {
                "Model": model_name,
                "Fold": fold,
                "Inner Best AP": grid_search.best_score_,
                "Best Parameters": grid_search.best_params_,
                **_score_estimator(grid_search.best_estimator_, x_test, y_test),
            }
        )
        print(
            f"{model_name} - outer fold {fold}/{len(outer_splits)} complete "
            f"(inner best AP={grid_search.best_score_:.4f})"
        )

    fold_results = pd.DataFrame(rows)
    return fold_results, _summarize_fold_results(fold_results)
