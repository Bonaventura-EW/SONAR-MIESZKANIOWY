// SONAR MIESZKANIOWY - JavaScript
// Interaktywna mapa z filtrami, wyszukiwaniem i warstwami

// Helper: parsowanie daty z formatu polskiego "DD.MM.YYYY HH:MM"
function parsePolishDate(str) {
    if (!str) return null;
    try {
        const parts = str.split(' ');
        const d = parts[0].split('.');
        const t = (parts[1] || '00:00').split(':');
        return new Date(
            parseInt(d[2]),
            parseInt(d[1]) - 1,
            parseInt(d[0]),
            parseInt(t[0]),
            parseInt(t[1])
        );
    } catch (e) {
        return null;
    }
}

let map;
let mapData;
let allMarkers = [];
let markerLayers = {
    active: L.layerGroup(),
    inactive: L.layerGroup(),
    damaged: L.layerGroup(),      // Warstwa dla ogłoszeń oznaczonych jako uszkodzone
    approx: L.layerGroup(),       // Aktywne ogłoszenia bez numeru domu (kwadratowe markery)
    approxInactive: L.layerGroup() // Nieaktywne ogłoszenia bez numeru domu (historia przybliżonych)
};

// ===== Filtr daty dodania (suwak dni) =====
// Stan: mapowanie "YYYY-MM-DD" -> liczba ofert w tym dniu, lista dni w zakresie
let dateSliderState = {
    enabled: false,
    days: [],            // posortowana tablica Date (północ) od najstarszego do najnowszego
    countsPerDay: {},    // klucz "YYYY-MM-DD" -> liczba ofert z first_seen tego dnia
    selectedIndex: -1    // indeks aktualnie wybranego dnia w days[]
};

function dayKey(date) {
    // Format klucza "YYYY-MM-DD" niezależny od strefy
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function formatDayPL(date) {
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    return `${d}.${m}.${date.getFullYear()}`;
}

// Warstwy uczelni
let universityLayers = {};
const universities = {
    kul: {
        name: "KUL",
        fullName: "Katolicki Uniwersytet Lubelski",
        color: "#1e88e5",
        locations: [
            { name: "Kampus Główny", lat: 51.2475, lng: 22.5450, radius: 120 },
            { name: "Konstantynów (Medyczny)", lat: 51.2382, lng: 22.5014, radius: 140 },
            { name: "Biblioteka", lat: 51.2438, lng: 22.5538, radius: 70 },
            { name: "Collegium Iuridicum", lat: 51.2494, lng: 22.5543, radius: 60 },
            { name: "Akademik Idzi", lat: 51.2505, lng: 22.5605, radius: 50 }
        ]
    },
    umcs: {
        name: "UMCS",
        fullName: "Uniwersytet Marii Curie-Skłodowskiej",
        color: "#43a047",
        locations: [
            { name: "Rektorat", lat: 51.2455, lng: 22.5409, radius: 100 },
            { name: "Biblioteka Główna", lat: 51.2464, lng: 22.5411, radius: 70 },
            { name: "Wydz. Ekonomiczny", lat: 51.2456, lng: 22.5408, radius: 80 },
            { name: "Wydz. Prawa", lat: 51.2454, lng: 22.5408, radius: 80 },
            { name: "Wydz. Mat-Fiz-Inf", lat: 51.2458, lng: 22.5422, radius: 90 },
            { name: "Wydz. Chemii", lat: 51.2447, lng: 22.5424, radius: 80 },
            { name: "Wydz. Filozofii", lat: 51.2452, lng: 22.5412, radius: 70 },
            { name: "Wydz. Pedagogiki", lat: 51.2466, lng: 22.5259, radius: 80 },
            { name: "Wydz. Artystyczny", lat: 51.2480, lng: 22.5222, radius: 70 },
            { name: "Wydz. Politologii", lat: 51.2470, lng: 22.5243, radius: 80 },
            { name: "Wydz. Nauk o Ziemi", lat: 51.2478, lng: 22.5235, radius: 70 },
            { name: "Miasteczko Akad.", lat: 51.2466, lng: 22.5336, radius: 150 }
        ]
    },
    politechnika: {
        name: "Politechnika",
        fullName: "Politechnika Lubelska",
        color: "#ff5722",
        locations: [
            { name: "Wydz. Budownictwa", lat: 51.2354, lng: 22.5480, radius: 80 },
            { name: "Wydz. Zarządzania", lat: 51.2347, lng: 22.5484, radius: 70 },
            { name: "Wydz. Mechaniczny", lat: 51.2369, lng: 22.5501, radius: 90 },
            { name: "Wydz. Elektrotechniki", lat: 51.2368, lng: 22.5488, radius: 80 },
            { name: "Wydz. Inż. Środowiska", lat: 51.2346, lng: 22.5478, radius: 70 },
            { name: "Wydz. Matematyki", lat: 51.2350, lng: 22.5489, radius: 60 },
            { name: "Centrum Innowacji", lat: 51.2362, lng: 22.5512, radius: 70 }
        ]
    },
    wspa: {
        name: "WSPA",
        fullName: "Wyższa Szkoła Przedsiębiorczości i Administracji",
        color: "#9c27b0",
        locations: [
            { name: "Kampus WSPA", lat: 51.2701, lng: 22.5695, radius: 100 }
        ]
    },
    up: {
        name: "UP",
        fullName: "Uniwersytet Przyrodniczy",
        color: "#009688",
        locations: [
            { name: "Rektorat", lat: 51.2437, lng: 22.5401, radius: 90 },
            { name: "Biblioteka Główna", lat: 51.2435, lng: 22.5414, radius: 60 },
            { name: "Wydz. Weterynarii", lat: 51.2444, lng: 22.5435, radius: 80 },
            { name: "Klinika Weteryn.", lat: 51.2414, lng: 22.5424, radius: 90 },
            { name: "Centrum Innowacji", lat: 51.2408, lng: 22.5450, radius: 70 },
            { name: "Wydz. Inż. Produkcji", lat: 51.2438, lng: 22.5404, radius: 70 },
            { name: "Wydz. Żywności", lat: 51.2493, lng: 22.5110, radius: 90 },
            { name: "Felin (Doświadcz.)", lat: 51.2271, lng: 22.6350, radius: 150 }
        ]
    },
    umed: {
        name: "UM",
        fullName: "Uniwersytet Medyczny",
        color: "#e91e63",
        locations: [
            { name: "Rektorat", lat: 51.2482, lng: 22.5488, radius: 80 },
            { name: "Collegium Medicum", lat: 51.2496, lng: 22.5594, radius: 70 },
            { name: "Collegium Maximum", lat: 51.2487, lng: 22.5620, radius: 60 },
            { name: "Szpital SPSK1", lat: 51.2507, lng: 22.5626, radius: 100 },
            { name: "Collegium Universum", lat: 51.2593, lng: 22.5681, radius: 90 },
            { name: "Centrum Symulacji", lat: 51.2611, lng: 22.5642, radius: 70 },
            { name: "Pharmaceuticum", lat: 51.2618, lng: 22.5636, radius: 60 },
            { name: "Szpital Dziecięcy", lat: 51.2605, lng: 22.5607, radius: 100 }
        ]
    },
    awp: {
        name: "AWP",
        fullName: "Akademia Wincentego Pola",
        color: "#ff9800",
        locations: [
            { name: "Kampus AWP", lat: 51.2700, lng: 22.5572, radius: 100 }
        ]
    },
    ansim: {
        name: "ANSiM",
        fullName: "Akademia Nauk Społecznych i Medycznych",
        color: "#795548",
        locations: [
            { name: "Kampus ANSiM", lat: 51.2403, lng: 22.5700, radius: 90 }
        ]
    }
};

// LocalStorage dla ogłoszeń oznaczonych jako uszkodzone
const DAMAGED_KEY = 'sonar_damaged_listings';

// Pomocnicze funkcje dla damaged listings
function getDamagedListings() {
    const stored = localStorage.getItem(DAMAGED_KEY);
    return stored ? JSON.parse(stored) : [];
}

function addToDamaged(offerId) {
    const damaged = getDamagedListings();
    if (!damaged.includes(offerId)) {
        damaged.push(offerId);
        localStorage.setItem(DAMAGED_KEY, JSON.stringify(damaged));
        return true;
    }
    return false;
}

function removeFromDamaged(offerId) {
    let damaged = getDamagedListings();
    damaged = damaged.filter(id => id !== offerId);
    localStorage.setItem(DAMAGED_KEY, JSON.stringify(damaged));
}

function isDamaged(offerId) {
    return getDamagedListings().includes(offerId);
}

// Inicjalizacja mapy
function initMap() {
    // Centrum Lublina
    map = L.map('map').setView([51.2465, 22.5684], 13);
    
    // Tile layer (OpenStreetMap)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);
    
    // Dodaj warstwy do mapy
    markerLayers.active.addTo(map);
    markerLayers.inactive.addTo(map);
    // markerLayers.damaged NIE dodajemy - będzie domyślnie ukryta
    // markerLayers.approx NIE dodajemy - domyślnie ukryta (przybliżone aktywne)
    // markerLayers.approxInactive NIE dodajemy - domyślnie ukryta (przybliżone nieaktywne)
    
    // Tworzenie warstw uczelni
    createUniversityLayers();
}

// Wczytanie danych
async function loadData() {
    try {
        // Użyj absolutnej ścieżki dla GitHub Pages
        const baseUrl = window.location.pathname.includes('/SONAR-MIESZKANIOWY/') 
            ? '/SONAR-MIESZKANIOWY/data.json' 
            : '/data.json';
        
        // Próba 1: Z cache-busting
        const timestamp = new Date().getTime();
        const urlWithCache = `${baseUrl}?v=${timestamp}`;
        
        let response = await fetch(urlWithCache);
        
        // Jeśli 404, spróbuj bez cache-busting
        if (!response.ok) {
            console.warn('⚠️ Fetch z cache-busting nie udał się, próbuję bez...');
            response = await fetch(baseUrl);
        }
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const text = await response.text();
        mapData = JSON.parse(text);
        
        console.log(`✅ Załadowano ${mapData.markers?.length || 0} markerów`);
        
        updateScanInfo();
        createPriceRangeFilters();
        createMarkers();
        updateStats();  // Wywołaj PO createMarkers(), żeby allMarkers był wypełniony
        initDateSlider();  // Suwak dni - wymaga wypełnionego allMarkers
        setupEventListeners();
        filterMarkers();  // ✅ Przefiltruj markery zgodnie z początkowymi stanami checkboxów
        initUnlocalisedLayer();  // ✅ Warstwa ofert bez lokacji GPS
        
        console.log('🎉 Mapa gotowa!');
        
    } catch (error) {
        console.error('❌ Błąd wczytywania danych:', error);
        alert('Nie udało się wczytać danych mapy. Sprawdź czy plik data.json istnieje.\n\nBłąd: ' + error.message);
    }
}

// Obliczanie statystyk dla widocznych ofert (po filtrowaniu)
function calculateFilteredStats() {
    const showActive = document.getElementById('layer-active').checked;
    const showInactive = document.getElementById('layer-inactive').checked;
    const showApprox = document.getElementById('layer-approx')?.checked ?? false;
    const showApproxInactive = document.getElementById('layer-approx-inactive')?.checked ?? false;
    
    // Filtr czasowy
    const timeFilter = document.getElementById('time-filter').value;
    const now = new Date();
    let cutoffDate = null;
    
    if (timeFilter !== 'all') {
        const daysAgo = parseInt(timeFilter);
        cutoffDate = new Date(now.getTime() - (daysAgo * 24 * 60 * 60 * 1000));
    }
    
    // Zakresy cenowe - wspólne dla obu warstw
    const selectedRanges = Array.from(document.querySelectorAll('.price-range-filter:checked'))
        .map(cb => cb.dataset.range);
    
    // Wyszukiwanie
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    
    // Funkcja pomocnicza sprawdzająca czy oferta spełnia kryteria czasowe
    function passesTimeFilter(offer) {
        if (!cutoffDate) return true;
        
        try {
            const parts = offer.first_seen.split(' ');
            const dateParts = parts[0].split('.');
            const timeParts = parts[1].split(':');
            const offerDate = new Date(
                parseInt(dateParts[2]),         // year (already full format YYYY)
                parseInt(dateParts[1]) - 1,     // month (0-indexed)
                parseInt(dateParts[0]),         // day
                parseInt(timeParts[0]),         // hour
                parseInt(timeParts[1])          // minute
            );
            return offerDate >= cutoffDate;
        } catch (e) {
            return true; // Jeśli błąd parsowania, uwzględnij ofertę
        }
    }
    
    // Zbierz wszystkie widoczne oferty (aktywne + nieaktywne razem)
    const visibleOffers = [];
    
    allMarkers.forEach(item => {
        // Sprawdź filtr warstwy
        if (item.hasNumber === false) {
            // Markery przybliżone — aktywne i nieaktywne mają osobne checkboxy
            if (item.isActive && !showApprox) return;
            if (!item.isActive && !showApproxInactive) return;
        } else {
            if (item.isActive && !showActive) return;
            if (!item.isActive && !showInactive) return;
        }
        
        // Sprawdź czy marker jest widoczny (jest w odpowiedniej warstwie na mapie)
        const isOnMap = (!item.hasNumber && item.isActive && markerLayers.approx.hasLayer(item.marker)) ||
                        (!item.hasNumber && !item.isActive && markerLayers.approxInactive.hasLayer(item.marker)) ||
                        (item.hasNumber && item.isActive && markerLayers.active.hasLayer(item.marker)) ||
                        (item.hasNumber && !item.isActive && markerLayers.inactive.hasLayer(item.marker));
        
        if (!isOnMap) return;
        
        // Sprawdź wyszukiwanie
        if (searchTerm && !item.address.toLowerCase().includes(searchTerm)) return;
        
        // Sprawdź zakres cenowy (wspólny dla obu warstw)
        if (!selectedRanges.includes(item.priceRange)) return;
        
        // Przetwórz każdą ofertę z tego markera
        item.offers.forEach(offer => {
            // Sprawdź filtr czasowy
            if (!passesTimeFilter(offer)) return;

            // Sprawdź filtr dzienny (suwak dni)
            if (!passesDaySliderFilter(parsePolishDate(offer.first_seen))) return;

            // Oferta przeszła wszystkie filtry - dodaj do listy
            visibleOffers.push(offer);
        });
    });
    
    // Oblicz statystyki
    if (visibleOffers.length === 0) {
        return null; // Brak ofert
    }
    
    const prices = visibleOffers.map(o => o.price);
    return {
        count: visibleOffers.length,
        avg: Math.round(prices.reduce((a, b) => a + b, 0) / prices.length),
        min: Math.min(...prices),
        max: Math.max(...prices)
    };
}

// Aktualizacja wyświetlanych statystyk
function updateStats() {
    const stats = calculateFilteredStats();
    
    if (stats) {
        document.getElementById('visible-count').textContent = stats.count;
        document.getElementById('avg-price').textContent = stats.avg + ' zł';
        document.getElementById('min-price').textContent = stats.min + ' zł';
        document.getElementById('max-price').textContent = stats.max + ' zł';
    } else {
        // Brak ofert spełniających kryteria
        document.getElementById('visible-count').textContent = '-';
        document.getElementById('avg-price').textContent = '-';
        document.getElementById('min-price').textContent = '-';
        document.getElementById('max-price').textContent = '-';
    }
    
    // Licznik przybliżonych lokalizacji
    const approxCountEl = document.getElementById('approx-count');
    if (approxCountEl) {
        const approxTotal = allMarkers.filter(m => !m.hasNumber && m.isActive).length;
        approxCountEl.textContent = approxTotal > 0 ? `(${approxTotal})` : '(0)';
    }
    const approxInactiveCountEl = document.getElementById('approx-inactive-count');
    if (approxInactiveCountEl) {
        const approxInactiveTotal = allMarkers.filter(m => !m.hasNumber && !m.isActive).length;
        approxInactiveCountEl.textContent = approxInactiveTotal > 0 ? `(${approxInactiveTotal})` : '(0)';
    }
}

// Aktualizacja informacji o skanach
function updateScanInfo() {
    document.getElementById('last-scan').textContent = mapData.scan_info.last;
    document.getElementById('next-scan').textContent = mapData.scan_info.next;
}

// Tworzenie checkboxów dla zakresów cenowych
function createPriceRangeFilters() {
    const container = document.getElementById('price-range-filters');
    
    Object.entries(mapData.price_ranges).forEach(([key, range]) => {
        const label = document.createElement('label');
        label.innerHTML = `
            <input type="checkbox" class="price-range-filter" data-range="${key}" checked>
            <span style="display:inline-block; width:15px; height:15px; background:${range.color}; margin-right:5px; vertical-align:middle; border-radius:50%;"></span>
            ${range.label}
        `;
        container.appendChild(label);
    });
}

// Tworzenie markerów
function createMarkers() {
    allMarkers = [];
    
    mapData.markers.forEach(marker => {
        const coords = marker.coords;
        const address = marker.address;
        const offers = marker.offers;
        const hasActive = marker.has_active;
        
        // Grupuj oferty: aktywne osobno, nieaktywne osobno
        const activeOffers = offers.filter(o => o.active);
        const inactiveOffers = offers.filter(o => !o.active);
        
        // Twórz marker dla aktywnych (jeśli są)
        if (activeOffers.length > 0) {
            createMarkerGroup(coords, address, activeOffers, true);
        }
        
        // Twórz marker dla nieaktywnych (jeśli są)
        if (inactiveOffers.length > 0) {
            createMarkerGroup(coords, address, inactiveOffers, false);
        }
    });
}

// Tworzenie grupy markerów (rozsunięcie dla tego samego adresu)
function createMarkerGroup(baseCoords, address, offers, isActive) {
    // Oblicz offset bazowy - ~10 metrów między markerami (0.0001 stopnia ≈ 10m)
    const baseOffset = 0.0001;
    
    offers.forEach((offer, index) => {
        // Pobierz kolor z zakresu cenowego oferty
        const offerPriceRange = offer.price_range;
        const color = mapData.price_ranges[offerPriceRange]?.color || '#808080';
        
        // Sprawdź czy oferta jest oznaczona jako uszkodzona
        const isDamagedOffer = isDamaged(offer.id);
        
        // Oblicz offset w kole (rozsunięcie)
        // Każda oferta na innym kącie, promień rośnie z ilością ofert
        const totalOffers = offers.length;
        
        let offsetLat = 0;
        let offsetLon = 0;
        
        if (totalOffers > 1) {
            const angle = (index / totalOffers) * 2 * Math.PI;
            // Promień zależny od pozycji - spirala
            const radius = baseOffset * (0.5 + index * 0.5);
            offsetLat = Math.cos(angle) * radius;
            offsetLon = Math.sin(angle) * radius * 1.5; // 1.5x bo longitude jest "węższa"
        }
        
        // Konwersja z obiektu {lat, lon} na tablicę [lat, lon] dla Leaflet
        const coords = [
            baseCoords.lat + offsetLat,
            baseCoords.lon + offsetLon
        ];
        
        // Tooltip (pojawia się przy hover)
        const price = offer.price;
        const tooltipText = isDamagedOffer 
            ? `⚠️ USZKODZONE: ${address} - ${price} zł`
            : `${address} - ${price} zł`;
        
        // Sprawdź czy oferta jest nowa (z ostatniego skanu)
        const isNew = offer.is_new === true;
        
        // Sprawdź czy cena się zmieniła
        const hasPriceChange = offer.previous_price && offer.price_trend;
        const priceUp = offer.price_trend === 'up';
        const priceDown = offer.price_trend === 'down';
        
        // DEBUG: Log ofert ze zmianą ceny
        if (hasPriceChange) {
            console.log(`💲 Zmiana ceny: ${address} | ${offer.previous_price} → ${offer.price} (${offer.price_trend})`);
        }
        
        // Sprawdź czy oferta ma znany numer domu
        const hasNumber = offer.has_number !== false;  // domyślnie true (wsteczna kompatybilność)

        // Ikona markera - pinezka z kolorem
        // Jeśli uszkodzone - pomarańczowy, jeśli nowa - czerwona obwódka, inaczej - biała
        const strokeColor = isDamagedOffer ? '#ff6600' : (isNew ? '#ff0000' : 'white');
        const strokeWidth = isDamagedOffer ? '4' : (isNew ? '3' : '2');
        const markerColor = isDamagedOffer ? '#ff9933' : color;  // Pomarańczowy dla uszkodzonych

        // Badge zmiany ceny - ikona dolara ze strzałką
        let priceChangeBadge = '';
        if (hasPriceChange && !isDamagedOffer) {
            const badgeColor = priceDown ? '#28a745' : '#dc3545';  // Zielony=spadek, Czerwony=wzrost
            const arrow = priceDown ? '↓' : '↑';
            priceChangeBadge = `
                <div style="
                    position: absolute; 
                    top: -8px; 
                    right: -8px; 
                    background: ${badgeColor}; 
                    color: white; 
                    border-radius: 10px; 
                    min-width: 28px; 
                    height: 20px; 
                    font-size: 11px; 
                    font-weight: bold; 
                    display: flex; 
                    align-items: center; 
                    justify-content: center; 
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                    padding: 0 4px;
                    border: 2px solid white;
                    z-index: 1000;
                ">💲${arrow}</div>
            `;
        }

        let icon;
        if (!hasNumber) {
            // ===== MARKER KWADRATOWY dla ulic bez numeru =====
            // Przybliżona lokalizacja - wyświetlony na środku ulicy
            icon = L.divIcon({
                className: 'square-marker',
                html: `
                    <div style="position: relative; width: 36px; height: 36px;" title="~${tooltipText}">
                        <svg width="36" height="36" viewBox="0 0 36 36" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.35));">
                            <rect x="2" y="2" width="32" height="32" rx="7" ry="7"
                                  fill="${markerColor}"
                                  stroke="${isDamagedOffer ? '#ff6600' : 'white'}"
                                  stroke-width="${isDamagedOffer ? 3 : 2}"
                                  stroke-dasharray="5 3"/>
                            <circle cx="18" cy="18" r="7" fill="white" opacity="0.85"/>
                            <text x="18" y="22" text-anchor="middle" font-size="10" font-weight="bold"
                                  fill="${markerColor}" font-family="Arial,sans-serif">~</text>
                        </svg>
                        ${isNew && !hasPriceChange ? '<div style="position: absolute; top: -5px; right: -5px; background: #ff0000; color: white; border-radius: 50%; width: 16px; height: 16px; font-size: 10px; font-weight: bold; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.3);">N</div>' : ''}
                        ${priceChangeBadge}
                        ${isDamagedOffer ? '<div style="position: absolute; top: -5px; left: -5px; background: #ff6600; color: white; border-radius: 50%; width: 18px; height: 18px; font-size: 12px; font-weight: bold; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.3);">⚠</div>' : ''}
                    </div>
                `,
                iconSize: [36, 36],
                iconAnchor: [18, 18],   // Środek kwadratu (nie czubek pinezki)
                popupAnchor: [0, -20]
            });
        } else {
            // ===== MARKER PINEZKA (standardowy, z numerem domu) =====
            icon = L.divIcon({
            className: 'pin-marker',
            html: `
                <div style="position: relative; width: 40px; height: 50px;" title="${tooltipText}">
                    <svg width="40" height="50" viewBox="0 0 40 50" style="filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
                        <path d="M20 0 C9 0 0 9 0 20 C0 35 20 50 20 50 C20 50 40 35 40 20 C40 9 31 0 20 0 Z" 
                              fill="${markerColor}" 
                              stroke="${strokeColor}" 
                              stroke-width="${strokeWidth}"/>
                        <circle cx="20" cy="18" r="8" fill="white" opacity="0.9"/>
                    </svg>
                    ${!isActive ? '<div style="position: absolute; top: 8px; left: 50%; transform: translateX(-50%); font-size: 24px;">×</div>' : ''}
                    ${isNew && !hasPriceChange ? '<div style="position: absolute; top: -5px; right: -5px; background: #ff0000; color: white; border-radius: 50%; width: 16px; height: 16px; font-size: 10px; font-weight: bold; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.3);">N</div>' : ''}
                    ${priceChangeBadge}
                    ${isDamagedOffer ? '<div style="position: absolute; top: -5px; left: -5px; background: #ff6600; color: white; border-radius: 50%; width: 18px; height: 18px; font-size: 12px; font-weight: bold; display: flex; align-items: center; justify-content: center; box-shadow: 0 1px 3px rgba(0,0,0,0.3);">⚠</div>' : ''}
                </div>
            `,
            iconSize: [40, 50],
            iconAnchor: [20, 50],
            popupAnchor: [0, -50]
        });
        } // end if hasNumber
        
        // Popup content
        const popupContent = createPopupContent(address, [offer]);
        
        // Tworzenie markera z tooltip
        const markerObj = L.marker(coords, { 
            icon: icon,
            title: tooltipText  // Tooltip przy hover
        })
            .bindPopup(popupContent, { maxWidth: 400 });
        
        // Dodaj do odpowiedniej warstwy
        if (isDamagedOffer) {
            markerObj.addTo(markerLayers.damaged);
        } else if (!hasNumber && isActive) {
            markerObj.addTo(markerLayers.approx);          // ⬜ Aktywne przybliżone
        } else if (!hasNumber && !isActive) {
            markerObj.addTo(markerLayers.approxInactive);  // ⬜ Nieaktywne przybliżone (historia)
        } else if (isActive) {
            markerObj.addTo(markerLayers.active);
        } else {
            markerObj.addTo(markerLayers.inactive);
        }
        
        // Zapisz referencję - używamy price_range z oferty
        allMarkers.push({
            marker: markerObj,
            address: address,
            offers: [offer],
            priceRange: offerPriceRange,  // ✅ Zakres cenowy z oferty
            isActive: isActive,
            isDamaged: isDamagedOffer,
            hasNumber: hasNumber,           // ✅ Czy znany numer domu
            primaryTag: offer.tags ? offer.tags.primary : 'pokoj',  // B1: Tag główny
            // Flagi oznaczeń pinezek (do filtrowania legendy)
            isNew: isNew,
            priceDown: hasPriceChange && priceDown && !isDamagedOffer,
            priceUp: hasPriceChange && priceUp && !isDamagedOffer,
            // Daty do filtrowania zakresem dat
            firstSeenDate: parsePolishDate(offer.first_seen),
            priceChangedAtDate: parsePolishDate(offer.price_changed_at)
        });
    });
    
    // B1: Aktualizuj liczniki tagów
    updateTagCounts();
    // Aktualizuj liczniki oznaczeń (legenda)
    updateBadgeCounts();
}

// Tworzenie HTML popup
function createPopupContent(address, offers) {
    let html = `<div class="offer-popup">`;
    html += `<h3>📍 ${address}</h3>`;
    
    offers.forEach(offer => {
        const isActive = offer.active;
        const isApprox = offer.has_number === false;

        html += `<div class="offer-item ${isActive ? '' : 'inactive'}" data-offer-id="${offer.id}">`;

        if (!isActive) {
            html += `<div class="inactive-badge">❌ Nieaktywne</div>`;
        }
        if (isApprox) {
            html += `<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:5px 8px;margin-bottom:8px;font-size:12px;color:#856404;">
                ⬜ <strong>Lokalizacja przybliżona</strong> — brak numeru domu w ogłoszeniu.<br>
                Marker umieszczony na środku ulicy.
            </div>`;
        }
        
        // Cena - NOWE: wyświetlanie zmiany ceny
        if (offer.previous_price && offer.price_trend) {
            const priceDiff = offer.price - offer.previous_price;
            const trendIcon = offer.price_trend === 'down' ? '📉' : '📈';
            const trendColor = offer.price_trend === 'down' ? '#28a745' : '#dc3545';
            const trendSign = offer.price_trend === 'down' ? '' : '+';
            
            html += `<div class="offer-price ${isActive ? '' : 'inactive'}">`;
            html += `💰 <strong style="font-size: 1.2em;">${offer.price} zł</strong>`;
            html += `<span style="color: ${trendColor}; font-weight: bold; margin-left: 8px;">`;
            html += `${trendIcon} ${trendSign}${priceDiff} zł</span>`;
            html += `</div>`;
            
            // Poprzednia cena
            html += `<div class="previous-price" style="color: #888; font-size: 0.9em; margin-top: 2px;">`;
            html += `<s>Poprzednio: ${offer.previous_price} zł</s>`;
            if (offer.price_changed_at) {
                html += ` <span style="font-size: 0.85em;">(zmiana: ${offer.price_changed_at})</span>`;
            }
            html += `</div>`;
        } else {
            html += `<div class="offer-price ${isActive ? '' : 'inactive'}">💰 ${offer.price} zł</div>`;
        }
        
        // Historia cen (pełna)
        if (offer.price_history && offer.price_history.length > 1) {
            const history = offer.price_history.map(p => p + ' zł').join(' → ');
            html += `<div class="price-history" style="color: #666; font-size: 0.85em; margin-top: 4px;">📊 Historia: ${history}</div>`;
        }
        
        // Media info
        html += `<div class="media-info">Skład: ${offer.media_info}</div>`;
        
        // B1: Tag oferty
        if (offer.tags && offer.tags.primary) {
            const tagIcons = { pokoj: '🛏️', kawalerka: '🏠', mieszkanie: '🏢' };
            const tagLabels = { pokoj: 'Pokój', kawalerka: 'Kawalerka', mieszkanie: 'Mieszkanie' };
            const tagColors = { pokoj: '#3b82f6', kawalerka: '#10b981', mieszkanie: '#8b5cf6' };
            
            const primary = offer.tags.primary;
            html += `<div class="offer-tag" style="margin: 8px 0; display: inline-block; padding: 4px 10px; background: ${tagColors[primary]}22; border: 1px solid ${tagColors[primary]}; border-radius: 12px; font-size: 12px; color: ${tagColors[primary]}; font-weight: 600;">`;
            html += `${tagIcons[primary] || ''} ${tagLabels[primary] || primary}`;
            if (offer.tags.secondary && offer.tags.secondary.length > 0) {
                html += ` <span style="opacity: 0.7;">+ ${offer.tags.secondary.map(t => tagLabels[t] || t).join(', ')}</span>`;
            }
            html += `</div>`;
        }
        
        // Link
        html += `<a href="${offer.url}" target="_blank" class="offer-link">🔗 Otwórz ogłoszenie</a>`;
        
        // Przycisk: Oznacz jako uszkodzone / Przywróć
        if (isDamaged(offer.id)) {
            html += `<button class="restore-listing-btn" onclick="restoreListing('${offer.id}')" style="margin-top: 10px; padding: 5px 10px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">✅ Przywróć ogłoszenie</button>`;
        } else {
            html += `<button class="mark-damaged-btn" onclick="markAsDamaged('${offer.id}')" style="margin-top: 10px; padding: 5px 10px; background: #ff6600; color: white; border: none; border-radius: 4px; cursor: pointer;">⚠️ Oznacz jako uszkodzone</button>`;
        }
        
        // Opis - z funkcją zwijania/rozwijania
        const maxChars = 100; // Maksymalna długość podglądu (~1-2 linie)
        const needsTruncate = offer.description.length > maxChars;
        
        if (needsTruncate) {
            const uniqueId = `desc-${offer.id}`;
            const shortDescription = offer.description.substring(0, maxChars);
            
            html += `
                <div class="offer-description">
                    <div id="${uniqueId}-short">
                        📝 ${shortDescription}...
                        <br><a href="javascript:void(0)" onclick="toggleDescription('${uniqueId}')" class="show-more-link">▼ Pokaż całość</a>
                    </div>
                    <div id="${uniqueId}-full" style="display: none;">
                        📝 ${offer.description}
                        <br><a href="javascript:void(0)" onclick="toggleDescription('${uniqueId}')" class="show-more-link">▲ Zwiń</a>
                    </div>
                </div>
            `;
        } else {
            html += `<div class="offer-description">📝 ${offer.description}</div>`;
        }
        
        // Daty
        if (isActive) {
            html += `<div class="offer-dates">`;
            html += `📅 Dodano: ${offer.first_seen}<br>`;
            html += `📅 Ostatnio widziane: ${offer.last_seen}<br>`;
            html += `⏱️ Dni aktywności: ${offer.days_active}`;
            html += `</div>`;
        } else {
            html += `<div class="offer-dates">`;
            html += `📅 Aktywna przez: ${offer.days_active} dni<br>`;
            html += `📅 Nieaktywna od: ${offer.last_seen}<br>`;
            html += `💰 Ostatnia cena: ${offer.price} zł`;
            html += `</div>`;
        }
        
        // Przycisk usuwania
        html += `<button class="delete-offer-btn" onclick="deleteOffer('${offer.id}', '${address}')">🗑️ Usuń z mapy</button>`;
        
        html += `</div>`;
    });
    
    html += `</div>`;
    return html;
}

// Filtrowanie markerów
function filterMarkers() {
    // Pobierz ustawienia filtrów
    const showActive = document.getElementById('layer-active').checked;
    const showInactive = document.getElementById('layer-inactive').checked;
    const showApprox = document.getElementById('layer-approx')?.checked ?? false;
    const showApproxInactive = document.getElementById('layer-approx-inactive')?.checked ?? false;
    
    // B1: Filtry tagów
    const showPokoj = document.getElementById('layer-tag-pokoj')?.checked ?? true;
    const showKawalerka = document.getElementById('layer-tag-kawalerka')?.checked ?? true;
    const showMieszkanie = document.getElementById('layer-tag-mieszkanie')?.checked ?? true;
    
    // Filtry oznaczeń pinezek (legenda)
    const showPriceDown = document.getElementById('badge-filter-price-down')?.checked ?? true;
    const showPriceUp = document.getElementById('badge-filter-price-up')?.checked ?? true;
    const showNew = document.getElementById('badge-filter-new')?.checked ?? true;
    const showDamaged = document.getElementById('badge-filter-damaged')?.checked ?? true;
    
    // NOWY: Filtr czasowy
    const timeFilter = document.getElementById('time-filter').value;
    const now = new Date();
    let cutoffDate = null;
    
    if (timeFilter !== 'all') {
        const daysAgo = parseInt(timeFilter);
        cutoffDate = new Date(now.getTime() - (daysAgo * 24 * 60 * 60 * 1000));
    }
    
    // Zakresy cenowe - wspólne dla obu warstw
    const selectedRanges = Array.from(document.querySelectorAll('.price-range-filter:checked'))
        .map(cb => cb.dataset.range);
    
    // Precyzyjne filtry cen - wspólne dla obu warstw
    const priceMin = parseInt(document.getElementById('price-min').value) || 0;
    const priceMax = parseInt(document.getElementById('price-max').value) || 999999;
    
    // Wyszukiwanie
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    
    // Filtruj markery
    allMarkers.forEach(item => {
        let visible = true;
        
        // Filtr aktywne/nieaktywne (nie dotyczy przybliżonych - mają osobny checkbox)
        if (!item.hasNumber) {
            // Marker przybliżony — aktywne i nieaktywne mają osobne checkboxy
            if (item.isActive && !showApprox) visible = false;
            if (!item.isActive && !showApproxInactive) visible = false;
        } else {
            if (item.isActive && !showActive) visible = false;
            if (!item.isActive && !showInactive) visible = false;
        }
        
        // B1: Filtr tagów
        if (visible) {
            const tag = item.primaryTag || 'pokoj';
            if (tag === 'pokoj' && !showPokoj) visible = false;
            if (tag === 'kawalerka' && !showKawalerka) visible = false;
            if (tag === 'mieszkanie' && !showMieszkanie) visible = false;
        }
        
        // Filtr oznaczeń pinezek (OR) - pinezki bez żadnego oznaczenia zawsze widoczne
        if (visible) {
            const hasAnyBadge = item.isDamaged || item.isNew || item.priceDown || item.priceUp;
            if (hasAnyBadge) {
                // Pokaż, jeśli CHOĆ JEDNO z oznaczeń pinezki jest zaznaczone w legendzie
                const passes =
                    (item.isDamaged && showDamaged) ||
                    (item.isNew && showNew) ||
                    (item.priceDown && showPriceDown) ||
                    (item.priceUp && showPriceUp);
                if (!passes) visible = false;
            }
        }
        
        // Filtr czasowy - uwzględnia first_seen ORAZ price_changed_at
        // Oferta przechodzi gdy KTÓRAKOLWIEK z dat mieści się w zakresie
        if (visible && cutoffDate) {
            const firstSeenOk = item.firstSeenDate && item.firstSeenDate >= cutoffDate;
            const priceChangedOk = item.priceChangedAtDate && item.priceChangedAtDate >= cutoffDate;
            if (!firstSeenOk && !priceChangedOk) {
                visible = false;
            }
        }

        // Filtr dzienny (suwak dni) - oferta widoczna jeśli first_seen = wybrany dzień
        if (visible && !passesDaySliderFilter(item.firstSeenDate)) {
            visible = false;
        }
        
        // Filtr zakresów cenowych - wspólny dla obu warstw
        // Jeśli selectedRanges jest puste (żaden checkbox), pokaż wszystkie
        if (selectedRanges.length > 0 && !selectedRanges.includes(item.priceRange)) {
            visible = false;
        }
        
        // Precyzyjny filtr cen - wspólny dla obu warstw
        const price = item.offers[0].price;
        if (price < priceMin || price > priceMax) {
            visible = false;
        }
        
        // Wyszukiwanie
        if (searchTerm && !item.address.toLowerCase().includes(searchTerm)) {
            visible = false;
        }
        
        // Pokaż/ukryj marker
        if (visible) {
            if (item.isDamaged) {
                markerLayers.damaged.addLayer(item.marker);
            } else if (!item.hasNumber && item.isActive) {
                markerLayers.approx.addLayer(item.marker);
            } else if (!item.hasNumber && !item.isActive) {
                markerLayers.approxInactive.addLayer(item.marker);
            } else if (item.isActive) {
                markerLayers.active.addLayer(item.marker);
            } else {
                markerLayers.inactive.addLayer(item.marker);
            }
        } else {
            if (item.isDamaged) {
                markerLayers.damaged.removeLayer(item.marker);
            } else if (!item.hasNumber && item.isActive) {
                markerLayers.approx.removeLayer(item.marker);
            } else if (!item.hasNumber && !item.isActive) {
                markerLayers.approxInactive.removeLayer(item.marker);
            } else if (item.isActive) {
                markerLayers.active.removeLayer(item.marker);
            } else {
                markerLayers.inactive.removeLayer(item.marker);
            }
        }
    });
    
    // Przelicz i zaktualizuj statystyki po filtrowaniu
    updateStats();
    // Zaktualizuj liczniki oznaczeń (respektują aktualny zakres dat)
    updateBadgeCounts();
}

// Wyszukiwanie z zoomem
function searchAndZoom() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    
    if (!searchTerm) {
        filterMarkers();
        return;
    }
    
    // Znajdź pierwsze dopasowanie
    const match = allMarkers.find(item => 
        item.address.toLowerCase().includes(searchTerm) &&
        (item.isActive ? document.getElementById('layer-active').checked : document.getElementById('layer-inactive').checked)
    );
    
    if (match) {
        const coords = match.marker.getLatLng();
        map.setView(coords, 17);
        match.marker.openPopup();
    }
    
    filterMarkers();
}

// ===== Inicjalizacja suwaka dni =====
// Buduje zakres dni od najstarszego first_seen do DZISIAJ,
// zlicza oferty per dzień i renderuje mini-histogram.
function initDateSlider() {
    const slider = document.getElementById('date-slider');
    const enableCb = document.getElementById('date-filter-enable');
    const control = document.getElementById('date-slider-control');
    const minLabel = document.getElementById('date-slider-min');
    const maxLabel = document.getElementById('date-slider-max');
    const histogram = document.getElementById('date-slider-histogram');

    if (!slider || !enableCb) return;

    // 1. Wyłoń najstarszy first_seen
    let earliest = null;
    allMarkers.forEach(item => {
        if (item.firstSeenDate && (!earliest || item.firstSeenDate < earliest)) {
            earliest = item.firstSeenDate;
        }
    });

    if (!earliest) {
        // Brak danych z datami - wyłącz filtr
        enableCb.disabled = true;
        minLabel.textContent = '—';
        maxLabel.textContent = '—';
        return;
    }

    // 2. Zbuduj tablicę dni: od północy earliest do północy dzisiaj (włącznie)
    const startDay = new Date(earliest.getFullYear(), earliest.getMonth(), earliest.getDate());
    const now = new Date();
    const endDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    const days = [];
    const cursor = new Date(startDay);
    while (cursor <= endDay) {
        days.push(new Date(cursor));
        cursor.setDate(cursor.getDate() + 1);
    }

    // 3. Zlicz oferty per dzień
    const counts = {};
    days.forEach(d => { counts[dayKey(d)] = 0; });
    allMarkers.forEach(item => {
        item.offers.forEach(offer => {
            const fs = parsePolishDate(offer.first_seen);
            if (!fs) return;
            const key = dayKey(fs);
            if (key in counts) {
                counts[key]++;
            }
        });
    });

    dateSliderState.days = days;
    dateSliderState.countsPerDay = counts;
    dateSliderState.selectedIndex = days.length - 1; // start na ostatnim dniu

    // 4. Skonfiguruj suwak
    slider.min = 0;
    slider.max = days.length - 1;
    slider.value = days.length - 1;

    minLabel.textContent = formatDayPL(days[0]);
    maxLabel.textContent = formatDayPL(days[days.length - 1]);

    // 5. Zbuduj histogram
    histogram.innerHTML = '';
    const maxCount = Math.max(1, ...Object.values(counts));

    days.forEach((d, i) => {
        const c = counts[dayKey(d)];
        const bar = document.createElement('div');
        bar.className = 'bar' + (c === 0 ? ' empty' : '');
        const pct = c === 0 ? 8 : Math.max(15, Math.round((c / maxCount) * 100));
        bar.style.height = pct + '%';
        bar.dataset.index = i;
        bar.title = `${formatDayPL(d)}: ${c} ofert`;
        bar.addEventListener('click', () => {
            if (!dateSliderState.enabled) return;
            slider.value = i;
            dateSliderState.selectedIndex = i;
            updateDateSliderReadout();
            filterMarkers();
        });
        histogram.appendChild(bar);
    });

    // 6. Listenery (tylko raz)
    enableCb.addEventListener('change', () => {
        dateSliderState.enabled = enableCb.checked;
        if (enableCb.checked) {
            control.classList.add('enabled');
            slider.disabled = false;
            histogram.classList.remove('disabled');
            // Użyj aktualnej pozycji suwaka
            dateSliderState.selectedIndex = parseInt(slider.value);
        } else {
            control.classList.remove('enabled');
            slider.disabled = true;
            histogram.classList.add('disabled');
        }
        updateDateSliderReadout();
        filterMarkers();
    });

    slider.addEventListener('input', () => {
        dateSliderState.selectedIndex = parseInt(slider.value);
        updateDateSliderReadout();
        filterMarkers();
    });

    // 7. Stan początkowy - wyłączony
    control.classList.remove('enabled');
    histogram.classList.add('disabled');
    updateDateSliderReadout();
}

// Aktualizuje wyświetlaną datę i licznik po zmianie suwaka / checkboxa
function updateDateSliderReadout() {
    const dateEl = document.getElementById('date-slider-current');
    const countEl = document.getElementById('date-slider-count');
    const histogram = document.getElementById('date-slider-histogram');
    if (!dateEl || !countEl) return;

    const idx = dateSliderState.selectedIndex;
    const days = dateSliderState.days;

    // Podświetl aktywny słupek
    if (histogram) {
        Array.from(histogram.children).forEach((bar, i) => {
            bar.classList.toggle('active', dateSliderState.enabled && i === idx);
        });
    }

    if (!dateSliderState.enabled || idx < 0 || idx >= days.length) {
        dateEl.textContent = '—';
        dateEl.classList.remove('active');
        countEl.textContent = '— ofert';
        return;
    }

    const day = days[idx];
    const count = dateSliderState.countsPerDay[dayKey(day)] || 0;
    dateEl.textContent = formatDayPL(day);
    dateEl.classList.add('active');
    countEl.textContent = `${count} ${pluralOffers(count)}`;
}

// Polska deklinacja dla "oferta"
function pluralOffers(n) {
    if (n === 1) return 'oferta';
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'oferty';
    return 'ofert';
}

// Czy oferta/marker pasuje do wybranego dnia w suwaku dni
// Używane wspólnie przez filterMarkers, calculateFilteredStats, updateBadgeCounts
function passesDaySliderFilter(firstSeenDate) {
    if (!dateSliderState.enabled) return true;
    if (!firstSeenDate) return false;
    const idx = dateSliderState.selectedIndex;
    const days = dateSliderState.days;
    if (idx < 0 || idx >= days.length) return true;
    const selected = days[idx];
    return firstSeenDate.getFullYear() === selected.getFullYear() &&
           firstSeenDate.getMonth() === selected.getMonth() &&
           firstSeenDate.getDate() === selected.getDate();
}

// Setup event listeners
function setupEventListeners() {
    // Warstwy
    document.getElementById('layer-active').addEventListener('change', filterMarkers);
    document.getElementById('layer-inactive').addEventListener('change', filterMarkers);
    document.getElementById('layer-damaged').addEventListener('change', toggleDamagedLayer);
    document.getElementById('layer-approx')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            markerLayers.approx.addTo(map);
        } else {
            map.removeLayer(markerLayers.approx);
        }
        filterMarkers();
    });
    document.getElementById('layer-approx-inactive')?.addEventListener('change', (e) => {
        if (e.target.checked) {
            markerLayers.approxInactive.addTo(map);
        } else {
            map.removeLayer(markerLayers.approxInactive);
        }
        filterMarkers();
    });
    
    // NOWY: Filtr czasowy
    document.getElementById('time-filter').addEventListener('change', filterMarkers);
    
    // Zakresy cenowe - wspólne dla obu warstw
    document.querySelectorAll('.price-range-filter').forEach(cb => {
        cb.addEventListener('change', filterMarkers);
    });
    
    // Filtry oznaczeń pinezek (legenda)
    ['badge-filter-price-down', 'badge-filter-price-up', 'badge-filter-new', 'badge-filter-damaged']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('change', filterMarkers);
        });
    
    // Precyzyjne filtry cen - wspólne dla obu warstw
    document.getElementById('price-min').addEventListener('input', filterMarkers);
    document.getElementById('price-max').addEventListener('input', filterMarkers);
    
    // Wyszukiwanie
    document.getElementById('search-input').addEventListener('input', searchAndZoom);
    
    // Zoom mapy - aktualizuj rozsunięcie markerów
    map.on('zoomend', function() {
        // TODO: Rekonstruuj markery z nowym offsetem
        // Na razie zostawiam jak jest (offset statyczny)
    });
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
    initMap();
    loadData();
});

// NOWA funkcja: Oznaczanie ogłoszenia jako uszkodzone
function markAsDamaged(offerId) {
    if (!confirm('⚠️ Oznaczyć to ogłoszenie jako uszkodzone?\n\nOgłoszenie trafi do warstwy "Uszkodzone" (domyślnie ukrytej).\nMożesz je przywrócić w każdej chwili.')) {
        return;
    }
    
    if (addToDamaged(offerId)) {
        console.log('⚠️ Oznaczono jako uszkodzone:', offerId);
        alert('✅ Ogłoszenie oznaczone jako uszkodzone!\n\nOdśwież stronę (F5) aby zobaczyć zmiany.');
        
        // Opcjonalnie: odśwież automatycznie
        setTimeout(() => {
            location.reload();
        }, 1000);
    }
}

// NOWA funkcja: Przywracanie ogłoszenia z warstwy uszkodzone
function restoreListing(offerId) {
    if (!confirm('✅ Przywrócić to ogłoszenie?\n\nOgłoszenie wróci do normalnej warstwy.')) {
        return;
    }
    
    removeFromDamaged(offerId);
    console.log('✅ Przywrócono ogłoszenie:', offerId);
    alert('✅ Ogłoszenie przywrócone!\n\nOdśwież stronę (F5) aby zobaczyć zmiany.');
    
    // Opcjonalnie: odśwież automatycznie
    setTimeout(() => {
        location.reload();
    }, 1000);
}

// NOWA funkcja: Przełączanie widoku opisu (pokaż całość / zwiń)
function toggleDescription(uniqueId) {
    const shortDiv = document.getElementById(`${uniqueId}-short`);
    const fullDiv = document.getElementById(`${uniqueId}-full`);
    
    if (shortDiv && fullDiv) {
        if (shortDiv.style.display === 'none') {
            // Pokazuj krótką wersję
            shortDiv.style.display = 'block';
            fullDiv.style.display = 'none';
        } else {
            // Pokazuj pełną wersję
            shortDiv.style.display = 'none';
            fullDiv.style.display = 'block';
        }
    }
}

// NOWA funkcja: Włączanie/wyłączanie warstwy "Uszkodzone"
function toggleDamagedLayer() {
    const isChecked = document.getElementById('layer-damaged').checked;
    
    if (isChecked) {
        // Dodaj warstwę do mapy
        markerLayers.damaged.addTo(map);
        console.log('✅ Warstwa "Uszkodzone" włączona');
    } else {
        // Usuń warstwę z mapy
        map.removeLayer(markerLayers.damaged);
        console.log('⚠️ Warstwa "Uszkodzone" wyłączona');
    }
}

// ========== WARSTWY UCZELNI ==========

// Tworzenie warstw uczelni
function createUniversityLayers() {
    Object.entries(universities).forEach(([key, uni]) => {
        const layerGroup = L.layerGroup();
        
        uni.locations.forEach(loc => {
            // Okrąg
            const circle = L.circle([loc.lat, loc.lng], {
                radius: loc.radius,
                color: uni.color,
                weight: 2,
                fillColor: uni.color,
                fillOpacity: 0.4
            });
            
            circle.bindPopup(`
                <div style="text-align: center; min-width: 150px;">
                    <strong style="color: ${uni.color}; font-size: 14px;">${uni.name}</strong><br>
                    <span style="font-size: 12px;">${loc.name}</span><br>
                    <span style="font-size: 10px; color: #888;">${uni.fullName}</span><br>
                    <span style="font-size: 10px; color: #666;">Promień: ${loc.radius}m</span>
                </div>
            `);
            
            layerGroup.addLayer(circle);
            
            // Etykieta
            const label = L.marker([loc.lat, loc.lng], {
                icon: L.divIcon({
                    className: 'uni-label',
                    html: `<span style="color: ${uni.color};">${loc.name}</span>`,
                    iconSize: [90, 14],
                    iconAnchor: [45, 7]
                })
            });
            layerGroup.addLayer(label);
        });
        
        // Domyślnie warstwy uczelni są WYŁĄCZONE
        universityLayers[key] = layerGroup;
    });
    
    console.log('🎓 Warstwy uczelni utworzone');
}

// Przełączanie warstwy uczelni
function toggleUniversityLayer(key) {
    const checkbox = document.getElementById(`layer-uni-${key}`);
    if (!checkbox) return;
    
    if (checkbox.checked) {
        universityLayers[key].addTo(map);
    } else {
        map.removeLayer(universityLayers[key]);
    }
}

// Zwijanie/rozwijanie sekcji uczelni
function toggleUniSection() {
    const list = document.getElementById('uni-list');
    const icon = document.getElementById('uni-toggle-icon');
    if (list.style.display === 'none') {
        list.style.display = 'block';
        icon.textContent = '▼';
    } else {
        list.style.display = 'none';
        icon.textContent = '▶';
    }
}

// B1: Aktualizacja liczników tagów
function updateTagCounts() {
    const counts = { pokoj: 0, kawalerka: 0, mieszkanie: 0 };
    
    allMarkers.forEach(item => {
        if (item.isActive) {
            const tag = item.primaryTag || 'pokoj';
            if (counts[tag] !== undefined) {
                counts[tag]++;
            }
        }
    });
    
    // Aktualizuj wyświetlane liczniki
    const pokojEl = document.getElementById('tag-count-pokoj');
    const kawalerkaEl = document.getElementById('tag-count-kawalerka');
    const mieszkanieEl = document.getElementById('tag-count-mieszkanie');
    
    if (pokojEl) pokojEl.textContent = `(${counts.pokoj})`;
    if (kawalerkaEl) kawalerkaEl.textContent = `(${counts.kawalerka})`;
    if (mieszkanieEl) mieszkanieEl.textContent = `(${counts.mieszkanie})`;
}

// B1: Filtrowanie po tagach - alias do filterMarkers
function filterByTags() {
    filterMarkers();
}

// Aktualizacja liczników oznaczeń pinezek (legenda)
// Respektuje aktywny zakres dat (filtr "Pokaż oferty z ostatnich")
function updateBadgeCounts() {
    const timeFilter = document.getElementById('time-filter')?.value || 'all';
    let cutoffDate = null;
    if (timeFilter !== 'all') {
        const daysAgo = parseInt(timeFilter);
        cutoffDate = new Date(Date.now() - (daysAgo * 24 * 60 * 60 * 1000));
    }

    const counts = { priceDown: 0, priceUp: 0, isNew: 0, damaged: 0 };

    allMarkers.forEach(item => {
        // Dla zmian ceny używamy price_changed_at
        const priceChangeInRange = !cutoffDate ||
            (item.priceChangedAtDate && item.priceChangedAtDate >= cutoffDate);
        // Dla "nowa oferta" używamy first_seen
        const firstSeenInRange = !cutoffDate ||
            (item.firstSeenDate && item.firstSeenDate >= cutoffDate);

        // Filtr suwaka dni - dotyczy first_seen markera
        const daySliderOk = passesDaySliderFilter(item.firstSeenDate);
        if (!daySliderOk) return;

        if (item.priceDown && priceChangeInRange) counts.priceDown++;
        if (item.priceUp && priceChangeInRange) counts.priceUp++;
        if (item.isNew && firstSeenInRange) counts.isNew++;
        // Uszkodzone - bez filtra daty
        if (item.isDamaged) counts.damaged++;
    });

    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = `(${value})`;
    };

    setText('badge-count-price-down', counts.priceDown);
    setText('badge-count-price-up', counts.priceUp);
    setText('badge-count-new', counts.isNew);
    setText('badge-count-damaged', counts.damaged);
}

// ============================================================
// WARSTWA: Oferty bez precyzyjnej lokacji GPS
// ============================================================

let unlocalisedData = [];

function initUnlocalisedLayer() {
    unlocalisedData = mapData.unlocalised_offers || [];
    const activeCount = unlocalisedData.filter(o => o.active).length;

    if (unlocalisedData.length === 0) return;

    // Pokaż pasek toggle
    const toggleBar = document.getElementById('unlocalised-toggle-bar');
    const toggleCount = document.getElementById('unlocalised-toggle-count');
    if (toggleBar) {
        toggleBar.style.display = 'block';
        if (toggleCount) toggleCount.textContent = activeCount;
    }

    // Zaktualizuj badge w statystykach (jeśli jest)
    const badge = document.getElementById('unlocalised-count-badge');
    if (badge) badge.textContent = activeCount;

    renderUnlocalised();
}

function toggleUnlocalisedSection() {
    const section = document.getElementById('unlocalised-section');
    const toggleBar = document.getElementById('unlocalised-toggle-bar');
    if (!section) return;

    const isHidden = section.style.display === 'none';
    section.style.display = isHidden ? 'block' : 'none';
    if (toggleBar) toggleBar.style.display = isHidden ? 'none' : 'block';

    if (isHidden) {
        renderUnlocalised();
        // Scroll do sekcji
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function renderUnlocalised() {
    const grid = document.getElementById('unlocalised-grid');
    const empty = document.getElementById('unlocalised-empty');
    const badge = document.getElementById('unlocalised-count-badge');
    if (!grid) return;

    // Odczytaj filtry
    const filterTag = document.getElementById('unlocalised-filter-tag')?.value || 'all';
    const filterStatus = document.getElementById('unlocalised-filter-status')?.value || 'active';
    const priceMax = parseInt(document.getElementById('unlocalised-price-max')?.value || '0');
    const searchQuery = (document.getElementById('unlocalised-search')?.value || '').toLowerCase().trim();

    let filtered = unlocalisedData.filter(offer => {
        // Status
        if (filterStatus === 'active' && !offer.active) return false;
        // Typ
        if (filterTag !== 'all' && offer.tags?.primary !== filterTag) return false;
        // Cena
        if (priceMax > 0 && offer.price > priceMax) return false;
        // Wyszukiwanie
        if (searchQuery) {
            const haystack = `${offer.address} ${offer.description}`.toLowerCase();
            if (!haystack.includes(searchQuery)) return false;
        }
        return true;
    });

    // Sortuj: najpierw aktywne, potem po cenie
    filtered.sort((a, b) => {
        if (a.active !== b.active) return a.active ? -1 : 1;
        return a.price - b.price;
    });

    if (badge) badge.textContent = filtered.filter(o => o.active).length;

    if (filtered.length === 0) {
        grid.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';

    const tagIcons = { mieszkanie: '🏢', kawalerka: '🏠', pokoj: '🛏️' };

    grid.innerHTML = filtered.map(offer => {
        const tagIcon = tagIcons[offer.tags?.primary] || '📋';
        const tagLabel = offer.tags?.primary || 'oferta';
        const isNew = offer.is_new ? '<span style="background:#ef4444;color:white;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:700;margin-left:4px;">NOWA</span>' : '';
        const inactive = !offer.active ? '<span style="background:#94a3b8;color:white;border-radius:4px;padding:1px 6px;font-size:10px;">nieaktywna</span>' : '';
        const desc = offer.description ? offer.description.substring(0, 120).trim() + '…' : '';
        const mediaInfo = offer.media_info && offer.media_info !== 'brak informacji'
            ? `<span style="font-size:11px;color:#64748b;">💡 ${offer.media_info}</span>` : '';
        const cardBg = offer.active ? 'white' : '#f8fafc';
        const borderColor = offer.active ? '#f59e0b' : '#e2e8f0';

        return `
        <div style="background:${cardBg};border:1px solid ${borderColor};border-radius:8px;padding:12px;font-size:13px;opacity:${offer.active ? 1 : 0.75};">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
                <div style="font-weight:600;color:#1e293b;flex:1;margin-right:8px;">
                    ${tagIcon} ${offer.address || 'Nieznany adres'}
                    ${isNew}${inactive}
                </div>
                <div style="font-weight:700;color:#7c3aed;white-space:nowrap;font-size:15px;">
                    ${offer.price ? offer.price.toLocaleString('pl-PL') + ' zł' : '—'}
                </div>
            </div>
            ${mediaInfo ? `<div style="margin-bottom:4px;">${mediaInfo}</div>` : ''}
            <div style="color:#475569;font-size:12px;margin-bottom:6px;line-height:1.4;">${desc}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px;">
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <span style="background:#f1f5f9;color:#64748b;border-radius:4px;padding:2px 6px;font-size:11px;">${tagIcon} ${tagLabel}</span>
                    <span style="color:#94a3b8;font-size:11px;">📅 ${offer.first_seen || '—'}</span>
                </div>
                <a href="${offer.url}" target="_blank" rel="noopener"
                   style="background:#7c3aed;color:white;border-radius:6px;padding:4px 10px;text-decoration:none;font-size:12px;font-weight:600;">
                    Otwórz →
                </a>
            </div>
        </div>`;
    }).join('');
}
