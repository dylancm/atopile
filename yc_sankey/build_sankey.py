#!/usr/bin/env python3
"""
Build a Sankey chart of all (current + past) Y Combinator companies, showing the
funding rounds they progressed through and how they ended up: still active,
acquired (sale), public (IPO), or inactive (shut down).

DATA MODEL
==========
Two kinds of numbers go into this chart and they are treated very differently:

1. OUTCOMES  -> REAL DATA.
   The four terminal buckets (Active / Acquired / Public / Inactive) come
   straight from YC's official public company directory (mirrored daily by the
   yc-oss/api project from YC's Algolia index). These totals are exact.

2. FUNDING ROUNDS -> ESTIMATES.
   YC does not publish per-company funding-round history, and the only
   comprehensive sources are paywalled (Crunchbase) or proprietary (Rebel Fund).
   So the Seed -> Series A -> Series B -> Series C+ progression is *modeled*
   from published aggregate graduation rates (see ASSUMPTIONS below). These are
   illustrative, not per-company facts.

To make the two consistent, we build a stage x outcome flow matrix and run
Iterative Proportional Fitting (IPF / "raking"): the matrix is forced so that
  - its COLUMN totals equal the REAL outcome counts, and
  - its ROW totals equal the MODELED "furthest round reached" counts,
starting from a plausible prior for how outcomes differ by stage. The result is
a single internally-consistent flow that respects the real outcomes exactly.

Every assumption below is a named constant -- change them and re-run.
"""

import collections
import json
import os

import plotly.graph_objects as go
import plotly.io as pio

# Static PNG export uses kaleido's headless chromium; running as root needs
# --no-sandbox. Harmless if kaleido v1+ ignores it.
try:
    pio.kaleido.scope.chromium_args = tuple(
        set(pio.kaleido.scope.chromium_args)
        | {"--no-sandbox", "--disable-gpu", "--single-process"}
    )
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "yc_companies_snapshot.json")

# ---------------------------------------------------------------------------
# 1. REAL DATA: outcome counts from YC's official directory
# ---------------------------------------------------------------------------
companies = json.load(open(DATA))
status_counts = collections.Counter(c.get("status") for c in companies)
TOTAL = len(companies)

# YC status -> our outcome label
OUTCOMES = ["Active", "Acquired", "Public", "Inactive"]
OUTCOME_LABEL = {
    "Active": "Still operating\n(active / private)",
    "Acquired": "Exited: Acquired\n(sale)",
    "Public": "Exited: Public\n(IPO)",
    "Inactive": "Died\n(inactive / shut down)",
}
real_outcome = {o: status_counts.get(o, 0) for o in OUTCOMES}

# ---------------------------------------------------------------------------
# 2. ASSUMPTIONS (ESTIMATES): round-to-round graduation rates
#    Sources documented in README.md. Tweak freely.
# ---------------------------------------------------------------------------
# Fraction of companies at each round that advance to the *next* round.
SEED_TO_A = 0.45   # YC-specific (~45%, well above the ~30% market average)
A_TO_B = 0.60      # industry benchmark (~60%)
B_TO_C = 0.60      # industry benchmark (~60%)

ROUNDS = ["Seed", "Series A", "Series B", "Series C+"]

# Cumulative fraction of all companies that ever *reach* each round.
reach = {
    "Seed": 1.0,
    "Series A": SEED_TO_A,
    "Series B": SEED_TO_A * A_TO_B,
    "Series C+": SEED_TO_A * A_TO_B * B_TO_C,
}
# "Furthest round reached" = companies that reach round r but not the next one.
# (Series C+ is the terminal bucket: everyone who reaches it stays there.)
furthest_frac = {
    "Seed": reach["Seed"] - reach["Series A"],
    "Series A": reach["Series A"] - reach["Series B"],
    "Series B": reach["Series B"] - reach["Series C+"],
    "Series C+": reach["Series C+"],
}
furthest = {r: furthest_frac[r] * TOTAL for r in ROUNDS}

# Prior P(outcome | furthest round reached). Shape only -- IPF rescales it.
# Later-stage companies are less likely to die and more likely to exit; IPOs
# are essentially confined to the latest stages.
PRIOR = {
    #            Active  Acquired  Public   Inactive
    "Seed":     [0.50,   0.10,     0.0005,  0.40],
    "Series A": [0.62,   0.20,     0.002,   0.18],
    "Series B": [0.66,   0.23,     0.01,    0.10],
    "Series C+":[0.60,   0.27,     0.08,    0.05],
}

# ---------------------------------------------------------------------------
# 3. RECONCILE via Iterative Proportional Fitting
#    rows = furthest round reached (modeled), cols = outcomes (real)
# ---------------------------------------------------------------------------
row_tot = [furthest[r] for r in ROUNDS]
col_tot = [real_outcome[o] for o in OUTCOMES]

# seed matrix from the prior
M = [[furthest[r] * PRIOR[r][j] for j in range(len(OUTCOMES))] for r in ROUNDS]

for _ in range(200):
    # scale rows
    for i in range(len(ROUNDS)):
        s = sum(M[i]) or 1.0
        f = row_tot[i] / s
        M[i] = [v * f for v in M[i]]
    # scale cols
    for j in range(len(OUTCOMES)):
        s = sum(M[i][j] for i in range(len(ROUNDS))) or 1.0
        f = col_tot[j] / s
        for i in range(len(ROUNDS)):
            M[i][j] *= f

# advance flows between rounds (the funnel narrowing)
advance = {
    "Seed": reach["Series A"] * TOTAL,
    "Series A": reach["Series B"] * TOTAL,
    "Series B": reach["Series C+"] * TOTAL,
}

# ---------------------------------------------------------------------------
# 4. Build the Sankey
# ---------------------------------------------------------------------------
# node order: 4 rounds, then 4 outcomes
node_labels = [
    f"{r}\n({reach[r]*TOTAL:,.0f} reach this round)" if r != "Seed"
    else f"Seed\n(all {TOTAL:,} YC companies)"
    for r in ROUNDS
] + [OUTCOME_LABEL[o] + f"\n{real_outcome[o]:,}" for o in OUTCOMES]

ROUND_IDX = {r: i for i, r in enumerate(ROUNDS)}
OUT_IDX = {o: len(ROUNDS) + j for j, o in enumerate(OUTCOMES)}

ROUND_COLOR = {
    "Seed": "#7e57c2", "Series A": "#5c6bc0",
    "Series B": "#42a5f5", "Series C+": "#26c6da",
}
OUT_COLOR = {
    "Active": "#66bb6a", "Acquired": "#ab47bc",
    "Public": "#ffca28", "Inactive": "#ef5350",
}
node_color = [ROUND_COLOR[r] for r in ROUNDS] + [OUT_COLOR[o] for o in OUTCOMES]

def rgba(hexc, a=0.40):
    h = hexc.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"

src, tgt, val, lcol, ltxt = [], [], [], [], []

# funnel: round -> next round
for r in ["Seed", "Series A", "Series B"]:
    nxt = ROUNDS[ROUNDS.index(r) + 1]
    src.append(ROUND_IDX[r]); tgt.append(ROUND_IDX[nxt]); val.append(advance[r])
    lcol.append(rgba(ROUND_COLOR[r], 0.55))
    ltxt.append(f"advanced from {r} to {nxt} (modeled)")

# round -> outcome (terminal at each stage)
for i, r in enumerate(ROUNDS):
    for j, o in enumerate(OUTCOMES):
        v = M[i][j]
        if v < 0.5:
            continue
        src.append(ROUND_IDX[r]); tgt.append(OUT_IDX[o]); val.append(v)
        lcol.append(rgba(OUT_COLOR[o], 0.38))
        ltxt.append(f"{r} -> {o}")

# explicit horizontal positions so the funnel reads left->right
node_x = [0.001, 0.18, 0.36, 0.54, 0.999, 0.999, 0.999, 0.999]
node_y = [0.55, 0.62, 0.70, 0.78, 0.10, 0.40, 0.62, 0.85]

fig = go.Figure(go.Sankey(
    arrangement="snap",
    node=dict(
        label=[l.replace("\n", "<br>") for l in node_labels],
        color=node_color,
        x=node_x, y=node_y,
        pad=22, thickness=24,
        line=dict(color="rgba(0,0,0,0.25)", width=0.5),
        hovertemplate="%{label}<br>%{value:,.0f} companies<extra></extra>",
    ),
    link=dict(
        source=src, target=tgt, value=val, color=lcol,
        customdata=ltxt,
        hovertemplate="%{customdata}<br>%{value:,.0f} companies<extra></extra>",
    ),
))

fig.update_layout(
    title=dict(
        text=(
            f"<b>Y Combinator: {TOTAL:,} companies (all batches, 2005-2026) "
            "through funding rounds and outcomes</b><br>"
            "<sub>Outcomes (right) are REAL from YC's official directory; "
            "funding-round flows (left) are MODELED estimates from published "
            "graduation rates - illustrative, not per-company facts.</sub>"
        ),
        x=0.5, xanchor="center", font=dict(size=20),
    ),
    font=dict(family="Inter, Helvetica, Arial, sans-serif", size=13, color="#222"),
    paper_bgcolor="white", plot_bgcolor="white",
    margin=dict(l=20, r=20, t=90, b=70),
    height=720, width=1300,
    annotations=[dict(
        x=0.5, y=-0.09, xref="paper", yref="paper", showarrow=False,
        font=dict(size=11, color="#888"),
        text=(
            "Source: yc-oss/api (mirror of YC's official Algolia directory). "
            "Round assumptions: Seed->A 45% (YC), A->B 60%, B->C 60% (industry benchmarks). "
            "Reconciled to real outcome totals via iterative proportional fitting. See README.md."
        ),
    )],
)

html_path = os.path.join(HERE, "yc_sankey.html")
png_path = os.path.join(HERE, "yc_sankey.png")
fig.write_html(html_path, include_plotlyjs="cdn")
fig.write_image(png_path, scale=2)

# ---------------------------------------------------------------------------
# 5. Transparency: print the numbers that went into the chart
# ---------------------------------------------------------------------------
print(f"Total YC companies: {TOTAL:,}")
print("\nREAL outcomes (from YC directory):")
for o in OUTCOMES:
    print(f"  {OUTCOME_LABEL[o].splitlines()[0]:24} {real_outcome[o]:>5,}")
print("\nMODELED 'furthest round reached':")
for r in ROUNDS:
    print(f"  {r:10} {furthest[r]:>8,.0f}   (reach: {reach[r]*TOTAL:>8,.0f})")
print("\nReconciled stage x outcome matrix (companies):")
hdr = " " * 12 + "".join(f"{o:>11}" for o in OUTCOMES)
print(hdr)
for i, r in enumerate(ROUNDS):
    print(f"  {r:10}" + "".join(f"{M[i][j]:>11,.0f}" for j in range(len(OUTCOMES))))
print(f"\nWrote:\n  {html_path}\n  {png_path}")
