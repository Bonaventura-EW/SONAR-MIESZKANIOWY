#!/usr/bin/env python3
"""
Skrypt do ręcznego usuwania ogłoszeń
Użycie: python remove_listing.py <offer_id>
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import pytz

def remove_listing(offer_id: str):
    """Dodaje ID ogłoszenia do listy usuniętych."""
    # Znajdź katalog data/ relatywnie do lokalizacji skryptu
    script_dir = Path(__file__).parent
    removed_file = script_dir.parent / "data" / "removed_listings.json"
    
    # Wczytaj listę usuniętych
    if removed_file.exists():
        with open(removed_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {
            'removed_ids': [],
            'last_updated': None
        }
    
    # Sprawdź czy już jest usunięte
    if offer_id in data['removed_ids']:
        print(f"⚠️ Ogłoszenie {offer_id} już jest na liście usuniętych")
        return
    
    # Dodaj do listy
    data['removed_ids'].append(offer_id)
    data['last_updated'] = datetime.now(pytz.timezone('Europe/Warsaw')).isoformat()
    
    # Zapisz
    with open(removed_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Ogłoszenie {offer_id} dodane do listy usuniętych")
    print(f"💡 Przy następnym scanie to ogłoszenie nie pojawi się na mapie")

def list_removed():
    """Wyświetla listę usuniętych ogłoszeń."""
    script_dir = Path(__file__).parent
    removed_file = script_dir.parent / "data" / "removed_listings.json"
    
    if not removed_file.exists():
        print("📋 Lista usuniętych ogłoszeń jest pusta")
        return
    
    with open(removed_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    removed = data.get('removed_ids', [])
    
    if not removed:
        print("📋 Lista usuniętych ogłoszeń jest pusta")
        return
    
    print(f"\n🗑️ Usunięte ogłoszenia ({len(removed)}):")
    print("=" * 60)
    for i, offer_id in enumerate(removed, 1):
        print(f"{i}. {offer_id}")
    print("=" * 60)
    print(f"Ostatnia aktualizacja: {data.get('last_updated', 'brak')}\n")

def restore_listing(offer_id: str):
    """Usuwa ID ogłoszenia z listy usuniętych (przywrócenie)."""
    script_dir = Path(__file__).parent
    removed_file = script_dir.parent / "data" / "removed_listings.json"
    
    if not removed_file.exists():
        print(f"⚠️ Brak pliku z usuniętymi ogłoszeniami")
        return
    
    with open(removed_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if offer_id not in data['removed_ids']:
        print(f"⚠️ Ogłoszenie {offer_id} nie znajduje się na liście usuniętych")
        return
    
    # Usuń z listy
    data['removed_ids'].remove(offer_id)
    data['last_updated'] = datetime.now(pytz.timezone('Europe/Warsaw')).isoformat()
    
    # Zapisz
    with open(removed_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Ogłoszenie {offer_id} przywrócone (usunięte z listy usuniętych)")
    print(f"💡 Przy następnym scanie to ogłoszenie pojawi się ponownie na mapie")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("""
🗑️ Skrypt do zarządzania usuniętymi ogłoszeniami

Użycie:
  python remove_listing.py <offer_id>       - usuń ogłoszenie
  python remove_listing.py list             - wyświetl listę usuniętych
  python remove_listing.py restore <offer_id> - przywróć ogłoszenie
  
Przykład:
  python remove_listing.py pokoj-jednoosobowy-z-balkonem-CID3-ID14gaar
        """)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_removed()
    elif command == "restore" and len(sys.argv) >= 3:
        restore_listing(sys.argv[2])
    else:
        # Domyślnie - usuń ogłoszenie
        remove_listing(command)
