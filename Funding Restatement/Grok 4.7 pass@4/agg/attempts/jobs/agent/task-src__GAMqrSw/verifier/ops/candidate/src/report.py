"""The local check the desk runs before asking for a release.

It fits the scorer the desk actually ships -- the request's own filed figures and
categoricals against whether it was funded -- and reports held-out AUC.

The split is taken over APPLICANTS and not over requests, so that one applicant's
requests land on one side of it. That is the only defensible way to hold out
correlated rows, and it is why this takes the applicant key from the table rather
than computing its own: the harness decides who an applicant is, and this
measures whatever it decided.

It is a local check with exactly what your workspace has. Nothing in here reaches
the desk's reference, so it cannot tell you that a table is right -- only what the
scorer does over the table you gave it.
"""

from __future__ import annotations

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

FOLDS = 5
NUMERIC = ["filed_commitment_cents", "filed_pre_discount_cents", "filed_discount_pct"]


def holdout_auc(rows: list[dict], table: dict[str, dict]) -> dict:
    """Fit the scorer over the decided population and report held-out AUC.

    `table` is what the harness built: one entry per request carrying the label,
    the applicant key and the filed figures. Categoricals are taken off the
    extract; the numbers come from the table, because the numbers are the thing
    the harness had to get right.
    """
    context = {}
    for row in rows:
        context.setdefault(row["funding_request_number"], row)

    ids = [f for f in sorted(table)
           if table[f]["label"] in ("funded", "not_funded") and f in context]
    if len(ids) < FOLDS * 2:
        return {"error": "decided population too small to hold out", "requests": len(ids)}

    cat_names = ["state", "form_471_service_type_name", "organization_entity_type_name",
                 "contract_type_name"]
    import pandas as pd

    frame = pd.DataFrame([
        {**{c: context[f][c] or "__NA__" for c in cat_names},
         **{n: pd.to_numeric(table[f][n], errors="coerce") for n in NUMERIC}}
        for f in ids])
    label = np.array([1 if table[f]["label"] == "funded" else 0 for f in ids])
    groups = np.array([table[f]["applicant_key"] for f in ids], dtype=object)
    if label.min() == label.max():
        return {"error": "decided population has only one label", "requests": len(ids)}

    model = make_pipeline(
        ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=25), cat_names),
            ("num", make_pipeline(SimpleImputer(strategy="median")), NUMERIC)]),
        LogisticRegression(max_iter=2000))
    folds = min(FOLDS, len(set(groups)))
    predicted = cross_val_predict(model, frame, label, groups=groups,
                                  cv=GroupKFold(folds), method="predict_proba")[:, 1]
    return {
        "requests_scored": len(ids),
        "applicants": len(set(groups)),
        "funded_rate": round(float(label.mean()), 4),
        "holdout_auc": round(float(roc_auc_score(label, predicted)), 4),
    }
