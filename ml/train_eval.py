"""Train and evaluate the anomaly detector on synthetic transfer events.

5,000 events, 5% exfiltration, 70/30 stratified split (by attack pattern, so the test set keeps
the 5% leak rate and equal thirds of each attack), seed 42.
Isolation Forest (200 trees, contamination 0.05) is trained WITHOUT labels.
Compares: rule-based heuristic, Isolation Forest, and the hybrid max(ML, heuristic) at threshold 0.5.

Outputs: models/anomaly_iforest.joblib, results/metrics.json, results/ml_evaluation.md, results/roc_curve.png

Run:  python ml/train_eval.py
"""
import json
import os
import sys
import time

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
RESULTS = os.path.join(ROOT, "results")
SEED = 42
THRESHOLD = 0.5

# Numbers quoted in the project review document (Figure 1), for comparison.
REVIEW = {"Rule-based heuristic": (66.2, 60.0, 62.9, 74.7), "Isolation Forest": (95.8, 90.7, 93.2, 99.9),
          "Proposed hybrid": (74.2, 96.0, 83.7, 99.7)}


def evaluate(name, y, score):
    pred = (score >= THRESHOLD).astype(int)
    return {"approach": name,
            "precision": precision_score(y, pred, zero_division=0),
            "recall": recall_score(y, pred, zero_division=0),
            "f1": f1_score(y, pred, zero_division=0),
            "roc_auc": roc_auc_score(y, score),
            "caught": int(((pred == 1) & (y == 1)).sum()),
            "leaks": int(y.sum()),
            "false_alarms": int(((pred == 1) & (y == 0)).sum())}


def main():
    X, y, pattern = synthetic.generate(n=5000, exfil_rate=0.05, seed=SEED)
    # Stratify by attack pattern (normal + 3 patterns): keeps the 5% leak rate AND equal thirds in the test set.
    X_tr, X_te, y_tr, y_te, p_tr, p_te = train_test_split(X, y, pattern, test_size=0.3, stratify=pattern,
                                                          random_state=SEED)

    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=SEED)
    t0 = time.perf_counter()
    model.fit(X_tr)                                # unsupervised: labels are not used
    train_ms = (time.perf_counter() - t0) * 1000

    heur = synthetic.heuristic(X_te)
    ml = synthetic.iforest_unit(model, X_te)
    hybrid = np.maximum(heur, ml)
    rows = [evaluate("Rule-based heuristic", y_te, heur),
            evaluate("Isolation Forest", y_te, ml),
            evaluate("Proposed hybrid", y_te, hybrid)]
    # ROC-AUC of the raw Isolation Forest score (before clipping to 0..1) for reference.
    raw_auc = roc_auc_score(y_te, -model.score_samples(X_te))

    per_pattern = {}
    for pat in ["night bulk copy", "large sensitive file", "burst of small files"]:
        m = p_te == pat
        per_pattern[pat] = {name: int((s[m] >= THRESHOLD).sum()) for name, s in
                            [("heuristic", heur), ("isolation_forest", ml), ("hybrid", hybrid)]}
        per_pattern[pat]["total"] = int(m.sum())

    os.makedirs(MODELS, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    joblib.dump(model, os.path.join(MODELS, "anomaly_iforest.joblib"))

    metrics = {"dataset": {"events": int(len(y)), "exfiltration": int(y.sum()), "train": int(len(y_tr)),
                           "test": int(len(y_te)), "test_leaks": int(y_te.sum()), "seed": SEED},
               "threshold": THRESHOLD, "train_ms": round(train_ms, 1),
               "isolation_forest_raw_roc_auc": raw_auc, "results": rows, "caught_by_pattern": per_pattern}
    with open(os.path.join(RESULTS, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)

    write_markdown(metrics)
    plot_roc(y_te, [("Rule-based heuristic", heur), ("Isolation Forest", ml), ("Proposed hybrid", hybrid)])

    print(f"Test set: {len(y_te)} events, {int(y_te.sum())} leaks. Threshold {THRESHOLD}.")
    print(f"{'Approach':<22}{'Precision':>10}{'Recall':>9}{'F1':>8}{'ROC-AUC':>9}  Caught    | review doc")
    for r in rows:
        ref = REVIEW[r["approach"]]
        print(f"{r['approach']:<22}{r['precision']:>10.1%}{r['recall']:>9.1%}{r['f1']:>8.1%}{r['roc_auc']:>9.1%}"
              f"  {r['caught']:>2} of {r['leaks']}  | P {ref[0]} R {ref[1]} F1 {ref[2]} AUC {ref[3]}")
    print(f"Isolation Forest raw-score ROC-AUC: {raw_auc:.1%}   training time {train_ms:.0f} ms")
    print("Saved models/anomaly_iforest.joblib, results/metrics.json, results/ml_evaluation.md, results/roc_curve.png")


def write_markdown(m):
    ds = m["dataset"]
    lines = ["# Anomaly detection - evaluation", "",
             f"Synthetic data: {ds['events']:,} transfer events, {ds['exfiltration']} exfiltration "
             f"({ds['exfiltration'] / ds['events']:.0%}), 70/30 split stratified by attack pattern (seed {ds['seed']}). "
             f"Test set: {ds['test']:,} events, {ds['test_leaks']} leaks. Threshold {m['threshold']}.",
             "", "Isolation Forest: 200 trees, contamination 0.05, trained without labels "
             f"({m['train_ms']:.0f} ms).", "",
             "| Approach | Precision | Recall | F1-score | ROC-AUC | Leaks caught | False alarms |",
             "|---|---|---|---|---|---|---|"]
    for r in m["results"]:
        lines.append(f"| {r['approach']} | {r['precision']:.1%} | {r['recall']:.1%} | {r['f1']:.1%} | "
                     f"{r['roc_auc']:.1%} | {r['caught']} of {r['leaks']} | {r['false_alarms']} |")
    lines += ["", f"Isolation Forest ROC-AUC on the raw (unclipped) score: {m['isolation_forest_raw_roc_auc']:.1%}.",
              "", "## Leaks caught by pattern", "",
              "| Pattern | Leaks | Heuristic | Isolation Forest | Hybrid |", "|---|---|---|---|---|"]
    for pat, c in m["caught_by_pattern"].items():
        lines.append(f"| {pat} | {c['total']} | {c['heuristic']} | {c['isolation_forest']} | {c['hybrid']} |")
    lines += ["", "## Review document (Figure 1) for comparison", "",
              "| Approach | Precision | Recall | F1-score | ROC-AUC |", "|---|---|---|---|---|"]
    for name, (p, r, f, a) in REVIEW.items():
        lines.append(f"| {name} | {p}% | {r}% | {f}% | {a}% |")
    lines += ["", "Note: the data is synthetic. These numbers show that the method separates the simulated "
              "patterns; accuracy on real organisational data needs labelled real transfer logs.", ""]
    with open(os.path.join(RESULTS, "ml_evaluation.md"), "w") as fh:
        fh.write("\n".join(lines))


def plot_roc(y, curves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from data_sentinel import viz
    viz.mpl_style(plt)
    fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=150)
    ax.plot([0, 1], [0, 1], color=viz.BASELINE, linewidth=1)
    for (name, score), color in zip(curves, viz.SERIES):
        fpr, tpr, _ = roc_curve(y, score)
        ax.plot(fpr, tpr, color=color, linewidth=2, label=f"{name} (AUC {roc_auc_score(y, score):.1%})",
                solid_joinstyle="round", solid_capstyle="round")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.01)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate (recall)")
    ax.set_title("ROC curve - anomaly detection on synthetic test set")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "roc_curve.png"))
    plt.close(fig)


if __name__ == "__main__":
    main()
