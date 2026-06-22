# 🐾 Sakos Statistik

Auto-genereret driftsrapport for **Hundehaven Potefryd**. Udarbejdet af Statistiker Sako (Vizsla, stamhund).

Rapporten genereres hver 14. dag (1. og 15. i hver måned) **via Cowork** — som bruger ægte Claude-ræsonnement til at skrive Sakos pote-noter ud fra de faktiske tal.

## Arkitektur

```
┌─ Google Sheets (protokol 2025 + 2026)
│   │
│   ▼ fetch CSV
│
┌─ generate.py (Python, deterministisk)
│   │
│   ├─ Beregner alle nøgletal
│   ├─ Bygger HTML med placeholders for pote-noter
│   └─ Skriver data.json (rå tal til Cowork-agenten)
│
│   ▼
│
┌─ Cowork-agent (Claude)
│   │
│   ├─ Læser data.json
│   ├─ Skriver 4 pote-noter i Sakos stemme baseret på TALLENE
│   └─ Substituerer placeholders i HTML
│
│   ▼
│
└─ git commit + push → GitHub Pages renderer
```

## Hvorfor hybrid?

- **Python** = tal, layout, struktur (kan ikke hallucinere)
- **Claude** = narrative, kontekst, observation (kan se nuancer Python ikke kan)
- **Tallene er låste**, kun pote-noterne er AI-genererede

## Live URL

- **Nuværende rapport**: `docs/index.html` (deploy som GitHub Pages → `<user>.github.io/sako-statistics/`)
- **Arkiv**: `docs/arkiv/Driftsrapport_YYYY-MM-DD_ugeXX.html`
- **Top-menu** på alle sider — adgang til alle tidligere rapporter, grupperet pr. år

## Sådan kører du det

### Via Cowork (anbefalet)

1. Åbn Cowork
2. Trigger scheduled task `sakos-driftsrapport` (eller vent på næste automatiske kørsel 1./15.)
3. Cowork agent gør resten:
   - Henter friske CSV'er fra Sheets
   - Kører `python3 generate.py`
   - Læser `data.json`
   - Skriver pote-noter i Sakos stemme
   - Substituerer placeholders i HTML
   - `git add`, `commit`, `push`

### Manuelt (Claude Code eller kommandolinje)

```bash
pip install -r requirements.txt
python3 generate.py
# Nu indeholder docs/index.html placeholders <!--POTE_DPD--> osv.
# Erstat dem manuelt eller med Claude Code:
claude "Læs docs/data.json og skriv 4 pote-noter i Sakos stemme — erstat <!--POTE_DPD-->, <!--POTE_YOY-->, <!--POTE_MONTH-->, <!--POTE_TOP--> i docs/index.html og docs/arkiv/*.html"
git add docs/ && git commit -m "🐾 Sako rapport" && git push
```

## Hvad rapporten indeholder

- ⭐ Gennemsnit hunde pr. åbningsdag (drift-nøgletal med farvegradering)
- 📊 År-over-år sammenligning (2025 vs 2026)
- 📅 Månedligt overblik
- 🏆 Top hunde — de mest loyale gæster
- 📋 Detaljerede uge-tal
- 🐾 Sakos pote-noter (AI-skrevet baseret på data)

## Tærskler for hunde/dag (låst)

- 🔴 < 12: pres på drift
- 🟡 12–14: ustabil drift
- 🟢 14–16: al