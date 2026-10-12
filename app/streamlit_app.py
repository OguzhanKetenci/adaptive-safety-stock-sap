"""Adaptive Safety Stock for SAP MM - interactive demo.

Run:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_ss import costs, data_gen, methods, sap_export, simulation  # noqa: E402

st.set_page_config(page_title="Adaptive Safety Stock for SAP", page_icon="📦", layout="wide")

# Fixed colour per method (entity), never by rank. Validated reference palette.
COLORS = {
    "adaptive": "#2a78d6",
    "static": "#eb6834",
    "rolling": "#1baf7a",
    "ewma": "#4a3aa7",
    "empirical": "#e87ba4",
    "demand": "#9a9893",
}
LABEL = methods.METHOD_LABELS
ALL_METHODS = ["static", "rolling", "ewma", "empirical", "adaptive"]
PAGES = ["Overview", "Material drill-down", "Step-by-step replay", "SAP export", "About & SAP fields"]
SPEEDS = {"0.5 day/s": 0.5, "1 day/s (slow)": 1.0, "2 days/s": 2.0, "5 days/s": 5.0,
          "10 days/s": 10.0, "30 days/s": 30.0}


# ---------------------------------------------------------------------------
# Cached computation
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Generating SAP-like data ...")
def get_base_data() -> data_gen.Dataset:
    return data_gen.generate()


def dataset_with_targets(sl_matrix: tuple) -> data_gen.Dataset:
    """Dataset with service levels taken from the (possibly edited) segment matrix."""
    ds = get_base_data()
    m = {abc: dict(zip("XYZ", row)) for abc, row in zip("ABC", sl_matrix)}
    meta = ds.meta.copy()
    meta["service_level"] = [m[a][x] for a, x in zip(meta["ABC"], meta["XYZ"])]
    return dataclasses.replace(ds, meta=meta)


@st.cache_resource(show_spinner="Simulating 30 materials x 4 methods ...", max_entries=8)
def run_simulation(cfg: simulation.SimConfig, sl_matrix: tuple):
    ds = dataset_with_targets(sl_matrix)
    return simulation.run_all(ds, cfg)


def get_kpis(cfg, sl_matrix, cost_params) -> pd.DataFrame:
    ds = dataset_with_targets(sl_matrix)
    return costs.kpi_table(run_simulation(cfg, sl_matrix), ds.meta, cost_params, cfg.warmup)


def series(results, matnr: str, method: str) -> pd.DataFrame:
    if method == "adaptive":
        method = get_base_data().meta.set_index("MATNR").loc[matnr, "adaptive_method"]
    return results[(matnr, method)].daily


def eur(x: float) -> str:
    return f"€{x:,.0f}"


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def sidebar():
    st.sidebar.title("📦 Adaptive Safety Stock")
    page = st.sidebar.radio("Page", PAGES, key="page")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Parameters")
    with st.sidebar.expander("Service level targets (ABC x XYZ)", expanded=False):
        st.caption("Target cycle service level per segment. Edit to override.")
        default = pd.DataFrame(methods.SERVICE_LEVEL_MATRIX).T[["X", "Y", "Z"]]
        edited = st.data_editor(
            default, key="sl_editor", use_container_width=True,
            column_config={c: st.column_config.NumberColumn(c, min_value=0.5, max_value=0.999,
                                                            step=0.01, format="%.3f")
                           for c in "XYZ"})
        sl_matrix = tuple(tuple(float(v) for v in edited.loc[a, ["X", "Y", "Z"]]) for a in "ABC")

    with st.sidebar.expander("Recalculation", expanded=True):
        window = st.slider("Demand history window (days)", 30, 180, 90, step=10,
                           help="Rolling-window length. Empirical method uses max(window, 180).")
        review = st.select_slider("Review frequency (days)", [1, 7, 14, 30], value=7,
                                  help="How often the background job recalculates EISBE.")
        alpha = st.slider("EWMA smoothing α", 0.01, 0.30, 0.05, step=0.01)
        lost = st.radio("Unmet demand", ["Lost sales", "Backorder"], horizontal=True) == "Lost sales"

    with st.sidebar.expander("Cost parameters", expanded=True):
        hold = st.slider("Holding cost (% of unit value / year)", 5, 40, 20) / 100
        so = st.slider("Stockout cost per unit (% of unit value)", 10, 200, 50, step=10) / 100
        order = st.number_input("Ordering cost per PO (€)", 0.0, 1000.0, 50.0, step=10.0)

    cfg = simulation.SimConfig(window=window, review_every=review, ewma_alpha=alpha,
                               lost_sales=lost)
    return page, cfg, sl_matrix, costs.CostParams(hold, so, order)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def _layout(fig: go.Figure, title: str, y: str, height: int = 330) -> go.Figure:
    fig.update_layout(title=dict(text=title, x=0, font=dict(size=15)), height=height,
                      margin=dict(l=10, r=10, t=45, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"),
                      yaxis_title=y, xaxis_title="Day")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", zeroline=False)
    return fig


def _markers(fig: go.Figure, cfg: simulation.SimConfig, pattern: str):
    fig.add_vrect(x0=0, x1=cfg.warmup, fillcolor="rgba(128,128,128,0.10)", line_width=0,
                  annotation_text="warm-up", annotation_position="top left")
    if pattern == "regime_shift":
        fig.add_vline(x=data_gen.SHIFT_DAY, line_dash="dot", line_color="#888",
                      annotation_text="regime shift", annotation_position="top right")


def demand_chart(d: pd.Series, cfg, pattern, x_range=None) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(x=d.index, y=d.values, name="Daily demand", marker_color=COLORS["demand"],
                marker_line_width=0, opacity=0.55)
    fig.add_scatter(x=d.index, y=d.rolling(28, min_periods=1).mean(), name="28-day average",
                    line=dict(color="#52514e", width=2))
    _markers(fig, cfg, pattern)
    if x_range:
        fig.update_xaxes(range=x_range)
    return _layout(fig, "Demand (consumption)", "Units / day", 280)


def method_lines(results, matnr, meths, col, title, ytitle, cfg, pattern, upto=None,
                 x_range=None, step=False) -> go.Figure:
    fig = go.Figure()
    for m in meths:
        s = series(results, matnr, m)[col]
        if upto is not None:
            s = s.iloc[:upto + 1]
        fig.add_scatter(x=s.index, y=s.values, name=LABEL[m], mode="lines",
                        line=dict(color=COLORS[m], width=2, shape="hv" if step else "linear"))
    _markers(fig, cfg, pattern)
    if x_range:
        fig.update_xaxes(range=x_range)
    return _layout(fig, title, ytitle)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_overview(cfg, sl_matrix, cp):
    ds = dataset_with_targets(sl_matrix)
    kpis = get_kpis(cfg, sl_matrix, cp)
    h = costs.headline(kpis)
    summ = costs.summary_by_method(kpis)

    st.title("Adaptive safety stock vs. static SAP settings")
    st.markdown(
        "In many SAP systems the safety stock **MARC-EISBE** is set once and then left alone. "
        "This demo replays 18 months of daily demand for 30 materials and compares the static "
        "setting with safety stocks that are **recalculated every "
        f"{cfg.review_every} days** from recent consumption and actual supplier lead times. "
        f"The KPIs exclude the first {cfg.warmup} warm-up days.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cost – static", eur(h["static_cost"]))
    c2.metric("Total cost – adaptive", eur(h["adaptive_cost"]),
              f"{-h['savings_pct']:.0%} vs static", delta_color="inverse")
    c3.metric("Fill rate", f"{h['adaptive_fill']:.1%}",
              f"{(h['adaptive_fill'] - h['static_fill']) * 100:+.1f} pp vs static")
    c4.metric("Avg. inventory value", eur(h["adaptive_inv"]),
              f"{h['adaptive_inv'] / h['static_inv'] - 1:+.0%} vs static", delta_color="inverse")

    verdict = "saves" if h["savings"] > 0 else "costs an extra"
    st.info(
        f"**Headline:** the adaptive approach {verdict} **{eur(abs(h['savings']))}** "
        f"({abs(h['savings_pct']):.0%} of total cost) over the evaluation period. It raises fill "
        f"rate from {h['static_fill']:.1%} to {h['adaptive_fill']:.1%} while average inventory "
        f"value changes by {h['adaptive_inv'] / h['static_inv'] - 1:+.0%}. In other words, the stock is "
        "moved to the materials whose demand has actually changed.")

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("Cost by method")
        order = ["static", "rolling", "ewma", "empirical", "adaptive"]
        fig = go.Figure()
        for comp, color in [("holding_cost", "#2a78d6"), ("stockout_cost", "#eb6834"),
                            ("ordering_cost", "#9a9893")]:
            fig.add_bar(y=[LABEL[m] for m in order], x=summ.loc[order, comp], orientation="h",
                        name=comp.replace("_", " ").capitalize(), marker_color=color,
                        marker_line_color="rgba(0,0,0,0)",
                        hovertemplate="%{y}<br>%{x:,.0f} €<extra>" + comp.split("_")[0] + "</extra>")
        fig.update_layout(barmode="stack", height=340, margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
                          xaxis_title="€ over evaluation period",
                          bargap=0.35)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
        tbl = summ.loc[order].rename(index=LABEL)[["total_cost", "fill_rate", "cycle_service_level",
                                                     "stockout_days", "inventory_value", "orders"]]
        st.dataframe(tbl.style.format({"total_cost": "€{:,.0f}", "fill_rate": "{:.1%}",
                                       "cycle_service_level": "{:.1%}", "inventory_value": "€{:,.0f}",
                                       "stockout_days": "{:,.0f}", "orders": "{:,.0f}"}),
                     use_container_width=True)
    with right:
        st.subheader("Segment matrix (ABC × XYZ)")
        st.caption("Number of materials, target service level, and savings of adaptive vs static.")
        imp = costs.impact_by_material(kpis).join(ds.meta.set_index("MATNR")[["ABC", "XYZ", "service_level"]])
        z, text = [], []
        for a in "ABC":
            zr, tr = [], []
            for x in "XYZ":
                cell = imp[(imp["ABC"] == a) & (imp["XYZ"] == x)]
                sl = dict(zip("XYZ", sl_matrix["ABC".index(a)]))[x]
                sav = cell["savings"].sum()
                zr.append(sav if len(cell) else np.nan)
                tr.append(f"<b>{a}{x}</b><br>{len(cell)} mat. · SL {sl:.0%}<br>"
                          + (f"{'+' if sav < 0 else '−'}{eur(abs(sav))}" if len(cell) else "—"))
            z.append(zr)
            text.append(tr)
        lim = np.nanmax(np.abs(np.array(z, dtype=float)))
        fig = go.Figure(go.Heatmap(
            z=z, x=["X (stable)", "Y (variable)", "Z (erratic)"], y=["A (high value)", "B", "C (low value)"],
            text=text, texttemplate="%{text}", colorscale=[[0, "#e34948"], [0.5, "#f1f0ec"], [1, "#2a78d6"]],
            zmin=-lim, zmax=lim, showscale=False, xgap=3, ygap=3,
            hovertemplate="%{y} / %{x}<br>savings: %{z:,.0f} €<extra></extra>"))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Blue = adaptive cheaper, red = adaptive more expensive. "
                   "“−€” is a cost reduction.")

    st.subheader("Where the difference comes from")
    c1, c2 = st.columns(2)
    by_pat = kpis.pivot_table(index="pattern", columns="method", values="total_cost", aggfunc="sum")
    by_pat = by_pat[["static", "adaptive"]].sort_values("static", ascending=False)
    with c1:
        fig = go.Figure()
        for m in ["static", "adaptive"]:
            fig.add_bar(x=by_pat.index.str.replace("_", " "), y=by_pat[m], name=LABEL[m],
                        marker_color=COLORS[m], hovertemplate="%{x}: %{y:,.0f} €<extra>" + LABEL[m] + "</extra>")
        fig.update_layout(barmode="group", height=330, margin=dict(l=10, r=10, t=30, b=10),
                          title=dict(text="Total cost by demand pattern", x=0, font=dict(size=15)),
                          legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right"),
                          yaxis_title="€", bargap=0.3, bargroupgap=0.08)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown(
            "- **Growth and regime-shift** items drive the savings. The static safety stock is sized for "
            "demand that no longer exists, so stockouts pile up.\n"
            "- **Declining** items carry too much stock under the static setting, and adaptive releases it.\n"
            "- **Stable and intermittent** items show little benefit and can even get worse, because "
            "recalculating adds estimation noise. That is why the export has a dead band and a "
            "planner-approval step instead of posting every change.")

    st.subheader("Top materials by impact")
    imp_show = imp.join(ds.mara.set_index("MATNR")["MAKTX"])
    cols = ["MAKTX", "WERKS", "pattern", "segment", "static", "adaptive", "savings"]
    fmt = {"static": "€{:,.0f}", "adaptive": "€{:,.0f}", "savings": "€{:,.0f}"}
    t1, t2 = st.tabs(["Largest savings", "Where adaptive costs more"])
    t1.dataframe(imp_show[cols].head(10).style.format(fmt), use_container_width=True)
    t2.dataframe(imp_show[cols].sort_values("savings").head(5).style.format(fmt),
                 use_container_width=True)


def _material_picker(key: str, default_pattern: str = "growth", nth: int = 0) -> str:
    ds = get_base_data()
    info = ds.meta.merge(ds.mara, on="MATNR")
    labels = {r.MATNR: f"{r.MATNR} – {r.MAKTX}  ({r.pattern.replace('_', ' ')}, {r.segment})"
              for r in info.itertuples()}
    mats = list(labels)
    default = int(np.flatnonzero(info["pattern"].to_numpy() == default_pattern)[nth])
    return st.selectbox("Material", mats, index=default, format_func=labels.get, key=key)


def page_drilldown(cfg, sl_matrix, cp):
    ds = dataset_with_targets(sl_matrix)
    results = run_simulation(cfg, sl_matrix)
    st.title("Material drill-down")
    c1, c2 = st.columns([2, 3])
    with c1:
        matnr = _material_picker("drill_mat")
    row = ds.meta.set_index("MATNR").loc[matnr]
    with c2:
        meths = st.multiselect("Methods", ALL_METHODS, default=["static", "adaptive"],
                               format_func=LABEL.get, key="drill_methods")
    marc = ds.marc.set_index("MATNR").loc[matnr]
    st.caption(f"Plant {row.WERKS} · segment {row.segment} · target service level "
               f"{row.service_level:.0%} · unit value €{row.price:,.2f} · PLIFZ {row.PLIFZ} d "
               f"(actual ≈ {row.lt_mean_true:.1f} d) · current MARC: EISBE {marc.EISBE}, "
               f"MINBE {marc.MINBE}, BSTFE {marc.BSTFE} · adaptive method: {LABEL[row.adaptive_method]}")
    if not meths:
        st.warning("Select at least one method.")
        return
    d = series(results, matnr, "static")["demand"]
    st.plotly_chart(demand_chart(d, cfg, row.pattern), use_container_width=True)
    st.plotly_chart(method_lines(results, matnr, meths, "on_hand", "On-hand inventory",
                                 "Units", cfg, row.pattern), use_container_width=True)
    st.plotly_chart(method_lines(results, matnr, meths, "ss", "Safety stock (EISBE) over time",
                                 "Units", cfg, row.pattern, step=True), use_container_width=True)

    kpis = get_kpis(cfg, sl_matrix, cp)
    k = kpis[kpis["MATNR"] == matnr].set_index("method").loc[meths]
    k = k.rename(index=LABEL)[["fill_rate", "cycle_service_level", "stockout_days", "avg_inventory",
                               "holding_cost", "stockout_cost", "ordering_cost", "total_cost", "final_ss"]]
    st.dataframe(k.style.format({"fill_rate": "{:.1%}", "cycle_service_level": "{:.1%}",
                                 "avg_inventory": "{:,.0f}", "holding_cost": "€{:,.0f}",
                                 "stockout_cost": "€{:,.0f}", "ordering_cost": "€{:,.0f}",
                                 "total_cost": "€{:,.0f}", "final_ss": "{:,.0f}"}),
                 use_container_width=True)


def page_replay(cfg, sl_matrix, cp):
    ds = dataset_with_targets(sl_matrix)
    results = run_simulation(cfg, sl_matrix)
    n = ds.n_days
    ss_ = st.session_state
    ss_.setdefault("replay_day", 0)
    ss_.setdefault("playing", False)
    ss_.setdefault("last_tick", 0.0)

    st.title("Step-by-step replay")
    st.caption("Watch the planning logic day by day: demand comes in, goods are issued, purchase "
               "orders are placed when the inventory position falls to the reorder point, and the "
               "adaptive method recalculates its safety stock on review days.")
    c1, c2 = st.columns([3, 2])
    with c1:
        matnr = _material_picker("replay_mat", default_pattern="regime_shift", nth=1)  # demand up-shift
    with c2:
        speed_label = st.select_slider("Speed", list(SPEEDS), value="1 day/s (slow)", key="speed")
    row = ds.meta.set_index("MATNR").loc[matnr]

    b1, b2, b3, b4, b5 = st.columns([1, 1, 1, 1, 3])
    if b1.button("▶ Play", use_container_width=True, disabled=ss_.playing):
        ss_.playing = True
        ss_.last_tick = time.time()
    if b2.button("⏸ Pause", use_container_width=True, disabled=not ss_.playing):
        ss_.playing = False
    if b3.button("⏭ Next day", use_container_width=True):
        ss_.playing = False
        ss_.replay_day = min(n - 1, ss_.replay_day + 1)
    if b4.button("⏮ Reset", use_container_width=True):
        ss_.playing = False
        ss_.replay_day = 0
    with b5:
        jump = st.number_input("Jump to day", 0, n - 1, value=int(ss_.replay_day), step=10,
                               key=f"jump_{ss_.replay_day}")
        if jump != ss_.replay_day:
            ss_.replay_day = int(jump)
            ss_.playing = False

    interval = 1.0 / SPEEDS[speed_label]
    meths = ["static", "adaptive"]

    @st.fragment(run_every=interval if ss_.playing else None)
    def board():
        if ss_.playing:
            # advance by wall-clock time so the speed holds even when rendering is slow
            steps = int((time.time() - ss_.last_tick) / interval + 0.2)
            if steps >= 1:
                ss_.replay_day = min(n - 1, ss_.replay_day + steps)
                ss_.last_tick += steps * interval
            if ss_.replay_day >= n - 1:
                ss_.playing = False
        t = int(ss_.replay_day)
        st.progress((t + 1) / n, text=f"Day {t} of {n - 1} · "
                    f"{(data_gen.START_DATE + pd.Timedelta(days=t)):%a %d %b %Y}"
                    + (" · ▶ playing" if ss_.playing else " · ⏸ paused"))
        x_range = [max(0, t - 119) - 0.5, max(120, t + 1) + 0.5]

        cols = st.columns(2)
        for col, m in zip(cols, meths):
            d = series(results, matnr, m)
            today = d.iloc[t]
            so_units = d["unmet"].iloc[cfg.warmup:t + 1].sum() if t >= cfg.warmup else 0
            with col:
                st.markdown(f"**{LABEL[m]}**")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("On hand", f"{today.on_hand:,.0f}")
                k2.metric("Open POs", f"{today.pipeline:,.0f}")
                k3.metric("Safety stock", f"{today.ss:,.0f}",
                          f"{today.ss - d['ss'].iloc[t - 1]:+,.0f}" if t and today.ss != d["ss"].iloc[t - 1] else None)
                k4.metric("Unmet units*", f"{so_units:,.0f}")
                events = [f"demand {today.demand:,.0f}, issued {today.served:,.0f}"]
                if today.unmet > 0:
                    events.append(f"🔴 **stockout: {today.unmet:,.0f} units not served**")
                if today.receipt_qty > 0:
                    events.append(f"📥 goods receipt {today.receipt_qty:,.0f}")
                if today.order_qty > 0:
                    events.append(f"📝 PO placed for {today.order_qty:,.0f} (IP ≤ ROP {today.rop:,.0f})")
                if t and today.ss != d["ss"].iloc[t - 1]:
                    events.append(f"🔄 EISBE recalculated {d['ss'].iloc[t - 1]:,.0f} → {today.ss:,.0f}")
                st.markdown("Today: " + " · ".join(events))

        fig = go.Figure()
        for m in meths:
            d = series(results, matnr, m).iloc[:t + 1]
            fig.add_scatter(x=d.index, y=d["on_hand"], name=f"On hand – {LABEL[m]}",
                            line=dict(color=COLORS[m], width=2))
            fig.add_scatter(x=d.index, y=d["rop"], name=f"Reorder point – {LABEL[m]}",
                            line=dict(color=COLORS[m], width=1.5, dash="dot", shape="hv"))
        _markers(fig, cfg, row.pattern)
        fig.add_vline(x=t, line_color="#52514e", line_width=1)
        fig.update_xaxes(range=x_range)
        st.plotly_chart(_layout(fig, "Inventory and reorder point (last 120 days)", "Units", 360),
                        use_container_width=True, key=f"replay_inv_{t}")
        dem = series(results, matnr, "static")["demand"].iloc[:t + 1]
        st.plotly_chart(demand_chart(dem, cfg, row.pattern, x_range),
                        use_container_width=True, key=f"replay_dem_{t}")
        st.caption("*Unmet units are counted after the warm-up period only.")

    board()


def page_export(cfg, sl_matrix, cp):
    ds = dataset_with_targets(sl_matrix)
    st.title("SAP export – proposed EISBE changes")
    st.markdown(
        "This is what the weekly background job would propose today, compared with the values "
        "currently in MARC. Changes under **5 %** are ignored (dead band). Changes up to **±30 %** are "
        "posted automatically via MM17/LSMW. Anything larger goes to the responsible MRP "
        "controller (DISPO) as **needs planner approval**.")
    prop = sap_export.build_proposals(ds, cfg).merge(ds.mara[["MATNR", "MAKTX"]], on="MATNR")
    counts = prop["STATUS"].value_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Auto-update", int(counts.get(sap_export.STATUS_AUTO, 0)))
    c2.metric("Needs planner approval", int(counts.get(sap_export.STATUS_APPROVAL, 0)))
    c3.metric("No change (dead band)", int(counts.get(sap_export.STATUS_NO_CHANGE, 0)))
    st.caption("Note: this is the *first* run after 16 months of static settings, so many items need "
               "approval. In normal weekly operation the changes are small and mostly automatic.")

    st.subheader("Planner approval")
    st.caption("Approve or reject the large changes. Approved rows are added to the MM17 upload file.")
    prop["DECISION"] = np.where(prop["STATUS"] == sap_export.STATUS_APPROVAL, "Pending", "—")
    show = ["MATNR", "MAKTX", "WERKS", "DISPO", "EISBE_OLD", "EISBE_NEW", "CHANGE_PCT",
            "MINBE_OLD", "MINBE_NEW", "REASON", "STATUS", "DECISION"]
    edited = st.data_editor(
        prop[show], key="approval_editor", hide_index=True, use_container_width=True,
        disabled=[c for c in show if c != "DECISION"],
        column_config={
            "DECISION": st.column_config.SelectboxColumn("Planner decision",
                                                         options=["—", "Pending", "Approve", "Reject"]),
            "CHANGE_PCT": st.column_config.NumberColumn("Change %", format="%.1f"),
            "REASON": st.column_config.TextColumn("Reason", width="large"),
        })
    approved = edited["DECISION"].eq("Approve") & edited["STATUS"].eq(sap_export.STATUS_APPROVAL)
    final = prop.copy()
    final.loc[approved.values, "STATUS"] = sap_export.STATUS_AUTO
    upload = sap_export.mm17_upload(final)

    st.subheader("Downloads")
    d1, d2 = st.columns(2)
    d1.download_button("⬇ Full proposal list (planner review)",
                       sap_export.to_csv(prop[sap_export.EXPORT_COLUMNS]),
                       file_name="eisbe_proposals.csv", mime="text/csv", use_container_width=True)
    d2.download_button(f"⬇ MM17 / LSMW upload file ({len(upload)} rows)",
                       sap_export.to_csv(upload), file_name="mm17_eisbe_upload.csv",
                       mime="text/csv", use_container_width=True)
    with st.expander("Preview MM17 upload file"):
        st.code(sap_export.to_csv(upload) or "(empty)", language="text")


def page_about():
    st.title("About this demo")
    st.markdown("""
**Problem.** The safety stock in SAP MM (`MARC-EISBE`) is usually set once and then forgotten.
When demand grows, shrinks or becomes more volatile, a static value leads either to stockouts or
to excess inventory.

**Approach.** A scheduled job recalculates the safety stock from recent consumption and from actual
supplier lead times (PO date to goods receipt). The target service level comes from the ABC × XYZ
segment. Small changes are posted automatically; large ones go to the MRP controller for approval.

**SAP objects used (synthetic data, same field names):**

| Table | Fields | Used for |
|---|---|---|
| MARA | MATNR, MAKTX, MEINS | material master |
| MARC | MATNR, WERKS, DISMM, DISPO, EISBE, MINBE, BSTFE, PLIFZ | current settings, update target |
| MSEG / MVER | goods issues (daily), GSVBR (monthly) | demand mean and variability |
| EKKO / EKPO / EKBE | BEDAT, MATNR, WERKS, BUDAT (GR, BWART 101) | actual lead time and its variability |

**Methods compared:** static (SAP as-is), rolling window, EWMA, and empirical percentile (for
intermittent demand). The "adaptive" result uses the rolling window for regular items and the
empirical percentile for intermittent items. This choice is made before the simulation.

**Limitations:** synthetic data, single echelon, no capacity or MOQ constraints, consumption equals
demand (no censoring), no forecast-based planning.
""")
    ds = get_base_data()
    t1, t2, t3 = st.tabs(["MARC (current)", "MARA", "EKKO (first rows)"])
    t1.dataframe(ds.marc, hide_index=True, use_container_width=True)
    t2.dataframe(ds.mara, hide_index=True, use_container_width=True)
    t3.dataframe(ds.ekko.head(20), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
def main():
    page, cfg, sl_matrix, cp = sidebar()
    if page == "Overview":
        page_overview(cfg, sl_matrix, cp)
    elif page == "Material drill-down":
        page_drilldown(cfg, sl_matrix, cp)
    elif page == "Step-by-step replay":
        page_replay(cfg, sl_matrix, cp)
    elif page == "SAP export":
        page_export(cfg, sl_matrix, cp)
    else:
        page_about()


main()
