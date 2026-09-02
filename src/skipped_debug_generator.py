"""
Skipped Debug Generator - generuje statyczną stronę docs/skipped_debug.html
z diagnostyką ostatniego skanu (no_address / no_coords / duplicate / no_price).

FIX 2026-08-07: kategoria `no_address` to już NIE są oferty odrzucone — takie
ogłoszenia zostają na stronie w warstwie „bez lokacji" (patrz `main._process_offer`).
Ta sekcja służy więc do wyłapywania regresji parsera adresów, a nie do liczenia
straconych ofert. Pozostałe kategorie (duplikat, brak ceny) nadal oznaczają pominięcie.

Stała strona diagnostyczna parsera/geokodera (pomaga wyłapywać regresje w
ekstrakcji adresów/cen po zmianach w scraperze lub OLX).

Źródło danych: data/skipped_offers_sample.json (zapisywany przez main.py podczas skanu).
"""

import json
import html
from pathlib import Path
from datetime import datetime

import paths


# Mapowanie kategorii → metadane wyświetlania
CATEGORY_LABELS = {
    # FIX 2026-08-07: te oferty NIE są już odrzucane — zostają na stronie w warstwie
    # „bez lokacji". Sekcja pełni więc rolę diagnostyki parsera, a nie listy strat.
    'no_address': {
        'label': 'Bez adresu (na stronie, bez pinezki)',
        'short': 'bez adresu',
        'color': '#ef4444',
        'sub': 'parser nie znalazł ulicy — oferta trafia do warstwy „bez lokacji”',
    },
    # FIX 2026-08-09: trzy kategorie, których strona wcześniej nie miała — a bez nich
    # bilans się nie domykał (111 ofert bez pinezki, pokazanych 28).
    'not_a_street': {
        'label': 'Etykieta nie jest ulicą',
        'short': 'nie ulica',
        'color': '#db2777',
        'sub': 'parser coś odczytał, ale to nie nazwa ulicy',
    },
    'area_only': {
        'label': 'Obszar zamiast punktu',
        'short': 'obszar',
        'color': '#0891b2',
        'sub': 'osiedle lub dzielnica — znamy okolicę, nie budynek',
    },
    'no_coords': {
        'label': 'Brak współrzędnych',
        'short': 'brak współrzędnych',
        'color': '#8b5cf6',
        'sub': 'realna ulica, ale geokoder nie dał punktu',
    },
    'duplicate': {
        'label': 'Duplikaty',
        'short': 'duplikat',
        'color': '#06b6d4',
        'sub': 'to samo mieszkanie 2× w wynikach',
    },
    'no_price': {
        'label': 'Brak ceny',
        'short': 'brak ceny',
        'color': '#f59e0b',
        'sub': 'parser nie wyciągnął ceny',
    },
}

# Kategorie „jest na stronie, ale bez pinezki" — ich suma musi się zgadzać
# z liczbą ofert poza mapą (main._write_map_gap_breakdown).
OFF_MAP_CATEGORIES = ('no_address', 'not_a_street', 'area_only', 'no_coords')
# Kategorie „pominięte w skanie" — tych ofert na stronie nie ma wcale.
SKIPPED_CATEGORIES = ('duplicate', 'no_price')


def _esc(text) -> str:
    """HTML-escape z fallbackiem na pusty string dla None/non-str."""
    if text is None:
        return ''
    return html.escape(str(text), quote=True)


def _format_url_display(url: str) -> str:
    """Skróć URL do wyświetlenia (bez schemy)."""
    if not url:
        return '(brak URL)'
    return url.replace('https://', '').replace('http://', '')


def _build_offer_card(category: str, sample: dict) -> str:
    """Buduje HTML jednej karty oferty."""
    cat_meta = CATEGORY_LABELS.get(category, CATEGORY_LABELS['no_address'])
    badge_class = category
    title = _esc(sample.get('title', '(brak tytułu)'))
    url = sample.get('url', '')
    url_esc = _esc(url)
    desc = _esc(sample.get('description_preview', ''))

    # Metadane różne per kategoria
    meta_items = []
    note = sample.get('note', '')
    parsed_addr = sample.get('address_parsed', '')

    if parsed_addr:
        meta_items.append(
            f'<span class="parsed-addr">parsed: "{_esc(parsed_addr)}"</span>'
        )
    if note:
        meta_items.append(f'<span class="note">⚠️ {_esc(note)}</span>')

    meta_html = ''
    if meta_items:
        meta_html = f'<div class="offer-meta">{"".join(meta_items)}</div>'

    # Sekcja porównania duplikatów (tylko gdy category == duplicate i mamy duplicate_of)
    compare_html = ''
    if category == 'duplicate' and sample.get('duplicate_of'):
        dup_of = sample['duplicate_of']
        similarity = sample.get('similarity')
        sim_label = f'{similarity * 100:.1f}% podobne' if isinstance(similarity, (int, float)) else 'podobne'
        orig_url = dup_of.get('url', '')
        orig_url_esc = _esc(orig_url)
        orig_id_esc = _esc(dup_of.get('id', '(brak ID)'))
        orig_addr_esc = _esc(dup_of.get('address', '(brak adresu)'))
        orig_price = dup_of.get('price')
        orig_price_str = f'{orig_price} zł' if orig_price is not None else 'brak'
        this_price = sample.get('price')
        this_price_str = f'{this_price} zł' if this_price is not None else 'brak'
        this_addr_esc = _esc(sample.get('address_parsed', '(brak)'))

        this_url_display = _format_url_display(url)
        orig_url_display = _format_url_display(orig_url)

        compare_html = f'''
        <div class="duplicate-compare">
          <div class="duplicate-compare-title">
            🔗 Porównaj oferty
            <span class="similarity-pill">{_esc(sim_label)}</span>
          </div>
          <div class="duplicate-compare-grid">
            <div class="duplicate-side this">
              <div class="role-label">⚠️ Odrzucone (duplikat)</div>
              <strong>{title}</strong>
              <a href="{url_esc}" target="_blank" rel="noopener" class="url">{_esc(this_url_display)} ↗</a>
              <div class="meta">parsed: {this_addr_esc} · cena: {_esc(this_price_str)}</div>
            </div>
            <div class="duplicate-arrow">≈</div>
            <div class="duplicate-side original">
              <div class="role-label">✅ Pozostawione na mapie</div>
              <strong>ID: {orig_id_esc}</strong>
              <a href="{orig_url_esc}" target="_blank" rel="noopener" class="url">{_esc(orig_url_display)} ↗</a>
              <div class="meta">adres: {orig_addr_esc} · cena: {_esc(orig_price_str)}</div>
            </div>
          </div>
        </div>
        '''

    # Dla nie-duplikatów - prosty link "→ OLX"
    olx_link_html = ''
    if category != 'duplicate' and url:
        olx_link_html = f'<a href="{url_esc}" target="_blank" rel="noopener" class="offer-link">→ OLX</a>'

    desc_html = ''
    if desc:
        desc_html = f'<div class="offer-desc" onclick="this.classList.toggle(\'expanded\')">{desc}</div>'

    return f'''
    <div class="offer" data-category="{category}" data-search="{_esc((title + ' ' + desc).lower())}">
      <div class="offer-header">
        <span class="badge {badge_class}">{_esc(cat_meta["short"])}</span>
        <div class="offer-title">{title}</div>
        {olx_link_html}
      </div>
      {desc_html}
      {meta_html}
      {compare_html}
    </div>
    '''


def _map_reality(map_data_path: str):
    """Ile ofert NAPRAWDĘ jest na mapie — czytane z `docs/data.json`.

    FIX 2026-08-09: sam domknięty bilans nie wystarcza. Liczony w złym miejscu
    skanu potrafi się zgadzać wewnętrznie („104 = 25+70+5+4"), a mimo to opisywać
    stan sprzed reaktywacji ofert — pokazywał 665 aktywnych zamiast 713, i to
    z zielonym paskiem „bilans OK". Dlatego konfrontujemy go z tym, co poszło
    na mapę. Brak pliku = brak kontroli (None), nie fałszywy alarm.
    """
    try:
        stats = json.loads(Path(map_data_path).read_text(encoding='utf-8')).get('stats') or {}
    except (OSError, json.JSONDecodeError):
        return None
    on_map, off_map = stats.get('active_count'), stats.get('unlocalised_count')
    if on_map is None or off_map is None:
        return None
    return {'on_map': on_map, 'off_map': off_map}


def generate_skipped_debug_page(
    sample_path: str = paths.SKIPPED_SAMPLE_JSON,
    output_path: str = paths.DOCS_SKIPPED_DEBUG_HTML,
    map_data_path: str = paths.DOCS_DATA_JSON
) -> bool:
    """
    Generuje docs/skipped_debug.html z aktualnymi próbkami pominiętych ofert.

    Returns:
        True jeśli wygenerowano stronę, False jeśli sample_path nie istnieje.
    """
    sample_file = Path(sample_path)
    if not sample_file.exists():
        print(f"⚠️  skipped_debug_generator: brak {sample_path}, pomijam generację.")
        return False

    with open(sample_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    counts = dict(data.get('counts', {}))
    samples = dict(data.get('samples', {}))
    scan_ts_raw = data.get('scan_timestamp', '')

    # FIX 2026-08-09: bilans „dlaczego nie na mapie" liczony z KOŃCOWEGO stanu bazy
    # (patrz main._write_map_gap_breakdown). Liczniki z pętli skanu nie mogły go
    # oddać, bo część ofert traci współrzędne dopiero w krokach porządkowych.
    map_gap = data.get('map_gap') or {}
    gap_counts = map_gap.get('counts') or {}
    for cat_key, value in gap_counts.items():
        counts[cat_key] = value
        gap_samples = (map_gap.get('samples') or {}).get(cat_key) or []
        if gap_samples:
            samples[cat_key] = gap_samples

    # Sformatuj timestamp do czytelnej postaci
    scan_ts_display = scan_ts_raw
    try:
        dt = datetime.fromisoformat(scan_ts_raw)
        scan_ts_display = dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        pass

    # Liczniki dla kart statystyk
    total_samples = sum(len(s) for s in samples.values())

    # Renderuj karty statystyk
    cards_html_parts = []
    for cat_key in OFF_MAP_CATEGORIES + SKIPPED_CATEGORIES:
        meta = CATEGORY_LABELS[cat_key]
        count = counts.get(cat_key, 0)
        cards_html_parts.append(f'''
        <div class="stat-card {cat_key}">
          <div class="label">{_esc(meta["label"])}</div>
          <div class="value">{count}</div>
          <div class="sub">{_esc(meta["sub"])}</div>
        </div>
        ''')
    cards_html = ''.join(cards_html_parts)

    # Rachunek do sprawdzenia gołym okiem: aktywne = na mapie + suma kategorii.
    # Gdy się nie domyka, to znaczy że doszła piąta przyczyna, której nie nazwaliśmy.
    reconciliation_html = ''
    if map_gap:
        gap_sum = sum(gap_counts.get(k, 0) for k in OFF_MAP_CATEGORIES)
        off_map = map_gap.get('off_map', 0)
        parts = ' + '.join(
            f'{_esc(CATEGORY_LABELS[k]["short"])} {gap_counts.get(k, 0)}'
            for k in OFF_MAP_CATEGORIES if gap_counts.get(k)
        )
        problems = []
        if gap_sum != off_map:
            problems.append(f'suma kategorii to {gap_sum}, a ofert bez pinezki jest {off_map}')
        # Druga, niezależna kontrola: czy bilans opisuje TEN stan, który poszedł na mapę.
        reality = _map_reality(map_data_path)
        if reality and (reality['on_map'] != map_gap.get('on_map')
                        or reality['off_map'] != off_map):
            problems.append(
                f'mapa pokazuje {reality["on_map"]} ofert i {reality["off_map"]} bez lokacji '
                f'— bilans policzono na innym stanie bazy'
            )
        balanced = not problems
        reconciliation_html = f'''
  <p class="reconciliation {'ok' if balanced else 'broken'}">
    {'✅' if balanced else '⚠️'} <strong>{map_gap.get("active", 0)}</strong> ofert aktywnych =
    <strong>{map_gap.get("on_map", 0)}</strong> na mapie +
    <strong>{off_map}</strong> bez pinezki{f' ({parts})' if parts else ''}
    {'' if balanced else ' — ' + _esc('; '.join(problems))}
  </p>'''

    # Renderuj listę ofert (duplikaty pierwsze - najbardziej diagnostyczne)
    offers_html_parts = []
    for cat_key in ('duplicate',) + OFF_MAP_CATEGORIES + ('no_price',):
        cat_samples = samples.get(cat_key, [])
        for s in cat_samples:
            offers_html_parts.append(_build_offer_card(cat_key, s))
    offers_html = ''.join(offers_html_parts)

    if not offers_html:
        offers_html = '<div class="empty">Brak danych — uruchom skan żeby wygenerować próbki.</div>'

    # Opcje filtra kategorii
    filter_options = [f'<option value="all">Wszystkie ({total_samples} próbek)</option>']
    for cat_key in OFF_MAP_CATEGORIES + SKIPPED_CATEGORIES:
        meta = CATEGORY_LABELS[cat_key]
        cnt = len(samples.get(cat_key, []))
        filter_options.append(
            f'<option value="{cat_key}">{_esc(meta["label"])} ({cnt})</option>'
        )
    filter_options_html = ''.join(filter_options)

    # Pełen HTML strony
    html_doc = f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SONAR MIESZKANIOWY - Diagnostyka skanu (debug)</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="stylesheet" href="assets/header.css?v=1">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7fa; color: #2d3748; line-height: 1.5; }}
.banner {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 24px; color: #78350f; font-size: 14px; }}
.container {{ max-width: 1400px; margin: 24px auto; padding: 0 24px; }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.stat-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border-left: 4px solid; }}
.reconciliation {{ margin: 0 0 16px; padding: 10px 14px; border-radius: 4px; font-size: 14px; }}
.reconciliation.ok {{ background: #ecfdf5; border-left: 3px solid #10b981; color: #065f46; }}
.reconciliation.broken {{ background: #fef2f2; border-left: 3px solid #ef4444; color: #991b1b; }}
.stat-card.not_a_street {{ border-color: #db2777; }}
.stat-card.area_only {{ border-color: #0891b2; }}
.badge.not_a_street {{ background: #fce7f3; color: #9d174d; }}
.badge.area_only {{ background: #cffafe; color: #155e75; }}
.stat-card.no_address {{ border-color: #ef4444; }}
.stat-card.no_price {{ border-color: #f59e0b; }}
.stat-card.no_coords {{ border-color: #8b5cf6; }}
.stat-card.duplicate {{ border-color: #06b6d4; }}
.stat-card .label {{ font-size: 12px; color: #718096; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
.stat-card .value {{ font-size: 28px; font-weight: 700; color: #2d3748; }}
.stat-card .sub {{ font-size: 12px; color: #a0aec0; margin-top: 4px; }}
.filter-bar {{ background: white; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
.filter-bar label {{ font-weight: 600; font-size: 14px; color: #4a5568; }}
.filter-bar select, .filter-bar input {{ padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; font-family: inherit; }}
.filter-bar input {{ flex: 1; min-width: 200px; }}
.timestamp {{ color: #718096; font-size: 12px; margin-left: auto; }}
.offer-list {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow: hidden; }}
.offer {{ padding: 16px 20px; border-bottom: 1px solid #edf2f7; }}
.offer:last-child {{ border-bottom: none; }}
.offer.hidden {{ display: none; }}
.offer-header {{ display: flex; gap: 12px; align-items: flex-start; margin-bottom: 8px; flex-wrap: wrap; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; }}
.badge.no_address {{ background: #fee2e2; color: #991b1b; }}
.badge.no_price {{ background: #fef3c7; color: #92400e; }}
.badge.no_coords {{ background: #ede9fe; color: #5b21b6; }}
.badge.duplicate {{ background: #cffafe; color: #155e75; }}
.offer-title {{ font-weight: 600; color: #2d3748; font-size: 15px; flex: 1; min-width: 0; }}
.offer-link {{ color: #667eea; text-decoration: none; font-size: 13px; white-space: nowrap; }}
.offer-link:hover {{ text-decoration: underline; }}
.offer-desc {{ color: #4a5568; font-size: 13px; line-height: 1.6; margin-top: 4px; max-height: 60px; overflow: hidden; transition: max-height 0.3s; cursor: pointer; position: relative; }}
.offer-desc.expanded {{ max-height: 1000px; }}
.offer-meta {{ display: flex; gap: 16px; font-size: 12px; color: #718096; margin-top: 8px; flex-wrap: wrap; }}
.offer-meta .note {{ color: #d97706; font-weight: 600; }}
.offer-meta .parsed-addr {{ color: #5b21b6; font-family: monospace; }}

/* === Sekcja porównania duplikatów === */
.duplicate-compare {{
    margin-top: 12px;
    background: #f0fdfa;
    border: 1px solid #99f6e4;
    border-radius: 6px;
    padding: 12px 14px;
}}
.duplicate-compare-title {{
    font-size: 12px;
    font-weight: 700;
    color: #0f766e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}}
.duplicate-compare-grid {{
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 12px;
    align-items: center;
}}
@media (max-width: 700px) {{
    .duplicate-compare-grid {{ grid-template-columns: 1fr; }}
    .duplicate-arrow {{ transform: rotate(90deg); }}
}}
.duplicate-side {{
    background: white;
    padding: 10px 12px;
    border-radius: 4px;
    font-size: 13px;
    min-width: 0;
}}
.duplicate-side .role-label {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
}}
.duplicate-side.this {{ border-left: 3px solid #f59e0b; }}
.duplicate-side.this .role-label {{ color: #d97706; }}
.duplicate-side.original {{ border-left: 3px solid #10b981; }}
.duplicate-side.original .role-label {{ color: #047857; }}
.duplicate-side .url {{ color: #667eea; text-decoration: none; word-break: break-all; display: block; margin-top: 4px; font-size: 12px; }}
.duplicate-side .url:hover {{ text-decoration: underline; }}
.duplicate-side .meta {{ color: #718096; font-size: 11px; margin-top: 4px; }}
.duplicate-arrow {{ font-size: 20px; color: #0d9488; font-weight: bold; text-align: center; }}
.similarity-pill {{
    display: inline-block;
    background: #0d9488;
    color: white;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
}}

.empty {{ text-align: center; padding: 60px 20px; color: #a0aec0; }}
.no-results {{ text-align: center; padding: 40px 20px; color: #a0aec0; display: none; }}
.no-results.visible {{ display: block; }}
</style>
</head>
<body>

<header class="sm-header">
  <div class="sm-brand">
    <svg class="sm-brand-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <radialGradient id="smRb-skipped" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#3a2e15"/>
          <stop offset="100%" stop-color="#1a1408"/>
        </radialGradient>
        <linearGradient id="smRs-skipped" x1="50%" y1="50%" x2="100%" y2="50%">
          <stop offset="0%" stop-color="#ffb800" stop-opacity="0.8"/>
          <stop offset="50%" stop-color="#ffb800" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="#ffb800" stop-opacity="0"/>
        </linearGradient>
        <mask id="smRm-skipped"><circle cx="32" cy="32" r="28" fill="white"/></mask>
      </defs>
      <circle cx="32" cy="32" r="32" fill="url(#smRb-skipped)"/>
      <circle cx="32" cy="32" r="30" fill="none" stroke="#ffb800" stroke-width="0.5" opacity="0.6"/>
      <circle cx="32" cy="32" r="22" fill="none" stroke="#ffb800" stroke-width="0.3" opacity="0.3"/>
      <circle cx="32" cy="32" r="14" fill="none" stroke="#ffb800" stroke-width="0.3" opacity="0.3"/>
      <line x1="32" y1="4" x2="32" y2="60" stroke="#ffb800" stroke-width="0.3" opacity="0.3"/>
      <line x1="4" y1="32" x2="60" y2="32" stroke="#ffb800" stroke-width="0.3" opacity="0.3"/>
      <g transform="translate(32, 32)">
        <path fill-rule="evenodd" d="M0,-6 L-5,-1 L5,-1 Z M-4,-1 L4,-1 L4,5 L-4,5 Z M-1.2,1 L1.2,1 L1.2,5 L-1.2,5 Z" fill="#ffb800" stroke="#3a2400" stroke-width="0.5" opacity="0.9">
          <animateTransform attributeName="transform" type="scale" values="1;1.3;1" dur="2s" repeatCount="indefinite"/>
        </path>
      </g>
      <g mask="url(#smRm-skipped)">
        <path d="M32,32 L32,4 A28,28 0 0,1 60,32 Z" fill="url(#smRs-skipped)" opacity="0.6">
          <animateTransform attributeName="transform" type="rotate" from="0 32 32" to="360 32 32" dur="3s" repeatCount="indefinite"/>
        </path>
      </g>
      <circle cx="22" cy="18" r="1.5" fill="#ffb800" opacity="0.8">
        <animate attributeName="opacity" values="0.8;0.3;0.8" dur="1.5s" repeatCount="indefinite"/>
      </circle>
    </svg>
    <h1>
      <span class="sm-b">SONAR MIESZKANIOWY</span>
      <span class="sm-s">·</span>
      <span class="sm-p">🐛 Pominięte</span>
    </h1>
  </div>
  <nav>
    <a href="index.html">🗺️ Mapa</a>
    <a href="analytics.html">📈 Analityka</a>
    <a href="trend.html">📉 Indeks</a>
    <a href="monitoring.html">📊 Monitoring</a>
    <a href="market_analysis.html">🔍 Analiza Rynku</a>
    <a href="analiza_metraz.html">📐 Ceny/m²</a>
    <a href="okazje.html">💎 Okazje</a>
    <a href="top5.html">🏆 Top 5</a>
    <a href="skipped_debug.html" class="active">🐛 Pominięte</a>
  </nav>
</header>

<div class="banner">
  🐛 <strong>Diagnostyka parsera</strong> — oferty, które scraper pobrał, ale nie trafiły na mapę
  (brak adresu/ceny/współrzędnych lub duplikat). Aktualizowana przy każdym skanie.
</div>

<div class="container">
  <div class="stats-grid">
    {cards_html}
  </div>

  {reconciliation_html}

  <p style="margin: 0 0 16px; padding: 10px 14px; background: #eff6ff; border-left: 3px solid #3b82f6; border-radius: 4px; font-size: 13px; color: #1e3a8a;">
    ℹ️ Pierwsze cztery kategorie to oferty, które <strong>są na stronie</strong>, ale bez pinezki —
    trafiają do warstwy „bez lokacji" pod mapą. <strong>Duplikaty</strong> i <strong>brak ceny</strong>
    oznaczają ogłoszenia pominięte w skanie, których na stronie nie ma wcale.
  </p>

  <div class="filter-bar">
    <label for="category-filter">Kategoria:</label>
    <select id="category-filter">
      {filter_options_html}
    </select>
    <label for="search-input">Szukaj:</label>
    <input type="text" id="search-input" placeholder="filtruj po tytule/opisie/URL...">
    <span class="timestamp">Aktualizacja: {_esc(scan_ts_display)}</span>
  </div>

  <div class="offer-list" id="offer-list">
    {offers_html}
  </div>
  <div class="no-results" id="no-results">Brak wyników dla wybranych filtrów.</div>
</div>

<script>
(function() {{
    const categoryFilter = document.getElementById('category-filter');
    const searchInput = document.getElementById('search-input');
    const offers = document.querySelectorAll('#offer-list .offer');
    const noResults = document.getElementById('no-results');
    const offerList = document.getElementById('offer-list');

    function applyFilters() {{
        const selectedCategory = categoryFilter.value;
        const searchTerm = searchInput.value.toLowerCase().trim();
        let visibleCount = 0;

        offers.forEach(offer => {{
            const offerCategory = offer.getAttribute('data-category');
            const offerSearch = offer.getAttribute('data-search') || '';

            const categoryMatch = selectedCategory === 'all' || offerCategory === selectedCategory;
            const searchMatch = !searchTerm || offerSearch.indexOf(searchTerm) !== -1;

            if (categoryMatch && searchMatch) {{
                offer.classList.remove('hidden');
                visibleCount++;
            }} else {{
                offer.classList.add('hidden');
            }}
        }});

        if (visibleCount === 0) {{
            noResults.classList.add('visible');
            offerList.style.display = 'none';
        }} else {{
            noResults.classList.remove('visible');
            offerList.style.display = '';
        }}
    }}

    categoryFilter.addEventListener('change', applyFilters);
    searchInput.addEventListener('input', applyFilters);
}})();
</script>

</body>
</html>'''

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html_doc)

    print(f"✅ skipped_debug.html wygenerowany: {out}")
    print(f"   Próbek: no_address={len(samples.get('no_address', []))}, "
          f"no_coords={len(samples.get('no_coords', []))}, "
          f"duplicate={len(samples.get('duplicate', []))}, "
          f"no_price={len(samples.get('no_price', []))}")
    return True


if __name__ == "__main__":
    generate_skipped_debug_page()
