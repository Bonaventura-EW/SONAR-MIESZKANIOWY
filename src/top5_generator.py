#!/usr/bin/env python3
"""
Generator danych dla strony TOP5 - SONAR MIESZKANIOWY
Wyciąga z offers.json wszystkie oferty które miały zmianę ceny
i produkuje docs/top5_data.json z pełnymi metadanymi do wyświetlenia.

Filtrowanie/sortowanie/limit do top5 odbywa się po stronie frontendu
(żeby umożliwić dynamiczny wybór zakresu dat bez regeneracji backendu).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _parse_iso_safe(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _build_change_entry(offer: dict) -> Optional[dict]:
    """
    Buduje wpis dla strony top5 z jednej oferty.
    Zwraca None gdy oferta nie ma zmiany ceny.
    """
    price = offer.get("price", {})
    history = price.get("history", [])
    price_changes = price.get("price_changes", [])

    if len(history) < 2:
        return None

    first_price = history[0]
    current_price = price.get("current") or history[-1]
    total_diff_pln = current_price - first_price
    if total_diff_pln == 0:
        return None

    total_diff_pct = (total_diff_pln / first_price * 100) if first_price else 0

    # Buduj timeline cen do wykresu: [{date, price}, ...]
    # Punkt startowy = first_seen z ceną history[0]
    # Każda zmiana z price_changes = kolejny punkt
    timeline = []
    first_seen = offer.get("first_seen")
    if first_seen:
        timeline.append({"date": first_seen, "price": first_price})

    # Dla każdej zmiany dodaj punkt po jej dacie
    for ch in price_changes:
        timeline.append({
            "date": ch.get("changed_at"),
            "price": ch.get("new_price"),
        })

    # Jeśli nie ma price_changes (stare dane), spróbuj zbudować przybliżenie
    # z samej history + price_changed_at
    if not price_changes and len(history) > 1:
        last_change_at = price.get("price_changed_at") or offer.get("last_seen")
        for i, p in enumerate(history[1:], start=1):
            timeline.append({"date": last_change_at, "price": p})

    # Adres - czytelny
    addr = offer.get("address", {}) or {}
    address_full = addr.get("full") or addr.get("street") or "?"

    return {
        "id": offer.get("id"),
        "url": offer.get("url"),
        "address": address_full,
        "first_price": first_price,
        "current_price": current_price,
        "total_diff_pln": total_diff_pln,
        "total_diff_pct": round(total_diff_pct, 2),
        "trend": "down" if total_diff_pln < 0 else "up",
        "first_seen": offer.get("first_seen"),
        "last_seen": offer.get("last_seen"),
        "active": offer.get("active", True),
        "timeline": timeline,
        "num_changes": len(price_changes) if price_changes else len(history) - 1,
    }


def generate(
    offers_path: str = "../data/offers.json",
    output_path: str = "../docs/top5_data.json",
) -> dict:
    """Generuje docs/top5_data.json. Zwraca statystyki."""
    p_in = Path(offers_path)
    with open(p_in, encoding="utf-8") as f:
        data = json.load(f)

    offers = data.get("offers", [])
    entries = []
    for offer in offers:
        entry = _build_change_entry(offer)
        if entry:
            entries.append(entry)

    # Sortuj: największe spadki (najbardziej ujemne) -> największe wzrosty
    entries.sort(key=lambda e: e["total_diff_pln"])

    # Wyznacz globalne min/max dat na potrzeby UI (defaultowy range)
    all_first = [_parse_iso_safe(e["first_seen"]) for e in entries]
    all_last = [_parse_iso_safe(e["last_seen"]) for e in entries]
    all_first = [d for d in all_first if d]
    all_last = [d for d in all_last if d]

    date_min = min(all_first).isoformat() if all_first else None
    date_max = max(all_last).isoformat() if all_last else None

    output = {
        "generated_at": datetime.now().isoformat(),
        "source_last_scan": data.get("last_scan"),
        "total_offers": len(offers),
        "offers_with_change": len(entries),
        "date_range": {"min": date_min, "max": date_max},
        "entries": entries,
    }

    p_out = Path(output_path)
    p_out.parent.mkdir(parents=True, exist_ok=True)
    with open(p_out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return {
        "total_offers": len(offers),
        "with_change": len(entries),
        "drops": sum(1 for e in entries if e["trend"] == "down"),
        "rises": sum(1 for e in entries if e["trend"] == "up"),
        "output_path": str(p_out),
    }


if __name__ == "__main__":
    import sys
    offers_arg = sys.argv[1] if len(sys.argv) > 1 else "../data/offers.json"
    out_arg = sys.argv[2] if len(sys.argv) > 2 else "../docs/top5_data.json"
    stats = generate(offers_arg, out_arg)
    print("📊 TOP5 generator zakończony:")
    print(f"   Łącznie ofert:        {stats['total_offers']}")
    print(f"   Ze zmianą ceny:       {stats['with_change']}")
    print(f"   Spadki:               {stats['drops']}")
    print(f"   Wzrosty:              {stats['rises']}")
    print(f"   Plik wyjściowy:       {stats['output_path']}")
