"""Model evaluation and feature-importance helpers for notebook experiments."""

from collections.abc import Mapping, Sequence
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    precision_recall_curve,
)


RESULT_COLUMNS = [
    "Model",
    "Defect Precision",
    "Defect Recall",
    "Defect F1 Score",
    "Average Precision",
]


def evaluate_models(
    model_dict: Mapping[str, Any],
    x_test: Any,
    y_test: Any,
    result_df: pd.DataFrame,
    *,
    target_names: Sequence[str] = ("양품", "불량"),
    negative_label: Any = 0,
    positive_label: Any = 1,
) -> pd.DataFrame:
    """Evaluate fitted classifiers and append one result row per model.

    The keys in ``model_dict`` are used unchanged in the ``Model`` column, so
    each experiment's complete display name should be assigned when the model
    is stored in the dictionary.
    """
    if not model_dict:
        raise ValueError("model_dict is empty.")
    if len(target_names) != 2:
        raise ValueError("target_names must contain exactly two class names.")

    result_rows = []
    plt.figure()

    for model_name, estimator in model_dict.items():
        if not hasattr(estimator, "predict_proba"):
            raise TypeError(f"{model_name!r} does not support predict_proba().")

        predictions = estimator.predict(x_test)
        probabilities = estimator.predict_proba(x_test)
        classes = list(estimator.classes_)
        if positive_label not in classes:
            raise ValueError(
                f"positive_label={positive_label!r} is not in {model_name!r}.classes_."
            )

        positive_probabilities = probabilities[:, classes.index(positive_label)]
        accuracy = estimator.score(x_test, y_test)
        ap_score = average_precision_score(
            y_test, positive_probabilities, pos_label=positive_label
        )
        precision, recall, _ = precision_recall_curve(
            y_test, positive_probabilities, pos_label=positive_label
        )

        print("=" * 80)
        print(model_name)
        print("=" * 80)
        print(f"Accuracy: {accuracy}")
        print(f"Average Precision: {ap_score}")
        print("Classification Report")
        print(
            classification_report(
                y_test,
                predictions,
                labels=[negative_label, positive_label],
                target_names=list(target_names),
                zero_division=0,
            )
        )
        plt.plot(recall, precision, label=f"{model_name} AP= {ap_score:.2f}")

        report = classification_report(
            y_test,
            predictions,
            labels=[negative_label, positive_label],
            target_names=list(target_names),
            output_dict=True,
            zero_division=0,
        )
        defect_report = report[target_names[1]]
        result_rows.append(
            {
                "Model": model_name,
                "Defect Precision": defect_report["precision"],
                "Defect Recall": defect_report["recall"],
                "Defect F1 Score": defect_report["f1-score"],
                "Average Precision": ap_score,
            }
        )

    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title("Precision-Recall Curve")
    plt.legend(loc="lower left")
    plt.show()

    new_results = pd.DataFrame(result_rows, columns=RESULT_COLUMNS)
    return pd.concat([result_df, new_results], ignore_index=True)


def show_random_forest_feature_importance(
    model_dict: Mapping[str, Any],
    feature_names: Sequence[str],
    *,
    figsize: tuple[int, int] = (6, 10),
) -> dict[str, pd.DataFrame]:
    """Display feature-importance tables and plots for Random Forest models only."""
    feature_names = list(feature_names)
    importance_tables: dict[str, pd.DataFrame] = {}

    for model_name, estimator in model_dict.items():
        if not isinstance(estimator, RandomForestClassifier):
            continue
        if len(feature_names) != len(estimator.feature_importances_):
            raise ValueError(
                f"{model_name!r} has {len(estimator.feature_importances_)} importances, "
                f"but {len(feature_names)} feature names were provided."
            )

        importance_df = pd.DataFrame(
            {
                "Feature": feature_names,
                "Importance": estimator.feature_importances_,
            }
        ).sort_values("Importance", ascending=False, ignore_index=True)
        importance_tables[model_name] = importance_df

        print(f"{model_name} - Random Forest Feature Importance")
        try:
            from IPython.display import display

            display(importance_df)
        except ImportError:
            print(importance_df.to_string(index=False))

        plot_df = importance_df.sort_values("Importance")
        plt.figure(figsize=figsize)
        plt.barh(plot_df["Feature"], plot_df["Importance"])
        plt.xlabel("Importance")
        plt.title(f"Random Forest Feature Importance\n{model_name}")
        plt.tight_layout()
        plt.show()

    if not importance_tables:
        print("No Random Forest model found in model_dict.")

    return importance_tables
