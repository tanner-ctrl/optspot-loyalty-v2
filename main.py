import html as _html
import io
import os
import re
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="OptSpot Loyalty Analytics", layout="wide")

ACTION_LABELS = {
    "CHECKIN":  "Visited",
    "REDEEM":   "Redeemed Reward",
    "BONUS":    "Earned Bonus Points",
    "REFERRAL": "Referred a Friend",
    "JOINED":   "Joined Loyalty Program",
    "VISITED":  "Visited",
    "LOYALTY GOAL REACHED":    "Reached Loyalty Goal",
    "KIOSK ENTRY PROCESSED":   "Earned Points",
    "KIOSK ENTRY PROCESSED - RE-CALCULATE THE LOYALTY POINT BALANCE": "Earned Points",
}

SCHEMA_FIELDS = [
    "Location",
    "Mobile",
    "Action",
    "Date",
    "Time",
    "Points Awarded",
    "Total Points",
    "License Plate",
]

FILTER_DEFAULTS = {
    "filter_preset":      "All time",
    "filter_date_start":  None,
    "filter_date_end":    None,
    "filter_actions":     None,
    "filter_min_visits":  None,
    "filter_max_visits":  None,
    "filter_search":      "",
    "filter_reset_count": 0,
}


def resolve_action_label(raw):
    cleaned = _html.unescape(str(raw)).replace("\xa0", " ").strip().upper()
    return ACTION_LABELS.get(cleaned, str(raw).strip().title())


def render_action_distribution(df):
    st.subheader("What Are Customers Doing?")
    st.caption("Breakdown of every loyalty interaction by type.")

    raw_counts = df["Action"].value_counts()

    merged: dict = {}
    for raw, count in raw_counts.items():
        label = resolve_action_label(raw)
        merged[label] = merged.get(label, 0) + int(count)

    rows      = sorted(merged.items(), key=lambda x: x[1], reverse=True)
    total     = sum(c for _, c in rows)
    max_count = rows[0][1] if rows else 1

    parts = []
    for label, count in rows:
        pct       = count / total * 100 if total else 0
        bar_width = count / max_count * 100
        safe_lbl  = _html.escape(label)
        parts.append(f"""
        <div style="margin-bottom:14px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-weight:500;font-size:14px;">{safe_lbl}</span>
            <span style="color:#888;font-size:14px;">{count:,} ({pct:.1f}%)</span>
          </div>
          <div style="background:#e0e7ef;border-radius:4px;height:12px;">
            <div style="background:#1a4f7a;width:{bar_width:.1f}%;height:12px;border-radius:4px;"></div>
          </div>
        </div>""")

    parts.append(
        f'<p style="color:#888;font-size:13px;margin-top:8px;">Total actions: {total:,}</p>'
    )
    st.markdown("".join(parts), unsafe_allow_html=True)


def auto_match(file_cols, schema_field):
    for col in file_cols:
        if col.strip().lower() == schema_field.lower():
            return col
    return None


# Auto-load sample data once per session
if "loaded_data" not in st.session_state:
    sample_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data.csv")
    if os.path.exists(sample_path):
        st.session_state["loaded_data"] = pd.read_csv(sample_path)
        st.session_state["auto_loaded"] = True
    else:
        st.session_state["loaded_data"] = None
        st.session_state["auto_loaded"] = False


def render_status_line():
    df = st.session_state.get("loaded_data")
    if df is not None:
        st.caption(f"{len(df):,} records loaded")
    else:
        st.caption("No data loaded — upload a file to get started.")


# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.title("OptSpot Loyalty")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Retention", "Directory", "Dispatcher", "Import Files"],
)

if st.session_state.get("auto_loaded"):
    st.sidebar.caption("Sample data loaded automatically. Use Import Files to replace.")


# ── Page functions ────────────────────────────────────────────────────────────

def aggregate_visits(df, period):
    dates = pd.to_datetime(df["Date"], errors="coerce").dropna()

    if period == "Day":
        counts = dates.dt.date.value_counts().sort_index()
        labels = [pd.Timestamp(d).strftime("%b %-d") for d in counts.index]

    elif period == "Week":
        week_starts = (dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")).dt.normalize()
        counts = week_starts.value_counts().sort_index()
        labels = [f"Week of {d.strftime('%b')} {d.day}" for d in counts.index]

    else:  # Month
        months = dates.dt.to_period("M")
        counts = months.value_counts().sort_index()
        labels = [p.strftime("%b %Y") for p in counts.index]

    return labels, counts


def build_activity_chart(labels, counts, log_scale):
    tick_angle = 0 if len(labels) <= 30 else -35

    fig = go.Figure(go.Bar(
        x=labels,
        y=counts.values,
        marker_color="#3d85c8",
        hovertemplate="%{x}: %{y:,} visits<extra></extra>",
    ))
    fig.update_layout(
        title="Activity Trends Over Time",
        yaxis_title="Visits",
        yaxis_type="log" if log_scale else "linear",
        xaxis_tickangle=tick_angle,
        height=400,
        margin=dict(t=50, b=20, l=60, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def build_frequency_chart(df):
    visit_counts    = df.groupby("Mobile").size()
    max_tier        = int(visit_counts.max())
    tier_range      = range(1, max_tier + 1)
    tier_cust       = visit_counts.value_counts().reindex(tier_range, fill_value=0)
    total_customers = len(visit_counts)
    total_visits    = len(df)

    colors, texts, customdata = [], [], []
    for t in tier_range:
        n_custs  = int(tier_cust[t])
        n_visits = n_custs * t
        cust_pct  = n_custs / total_customers * 100 if total_customers else 0
        visit_pct = n_visits / total_visits * 100 if total_visits else 0

        texts.append(
            f"{cust_pct:.0f}% of customers<br>{visit_pct:.0f}% of visits"
            if n_custs > 0 else ""
        )
        customdata.append(n_custs)

        if t <= 2:
            colors.append("#a8c8e8")
        elif t <= 9:
            colors.append("#3d85c8")
        else:
            colors.append("#1a4f7a")

    fig = go.Figure(go.Bar(
        x=list(tier_range),
        y=tier_cust.values,
        text=texts,
        textposition="outside",
        textfont=dict(size=10),
        customdata=customdata,
        hovertemplate="%{customdata:,} customers visited %{x} times<extra></extra>",
        marker_color=colors,
    ))
    fig.update_layout(
        xaxis_title="Number of Visits",
        yaxis_title="Number of Customers",
        xaxis=dict(tickmode="linear", dtick=1),
        height=450,
        margin=dict(t=60, b=20, l=60, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def mask_phone(mobile, reveal):
    s = str(mobile).strip()
    if not reveal:
        last4 = s[-4:] if len(s) >= 4 else s
        return f"Customer ending in {last4}"
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return s


def build_top_visitors_chart(labels, visits):
    fig = go.Figure(go.Bar(
        x=visits,
        y=labels,
        orientation="h",
        marker_color="#3d85c8",
        text=[f"{v:,} visits" for v in visits],
        textposition="outside",
        hovertemplate="%{y} — %{x:,} visits<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Visit Count",
        height=600,
        margin=dict(t=20, b=20, l=240, r=80),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_top_visitors(df):
    st.subheader("Your Most Loyal Customers")
    st.caption(
        "Top 20 by visit count. Reach out to these people first when launching "
        "a referral program or VIP perk."
    )

    reveal = st.checkbox(
        "Reveal phone numbers (use only when not screen-sharing)",
        key="reveal_phones",
    )
    if reveal:
        st.warning("Phone numbers are visible. Hide before sharing your screen.")

    top20 = (
        df.groupby("Mobile")
        .size()
        .reset_index(name="visits")
        .nlargest(20, "visits")
        .sort_values("visits", ascending=True)  # ascending → largest at top in Plotly
    )

    labels = [mask_phone(m, reveal) for m in top20["Mobile"]]
    visits = top20["visits"].tolist()

    st.plotly_chart(build_top_visitors_chart(labels, visits), use_container_width=True)


def bin_to_range_label(bin_mins):
    def fmt(h, m):
        suffix = "AM" if h < 12 else "PM"
        h12    = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"

    h1, m1 = divmod(bin_mins, 60)
    h2, m2 = divmod((bin_mins + 30) % (24 * 60), 60)
    return f"{fmt(h1, m1)}–{fmt(h2, m2)}"


def popular_times_insight(counts):
    total = counts.sum()
    if total == 0:
        return ""
    evening = counts[counts.index.isin(range(960, 1200, 30))].sum()  # 4 PM–8 PM
    morning = counts[counts.index.isin(range(420,  660, 30))].sum()  # 7 AM–11 AM
    if evening / total >= 0.60:
        return "Evening rush. Schedule promos for after-work drivers."
    if morning / total >= 0.60:
        return "Morning rush. Commuter-focused offers will land best."
    if evening / total >= 0.20 and morning / total >= 0.20:
        return "Two waves: morning and evening. Test offers at both."
    return "Steady throughout the day."


def build_popular_times_chart(counts):
    all_bins = list(range(0, 24 * 60, 30))
    counts   = counts.reindex(all_bins, fill_value=0)

    tick_vals = list(range(0, 24 * 60, 120))
    tick_text = []
    for m in tick_vals:
        h = m // 60
        if h == 0:      tick_text.append("12 AM")
        elif h < 12:    tick_text.append(f"{h} AM")
        elif h == 12:   tick_text.append("12 PM")
        else:           tick_text.append(f"{h - 12} PM")

    peak_bin   = int(counts.idxmax())
    peak_count = int(counts.max())

    fig = go.Figure(go.Scatter(
        x=all_bins,
        y=counts.values,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(61, 133, 200, 0.15)",
        line=dict(color="#3d85c8", width=2, shape="spline"),
        customdata=[bin_to_range_label(b) for b in all_bins],
        hovertemplate="%{customdata}: %{y:,} visits<extra></extra>",
    ))
    fig.update_layout(
        yaxis_title="Visits",
        xaxis=dict(tickmode="array", tickvals=tick_vals, ticktext=tick_text),
        height=380,
        margin=dict(t=50, b=20, l=60, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            x=peak_bin, y=peak_count,
            text=f"Busiest: {bin_to_range_label(peak_bin)}, {peak_count:,} visits",
            showarrow=True, arrowhead=2, ax=50, ay=-40,
            bgcolor="white", bordercolor="#3d85c8", borderwidth=1,
            font=dict(size=11),
        )],
    )
    return fig


def render_popular_times(df):
    st.subheader("When Customers Show Up")
    st.caption(
        "Visit volume in 30-minute windows across the entire period. "
        "Use this to schedule staff and time your promotions."
    )

    times    = pd.to_datetime("2000-01-01 " + df["Time"].astype(str), errors="coerce")
    bin_mins = ((times.dt.hour * 60 + times.dt.minute) // 30) * 30
    counts   = bin_mins.value_counts().sort_index()

    st.plotly_chart(build_popular_times_chart(counts), use_container_width=True)

    insight = popular_times_insight(counts)
    if insight:
        st.caption(f"**Insight:** {insight}")


def compute_cohort_retention(df):
    d = df.copy()
    d["_dt"]    = pd.to_datetime(d["Date"], errors="coerce")
    d["_month"] = d["_dt"].dt.to_period("M")

    first_month = d.groupby("Mobile")["_month"].min().rename("cohort")
    d           = d.join(first_month, on="Mobile")

    active = (
        d.groupby(["cohort", "_month"])["Mobile"]
        .nunique()
        .reset_index(name="active")
    )
    active["offset"] = (
        active["_month"].apply(lambda p: p.ordinal)
        - active["cohort"].apply(lambda p: p.ordinal)
    )

    cohort_sizes = active[active["offset"] == 0].set_index("cohort")["active"]

    count_pivot = active.pivot_table(
        index="cohort", columns="offset", values="active", fill_value=0
    )
    pct_pivot = count_pivot.div(cohort_sizes, axis=0) * 100

    max_month = d["_month"].max()
    for cohort in pct_pivot.index:
        for offset in pct_pivot.columns:
            if cohort.ordinal + offset > max_month.ordinal:
                pct_pivot.loc[cohort, offset]  = None
                count_pivot.loc[cohort, offset] = None

    return pct_pivot, count_pivot, cohort_sizes


def cohort_headline(pct_pivot):
    avg  = pct_pivot.mean(axis=0)
    m1   = avg.get(1)
    m2   = avg.get(2)
    m3   = avg.get(3)

    parts = []
    if m1 is not None and not pd.isna(m1): parts.append(f"Month 1: {m1:.0f}%")
    if m2 is not None and not pd.isna(m2): parts.append(f"Month 2: {m2:.0f}%")
    if m3 is not None and not pd.isna(m3): parts.append(f"Month 3: {m3:.0f}%")

    if not parts:
        return "Not enough data yet to compute multi-month retention."

    msg = "On average, " + ", ".join(parts) + " of your customers come back."

    if m1 is not None and not pd.isna(m1) and (100 - m1) > 50:
        msg += (
            " That's a steep cliff. Most loyalty churn happens in the first 30 days. "
            "A welcome-back offer after a customer's first visit could move the needle."
        )
    return msg


def build_cohort_heatmap(pct_pivot, count_pivot, cohort_sizes, mode):
    cohorts = sorted(pct_pivot.index)
    offsets = sorted(pct_pivot.columns)

    y_labels = [
        f"{c.strftime('%b %Y')} ({int(cohort_sizes.get(c, 0))} joiners)"
        for c in cohorts
    ]
    x_labels = [f"Month {i}" for i in offsets]

    use_pct = (mode == "Retention %")

    z_vals, text_vals, hover_vals = [], [], []
    for cohort in cohorts:
        z_row, text_row, hover_row = [], [], []
        size      = int(cohort_sizes.get(cohort, 0))
        clbl      = cohort.strftime("%b %Y")
        for offset in offsets:
            pct = pct_pivot.loc[cohort, offset] if offset in pct_pivot.columns else None
            cnt = count_pivot.loc[cohort, offset] if offset in count_pivot.columns else None
            if pct is None or pd.isna(pct):
                z_row.append(-1)
                text_row.append("")
                hover_row.append("")
            else:
                pct_val = float(pct)
                cnt_val = int(cnt) if cnt is not None and not pd.isna(cnt) else 0
                if use_pct:
                    z_row.append(round(pct_val, 1))
                    text_row.append(f"{pct_val:.1f}%")
                else:
                    z_row.append(cnt_val)
                    text_row.append(str(cnt_val))
                hover_row.append(
                    f"{clbl} cohort: {pct_val:.1f}% of {size} joiners "
                    f"returned in Month {offset} ({cnt_val} customers)"
                )
        z_vals.append(z_row)
        text_vals.append(text_row)
        hover_vals.append(hover_row)

    if use_pct:
        colorscale = [
            [0.000, "#e8eaed"],
            [0.010, "#eaf2fb"],
            [0.505, "#3d85c8"],
            [1.000, "#1a4f7a"],
        ]
        zmin, zmax = -1, 100
    else:
        colorscale = "Blues"
        zmin, zmax = 0, max(int(cohort_sizes.max()), 1)

    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=x_labels,
        y=y_labels,
        text=text_vals,
        customdata=hover_vals,
        texttemplate="%{text}",
        hovertemplate="%{customdata}<extra></extra>",
        colorscale=colorscale,
        zmin=zmin,
        zmax=zmax,
        showscale=False,
        xgap=2,
        ygap=2,
    ))
    fig.update_layout(
        height=max(300, len(cohorts) * 70 + 100),
        margin=dict(t=30, b=20, l=180, r=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(autorange="reversed"),
    )
    return fig


def render_cohort_heatmap(df):
    st.subheader("Customer Retention by Cohort")
    st.caption(
        "How many customers from each acquisition month came back in the months after. "
        "The single most important chart for loyalty strategy."
    )

    pct_pivot, count_pivot, cohort_sizes = compute_cohort_retention(df)

    if pct_pivot.empty:
        st.info("Not enough data to build cohort chart.")
        return

    st.info(cohort_headline(pct_pivot))

    mode = st.radio(
        "Show as:",
        ["Retention %", "Active Count"],
        horizontal=True,
        key="cohort_mode",
    )

    st.plotly_chart(
        build_cohort_heatmap(pct_pivot, count_pivot, cohort_sizes, mode),
        use_container_width=True,
    )

    st.markdown(
        "- **Acquisition Quality:** A darker Month 0 column means that cohort's customers "
        "were higher quality — maybe a stronger promo or a busier season brought them in.\n"
        "- **The Cliff:** Most drop-off happens between Month 0 and Month 1. "
        "Target ghost customers with an automated offer sent 3–4 weeks after their first visit.\n"
        "- **Seasonal Drift:** Compare summer joiners to winter joiners — "
        "car wash habits differ by season, so retention rates may too."
    )


def compute_tldr(df):
    bullets = []

    # ── a. Scale ──────────────────────────────────────────────────────────────
    total_visits     = len(df)
    unique_customers = df["Mobile"].nunique() if "Mobile" in df.columns else 0

    if "Date" in df.columns:
        dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
        days  = (dates.max() - dates.min()).days
        if days >= 60:
            n         = max(1, round(days / 30))
            range_str = f"{n} month{'s' if n != 1 else ''}"
        else:
            n         = max(1, round(days / 7))
            range_str = f"{n} week{'s' if n != 1 else ''}"
        bullets.append(
            f"You have {unique_customers:,} active loyalty customers driving "
            f"{total_visits:,} visits across {range_str}."
        )

    # ── b. Retention ──────────────────────────────────────────────────────────
    if "Mobile" in df.columns and "Date" in df.columns:
        pct_pivot, _, cohort_sizes = compute_cohort_retention(df)
        valid   = cohort_sizes[cohort_sizes >= 5].index
        m1_vals = (
            pct_pivot.loc[pct_pivot.index.isin(valid), 1].dropna()
            if 1 in pct_pivot.columns else pd.Series([], dtype=float)
        )
        avg_m1 = float(m1_vals.mean()) if len(m1_vals) else None

        if avg_m1 is None:
            bullets.append("Not enough cohort data yet to compute Month 1 retention.")
        elif avg_m1 >= 60:
            bullets.append(
                f"Strong retention. {avg_m1:.0f}% of new customers come back the next month "
                "— well above industry norms for car wash loyalty."
            )
        elif avg_m1 >= 40:
            bullets.append(
                f"Solid retention. {avg_m1:.0f}% of new customers return in their first month. "
                "There's room to grow with a structured welcome offer."
            )
        else:
            bullets.append(
                f"Retention is your biggest opportunity. Only {avg_m1:.0f}% of new customers "
                "come back the next month. A welcome-back offer at day 14–21 could "
                "meaningfully change this number."
            )
    else:
        avg_m1 = None

    # ── c. Engagement mix ─────────────────────────────────────────────────────
    if "Mobile" in df.columns:
        visit_counts     = df.groupby("Mobile").size()
        total_c          = len(visit_counts)
        one_and_done_pct = (visit_counts <= 2).sum() / total_c * 100 if total_c else 0
        regular_pct      = (visit_counts >= 3).sum() / total_c * 100 if total_c else 0
        vip_pct          = (visit_counts >= 10).sum() / total_c * 100 if total_c else 0
        vip_count        = int((visit_counts >= 10).sum())
        bullets.append(
            f"{one_and_done_pct:.0f}% of your customers visit only once or twice — "
            f"that's your biggest growth lever. The good news: {regular_pct:.0f}% are "
            f"loyal regulars (3+ visits) and {vip_pct:.0f}% are VIPs (10+ visits)."
        )
    else:
        one_and_done_pct = 0
        vip_count        = 0

    # ── d. Peak time ──────────────────────────────────────────────────────────
    if "Time" in df.columns:
        times    = pd.to_datetime("2000-01-01 " + df["Time"].astype(str), errors="coerce")
        bin_mins = ((times.dt.hour * 60 + times.dt.minute) // 30) * 30
        t_counts = bin_mins.value_counts().reindex(range(0, 24 * 60, 30), fill_value=0)
        peak_bin   = int(t_counts.idxmax())
        peak_count = int(t_counts.max())
        bullets.append(
            f"Your busiest window is {bin_to_range_label(peak_bin)}, with "
            f"{peak_count:,} visits in that slot over the period. "
            "Time promotions to hit that block."
        )

    # ── e. Recommended action ─────────────────────────────────────────────────
    if avg_m1 is not None and avg_m1 < 50:
        bullets.append(
            "Action to take: launch a Day 14 welcome-back text offer. "
            "Even a 10-point boost would meaningfully improve retention."
        )
    elif one_and_done_pct > 60:
        bullets.append(
            "Action to take: target one-time visitors with a second-visit "
            "incentive within 30 days."
        )
    else:
        bullets.append(
            f"Action to take: nurture your VIPs ({vip_count:,} customers with 10+ visits) "
            "with a private rewards tier. They're already loyal — deepen it."
        )

    return bullets


def render_tldr(df):
    bullets = compute_tldr(df)
    if not bullets:
        return

    items = "".join(
        f'<li style="margin-bottom:8px;padding-left:18px;position:relative;">'
        f'<span style="position:absolute;left:0;color:#3d85c8;font-weight:bold;">→</span>'
        f"{_html.escape(b)}</li>"
        for b in bullets
    )
    st.markdown(
        f"""
        <div style="background:#f0f7ff;border-left:4px solid #3d85c8;
                    border-radius:4px;padding:16px 20px;margin-bottom:20px;color:#0a2540;">
          <p style="font-weight:700;font-size:15px;margin:0 0 10px 0;color:#061a2d;">
            What This Data Tells You
          </p>
          <ul style="list-style:none;padding:0;margin:0;line-height:1.65;">
            {items}
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def compute_kpis(df):
    total_visits     = len(df)
    unique_customers = df["Mobile"].nunique() if "Mobile" in df.columns else 0
    avg_visits       = round(total_visits / unique_customers, 1) if unique_customers else 0

    peak_display = "N/A"
    if "Date" in df.columns:
        peak_series  = df.groupby("Date").size()
        peak_date    = pd.to_datetime(peak_series.idxmax())
        peak_count   = int(peak_series.max())
        peak_display = f"{peak_date.strftime('%b')} {peak_date.day} — {peak_count:,} visits"

    return {
        "total_visits":     total_visits,
        "unique_customers": unique_customers,
        "avg_visits":       avg_visits,
        "peak_display":     peak_display,
    }


def get_filtered_data():
    df = st.session_state.get("loaded_data")
    if df is None or df.empty:
        return pd.DataFrame()

    result = df.copy()
    preset = st.session_state.get("filter_preset", "All time")
    start  = st.session_state.get("filter_date_start")
    end    = st.session_state.get("filter_date_end")
    labels = st.session_state.get("filter_actions")
    min_v  = st.session_state.get("filter_min_visits")
    max_v  = st.session_state.get("filter_max_visits")
    search = st.session_state.get("filter_search", "")

    if preset != "All time" and "Date" in result.columns:
        dates = pd.to_datetime(result["Date"], errors="coerce")
        if start:
            result = result[dates >= pd.Timestamp(start)]
        if end:
            result = result[dates <= pd.Timestamp(end)]

    if labels is not None and "Action" in result.columns:
        all_lbls = {resolve_action_label(a) for a in df["Action"].dropna().unique()}
        if set(labels) != all_lbls:
            result = result[result["Action"].apply(resolve_action_label).isin(labels)]

    if (min_v or max_v) and "Mobile" in df.columns:
        totals = df.groupby("Mobile").size()
        mask   = pd.Series(True, index=totals.index)
        if min_v:
            mask &= totals >= min_v
        if max_v:
            mask &= totals <= max_v
        result = result[result["Mobile"].isin(totals[mask].index)]

    if search.strip() and "Mobile" in result.columns:
        s   = search.strip()
        mob = result["Mobile"].astype(str)
        if len(s) <= 4 and s.isdigit():
            result = result[mob.str.endswith(s)]
        else:
            result = result[mob.str.contains(s, case=False, na=False)]

    return result


def build_filter_summary(df_full, df_filtered):
    total    = len(df_full)
    filtered = len(df_filtered)

    if filtered == total:
        return f"Showing all {total:,} records."

    parts  = []
    preset = st.session_state.get("filter_preset", "All time")

    if preset not in ("All time", "Custom", None):
        parts.append(preset)
    elif st.session_state.get("filter_date_start") or st.session_state.get("filter_date_end"):
        s      = st.session_state.get("filter_date_start")
        e      = st.session_state.get("filter_date_end")
        from_s = s.strftime("%-d %b %Y") if s else "start"
        to_s   = e.strftime("%-d %b %Y") if e else "end"
        parts.append(f"{from_s}–{to_s}")

    labels = st.session_state.get("filter_actions")
    if labels is not None and "Action" in df_full.columns:
        all_lbls = {resolve_action_label(a) for a in df_full["Action"].dropna().unique()}
        if set(labels) != all_lbls:
            shown = ", ".join(labels[:2]) + (f" +{len(labels)-2} more" if len(labels) > 2 else "")
            parts.append(f"action: {shown}")

    search = st.session_state.get("filter_search", "").strip()
    if search:
        if len(search) <= 4 and search.isdigit():
            parts.append(f"search: ending in {search}")
        else:
            parts.append(f"search: {search}")

    suffix = (" — " + ", ".join(parts)) if parts else ""
    return f"Showing {filtered:,} of {total:,} records{suffix}."


def render_filters(df):
    n = st.session_state.get("filter_reset_count", 0)

    if "Date" in df.columns:
        dates    = pd.to_datetime(df["Date"], errors="coerce").dropna()
        data_min = dates.min().date()
        data_max = dates.max().date()
    else:
        data_min = date.today() - timedelta(days=180)
        data_max = date.today()

    st.markdown("**Filter data**")

    row1           = st.columns([1, 1, 1, 1, 0.2, 1.5, 1.5])
    presets        = ["Last 7 days", "Last 30 days", "Last 90 days", "All time"]
    current_preset = st.session_state.get("filter_preset", "All time")

    for i, label in enumerate(presets):
        with row1[i]:
            btn_type = "primary" if current_preset == label else "secondary"
            if st.button(label, key=f"preset_{label.replace(' ', '_')}", type=btn_type,
                         use_container_width=True):
                if label == "All time":
                    st.session_state.update({
                        "filter_preset":      "All time",
                        "filter_date_start":  None,
                        "filter_date_end":    None,
                        "filter_reset_count": n + 1,
                    })
                else:
                    d = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[label]
                    st.session_state.update({
                        "filter_preset":      label,
                        "filter_date_start":  data_max - timedelta(days=d),
                        "filter_date_end":    data_max,
                        "filter_reset_count": n + 1,
                    })
                st.rerun()

    n            = st.session_state.get("filter_reset_count", 0)
    stored_start = st.session_state.get("filter_date_start")
    stored_end   = st.session_state.get("filter_date_end")

    with row1[5]:
        r_start = st.date_input(
            "From",
            value=stored_start if stored_start is not None else data_min,
            min_value=data_min,
            max_value=data_max,
            key=f"ds_{n}",
        )
    with row1[6]:
        r_end = st.date_input(
            "To",
            value=stored_end if stored_end is not None else data_max,
            min_value=data_min,
            max_value=data_max,
            key=f"de_{n}",
        )

    if current_preset == "All time":
        if r_start != data_min or r_end != data_max:
            st.session_state.update({
                "filter_preset":      "Custom",
                "filter_date_start":  r_start,
                "filter_date_end":    r_end,
            })
            st.rerun()
    else:
        if r_start != stored_start or r_end != stored_end:
            st.session_state["filter_preset"] = "Custom"
        st.session_state["filter_date_start"] = r_start
        st.session_state["filter_date_end"]   = r_end

    unique_labels = (
        sorted({resolve_action_label(a) for a in df["Action"].dropna().unique()})
        if "Action" in df.columns else []
    )
    if st.session_state.get("filter_actions") is None and unique_labels:
        st.session_state["filter_actions"] = unique_labels

    row2 = st.columns([3, 1, 1, 2, 1])

    with row2[0]:
        st.multiselect("Actions", unique_labels, key="filter_actions")
    with row2[1]:
        min_raw = st.text_input("Min visits", placeholder="Any", key=f"min_v_{n}")
    with row2[2]:
        max_raw = st.text_input("Max visits", placeholder="Any", key=f"max_v_{n}")
    with row2[3]:
        st.text_input(
            "Search by phone",
            placeholder="Last 4 digits or full number",
            key="filter_search",
        )
    with row2[4]:
        st.write("")
        if st.button("✕ Clear", key="cf_btn", use_container_width=True):
            st.session_state.update({
                **FILTER_DEFAULTS,
                "filter_reset_count": st.session_state.get("filter_reset_count", 0) + 1,
            })
            st.rerun()

    st.session_state["filter_min_visits"] = (
        int(min_raw) if min_raw.strip().isdigit() and int(min_raw) > 0 else None
    )
    st.session_state["filter_max_visits"] = (
        int(max_raw) if max_raw.strip().isdigit() and int(max_raw) > 0 else None
    )

    st.divider()


# ── PDF report ────────────────────────────────────────────────────────────────

def _make_numbered_canvas(max_date_str):
    """Return a Canvas subclass that stamps 'Page X of Y' on every page."""
    from reportlab.pdfgen import canvas as rl_canvas

    class _Canvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_pages = []

        def showPage(self):
            self._saved_pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_pages)
            for state in self._saved_pages:
                self.__dict__.update(state)
                self.setFont("Helvetica", 8)
                self.setFillColorRGB(0.55, 0.55, 0.55)
                self.drawCentredString(
                    306, 18,
                    f"Generated by OptSpot Loyalty Analytics  •  "
                    f"Page {self._pageNumber} of {total}  •  "
                    f"Data through {max_date_str}",
                )
                super().showPage()
            super().save()

    return _Canvas


def build_pdf_actions(df):
    """Return a list of 3–5 plain-English recommended action strings."""
    actions = []

    visit_counts = df.groupby("Mobile").size() if "Mobile" in df.columns else None

    # 1. Lapsed win-back
    if "Date" in df.columns and "Mobile" in df.columns:
        lapsed_n = len(compute_lapsed(df, 30))
        if lapsed_n > 50:
            actions.append(
                f"Win back {lapsed_n:,} customers who haven’t been back in 30+ days. "
                "Send a discount text within the next 7 days."
            )

    # 2. Peak hour (always included when Time data exists)
    if "Time" in df.columns:
        times    = pd.to_datetime("2000-01-01 " + df["Time"].astype(str), errors="coerce")
        bin_mins = ((times.dt.hour * 60 + times.dt.minute) // 30) * 30
        t_counts = bin_mins.value_counts().reindex(range(0, 24 * 60, 30), fill_value=0)
        peak_bin = int(t_counts.idxmax())
        actions.append(
            f"Promote during your peak hour: {bin_to_range_label(peak_bin)}. "
            "Push offers in the 60 minutes before that window opens."
        )

    # 3. VIP private tier
    if visit_counts is not None:
        vip_n = int((visit_counts >= 10).sum())
        if vip_n >= 20:
            actions.append(
                f"Create a private rewards tier for your {vip_n:,} VIPs (10+ visits). "
                "They’re already loyal — reward them publicly so others notice."
            )

        # 4. One-and-done re-engagement
        one_n   = int((visit_counts == 1).sum())
        one_pct = one_n / len(visit_counts) * 100 if len(visit_counts) else 0
        if one_pct > 50:
            actions.append(
                f"Target one-time visitors with a second-visit incentive within 14 days. "
                f"Currently {one_n:,} of your customers have only visited once."
            )

    # 5. Day-14 welcome-back automation
    if "Date" in df.columns and "Mobile" in df.columns:
        pct_pivot, _, cohort_sizes = compute_cohort_retention(df)
        valid   = cohort_sizes[cohort_sizes >= 5].index
        m0_vals = (
            pct_pivot.loc[pct_pivot.index.isin(valid), 0].dropna()
            if 0 in pct_pivot.columns else pd.Series([], dtype=float)
        )
        m1_vals = (
            pct_pivot.loc[pct_pivot.index.isin(valid), 1].dropna()
            if 1 in pct_pivot.columns else pd.Series([], dtype=float)
        )
        if len(m0_vals) and len(m1_vals):
            avg_m0 = float(m0_vals.mean())
            avg_m1 = float(m1_vals.mean())
            if avg_m0 > 0 and (avg_m0 - avg_m1) / avg_m0 > 0.5:
                actions.append(
                    "Build a Day 14 welcome-back automation. "
                    "The biggest churn happens in the first month — "
                    "an automated offer at day 14 is the highest-leverage fix."
                )

    # Fallback: always have at least the peak-hour item
    if not actions:
        actions.append(
            "Review your data quality — not enough records to generate "
            "specific recommendations."
        )

    return actions


def generate_pdf(df, wash_name, prepared_for):
    """Build the PDF and return its bytes. Raises RuntimeError if deps missing."""
    try:
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Image,
            Table, TableStyle, PageBreak, HRFlowable, KeepTogether,
        )
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor
    except ImportError:
        raise RuntimeError(
            "reportlab is not installed. Run: pip install reportlab kaleido"
        )

    NAVY   = HexColor("#0a2540")
    GREY   = HexColor("#333333")
    LTGREY = HexColor("#888888")
    BGBLUE = HexColor("#f0f2f6")
    RULE   = HexColor("#cccccc")

    W = 540  # content width in points (7.5" with 0.5" margins each side)

    def ps(name, size, color=GREY, bold=False, space_after=6, leading=None, left_indent=0):
        return ParagraphStyle(
            name,
            fontSize=size,
            textColor=color,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            spaceAfter=space_after,
            leading=leading or max(size + 4, 14),
            leftIndent=left_indent,
        )

    sty_report_label = ps("rl",  9, LTGREY)
    sty_title        = ps("ti", 28, NAVY,  bold=True,  space_after=8,  leading=32)
    sty_wash         = ps("wn", 20, NAVY,  bold=True,  space_after=6,  leading=24)
    sty_meta         = ps("mt", 10, GREY,  space_after=4)
    sty_h1           = ps("h1", 16, NAVY,  bold=True,  space_after=10, leading=20)
    sty_h2           = ps("h2", 13, NAVY,  bold=True,  space_after=6,  leading=17)
    sty_body         = ps("bd", 10, GREY,  space_after=5)
    sty_bullet       = ps("bu", 10, GREY,  space_after=7, left_indent=14, leading=15)
    sty_action       = ps("ac", 10, GREY,  space_after=10, left_indent=20, leading=15)
    sty_kpi_val      = ps("kv", 22, NAVY,  bold=True,  space_after=2,  leading=26)
    sty_kpi_lbl      = ps("kl",  9, LTGREY, space_after=0)

    # ── shared data ───────────────────────────────────────────────────────────
    kpis    = compute_kpis(df)
    bullets = compute_tldr(df)
    actions = build_pdf_actions(df)

    dates_series = (
        pd.to_datetime(df["Date"], errors="coerce").dropna()
        if "Date" in df.columns else pd.Series([], dtype="datetime64[ns]")
    )
    if len(dates_series):
        min_date_str = dates_series.min().strftime("%b %-d, %Y")
        max_date_str = dates_series.max().strftime("%b %-d, %Y")
        max_date_raw = dates_series.max().strftime("%b %-d, %Y")
    else:
        min_date_str = max_date_str = max_date_raw = "N/A"

    today_str = date.today().strftime("%B %-d, %Y")

    # ── chart helper ──────────────────────────────────────────────────────────
    def chart_image(fig, display_w_pt, display_h_pt, px_w=1200, px_h=450):
        try:
            png = fig.to_image(format="png", width=px_w, height=px_h, scale=2)
            return Image(io.BytesIO(png), width=display_w_pt, height=display_h_pt)
        except Exception:
            return Paragraph(
                "<i>[Chart unavailable — ensure kaleido is installed: "
                "pip install kaleido]</i>",
                sty_body,
            )

    # ── PAGE 1 — Cover / Executive Summary ───────────────────────────────────
    story = []

    story.append(Paragraph("OPTSPOT LOYALTY ANALYTICS", sty_report_label))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Loyalty Performance Report", sty_title))
    story.append(Paragraph(_html.escape(wash_name), sty_wash))

    if prepared_for:
        story.append(Paragraph(f"Prepared for: {_html.escape(prepared_for)}", sty_meta))

    story.append(Paragraph(f"Period: {min_date_str} – {max_date_str}", sty_meta))
    story.append(Paragraph(f"Generated {today_str}", sty_meta))
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width=W, thickness=1, color=RULE, spaceAfter=16))

    story.append(Paragraph("Executive Summary", sty_h1))
    for b in bullets:
        story.append(
            Paragraph(
                f'→  {_html.escape(b)}',
                sty_bullet,
            )
        )

    story.append(PageBreak())

    # ── PAGE 2 — Key Metrics + Activity Chart ─────────────────────────────────
    story.append(Paragraph("Key Metrics", sty_h1))

    def kpi_cell(label, value):
        return [
            Paragraph(_html.escape(str(value)), sty_kpi_val),
            Paragraph(_html.escape(label),      sty_kpi_lbl),
        ]

    kpi_data = [
        [kpi_cell("TOTAL VISITS",          f"{kpis['total_visits']:,}"),
         kpi_cell("UNIQUE CUSTOMERS",      f"{kpis['unique_customers']:,}")],
        [kpi_cell("AVG VISITS / CUSTOMER", str(kpis["avg_visits"])),
         kpi_cell("PEAK DAY",              kpis["peak_display"])],
    ]
    kpi_tbl = Table(kpi_data, colWidths=[W / 2, W / 2])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BGBLUE),
        ("BOX",        (0, 0), (-1, -1), 0.5,  RULE),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5,  RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 20))

    if "Date" in df.columns:
        story.append(Paragraph("Activity Over Time", sty_h1))
        labels, counts = aggregate_visits(df, "Day")
        fig_act = build_activity_chart(labels, counts, log_scale=False)
        fig_act.update_layout(title="", margin=dict(t=20, b=40, l=60, r=20))
        story.append(chart_image(fig_act, W, 200))

    story.append(PageBreak())

    # ── PAGE 3 — Cohort Retention ─────────────────────────────────────────────
    if "Mobile" in df.columns and "Date" in df.columns:
        story.append(Paragraph("Customer Retention by Cohort", sty_h1))
        pct_pivot, count_pivot, cohort_sizes = compute_cohort_retention(df)

        if not pct_pivot.empty:
            fig_cohort = build_cohort_heatmap(pct_pivot, count_pivot, cohort_sizes, "Retention %")
            n_cohorts  = len(pct_pivot)
            ch_h       = max(200, min(360, n_cohorts * 55 + 80))
            fig_cohort.update_layout(
                height=ch_h,
                margin=dict(t=20, b=20, l=180, r=20),
            )
            story.append(chart_image(fig_cohort, W, ch_h * (W / 1200), px_w=1200, px_h=ch_h * 2))
            story.append(Spacer(1, 10))
            story.append(Paragraph(cohort_headline(pct_pivot), sty_body))
        else:
            story.append(Paragraph(
                "Not enough data to build a cohort chart — "
                "at least 2 months of records are needed.",
                sty_body,
            ))

        story.append(PageBreak())

    # ── PAGE 4 — Visit Patterns ───────────────────────────────────────────────
    story.append(Paragraph("Visit Patterns", sty_h1))

    if "Mobile" in df.columns:
        story.append(Paragraph("How Often Customers Come Back", sty_h2))
        fig_freq = build_frequency_chart(df)
        fig_freq.update_layout(title="", margin=dict(t=20, b=40, l=60, r=20))
        story.append(chart_image(fig_freq, W, 210))
        story.append(Spacer(1, 14))

    if "Time" in df.columns:
        story.append(Paragraph("When Customers Show Up", sty_h2))
        times    = pd.to_datetime("2000-01-01 " + df["Time"].astype(str), errors="coerce")
        bin_mins = ((times.dt.hour * 60 + times.dt.minute) // 30) * 30
        t_counts = bin_mins.value_counts().sort_index()
        fig_times = build_popular_times_chart(t_counts)
        fig_times.update_layout(title="", margin=dict(t=20, b=40, l=60, r=20))
        story.append(chart_image(fig_times, W, 180))
        insight = popular_times_insight(t_counts)
        if insight:
            story.append(Spacer(1, 6))
            story.append(Paragraph(insight, sty_body))

    story.append(PageBreak())

    # ── PAGE 5 — Recommended Actions ─────────────────────────────────────────
    story.append(Paragraph("Recommended Actions", sty_h1))
    story.append(Paragraph(
        "Based on your data, here are the highest-leverage steps to take next:",
        sty_body,
    ))
    story.append(Spacer(1, 8))

    for i, action in enumerate(actions, 1):
        story.append(Paragraph(
            f'<b>{i}.</b>  {_html.escape(action)}',
            sty_action,
        ))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.6 * inch,  # slightly taller for footer
    )
    doc.build(story, canvasmaker=_make_numbered_canvas(max_date_raw))
    return buf.getvalue()


def render_report_expander(df):
    with st.expander("Generate Customer Report"):
        wash_name    = st.text_input(
            "Car wash name",
            placeholder="e.g. Bubba's Express Wash",
            key="pdf_wash_name",
        )
        prepared_for = st.text_input(
            "Prepared for (optional)",
            placeholder="e.g. John Smith, Owner",
            key="pdf_prepared_for",
        )

        if st.button("Generate Report (PDF)", type="primary", key="pdf_generate_btn"):
            if not wash_name.strip():
                st.error("Enter a car wash name before generating.")
            else:
                with st.spinner("Building report — exporting charts…"):
                    try:
                        pdf_bytes = generate_pdf(df, wash_name.strip(), prepared_for.strip())
                        st.session_state["pdf_bytes"] = pdf_bytes
                        slug = re.sub(r"[^a-z0-9]+", "-", wash_name.lower()).strip("-")
                        st.session_state["pdf_filename"] = (
                            f"loyalty-report-{slug}-{date.today().strftime('%Y-%m-%d')}.pdf"
                        )
                    except RuntimeError as exc:
                        st.error(str(exc))
                        st.session_state.pop("pdf_bytes", None)

        if st.session_state.get("pdf_bytes"):
            st.download_button(
                "⬇ Download PDF",
                data=st.session_state["pdf_bytes"],
                file_name=st.session_state.get("pdf_filename", "loyalty-report.pdf"),
                mime="application/pdf",
                key="pdf_download_btn",
            )


def page_dashboard():
    st.header("Dashboard")
    render_status_line()

    df = st.session_state.get("loaded_data")

    if df is None or df.empty:
        st.info("No data yet — upload a file from Import Files to see your metrics.")
        return

    st.markdown(
        """
        <style>
        [data-testid="metric-container"] {
            background-color: #f0f2f6;
            border-radius: 10px;
            padding: 20px 16px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    render_filters(df)
    df_filtered = get_filtered_data()

    if df_filtered.empty:
        st.warning(
            "No records match these filters. "
            "Try widening the date range or clearing a filter."
        )
        return

    st.caption(build_filter_summary(df, df_filtered))

    render_report_expander(df_filtered)

    render_tldr(df_filtered)

    kpis = compute_kpis(df_filtered)
    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "TOTAL VISITS",
        f"{kpis['total_visits']:,}",
        help="Every customer interaction logged at the kiosk in this period.",
    )
    c2.metric(
        "UNIQUE CUSTOMERS",
        f"{kpis['unique_customers']:,}",
        help="Number of different people who used your loyalty program in this period.",
    )
    c3.metric(
        "AVG VISITS PER CUSTOMER",
        str(kpis["avg_visits"]),
        help=(
            "On average, how many times each customer came back. "
            "Higher is better — it means your loyalty program is bringing people back."
        ),
    )
    c4.metric(
        "PEAK DAY",
        kpis["peak_display"],
        help=(
            "Your busiest day in this period. Look at it on a map of holidays "
            "and weather to understand drivers."
        ),
    )

    if "Date" in df_filtered.columns:
        dates    = pd.to_datetime(df_filtered["Date"], errors="coerce").dropna()
        min_date = dates.min().strftime("%b %-d, %Y")
        max_date = dates.max().strftime("%b %-d, %Y")
        st.caption(f"Data range: {min_date} to {max_date}")

    if "Date" not in df_filtered.columns:
        return

    ctrl_left, ctrl_right = st.columns([3, 1])
    with ctrl_left:
        period = st.radio(
            "Aggregation",
            ["Day", "Week", "Month"],
            index=0,
            horizontal=True,
        )
    with ctrl_right:
        st.write("")  # vertical alignment nudge
        log_scale = st.checkbox("Log scale")

    labels, counts = aggregate_visits(df_filtered, period)

    median_val = counts.median()
    max_val    = counts.max()
    if median_val > 0 and max_val > 3 * median_val:
        outlier_label = labels[counts.values.argmax()]
        ratio = round(max_val / median_val, 1)
        st.info(
            f"Tip: One period stands out — {outlier_label} had {ratio}x the typical "
            "volume. Try Log scale to see the rest of the trend more clearly."
        )

    st.plotly_chart(build_activity_chart(labels, counts, log_scale), use_container_width=True)

    if "Mobile" in df_filtered.columns:
        st.subheader("How Often Do Customers Come Back?")
        st.caption(
            "Distribution of customer visit counts. Most loyalty programs see a heavy "
            "left skew — that's normal. The goal is to grow the middle and right."
        )
        st.plotly_chart(build_frequency_chart(df_filtered), use_container_width=True)
        st.markdown(
            "**Light blue: One-and-Done customers (1–2 visits)** — your biggest growth opportunity.  \n"
            "**Medium blue: Regulars (3–9 visits)** — your loyal core.  \n"
            "**Dark blue: VIPs (10+ visits)** — your champions. Send them rewards."
        )

    if "Action" in df_filtered.columns:
        render_action_distribution(df_filtered)

    if "Mobile" in df_filtered.columns:
        render_top_visitors(df_filtered)

    if "Time" in df_filtered.columns:
        render_popular_times(df_filtered)

    if "Mobile" in df_filtered.columns and "Date" in df_filtered.columns:
        render_cohort_heatmap(df_filtered)


def compute_lapsed(df, threshold_days):
    today = date.today()
    d     = df.copy()
    d["_dt"] = pd.to_datetime(d["Date"], errors="coerce")

    groups     = d.groupby("Mobile")
    last_visit = groups["_dt"].max()
    lifetime   = groups.size().rename("lifetime_visits")

    result = pd.DataFrame({"last_visit": last_visit, "lifetime_visits": lifetime})

    if "Total Points" in d.columns:
        last_rows = d.sort_values("_dt").groupby("Mobile").last()
        result["total_points"] = last_rows["Total Points"].astype("Int64")

    result["days_since"] = result["last_visit"].apply(
        lambda dt: (today - dt.date()).days if pd.notna(dt) else None
    )
    result = result.dropna(subset=["days_since"])
    result["days_since"] = result["days_since"].astype(int)

    lapsed = result[result["days_since"] >= threshold_days].copy()

    def rec_action(visits):
        if visits >= 10:
            return "Personal outreach"
        if visits >= 3:
            return "Send win-back offer"
        return "Drop from active list"

    lapsed["recommended_action"] = lapsed["lifetime_visits"].apply(rec_action)
    return lapsed.sort_values("days_since", ascending=False).reset_index()


def render_retention_threshold():
    presets        = ["30 days", "60 days", "90 days", "Custom"]
    current_preset = st.session_state.get("retention_threshold_preset", "30 days")

    st.markdown("**Lapsed = no visits in the last N days**")
    cols = st.columns([1, 1, 1, 1, 3])

    for i, label in enumerate(presets):
        with cols[i]:
            btn_type = "primary" if current_preset == label else "secondary"
            if st.button(label, key=f"rt_{label[:3]}", type=btn_type, use_container_width=True):
                st.session_state["retention_threshold_preset"] = label
                if label != "Custom":
                    st.session_state["retention_threshold_days"] = int(label.split()[0])
                st.rerun()

    if current_preset == "Custom":
        with cols[4]:
            custom_val = st.number_input(
                "Custom days",
                min_value=1,
                step=1,
                value=st.session_state.get("retention_threshold_days", 30),
                label_visibility="collapsed",
            )
            st.session_state["retention_threshold_days"] = int(custom_val)
            st.caption(f"Lapsed = no visit in the last {int(custom_val)} days")

    return st.session_state.get("retention_threshold_days", 30)


def page_retention():
    st.header("Retention")
    st.caption("Find customers who are slipping away. Win them back before they're gone.")
    render_status_line()

    df_full = st.session_state.get("loaded_data")
    if df_full is None or df_full.empty:
        st.info("No data yet — upload a file from Import Files to get started.")
        return

    if "Date" not in df_full.columns or "Mobile" not in df_full.columns:
        st.warning("Retention requires Date and Mobile columns. Check your column mapping in Import Files.")
        return

    df_filtered = get_filtered_data()
    filters_active = len(df_filtered) < len(df_full)

    threshold = render_retention_threshold()

    st.divider()

    lapsed_df = compute_lapsed(df_filtered, threshold)
    n_lapsed  = len(lapsed_df)
    total_c   = df_filtered["Mobile"].nunique() if "Mobile" in df_filtered.columns else 0
    pct       = round(n_lapsed / total_c * 100) if total_c else 0

    if n_lapsed == 0:
        st.success(
            "No lapsed customers at this threshold. Your retention is strong — "
            "try a tighter threshold to find at-risk customers earlier."
        )
        return

    filter_note = ""
    if filters_active:
        preset = st.session_state.get("filter_preset", "All time")
        if preset not in ("All time", None):
            filter_note = f" (Filters applied: {preset})"
        else:
            filter_note = " (Filters applied)"

    st.markdown(
        f"""
        <div style="background:#f0f7ff;border-left:4px solid #3d85c8;
                    border-radius:4px;padding:16px 20px;margin-bottom:20px;color:#0a2540;">
          <span style="font-size:15px;">
            <strong>{n_lapsed:,} customers</strong> haven't been back in {threshold} days.
            That's <strong>{pct}%</strong> of your active customer base.
            Reaching out today is high-leverage.{_html.escape(filter_note)}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    reveal = st.checkbox(
        "Reveal phone numbers (use only when not screen-sharing)",
        key="retention_reveal_phones",
    )
    if reveal:
        st.warning("Phone numbers are visible. Hide before sharing your screen.")

    show_all    = st.session_state.get("retention_show_all", False)
    display_cap = len(lapsed_df) if show_all else min(100, len(lapsed_df))
    display_rows = lapsed_df.iloc[:display_cap]

    has_points = "total_points" in lapsed_df.columns

    def build_display_df(rows, reveal_phones):
        out = pd.DataFrame()
        out["Customer"]              = rows["Mobile"].apply(lambda m: mask_phone(m, reveal_phones))
        out["Last Visit"]            = rows["last_visit"].dt.strftime("%b %-d, %Y")
        out["Days Since Last Visit"] = rows["days_since"]
        out["Lifetime Visits"]       = rows["lifetime_visits"]
        if has_points:
            out["Total Points"] = rows["total_points"]
        out["Recommended Action"] = rows["recommended_action"]
        return out

    disp_df = build_display_df(display_rows, reveal_phones=reveal)

    col_cfg = {
        "Customer":              st.column_config.TextColumn("Customer"),
        "Last Visit":            st.column_config.TextColumn("Last Visit"),
        "Days Since Last Visit": st.column_config.NumberColumn("Days Since Last Visit", format="%d"),
        "Lifetime Visits":       st.column_config.NumberColumn("Lifetime Visits", format="%d"),
        "Recommended Action":    st.column_config.TextColumn("Recommended Action"),
    }
    if has_points:
        col_cfg["Total Points"] = st.column_config.NumberColumn("Total Points", format="%d")

    st.dataframe(disp_df, column_config=col_cfg, use_container_width=True, hide_index=True)

    if not show_all and len(lapsed_df) > 100:
        st.caption(f"Showing 100 of {n_lapsed:,} lapsed customers.")
        if st.button(f"Show all {n_lapsed:,} customers"):
            st.session_state["retention_show_all"] = True
            st.rerun()
    else:
        st.session_state["retention_show_all"] = False

    st.divider()

    export_df = build_display_df(lapsed_df, reveal_phones=True)  # full phones in CSV
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")

    dl_col, cap_col = st.columns([1, 4])
    with dl_col:
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=f"lapsed_customers_{threshold}d.csv",
            mime="text/csv",
        )
    with cap_col:
        st.caption("CSV contains full phone numbers — download to a private folder.")


def page_directory():
    st.header("Directory")
    render_status_line()
    st.info("Coming soon.")


def page_dispatcher():
    st.header("Dispatcher")
    render_status_line()
    st.info("Coming soon.")


def page_import():
    st.header("Import Files")
    render_status_line()

    if "import_success_msg" in st.session_state:
        msg = st.session_state["import_success_msg"]
        del st.session_state["import_success_msg"]
        st.success(msg)

    uploaded = st.file_uploader("Upload a CSV file", type=["csv"])

    if uploaded is None:
        return

    df_raw = pd.read_csv(uploaded)

    st.write(f"**{uploaded.name}** — {len(df_raw):,} rows")
    st.write("**Preview (first 5 rows):**")
    st.dataframe(df_raw.head(5), use_container_width=True)

    st.subheader("Column Mapping")
    st.write("Map your file's columns to the OptSpot schema. Auto-matched where column names align.")

    file_cols = list(df_raw.columns)
    options = ["-- not mapped --"] + file_cols
    col_left, col_right = st.columns(2)
    mapping = {}

    for i, field in enumerate(SCHEMA_FIELDS):
        auto = auto_match(file_cols, field)
        default_idx = options.index(auto) if auto else 0
        target_col = col_left if i % 2 == 0 else col_right
        with target_col:
            selected = st.selectbox(field, options, index=default_idx, key=f"map_{field}")
            if selected != "-- not mapped --":
                mapping[field] = selected

    st.subheader("Import Mode")
    mode = st.radio(
        "Import Mode",
        ["Replace all data", "Append to existing data"],
        index=0,
        horizontal=True,
        label_visibility="collapsed",
    )

    if st.button("Process Import", type="primary"):
        if not mapping:
            st.error("Map at least one column before importing.")
            return

        mapped_df = pd.DataFrame({field: df_raw[col] for field, col in mapping.items()})

        existing = st.session_state.get("loaded_data")
        if mode == "Append to existing data" and existing is not None:
            st.session_state["loaded_data"] = pd.concat([existing, mapped_df], ignore_index=True)
        else:
            st.session_state["loaded_data"] = mapped_df

        st.session_state["auto_loaded"] = False
        st.session_state["import_success_msg"] = f"Imported {len(mapped_df):,} rows successfully."
        st.rerun()


# ── Router ────────────────────────────────────────────────────────────────────

if page == "Dashboard":
    page_dashboard()
elif page == "Retention":
    page_retention()
elif page == "Directory":
    page_directory()
elif page == "Dispatcher":
    page_dispatcher()
elif page == "Import Files":
    page_import()
