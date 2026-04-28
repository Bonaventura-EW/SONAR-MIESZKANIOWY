"""
Quick scan - 5 stron dla szybkiej naprawy
"""
from main import SonarMieszkaniowy

# Nadpisz scraper na mniej stron
class QuickSonar(SonarMieszkaniowy):
    def run_quick_scan(self):
        """Scan tylko 5 stron (szybki)"""
        import time
        from datetime import datetime
        
        print("\n" + "="*60)
        print("🎯 SONAR MIESZKANIOWY - QUICK SCAN (5 stron)")
        print("="*60 + "\n")
        
        scan_start_time = time.time()
        now = datetime.now(self.tz)
        print(f"⏰ Czas: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
        
        self.scan_logger.start_scan()
        
        try:
            # 1. WYCZYŚĆ STARĄ BAZĘ
            print("🗑️ Czyszczenie starej bazy...")
            self.database['offers'] = []
            
            # 2. Scraping - tylko 5 stron
            print("📡 Scraping OLX (5 stron)...")
            scraping_start = time.time()
            raw_offers = self.scraper.scrape_all_pages(max_pages=5)
            scraping_duration = time.time() - scraping_start
            
            self.scan_logger.log_phase('scraping', scraping_duration, {
                'offers_found': len(raw_offers),
                'max_pages': 5
            })
            
            print(f"✅ Pobrano {len(raw_offers)} ofert\n")
            
            # 3. Przetwarzanie (skopiowane z main.py)
            print("🔧 Przetwarzanie ofert...")
            processing_start = time.time()
            
            processed_offers = []
            skipped_no_address = 0
            skipped_no_price = 0
            skipped_no_coords = 0
            skipped_duplicate = 0
            skipped_removed = 0
            
            for i, raw_offer in enumerate(raw_offers, 1):
                if i % 10 == 0:
                    print(f"   [{i}/{len(raw_offers)}]...")
                
                offer_id = raw_offer['url'].split('/')[-1].split('.')[0]
                
                if offer_id in self.removed_listings:
                    skipped_removed += 1
                    continue
                
                processed = self._process_offer(raw_offer)
                
                if not processed:
                    full_text = raw_offer['title'] + " " + raw_offer.get('description', '')
                    if not self.address_parser.extract_address(full_text):
                        skipped_no_address += 1
                    elif not self.price_parser.extract_price(full_text) and not raw_offer.get('official_price'):
                        skipped_no_price += 1
                    else:
                        skipped_no_coords += 1
                    continue
                
                if self.duplicate_detector.filter_duplicates(processed, processed_offers):
                    skipped_duplicate += 1
                    continue
                
                processed_offers.append(processed)
            
            processing_duration = time.time() - processing_start
            
            print(f"\n✅ Przetworzone: {len(processed_offers)} (w {processing_duration:.1f}s)")
            print(f"   Pominięte - brak adresu: {skipped_no_address}")
            print(f"   Pominięte - brak ceny: {skipped_no_price}")
            print(f"   Pominięte - brak coords: {skipped_no_coords}")
            print(f"   Pominięte - duplikaty: {skipped_duplicate}")
            print(f"   Pominięte - usunięte: {skipped_removed}\n")
            
            # 4. Zapisz do bazy
            print("💾 Zapisywanie do bazy...")
            self.database['offers'] = processed_offers
            self.database['last_scan'] = now.isoformat()
            self.database['next_scan'] = self._calculate_next_scan_time()
            
            self._save_database()
            
            # 5. Loguj
            total_duration = time.time() - scan_start_time
            active = sum(1 for o in self.database['offers'] if o['active'])
            
            self.scan_logger.log_stats({
                'raw_offers': len(raw_offers),
                'processed': len(processed_offers),
                'new': len(processed_offers),
                'active': active,
                'skipped_no_address': skipped_no_address,
                'skipped_no_price': skipped_no_price,
                'skipped_no_coords': skipped_no_coords,
                'skipped_duplicate': skipped_duplicate,
                'skipped_removed': skipped_removed
            })
            
            self.scan_logger.end_scan('completed', total_duration)
            
            print("\n" + "="*60)
            print("📊 PODSUMOWANIE")
            print("="*60)
            print(f"✅ Aktywnych ofert: {active}")
            print(f"📦 Łącznie w bazie: {len(self.database['offers'])}")
            print(f"⏱️ Czas: {total_duration:.1f}s")
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"\n❌ Błąd: {e}")
            import traceback
            traceback.print_exc()
            self.scan_logger.log_error(str(e))
            self.scan_logger.end_scan('failed', time.time() - scan_start_time)
            raise

if __name__ == "__main__":
    agent = QuickSonar(data_file="../data/offers.json")
    agent.run_quick_scan()

