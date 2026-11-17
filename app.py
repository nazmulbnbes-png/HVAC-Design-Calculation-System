"""
HVAC Design & Calculation System — Streamlit app.
Run locally:  streamlit run app.py
"""
import json
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import hvac_engine as E
from hvac_engine import fmt as F

st.set_page_config(page_title="HVAC Design & Calculation System", page_icon="❄️",
                   layout="wide")

# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
ROOM_COLS = {"n": "Room", "a": "Area m²", "h": "Height m", "w": "Wall m²", "g": "Glass m²",
             "r": "Roof m²", "p": "People", "l": "Light W/m²", "e": "Equip W/m²"}


def rooms_to_df(rooms):
    return pd.DataFrame([{ROOM_COLS[k]: r.get(k, 0) for k in E.ROOM_KEYS} for r in rooms])


def df_to_rooms(df):
    out = []
    for _, row in df.iterrows():
        d = {}
        for k in E.ROOM_KEYS:
            v = row[ROOM_COLS[k]]
            if k == "n":
                d[k] = "" if pd.isna(v) else str(v)
            else:
                d[k] = 0.0 if pd.isna(v) else float(v)
        out.append(d)
    return out


def _cast(k, v):
    default = E.DEFAULTS[k]
    opts = E.LABELS[k][2]
    if opts:
        return v if v in opts else default
    if isinstance(default, str):
        return str(v)
    return float(v)


def apply_project(data):
    """Load a project dict into session state (call BEFORE widgets are drawn)."""
    for k in E.DEFAULTS:
        if k in data.get("S", {}):
            try:
                st.session_state[f"in_{k}"] = _cast(k, data["S"][k])
            except (TypeError, ValueError):
                pass
    if data.get("rooms"):
        st.session_state["rooms_base"] = rooms_to_df(data["rooms"])
    st.session_state["rooms_ver"] = st.session_state.get("rooms_ver", 0) + 1
    st.session_state["in_crv"] = data.get("curve", "")


def reset_defaults():
    apply_project({"S": E.DEFAULTS, "rooms": E.DEFAULT_ROOMS, "curve": ""})


def use_chw_duty():
    st.session_state["in_sQ"] = round(st.session_state["_m3C"], 1)
    st.session_state["in_sH"] = round(st.session_state["_Hp"], 1)


if "rooms_base" not in st.session_state:
    reset_defaults()
for _k, _v in E.DEFAULTS.items():                     # safety net
    st.session_state.setdefault(f"in_{_k}", _cast(_k, _v))

# sidebar: load project (processed before any widget is drawn)
with st.sidebar:
    st.header("Project file")
    up = st.file_uploader("Load project (.json)", type="json")
    if up is not None:
        fid = getattr(up, "file_id", None) or (up.name, up.size)
        if st.session_state.get("_loaded") != fid:
            try:
                apply_project(json.load(up))
                st.session_state["_loaded"] = fid
            except Exception:
                st.error("Could not read that project file.")
    st.button("Reset to defaults", on_click=reset_defaults)

# --------------------------------------------------------------------------
# Input widgets
# --------------------------------------------------------------------------
TEMP_KEYS = {"tdb", "twb", "tin", "cwS", "cwR", "sT"}
MIN_OVERRIDE = {"cop": .1, "rng": .1, "cyc": 1.05, "gph": .1, "cell": 1.0,
                "pe": 1.0, "me": 1.0, "sPe": 1.0, "sMe": 1.0, "fr": 0.0}
MAX_OVERRIDE = {"rh": 100.0, "pe": 100.0, "me": 100.0, "sPe": 100.0, "sMe": 100.0}


def _step(k):
    d = abs(float(E.DEFAULTS[k]))
    return 10.0 if d >= 100 else 1.0 if d >= 10 else .1 if d >= 1 else .01


def field(k):
    label, unit, opts = E.LABELS[k]
    text = f"{label} ({unit})" if unit else label
    key = f"in_{k}"
    if opts:
        st.selectbox(text, opts, key=key)
    elif isinstance(E.DEFAULTS[k], str):
        st.text_input(text, key=key)
    else:
        mn = None if k in TEMP_KEYS else MIN_OVERRIDE.get(k, 0.0)
        st.number_input(text, key=key, step=_step(k), format="%g",
                        min_value=mn, max_value=MAX_OVERRIDE.get(k))


def fields(group, ncol=4):
    keys = E.GROUPS[group]
    for i in range(0, len(keys), ncol):
        cols = st.columns(ncol)
        for c, k in zip(cols, keys[i:i + ncol]):
            with c:
                field(k)


def kv(rows):
    return pd.DataFrame(rows, columns=["Item", "Value"]).set_index("Item")


# --------------------------------------------------------------------------
# Layout: draw inputs first, compute, then fill the output placeholders
# --------------------------------------------------------------------------
st.title("HVAC Design & Calculation System")
t_dash, t_load, t_chi, t_pump, t_sel, t_ct, t_rep = st.tabs(
    ["Dashboard", "Cooling load", "Chillers", "Pumps", "Pump selection",
     "Cooling tower", "Report"])

with t_dash:
    kp_box = st.container()
    chain_box = st.container()
    with st.container(border=True):
        st.subheader("Project information")
        fields("proj", 3)
    with st.container(border=True):
        st.subheader("Design conditions")
        fields("des", 3)
        st.caption("Change any input anywhere: every load, selection, schedule and "
                   "report recalculates instantly.")
    eq_box = st.container(border=True)
    brk_box = st.container(border=True)
    chk_box = st.container(border=True)

with t_load:
    with st.container(border=True):
        st.subheader("Envelope, internal & ventilation assumptions")
        fields("env", 4)
        st.caption("Simplified CLTD/SHGC method for pre-design. Wall/roof use CLTD (K); glass "
                   "conduction uses outdoor–indoor ΔT; solar = glass area × SHGC × peak solar "
                   "flux. Verify with ASHRAE CLTD/RTS or HAP for final design.")
    with st.container(border=True):
        st.subheader("Room-by-room load")
        st.caption("Edit cells, or use the + row at the bottom to add rooms. "
                   "Select a row and press Delete to remove it.")
        num = lambda: st.column_config.NumberColumn(min_value=0.0, format="%g")
        edited = st.data_editor(
            st.session_state["rooms_base"], num_rows="dynamic", hide_index=True,
            key=f"rooms_editor_{st.session_state['rooms_ver']}",
            column_config={c: num() for c in ROOM_COLS.values() if c != "Room"})
        rooms_box = st.container()
    ls_box = st.container(border=True)

with t_chi:
    with st.container(border=True):
        st.subheader("Chiller inputs")
        fields("chi", 3)
    ct_box = st.container(border=True)

with t_pump:
    with st.container(border=True):
        st.subheader("Hydraulic inputs")
        fields("pmp", 4)
    pt_box = st.container(border=True)

with t_sel:
    with st.container(border=True):
        st.subheader("Pump selection")
        fields("sel", 4)
        st.button("Use CHW primary duty", on_click=use_chw_duty)
        st_box = st.container()
    with st.container(border=True):
        st.subheader("Duty point & manufacturer curve")
        st.caption("Paste points from the manufacturer’s catalog curve (flow m³/h, head m), "
                   "one per line, e.g. `0,52`. The tool finds where it meets your system "
                   "curve. No curve data is built in.")
        st.text_area("Catalog curve points", key="in_crv", height=120,
                     placeholder="0,52\n100,50\n200,44\n300,34")
        cs_box = st.container()

with t_ct:
    with st.container(border=True):
        st.subheader("Cooling tower inputs")
        fields("ct", 4)
    tt_box = st.container(border=True)

with t_rep:
    rp_box = st.container(border=True)

# --------------------------------------------------------------------------
# Compute
# --------------------------------------------------------------------------
S = {k: st.session_state[f"in_{k}"] for k in E.DEFAULTS}
rooms = df_to_rooms(edited)

errs = E.validate(S)
if errs:
    for e in errs:
        st.error(e)
    st.stop()

r = E.calc(S, rooms)
if r is None:
    st.warning("The modelled cooling load is zero. Add at least one room with a non-zero load.")
    st.stop()

st.session_state["_m3C"], st.session_state["_Hp"] = r.m3C, r.Hp

# --------------------------------------------------------------------------
# Tables (shared by the screen and the printable report)
# --------------------------------------------------------------------------
tbl_load = kv([
    ("Sensible load", f"{F(r.sen, 1)} kW"), ("Latent load", f"{F(r.lat, 1)} kW"),
    ("Subtotal", f"{F(r.sen + r.lat, 1)} kW"), ("Safety factor", f"{F(S['sf'], 0)} %"),
    ("Total cooling load (kW)", F(r.tot, 1)), ("Total cooling load (BTU/hr)", F(r.BTU, 0)),
    ("Total cooling load (TR)", F(r.TR, 1)),
    ("Outdoor / indoor humidity ratio", f"{F(r.Wo * 1000, 1)} / {F(r.Wi * 1000, 1)} g/kg"),
    ("Fresh air total", f"{F(r.fa_total, 0)} L/s"),
])

tbl_chiller = kv([
    ("Total building cooling load (connected)", f"{F(r.conn, 1)} TR"),
    ("Diversity factor", f"{S['div']:g} %"), ("Design margin", f"{S['csf']:g} %"),
    ("Required chiller capacity", f"{F(r.req, 1)} TR"),
    ("Selected configuration", f"{r.nd} duty × {r.sz} TR"),
    ("Standby", f"{r.ns} × {r.sz} TR ({S['stb']})"),
    ("Installed / duty capacity", f"{r.ni * r.sz} / {r.dutyTR} TR"),
    ("Oversize vs. required", f"{F((r.dutyTR / r.req - 1) * 100, 1)} %"),
    ("CHW supply / return / ΔT", f"{S['cwS']:g} / {S['cwR']:g} / {F(r.dTc, 1)} °C"),
    ("CHW flow per chiller", f"{F(r.gpmC, 0)} GPM · {F(r.m3C, 1)} m³/h"),
    ("Chiller COP · kW/TR", f"{S['cop']:g} · {F(r.kwTR, 3)}"),
    ("Chiller input power each / duty total", f"{F(r.kwC, 0)} / {F(r.kwCh, 0)} kW"),
    ("Heat rejection per chiller", f"{F(r.hrC, 0)} kW"),
])


def pump_row(name, flow, head, p):
    return {"Pump": name, "Flow m³/h": F(flow, 1), "GPM": F(flow * 4.403, 0),
            "TDH m": F(head, 1), "Hydraulic kW": F(p.hy, 1), "Shaft kW": F(p.sh, 1),
            "Motor kW": p.mk, "Motor HP": F(p.hp, 1), "Type (indicative)": E.pump_type(flow, head),
            "Duty + standby": f"{r.nd} + {r.ns}"}


pump_rows = [pump_row("CHW primary" if r.ps else "CHW", r.m3C, r.Hp, r.pp)]
if r.ps:
    pump_rows.append(pump_row("CHW secondary", r.m3T / r.nd, r.Hs, r.sp))
pump_rows.append(pump_row("Condenser water", r.cwq, r.Hc, r.cp))
tbl_pumps = pd.DataFrame(pump_rows).astype(str).set_index("Pump")

tbl_head = pd.DataFrame(
    [[a, F(b), F(c)] for a, b, c in [
        ("Pipe friction", S["len"] * S["fr"] / 100, S["cLen"] * S["fr"] / 100),
        ("Fittings", S["len"] * S["fr"] / 100 * S["fit"] / 100,
         S["cLen"] * S["fr"] / 100 * S["fit"] / 100),
        ("Valves & strainers", S["vl"], S["vl"]),
        ("Evaporator / condenser", S["ev"], S["cEv"]),
        ("Coils + control valves", S["co"] + S["cv"], 0),
        ("Tower nozzles", 0, S["cTw"]),
        ("Static head", S["st"], S["cSt"]),
        (f"TDH incl. {S['hs']:g}% safety", r.Hp + r.Hs if r.ps else r.Hp, r.Hc)]],
    columns=["Component (m)", "CHW", "Condenser"]).set_index("Component (m)")

tbl_tower = kv([
    ("Chiller capacity (duty)", f"{r.dutyTR} TR"),
    ("Heat rejection", f"{F(r.hrT, 0)} kW · {F(r.hrT / 3.517, 0)} TR"),
    ("Condenser water flow", f"{F(r.cwT, 0)} m³/h · {F(r.gpmT, 0)} GPM"),
    ("Design wet bulb", f"{S['twb']:g} °C"),
    ("Leaving (cold) water", f"{F(r.lct, 1)} °C"), ("Entering (hot) water", f"{F(r.ect, 1)} °C"),
    ("Range / approach", f"{S['rng']:g} / {S['app']:g} K"),
    ("Tower capacity required", f"{F(r.tt, 0)} tower tons (15,000 BTU/hr each) at design WB"),
    ("Number of cells", f"{r.nc} × {F(r.tt / r.nc, 0)} tons"),
    ("Fan motor power", f"{F(r.fanKw, 1)} kW total · {F(r.fanKw / r.nc, 1)} kW per cell"),
    ("Evaporation loss", f"{F(r.evp, 2)} m³/h ({F(r.evp / r.cwT * 100, 2)}%)"),
    ("Drift loss", f"{F(r.drf, 3)} m³/h"),
    ("Blowdown", f"{F(r.bd, 2)} m³/h at {S['cyc']:g} cycles"),
    ("Make-up water", f"{F(r.mk, 2)} m³/h · {F(r.mk * 24, 0)} m³/day"),
])

tbl_elec = kv([("Chillers", f"{F(r.kwCh, 0)} kW"), ("CHW pumps", f"{F(r.kwPP + r.kwSP, 0)} kW"),
               ("Condenser pumps", f"{F(r.kwCP, 0)} kW"), ("Tower fans", f"{F(r.fanKw, 0)} kW"),
               ("AHU/FCU fans", f"{F(r.ac, 0)} kW"), ("Total", f"{F(r.kwTot, 0)} kW")])

# --------------------------------------------------------------------------
# Fill: Dashboard
# --------------------------------------------------------------------------
with kp_box:
    kpis = [
        ("Total cooling load", f"{F(r.TR)} TR", f"{F(r.tot, 0)} kW · {F(r.BTU / 1e3, 0)} MBH"),
        ("Chiller capacity (duty)", f"{F(r.dutyTR, 0)} TR",
         f"{r.nd} × {r.sz} TR + {r.ns} standby"),
        ("CHW pump flow (total)", f"{F(r.m3T * 4.403, 0)} GPM", f"{F(r.m3T, 0)} m³/h"),
        ("CHW pump head", f"{F(r.Hp + r.Hs if r.ps else r.Hp, 1)} m",
         f"primary {F(r.Hp)} + secondary {F(r.Hs)}" if r.ps else "single set"),
        ("Cooling tower", f"{F(r.tt, 0)} tons", f"{r.nc} cell(s) · {F(r.hrT, 0)} kW rejected"),
        ("Total electrical load", f"{F(r.kwTot, 0)} kW", f"{F(r.kwTot / r.TR, 2)} kW/TR system"),
    ]
    for row in (kpis[:3], kpis[3:]):
        for c, (a, b, d) in zip(st.columns(3), row):
            with c, st.container(border=True):
                st.metric(a, b)
                st.caption(d)

with chain_box:
    chain = [("Building load", f"{F(r.TR)} TR"),
             ("Chillers", f"{r.nd}+{r.ns} × {r.sz} TR"),
             ("CHW flow / chiller", f"{F(r.m3C, 0)} m³/h"),
             ("CW flow / chiller", f"{F(r.cwq, 0)} m³/h"),
             ("Tower water in/out", f"{F(r.ect, 1)} / {F(r.lct, 1)} °C")]
    for c, (a, b) in zip(st.columns(5), chain):
        with c:
            st.caption(a)
            st.markdown(f"**{b}**")

with eq_box:
    st.subheader("Equipment summary")
    eq = [["Chiller", f"{r.nd}/{r.ns}", f"{r.sz} TR", F(r.m3C, 0), "–",
           f"{F(r.kwC, 0)} (input)", "–"],
          ["CHW primary pump" if r.ps else "CHW pump", f"{r.nd}/{r.ns}", "–", F(r.m3C, 0),
           F(r.Hp), r.pp.mk, F(r.pp.hp, 0)]]
    if r.ps:
        eq.append(["CHW secondary pump", f"{r.nd}/{r.ns}", "–", F(r.m3T / r.nd, 0), F(r.Hs),
                   r.sp.mk, F(r.sp.hp, 0)])
    eq.append(["Condenser water pump", f"{r.nd}/{r.ns}", "–", F(r.cwq, 0), F(r.Hc),
               r.cp.mk, F(r.cp.hp, 0)])
    eq.append(["Cooling tower", f"{r.nc}/0", f"{F(r.tt / r.nc, 0)} tons", F(r.cwT / r.nc, 0),
               "–", f"{F(r.fanKw / r.nc, 1)} fan", "–"])
    st.table(pd.DataFrame(eq, columns=["Equipment", "Duty/Standby", "Unit capacity", "Flow m³/h",
                                       "Head m", "Motor kW", "Motor HP"])
             .astype(str).set_index("Equipment"))

with brk_box:
    st.subheader("Cooling load breakdown")
    T, m = r.T, r.m
    bk = [("Walls", T["wall"]), ("Roof", T["roof"]), ("Glass conduction", T["gc"]),
          ("Solar", T["sol"]), ("Lighting", T["lt"]), ("Equipment", T["eq"]),
          ("People", T["ps"] + T["pl"]), ("Fresh air", T["fs"] + T["fl"]),
          ("Infiltration", T["ins"] + T["inl"])]
    names, vals = [b[0] for b in bk][::-1], [b[1] * m for b in bk][::-1]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h", marker_color="#0e6b7e",
                           text=[f"{F(v, 0)} kW" for v in vals], textposition="outside"))
    fig.update_layout(height=340, margin=dict(l=10, r=40, t=10, b=10),
                      xaxis_title="kW (before safety factor)")
    st.plotly_chart(fig)
    st.caption(f"Before safety factor. Sensible heat ratio {F(r.shr, 2)}.")

with chk_box:
    st.subheader("Design checks")
    warns = E.design_checks(S, rooms, r)
    if warns:
        for w in warns:
            st.warning(w)
    else:
        st.caption("No warnings. Inputs are within typical pre-design ranges.")

# --------------------------------------------------------------------------
# Fill: Cooling load
# --------------------------------------------------------------------------
with rooms_box:
    st.caption("Room results")
    st.table(pd.DataFrame(
        [{"Room": x["n"], "Sens kW": F(x["sen"]), "Lat kW": F(x["lat"]),
          "Total kW": F(x["tot"]), "TR": F(x["tr"])} for x in r.rooms]).set_index("Room"))
    st.caption("Room figures are for one typical floor, before the repeat multiplier "
               "and safety factor.")
with ls_box:
    st.subheader("Load summary")
    st.table(tbl_load)

# --------------------------------------------------------------------------
# Fill: Chillers / Pumps / Tower
# --------------------------------------------------------------------------
with ct_box:
    st.subheader("Chiller load & selection")
    st.table(tbl_chiller)
    st.caption(f"Part-load: with {r.nd} duty units, one unit carries about "
               f"{F(r.req / r.nd / r.sz * 100, 0)}% at design.")
    st.caption("Capacities are generic standard sizes for sizing studies, not manufacturer "
               "models. Confirm part-load (IPLV/NPLV) and selection with vendor software.")

with pt_box:
    st.subheader("Pump duties")
    st.table(tbl_pumps)
    st.subheader("Head build-up (m)")
    st.table(tbl_head)
    st.caption("Primary loop head covers evaporator and 40 m of primary piping; the secondary "
               "carries the distribution." if r.ps else
               "Single set carries evaporator and distribution.")

with tt_box:
    st.subheader("Cooling tower selection & water balance")
    st.table(tbl_tower)
    st.caption("Tower tons are nominal; confirm at the actual design WB and range using the "
               "vendor’s thermal rating curves.")

# --------------------------------------------------------------------------
# Fill: Pump selection + curve
# --------------------------------------------------------------------------
q = r.sl
with st_box:
    st.table(kv([
        ("Fluid density", f"{F(r.rs, 1)} kg/m³"),
        ("Recommended duty (per pump)",
         f"{F(S['sQ'], 1)} m³/h ({F(S['sQ'] * 4.403, 0)} GPM) @ {F(S['sH'], 1)} m"),
        ("Hydraulic / shaft power", f"{F(q.hy, 2)} / {F(q.sh, 2)} kW"),
        ("Motor input power", f"{F(q.inp, 2)} kW"),
        ("Motor (standard, 15% margin)", f"{q.mk} kW · {F(q.hp, 1)} HP"),
        ("Recommended type", E.pump_type(S["sQ"], S["sH"])),
        ("Number of pumps", f"{r.nd} duty + {r.ns} standby"),
        ("Note", "Select a catalog pump whose curve meets the duty near best efficiency "
                 "(about 70–110% of BEP flow). Glycol needs viscosity derating from the "
                 "manufacturer."),
    ]))

pts = E.parse_curve(st.session_state.get("in_crv", ""))
dp = E.duty_point(S, pts)
with cs_box:
    n = 41
    xs = [dp["mx"] * i / (n - 1) for i in range(n)]
    fig = go.Figure()
    fig.add_scatter(x=xs, y=[dp["sys"](x) for x in xs], name="System curve",
                    line=dict(color="#c27a00", width=2))
    if len(pts) > 1:
        fig.add_scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], name="Catalog curve",
                        line=dict(color="#0e6b7e", width=2))
    fig.add_scatter(x=[S["sQ"]], y=[S["sH"]], name="Design duty", mode="markers",
                    marker=dict(color="#c27a00", size=10))
    if dp["op"]:
        fig.add_scatter(x=[dp["op"]["Q"]], y=[dp["op"]["H"]], name="Operating point",
                        mode="markers", marker=dict(symbol="circle-open", size=14,
                                                    line=dict(width=2, color="#14212b")))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(title="Flow m³/h", range=[0, dp["mx"]]),
                      yaxis=dict(title="Head m", range=[0, dp["my"]]))
    st.plotly_chart(fig)
    if len(pts) < 2:
        st.caption("Amber line: system curve through the design duty. Add catalog curve "
                   "points to see the operating point.")
    elif dp["op"]:
        o = dp["op"]
        st.markdown(f"**Operating point:** `{F(o['Q'], 1)} m³/h @ {F(o['H'], 1)} m` — "
                    f"{F(o['Q'] / S['sQ'] * 100, 0)}% of design flow, "
                    f"{F((o['H'] / S['sH'] - 1) * 100, 1)}% head vs design.")
        if o["Q"] < S["sQ"] * .95:
            st.warning("Below design flow: pick a larger pump or trim less.")
        elif o["Q"] > S["sQ"] * 1.2:
            st.warning("Well above design flow: check motor loading and throttle.")
        else:
            st.caption("Within the usual selection window.")
    else:
        st.warning("The catalog curve never meets the system curve in the range given. "
                   "Check the points or choose a pump with more head.")

# --------------------------------------------------------------------------
# Fill: Report (+ HTML download, print to PDF from the browser)
# --------------------------------------------------------------------------
sections = [("Cooling load", tbl_load), ("Chillers", tbl_chiller), ("Pumps", tbl_pumps),
            ("Cooling tower", tbl_tower), ("Electrical", tbl_elec)]
head_line = (f"{S['btype']} · {S['loc']}<br>Design: {S['tdb']:g}/{S['twb']:g} °C DB/WB outdoor, "
             f"{S['tin']:g} °C / {S['rh']:g}% indoor · {S['floors']:g} floors · {S['sys']}")
disclaimer = ("Pre-design tool. Rules of thumb and simplified methods; verify against project "
              "specifications, manufacturer data and applicable codes (ASHRAE, BNBC) "
              "before issue.")

with rp_box:
    st.subheader("Calculation report")
    st.markdown(f"**{S['proj']}**  \n{head_line}", unsafe_allow_html=True)
    for title, df in sections:
        st.markdown(f"##### {title}")
        st.table(df)
    st.caption(disclaimer)

html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{S['proj']} — HVAC Calculation Report</title>
<style>body{{font:13px/1.45 Arial,sans-serif;max-width:900px;margin:24px auto;color:#14212b}}
h1{{font-size:20px}}h3{{margin:18px 0 6px;color:#0e6b7e}}
table{{border-collapse:collapse;width:100%;margin-bottom:6px}}
th,td{{border-bottom:1px solid #d5dee4;padding:4px 8px;text-align:left;vertical-align:top}}
th{{color:#5b6b78;font-size:12px}}.n{{color:#5b6b78;font-size:12px}}</style></head><body>
<h1>{S['proj']} — HVAC Design &amp; Calculation</h1><p>{head_line}<br>
<span class="n">Issued {date.today().isoformat()}</span></p>
{''.join(f'<h3>{t}</h3>' + d.to_html(border=0, escape=True) for t, d in sections)}
<p class="n">{disclaimer}</p></body></html>"""

with t_rep:
    st.download_button("Download report (HTML — open and print / save as PDF)", html,
                       file_name="hvac_calculation_report.html", mime="text/html")

with st.sidebar:
    project = {"S": S, "rooms": rooms, "curve": st.session_state.get("in_crv", "")}
    st.download_button("Save project (.json)", json.dumps(project, indent=2),
                       file_name="hvac_project.json", mime="application/json")
    st.caption("Saves all inputs and rooms. Load it again with the uploader above.")
