"""Shared chart colours and a matplotlib style (used by the ML scripts and the dashboard)."""

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

# Categorical slots, fixed order (identity).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

# Status colours (state) - always shown with a text label too.
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
DECISION_COLORS = {"ALLOW": GOOD, "WARN": WARNING, "BLOCK": CRITICAL}
LEVEL_COLORS = {"LOW": GOOD, "MEDIUM": WARNING, "HIGH": SERIOUS, "CRITICAL": CRITICAL}


def mpl_style(plt):
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": BASELINE, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
        "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "legend.frameon": False, "legend.labelcolor": INK_2, "lines.linewidth": 2,
        "font.family": "sans-serif", "font.size": 10,
    })
