"""Step 2: label every day with its cycle phase, aggregate spending, run tests, draw figures.

Inputs : data/processed/transactions.csv (git-ignored), data/raw/cycles.csv (git-ignored)
Outputs: data/aggregated/*.csv (cycle- and phase-level only, no dates), figures/*.png
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
TX = ROOT / "data" / "processed" / "transactions.csv"
CYC = ROOT / "data" / "raw" / "cycles.csv"
AGG = ROOT / "data" / "aggregated"
FIG = ROOT / "figures"
AGG.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

LUTEAL_LEN = 14          # assumption: ovulation ~14 days before next period
MENSES_DAYS = 5          # assumption: bleeding length not recorded, first 5 days
DISCRETIONARY = ["Cafe", "Food delivery", "Eating out", "Online shopping",
                 "Clothing & cosmetics", "Entertainment & events", "Vending"]
PHASES = ["Menstrual", "Follicular", "Ovulatory", "Luteal"]
RNG = np.random.default_rng(210)

INK, MUTED, ACCENT, GRID = "#1f2933", "#6b7785", "#0f6e6e", "#e3e7eb"
plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.dpi": 140, "savefig.bbox": "tight",
})


def label_days(first_day, last_day) -> pd.DataFrame:
    cyc = pd.read_csv(CYC, parse_dates=["start", "end"])
    rows = []
    for i, c in cyc.iterrows():
        L = (c.end - c.start).days + 1
        ongoing = c.end >= last_day          # cycle not finished yet: its length is unknown
        if ongoing:
            # only days that are phase-certain for any observed cycle length (>= 25 days):
            # day 1-5 menstrual, day 6-9 follicular. Later days stay unlabelled.
            L = MENSES_DAYS + 4
            ov = 99
        else:
            ov = L - LUTEAL_LEN
        for d in range(1, L + 1):
            day = c.start + pd.Timedelta(days=d - 1)
            if d <= MENSES_DAYS:
                ph = "Menstrual"
            elif d <= ov - 2:
                ph = "Follicular"
            elif d <= ov + 1:
                ph = "Ovulatory"
            else:
                ph = "Luteal"
            rows.append((day.normalize(), i + 1, L, d, L - d + 1, ph))
    lab = pd.DataFrame(rows, columns=["date", "cycle", "cycle_len", "cycle_day", "days_to_next", "phase"])
    return lab[(lab.date >= first_day) & (lab.date <= last_day)].reset_index(drop=True)


def daily_metrics(tx: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    p = tx[tx["type"] == "purchase"].copy()
    p["date"] = p.ts.dt.normalize()
    p["spend"] = -p.tutar
    p["hour"] = p.ts.dt.hour
    p["late"] = (p.hour >= 22) | (p.hour < 5)
    p["disc"] = p.category.isin(DISCRETIONARY)
    g = pd.DataFrame(index=days)
    g["spend_all"] = p.groupby("date").spend.sum()
    g["spend_disc"] = p[p.disc].groupby("date").spend.sum()
    g["n_purchases"] = p.groupby("date").size()
    g["n_late"] = p[p.late].groupby("date").size()
    g["n_delivery"] = p[p.category == "Food delivery"].groupby("date").size()
    g["spend_cafe"] = p[p.category == "Cafe"].groupby("date").spend.sum()
    g = g.fillna(0.0)
    # winsorise heavy tails (one-off flights, tickets) at the 99th percentile
    for c in ["spend_all", "spend_disc"]:
        g[c + "_w"] = g[c].clip(upper=g[c].quantile(0.99))
    g.index.name = "date"
    return g.reset_index()


def paired_cycle_test(df: pd.DataFrame, metric: str, a="Luteal", b="Follicular"):
    m = df.pivot_table(index="cycle", columns="phase", values=metric, aggfunc="mean")
    m = m[[a, b]].dropna()
    diff = (m[a] - m[b]).values
    boot = [RNG.choice(diff, len(diff)).mean() for _ in range(10000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    try:
        w = stats.wilcoxon(diff).pvalue
    except ValueError:
        w = np.nan
    return m, diff, lo, hi, w


def rotation_p(df: pd.DataFrame, metric: str, a="Luteal", b="Follicular"):
    lab = df.phase.values
    y = df[metric].values
    def stat(l):
        return y[l == a].mean() - y[l == b].mean()
    obs = stat(lab)
    n = len(lab)
    null = np.array([stat(np.roll(lab, k)) for k in range(14, n - 14)])  # skip near-identity shifts
    return obs, (np.abs(null) >= abs(obs)).mean()


def main() -> None:
    tx = pd.read_csv(TX, parse_dates=["ts"])
    first, last = tx.ts.min().normalize(), tx.ts.max().normalize()
    lab = label_days(first, last)
    days = pd.DatetimeIndex(lab.date)
    met = daily_metrics(tx, days)
    df = lab.merge(met, on="date")
    print(f"labelled days: {len(df)}  ({df.date.min().date()} .. {df.date.max().date()})  cycles: {df.cycle.nunique()}")
    print(f"unlabelled tail (no cycle info): {(last - df.date.max()).days} days")

    # ---- descriptive: phase level
    metrics = {"spend_disc_w": "Discretionary spend / day (TL, winsorised)",
               "spend_all_w": "All card spend / day (TL, winsorised)",
               "n_purchases": "Purchases / day",
               "n_late": "Late-night purchases / day (22:00-05:00)",
               "n_delivery": "Food-delivery orders / day",
               "spend_cafe": "Cafe spend / day (TL)"}
    ph = df.groupby("phase")[list(metrics)].mean().reindex(PHASES)
    ph.insert(0, "days", df.groupby("phase").size().reindex(PHASES))
    ph.round(3).to_csv(AGG / "phase_summary.csv")
    print(ph.round(2).to_string())

    # ---- inferential: luteal vs follicular, cycle-level
    res, cyc_tables = [], {}
    for m in metrics:
        tab, diff, lo, hi, w = paired_cycle_test(df, m)
        obs, p_rot = rotation_p(df, m)
        res.append(dict(metric=m, n_cycles=len(diff), luteal_mean=tab["Luteal"].mean(),
                        follicular_mean=tab["Follicular"].mean(), mean_diff=diff.mean(),
                        ci95_lo=lo, ci95_hi=hi, wilcoxon_p=w, rotation_p=p_rot,
                        cycles_luteal_higher=int((diff > 0).sum())))
        cyc_tables[m] = tab
    r = pd.DataFrame(res)
    # Holm correction over the 6 metrics (on rotation p)
    order = r.rotation_p.argsort().values
    holm = np.empty(len(r))
    prev = 0
    for rank, idx in enumerate(order):
        adj = min(1.0, (len(r) - rank) * r.rotation_p.iloc[idx])
        prev = max(prev, adj)
        holm[idx] = prev
    r["rotation_p_holm"] = holm
    r.round(4).to_csv(AGG / "luteal_vs_follicular_tests.csv", index=False)
    print(r.round(3).to_string())
    pd.concat({m: t for m, t in cyc_tables.items()}, axis=1).round(2).to_csv(AGG / "cycle_level_means.csv")

    # ---- robustness: remove slow seasonal drift (29-day centred rolling mean), repeat the tests
    rob = []
    for m in metrics:
        df[m + "_dt"] = df[m] - df[m].rolling(29, center=True, min_periods=15).mean()
        tab, diff, lo, hi, w = paired_cycle_test(df, m + "_dt")
        obs, p_rot = rotation_p(df, m + "_dt")
        rob.append(dict(metric=m, mean_diff_detrended=diff.mean(), ci95_lo=lo, ci95_hi=hi,
                        wilcoxon_p=w, rotation_p=p_rot, cycles_luteal_higher=int((diff > 0).sum())))
    rob = pd.DataFrame(rob)
    rob.round(4).to_csv(AGG / "robustness_detrended.csv", index=False)
    print("\nDETRENDED (seasonality removed)"); print(rob.round(3).to_string())

    # ---- 4 phases, Kruskal-Wallis (descriptive only: days are autocorrelated)
    kw = {m: stats.kruskal(*[g[m].values for _, g in df.groupby("phase")]).pvalue for m in metrics}
    pd.Series(kw, name="kruskal_p").round(4).to_csv(AGG / "kruskal_by_phase.csv")

    # ---- figures
    spend = tx[tx["type"] == "purchase"].copy()
    spend["spend"] = -spend.tutar
    cat = spend.groupby("category").spend.sum().sort_values()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(cat.index, cat.values / 1000, color=ACCENT, height=0.6)
    ax.set_xlabel("Total card spend over 12 months (thousand TL)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Where the money went (card purchases)", loc="left", fontweight="bold")
    fig.savefig(FIG / "01_categories.png"); plt.close(fig)

    hr = spend.groupby(spend.ts.dt.hour).size().reindex(range(24), fill_value=0)
    fig, ax = plt.subplots(figsize=(7, 3.4))
    ax.bar(hr.index, hr.values, color=[ACCENT if (h >= 22 or h < 5) else "#9fb8b8" for h in hr.index], width=0.75)
    ax.set_xlabel("Hour of day"); ax.set_ylabel("Purchases")
    ax.set_title("When I pay (dark = late-night window 22:00-05:00)", loc="left", fontweight="bold")
    ax.set_xticks(range(0, 24, 3)); ax.grid(axis="x", visible=False)
    fig.savefig(FIG / "02_hour_of_day.png"); plt.close(fig)

    sel = ["spend_disc_w", "n_late", "spend_cafe"]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
    for ax, m in zip(axes, sel):
        mean = df.groupby("phase")[m].mean().reindex(PHASES)
        ax.bar(PHASES, mean.values, color=ACCENT, width=0.6)
        ax.set_title(metrics[m].split(" (")[0], fontsize=9.5, loc="left", fontweight="bold")
        ax.tick_params(axis="x", labelrotation=30, labelsize=8.5)
        ax.grid(axis="x", visible=False)
    fig.suptitle("Daily averages by cycle phase", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "03_phase_means.png"); plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    for ax, m in zip(axes, sel):
        t = cyc_tables[m]
        for _, row in t.iterrows():
            ax.plot([0, 1], [row["Follicular"], row["Luteal"]], color="#b9c4cc", lw=1, marker="o", ms=4,
                    markerfacecolor="white", markeredgecolor=MUTED)
        ax.plot([0, 1], [t["Follicular"].mean(), t["Luteal"].mean()], color=ACCENT, lw=2.4, marker="o", ms=7)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["Follicular", "Luteal"]); ax.set_xlim(-0.3, 1.3)
        ax.set_title(metrics[m].split(" (")[0], fontsize=9.5, loc="left", fontweight="bold")
        ax.grid(axis="x", visible=False)
    fig.suptitle("Each line = one cycle (thick = average of cycles)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "04_cycle_pairs.png"); plt.close(fig)

    near = df[df.days_to_next <= 14].groupby("days_to_next")["spend_disc_w"].agg(["mean", "sem"]).sort_index(ascending=False)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    x = -near.index.values
    ax.fill_between(x, near["mean"] - 1.96 * near["sem"], near["mean"] + 1.96 * near["sem"], color=ACCENT, alpha=0.15, lw=0)
    ax.plot(x, near["mean"], color=ACCENT, lw=2)
    ax.set_xlabel("Days before the next period starts (-1 = last day of cycle)")
    ax.set_ylabel("Discretionary spend / day (TL)")
    ax.set_title("Spending in the 14 days before a period (mean +/- 95% band)", loc="left", fontweight="bold")
    fig.savefig(FIG / "05_pre_period_curve.png"); plt.close(fig)


if __name__ == "__main__":
    main()
