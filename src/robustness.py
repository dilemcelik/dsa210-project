"""Step 3: is the cafe result just campus life? Re-test under alternative definitions.

Scenarios remove trip days, the stated campus break, summer, weekends, or look at
campus cafes only. Everything else (phase definitions, tests) is identical to analyze.py.
Output: data/aggregated/cafe_robustness.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze as A  # noqa: E402

TRIPS = [("2026-02-09", "2026-02-12"), ("2026-09-02", "2026-09-05")]   # abroad
BREAK = ("2026-06-11", "2026-06-28")                                      # between terms
SUMMER = ("2026-06-11", "2026-08-31")                                     # broad summer window


def in_ranges(dates: pd.Series, ranges) -> pd.Series:
    m = pd.Series(False, index=dates.index)
    for a, b in ranges:
        m |= (dates >= pd.Timestamp(a)) & (dates <= pd.Timestamp(b))
    return m


def rotation_masked(lab, y, keep, a="Luteal", b="Follicular"):
    def stat(l):
        sel_a, sel_b = (l == a) & keep, (l == b) & keep
        return y[sel_a].mean() - y[sel_b].mean()
    obs = stat(lab)
    null = np.array([stat(np.roll(lab, k)) for k in range(14, len(lab) - 14)])
    null = null[~np.isnan(null)]
    return obs, (np.abs(null) >= abs(obs)).mean()


def run(df, metric, keep, detrend):
    d = df.copy()
    y = d[metric].copy()
    if detrend:
        y = y - y.rolling(29, center=True, min_periods=15).mean()
    d["y"] = y
    sub = d[keep]
    tab = sub.pivot_table(index="cycle", columns="phase", values="y", aggfunc="mean")[["Luteal", "Follicular"]].dropna()
    diff = (tab["Luteal"] - tab["Follicular"]).values
    boot = [A.RNG.choice(diff, len(diff)).mean() for _ in range(10000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    w = stats.wilcoxon(diff).pvalue if len(diff) >= 6 and np.any(diff != 0) else np.nan
    obs, p_rot = rotation_masked(d.phase.values, d["y"].values, keep.values)
    return dict(n_cycles=len(diff), luteal_days=int((sub.phase == "Luteal").sum()),
                follicular_days=int((sub.phase == "Follicular").sum()),
                luteal_mean=tab["Luteal"].mean(), follicular_mean=tab["Follicular"].mean(),
                mean_diff=diff.mean(), ci95_lo=lo, ci95_hi=hi, wilcoxon_p=w, rotation_p=p_rot,
                cycles_luteal_lower=int((diff < 0).sum()))


def main():
    tx = pd.read_csv(A.TX, parse_dates=["ts"])
    lab = A.label_days(tx.ts.min().normalize(), tx.ts.max().normalize())
    df = lab.merge(A.daily_metrics(tx, pd.DatetimeIndex(lab.date)), on="date")
    p = tx[(tx["type"] == "purchase") & (tx.category == "Kafe")].copy()
    p["date"] = p.ts.dt.normalize()
    p["campus"] = p.merchant.str.upper().str.contains("SABANC")
    df["cafe_campus"] = df.date.map(-p[p.campus].groupby("date").tutar.sum()).fillna(0.0)
    df["cafe_other"] = df.date.map(-p[~p.campus].groupby("date").tutar.sum()).fillna(0.0)
    df["cafe_any"] = (df.spend_cafe > 0).astype(float)   # outlier-proof: did I buy a coffee at all?
    print(f"cafe purchases: {len(p)}  campus-name share: {p.campus.mean():.0%} (spend {-p[p.campus].tutar.sum():.0f} of {-p.tutar.sum():.0f} TL)")

    trip = in_ranges(df.date, TRIPS)
    brk = in_ranges(df.date, [BREAK])
    summer = in_ranges(df.date, [SUMMER])
    weekday = df.date.dt.dayofweek < 5
    allday = pd.Series(True, index=df.index)
    scen = [
        ("1 baseline (all days)", "spend_cafe", allday),
        ("2 without trip days", "spend_cafe", ~trip),
        ("3 without trips + stated break (11-28 Jun)", "spend_cafe", ~trip & ~brk),
        ("4 without trips + whole summer (Jun-Aug)", "spend_cafe", ~trip & ~summer),
        ("5 weekdays only, no trips/break", "spend_cafe", weekday & ~trip & ~brk),
        ("6 campus cafes only, no trips/break", "cafe_campus", ~trip & ~brk),
        ("7 NON-campus cafes only, no trips/break", "cafe_other", ~trip & ~brk),
        ("8 campus cafes, weekdays, no trips/summer", "cafe_campus", weekday & ~trip & ~summer),
        ("9 any cafe purchase (0/1), all days", "cafe_any", allday),
        ("10 any cafe purchase (0/1), no trips/break", "cafe_any", ~trip & ~brk),
        ("11 any cafe purchase (0/1), weekdays, no trips/break", "cafe_any", weekday & ~trip & ~brk),
    ]
    rows = []
    for name, metric, keep in scen:
        for dt in (False, True):
            r = run(df, metric, keep, dt)
            rows.append(dict(scenario=name, detrended=dt, **r))
    out = pd.DataFrame(rows)
    out.round(3).to_csv(A.AGG / "cafe_robustness.csv", index=False)
    pd.set_option("display.width", 250)
    print(out.drop(columns=["luteal_days", "follicular_days"]).round(2).to_string())
    print(out[["scenario", "detrended", "luteal_days", "follicular_days"]].drop_duplicates("scenario").to_string())


if __name__ == "__main__":
    main()
