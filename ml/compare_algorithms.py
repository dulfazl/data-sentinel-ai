"""Compare anomaly-detection algorithms and test the Luhn check.

1. Isolation Forest vs One-Class SVM vs Local Outlier Factor vs Elliptic Envelope vs the frequency
   heuristic, on the same synthetic data as train_eval.py, mean over seeds 1-5.
   Detectors are unsupervised; precision/recall/F1 use each detector's own decision
   (contamination / nu = 0.05; heuristic at 0.5), ROC-AUC uses its continuous score.
2. Luhn test: false card alarms on 10,000 random 16-digit numbers with and without the Luhn
   check, and the standard test card numbers must all still be detected.

Outputs: results/algorithm_comparison.{json,md,png}, results/luhn_test.{json,png}
Run:  python ml/compare_algorithms.py
"""
import json
import os
import sys
import time

import numpy as np
from sklearn.covariance import EllipticEnvelope
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic  # noqa: E402

from data_sentinel import viz  # noqa: E402
from data_sentinel.classifier import CONTENT_RULES, classify_text, luhn_ok  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
SEEDS = [1, 2, 3, 4, 5]
TEST_CARDS = {"Visa": "4111 1111 1111 1111", "Mastercard": "5555 5555 5555 4444", "Amex": "3782 822463 10005",
              "Discover": "6011 1111 1111 1117", "JCB": "3530 1113 3330 0000", "Diners Club": "3056 930902 5904"}
# Review document, Figure 2 (mean of 5 runs): precision, recall, F1, ROC-AUC
REVIEW = {"Isolation Forest": (92.2, 93.6, 92.8, 99.9), "Elliptic Envelope": (85.1, 82.4, 83.5, 99.6),
          "One-Class SVM": (66.4, 77.1, 71.3, 94.6), "Frequency heuristic": (62.8, 65.6, 64.0, 78.5),
          "Local Outlier Factor": (20.6, 20.8, 20.7, 68.4)}


def detectors(seed):
    return {
        "Isolation Forest": IsolationForest(n_estimators=200, contamination=0.05, random_state=seed),
        "One-Class SVM": make_pipeline(StandardScaler(), OneClassSVM(nu=0.05, gamma="scale")),
        "Local Outlier Factor": make_pipeline(StandardScaler(),
                                              LocalOutlierFactor(n_neighbors=20, contamination=0.05, novelty=True)),
        "Elliptic Envelope": EllipticEnvelope(contamination=0.05, random_state=seed),
    }


def run_seed(seed):
    X, y, pattern = synthetic.generate(n=5000, exfil_rate=0.05, seed=seed)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, stratify=pattern, random_state=seed)
    out = {}
    for name, model in detectors(seed).items():
        t0 = time.perf_counter()
        model.fit(X_tr)                                          # no labels
        ms = (time.perf_counter() - t0) * 1000
        pred = (model.predict(X_te) == -1).astype(int)
        score = -model.score_samples(X_te)                       # higher = more anomalous
        out[name] = metrics(y_te, pred, score, ms)
    heur = synthetic.heuristic(X_te)
    out["Frequency heuristic"] = metrics(y_te, (heur >= 0.5).astype(int), heur, None)
    return out


def metrics(y, pred, score, ms):
    return {"precision": precision_score(y, pred, zero_division=0), "recall": recall_score(y, pred, zero_division=0),
            "f1": f1_score(y, pred, zero_division=0), "roc_auc": roc_auc_score(y, score), "train_ms": ms}


def compare():
    runs = [run_seed(s) for s in SEEDS]
    names = list(runs[0])
    mean = {}
    for n in names:
        mean[n] = {k: float(np.mean([r[n][k] for r in runs])) for k in ("precision", "recall", "f1", "roc_auc")}
        times = [r[n]["train_ms"] for r in runs if r[n]["train_ms"] is not None]
        mean[n]["train_ms"] = float(np.mean(times)) if times else None
    return dict(sorted(mean.items(), key=lambda kv: -kv[1]["f1"])), runs


def luhn_test(n=10_000, seed=42):
    rng = np.random.default_rng(seed)
    numbers = ["".join(map(str, [rng.integers(1, 10)] + list(rng.integers(0, 10, 15)))) for _ in range(n)]
    card_rx = next(rx for label, rx, *_ in CONTENT_RULES if label == "credit card number")
    regex_hits = sum(1 for num in numbers if card_rx.fullmatch(num))
    luhn_hits = sum(1 for num in numbers if card_rx.fullmatch(num) and luhn_ok(num))
    detected = {brand: classify_text(f"card: {num}").matches.get("credit card number", 0) == 1
                for brand, num in TEST_CARDS.items()}
    return {"random_numbers": n, "seed": seed, "false_alarms_regex_only": regex_hits,
            "false_alarms_regex_plus_luhn": luhn_hits, "reduction": 1 - luhn_hits / regex_hits,
            "test_cards_detected": detected, "all_test_cards_detected": all(detected.values())}


def plot_comparison(mean):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    viz.mpl_style(plt)
    names = list(mean)[::-1]                                     # best at the top
    y = np.arange(len(names))
    h = 0.34
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=150)
    for off, key, label, color in [(h / 2 + 0.02, "f1", "F1-score", viz.SERIES[0]),
                                   (-h / 2 - 0.02, "roc_auc", "ROC-AUC", viz.SERIES[1])]:
        vals = [mean[n][key] * 100 for n in names]
        ax.barh(y + off, vals, height=h, color=color, label=label)
        for yi, v in zip(y + off, vals):
            ax.text(v + 1, yi, f"{v:.1f}%", va="center", fontsize=8, color=viz.INK_2)
    ax.set_yticks(y, names)
    ax.set_xlim(0, 112)
    ax.set_xlabel("%  (mean of seeds 1-5)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Anomaly detectors on synthetic transfers")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "algorithm_comparison.png"))
    plt.close(fig)


def plot_luhn(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    viz.mpl_style(plt)
    labels = ["Regex only", "Regex + Luhn"]
    vals = [res["false_alarms_regex_only"], res["false_alarms_regex_plus_luhn"]]
    fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=150)
    ax.bar(labels, vals, width=0.45, color=viz.SERIES[0])
    for i, v in enumerate(vals):
        ax.text(i, v + 150, f"{v:,}", ha="center", fontsize=10, color=viz.INK)
    ax.set_ylim(0, max(vals) * 1.15)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_ylabel("False card-number alarms")
    ax.grid(axis="x", visible=False)
    ax.set_title(f"False alarms on {res['random_numbers']:,} random 16-digit numbers")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "luhn_test.png"))
    plt.close(fig)


def main():
    os.makedirs(RESULTS, exist_ok=True)
    mean, runs = compare()
    luhn = luhn_test()
    with open(os.path.join(RESULTS, "algorithm_comparison.json"), "w") as fh:
        json.dump({"seeds": SEEDS, "mean": mean, "per_seed": runs}, fh, indent=2)
    with open(os.path.join(RESULTS, "luhn_test.json"), "w") as fh:
        json.dump(luhn, fh, indent=2)
    plot_comparison(mean)
    plot_luhn(luhn)

    lines = ["# Algorithm comparison (mean of seeds 1-5)", "",
             "| Algorithm | Precision | Recall | F1-score | ROC-AUC | Training time | Review doc (P / R / F1 / AUC) |",
             "|---|---|---|---|---|---|---|"]
    print(f"{'Algorithm':<22}{'Precision':>10}{'Recall':>9}{'F1':>8}{'ROC-AUC':>9}{'Train':>10}   | review doc")
    for n, m in mean.items():
        t = f"{m['train_ms']:.0f} ms" if m["train_ms"] is not None else "none"
        ref = REVIEW[n]
        print(f"{n:<22}{m['precision']:>10.1%}{m['recall']:>9.1%}{m['f1']:>8.1%}{m['roc_auc']:>9.1%}{t:>10}"
              f"   | {ref[0]} / {ref[1]} / {ref[2]} / {ref[3]}")
        lines.append(f"| {n} | {m['precision']:.1%} | {m['recall']:.1%} | {m['f1']:.1%} | {m['roc_auc']:.1%} | {t} | "
                     f"{ref[0]}% / {ref[1]}% / {ref[2]}% / {ref[3]}% |")
    lines += ["", "Training time depends on the machine.", "",
              "# Luhn test", "",
              f"Random 16-digit numbers: {luhn['random_numbers']:,} (seed {luhn['seed']}).", "",
              f"- False alarms with the card regex only: **{luhn['false_alarms_regex_only']:,}**",
              f"- False alarms with regex + Luhn: **{luhn['false_alarms_regex_plus_luhn']:,}** "
              f"({luhn['reduction']:.1%} fewer)",
              f"- Standard test card numbers detected: {sum(luhn['test_cards_detected'].values())} of "
              f"{len(TEST_CARDS)} ({', '.join(TEST_CARDS)})", ""]
    with open(os.path.join(RESULTS, "algorithm_comparison.md"), "w") as fh:
        fh.write("\n".join(lines))
    print(f"\nLuhn: regex alone {luhn['false_alarms_regex_only']:,} false alarms, regex + Luhn "
          f"{luhn['false_alarms_regex_plus_luhn']:,} ({luhn['reduction']:.1%} fewer); "
          f"test cards detected: {sum(luhn['test_cards_detected'].values())}/{len(TEST_CARDS)}")
    print("Saved results/algorithm_comparison.{json,md,png} and results/luhn_test.{json,png}")


if __name__ == "__main__":
    main()
