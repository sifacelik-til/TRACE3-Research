"""Test whether CDP action clusters improve three-year Scope 3 forecasts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def model():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=1.0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", required=True, type=Path)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--company-column", default="company")
    parser.add_argument("--year-column", default="year")
    parser.add_argument("--scope3-column", default="upstream_scope3_intensity")
    parser.add_argument(
        "--action-column", choices=("action_cluster_ids", "industry_action_cluster_ids"),
        default="industry_action_cluster_ids",
    )
    parser.add_argument("--state-columns", nargs="+", required=True)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--minimum-train-years", type=int, default=3)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    actions = pd.read_csv(args.actions)
    required = {args.company_column, args.year_column, args.scope3_column, *args.state_columns}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"Panel is missing columns: {sorted(missing)}")
    actions = actions[actions.goal.eq("reduction")].copy()
    actions[args.action_column] = actions[args.action_column].map(json.loads)
    exploded = actions.explode(args.action_column)
    action_matrix = pd.crosstab(
        [exploded.company, exploded.year], exploded[args.action_column]
    ).clip(upper=1).add_prefix("action__").reset_index()
    frame = panel.merge(
        action_matrix, how="left",
        left_on=[args.company_column, args.year_column], right_on=["company", "year"],
    )
    action_columns = [column for column in frame if column.startswith("action__")]
    frame[action_columns] = frame[action_columns].fillna(0)
    future = frame[[args.company_column, args.year_column, args.scope3_column]].copy()
    future[args.year_column] -= args.horizon
    future = future.rename(columns={args.scope3_column: "future_scope3"})
    frame = frame.merge(future, on=[args.company_column, args.year_column], how="inner")
    frame = frame[(frame[args.scope3_column] > 0) & (frame.future_scope3 > 0)].copy()
    frame["target"] = np.log(frame[args.scope3_column] / frame.future_scope3)
    years = sorted(frame[args.year_column].unique())
    results = []
    for test_year in years[args.minimum_train_years:]:
        train, test = frame[frame[args.year_column] < test_year], frame[frame[args.year_column] == test_year]
        if train.empty or test.empty:
            continue
        row = {"test_year": int(test_year), "train_n": len(train), "test_n": len(test)}
        for name, columns in (("state_only", args.state_columns),
                              ("state_plus_actions", args.state_columns + action_columns)):
            fitted = model().fit(train[columns], train.target)
            prediction = fitted.predict(test[columns])
            row.update({
                f"{name}_rmse": float(mean_squared_error(test.target, prediction) ** 0.5),
                f"{name}_mae": float(mean_absolute_error(test.target, prediction)),
                f"{name}_r2": float(r2_score(test.target, prediction)),
            })
        row["rmse_improvement"] = row["state_only_rmse"] - row["state_plus_actions_rmse"]
        row["mae_improvement"] = row["state_only_mae"] - row["state_plus_actions_mae"]
        results.append(row)
    output = pd.DataFrame(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(output.to_string(index=False))


if __name__ == "__main__":
    main()
