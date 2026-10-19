"""Data Sentinel AI - monitoring dashboard.   Run:  streamlit run dashboard/app.py"""
import json
import os
import sys
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_sentinel import audit, config, viz  # noqa: E402
from data_sentinel.db import Database  # noqa: E402
from data_sentinel.engine import Engine, Payload  # noqa: E402

st.set_page_config(page_title="Data Sentinel AI", page_icon="🛡️", layout="wide")

DECISIONS = ["ALLOW", "WARN", "BLOCK"]
LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
DECISION_SCALE = alt.Scale(domain=DECISIONS, range=[viz.DECISION_COLORS[d] for d in DECISIONS])
LEVEL_SCALE = alt.Scale(domain=LEVELS, range=[viz.LEVEL_COLORS[lv] for lv in LEVELS])
ICON = {"ALLOW": "✅", "WARN": "⚠️", "BLOCK": "⛔"}


@st.cache_resource
def get_engine():
    db = Database()
    db.init_schema(seed=False)
    return Engine(db)


engine = get_engine()
db = engine.db


def load_events():
    rows = db.query(
        "SELECT e.id, e.ts, e.channel, e.dest_type, e.decision, e.action_taken, e.dry_run, "
        "u.name AS user, u.role, d.name AS destination, d.trust_status AS trust, "
        "f.name AS file, f.size_bytes, f.sensitivity, f.sha256, f.matches, f.inspected, "
        "r.score, r.level, r.reasons, r.features, r.signals "
        "FROM transfer_events e JOIN users u ON u.id = e.user_id JOIN devices d ON d.id = e.device_id "
        "JOIN files f ON f.id = e.file_id JOIN risk_assessments r ON r.event_id = e.id ORDER BY e.id DESC")
    df = pd.DataFrame(rows)
    if not df.empty:
        df["time"] = pd.to_datetime(df["ts"]).dt.tz_convert(config.IST).dt.tz_localize(None)
    return df


def kpis(df):
    open_alerts = db.scalar("SELECT COUNT(*) AS n FROM alerts WHERE status = 'OPEN'") or 0
    check = audit.verify(db)
    c = st.columns([1, 1, 1, 1, 1.6])
    c[0].metric("Events", f"{len(df):,}")
    c[1].metric("Blocked", f"{int((df['decision'] == 'BLOCK').sum()) if len(df) else 0:,}")
    c[2].metric("Warnings", f"{int((df['decision'] == 'WARN').sum()) if len(df) else 0:,}")
    c[3].metric("Open alerts", f"{open_alerts:,}")
    c[4].metric("Audit chain", "✅ Intact" if check.ok else "❌ Tampered", help=str(check))
    if not check.ok:
        st.error(str(check))


def filters(df):
    c = st.columns(4)
    pick = {}
    for col, (field, label, order) in zip(c, [("channel", "Channel", None), ("user", "User", None),
                                              ("level", "Risk level", LEVELS), ("decision", "Decision", DECISIONS)]):
        options = order or sorted(df[field].dropna().unique())
        pick[field] = col.multiselect(label, options, placeholder="All")
    for field, chosen in pick.items():
        if chosen:
            df = df[df[field].isin(chosen)]
    return df


def charts(df):
    left, mid = st.columns(2)
    with left:
        st.markdown("**Decisions by channel**")
        agg = df.groupby(["channel", "decision"]).size().reset_index(name="events")
        chart = alt.Chart(agg).mark_bar(cornerRadiusEnd=4, stroke=viz.SURFACE, strokeWidth=2, size=22).encode(
            y=alt.Y("channel:N", title=None, sort="-x"),
            x=alt.X("sum(events):Q", title="Events", stack="zero"),
            color=alt.Color("decision:N", scale=DECISION_SCALE, title=None,
                            legend=alt.Legend(orient="top")),
            order=alt.Order("decision_rank:Q"),
            tooltip=[alt.Tooltip("channel:N", title="Channel"), alt.Tooltip("decision:N", title="Decision"),
                     alt.Tooltip("events:Q", title="Events")],
        ).transform_calculate(decision_rank="indexof(['ALLOW','WARN','BLOCK'], datum.decision)")
        st.altair_chart(chart.properties(height=alt.Step(34)), width="stretch")
    with mid:
        st.markdown("**Events by risk level**")
        lv = df.groupby("level").size().reindex(LEVELS, fill_value=0).reset_index(name="events")
        bars = alt.Chart(lv).mark_bar(cornerRadiusEnd=4, size=40).encode(
            x=alt.X("level:N", sort=LEVELS, title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("events:Q", title="Events"),
            color=alt.Color("level:N", scale=LEVEL_SCALE, legend=None),
            tooltip=[alt.Tooltip("level:N", title="Risk level"), alt.Tooltip("events:Q", title="Events")])
        text = bars.mark_text(dy=-8, color=viz.INK_2).encode(text="events:Q", color=alt.value(viz.INK_2))
        st.altair_chart((bars + text).properties(height=260), width="stretch")

    st.markdown("**Risk score over time** (IST) - lines mark the LOW / MEDIUM / HIGH / CRITICAL bands")
    rules = alt.Chart(pd.DataFrame({"y": [25, 50, 70]})).mark_rule(color=viz.BASELINE, strokeWidth=1).encode(y="y:Q")
    pts = alt.Chart(df).mark_circle(size=90, stroke=viz.SURFACE, strokeWidth=2, opacity=0.95).encode(
        x=alt.X("time:T", title=None),
        y=alt.Y("score:Q", title="Risk score", scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("decision:N", scale=DECISION_SCALE, title=None, legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("id:Q", title="Event"), alt.Tooltip("time:T", title="Time", format="%d %b %H:%M:%S"),
                 alt.Tooltip("user:N"), alt.Tooltip("file:N"), alt.Tooltip("destination:N"),
                 alt.Tooltip("score:Q", title="Score"), alt.Tooltip("level:N"), alt.Tooltip("decision:N")])
    st.altair_chart((rules + pts).properties(height=280).interactive(bind_y=False), width="stretch")


def events_table(df):
    st.subheader("Events")
    view = df[["id", "time", "channel", "user", "destination", "file", "sensitivity", "score", "level",
               "decision", "action_taken"]].copy()
    view["decision"] = view["decision"].map(lambda d: f"{ICON.get(d, '')} {d}")
    st.dataframe(view, hide_index=True, width="stretch", height=320,
                 column_config={"id": st.column_config.NumberColumn("#", width="small"),
                                "time": st.column_config.DatetimeColumn("Time (IST)", format="DD MMM HH:mm:ss"),
                                "score": st.column_config.NumberColumn("Score", format="%.1f"),
                                "action_taken": "Response"})


def explain(df):
    st.subheader("Why was this scored this way?")
    labels = {int(r.id): f"#{r.id} · {r.file} → {r.destination} · {r.decision} {r.score}" for r in df.itertuples()}
    eid = st.selectbox("Event", list(labels), format_func=labels.get)
    if eid is None:
        return
    r = df[df["id"] == eid].iloc[0]
    signals = json.loads(r["signals"] or "{}")
    feats = json.loads(r["features"] or "{}")
    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"### {ICON.get(r['decision'], '')} {r['decision']} — risk {r['score']} ({r['level']})")
        st.markdown(f"**{r['user']}** ({r['role']}) → **{r['destination']}** ({r['dest_type']}, {r['trust']}) "
                    f"via {r['channel']} · `{r['file']}` · {r['sensitivity']}")
        st.markdown("\n".join(f"- {x}" for x in json.loads(r["reasons"])))
        if r["action_taken"]:
            st.markdown(f"**Response:** {r['action_taken']}")
        matches = json.loads(r["matches"] or "{}")
        if matches:
            st.caption("Matched (type × count only - values are never stored): "
                       + ", ".join(f"{k} ×{v}" for k, v in matches.items()))
    with right:
        rows = [{"signal": k, "value": round(v, 3), "weight": config.WEIGHTS[k],
                 "points": round(100 * config.WEIGHTS[k] * v, 1)} for k, v in signals.items()]
        contrib = pd.DataFrame(rows)
        st.markdown("**Score breakdown** (points = 100 × weight × signal)")
        bar = alt.Chart(contrib).mark_bar(cornerRadiusEnd=4, size=18, color=viz.SERIES[0]).encode(
            y=alt.Y("signal:N", sort=list(config.WEIGHTS), title=None),
            x=alt.X("points:Q", title="Points", scale=alt.Scale(domain=[0, 35])),
            tooltip=["signal", "value", "weight", "points"])
        lbl = bar.mark_text(align="left", dx=4, color=viz.INK_2).encode(text="points:Q", color=alt.value(viz.INK_2))
        st.altair_chart((bar + lbl).properties(height=220), width="stretch")
        st.caption("Anomaly features: " + ", ".join(f"{k}={v}" for k, v in feats.items()))


def alerts_panel():
    st.subheader("Alerts")
    rows = db.query("SELECT a.id, a.event_id, a.severity, a.status, a.created_at, a.message, a.resolved_by "
                    "FROM alerts a ORDER BY a.id DESC LIMIT 200")
    open_rows = [a for a in rows if a["status"] == "OPEN"]
    if not open_rows:
        st.success("No open alerts.")
    else:
        pick = st.multiselect("Select alerts to resolve", [a["id"] for a in open_rows],
                              format_func=lambda i: next(f"#{a['id']} {a['message']}" for a in open_rows if a["id"] == i))
        c = st.columns([1, 1, 4])
        if c[0].button("Mark resolved", disabled=not pick, type="primary"):
            for i in pick:
                db.resolve_alert(i, "dashboard")
            st.rerun()
        if c[1].button("Resolve all"):
            for a in open_rows:
                db.resolve_alert(a["id"], "dashboard")
            st.rerun()
    if rows:
        table = pd.DataFrame(rows)
        table["created_at"] = pd.to_datetime(table["created_at"]).dt.tz_convert(config.IST).dt.tz_localize(None)
        st.dataframe(table[["id", "event_id", "severity", "status", "created_at", "message"]], hide_index=True,
                     width="stretch", height=240,
                     column_config={"created_at": st.column_config.DatetimeColumn("Raised (IST)",
                                                                                  format="DD MMM HH:mm:ss")})


def check_file():
    st.subheader("Check a file")
    st.caption("Runs the file through the full pipeline and records the result (channel 'dashboard'). "
               "The content is processed in memory and never stored.")
    users = [u["name"] for u in db.query("SELECT name FROM users ORDER BY name")] or ["alice"]
    with st.form("check"):
        up = st.file_uploader("File")
        c = st.columns(3)
        user = c[0].selectbox("User", users, index=users.index("alice") if "alice" in users else 0)
        dest = c[1].text_input("Destination", "drive.google.com")
        dest_type = c[2].selectbox("Destination type", list(config.DEST_RISK), index=list(config.DEST_RISK).index("cloud"))
        go = st.form_submit_button("Check file", type="primary")
    if go and up is not None:
        d = engine.process(user, Payload.from_bytes(up.name, up.getvalue()), dest.strip() or "unknown", dest_type,
                           "dashboard")
        box = {"BLOCK": st.error, "WARN": st.warning}.get(d.decision, st.success)
        box(f"{ICON[d.decision]} {d.decision} — {d.file_name} ({d.sensitivity}) → {d.device}: "
            f"risk {d.score} ({d.level})")
        st.markdown("\n".join(f"- {x}" for x in d.reasons))
    elif go:
        st.info("Choose a file first.")


def reference_tables():
    left, right = st.columns(2)
    with left:
        st.subheader("Devices and destinations")
        st.dataframe(pd.DataFrame(db.query("SELECT name, device_type AS type, trust_status AS trust FROM devices "
                                           "ORDER BY name")), hide_index=True, width="stretch", height=300)
    with right:
        st.subheader("Policy")
        st.dataframe(pd.DataFrame(db.query("SELECT level, action, description FROM policies ORDER BY id")),
                     hide_index=True, width="stretch")
        st.markdown("**Hard rules (applied in this order)**\n"
                    "1. Restricted data to any non-trusted destination → always BLOCK\n"
                    "2. Public data that would get WARN → ALLOW\n"
                    "3. Admin on a trusted device → BLOCK becomes WARN")
        w = " + ".join(f"{v:.2f}·{k}" for k, v in config.WEIGHTS.items())
        st.caption(f"Risk = 100 × ({w}), each signal 0-1 (sensitivity = level / 3). "
                   "LOW < 25 ≤ MEDIUM < 50 ≤ HIGH < 70 ≤ CRITICAL.")


# --------------------------------------------------------------------------- page
with st.sidebar:
    st.markdown("## 🛡️ Data Sentinel AI")
    st.caption("AI-powered multi-channel Data Loss Prevention")
    auto = st.toggle("Auto-refresh every 5 s", value=True)
    if st.button("Refresh now"):
        st.rerun()
    st.caption(f"Database: {db.location}")
    st.caption(f"Anomaly model: {engine.anomaly.source}")
    st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')}")


@st.fragment(run_every="5s" if auto else None)
def live():
    df = load_events()
    st.title("Data Sentinel AI")
    st.caption("Monitoring dashboard · every transfer on every channel, scored and explained")
    kpis(df)
    if df.empty:
        st.info("No transfer events yet. Run `python -m data_sentinel simulate` or start the agent.")
        return
    st.divider()
    fdf = filters(df)
    if fdf.empty:
        st.warning("No events match these filters.")
        return
    charts(fdf)
    events_table(fdf)
    explain(fdf)


live()
st.divider()
alerts_panel()
st.divider()
check_file()
st.divider()
reference_tables()
