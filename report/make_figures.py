"""Figures for the IEEE report, drawn from the project's real results (results/*.json, scenarios).

Run:  .venv/bin/python report/make_figures.py      -> report/figures/*.png (300 dpi)
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data_sentinel import config, viz  # noqa: E402

OUT = os.path.join(ROOT, "report", "figures")
COL_W = 3.45          # IEEE single column width (in)
PAGE_W = 7.0          # IEEE text width (in)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 7.5, "axes.titlesize": 8, "axes.labelsize": 7.5, "xtick.labelsize": 7,
    "ytick.labelsize": 7, "legend.fontsize": 6.8, "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#8a8a8a", "axes.grid": True, "grid.color": "#e1e0d9", "grid.linewidth": 0.6,
    "axes.axisbelow": True, "legend.frameon": False, "savefig.dpi": 300, "figure.dpi": 300,
})
BLUE, ORANGE, AQUA = viz.SERIES[0], viz.SERIES[1], viz.SERIES[2]


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight", pad_inches=0.03, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------- architecture
def box(ax, x, y, w, h, text, fc, ec, size=6.2, bold_first=False):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.25,rounding_size=0.9",
                                fc=fc, ec=ec, lw=0.7))
    lines = text.split("\n")
    if bold_first and len(lines) > 1:
        ax.text(x, y + 0.9, lines[0], ha="center", va="center", fontsize=size, fontweight="bold", color="#1b1b1b")
        ax.text(x, y - 1.1, "\n".join(lines[1:]), ha="center", va="center", fontsize=size - 0.6, color="#333",
                linespacing=1.05)
    else:
        ax.text(x, y, text, ha="center", va="center", fontsize=size, color="#1b1b1b", linespacing=1.05)


def arrow(ax, x1, y1, x2, y2, color="#6b6b6b"):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=0.7, mutation_scale=6, shrinkA=0, shrinkB=0))


def line(ax, xs, ys, color="#6b6b6b"):
    ax.plot(xs, ys, color=color, lw=0.7, solid_capstyle="butt")


def group(ax, x0, x1, y0, y1, title, solid=False):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.2",
                                fc="#f7f7f5" if solid else "none", ec="#b5b5b0", lw=0.7,
                                ls="-" if solid else (0, (4, 3))))
    ax.text(x0 + 1.0, y1 - 1.6, title, ha="left", va="center", fontsize=6.6, fontweight="bold", color="#1b1b1b")


def architecture():
    fig = plt.figure(figsize=(PAGE_W, 3.55))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(4, 55)
    ax.axis("off")
    CH = ("#f1eee6", "#b3ad9c")
    SE = ("#e3eefb", "#86b6ef")
    EN = ("#e2f4ec", "#6cc4a0")
    AN = ("#fdeee6", "#ec835a")
    RB = ("#fbe1e1", "#d97777")
    RW = ("#fdf2dc", "#e3b54a")
    ST = ("#ebe7f8", "#9a8fd8")

    group(ax, 0.5, 17.5, 6, 54, "1. Data exit channels")
    group(ax, 19.5, 36.5, 6, 54, "2. Sensors (detection)")
    group(ax, 39.5, 61.5, 6, 54, "3. Data Sentinel AI engine", solid=True)
    group(ax, 63.5, 80.5, 6, 54, "4. Response")
    group(ax, 82.5, 99.5, 6, 54, "5. Storage & monitoring")

    chans = [(47, "USB drives"), (40.5, "Cloud sync folders\n(Drive, OneDrive, Dropbox,\niCloud, Box)"),
             (33.5, "Network shares\n(SMB / NFS / WebDAV)"), (26.5, "Websites\n(upload, drag-drop, paste)"),
             (19.5, "Desktop e-mail\n(Outlook, Thunderbird)"), (12.5, "Files already shared\nin Google Drive")]
    for y, t in chans:
        box(ax, 9, y, 15, 5.4, t, *CH, size=5.9)

    sensors = [(40.5, "Folder / volume monitor\n(psutil, polled every 2 s,\nbaseline + stable size)"),
               (26.5, "Browser extension (MV3)\n+ local scan API\n127.0.0.1:8765, token"),
               (19.5, "SMTP DLP gateway\n(aiosmtpd, 127.0.0.1:1025)"),
               (12.5, "Drive API v3 scanner\n(OAuth, report / --fix)")]
    for y, t in sensors:
        box(ax, 28, y, 15, 5.4, t, *SE, size=5.7)
    for y in (47, 40.5, 33.5):
        line(ax, [16.6, 18.2], [y, y])
    line(ax, [18.2, 18.2], [33.5, 47])
    arrow(ax, 18.2, 40.5, 20.4, 40.5)
    for y in (26.5, 19.5, 12.5):
        arrow(ax, 16.6, y, 20.4, y)

    # sensors -> engine bus
    for y in (40.5, 26.5, 19.5, 12.5):
        line(ax, [35.6, 38.2], [y, y])
    line(ax, [38.2, 38.2], [12.5, 47])
    arrow(ax, 38.2, 47, 40.8, 47)

    stages = [(47, "Metadata extraction\nuser, destination, size, time, SHA-256", EN),
              (40.2, "Data classifier\nregex rules + Luhn → Public … Restricted", EN),
              (33.4, "Context analysis\nrole, device trust, destination, time, size", EN),
              (26.6, "Anomaly detection\nIsolation Forest + frequency heuristic", AN),
              (19.8, "Weighted risk score\nscore 0–100 → LOW … CRITICAL", EN),
              (13.0, "Policy engine\nALLOW / WARN / BLOCK + hard rules", EN)]
    for i, (y, t, c) in enumerate(stages):
        box(ax, 50.5, y, 20, 5.0, t, *c, size=6.0, bold_first=True)
        if i:
            arrow(ax, 50.5, stages[i - 1][0] - 2.75, 50.5, y + 2.75)

    responses = [(46, "BLOCK\nquarantine / drop upload /\nSMTP 550 / remove sharing", RB),
                 (37.5, "Alert to security team\n(stored + console + Slack hook)", RB),
                 (27.5, "WARN\namber banner, transfer logged", RW),
                 (19.5, "ALLOW\nlogged only", ("#e8f5e8", "#7cc47c"))]
    for y, t, c in responses:
        box(ax, 72, y, 15, 5.6, t, *c, size=5.8, bold_first=True)
    arrow(ax, 72, 46 - 2.95, 72, 37.5 + 2.95)
    line(ax, [60.6, 62.6], [13, 13])
    line(ax, [62.6, 62.6], [13, 46])
    for y in (46, 27.5, 19.5):
        arrow(ax, 62.6, y, 64.4, y)

    stores = [(44, "Database\nSQLite / PostgreSQL: users,\ndevices, files, events, risk,\nalerts, policies"),
              (32, "Hash-chained audit log\nSHA-256(previous hash + record),\nchecked by verify-audit"),
              (20, "Streamlit dashboard\nKPIs, charts, reasons, alerts")]
    for y, t in stores:
        box(ax, 91, y, 15.2, 6.0, t, *ST, size=5.6, bold_first=True)
    arrow(ax, 91, 44 - 3.1, 91, 32 + 3.1)
    arrow(ax, 91, 32 - 3.1, 91, 20 + 3.1)
    for y in (37.5, 27.5, 19.5):
        line(ax, [79.6, 81.4], [y, y])
    line(ax, [81.4, 81.4], [19.5, 44])
    arrow(ax, 81.4, 44, 83.3, 44)
    ax.text(50.5, 7.6, "one shared, thread-safe engine for every channel", ha="center", fontsize=5.6,
            style="italic", color="#555")
    save(fig, "fig_architecture.png")


# --------------------------------------------------------------------------- bar diagrams
def scenarios():
    from data_sentinel import scenarios as sc
    from data_sentinel.db import Database
    from data_sentinel.engine import Engine
    db = Database(url="", sqlite_path=":memory:")
    db.init_schema()
    res = sc.run(Engine(db), verbose=False)
    labels = {"A": "A  Public notice → company laptop", "B": "B  Internal memo → unknown USB",
              "C": "C  Payroll + card → untrusted USB", "D": "D  12th night-time USB copy",
              "E": "E  Customer list → Google Drive", "F": "F  API key → ChatGPT",
              "G": "G  Salary sheet → personal Gmail", "H": "H  Lunch mail → colleague",
              "I": "I  Restricted file → OneDrive sync", "J": "J  Payroll shared publicly (Drive)"}
    order = sorted(res, key=lambda s: res[s].score)
    fig, ax = plt.subplots(figsize=(COL_W, 2.55))
    ys = range(len(order))
    for y, s in zip(ys, order):
        d = res[s]
        ax.barh(y, d.score, height=0.62, color=viz.DECISION_COLORS[d.decision])
        ax.text(d.score + 1, y, f"{d.score:.1f} {d.decision}", va="center", fontsize=6.2, color="#222")
    ax.set_yticks(list(ys), [labels[s] for s in order], fontsize=6.3)
    for x, lab in [(25, "MEDIUM"), (50, "HIGH"), (70, "CRITICAL")]:
        ax.axvline(x, color="#9a9a9a", lw=0.6, ls=(0, (3, 2)))
        ax.text(x + 0.6, len(order) - 0.35, lab, fontsize=5.4, color="#666")
    ax.set_xlim(0, 92)
    ax.set_xlabel("Risk score (0–100)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_scenarios.png")
    return res


def detection(m):
    names = ["Rule-based heuristic", "Isolation Forest", "Proposed hybrid"]
    rows = {r["approach"]: r for r in m["results"]}
    metrics = [("precision", "Precision"), ("recall", "Recall"), ("f1", "F1-score"), ("roc_auc", "ROC-AUC")]
    fig, ax = plt.subplots(figsize=(COL_W, 2.15))
    w = 0.26
    for i, (name, color) in enumerate(zip(names, [BLUE, ORANGE, AQUA])):
        xs = [k + (i - 1) * (w + 0.02) for k in range(len(metrics))]
        vals = [rows[name][key] * 100 for key, _ in metrics]
        ax.bar(xs, vals, width=w, color=color, label=name)
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.2, f"{v:.2f}" if v >= 99.9 else f"{v:.1f}", ha="center", fontsize=5.0, color="#333")
    ax.set_xticks(range(len(metrics)), [lab for _, lab in metrics])
    ax.set_ylim(0, 112)
    ax.set_ylabel("Score (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=3, handlelength=1.2, columnspacing=1.0)
    save(fig, "fig_detection.png")


def algorithms(c):
    mean = c["mean"]
    names = list(mean)
    fig, ax = plt.subplots(figsize=(COL_W, 2.1))
    w = 0.38
    for i, (key, lab, color) in enumerate([("f1", "F1-score", BLUE), ("roc_auc", "ROC-AUC", ORANGE)]):
        xs = [k + (i - 0.5) * (w + 0.02) for k in range(len(names))]
        vals = [mean[n][key] * 100 for n in names]
        ax.bar(xs, vals, width=w, color=color, label=lab)
        for x, v in zip(xs, vals):
            ax.text(x, v + 1.2, f"{v:.1f}", ha="center", fontsize=5.2, color="#333")
    short = {"Isolation Forest": "Isolation\nForest", "Elliptic Envelope": "Elliptic\nEnvelope",
             "One-Class SVM": "One-Class\nSVM", "Frequency heuristic": "Frequency\nheuristic",
             "Local Outlier Factor": "Local Outlier\nFactor"}
    ax.set_xticks(range(len(names)), [short.get(n, n) for n in names], fontsize=6.3)
    ax.set_ylim(0, 112)
    ax.set_ylabel("Score (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, handlelength=1.2)
    save(fig, "fig_algorithms.png")


def luhn(r):
    fig, ax = plt.subplots(figsize=(COL_W, 1.25))
    labels = ["Regex + Luhn check", "Regex only"]
    vals = [r["false_alarms_regex_plus_luhn"], r["false_alarms_regex_only"]]
    ax.barh([0, 1], vals, height=0.55, color=[AQUA, BLUE])
    for y, v in zip([0, 1], vals):
        ax.text(v + 120, y, f"{v:,}", va="center", fontsize=6.5)
    ax.set_yticks([0, 1], labels)
    ax.set_xlim(0, 11500)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel(f"False alarms on {r['random_numbers']:,} random 16-digit numbers")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_luhn.png")


def weights():
    labels = {"sensitivity": "Data sensitivity", "device": "Device / destination trust",
              "destination": "Destination type", "user": "User role & history", "context": "Context (time, size)",
              "anomaly": "Anomaly (ML)"}
    order = ["anomaly", "context", "user", "destination", "device", "sensitivity"]
    fig, ax = plt.subplots(figsize=(COL_W, 1.55))
    vals = [config.WEIGHTS[k] * 100 for k in order]
    ax.barh(range(len(order)), vals, height=0.58, color=BLUE)
    for y, v in enumerate(vals):
        ax.text(v + 0.5, y, f"{v:.0f}%", va="center", fontsize=6.5)
    ax.set_yticks(range(len(order)), [labels[k] for k in order])
    ax.set_xlim(0, 40)
    ax.set_xlabel("Weight in the risk score (%)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_weights.png")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    m = json.load(open(os.path.join(ROOT, "results", "metrics.json")))
    c = json.load(open(os.path.join(ROOT, "results", "algorithm_comparison.json")))
    lt = json.load(open(os.path.join(ROOT, "results", "luhn_test.json")))
    architecture()
    scenarios()
    detection(m)
    algorithms(c)
    luhn(lt)
    weights()
    print("figures written to", OUT, sorted(os.listdir(OUT)))
