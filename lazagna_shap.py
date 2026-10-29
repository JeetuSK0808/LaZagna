"""SHAP importance of search and design parameters.

Explains what drives the results of an Optuna study, or of any table of runs. A gradient-boosted
tree surrogate is fit to (parameters -> target, e.g. CPD gain %), and TreeSHAP splits every
prediction into one contribution per parameter. Reported for each parameter:

  mean |SHAP|  average size of its contribution, in the target's units (for the study
               targets: percentage points of CPD / WL gain)
  sd           spread of that number over repeated surrogate fits (different seeds)
  share        its fraction of the summed mean |SHAP| over all parameters
  direction    numeric parameters: Spearman correlation between the value and its SHAP value
               (+ = larger values raise the target). Categorical: mean SHAP per category.

Every table also reports the surrogate's cross-validated R^2 (out-of-fold predictions). When it
is low the parameters do not predict the target well (seed noise dominates), and the
importances should not be read as effects.

Categorical parameters are one-hot encoded and their columns summed back into one SHAP value
per parameter. Conditional parameters that a trial did not sample (e.g. hb_period when
family = edge) are filled with a typical observed value (the observed value nearest the
median; the most common category), NOT with a "missing" marker. A marker would repeat the
information already carried by the parameter that switches them on (family), and SHAP would
then split that parameter's effect between the two.

Needs scikit-learn and shap (pip install -r requirements-analysis.txt). The rest of LaZagna
works without them.

  python3 lazagna_shap.py --journal work/journal/columns_x.log --study columns_x
  python3 lazagna_shap.py --storage sqlite:///study.db --study lazagna_3d --target cpd_impr_pct
  python3 lazagna_shap.py --csv runs.csv --target cpd_gain --features a,b,c --out shap_out
"""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

DEFAULT_TARGETS = ("cpd_impr_pct", "wl_impr_pct")
MIN_SAMPLES = 8
LOW_R2 = 0.3
MIN_SHARE_FOR_DIRECTION = 0.05   # below this share, a direction is noise and is not shown
_MISSING = object()


def _require():
    try:
        import numpy  # noqa: F401
        import shap  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as e:
        raise ImportError("SHAP analysis needs scikit-learn and shap: "
                          "pip install -r requirements-analysis.txt") from e


@dataclass
class Table:
    """Samples to explain: ids, one dict of parameter values per sample, and target columns."""
    ids: list
    rows: list[dict]
    targets: dict[str, list[float]]
    params: list[str] = field(default_factory=list)


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _target_value(trial, spec: str):
    """A user attr, or "value:<i>" for the i-th objective value."""
    if spec.startswith("value:"):
        i = int(spec.split(":", 1)[1])
        vals = trial.values or []
        return vals[i] if i < len(vals) else None
    return trial.user_attrs.get(spec)


def table_from_study(study, targets: Sequence[str] = DEFAULT_TARGETS,
                     params: Optional[Sequence[str]] = None) -> Table:
    """COMPLETE trials that have every target as a finite number."""
    import optuna
    ids, rows, tv = [], [], {t: [] for t in targets}
    seen: list[str] = []
    for tr in study.trials:
        if tr.state != optuna.trial.TrialState.COMPLETE:
            continue
        vals = [_target_value(tr, t) for t in targets]
        if not all(_finite(v) for v in vals):
            continue
        ids.append(tr.number)
        rows.append(dict(tr.params))
        for t, v in zip(targets, vals):
            tv[t].append(float(v))
        for p in tr.params:
            if p not in seen:
                seen.append(p)
    return Table(ids=ids, rows=rows, targets=tv, params=list(params) if params else seen)


def _num(s):
    if isinstance(s, (int, float)):
        return s
    try:
        return float(s)
    except (TypeError, ValueError):
        return s


def table_from_csv(path: str, targets: Sequence[str], features: Optional[Sequence[str]] = None,
                   id_col: Optional[str] = None) -> Table:
    """One row per sample. Features default to every column that is not a target or the id."""
    with open(path, newline="") as f:
        data = list(csv.DictReader(f))
    if not data:
        raise ValueError(f"{path} has no rows")
    cols = list(data[0].keys())
    for t in targets:
        if t not in cols:
            raise ValueError(f"target column '{t}' not in {path} (columns: {cols})")
    feats = list(features) if features else [c for c in cols if c not in targets and c != id_col]
    ids, rows, tv = [], [], {t: [] for t in targets}
    for i, r in enumerate(data):
        vals = [_num(r[t]) for t in targets]
        if not all(_finite(v) for v in vals):
            continue
        ids.append(r[id_col] if id_col else i)
        rows.append({c: (_num(r[c]) if r.get(c, "") != "" else _MISSING) for c in feats})
        for t, v in zip(targets, vals):
            tv[t].append(float(v))
    return Table(ids=ids, rows=rows, targets=tv, params=feats)


def _is_number(v) -> bool:
    return isinstance(v, (bool, int, float)) and (not isinstance(v, float) or math.isfinite(v))


def encode(table: Table):
    """Design matrix. Returns (X, column names, groups {param: [column indices]}, kinds, fills)."""
    import numpy as np
    cols, names, groups, kinds, fills = [], [], {}, {}, {}
    for p in table.params:
        vals = [r.get(p, _MISSING) for r in table.rows]
        present = [v for v in vals if v is not _MISSING and v is not None]
        if present and all(_is_number(v) for v in present):
            kinds[p] = "numeric"
            xs = sorted(float(v) for v in present)
            med = xs[len(xs) // 2] if len(xs) % 2 else 0.5 * (xs[len(xs) // 2 - 1] + xs[len(xs) // 2])
            fill = min(xs, key=lambda x: (abs(x - med), x))   # an observed value, not an outlier
            col = []
            for v in vals:
                if v is _MISSING or v is None:
                    col.append(fill)
                    fills[p] = fill
                else:
                    col.append(float(v))
            groups[p] = [len(cols)]
            cols.append(col)
            names.append(p)
        else:
            kinds[p] = "categorical"
            labels = _cat_labels(vals)
            if any(v is _MISSING or v is None for v in vals):
                fills[p] = _cat_fill(vals)
            groups[p] = []
            for c in sorted(set(labels)):
                groups[p].append(len(cols))
                cols.append([1.0 if lab == c else 0.0 for lab in labels])
                names.append(f"{p}={c}")
    X = np.array(cols, dtype=float).T if cols else np.zeros((len(table.rows), 0))
    return X, names, groups, kinds, fills


def _cat_fill(vals) -> str:
    """Most common observed category (ties: alphabetical), used for trials without a value."""
    from collections import Counter
    seen = Counter(str(v) for v in vals if v is not _MISSING and v is not None)
    return min(seen, key=lambda c: (-seen[c], c)) if seen else "<missing>"


def _cat_labels(vals) -> list:
    fill = _cat_fill(vals)
    return [fill if (v is _MISSING or v is None) else str(v) for v in vals]


def _spearman(a, b) -> float:
    import numpy as np
    from scipy.stats import rankdata
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    ra, rb = rankdata(a), rankdata(b)
    return float(np.corrcoef(ra, rb)[0, 1])


def _model(seed: int, n: int, model_params: Optional[dict] = None):
    from sklearn.ensemble import GradientBoostingRegressor
    kw = dict(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8,
              min_samples_leaf=max(1, min(5, n // 10)), random_state=seed)
    kw.update(model_params or {})
    return GradientBoostingRegressor(**kw)


def shap_importance(table: Table, target: str, n_repeats: int = 5, seed: int = 0,
                    model_params: Optional[dict] = None) -> dict:
    """SHAP importance of table.params for one target (see the module docstring)."""
    _require()
    import numpy as np
    import shap
    from sklearn.metrics import r2_score
    from sklearn.model_selection import KFold, cross_val_predict

    y = np.asarray(table.targets[target], dtype=float)
    n = len(y)
    if n < MIN_SAMPLES:
        raise ValueError(f"{target}: {n} samples; SHAP needs at least {MIN_SAMPLES}")
    X, names, groups, kinds, fills = encode(table)
    if X.shape[1] == 0:
        raise ValueError("no parameters to explain")

    # How well do the parameters predict the target at all? Out-of-fold R^2.
    kf = KFold(n_splits=min(5, n), shuffle=True, random_state=seed)
    oof = cross_val_predict(_model(seed, n, model_params), X, y, cv=kf)
    cv_r2 = float(r2_score(y, oof))

    per_rep, sv_sum, train_r2, expected = [], None, [], []
    for r in range(max(1, n_repeats)):
        m = _model(seed + r, n, model_params).fit(X, y)
        train_r2.append(float(r2_score(y, m.predict(X))))
        ex = shap.TreeExplainer(m)
        sv = np.asarray(ex.shap_values(X), dtype=float).reshape(n, -1)
        ev = float(np.ravel(ex.expected_value)[0])
        if not np.allclose(sv.sum(axis=1) + ev, m.predict(X), atol=1e-6 * max(1.0, float(np.abs(y).max()))):
            raise RuntimeError("SHAP values do not add up to the model output (shap/sklearn mismatch)")
        expected.append(ev)
        grouped = np.stack([sv[:, idx].sum(axis=1) for idx in groups.values()], axis=1)
        per_rep.append(np.abs(grouped).mean(axis=0))
        sv_sum = grouped if sv_sum is None else sv_sum + grouped
    reps = np.stack(per_rep)                      # repeats x params
    sv_mean = sv_sum / len(per_rep)               # samples x params, averaged over repeats
    imp, sd = reps.mean(axis=0), reps.std(axis=0)
    total = float(imp.sum()) or 1.0

    params = list(groups)
    rows = []
    for j, p in enumerate(params):
        vals = [r.get(p, _MISSING) for r in table.rows]
        entry = {"param": p, "kind": kinds[p], "mean_abs_shap": float(imp[j]), "sd": float(sd[j]),
                 "share": float(imp[j]) / total}
        if kinds[p] == "numeric":
            xs = X[:, groups[p][0]]
            entry["direction"] = _spearman(xs, sv_mean[:, j])
            if p in fills:
                entry["missing_fill"] = fills[p]
        else:
            labels = _cat_labels(vals)
            entry["by_category"] = {c: float(np.mean([sv_mean[i, j] for i in range(n) if labels[i] == c]))
                                    for c in sorted(set(labels))}
            if p in fills:
                entry["missing_fill"] = fills[p]
        rows.append(entry)
    rows.sort(key=lambda e: -e["mean_abs_shap"])

    return {
        "target": target, "n": n, "params": params, "repeats": len(per_rep),
        "cv_r2": cv_r2, "train_r2": float(np.mean(train_r2)), "expected_value": float(np.mean(expected)),
        "importance": rows,
        "per_sample": {"ids": list(table.ids), "target": [float(v) for v in y],
                       "shap": {p: [float(v) for v in sv_mean[:, j]] for j, p in enumerate(params)}},
    }


def explain_study(study, targets: Sequence[str] = DEFAULT_TARGETS, params: Optional[Sequence[str]] = None,
                  n_repeats: int = 5, seed: int = 0) -> list[dict]:
    """shap_importance() for each target of an Optuna study."""
    table = table_from_study(study, targets, params)
    return [shap_importance(table, t, n_repeats=n_repeats, seed=seed) for t in targets]


def _fmt_dir(e: dict) -> str:
    if e.get("share", 1.0) < MIN_SHARE_FOR_DIRECTION:
        return "·"
    if e["kind"] == "numeric":
        d = e.get("direction")
        if d is None or not math.isfinite(d):
            return "flat"
        return f"{d:+.2f}"
    cats = e.get("by_category") or {}
    if not cats:
        return ""
    best = max(cats, key=cats.get)
    return f"best: {best} ({cats[best]:+.2f})"


def to_markdown(results: Sequence[dict], title: str = "") -> str:
    out = [f"## {title}", ""] if title else []
    for r in results:
        out += [f"### SHAP importance: {r['target']} (n = {r['n']}, surrogate CV R² = {r['cv_r2']:.2f}, "
                f"{r['repeats']} fits)", "",
                "| parameter | mean \\|SHAP\\| | ± sd | share | direction |",
                "|---|---|---|---|---|"]
        for e in r["importance"]:
            out.append(f"| {e['param']} | {e['mean_abs_shap']:.3f} | {e['sd']:.3f} | "
                       f"{100 * e['share']:.0f}% | {_fmt_dir(e)} |")
        out.append("")
        if r["cv_r2"] < LOW_R2:
            out += [f"> Surrogate CV R² is {r['cv_r2']:.2f} (< {LOW_R2}): the parameters explain little of "
                    f"the variation in {r['target']}, so read these importances as weak.", ""]
    out += ["mean |SHAP| is in the target's units. Direction: Spearman correlation between a "
            "numeric parameter's value and its SHAP value (+ = larger values raise the target); for a "
            "categorical parameter, the category with the highest mean SHAP. A direction near 0 with a "
            "large mean |SHAP| means the effect is not monotonic (e.g. best in the middle). '·' = share "
            f"below {100 * MIN_SHARE_FOR_DIRECTION:.0f}%, direction not meaningful.", ""]
    return "\n".join(out)


def write_outputs(results: Sequence[dict], out_dir: str, prefix: str = "shap", plot: bool = True,
                  title: str = "") -> list[str]:
    """<prefix>.json (all results), <prefix>.md, <prefix>_<target>.csv (per-sample SHAP) and,
    if matplotlib is available, <prefix>_<target>.png (bar chart of mean |SHAP| ± sd)."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    p = os.path.join(out_dir, prefix + ".json")
    with open(p, "w") as f:
        json.dump(list(results), f, indent=1)
    paths.append(p)
    p = os.path.join(out_dir, prefix + ".md")
    with open(p, "w") as f:
        f.write(to_markdown(results, title))
    paths.append(p)
    for r in results:
        ps = r["per_sample"]
        p = os.path.join(out_dir, f"{prefix}_{r['target']}.csv")
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", r["target"]] + [f"shap_{q}" for q in r["params"]])
            for i, sid in enumerate(ps["ids"]):
                w.writerow([sid, ps["target"][i]] + [ps["shap"][q][i] for q in r["params"]])
        paths.append(p)
        if plot:
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                continue
            imp = r["importance"][::-1]
            fig, ax = plt.subplots(figsize=(6, 0.4 * len(imp) + 1.2))
            ax.barh([e["param"] for e in imp], [e["mean_abs_shap"] for e in imp],
                    xerr=[e["sd"] for e in imp], color="#2a78d6")
            ax.set_xlabel(f"mean |SHAP| ({r['target']})")
            ax.set_title(f"{r['target']}: n = {r['n']}, CV R² = {r['cv_r2']:.2f}", fontsize=9)
            fig.tight_layout()
            p = os.path.join(out_dir, f"{prefix}_{r['target']}.png")
            fig.savefig(p, dpi=150)
            plt.close(fig)
            paths.append(p)
    return paths


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SHAP importance of an Optuna study's parameters, or of a CSV.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--journal", help="Optuna JournalStorage log file (campaign studies)")
    src.add_argument("--storage", help="Optuna storage URL, e.g. sqlite:///study.db")
    src.add_argument("--csv", help="CSV with one row per run")
    ap.add_argument("--study", help="study name (with --journal / --storage)")
    ap.add_argument("--target", action="append",
                    help=f"target: a trial user attr or value:<i> (default {', '.join(DEFAULT_TARGETS)}); "
                         "a column name for --csv. Repeat for several.")
    ap.add_argument("--params", "--features", dest="params", help="comma-separated parameters to explain")
    ap.add_argument("--id-col", help="(--csv) column with the row id")
    ap.add_argument("--repeats", type=int, default=5, help="surrogate refits with different seeds (default 5)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="shap_out", help="output directory (default shap_out)")
    ap.add_argument("--no-plot", action="store_true")
    a = ap.parse_args(argv)
    params = [s for s in (a.params or "").split(",") if s] or None

    if a.csv:
        if not a.target:
            ap.error("--csv needs --target")
        table = table_from_csv(a.csv, a.target, params, a.id_col)
        title, targets = os.path.basename(a.csv), a.target
    else:
        import optuna
        if not a.study:
            ap.error("--journal / --storage need --study")
        if a.journal:
            from lazagna_optuna import journal_storage
            storage = journal_storage(a.journal)
        else:
            storage = a.storage
        study = optuna.load_study(study_name=a.study, storage=storage)
        targets = a.target or list(DEFAULT_TARGETS)
        table = table_from_study(study, targets, params)
        title = a.study
    results = [shap_importance(table, t, n_repeats=a.repeats, seed=a.seed) for t in targets]
    for p in write_outputs(results, a.out, plot=not a.no_plot, title=title):
        print("wrote", p)
    print(to_markdown(results, title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
