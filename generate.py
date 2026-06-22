#!/usr/bin/env python3
"""
Sakos driftsrapport — microsite generator.

Læser de to protokol-Sheets (Protokol 2025 + 2026), beregner alle nøgletal,
og producerer en statisk HTML der ligger som /docs/index.html samt en arkiv-version.

Designet til at køre i GitHub Actions hver 14. dag.
"""

import csv
import re
import base64
import io
import os
import sys
import urllib.request
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ───── Konfiguration (kan overrides via env vars) ─────
PROTOKOL_2025_ID = os.getenv("PROTOKOL_2025_ID", "1hfkGRBkqH_sZDjKyUuLhUixCjRITl1-FXAJp3IrBH8U")
PROTOKOL_2026_ID = os.getenv("PROTOKOL_2026_ID", "1LvHM1mfl7ZeN5-9XG4uRE0XzKW3JV7F1q4sZQkNk0cg")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "docs"))
SAKO_IMAGE = Path(os.getenv("SAKO_IMAGE", "Sako.webp"))
SAKO_IMAGE_FALLBACK = Path("Sako.png")

DATE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")

# ───── Hjælpefunktioner ─────

def fetch_sheet_csv(file_id: str) -> str:
    """Hent en Google Sheet som CSV. Sheet skal være delt 'Anyone with the link'."""
    url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv&gid=0"
    print(f"  Henter: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Sako-Statistics/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")

def color_for(v):
    if v < 12: return "#b95757"
    if v < 14: return "#d4a73a"
    if v < 16: return "#5c8a5c"
    return "#3b6b3b"

def status_for(v):
    if v < 12: return ("🔴", "pres på drift")
    if v < 14: return ("🟡", "ustabil drift")
    if v < 16: return ("🟢", "alm. drift")
    return ("🌲", "ønsket niveau")

def parse_protokol(csv_text: str, year_filter: int):
    rows = list(csv.reader(csv_text.splitlines()))
    if not rows:
        raise RuntimeError("Tom CSV-fil")
    header_row_idx = None
    first_dog_col = None
    for i, row in enumerate(rows[:30]):
        for j, c in enumerate(row):
            if c.strip() == "Ada":
                header_row_idx = i
                first_dog_col = j
                break
        if header_row_idx is not None:
            break
    if first_dog_col is None:
        raise RuntimeError("Kunne ikke finde 'Ada' i header")
    dog_names = [c.strip() for c in rows[header_row_idx][first_dog_col:]]

    daily = []
    per_dog = defaultdict(int)
    for row in rows:
        if not row:
            continue
        ds = row[0].strip()
        if not DATE_PATTERN.match(ds):
            continue
        try:
            dt = datetime.strptime(ds, "%d/%m/%y")
        except ValueError:
            continue
        if dt.year != year_filter:
            continue
        bm = mk = other = 0
        for k, cell in enumerate(row[first_dog_col:]):
            v = cell.strip().lower()
            if not v or v == "x":
                continue
            if v == "bm":
                bm += 1
            elif v.startswith("mk"):
                mk += 1
            else:
                other += 1
            if k < len(dog_names) and dog_names[k]:
                per_dog[dog_names[k]] += 1
        total = bm + mk + other
        if total >= 2:
            daily.append({"dt": dt, "total": total, "bm": bm, "mk": mk})
    return daily, per_dog

def aggregate_weekly(daily):
    weekly = defaultdict(lambda: {"total": 0, "bm": 0, "mk": 0, "open": 0})
    for d in daily:
        yr, wk, _ = d["dt"].isocalendar()
        weekly[(yr, wk)]["open"] += 1
        weekly[(yr, wk)]["total"] += d["total"]
        weekly[(yr, wk)]["bm"] += d["bm"]
        weekly[(yr, wk)]["mk"] += d["mk"]
    return weekly

def aggregate_monthly(daily):
    monthly = defaultdict(lambda: {"total": 0, "days": 0})
    for d in daily:
        key = (d["dt"].year, d["dt"].month)
        monthly[key]["total"] += d["total"]
        monthly[key]["days"] += 1
    return monthly

def load_sako_images():
    img_path = SAKO_IMAGE if SAKO_IMAGE.exists() else SAKO_IMAGE_FALLBACK
    if not img_path.exists():
        return None, None
    from PIL import Image
    src = Image.open(img_path)
    w, h = src.size
    # Hero
    hero = src.copy()
    hero.thumbnail((500, 700), Image.Resampling.LANCZOS)
    hero_buf = io.BytesIO()
    hero.save(hero_buf, format="JPEG", quality=85, optimize=True)
    hero_b64 = base64.b64encode(hero_buf.getvalue()).decode()
    # Avatar
    crop_size = min(w, h) // 2
    left = (w - crop_size) // 2
    top = h // 6
    avatar = src.crop((left, top, left + crop_size, top + crop_size))
    avatar.thumbnail((200, 200), Image.Resampling.LANCZOS)
    av_buf = io.BytesIO()
    avatar.save(av_buf, format="JPEG", quality=88, optimize=True)
    av_b64 = base64.b64encode(av_buf.getvalue()).decode()
    return hero_b64, av_b64

def generate_pote_noter_placeholders():
    """Returnerer placeholder-tekst der erstattes af Cowork-agenten med ægte ræsonnement."""
    return {
        "dpd":   "<!--POTE_DPD-->",
        "yoy":   "<!--POTE_YOY-->",
        "month": "<!--POTE_MONTH-->",
        "top":   "<!--POTE_TOP-->",
    }

def generate_pote_noter_fallback(d):
    notes = {}
    last_week = d["last_8_weeks"][-1] if d["last_8_weeks"] else None
    above_target = sum(1 for w in d["last_8_weeks"] if w["avg"] >= 16)
    total_weeks = len(d["last_8_weeks"])
    if last_week and last_week["avg"] >= 16:
        notes["dpd"] = f"<strong>Sakos pote-note:</strong> {above_target} ud af {total_weeks} uger på mørkegrøn — det er sgu flot drift. Sidste uge ramte {last_week['avg']} hunde/dag."
    elif last_week and last_week["avg"] >= 14:
        notes["dpd"] = f"<strong>Sakos pote-note:</strong> {above_target} af {total_weeks} uger på ønsket niveau. Sidste uge: {last_week['avg']} hunde/dag — alm. drift."
    elif last_week and last_week["avg"] >= 12:
        notes["dpd"] = f"<strong>Sakos pote-note:</strong> Sidste uge dippede til {last_week['avg']} hunde/dag — ustabil drift. Holdes øje med."
    elif last_week:
        notes["dpd"] = f"<strong>Sakos pote-note:</strong> Sidste uge kun {last_week['avg']} hunde/dag — pres på drift. Værd at handle på."
    else:
        notes["dpd"] = "<strong>Sakos pote-note:</strong> Mangler data."

    if d["yoy_diff_pct"] >= 10:
        notes["yoy"] = f"<strong>Sakos pote-note:</strong> {d['yoy_diff_pct']:+.1f}% over sidste år ({d['common_avg_26']:.1f} vs {d['common_avg_25']:.1f} hunde/dag). Markant fremgang."
    elif d["yoy_diff_pct"] >= 2:
        notes["yoy"] = f"<strong>Sakos pote-note:</strong> {d['yoy_diff_pct']:+.1f}% over sidste år. Stille, stabil vækst."
    elif d["yoy_diff_pct"] >= -2:
        notes["yoy"] = f"<strong>Sakos pote-note:</strong> Stort set på niveau med sidste år ({d['yoy_diff_pct']:+.1f}%). Hund-ærlig stabilitet."
    elif d["yoy_diff_pct"] >= -10:
        notes["yoy"] = f"<strong>Sakos pote-note:</strong> Tilbagegang på {d['yoy_diff_pct']:+.1f}% mod sidste år. Ikke alarmerende, men værd at undersøge."
    else:
        notes["yoy"] = f"<strong>Sakos pote-note:</strong> {d['yoy_diff_pct']:+.1f}% bagud mod sidste år. Værd at gøre noget ved."

    top26_names = {n for n, _ in d["top_26"]}
    top25_names = {n for n, _ in d["top_25"]}
    common = top26_names & top25_names
    lost = top25_names - top26_names
    new = top26_names - top25_names
    parts = []
    if common:
        parts.append(f"Stamhundene {', '.join(sorted(common)[:4])} er gengangere begge år — rygraden.")
    if lost:
        parts.append(f"Tabt fra 2025: {', '.join(sorted(lost)[:3])} — ring til ejerne.")
    if new:
        parts.append(f"Nye top-10 i 2026: {', '.join(sorted(new)[:3])}.")
    notes["top"] = "<strong>Sakos pote-note:</strong> " + " ".join(parts) if parts else "<strong>Sakos pote-note:</strong> Top-10 stort set uændret."

    if d["months_data"]:
        biggest_up = max(d["months_data"], key=lambda m: m["t2026"] - m["t2025"])
        biggest_down = min(d["months_data"], key=lambda m: m["t2026"] - m["t2025"])
        latest = d["months_data"][-1]
        if biggest_up["t2026"] - biggest_up["t2025"] > 20:
            notes["month"] = f"<strong>Sakos pote-note:</strong> {biggest_up['name']} var bedst mod 2025 (+{biggest_up['t2026']-biggest_up['t2025']}). {biggest_down['name']} svagest ({biggest_down['t2026']-biggest_down['t2025']:+d}). Nuværende måned: {latest['perday_2026']} hunde/åbningsdag."
        else:
            notes["month"] = f"<strong>Sakos pote-note:</strong> Månederne ligger tæt på 2025. Nuværende: {latest['perday_2026']} hunde/åbningsdag i {latest['name']}."
    else:
        notes["month"] = ""
    return notes

# ───── Arkiv-scanning og navigation ─────

def discover_archives(output_dir: Path):
    """Scan eksisterende arkiv-filer og returnér sorterede metadata."""
    archives = []
    arkiv = output_dir / "arkiv"
    if arkiv.exists():
        for f in arkiv.glob("Driftsrapport_*.html"):
            m = re.match(r"Driftsrapport_(\d{4}-\d{2}-\d{2})_uge(\d+)", f.stem)
            if m:
                archives.append({"date": m.group(1), "week": int(m.group(2)), "filename": f.name})
    archives.sort(key=lambda x: x["date"], reverse=True)
    return archives

def build_topmenu(archives, from_archive: bool, current_file: str = None):
    """Bygger top-navigation. from_archive bestemmer relative paths."""
    aktuel_href = "../index.html" if from_archive else "index.html"
    arkiv_prefix = "" if from_archive else "arkiv/"

    # Gruppér efter år
    by_year = defaultdict(list)
    for a in archives:
        by_year[a["date"][:4]].append(a)

    items_html = []
    for yr in sorted(by_year.keys(), reverse=True):
        items_html.append(f'<li class="nav-year">{yr}</li>')
        for a in by_year[yr]:
            is_current = (a["filename"] == current_file)
            cls = ' class="active"' if is_current else ""
            items_html.append(
                f'<li{cls}><a href="{arkiv_prefix}{a["filename"]}">'
                f'<span class="wk">U{a["week"]:02d}</span>'
                f'<span class="dt">{a["date"]}</span></a></li>'
            )

    if not items_html:
        items_html.append('<li class="empty">Ingen arkiv-rapporter endnu</li>')

    return f"""<nav class="topnav">
  <div class="nav-inner">
    <a href="{aktuel_href}" class="nav-brand">🐾 Sakos Statistik <span class="nav-sub">Hundehaven Potefryd</span></a>
    <div class="nav-archive">
      <button class="nav-toggle" onclick="document.querySelector('.nav-list').classList.toggle('open')">📚 Arkiv ▾</button>
      <ul class="nav-list">{"".join(items_html)}</ul>
    </div>
  </div>
</nav>"""

# ───── HTML-skabelon (returneres som streng) ─────

def build_html(d, topmenu_html="", use_placeholders=True):
    # Standard: brug placeholders som Cowork-agenten erstatter med ægte Claude-ræsonnement
    # Hvis use_placeholders=False, brug de Python-baserede fallback-noter (i tilfælde af manuel kørsel)
    pote = generate_pote_noter_placeholders() if use_placeholders else generate_pote_noter_fallback(d)
    last_week = d["last_8_weeks"][-1] if d["last_8_weeks"] else None
    last_status = status_for(last_week["avg"]) if last_week else ("—", "—")
    yoy_arrow = "▲" if d["yoy_diff_pct"] > 0 else "▼" if d["yoy_diff_pct"] < 0 else "→"
    yoy_class = "up" if d["yoy_diff_pct"] > 0 else "down" if d["yoy_diff_pct"] < 0 else ""

    # Sako-billeder
    if d["avatar_b64"]:
        avatar_img = f'<img class="sako-avatar" alt="Sako" src="data:image/jpeg;base64,{d["avatar_b64"]}">'
        av_mini = f'<img class="av-mini" alt="Sako" src="data:image/jpeg;base64,{d["avatar_b64"]}">'
    else:
        avatar_img = '<div class="sako-avatar fallback">🐕</div>'
        av_mini = '<div class="av-mini fallback">🐕</div>'

    if d["hero_b64"]:
        hero_card = f'''<section class="card" style="text-align:center;padding:24px;">
    <h2 style="font-size:14px;margin-bottom:12px;color:#5a6557;">📊 Mød jeres statistiker</h2>
    <img src="data:image/jpeg;base64,{d["hero_b64"]}" alt="Sako" style="max-width:380px;width:100%;border-radius:12px;box-shadow:0 4px 14px rgba(0,0,0,0.12);">
    <p style="font-size:12px;color:#6a7560;margin:14px 0 0;font-style:italic;">"Når dataen lægger sig stille, lytter jeg." — Sako 🐾</p>
  </section>'''
    else:
        hero_card = ""

    # Tabel-rækker
    week_rows = []
    for w in d["last_8_weeks"]:
        emoji, label = status_for(w["avg"])
        is_latest = (w == d["last_8_weeks"][-1])
        bg = ' style="background:#f0f7ee;"' if is_latest else ""
        b1 = "<strong>" if is_latest else ""
        b2 = "</strong>" if is_latest else ""
        week_rows.append(f'<tr{bg}><td>{b1}{w["label"]}{b2}</td><td>Uge {w["wk"]}</td><td class="num">{b1}{w["total"]}{b2}</td><td class="num">{w["open"]}</td><td class="num">{b1}{w["avg"]}{b2}</td><td>{emoji} {label}</td></tr>')

    yoy_rows = []
    for y in d["yoy_data"]:
        diff = y["v2026"] - y["v2025"]
        cls = "up" if diff > 0 else "down" if diff < -0.05 else ""
        sign = "+" if diff > 0 else ""
        yoy_rows.append(f'<tr><td>{y["label"]}</td><td class="num">{y["v2025"]}</td><td class="num">{y["v2026"]}</td><td class="num {cls}">{sign}{diff:.1f}</td></tr>')

    month_rows = []
    for m in d["months_data"]:
        diff = m["t2026"] - m["t2025"]
        cls = "up" if diff > 0 else "down" if diff < 0 else ""
        sign = "+" if diff > 0 else ""
        month_rows.append(f'<tr><td>{m["name"]}</td><td class="num">{m["t2025"]}</td><td class="num">{m["t2026"]}</td><td class="num {cls}">{sign}{diff}</td><td class="num">{m["perday_2026"]}</td></tr>')

    top26_rows = []
    for i, (name, count) in enumerate(d["top_26"], 1):
        medal = ["🥇 1", "🥈 2", "🥉 3"][i-1] if i <= 3 else str(i)
        pct = round(count / d["total_open_26"] * 100) if d["total_open_26"] else 0
        top26_rows.append(f'<tr><td>{medal}</td><td>{name}</td><td class="num">{count}</td><td class="num">{pct}%</td></tr>')
    sako_pct = round(d["sako_count"] / d["total_open_26"] * 100) if d["total_open_26"] else 0
    sako_row = ""
    if d["sako_rank"] and d["sako_rank"] > 10:
        sako_row = f'<tr style="background:#fdf6e3;font-weight:600;"><td>{d["sako_rank"]}</td><td>Sako 🤓 (mig)</td><td class="num">{d["sako_count"]}</td><td class="num">{sako_pct}%</td></tr>'

    top25_rows = []
    for i, (name, count) in enumerate(d["top_25"], 1):
        medal = ["🥇 1", "🥈 2", "🥉 3"][i-1] if i <= 3 else str(i)
        pct = round(count / d["total_open_25"] * 100) if d["total_open_25"] else 0
        top25_rows.append(f'<tr><td>{medal}</td><td>{name}</td><td class="num">{count}</td><td class="num">{pct}%</td></tr>')

    # Chart data som JSON for Chart.js
    dpd_labels = [w["label"] for w in d["last_8_weeks"]]
    dpd_values = [w["avg"] for w in d["last_8_weeks"]]
    yoy_labels = [y["label"] for y in d["yoy_data"]]
    yoy_2025 = [y["v2025"] for y in d["yoy_data"]]
    yoy_2026 = [y["v2026"] for y in d["yoy_data"]]
    month_labels = [m["name"] for m in d["months_data"]]
    month_2025 = [m["t2025"] for m in d["months_data"]]
    month_2026 = [m["t2026"] for m in d["months_data"]]

    today_str = d["today"].strftime("%d. %B %Y")
    for en, da in [("January","januar"),("February","februar"),("March","marts"),("April","april"),("May","maj"),("June","juni"),("July","juli"),("August","august"),("September","september"),("October","oktober"),("November","november"),("December","december")]:
        today_str = today_str.replace(en, da)

    import json
    return f"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sakos Driftsrapport — Hundehaven Potefryd</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif; background: #f5f8f3; color: #1f2a1f; line-height: 1.45; }}
  /* Top navigation */
  .topnav {{ background: #1f3a1f; color: white; box-shadow: 0 2px 8px rgba(0,0,0,0.1); position: sticky; top: 0; z-index: 100; }}
  .topnav .nav-inner {{ max-width: 1100px; margin: 0 auto; padding: 12px 28px; display: flex; align-items: center; justify-content: space-between; gap: 20px; }}
  .topnav .nav-brand {{ color: white; text-decoration: none; font-weight: 600; font-size: 16px; }}
  .topnav .nav-brand .nav-sub {{ font-weight: 400; opacity: 0.65; font-size: 13px; margin-left: 6px; }}
  .topnav .nav-archive {{ position: relative; }}
  .topnav .nav-toggle {{ background: rgba(255,255,255,0.12); color: white; border: 0; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; }}
  .topnav .nav-toggle:hover {{ background: rgba(255,255,255,0.2); }}
  .topnav .nav-list {{ position: absolute; right: 0; top: calc(100% + 6px); background: white; color: #1f2a1f; border-radius: 10px; box-shadow: 0 6px 20px rgba(0,0,0,0.15); padding: 8px 0; min-width: 220px; max-height: 60vh; overflow-y: auto; list-style: none; margin: 0; display: none; }}
  .topnav .nav-list.open {{ display: block; }}
  .topnav .nav-list li {{ padding: 0; }}
  .topnav .nav-list li.nav-year {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #8a8174; padding: 10px 16px 4px; font-weight: 600; }}
  .topnav .nav-list li.empty {{ padding: 14px 16px; color: #8a8174; font-size: 13px; font-style: italic; }}
  .topnav .nav-list li a {{ display: flex; justify-content: space-between; padding: 8px 16px; color: #1f2a1f; text-decoration: none; font-size: 13px; gap: 14px; }}
  .topnav .nav-list li a:hover {{ background: #f0f7ee; }}
  .topnav .nav-list li.active a {{ background: #f0f7ee; font-weight: 600; color: #2c6f2c; }}
  .topnav .nav-list li a .wk {{ font-weight: 600; color: #2c6f2c; }}
  .topnav .nav-list li a .dt {{ color: #6a7560; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 28px 48px; }}
  header.hero {{ margin-bottom: 22px; padding: 22px 26px; background: linear-gradient(135deg, #4a8c3c, #2c6f2c); color: white; border-radius: 14px; box-shadow: 0 4px 14px rgba(44,111,44,0.18); display: flex; gap: 22px; align-items: center; }}
  header.hero .hero-text {{ flex: 1; }}
  header.hero h1 {{ margin: 0 0 4px; font-size: 22px; font-weight: 600; }}
  header.hero .sub {{ font-size: 13px; opacity: 0.92; }}
  header.hero .meta {{ display: inline-block; margin-top: 8px; font-size: 11px; background: rgba(255,255,255,0.18); padding: 4px 10px; border-radius: 12px; }}
  .sako-avatar {{ width: 86px; height: 86px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 3px solid rgba(255,255,255,0.4); box-shadow: 0 3px 8px rgba(0,0,0,0.15); display: block; }}
  .sako-byline {{ background: white; padding: 14px 20px; border-radius: 12px; margin-bottom: 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; align-items: center; gap: 14px; border-left: 4px solid #c97d4a; }}
  .sako-byline .av-mini {{ width: 48px; height: 48px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }}
  .sako-byline .by-name {{ font-weight: 600; font-size: 14px; }}
  .sako-byline .by-title {{ font-size: 12px; color: #6a7560; }}
  .sako-byline .by-stats {{ font-size: 11px; color: #8a8174; margin-top: 2px; }}
  .sako-byline .mug {{ background: #fdf6e3; padding: 6px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; color: #5a4820; letter-spacing: 0.04em; border: 1px solid #f0d8a3; }}
  .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 22px; }}
  .kpi {{ background: white; border-radius: 12px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-left: 3px solid transparent; }}
  .kpi .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: #5a6557; font-weight: 600; }}
  .kpi .value {{ font-size: 26px; font-weight: 600; }}
  .kpi .delta, .kpi .subline {{ font-size: 12px; color: #6a7560; }}
  .kpi.hero-metric {{ border-left-color: #4a8c3c; background: #f0f7ee; }}
  .kpi.hero-metric .value {{ font-size: 32px; color: #2c6f2c; }}
  .kpi.total {{ border-left-color: #5c8a5c; }}
  .kpi.year-avg {{ border-left-color: #3b6b3b; }}
  .kpi.yoy {{ border-left-color: #c89538; }}
  .kpi .delta.up {{ color: #2c6f2c; font-weight: 600; }}
  .kpi .delta.down {{ color: #b95757; font-weight: 600; }}
  section.card {{ background: white; border-radius: 12px; padding: 20px 24px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 22px; }}
  section.card.featured {{ border: 1px solid #cbe1c5; }}
  section.card h2 {{ margin: 0 0 6px; font-size: 16px; font-weight: 600; }}
  section.card h2 .pin {{ background: #f0f7ee; color: #2c6f2c; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 500; margin-left: 8px; }}
  section.card h2 .pin.source {{ background: #fef4e0; color: #8a6020; }}
  section.card .helper {{ font-size: 12px; color: #5a6557; margin: 0 0 16px; }}
  .chartbox {{ position: relative; height: 320px; }}
  .chartbox.tall {{ height: 360px; }}
  .chartbox.xtall {{ height: 400px; }}
  .health-strip {{ display: flex; gap: 14px; margin-top: 12px; font-size: 12px; flex-wrap: wrap; padding: 10px 14px; background: #f7faf5; border-radius: 8px; }}
  .health-dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 4px; vertical-align: -1px; }}
  .health-dot.red {{ background: #b95757; }}
  .health-dot.amber {{ background: #d4a73a; }}
  .health-dot.green {{ background: #5c8a5c; }}
  .health-dot.darkgreen {{ background: #3b6b3b; }}
  .footnote {{ font-size: 11px; color: #7a8474; padding: 12px 4px 0; }}
  table.simple {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.simple th, table.simple td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e8ede5; }}
  table.simple th {{ background: #eef2eb; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }}
  table.simple td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  table.simple td.up {{ color: #2c6f2c; font-weight: 600; }}
  table.simple td.down {{ color: #b95757; font-weight: 600; }}
  .sako-note {{ background: linear-gradient(135deg, #fdf6e3, #fbe8c0); border-left: 4px solid #c97d4a; padding: 14px 18px 14px 56px; border-radius: 8px; font-size: 13px; color: #4a3820; margin: 14px 0 0; position: relative; }}
  .sako-note::before {{ content: "🐾"; position: absolute; left: 16px; top: 13px; font-size: 22px; }}
  .sako-note strong {{ color: #6b4818; }}
  @media (max-width: 720px) {{ .kpis {{ grid-template-columns: repeat(2, 1fr); }} .chartbox {{ height: 280px; }} header.hero {{ flex-direction: column; text-align: center; }} }}
</style>
</head>
<body>
{topmenu_html}
<div class="wrap">
  <header class="hero">
    {avatar_img}
    <div class="hero-text">
      <h1>🐾 Hundehaven Potefryd — Bestyrelses-rapport</h1>
      <div class="sub">Operationelle nøgletal og trends · udarbejdet af Statistiker Sako</div>
      <div class="meta">📅 {today_str} · Auto-genereret rapport</div>
    </div>
  </header>

  <div class="sako-byline">
    {av_mini}
    <div style="flex:1">
      <div class="by-name">Sako, Statistiker</div>
      <div class="by-title">Vizsla · Bestyrelsens dataanalytiker · Stamhund hos Hundehaven Potefryd</div>
      <div class="by-stats">📊 Mine egne tal i år: {d["sako_count"]} besøg ({sako_pct}% loyalitet)</div>
    </div>
    <div class="mug">☕ DATA TALER SANDT</div>
  </div>

  {hero_card}

  <div class="kpis">
    <div class="kpi hero-metric">
      <div class="label">⭐ Hunde / dag (sidste hele uge, {last_week["label"] if last_week else "—"})</div>
      <div class="value">{last_week["avg"] if last_week else "—"}</div>
      <div class="delta">{last_status[0]} {last_status[1]} · {last_week["total"] if last_week else 0} hunde i ugen</div>
    </div>
    <div class="kpi total">
      <div class="label">Hunde i alt (i år)</div>
      <div class="value">{d["total_dogs_26"]:,}</div>
      <div class="subline">over {d["total_open_26"]} åbne dage</div>
    </div>
    <div class="kpi year-avg">
      <div class="label">Gns. 2026</div>
      <div class="value">{d["avg_per_day_2026"]:.1f}</div>
      <div class="subline">hunde/dag</div>
    </div>
    <div class="kpi yoy">
      <div class="label">2026 vs 2025 (samme uger)</div>
      <div class="value">{d["yoy_diff_pct"]:+.1f}%</div>
      <div class="delta {yoy_class}">{yoy_arrow} {d["common_avg_26"]:.1f} vs {d["common_avg_25"]:.1f}</div>
    </div>
  </div>

  <section class="card featured">
    <h2>⭐ Gennemsnit hunde pr. åbningsdag <span class="pin">Nøgletal: drift</span> <span class="pin source">Kilde: Protokol</span></h2>
    <p class="helper">Hvor mange hunde der i snit er hver åbningsdag (Mon–Fri), pr. uge. Tællingen kommer fra protokollerne.</p>
    <div class="chartbox tall"><canvas id="dpdChart"></canvas></div>
    <div class="health-strip">
      <span><span class="health-dot red"></span> &lt; 12 = pres på drift</span>
      <span><span class="health-dot amber"></span> 12–14 = ustabil drift</span>
      <span><span class="health-dot green"></span> 14–16 = alm. drift</span>
      <span><span class="health-dot darkgreen"></span> 16+ = ønsket niveau ⭐</span>
    </div>
    <div class="sako-note">{pote["dpd"]}</div>
  </section>

  <section class="card">
    <h2>📊 Hele halvåret — 2025 vs 2026 <span class="pin source">Kilde: Begge protokoller</span></h2>
    <div class="chartbox xtall"><canvas id="yoyChart"></canvas></div>
    <div class="sako-note">{pote["yoy"]}</div>
  </section>

  <section class="card">
    <h2>📅 Månedligt overblik — totaler 2025 vs 2026</h2>
    <div class="chartbox tall"><canvas id="monthlyChart"></canvas></div>
    <table class="simple" style="margin-top:14px;">
      <thead><tr><th>Måned</th><th class="num">2025</th><th class="num">2026</th><th class="num">Diff</th><th class="num">Pr. dag (2026)</th></tr></thead>
      <tbody>{chr(10).join(month_rows)}</tbody>
    </table>
    <div class="sako-note">{pote["month"]}</div>
  </section>

  <section class="card">
    <h2>🏆 Top hunde — de mest loyale gæster</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
      <div>
        <h3 style="font-size:13px;margin:0 0 8px;">Top 10 — 2026 ({d["total_open_26"]} dage)</h3>
        <table class="simple"><thead><tr><th>#</th><th>Hund</th><th class="num">Besøg</th><th class="num">%</th></tr></thead>
        <tbody>{chr(10).join(top26_rows)}{sako_row}</tbody></table>
      </div>
      <div>
        <h3 style="font-size:13px;margin:0 0 8px;">Top 10 — 2025 ({d["total_open_25"]} dage)</h3>
        <table class="simple"><thead><tr><th>#</th><th>Hund</th><th class="num">Besøg</th><th class="num">%</th></tr></thead>
        <tbody>{chr(10).join(top25_rows)}</tbody></table>
      </div>
    </div>
    <div class="sako-note">{pote["top"]}</div>
  </section>

  <section class="card">
    <h2>📋 Detaljerede tal — sidste 8 hele uger</h2>
    <table class="simple">
      <thead><tr><th>Uge</th><th>Periode</th><th class="num">Hunde i alt</th><th class="num">Åbne dage</th><th class="num">Hunde / dag</th><th>Status</th></tr></thead>
      <tbody>{chr(10).join(week_rows)}</tbody>
    </table>

    <h3 style="font-size:13px;margin:24px 0 8px;">År-over-år sammenligning</h3>
    <table class="simple">
      <thead><tr><th>Uge</th><th class="num">2025</th><th class="num">2026</th><th class="num">Diff</th></tr></thead>
      <tbody>
        {chr(10).join(yoy_rows)}
        <tr style="background:#eef2eb;font-weight:600;"><td>Gns.</td><td class="num">{d["common_avg_25"]:.1f}</td><td class="num">{d["common_avg_26"]:.1f}</td><td class="num {yoy_class}">{d["yoy_diff_pct"]:+.1f}%</td></tr>
      </tbody>
    </table>
  </section>

  <p class="footnote" style="text-align:center;">
    "Tal lyver ikke. Hunde gør sjældent." — Sako 🐕<br>
    Hundehaven Potefryd · Auto-genereret {today_str} · Kilde: protokollerne 2025 + 2026
  </p>
</div>

<script>
function color(v) {{
  if (v < 12) return "#b95757";
  if (v < 14) return "#d4a73a";
  if (v < 16) return "#5c8a5c";
  return "#3b6b3b";
}}

const dpdValues = {json.dumps(dpd_values)};
new Chart(document.getElementById("dpdChart"), {{
  type: "bar",
  data: {{ labels: {json.dumps(dpd_labels)}, datasets: [{{ label: "Hunde / dag", data: dpdValues, backgroundColor: dpdValues.map(color), borderRadius: 6 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false,
    scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: "Hunde pr. åbningsdag" }} }} }},
    plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.y.toFixed(1) + " hunde/dag" }} }} }}
  }}
}});

new Chart(document.getElementById("yoyChart"), {{
  type: "bar",
  data: {{ labels: {json.dumps(yoy_labels)}, datasets: [
    {{ label: "2025", data: {json.dumps(yoy_2025)}, backgroundColor: "#a8b8a3" }},
    {{ label: "2026", data: {json.dumps(yoy_2026)}, backgroundColor: "#4a8c3c" }}
  ] }},
  options: {{ responsive: true, maintainAspectRatio: false,
    scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: "Hunde / åbningsdag" }} }} }},
    plugins: {{ legend: {{ position: "bottom" }} }}
  }}
}});

new Chart(document.getElementById("monthlyChart"), {{
  type: "bar",
  data: {{ labels: {json.dumps(month_labels)}, datasets: [
    {{ label: "2025", data: {json.dumps(month_2025)}, backgroundColor: "#a8b8a3" }},
    {{ label: "2026", data: {json.dumps(month_2026)}, backgroundColor: "#4a8c3c" }}
  ] }},
  options: {{ responsive: true, maintainAspectRatio: false,
    scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: "Hunde total" }} }} }},
    plugins: {{ legend: {{ position: "bottom" }} }}
  }}
}});
</script>
</body>
</html>"""

# ───── Hovedlogik ─────

def main():
    print("📥 Henter protokoller fra Google Sheets …")
    csv_2026 = fetch_sheet_csv(PROTOKOL_2026_ID)
    csv_2025 = fetch_sheet_csv(PROTOKOL_2025_ID)

    print("🔢 Parser data …")
    daily_26, dogs_26 = parse_protokol(csv_2026, 2026)
    daily_25, dogs_25 = parse_protokol(csv_2025, 2025)

    weekly_26 = aggregate_weekly(daily_26)
    weekly_25 = aggregate_weekly(daily_25)
    monthly_26 = aggregate_monthly(daily_26)
    monthly_25 = aggregate_monthly(daily_25)

    today = date.today()
    iso_yr, iso_wk, _ = today.isocalendar()
    last_8_weeks = []
    for offset in range(8, 0, -1):
        target_wk = iso_wk - offset
        target_yr = iso_yr
        while target_wk < 1:
            target_yr -= 1
            target_wk += 52
        w = weekly_26.get((target_yr, target_wk))
        if w and w["open"] > 0:
            avg = w["total"] / w["open"]
            last_8_weeks.append({"label": f"U{target_wk:02d}", "wk": target_wk, "total": w["total"], "open": w["open"], "avg": round(avg, 1)})

    yoy_data = []
    for wk in range(2, iso_wk):
        v25 = weekly_25.get((2025, wk))
        v26 = weekly_26.get((2026, wk))
        if v25 and v26 and v25["open"] > 0 and v26["open"] > 0:
            yoy_data.append({"label": f"U{wk:02d}", "wk": wk, "v2025": round(v25["total"]/v25["open"], 1), "v2026": round(v26["total"]/v26["open"], 1)})

    months_data = []
    for m in range(1, today.month + 1):
        v25 = monthly_25.get((2025, m), {"total": 0, "days": 0})
        v26 = monthly_26.get((2026, m), {"total": 0, "days": 0})
        if v26["total"] > 0:
            months_data.append({
                "month": m,
                "name": ["Jan","Feb","Mar","Apr","Maj","Jun","Jul","Aug","Sep","Okt","Nov","Dec"][m-1],
                "t2025": v25["total"], "t2026": v26["total"],
                "perday_2026": round(v26["total"]/v26["days"], 1) if v26["days"] else 0,
            })

    total_open_26 = len(daily_26)
    top_26 = sorted(dogs_26.items(), key=lambda x: -x[1])[:10]
    sako_rank = next((i+1 for i, (n, _) in enumerate(sorted(dogs_26.items(), key=lambda x: -x[1])) if n == "Sako"), None)
    sako_count = dogs_26.get("Sako", 0)

    total_open_25 = len(daily_25)
    top_25 = sorted(dogs_25.items(), key=lambda x: -x[1])[:10]

    common_avg_26 = sum(d["v2026"] for d in yoy_data) / len(yoy_data) if yoy_data else 0
    common_avg_25 = sum(d["v2025"] for d in yoy_data) / len(yoy_data) if yoy_data else 0
    yoy_diff_pct = ((common_avg_26 - common_avg_25) / common_avg_25 * 100) if common_avg_25 else 0

    total_dogs_26 = sum(d["total"] for d in daily_26)
    avg_per_day_2026 = total_dogs_26 / total_open_26 if total_open_26 else 0

    print("🐕 Loader Sako-billede …")
    hero_b64, avatar_b64 = load_sako_images()

    # Forbered arkiv-info: scan eksisterende + tilføj dagens
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    archive_dir = OUTPUT_DIR / "arkiv"
    archive_dir.mkdir(exist_ok=True)

    last_data_wk = last_8_weeks[-1]["wk"] if last_8_weeks else iso_wk
    today_iso = today.strftime("%Y-%m-%d")
    archive_name = f"Driftsrapport_{today_iso}_uge{last_data_wk:02d}.html"

    existing_archives = discover_archives(OUTPUT_DIR)
    today_entry = {"date": today_iso, "week": last_data_wk, "filename": archive_name}
    all_archives = [a for a in existing_archives if a["filename"] != archive_name] + [today_entry]
    all_archives.sort(key=lambda x: x["date"], reverse=True)

    print(f"📚 Fundet {len(existing_archives)} eksisterende arkiver, dagens er {archive_name}")

    common_args = {
        "today": today, "iso_wk": iso_wk,
        "last_8_weeks": last_8_weeks, "yoy_data": yoy_data, "months_data": months_data,
        "top_26": top_26, "top_25": top_25, "sako_rank": sako_rank, "sako_count": sako_count,
        "total_open_26": total_open_26, "total_open_25": total_open_25,
        "total_dogs_26": total_dogs_26, "avg_per_day_2026": avg_per_day_2026,
        "common_avg_26": common_avg_26, "common_avg_25": common_avg_25,
        "yoy_diff_pct": yoy_diff_pct,
        "hero_b64": hero_b64, "avatar_b64": avatar_b64,
    }

    # 1. /docs/index.html (nuværende rapport, top-menu med "arkiv/" prefix)
    print("📝 Genererer index.html …")
    menu_root = build_topmenu(all_archives, from_archive=False, current_file=None)
    html_root = build_html(common_args, topmenu_html=menu_root)
    (OUTPUT_DIR / "index.html").write_text(html_root, encoding="utf-8")
    print(f"✅ {OUTPUT_DIR / 'index.html'} ({len(html_root)} bytes)")

    # 2. /docs/arkiv/Driftsrapport_X.html (arkiv-version, top-menu med "" prefix og dagens markeret)
    print("📦 Genererer arkiv-version …")
    menu_arkiv = build_topmenu(all_archives, from_archive=True, current_file=archive_name)
    html_arkiv = build_html(common_args, topmenu_html=menu_arkiv)
    (archive_dir / archive_name).write_text(html_arkiv, encoding="utf-8")
    print(f"📦 {archive_dir / archive_name}")

    # 3. Re-generér menuen i ALLE eksisterende arkiv-filer (så de også viser nyeste)
    if existing_archives:
        print(f"🔄 Opdaterer top-menu i {len(existing_archives)} eksisterende arkiver …")
        for old in existing_archives:
            if old["filename"] == archive_name:
                continue
            old_path = archive_dir / old["filename"]
            if not old_path.exists():
                continue
            try:
                content = old_path.read_text(encoding="utf-8")
                # Erstat eksisterende <nav class="topnav"> blok
                new_menu = build_topmenu(all_archives, from_archive=True, current_file=old["filename"])
                content = re.sub(
                    r'<nav class="topnav">.*?</nav>',
                    new_menu.replace("\\", "\\\\"),
                    content,
                    count=1, flags=re.DOTALL
                )
                old_path.write_text(content, encoding="utf-8")
            except Exception as e:
                print(f"  WARN: kunne ikke opdatere {old['filename']}: {e}")

    print(f"\n📊 Sidste hele uge: {last_8_weeks[-1]['label'] if last_8_weeks else 'INGEN'} ({last_8_weeks[-1]['avg'] if last_8_weeks else 0} hunde/dag)")
    print(f"📈 2026 vs 2025: {common_avg_26:.1f} vs {common_avg_25:.1f} ({yoy_diff_pct:+.1f}%)")

    # Skriv data.json så Cowork-agenten kan læse tallene og skrive pote-noter ud fra dem
    import json
    data_summary = {
        "today": today_iso,
        "iso_week_now": iso_wk,
        "last_complete_week": last_8_weeks[-1] if last_8_weeks else None,
        "last_8_weeks": last_8_weeks,
        "yoy_diff_pct": round(yoy_diff_pct, 1),
        "common_avg_26": round(common_avg_26, 1),
        "common_avg_25": round(common_avg_25, 1),
        "biggest_yoy_swing_up": max(yoy_data, key=lambda y: y["v2026"]-y["v2025"], default=None),
        "biggest_yoy_swing_down": min(yoy_data, key=lambda y: y["v2026"]-y["v2025"], default=None),
        "top_dogs_2026": [{"name": n, "visits": c} for n, c in top_26[:10]],
        "top_dogs_2025": [{"name": n, "visits": c} for n, c in top_25[:10]],
        "common_top_dogs": sorted(set(n for n,_ in top_26) & set(n for n,_ in top_25)),
        "lost_top_dogs": sorted(set(n for n,_ in top_25) - set(n for n,_ in top_26)),
        "new_top_dogs": sorted(set(n for n,_ in top_26) - set(n for n,_ in top_25)),
        "months_data": months_data,
        "sako_rank": sako_rank,
        "sako_count": sako_count,
        "total_open_26": total_open_26,
        "archive_filename": archive_name,
    }
    (OUTPUT_DIR / "data.json").write_text(json.dumps(data_summary, indent=2, default=str), encoding="utf-8")
    print(f"📋 {OUTPUT_DIR / 'data.json'} (til Cowork-agentens pote-noter)")

if __name__ == "__main__":
    main()
