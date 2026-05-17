#!/usr/bin/env python3
"""
JEDNORAZOWA migracja: dodaje pole price_changes do istniejących ofert w offers.json
Dla ofert które mają history > 1 ale nie mają jeszcze price_changes.

Strategia rozdzielania timestampów (gdy mamy N>2 zmian, a znamy tylko czas ostatniej):
- Ostatnia zmiana: użyj price_changed_at (jeśli jest), inaczej last_seen
- Pierwsza "zmiana": użyj first_seen + 1 dzień (oferta musiała istnieć zanim cena się zmieniła)
- Pośrednie zmiany: rozłóż liniowo między first_seen a price_changed_at

To jest tylko aproksymacja dla danych historycznych - nowe zmiany od teraz będą
miały dokładne timestampy zapisane w runtime.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path


def parse_iso(s: str) -> datetime:
    """Parsuje ISO 8601 z timezone."""
    return datetime.fromisoformat(s)


def migrate(offers_path: str = "../data/offers.json") -> dict:
    """Wykonuje migrację i zwraca statystyki."""
    p = Path(offers_path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    offers = data["offers"]
    stats = {"total": len(offers), "with_history": 0, "migrated": 0, "skipped": 0}

    for offer in offers:
        price = offer.get("price", {})
        history = price.get("history", [])

        if len(history) <= 1:
            continue
        stats["with_history"] += 1

        # Już zmigrowane - pomijamy
        if "price_changes" in price and len(price["price_changes"]) >= len(history) - 1:
            stats["skipped"] += 1
            continue

        # Buduj listę price_changes z aproksymowanymi timestampami
        first_seen = parse_iso(offer["first_seen"])
        last_seen = parse_iso(offer["last_seen"])

        # Czas ostatniej zmiany - najlepsza dostępna informacja
        if price.get("price_changed_at"):
            last_change_time = parse_iso(price["price_changed_at"])
        else:
            last_change_time = last_seen

        num_changes = len(history) - 1  # N zmian dla N+1 wartości w history

        # Rozłóż czasy zmian liniowo między first_seen a last_change_time
        # Każda zmiana powinna nastąpić PO first_seen (oferta musiała się pojawić)
        price_changes = []
        for i in range(num_changes):
            old_price = history[i]
            new_price = history[i + 1]

            if num_changes == 1:
                # Tylko jedna zmiana - użyj last_change_time
                changed_at = last_change_time
            else:
                # Wiele zmian - rozłóż między first_seen+offset a last_change_time
                # offset = 1 dzień (oferta musiała istnieć zanim cena się zmieniła)
                start = first_seen + timedelta(days=1)
                if start >= last_change_time:
                    start = first_seen
                # Liniowa interpolacja: i-ta zmiana (0-indexed) z N całkowitych
                frac = (i + 1) / num_changes  # 1/N, 2/N, ..., N/N
                changed_at = start + (last_change_time - start) * frac

            price_changes.append({
                "old_price": old_price,
                "new_price": new_price,
                "changed_at": changed_at.isoformat(),
                "trend": "down" if new_price < old_price else "up",
                "approximated": True,  # flaga: timestamp jest aproksymowany
            })

        price["price_changes"] = price_changes
        stats["migrated"] += 1

    # Backup oryginału
    backup_path = p.with_suffix(".json.pre_top5_migration.bak")
    if not backup_path.exists():
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Backup zapisany: {backup_path}")

    # Zapis
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return stats


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "../data/offers.json"
    stats = migrate(path)
    print(f"📊 Migracja zakończona:")
    print(f"   Łącznie ofert: {stats['total']}")
    print(f"   Z historią zmian: {stats['with_history']}")
    print(f"   Zmigrowanych: {stats['migrated']}")
    print(f"   Pominiętych (już zmigrowane): {stats['skipped']}")
