"""
Dashboard Monitoring Getaran Baterai - ADXL345  (v2 - tampilan baru)
====================================================================
Stack : ADXL345 -> Arduino -> Python logger -> MySQL -> Streamlit (file ini)

Jalankan:
    streamlit run dashboard.py

Password database JANGAN ditulis di kode. Isi lewat salah satu cara:
    1. Environment variable    : set DB_PASSWORD=passwordAnda   (CMD)
    2. .streamlit/secrets.toml : DB_PASSWORD = "passwordAnda"

Disarankan juga membuat .streamlit/config.toml:
    [theme]
    base = "dark"

Yang baru di versi ini:
    - Kartu KPI dengan sparkline mini + efek hover
    - Header animasi gradien, latar bergrid, kaca (glassmorphism)
    - Tabel riwayat: filter level, urutan, jumlah baris, progress bar, level berwarna
    - Tabel statistik dengan bar RMS
    - Grafik baru: distribusi level (donut) & histogram getaran
"""

# ==================================================================
# 1. IMPORT
# ==================================================================
import os
from dataclasses import dataclass
from datetime import datetime

import mysql.connector
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


# ==================================================================
# 2. KONFIGURASI & KONSTANTA
# ==================================================================
st.set_page_config(page_title="ADXL345 Vibration Monitoring", page_icon="⚙️", layout="wide")


def get_setting(name: str, default: str = "") -> str:
    """Baca pengaturan dari environment variable, lalu .streamlit/secrets.toml."""
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets[name])
    except Exception:
        return default


DB_CONFIG = {
    "host": get_setting("DB_HOST", "localhost"),
    "port": int(get_setting("DB_PORT", "3306")),
    "user": get_setting("DB_USER", "ta_app"),
    "password": get_setting("DB_PASSWORD", "Perdana17*"),   # sengaja kosong: isi lewat env / secrets
    "database": get_setting("DB_NAME", "vibration_monitoring"),
}
TABLE = "data_adxl345"
TIME_COL = "waktu_terima"

AXES = ["ax_ms2", "ay_ms2", "az_ms2"]
AXIS_NAME = {"ax_ms2": "Sumbu X", "ay_ms2": "Sumbu Y", "az_ms2": "Sumbu Z"}
AXIS_COLOR = {"ax_ms2": "#ff6b6b", "ay_ms2": "#4ade80", "az_ms2": "#38bdf8"}
AXIS_ICON = {"ax_ms2": "↔️", "ay_ms2": "↕️", "az_ms2": "⏺️"}

COLOR_OK = "#22c55e"
COLOR_WARN = "#f59e0b"
COLOR_DANGER = "#ef4444"
COLOR_ACCENT = "#22d3ee"
COLOR_FFT = "#a78bfa"
TEXT_MUTED = "#94a3b8"
GRID = "rgba(255,255,255,0.07)"
TRANSPARENT = "rgba(0,0,0,0)"
FONT = "Inter, Segoe UI, sans-serif"

DATA_AKTIF_DETIK = 10
MIN_SAMPEL_FFT = 64
PILIHAN_JUMLAH_DATA = [100, 200, 500, 1000, 5000, "Semua"]
JUMLAH_SPARK = 40       # titik pada sparkline kartu KPI


@dataclass
class Settings:
    limit: int | None
    auto_refresh: bool
    interval: int
    waspada: float
    bahaya: float


# ==================================================================
# 3. GAYA (CSS)
# ==================================================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ---------- Dasar ---------- */
html, body, [class*="css"], .stApp {font-family: 'Inter', 'Segoe UI', sans-serif;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}
.stApp {
    color: #e2e8f0;
    background:
        linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px) 0 0 / 38px 38px,
        linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px) 0 0 / 38px 38px,
        radial-gradient(900px 500px at 8% -8%,  rgba(59,91,255,.30), transparent 60%),
        radial-gradient(800px 500px at 100% 0%, rgba(34,211,238,.18), transparent 60%),
        radial-gradient(700px 500px at 50% 110%, rgba(167,139,250,.12), transparent 60%),
        #080c18;
}
.block-container {padding: 2.2rem 1.6rem 1.2rem 1.6rem; max-width: 100%;}
::-webkit-scrollbar {width: 8px; height: 8px;}
::-webkit-scrollbar-thumb {background: rgba(148,163,184,.3); border-radius: 8px;}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f1530, #0a0f1f);
    border-right: 1px solid rgba(255,255,255,.07);
}
section[data-testid="stSidebar"] * {color: #e2e8f0;}
.side-brand {
    font-weight: 800; font-size: 19px; letter-spacing: .6px; margin-bottom: 4px;
    background: linear-gradient(90deg, #22d3ee, #818cf8, #c084fc);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

/* ---------- Animasi ---------- */
@keyframes spin     {from {transform: rotate(0deg);}   to {transform: rotate(360deg);}}
@keyframes spin-rev {from {transform: rotate(360deg);} to {transform: rotate(0deg);}}
@keyframes pulse {
    0%   {box-shadow: 0 0 0 0 rgba(34,197,94,.7);}
    70%  {box-shadow: 0 0 0 9px rgba(34,197,94,0);}
    100% {box-shadow: 0 0 0 0 rgba(34,197,94,0);}
}
@keyframes flow {0% {background-position: 0% 50%;} 50% {background-position: 100% 50%;} 100% {background-position: 0% 50%;}}
@keyframes rise {from {opacity: 0; transform: translateY(8px);} to {opacity: 1; transform: none;}}
.gear      {display: inline-block; animation: spin 6s linear infinite;}
.gear-rev  {display: inline-block; animation: spin-rev 6s linear infinite;}
.gear-stop {display: inline-block;}

/* ---------- Header ---------- */
.topbar {
    position: relative; overflow: hidden;
    background: linear-gradient(120deg, #1d3bff, #4f46e5, #06b6d4, #4f46e5);
    background-size: 300% 300%; animation: flow 14s ease infinite;
    padding: 22px 28px; border-radius: 20px; margin-bottom: 18px;
    display: flex; justify-content: space-between; align-items: center;
    box-shadow: 0 12px 40px rgba(59,91,255,.35);
    border: 1px solid rgba(255,255,255,.2);
}
.topbar::before {
    content: ""; position: absolute; inset: 0;
    background: repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 22px);
}
.topbar::after {
    content: ""; position: absolute; right: -60px; top: -70px; width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(255,255,255,.28), transparent 70%);
}
.topbar > div {position: relative; z-index: 1;}
.topbar-title {font-size: 25px; font-weight: 800; letter-spacing: .8px; color: #fff; text-shadow: 0 2px 14px rgba(0,0,0,.25);}
.topbar-sub   {font-size: 13px; color: rgba(255,255,255,.85); margin-top: 4px;}
.topbar-right {text-align: right;}
.topbar-time  {font-size: 15px; font-weight: 600; color: #fff; margin-top: 8px; font-variant-numeric: tabular-nums;}
.live {
    display: inline-flex; align-items: center; gap: 8px; padding: 5px 14px;
    border-radius: 999px; background: rgba(0,0,0,.32); color: #fff;
    font-size: 12px; font-weight: 700; letter-spacing: 1.2px; backdrop-filter: blur(6px);
}
.live .dot {width: 9px; height: 9px; border-radius: 50%;}
.live.on  .dot {background: #22c55e; animation: pulse 1.6s infinite;}
.live.off .dot {background: #ef4444;}

/* ---------- Panel ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: linear-gradient(160deg, rgba(255,255,255,.055), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,.09) !important;
    border-radius: 18px; backdrop-filter: blur(10px);
    box-shadow: 0 6px 26px rgba(0,0,0,.30);
}
.ptitle {font-weight: 700; font-size: 16px; margin: 2px 0 10px; color: #f1f5f9;}

/* ---------- Kartu KPI ---------- */
.kpi {
    position: relative; overflow: hidden; height: 100%; animation: rise .5s ease both;
    background: linear-gradient(160deg, rgba(255,255,255,.08), rgba(255,255,255,.02));
    border: 1px solid rgba(255,255,255,.10); border-radius: 18px;
    padding: 16px 18px 16px 22px; box-shadow: 0 6px 24px rgba(0,0,0,.28);
    transition: transform .2s, box-shadow .2s, border-color .2s;
}
.kpi:hover {transform: translateY(-3px); border-color: var(--accent); box-shadow: 0 10px 30px rgba(0,0,0,.4), 0 0 22px -6px var(--accent);}
.kpi::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px;
    background: linear-gradient(180deg, var(--accent), transparent);
}
.kpi::after {
    content: ""; position: absolute; right: -30px; top: -30px; width: 120px; height: 120px;
    background: radial-gradient(circle, var(--accent), transparent 70%); opacity: .20;
}
.kpi-label {font-size: 12px; color: #94a3b8; font-weight: 700; letter-spacing: .6px;}
.kpi-value {font-size: 30px; font-weight: 800; color: #fff; margin-top: 6px; line-height: 1.1; font-variant-numeric: tabular-nums;}
.kpi-unit  {font-size: 13px; font-weight: 500; color: #94a3b8;}
.kpi-delta {font-size: 12px; margin-top: 6px; color: #94a3b8;}
.kpi-delta.up   {color: #fca5a5;}
.kpi-delta.down {color: #86efac;}
.kpi-spark {margin-top: 8px; height: 34px; opacity: .95;}
.kpi-status {
    font-size: 27px; font-weight: 800; margin-top: 6px; line-height: 1.2;
    color: var(--accent); text-shadow: 0 0 18px var(--accent);
}
.meter {height: 7px; border-radius: 99px; background: rgba(255,255,255,.1); margin-top: 10px; overflow: hidden;}
.meter > div {height: 100%; border-radius: 99px; background: var(--accent); box-shadow: 0 0 10px var(--accent);}

/* ---------- Info Data ---------- */
.info-row {
    display: flex; justify-content: space-between; align-items: center;
    background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07);
    border-radius: 12px; padding: 10px 14px; margin-top: 8px; font-size: 13.5px;
    transition: background .2s;
}
.info-row:hover {background: rgba(255,255,255,.08);}
.info-row span {color: #94a3b8;}
.info-row b    {color: #f1f5f9; font-variant-numeric: tabular-nums;}

/* ---------- Chip ringkasan tabel ---------- */
.chips {display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 10px;}
.chip {
    padding: 5px 13px; border-radius: 999px; font-size: 12.5px; font-weight: 700;
    border: 1px solid var(--c); color: var(--c); background: rgba(255,255,255,.04);
}
.chip b {color: #fff; margin-left: 4px;}

/* ---------- Tabel ---------- */
div[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,.10); border-radius: 14px; overflow: hidden;
    box-shadow: 0 4px 18px rgba(0,0,0,.28);
}

/* ---------- Tab ---------- */
div[data-baseweb="tab-list"] {gap: 8px; border-bottom: none;}
button[data-baseweb="tab"] {
    background: rgba(255,255,255,.05); border-radius: 999px; padding: 8px 20px;
    border: 1px solid rgba(255,255,255,.08); font-weight: 600; transition: background .2s;
}
button[data-baseweb="tab"]:hover {background: rgba(255,255,255,.1);}
button[data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(90deg, #2f4bff, #22a6ee); color: #fff;
    border-color: transparent; box-shadow: 0 4px 16px rgba(47,75,255,.45);
}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {display: none;}

/* ---------- Tombol ---------- */
div.stButton > button, div.stDownloadButton > button {
    background: linear-gradient(90deg, #2f4bff, #22a6ee); color: #fff; border: none;
    font-weight: 700; border-radius: 12px; height: 44px; width: 100%;
    box-shadow: 0 4px 14px rgba(47,75,255,.35); transition: transform .15s, box-shadow .15s;
}
div.stButton > button:hover, div.stDownloadButton > button:hover {
    color: #fff; transform: translateY(-1px); box-shadow: 0 6px 22px rgba(47,75,255,.55);
}

/* ---------- Footer ---------- */
.footer-box {
    text-align: center; color: #64748b; font-size: 13px; padding: 16px 0 6px;
    border-top: 1px solid rgba(255,255,255,.06); margin-top: 18px;
}
</style>
"""


def apply_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ==================================================================
# 4. LAPISAN DATA
# ==================================================================
def load_data(limit: int | None):
    """Ambil data dari MySQL. Return: (DataFrame, total_baris, pesan_error)."""
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG, connection_timeout=5)
        cur = conn.cursor(dictionary=True)

        cur.execute(f"SELECT COUNT(*) AS total FROM {TABLE}")
        total = cur.fetchone()["total"]

        if limit:
            cur.execute(
                f"SELECT * FROM (SELECT * FROM {TABLE} ORDER BY id DESC LIMIT %s) t "
                f"ORDER BY id ASC",
                (int(limit),),
            )
        else:
            cur.execute(f"SELECT * FROM {TABLE} ORDER BY id ASC")

        rows = cur.fetchall()
        cur.close()
        return pd.DataFrame(rows), total, None

    except mysql.connector.Error as e:
        return pd.DataFrame(), 0, str(e)

    finally:
        if conn is not None and conn.is_connected():
            conn.close()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Ubah tipe kolom dan buang baris yang tidak valid."""
    df = df.copy()
    df[TIME_COL] = pd.to_datetime(df[TIME_COL], errors="coerce")
    for c in AXES:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[TIME_COL] + AXES)
    return df.reset_index(drop=True)


# ==================================================================
# 5. ANALISIS
# ==================================================================
def analisis(df: pd.DataFrame):
    """Tambah kolom 'resultan' dan 'dinamis' (gravitasi dibuang), hitung RMS."""
    df = df.copy()
    df["resultan"] = np.sqrt((df[AXES] ** 2).sum(axis=1))
    simpangan = df[AXES] - df[AXES].mean()
    df["dinamis"] = np.sqrt((simpangan ** 2).sum(axis=1))
    rms = float(np.sqrt((df["dinamis"] ** 2).mean()))
    return df, rms


def spektrum(df: pd.DataFrame):
    """FFT dari resultan. Return: (freq, amp, fs, freq_dominan) atau None."""
    n = len(df)
    if n < MIN_SAMPEL_FFT:
        return None

    span = (df[TIME_COL].iloc[-1] - df[TIME_COL].iloc[0]).total_seconds()
    if span <= 0:
        return None

    fs = (n - 1) / span
    x = df["resultan"].to_numpy()
    x = x - x.mean()

    w = np.hanning(n)
    amp = np.abs(np.fft.rfft(x * w)) * 2 / w.sum()
    freq = np.fft.rfftfreq(n, 1 / fs)

    dominan = float(freq[1:][np.argmax(amp[1:])]) if len(freq) > 1 else 0.0
    return freq, amp, fs, dominan


def status_info(rms: float, waspada: float, bahaya: float):
    if rms >= bahaya:
        return "⚠️ BAHAYA", COLOR_DANGER
    if rms >= waspada:
        return "WASPADA", COLOR_WARN
    return "NORMAL", COLOR_OK


def tambah_level(df: pd.DataFrame, waspada: float, bahaya: float) -> pd.DataFrame:
    """Kolom 'level' per baris berdasarkan getaran dinamis."""
    df = df.copy()
    df["level"] = np.select(
        [df["dinamis"] >= bahaya, df["dinamis"] >= waspada],
        ["🔴 Bahaya", "🟡 Waspada"],
        default="🟢 Normal",
    )
    return df


def buat_statistik(df: pd.DataFrame, rms: float) -> pd.DataFrame:
    """Tabel min / maks / rata-rata / RMS per sumbu dan resultan."""
    ikon = {c: AXIS_ICON[c] for c in AXES}
    return pd.DataFrame({
        "Sumbu": [f"{ikon[c]} {AXIS_NAME[c]}" for c in AXES] + ["🧭 Resultan"],
        "Min": [df[c].min() for c in AXES] + [df["resultan"].min()],
        "Maks": [df[c].max() for c in AXES] + [df["resultan"].max()],
        "Rata-rata": [df[c].mean() for c in AXES] + [df["resultan"].mean()],
        "RMS Getaran": [df[c].std(ddof=0) for c in AXES] + [rms],
    }).round(3)


# ==================================================================
# 6. GRAFIK
# ==================================================================
def base_layout(fig: go.Figure, title: str, height: int = 340) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.02, font=dict(size=16, color="#f1f5f9")),
        height=height,
        margin=dict(l=10, r=14, t=56, b=10),
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        font=dict(family=FONT, color="#cbd5e1"),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#0f172a", bordercolor="#334155", font=dict(family=FONT)),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False)
    return fig


def hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def waveform_chart(df: pd.DataFrame) -> go.Figure:
    """
    Grafik getaran 3 sumbu dalam satu bidang, tema gelap transparan.

    Garis tebal halus dengan efek glow, area lembut di bawah garis,
    garis nol, grid horizontal tipis, dan penanda data terbaru.
    Gravitasi dibuang (nilai dikurangi rata-rata).
    """
    dev = {c: df[c] - df[c].mean() for c in AXES}
    lim = max(float(d.abs().max()) for d in dev.values()) * 1.2 or 1.0
    x = df[TIME_COL]

    fig = go.Figure()
    for c in AXES:
        warna = AXIS_COLOR[c]
        # Glow (garis lebar transparan di belakang)
        fig.add_trace(go.Scatter(
            x=x, y=dev[c], mode="lines", showlegend=False, hoverinfo="skip",
            line=dict(color=hex_rgba(warna, 0.16), width=10, shape="spline", smoothing=0.8),
        ))
        # Garis utama + area lembut ke garis nol
        fig.add_trace(go.Scatter(
            x=x, y=dev[c], name=AXIS_NAME[c], mode="lines",
            line=dict(color=warna, width=3, shape="spline", smoothing=0.8),
            fill="tozeroy", fillcolor=hex_rgba(warna, 0.07),
            hovertemplate="%{y:+.3f} m/s²",
        ))
        # Titik data terbaru
        fig.add_trace(go.Scatter(
            x=[x.iloc[-1]], y=[dev[c].iloc[-1]], mode="markers", showlegend=False,
            marker=dict(color=warna, size=11, line=dict(color="#ffffff", width=2)),
            hoverinfo="skip",
        ))

    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,.35)", width=1.2, dash="dot"))

    base_layout(fig, "🌊 Gelombang Getaran 3 Sumbu", height=470)
    fig.update_layout(
        margin=dict(l=64, r=24, t=64, b=50),
        showlegend=True,
        legend=dict(
            orientation="h", x=1, xanchor="right", y=1.14, yanchor="bottom",
            bgcolor="rgba(255,255,255,.06)", bordercolor="rgba(255,255,255,.12)", borderwidth=1,
            font=dict(size=12.5, color="#e2e8f0"), itemsizing="constant",
        ),
    )
    fig.update_xaxes(
        tickformat="%H:%M:%S", showgrid=False, ticks="outside",
        tickcolor="rgba(255,255,255,.2)", tickfont=dict(color=TEXT_MUTED),
        showspikes=True, spikemode="across", spikecolor="rgba(255,255,255,.4)",
        spikethickness=1, spikedash="dot",
    )
    fig.update_yaxes(
        range=[-lim, lim], gridcolor="rgba(255,255,255,.06)", griddash="dot",
        zeroline=False, tickfont=dict(color=TEXT_MUTED),
        title=dict(text="Percepatan (m/s²)", font=dict(size=12.5, color=TEXT_MUTED)),
    )
    return fig


def dynamic_chart(df: pd.DataFrame, waspada: float, bahaya: float) -> go.Figure:
    ymax = max(float(df["dinamis"].max()) * 1.15, bahaya * 1.2, 1.0)

    fig = go.Figure(go.Scatter(
        x=df[TIME_COL], y=df["dinamis"], name="Dinamis", mode="lines",
        line=dict(color=COLOR_WARN, width=2, shape="spline", smoothing=0.5),
        fill="tozeroy", fillcolor="rgba(245,158,11,0.16)",
        hovertemplate="%{y:.3f} m/s²",
    ))
    fig.add_hrect(y0=0, y1=waspada, fillcolor=COLOR_OK, opacity=0.07, line_width=0)
    fig.add_hrect(y0=waspada, y1=bahaya, fillcolor=COLOR_WARN, opacity=0.07, line_width=0)
    fig.add_hrect(y0=bahaya, y1=ymax, fillcolor=COLOR_DANGER, opacity=0.08, line_width=0)
    fig.add_hline(y=waspada, line=dict(color=COLOR_WARN, dash="dot", width=1),
                  annotation_text="Waspada", annotation_font_color=COLOR_WARN)
    fig.add_hline(y=bahaya, line=dict(color=COLOR_DANGER, dash="dot", width=1),
                  annotation_text="Bahaya", annotation_font_color=COLOR_DANGER)

    base_layout(fig, "Getaran Dinamis (gravitasi dibuang)")
    fig.update_xaxes(tickformat="%H:%M:%S")
    fig.update_yaxes(title_text="m/s²", range=[0, ymax])
    return fig


def gauge_chart(rms: float, waspada: float, bahaya: float) -> go.Figure:
    batas = max(bahaya * 1.5, rms * 1.2, 1.0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=rms,
        number=dict(suffix=" m/s²", valueformat=".3f", font=dict(size=32, color="#ffffff")),
        gauge=dict(
            axis=dict(range=[0, batas], tickcolor=TEXT_MUTED, tickfont=dict(color=TEXT_MUTED)),
            bar=dict(color="#ffffff", thickness=0.22),
            bgcolor=TRANSPARENT,
            borderwidth=0,
            steps=[
                dict(range=[0, waspada], color=COLOR_OK),
                dict(range=[waspada, bahaya], color=COLOR_WARN),
                dict(range=[bahaya, batas], color=COLOR_DANGER),
            ],
        ),
    ))
    base_layout(fig, "RMS Getaran")
    return fig


def donut_chart(df: pd.DataFrame) -> go.Figure:
    """Porsi waktu di tiap level (Normal / Waspada / Bahaya)."""
    urut = ["🟢 Normal", "🟡 Waspada", "🔴 Bahaya"]
    hitung = df["level"].value_counts().reindex(urut, fill_value=0)
    fig = go.Figure(go.Pie(
        labels=urut, values=hitung.values, hole=0.66, sort=False,
        marker=dict(colors=[COLOR_OK, COLOR_WARN, COLOR_DANGER],
                    line=dict(color="#0a0e1a", width=3)),
        textinfo="percent", textfont=dict(color="#fff", size=13),
        hovertemplate="%{label}: %{value} data (%{percent})<extra></extra>",
    ))
    base_layout(fig, "Distribusi Level Getaran")
    fig.update_layout(
        showlegend=True, hovermode="closest",
        legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center"),
        annotations=[dict(text=f"<b>{len(df):,}</b><br>data", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=18, color="#fff"))],
    )
    return fig


def histogram_chart(df: pd.DataFrame, waspada: float, bahaya: float) -> go.Figure:
    fig = go.Figure(go.Histogram(
        x=df["dinamis"], nbinsx=30,
        marker=dict(color=COLOR_ACCENT, line=dict(color="#0a0e1a", width=1)),
        opacity=0.85, hovertemplate="%{x:.2f} m/s²: %{y} data<extra></extra>",
    ))
    fig.add_vline(x=waspada, line=dict(color=COLOR_WARN, dash="dot", width=1.3))
    fig.add_vline(x=bahaya, line=dict(color=COLOR_DANGER, dash="dot", width=1.3))
    base_layout(fig, "Sebaran Nilai Getaran Dinamis")
    fig.update_layout(bargap=0.05, hovermode="closest")
    fig.update_xaxes(title_text="m/s²")
    fig.update_yaxes(title_text="Jumlah data")
    return fig


def fft_chart(freq, amp, dominan: float) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=freq, y=amp, name="Amplitudo", mode="lines",
        line=dict(color=COLOR_FFT, width=2.2),
        fill="tozeroy", fillcolor="rgba(167,139,250,0.20)",
    ))
    fig.add_vline(x=dominan, line=dict(color=COLOR_ACCENT, dash="dot", width=1.5),
                  annotation_text=f"{dominan:.2f} Hz", annotation_font_color=COLOR_ACCENT)

    base_layout(fig, "Spektrum Frekuensi (FFT dari resultan)", height=380)
    fig.update_xaxes(title_text="Frekuensi (Hz)")
    fig.update_yaxes(title_text="Amplitudo (m/s²)")
    return fig


# ==================================================================
# 7. KOMPONEN UI
# ==================================================================
def show_chart(fig: go.Figure, key: str) -> None:
    cfg = {"displayModeBar": False}
    try:
        st.plotly_chart(fig, width="stretch", key=key, config=cfg)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key, config=cfg)


def show_df(df: pd.DataFrame, **kwargs) -> None:
    """Tampilkan tabel; kompatibel dengan versi Streamlit lama & baru."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def panel_title(text: str) -> None:
    st.markdown(f'<div class="ptitle">{text}</div>', unsafe_allow_html=True)


def info_row(label: str, value) -> str:
    return f'<div class="info-row"><span>{label}</span><b>{value}</b></div>'


def sparkline(values, color: str, w: int = 200, h: int = 34) -> str:
    """SVG garis mini (tanpa library tambahan)."""
    v = np.asarray(values, dtype=float)
    if len(v) < 2:
        return ""
    lo, hi = float(v.min()), float(v.max())
    rentang = (hi - lo) or 1.0
    xs = np.linspace(0, w, len(v))
    ys = h - 3 - (v - lo) / rentang * (h - 6)
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    gid = f"g{abs(hash((color, len(v)))) % 99999}"
    return (
        f'<svg class="kpi-spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" width="100%" height="{h}">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity=".45"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="0,{h} {pts} {w},{h}" fill="url(#{gid})"/>'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def kpi_card(col, label: str, value: str, unit: str = "",
             delta: float | None = None, accent: str = COLOR_ACCENT,
             spark=None) -> None:
    """Kartu angka dengan garis aksen, delta berwarna, dan sparkline opsional."""
    delta_html = ""
    if delta is not None:
        arrow = "▲" if delta > 0 else "▼" if delta < 0 else "■"
        kelas = "up" if delta > 0 else "down" if delta < 0 else ""
        delta_html = f'<div class="kpi-delta {kelas}">{arrow} {delta:+.3f} dari data sebelumnya</div>'
    spark_html = sparkline(spark, accent) if spark is not None else ""

    with col:
        st.markdown(
            f'<div class="kpi" style="--accent:{accent}">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}<span class="kpi-unit"> {unit}</span></div>'
            f'{delta_html}{spark_html}</div>',
            unsafe_allow_html=True,
        )


def status_card(col, teks: str, warna: str, rms: float, bahaya: float) -> None:
    persen = (rms / bahaya * 100) if bahaya > 0 else 0
    lebar = min(persen, 100)
    with col:
        st.markdown(
            f'<div class="kpi" style="--accent:{warna}">'
            f'<div class="kpi-label">🏭 STATUS MESIN</div>'
            f'<div class="kpi-status">{teks}</div>'
            f'<div class="kpi-delta">{persen:.0f}% dari batas bahaya</div>'
            f'<div class="meter"><div style="width:{lebar:.0f}%"></div></div></div>',
            unsafe_allow_html=True,
        )


def chips(df: pd.DataFrame) -> str:
    """Ringkasan jumlah data per level."""
    hitung = df["level"].value_counts()
    item = [("🟢 Normal", COLOR_OK), ("🟡 Waspada", COLOR_WARN), ("🔴 Bahaya", COLOR_DANGER)]
    html = "".join(
        f'<span class="chip" style="--c:{w}">{n}<b>{int(hitung.get(n, 0)):,}</b></span>'
        for n, w in item
    )
    return f'<div class="chips">{html}</div>'


# ==================================================================
# 8. SIDEBAR
# ==================================================================
def render_sidebar() -> Settings:
    with st.sidebar:
        st.markdown('<div class="side-brand">⚙️ VIBRATION MONITOR</div>', unsafe_allow_html=True)
        st.caption("ADXL345 · Arduino · MySQL")

        st.markdown("### Tampilan Data")
        pilihan = st.selectbox("Jumlah data ditampilkan", PILIHAN_JUMLAH_DATA, index=1)
        auto = st.toggle("Auto refresh", value=True)
        interval = st.slider("Interval refresh (detik)", 1, 30, 3)

        st.markdown("### Batas Status")
        st.caption(
            "Berdasarkan RMS getaran dinamis. Nilai bawaan hanya contoh, "
            "sesuaikan dengan standar pengujian Anda."
        )
        waspada = st.number_input("Batas Waspada (m/s²)", value=2.0, step=0.5, min_value=0.0)
        bahaya = st.number_input("Batas Bahaya (m/s²)", value=5.0, step=0.5, min_value=0.0)
        st.button("🔄 Refresh sekarang")

    return Settings(
        limit=None if pilihan == "Semua" else int(pilihan),
        auto_refresh=auto,
        interval=interval,
        waspada=waspada,
        bahaya=bahaya,
    )


# ==================================================================
# 9. BAGIAN-BAGIAN DASHBOARD
# ==================================================================
def render_header(now: datetime, aktif: bool, usia: float) -> None:
    gear = "gear" if aktif else "gear-stop"
    gear_rev = "gear-rev" if aktif else "gear-stop"
    live_class, live_text = ("on", "LIVE") if aktif else ("off", "OFFLINE")

    st.markdown(
        f'<div class="topbar">'
        f'<div>'
        f'<div class="topbar-title"><span class="{gear}">⚙️</span> BATTERY VIBRATION MONITORING '
        f'<span class="{gear_rev}">⚙️</span></div>'
        f'<div class="topbar-sub">Monitoring percepatan getaran 3 sumbu · ADXL345</div>'
        f'</div>'
        f'<div class="topbar-right">'
        f'<span class="live {live_class}"><span class="dot"></span>{live_text}</span>'
        f'<div class="topbar-time">{now:%d/%m/%Y · %H:%M:%S}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    if not aktif:
        st.warning(
            f"Tidak ada data baru selama {usia:.0f} detik. "
            "Periksa apakah program logger dan sensor masih berjalan."
        )


def render_kpi(df: pd.DataFrame, rms: float, cfg: Settings) -> None:
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    k1, k2, k3, k4, k5 = st.columns(5)

    for col, c in zip((k1, k2, k3), AXES):
        delta = float(latest[c] - prev[c]) if prev is not None else None
        kpi_card(col, f"{AXIS_ICON[c]} {AXIS_NAME[c].upper()}",
                 f"{latest[c]:.3f}", "m/s²", delta, AXIS_COLOR[c],
                 spark=df[c].tail(JUMLAH_SPARK))

    teks, warna = status_info(rms, cfg.waspada, cfg.bahaya)
    kpi_card(k4, "🔧 RMS GETARAN", f"{rms:.3f}", "m/s²", accent=warna,
             spark=df["dinamis"].tail(JUMLAH_SPARK))
    status_card(k5, teks, warna, rms, cfg.bahaya)


def render_info_dan_statistik(df: pd.DataFrame, total: int, rms: float, cfg: Settings) -> None:
    latest = df.iloc[-1]
    c_info, c_stat = st.columns([1, 2])

    with c_info:
        with st.container(border=True):
            panel_title("🔩 Info Data")
            durasi = (df[TIME_COL].iloc[-1] - df[TIME_COL].iloc[0]).total_seconds()
            st.markdown(
                info_row("Total data tersimpan", f"{total:,}")
                + info_row("Data ditampilkan", f"{len(df):,}")
                + info_row("Rentang waktu", f"{durasi:,.0f} detik")
                + info_row("Data pertama", f"{df[TIME_COL].iloc[0]:%d/%m %H:%M:%S}")
                + info_row("Data terakhir", f"{latest[TIME_COL]:%d/%m %H:%M:%S}"),
                unsafe_allow_html=True,
            )

    with c_stat:
        with st.container(border=True):
            panel_title("📋 Statistik Percepatan")
            stat = buat_statistik(df, rms)
            fmt = "%.3f"
            show_df(stat, column_config={
                "Sumbu": st.column_config.TextColumn("Sumbu", width="medium"),
                "Min": st.column_config.NumberColumn("Min (m/s²)", format=fmt),
                "Maks": st.column_config.NumberColumn("Maks (m/s²)", format=fmt),
                "Rata-rata": st.column_config.NumberColumn("Rata-rata (m/s²)", format=fmt),
                "RMS Getaran": st.column_config.ProgressColumn(
                    "RMS Getaran (m/s²)", format=fmt,
                    min_value=0.0, max_value=float(max(cfg.bahaya, stat["RMS Getaran"].max(), 1.0)),
                ),
            })
            st.caption(
                "RMS Getaran dihitung dari simpangan terhadap rata-rata, "
                "sehingga pengaruh gravitasi (≈ 9,8 m/s²) tidak ikut terhitung."
            )


def render_tab_grafik(df: pd.DataFrame, rms: float, cfg: Settings) -> None:
    with st.container(border=True):
        show_chart(waveform_chart(df), "g_wave")

    g1, g2 = st.columns([2, 1])
    with g1:
        with st.container(border=True):
            show_chart(dynamic_chart(df, cfg.waspada, cfg.bahaya), "g_dyn")
    with g2:
        with st.container(border=True):
            show_chart(gauge_chart(rms, cfg.waspada, cfg.bahaya), "g_gauge")

    h1, h2 = st.columns([1, 2])
    with h1:
        with st.container(border=True):
            show_chart(donut_chart(df), "g_donut")
    with h2:
        with st.container(border=True):
            show_chart(histogram_chart(df, cfg.waspada, cfg.bahaya), "g_hist")


def render_tab_fft(df: pd.DataFrame) -> None:
    hasil = spektrum(df)
    if hasil is None:
        st.info(
            f"Spektrum butuh minimal {MIN_SAMPEL_FFT} data dengan selisih waktu yang valid. "
            "Tampilkan lebih banyak data lewat sidebar."
        )
        return

    freq, amp, fs, dominan = hasil
    f1, f2 = st.columns(2)
    kpi_card(f1, "🎛️ FREKUENSI DOMINAN (PERKIRAAN)", f"{dominan:.2f}", "Hz", accent=COLOR_FFT)
    kpi_card(f2, "📡 LAJU SAMPLING (PERKIRAAN)", f"{fs:.1f}", "Hz", accent=COLOR_ACCENT)

    st.write("")
    with st.container(border=True):
        show_chart(fft_chart(freq, amp, dominan), "g_fft")

    st.caption(
        f"Perkiraan ini memakai waktu penerimaan data (`{TIME_COL}`). "
        "Hasilnya akurat hanya jika data masuk dengan laju yang kira-kira tetap."
    )


def render_tab_data(df: pd.DataFrame, now: datetime, cfg: Settings) -> None:
    """Tabel riwayat: filter level, urutan, jumlah baris, progress bar, unduh CSV."""
    data = tambah_level(df, cfg.waspada, cfg.bahaya)

    with st.container(border=True):
        panel_title("🗂️ Riwayat Data Sensor")
        st.markdown(chips(data), unsafe_allow_html=True)

        f1, f2, f3 = st.columns([2, 1, 1])
        level = f1.multiselect(
            "Filter level", ["🟢 Normal", "🟡 Waspada", "🔴 Bahaya"],
            default=["🟢 Normal", "🟡 Waspada", "🔴 Bahaya"], key="flt_level",
        )
        urutan = f2.selectbox("Urutkan", ["Terbaru", "Terlama", "Getaran tertinggi"], key="flt_urut")
        baris = f3.selectbox("Jumlah baris", [50, 100, 250, 500, "Semua"], key="flt_baris")

        t = data[data["level"].isin(level)]
        if urutan == "Terbaru":
            t = t.sort_values("id", ascending=False)
        elif urutan == "Terlama":
            t = t.sort_values("id", ascending=True)
        else:
            t = t.sort_values("dinamis", ascending=False)
        if baris != "Semua":
            t = t.head(int(baris))

        kolom = [c for c in ["id", TIME_COL] + AXES + ["resultan", "dinamis", "level"] if c in t.columns]
        t = t[kolom]

        f = "%.3f"
        maks = float(max(cfg.bahaya * 1.2, data["dinamis"].max(), 1.0))
        show_df(t, height=480, column_config={
            "id": st.column_config.NumberColumn("ID", format="%d", width="small"),
            TIME_COL: st.column_config.DatetimeColumn("🕒 Waktu Diterima", format="DD/MM/YYYY HH:mm:ss"),
            "ax_ms2": st.column_config.NumberColumn("↔️ X (m/s²)", format=f),
            "ay_ms2": st.column_config.NumberColumn("↕️ Y (m/s²)", format=f),
            "az_ms2": st.column_config.NumberColumn("⏺️ Z (m/s²)", format=f),
            "resultan": st.column_config.NumberColumn("🧭 Resultan (m/s²)", format=f),
            "dinamis": st.column_config.ProgressColumn(
                "📳 Dinamis (m/s²)", format=f, min_value=0.0, max_value=maks),
            "level": st.column_config.TextColumn("Level", width="small"),
        })

        st.caption(f"Menampilkan {len(t):,} dari {len(data):,} data.")

        csv = t.rename(columns={
            "id": "ID", TIME_COL: "Waktu Diterima",
            "ax_ms2": "X (m/s2)", "ay_ms2": "Y (m/s2)", "az_ms2": "Z (m/s2)",
            "resultan": "Resultan (m/s2)", "dinamis": "Dinamis (m/s2)", "level": "Level",
        }).to_csv(index=False).encode("utf-8-sig")   # utf-8-sig: aman dibuka di Excel
        st.download_button(
            "⬇️ Unduh data (CSV)", csv,
            file_name=f"data_adxl345_{now:%Y%m%d_%H%M%S}.csv", mime="text/csv",
        )


def render_footer(interval: int) -> None:
    st.markdown(
        '<div class="footer-box">⚙️ Battery Vibration Monitoring · ADXL345, Arduino, Python, dan MySQL '
        f'· Diperbarui setiap {interval} detik</div>',
        unsafe_allow_html=True,
    )


# ==================================================================
# 10. DASHBOARD UTAMA & ENTRY POINT
# ==================================================================
def load_and_validate(cfg: Settings):
    raw, total, error = load_data(cfg.limit)

    if error:
        st.error(f"Koneksi MySQL gagal: {error}")
        if not DB_CONFIG["password"]:
            st.warning("`DB_PASSWORD` belum terbaca (kosong). Isi lewat environment variable "
                       "atau file `.streamlit/secrets.toml`, lalu jalankan ulang Streamlit.")
        st.info(
            "Periksa: MySQL sudah berjalan, password (environment variable `DB_PASSWORD`), "
            f"user dan nama database benar, serta tabel `{TABLE}` ada."
        )
        return None

    if raw.empty:
        st.warning("Belum ada data pengujian.")
        return None

    try:
        df = prepare(raw)
    except KeyError as e:
        st.error(
            f"Kolom {e} tidak ditemukan di tabel `{TABLE}`. "
            f"Kolom yang dibutuhkan: id, {TIME_COL}, {', '.join(AXES)}."
        )
        return None

    if df.empty:
        st.warning("Belum ada data yang valid.")
        return None

    return df, total


def build_dashboard(cfg: Settings):
    def dashboard() -> None:
        now = datetime.now()

        hasil = load_and_validate(cfg)
        if hasil is None:
            return
        df, total = hasil

        df, rms = analisis(df)
        df = tambah_level(df, cfg.waspada, cfg.bahaya)   # kolom 'level' dipakai donut & tabel
        usia = (now - df.iloc[-1][TIME_COL]).total_seconds()
        aktif = usia <= DATA_AKTIF_DETIK

        render_header(now, aktif, usia)
        render_kpi(df, rms, cfg)
        st.write("")
        render_info_dan_statistik(df, total, rms, cfg)
        st.write("")

        tab_grafik, tab_fft, tab_data = st.tabs(
            ["📈 Grafik", "🎛️ Spektrum (FFT)", "🗂️ Riwayat Data"]
        )
        with tab_grafik:
            render_tab_grafik(df, rms, cfg)
        with tab_fft:
            render_tab_fft(df)
        with tab_data:
            render_tab_data(df, now, cfg)

        render_footer(cfg.interval)

    return dashboard


def main() -> None:
    apply_css()
    cfg = render_sidebar()
    dashboard = build_dashboard(cfg)
    st.fragment(run_every=cfg.interval if cfg.auto_refresh else None)(dashboard)()


main()
