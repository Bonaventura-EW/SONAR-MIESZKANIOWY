// SONAR MIESZKANIOWY - JavaScript (Zoptymalizowany)
// Kluczowe zmiany wydajnościowe:
// 1. Lazy popup — HTML generowany przy pierwszym kliknięciu, nie przy tworzeniu markera
// 2. Debounce filtrów — filterMarkers() wywołuje się max raz na 120ms
// 3. Uproszczone SVG ikon — mniej węzłów DOM na marker
// 4. Tile layer z updateWhenIdle + keepBuffer dla płynniejszego przewijania
// 5. Cache wartości filtrów w filterMarkers() — jeden odczyt DOM zamiast wielu

// ─────────────────────── HELPERS ────────────────────────────────────────────

function parsePolishDate(str) {
    if (!str) return null;
    try {
        const parts = str.split(' ');
        const d = parts[0].split('.');
        const t = (parts[1] || '00:00').split(':');
        return new Date(parseInt(d[2]), parseInt(d[1]) - 1, parseInt(d[0]), parseInt(t[0]), parseInt(t[1]));
    } catch (e) { return null; }
}

function dayKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}

function formatDayPL(date) {
    return `${String(date.getDate()).padStart(2,'0')}.${String(date.getMonth()+1).padStart(2,'0')}.${date.getFullYear()}`;
}

function pluralOffers(n) {
    if (n === 1) return 'oferta';
    const m10 = n % 10, m100 = n % 100;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'oferty';
    return 'ofert';
}

function debounce(fn, wait) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), wait);
    };
}

// ─────────────────────── STAN GLOBALNY ───────────────────────────────────────

let map;
let mapData;
let allMarkers = [];
let markerLayers = {
    active:         L.layerGroup(),
    inactive:       L.layerGroup(),
    approx:         L.layerGroup(),
    approxInactive: L.layerGroup()
};

let dateSliderState = {
    enabled: false, days: [], countsPerDay: {}, selectedIndex: -1
};

// ─────────────────────── UCZELNIE ────────────────────────────────────────────

let universityLayers = {};
const universities = {
    kul:         { name:'KUL',         fullName:'Katolicki Uniwersytet Lubelski',                 color:'#1e88e5', locations:[{name:'Kampus Główny',lat:51.2475,lng:22.5450,radius:120},{name:'Konstantynów (Med.)',lat:51.2382,lng:22.5014,radius:140},{name:'Biblioteka',lat:51.2438,lng:22.5538,radius:70},{name:'Collegium Iuridicum',lat:51.2494,lng:22.5543,radius:60},{name:'Akademik Idzi',lat:51.2505,lng:22.5605,radius:50}] },
    umcs:        { name:'UMCS',        fullName:'Uniwersytet Marii Curie-Skłodowskiej',           color:'#43a047', locations:[{name:'Rektorat',lat:51.2455,lng:22.5409,radius:100},{name:'Biblioteka Główna',lat:51.2464,lng:22.5411,radius:70},{name:'Wydz. Ekonomiczny',lat:51.2456,lng:22.5408,radius:80},{name:'Wydz. Prawa',lat:51.2454,lng:22.5408,radius:80},{name:'Wydz. Mat-Fiz-Inf',lat:51.2458,lng:22.5422,radius:90},{name:'Wydz. Chemii',lat:51.2447,lng:22.5424,radius:80},{name:'Wydz. Filozofii',lat:51.2452,lng:22.5412,radius:70},{name:'Wydz. Pedagogiki',lat:51.2466,lng:22.5259,radius:80},{name:'Wydz. Artystyczny',lat:51.2480,lng:22.5222,radius:70},{name:'Wydz. Politologii',lat:51.2470,lng:22.5243,radius:80},{name:'Wydz. Nauk o Ziemi',lat:51.2478,lng:22.5235,radius:70},{name:'Miasteczko Akad.',lat:51.2466,lng:22.5336,radius:150}] },
    politechnika:{ name:'Politechnika',fullName:'Politechnika Lubelska',                          color:'#ff5722', locations:[{name:'Wydz. Budownictwa',lat:51.2354,lng:22.5480,radius:80},{name:'Wydz. Zarządzania',lat:51.2347,lng:22.5484,radius:70},{name:'Wydz. Mechaniczny',lat:51.2369,lng:22.5501,radius:90},{name:'Wydz. Elektrotechniki',lat:51.2368,lng:22.5488,radius:80},{name:'Wydz. Inż. Środowiska',lat:51.2346,lng:22.5478,radius:70},{name:'Wydz. Matematyki',lat:51.2350,lng:22.5489,radius:60},{name:'Centrum Innowacji',lat:51.2362,lng:22.5512,radius:70}] },
    wspa:        { name:'WSPA',        fullName:'Wyższa Szkoła Przedsiębiorczości i Administracji',color:'#9c27b0', locations:[{name:'Kampus WSPA',lat:51.2701,lng:22.5695,radius:100}] },
    up:          { name:'UP',          fullName:'Uniwersytet Przyrodniczy',                        color:'#009688', locations:[{name:'Rektorat',lat:51.2437,lng:22.5401,radius:90},{name:'Biblioteka Główna',lat:51.2435,lng:22.5414,radius:60},{name:'Wydz. Weterynarii',lat:51.2444,lng:22.5435,radius:80},{name:'Klinika Weteryn.',lat:51.2414,lng:22.5424,radius:90},{name:'Centrum Innowacji',lat:51.2408,lng:22.5450,radius:70},{name:'Wydz. Inż. Produkcji',lat:51.2438,lng:22.5404,radius:70},{name:'Wydz. Żywności',lat:51.2493,lng:22.5110,radius:90},{name:'Felin (Doświadcz.)',lat:51.2271,lng:22.6350,radius:150}] },
    umed:        { name:'UM',          fullName:'Uniwersytet Medyczny',                            color:'#e91e63', locations:[{name:'Rektorat',lat:51.2482,lng:22.5488,radius:80},{name:'Collegium Medicum',lat:51.2496,lng:22.5594,radius:70},{name:'Collegium Maximum',lat:51.2487,lng:22.5620,radius:60},{name:'Szpital SPSK1',lat:51.2507,lng:22.5626,radius:100},{name:'Collegium Universum',lat:51.2593,lng:22.5681,radius:90},{name:'Centrum Symulacji',lat:51.2611,lng:22.5642,radius:70},{name:'Pharmaceuticum',lat:51.2618,lng:22.5636,radius:60},{name:'Szpital Dziecięcy',lat:51.2605,lng:22.5607,radius:100}] },
    awp:         { name:'AWP',         fullName:'Akademia Wincentego Pola',                        color:'#ff9800', locations:[{name:'Kampus AWP',lat:51.2700,lng:22.5572,radius:100}] },
    ansim:       { name:'ANSiM',       fullName:'Akademia Nauk Społecznych i Medycznych',          color:'#795548', locations:[{name:'Kampus ANSiM',lat:51.2403,lng:22.5700,radius:90}] }
};

// ─────────────────────── INICJALIZACJA MAPY ──────────────────────────────────

function initMap() {
    map = L.map('map').setView([51.2465, 22.5684], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19,
        updateWhenIdle: true,
        keepBuffer: 2
    }).addTo(map);
    markerLayers.active.addTo(map);
    markerLayers.approx.addTo(map);
    markerLayers.inactive.addTo(map);
    markerLayers.approxInactive.addTo(map);
    createUniversityLayers();
}

// ─────────────────────── WCZYTANIE DANYCH ────────────────────────────────────

async function loadData() {
    try {
        const baseUrl = window.location.pathname.includes('/SONAR-MIESZKANIOWY/') ? '/SONAR-MIESZKANIOWY/data.json' : '/data.json';
        const ts = Date.now();
        let response = await fetch(`${baseUrl}?v=${ts}`);
        if (!response.ok) response = await fetch(baseUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        mapData = await response.json();
        console.log(`✅ Załadowano ${mapData.markers?.length || 0} markerów`);
        updateScanInfo();
        createPriceRangeFilters();
        createMarkers();
        updateStats();
        initDateSlider();
        setupEventListeners();
        filterMarkers();
        initUnlocalisedLayer();
        console.log('🎉 Mapa gotowa!');
        // Deep-link: ?offer=<id> z innych stron (np. top5.html)
        focusOfferFromUrl();
    } catch (error) {
        console.error('❌ Błąd wczytywania danych:', error);
        alert('Nie udało się wczytać danych mapy.\n\nBłąd: ' + error.message);
    }
}

// ─────────────────────── IKONY MARKERÓW ──────────────────────────────────────

function buildPinIcon(color, strokeColor, strokeWidth, badges, isActive = true) {
    const { isNew, priceDown, priceUp } = badges;
    let badge = '';
    if (priceDown)      badge = '<div class="marker-badge marker-badge--down">📉</div>';
    else if (priceUp)   badge = '<div class="marker-badge marker-badge--up">📈</div>';
    else if (isNew)     badge = '<div class="marker-badge marker-badge--new">N</div>';
    const inner = isActive
        ? `<circle cx="20" cy="18" r="8" fill="white" fill-opacity="0.9"/>`
        : `<circle cx="20" cy="18" r="8" fill="white" fill-opacity="0.9"/><line x1="14" y1="12" x2="26" y2="24" stroke="#555" stroke-width="2.5" stroke-linecap="round"/><line x1="26" y1="12" x2="14" y2="24" stroke="#555" stroke-width="2.5" stroke-linecap="round"/>`;
    return L.divIcon({
        className: 'pin-marker',
        html: `<div class="pin-wrap">${badge}<svg class="pin-svg" viewBox="0 0 40 50" xmlns="http://www.w3.org/2000/svg"><path d="M20 0C9 0 0 9 0 20c0 15 20 30 20 30s20-15 20-30C40 9 31 0 20 0z" fill="${color}" stroke="${strokeColor}" stroke-width="${strokeWidth}"/>${inner}</svg></div>`,
        iconSize: [40, 50], iconAnchor: [20, 50], popupAnchor: [0, -50]
    });
}

function buildSquareIcon(color, badges, isActive = true) {
    const { isNew, priceDown, priceUp } = (badges && typeof badges === 'object') ? badges : { isNew: badges, priceDown: false, priceUp: false };
    let badge = '';
    if (priceDown)    badge = '<div class="marker-badge marker-badge--down">📉</div>';
    else if (priceUp) badge = '<div class="marker-badge marker-badge--up">📈</div>';
    else if (isNew)   badge = '<div class="marker-badge marker-badge--new">N</div>';
    const inner = isActive
        ? `<circle cx="18" cy="18" r="7" fill="white" fill-opacity="0.85"/><text x="18" y="22" text-anchor="middle" font-size="10" font-weight="bold" fill="${color}" font-family="Arial,sans-serif">~</text>`
        : `<circle cx="18" cy="18" r="7" fill="white" fill-opacity="0.85"/><line x1="12" y1="12" x2="24" y2="24" stroke="#555" stroke-width="2.5" stroke-linecap="round"/><line x1="24" y1="12" x2="12" y2="24" stroke="#555" stroke-width="2.5" stroke-linecap="round"/>`;
    return L.divIcon({
        className: 'square-marker',
        html: `<div class="square-wrap">${badge}<svg class="square-svg" viewBox="0 0 36 36" xmlns="http://www.w3.org/2000/svg"><rect x="2" y="2" width="32" height="32" rx="7" fill="${color}" stroke="white" stroke-width="2" stroke-dasharray="5 3"/>${inner}</svg></div>`,
        iconSize: [36, 36], iconAnchor: [18, 18], popupAnchor: [0, -20]
    });
}

// ─────────────────────── TWORZENIE MARKERÓW ──────────────────────────────────

function createMarkers() {
    allMarkers = [];
    mapData.markers.forEach(({ coords, address, offers }) => {
        const active   = offers.filter(o =>  o.active);
        const inactive = offers.filter(o => !o.active);
        if (active.length)   createMarkerGroup(coords, address, active,   true);
        if (inactive.length) createMarkerGroup(coords, address, inactive, false);
    });
    updateTagCounts();
    updateBadgeCounts();
}

function createMarkerGroup(baseCoords, address, offers, isActive) {
    const baseOffset = 0.0001;
    const total = offers.length;
    offers.forEach((offer, index) => {
        const priceRange    = offer.price_range;
        const color         = mapData.price_ranges[priceRange]?.color || '#808080';
        const isNew         = offer.is_new === true;
        const hasPriceChg   = !!(offer.previous_price && offer.price_trend);
        const priceUp       = offer.price_trend === 'up';
        const priceDown     = offer.price_trend === 'down';
        const hasNumber     = offer.has_number !== false;

        let offsetLat = 0, offsetLon = 0;
        if (total > 1) {
            const angle  = (index / total) * 2 * Math.PI;
            const radius = baseOffset * (0.5 + index * 0.5);
            offsetLat = Math.cos(angle) * radius;
            offsetLon = Math.sin(angle) * radius * 1.5;
        }

        const coords        = [baseCoords.lat + offsetLat, baseCoords.lon + offsetLon];
        const strokeColor   = isNew ? '#ff0000' : 'white';
        const strokeWidth   = isNew ? 3 : 2;
        const markerColor   = color;

        const icon = hasNumber
            ? buildPinIcon(markerColor, strokeColor, strokeWidth, { isNew, priceDown, priceUp }, isActive)
            : buildSquareIcon(markerColor, { isNew, priceDown, priceUp }, isActive);

        // KLUCZOWA OPTYMALIZACJA: popup z funkcją — HTML tworzony przy kliknięciu
        const markerObj = L.marker(coords, { icon })
            .bindPopup(() => createPopupContent(address, [offer]), { maxWidth: 400 });

        const layer = (!hasNumber && isActive)         ? markerLayers.approx
            : (!hasNumber && !isActive)                ? markerLayers.approxInactive
            : isActive                                 ? markerLayers.active
            :                                            markerLayers.inactive;
        markerObj.addTo(layer);

        allMarkers.push({
            marker: markerObj, address,
            offers: [offer], priceRange,
            isActive, hasNumber,
            primaryTag:         offer.tags?.primary || 'pokoj',
            isNew,
            priceDown:          hasPriceChg && priceDown,
            priceUp:            hasPriceChg && priceUp,
            firstSeenDate:      parsePolishDate(offer.first_seen),
            priceChangedAtDate: parsePolishDate(offer.price_changed_at)
        });
    });
}

// ─────────────────────── POPUP HTML ──────────────────────────────────────────

function createPopupContent(address, offers) {
    let html = `<div class="offer-popup"><h3>📍 ${address}</h3>`;
    offers.forEach(offer => {
        const isActive = offer.active;
        const isApprox = offer.has_number === false;
        html += `<div class="offer-item${isActive ? '' : ' inactive'}" data-offer-id="${offer.id}">`;
        if (!isActive) html += `<div class="inactive-badge">❌ Nieaktywne</div>`;
        if (isApprox)  html += `<div class="approx-notice">⬜ <strong>Lokalizacja przybliżona</strong> — brak numeru domu w ogłoszeniu.<br>Marker umieszczony na środku ulicy.</div>`;

        if (offer.previous_price && offer.price_trend) {
            const diff = offer.price - offer.previous_price;
            const icon = offer.price_trend === 'down' ? '📉' : '📈';
            const clr  = offer.price_trend === 'down' ? '#28a745' : '#dc3545';
            const sign = diff > 0 ? '+' : '';
            html += `<div class="offer-price${isActive ? '' : ' inactive'}">💰 <strong>${offer.price} zł</strong> <span style="color:${clr};font-weight:bold">${icon} ${sign}${diff} zł</span></div>`;
            html += `<div class="previous-price"><s>Poprzednio: ${offer.previous_price} zł</s>${offer.price_changed_at ? ` (zmiana: ${offer.price_changed_at})` : ''}</div>`;
        } else {
            html += `<div class="offer-price${isActive ? '' : ' inactive'}">💰 ${offer.price} zł</div>`;
        }

        if (offer.price_history?.length > 1) {
            html += `<div class="price-history">📊 Historia: ${offer.price_history.map(p => p + ' zł').join(' → ')}</div>`;
        }

        html += `<div class="media-info">Skład: ${offer.media_info}</div>`;

        if (offer.tags?.primary) {
            const tI = { pokoj:'🛏️', kawalerka:'🏠', mieszkanie:'🏢' };
            const tL = { pokoj:'Pokój', kawalerka:'Kawalerka', mieszkanie:'Mieszkanie' };
            const tC = { pokoj:'#3b82f6', kawalerka:'#10b981', mieszkanie:'#8b5cf6' };
            const p  = offer.tags.primary;
            html += `<div class="offer-tag" style="background:${tC[p]}22;border:1px solid ${tC[p]};color:${tC[p]}">${tI[p]||''} ${tL[p]||p}${offer.tags.secondary?.length ? ` <span style="opacity:.7">+ ${offer.tags.secondary.map(t=>tL[t]||t).join(', ')}</span>` : ''}</div>`;
        }

        html += `<a href="${offer.url}" target="_blank" class="offer-link">🔗 Otwórz ogłoszenie</a>`;

        const max = 100;
        if (offer.description.length > max) {
            const uid = `desc-${offer.id}`;
            html += `<div class="offer-description">
                <div id="${uid}-short">📝 ${offer.description.substring(0,max)}... <br><a href="javascript:void(0)" onclick="toggleDescription('${uid}')" class="show-more-link">▼ Pokaż całość</a></div>
                <div id="${uid}-full" style="display:none">📝 ${offer.description}<br><a href="javascript:void(0)" onclick="toggleDescription('${uid}')" class="show-more-link">▲ Zwiń</a></div></div>`;
        } else {
            html += `<div class="offer-description">📝 ${offer.description}</div>`;
        }

        html += `<div class="offer-dates">`;
        if (isActive) {
            html += `📅 Dodano: ${offer.first_seen}<br>📅 Ostatnio widziane: ${offer.last_seen}<br>⏱️ Dni aktywności: ${offer.days_active}`;
        } else {
            html += `📅 Aktywna przez: ${offer.days_active} dni<br>📅 Nieaktywna od: ${offer.last_seen}<br>💰 Ostatnia cena: ${offer.price} zł`;
        }
        html += `</div>`;
        html += `</div>`;
    });
    html += `</div>`;
    return html;
}

// ─────────────────────── FILTROWANIE ─────────────────────────────────────────

function filterMarkers() {
    const showActive         = document.getElementById('layer-active').checked;
    const showInactive       = document.getElementById('layer-inactive').checked;
    const showApprox         = document.getElementById('layer-approx')?.checked         ?? false;
    const showApproxInactive = document.getElementById('layer-approx-inactive')?.checked ?? false;
    const showPokoj          = document.getElementById('layer-tag-pokoj')?.checked       ?? true;
    const showKawalerka      = document.getElementById('layer-tag-kawalerka')?.checked   ?? true;
    const showMieszkanie     = document.getElementById('layer-tag-mieszkanie')?.checked  ?? true;
    const showPriceDown      = document.getElementById('badge-filter-price-down')?.checked ?? true;
    const showPriceUp        = document.getElementById('badge-filter-price-up')?.checked   ?? true;
    const showNew            = document.getElementById('badge-filter-new')?.checked         ?? true;
    const showNoChange       = document.getElementById('badge-filter-no-change')?.checked   ?? true;
    const timeFilter         = document.getElementById('time-filter').value;
    const priceMin           = parseInt(document.getElementById('price-min').value)  || 0;
    const priceMax           = parseInt(document.getElementById('price-max').value)  || 999999;
    const searchTerm         = document.getElementById('search-input').value.toLowerCase();
    const selectedRanges     = Array.from(document.querySelectorAll('.price-range-filter:checked')).map(cb => cb.dataset.range);
    const cutoffDate         = timeFilter !== 'all' ? new Date(Date.now() - parseInt(timeFilter) * 86400000) : null;

    allMarkers.forEach(item => {
        let ok = true;

        if (!item.hasNumber) {
            if  (item.isActive  && !showApprox)        ok = false;
            if  (!item.isActive && !showApproxInactive) ok = false;
        } else {
            if  (item.isActive  && !showActive)   ok = false;
            if  (!item.isActive && !showInactive)  ok = false;
        }

        if (ok) {
            const t = item.primaryTag;
            if (t === 'pokoj'     && !showPokoj)     ok = false;
            if (t === 'kawalerka' && !showKawalerka) ok = false;
            if (t === 'mieszkanie'&& !showMieszkanie)ok = false;
        }

        if (ok) {
            const hasAny = item.isNew || item.priceDown || item.priceUp;
            if (hasAny) {
                if (!((item.isNew && showNew) || (item.priceDown && showPriceDown) || (item.priceUp && showPriceUp))) ok = false;
            } else {
                if (!showNoChange) ok = false;
            }
        }

        if (ok && cutoffDate) {
            if (!(item.firstSeenDate && item.firstSeenDate >= cutoffDate) && !(item.priceChangedAtDate && item.priceChangedAtDate >= cutoffDate)) ok = false;
        }

        if (ok && !passesDaySliderFilter(item.firstSeenDate)) ok = false;
        if (ok && selectedRanges.length > 0 && !selectedRanges.includes(item.priceRange)) ok = false;

        if (ok) {
            const p = item.offers[0].price;
            if (p < priceMin || p > priceMax) ok = false;
        }

        if (ok && searchTerm && !item.address.toLowerCase().includes(searchTerm)) ok = false;

        const layer = (!item.hasNumber && item.isActive)  ? markerLayers.approx
            : (!item.hasNumber && !item.isActive)         ? markerLayers.approxInactive
            : item.isActive                               ? markerLayers.active
            :                                               markerLayers.inactive;

        if (ok) layer.addLayer(item.marker);
        else    layer.removeLayer(item.marker);
    });

    updateStats();
    updateBadgeCounts();
    updatePriceRangeCounts();
}

// ─────────────────────── STATYSTYKI ──────────────────────────────────────────

function calculateFilteredStats() {
    const showActive         = document.getElementById('layer-active').checked;
    const showInactive       = document.getElementById('layer-inactive').checked;
    const showApprox         = document.getElementById('layer-approx')?.checked         ?? false;
    const showApproxInactive = document.getElementById('layer-approx-inactive')?.checked ?? false;
    const timeFilter         = document.getElementById('time-filter').value;
    const searchTerm         = document.getElementById('search-input').value.toLowerCase();
    const selectedRanges     = Array.from(document.querySelectorAll('.price-range-filter:checked')).map(cb => cb.dataset.range);
    const cutoffDate         = timeFilter !== 'all' ? new Date(Date.now() - parseInt(timeFilter) * 86400000) : null;
    const prices             = [];

    allMarkers.forEach(item => {
        // Filtr warstwy — identyczna logika jak w filterMarkers()
        if (!item.hasNumber) {
            if ( item.isActive && !showApprox)         return;
            if (!item.isActive && !showApproxInactive)  return;
        } else {
            if ( item.isActive && !showActive)   return;
            if (!item.isActive && !showInactive)  return;
        }
        // Sprawdź czy marker jest aktualnie widoczny (filterMarkers go nie ukrył)
        // Używamy layerGroup.hasLayer — działa niezależnie od tego czy
        // layerGroup jest przypięta do mapy (markerLayers.approx nie jest domyślnie)
        const group = (!item.hasNumber && item.isActive)  ? markerLayers.approx
            : (!item.hasNumber && !item.isActive)          ? markerLayers.approxInactive
            : item.isActive                                ? markerLayers.active
            :                                                markerLayers.inactive;
        if (!group.hasLayer(item.marker)) return;
        if (searchTerm && !item.address.toLowerCase().includes(searchTerm)) return;
        if (!selectedRanges.includes(item.priceRange)) return;

        item.offers.forEach(offer => {
            if (cutoffDate) {
                try {
                    const parts = offer.first_seen.split(' ');
                    const dp = parts[0].split('.');
                    const tp = parts[1].split(':');
                    const d = new Date(parseInt(dp[2]), parseInt(dp[1])-1, parseInt(dp[0]), parseInt(tp[0]), parseInt(tp[1]));
                    if (d < cutoffDate) return;
                } catch { /* uwzględnij */ }
            }
            if (!passesDaySliderFilter(parsePolishDate(offer.first_seen))) return;
            prices.push(offer.price);
        });
    });

    if (prices.length === 0) return null;
    return {
        count: prices.length,
        avg:   Math.round(prices.reduce((a, b) => a + b, 0) / prices.length),
        min:   Math.min(...prices),
        max:   Math.max(...prices)
    };
}

function updateStats() {
    const stats = calculateFilteredStats();
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    if (stats) {
        set('visible-count', stats.count);
        set('avg-price',     stats.avg + ' zł');
        set('min-price',     stats.min + ' zł');
        set('max-price',     stats.max + ' zł');
    } else {
        ['visible-count','avg-price','min-price','max-price'].forEach(id => set(id, '-'));
    }
    set('active-count',         `(${allMarkers.filter(m => m.isActive && m.hasNumber).length})`);
    set('inactive-count',       `(${allMarkers.filter(m => !m.isActive && m.hasNumber).length})`);
    set('approx-count',         `(${allMarkers.filter(m => !m.hasNumber && m.isActive).length})`);
    set('approx-inactive-count',`(${allMarkers.filter(m => !m.hasNumber && !m.isActive).length})`);
}

function updateScanInfo() {
    document.getElementById('last-scan').textContent = mapData.scan_info.last;
    document.getElementById('next-scan').textContent = mapData.scan_info.next;
}

function createPriceRangeFilters() {
    const container = document.getElementById('price-range-filters');
    Object.entries(mapData.price_ranges).forEach(([key, range]) => {
        const label = document.createElement('label');
        label.innerHTML = `<input type="checkbox" class="price-range-filter" data-range="${key}" checked><span class="price-dot" style="background:${range.color}"></span>${range.label}<span id="price-range-count-${key}" class="badge-count">(0)</span>`;
        container.appendChild(label);
    });
}

// ─────────────────────── SUWAK DNI ───────────────────────────────────────────

function initDateSlider() {
    const slider    = document.getElementById('date-slider');
    const enableCb  = document.getElementById('date-filter-enable');
    const control   = document.getElementById('date-slider-control');
    const minLabel  = document.getElementById('date-slider-min');
    const maxLabel  = document.getElementById('date-slider-max');
    const histogram = document.getElementById('date-slider-histogram');
    if (!slider || !enableCb) return;

    let earliest = null;
    allMarkers.forEach(item => { if (item.firstSeenDate && (!earliest || item.firstSeenDate < earliest)) earliest = item.firstSeenDate; });
    if (!earliest) { enableCb.disabled = true; minLabel.textContent = maxLabel.textContent = '—'; return; }

    const startDay = new Date(earliest.getFullYear(), earliest.getMonth(), earliest.getDate());
    const endDay   = (() => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); })();
    const days     = [];
    const cursor   = new Date(startDay);
    while (cursor <= endDay) { days.push(new Date(cursor)); cursor.setDate(cursor.getDate() + 1); }

    const counts = {};
    days.forEach(d => { counts[dayKey(d)] = 0; });
    allMarkers.forEach(item => {
        item.offers.forEach(offer => {
            const fs = parsePolishDate(offer.first_seen);
            if (fs) { const k = dayKey(fs); if (k in counts) counts[k]++; }
        });
    });

    dateSliderState.days = days; dateSliderState.countsPerDay = counts; dateSliderState.selectedIndex = days.length - 1;
    slider.min = 0; slider.max = days.length - 1; slider.value = days.length - 1;
    minLabel.textContent = formatDayPL(days[0]); maxLabel.textContent = formatDayPL(days[days.length - 1]);

    histogram.innerHTML = '';
    const maxCount = Math.max(1, ...Object.values(counts));
    days.forEach((d, i) => {
        const c = counts[dayKey(d)];
        const bar = document.createElement('div');
        bar.className = 'bar' + (c === 0 ? ' empty' : '');
        bar.style.height = (c === 0 ? 8 : Math.max(15, Math.round((c / maxCount) * 100))) + '%';
        bar.dataset.index = i;
        bar.title = `${formatDayPL(d)}: ${c} ofert`;
        bar.addEventListener('click', () => { if (!dateSliderState.enabled) return; slider.value = i; dateSliderState.selectedIndex = i; updateDateSliderReadout(); filterMarkers(); });
        histogram.appendChild(bar);
    });

    enableCb.addEventListener('change', () => {
        dateSliderState.enabled = enableCb.checked;
        if (enableCb.checked) { control.classList.add('enabled'); slider.disabled = false; histogram.classList.remove('disabled'); dateSliderState.selectedIndex = parseInt(slider.value); }
        else { control.classList.remove('enabled'); slider.disabled = true; histogram.classList.add('disabled'); }
        updateDateSliderReadout(); filterMarkers();
    });
    slider.addEventListener('input', () => { dateSliderState.selectedIndex = parseInt(slider.value); updateDateSliderReadout(); filterMarkers(); });
    control.classList.remove('enabled'); histogram.classList.add('disabled'); updateDateSliderReadout();
}

function updateDateSliderReadout() {
    const dateEl = document.getElementById('date-slider-current');
    const countEl = document.getElementById('date-slider-count');
    const histogram = document.getElementById('date-slider-histogram');
    if (!dateEl || !countEl) return;
    const idx = dateSliderState.selectedIndex;
    const days = dateSliderState.days;
    if (histogram) Array.from(histogram.children).forEach((bar, i) => bar.classList.toggle('active', dateSliderState.enabled && i === idx));
    if (!dateSliderState.enabled || idx < 0 || idx >= days.length) { dateEl.textContent = '—'; dateEl.classList.remove('active'); countEl.textContent = '— ofert'; return; }
    const day = days[idx]; const count = dateSliderState.countsPerDay[dayKey(day)] || 0;
    dateEl.textContent = formatDayPL(day); dateEl.classList.add('active');
    countEl.textContent = `${count} ${pluralOffers(count)}`;
}

function passesDaySliderFilter(firstSeenDate) {
    if (!dateSliderState.enabled) return true;
    if (!firstSeenDate) return false;
    const idx = dateSliderState.selectedIndex; const days = dateSliderState.days;
    if (idx < 0 || idx >= days.length) return true;
    const sel = days[idx];
    return firstSeenDate.getFullYear() === sel.getFullYear() && firstSeenDate.getMonth() === sel.getMonth() && firstSeenDate.getDate() === sel.getDate();
}

// ─────────────────────── EVENT LISTENERS ─────────────────────────────────────

function setupEventListeners() {
    const debouncedFilter = debounce(filterMarkers, 120);

    document.getElementById('layer-active').addEventListener('change', filterMarkers);
    document.getElementById('layer-inactive').addEventListener('change', e => { if (e.target.checked) markerLayers.inactive.addTo(map); else map.removeLayer(markerLayers.inactive); filterMarkers(); });
    document.getElementById('layer-approx')?.addEventListener('change', e => { if (e.target.checked) markerLayers.approx.addTo(map); else map.removeLayer(markerLayers.approx); filterMarkers(); });
    document.getElementById('layer-approx-inactive')?.addEventListener('change', e => { if (e.target.checked) markerLayers.approxInactive.addTo(map); else map.removeLayer(markerLayers.approxInactive); filterMarkers(); });
    document.getElementById('time-filter').addEventListener('change', filterMarkers);
    document.querySelectorAll('.price-range-filter').forEach(cb => cb.addEventListener('change', filterMarkers));
    ['badge-filter-price-down','badge-filter-price-up','badge-filter-new','badge-filter-no-change'].forEach(id => { const el = document.getElementById(id); if (el) el.addEventListener('change', filterMarkers); });

    // Pola tekstowe — debounce 120ms
    document.getElementById('price-min').addEventListener('input', debouncedFilter);
    document.getElementById('price-max').addEventListener('input', debouncedFilter);
    document.getElementById('search-input').addEventListener('input', () => { debouncedFilter(); clearTimeout(zoomTimer); zoomTimer = setTimeout(searchAndZoom, 300); });
}

let zoomTimer = null;
function searchAndZoom() {
    const term = document.getElementById('search-input').value.toLowerCase();
    if (!term) return;
    const match = allMarkers.find(item => item.address.toLowerCase().includes(term) && (item.isActive ? document.getElementById('layer-active').checked : document.getElementById('layer-inactive').checked));
    if (match) { map.setView(match.marker.getLatLng(), 17); match.marker.openPopup(); }
}

// ─────────────────────── UCZELNIE FUNKCJE ────────────────────────────────────

function createUniversityLayers() {
    Object.entries(universities).forEach(([key, uni]) => {
        const group = L.layerGroup();
        uni.locations.forEach(loc => {
            L.circle([loc.lat, loc.lng], { radius: loc.radius, color: uni.color, weight: 2, fillColor: uni.color, fillOpacity: 0.4 })
                .bindPopup(`<div style="text-align:center;min-width:150px"><strong style="color:${uni.color};font-size:14px">${uni.name}</strong><br><span style="font-size:12px">${loc.name}</span><br><span style="font-size:10px;color:#888">${uni.fullName}</span><br><span style="font-size:10px;color:#666">Promień: ${loc.radius}m</span></div>`)
                .addTo(group);
            L.marker([loc.lat, loc.lng], { icon: L.divIcon({ className:'uni-label', html:`<span style="color:${uni.color}">${loc.name}</span>`, iconSize:[90,14], iconAnchor:[45,7] }) }).addTo(group);
        });
        universityLayers[key] = group;
    });
    console.log('🎓 Warstwy uczelni utworzone');
}

function toggleUniversityLayer(key) {
    const cb = document.getElementById(`layer-uni-${key}`);
    if (!cb) return;
    if (cb.checked) universityLayers[key].addTo(map);
    else map.removeLayer(universityLayers[key]);
}

function toggleUniSection() {
    const list = document.getElementById('uni-list');
    const icon = document.getElementById('uni-toggle-icon');
    const hidden = list.style.display === 'none';
    list.style.display = hidden ? 'block' : 'none';
    icon.textContent = hidden ? '▼' : '▶';
}

// ─────────────────────── TAGI ─────────────────────────────────────────────────

function updateTagCounts() {
    const c = { pokoj:0, kawalerka:0, mieszkanie:0 };
    allMarkers.forEach(item => { if (item.isActive && c[item.primaryTag] !== undefined) c[item.primaryTag]++; });
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = `(${v})`; };
    set('tag-count-pokoj', c.pokoj); set('tag-count-kawalerka', c.kawalerka); set('tag-count-mieszkanie', c.mieszkanie);
}

function filterByTags() { filterMarkers(); }

// ─────────────────────── BADGE LICZNIKI ──────────────────────────────────────

function updateBadgeCounts() {
    const timeFilter = document.getElementById('time-filter')?.value || 'all';
    const cutoffDate = timeFilter !== 'all' ? new Date(Date.now() - parseInt(timeFilter) * 86400000) : null;
    const c = { priceDown:0, priceUp:0, isNew:0, noChange:0 };
    allMarkers.forEach(item => {
        if (!passesDaySliderFilter(item.firstSeenDate)) return;
        const priceIn = !cutoffDate || (item.priceChangedAtDate && item.priceChangedAtDate >= cutoffDate);
        const firstIn = !cutoffDate || (item.firstSeenDate     && item.firstSeenDate     >= cutoffDate);
        if (item.priceDown && priceIn) c.priceDown++;
        if (item.priceUp   && priceIn) c.priceUp++;
        if (item.isNew     && firstIn) c.isNew++;
        if (!item.isNew && !item.priceDown && !item.priceUp) c.noChange++;
    });
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = `(${v})`; };
    set('badge-count-price-down', c.priceDown); set('badge-count-price-up', c.priceUp);
    set('badge-count-new', c.isNew); set('badge-count-no-change', c.noChange);
}

function updatePriceRangeCounts() {
    if (!mapData || !mapData.price_ranges) return;

    const showActive         = document.getElementById('layer-active')?.checked         ?? true;
    const showInactive       = document.getElementById('layer-inactive')?.checked       ?? true;
    const showApprox         = document.getElementById('layer-approx')?.checked         ?? false;
    const showApproxInactive = document.getElementById('layer-approx-inactive')?.checked ?? false;
    const showPokoj          = document.getElementById('layer-tag-pokoj')?.checked       ?? true;
    const showKawalerka      = document.getElementById('layer-tag-kawalerka')?.checked   ?? true;
    const showMieszkanie     = document.getElementById('layer-tag-mieszkanie')?.checked  ?? true;
    const showPriceDown      = document.getElementById('badge-filter-price-down')?.checked ?? true;
    const showPriceUp        = document.getElementById('badge-filter-price-up')?.checked   ?? true;
    const showNew            = document.getElementById('badge-filter-new')?.checked         ?? true;
    const showNoChange       = document.getElementById('badge-filter-no-change')?.checked   ?? true;
    const priceMin           = parseInt(document.getElementById('price-min')?.value)  || 0;
    const priceMax           = parseInt(document.getElementById('price-max')?.value)  || 999999;
    const searchTerm         = (document.getElementById('search-input')?.value || '').toLowerCase();
    const timeFilter         = document.getElementById('time-filter')?.value || 'all';
    const cutoffDate         = timeFilter !== 'all'
        ? new Date(Date.now() - parseInt(timeFilter) * 86400000) : null;

    const counts = {};
    Object.keys(mapData.price_ranges).forEach(k => { counts[k] = 0; });

    allMarkers.forEach(item => {
        // Identyczna logika jak filterMarkers — warstwa aktywne/przybliżone
        if (!item.hasNumber) {
            if ( item.isActive && !showApprox)        return;
            if (!item.isActive && !showApproxInactive) return;
        } else {
            if ( item.isActive && !showActive)   return;
            if (!item.isActive && !showInactive)  return;
        }

        const t = item.primaryTag || 'pokoj';
        if (t === 'pokoj'     && !showPokoj)      return;
        if (t === 'kawalerka' && !showKawalerka)  return;
        if (t === 'mieszkanie'&& !showMieszkanie) return;

        const hasAny = item.isNew || item.priceDown || item.priceUp;
        if (hasAny) {
            if (!((item.isNew && showNew) || (item.priceDown && showPriceDown) || (item.priceUp && showPriceUp))) return;
        } else {
            if (!showNoChange) return;
        }

        if (cutoffDate) {
            const firstOk = item.firstSeenDate && item.firstSeenDate >= cutoffDate;
            const priceOk = item.priceChangedAtDate && item.priceChangedAtDate >= cutoffDate;
            if (!firstOk && !priceOk) return;
        }

        if (!passesDaySliderFilter(item.firstSeenDate)) return;

        const price = item.offers[0]?.price ?? 0;
        if (price < priceMin || price > priceMax) return;

        if (searchTerm && !item.address.toLowerCase().includes(searchTerm)) return;

        if (item.priceRange && counts.hasOwnProperty(item.priceRange)) {
            counts[item.priceRange]++;
        }
    });

    Object.entries(counts).forEach(([key, val]) => {
        const el = document.getElementById(`price-range-count-${key}`);
        if (el) el.textContent = `(${val})`;
    });
}

// ─────────────────────── OPIS — TOGGLE ────────────────────────────────────────

function toggleDescription(uid) {
    const s = document.getElementById(`${uid}-short`);
    const f = document.getElementById(`${uid}-full`);
    if (!s || !f) return;
    const showFull = s.style.display !== 'none';
    s.style.display = showFull ? 'none' : 'block';
    f.style.display = showFull ? 'block' : 'none';
}

// ─────────────────────── NIEULOKALIZOWANE ────────────────────────────────────

let unlocalisedData = [];

function initUnlocalisedLayer() {
    unlocalisedData = mapData.unlocalised_offers || [];
    const activeCount = unlocalisedData.filter(o => o.active).length;
    if (unlocalisedData.length === 0) return;
    const bar = document.getElementById('unlocalised-toggle-bar');
    const cnt = document.getElementById('unlocalised-toggle-count');
    if (bar) { bar.style.display = 'block'; if (cnt) cnt.textContent = activeCount; }
    const badge = document.getElementById('unlocalised-count-badge');
    if (badge) badge.textContent = activeCount;
    renderUnlocalised();
}

function toggleUnlocalisedSection() {
    const section = document.getElementById('unlocalised-section');
    const bar     = document.getElementById('unlocalised-toggle-bar');
    if (!section) return;
    const hidden = section.style.display === 'none';
    section.style.display = hidden ? 'block' : 'none';
    if (bar) bar.style.display = hidden ? 'none' : 'block';
    if (hidden) { renderUnlocalised(); section.scrollIntoView({ behavior:'smooth', block:'start' }); }
}

function renderUnlocalised() {
    const grid   = document.getElementById('unlocalised-grid');
    const empty  = document.getElementById('unlocalised-empty');
    const badge  = document.getElementById('unlocalised-count-badge');
    if (!grid) return;

    const fTag    = document.getElementById('unlocalised-filter-tag')?.value    || 'all';
    const fStatus = document.getElementById('unlocalised-filter-status')?.value || 'active';
    const pMax    = parseInt(document.getElementById('unlocalised-price-max')?.value || '0');
    const q       = (document.getElementById('unlocalised-search')?.value || '').toLowerCase().trim();

    let filtered = unlocalisedData.filter(o => {
        if (fStatus === 'active' && !o.active) return false;
        if (fTag !== 'all' && o.tags?.primary !== fTag) return false;
        if (pMax > 0 && o.price > pMax) return false;
        if (q && !`${o.address} ${o.description}`.toLowerCase().includes(q)) return false;
        return true;
    }).sort((a, b) => a.active !== b.active ? (a.active ? -1 : 1) : a.price - b.price);

    if (badge) badge.textContent = filtered.filter(o => o.active).length;
    if (filtered.length === 0) { grid.innerHTML = ''; if (empty) empty.style.display = 'block'; return; }
    if (empty) empty.style.display = 'none';

    const tI = { mieszkanie:'🏢', kawalerka:'🏠', pokoj:'🛏️' };
    grid.innerHTML = filtered.map(o => {
        const ti    = tI[o.tags?.primary] || '📋';
        const tl    = o.tags?.primary || 'oferta';
        const isNew = o.is_new ? '<span class="badge-new">NOWA</span>' : '';
        const inact = !o.active ? '<span class="badge-inactive">nieaktywna</span>' : '';
        const desc  = o.description ? o.description.substring(0, 120).trim() + '…' : '';
        const media = o.media_info && o.media_info !== 'brak informacji' ? `<span class="media-small">💡 ${o.media_info}</span>` : '';
        const bg    = o.active ? 'white' : '#f8fafc';
        const bd    = o.active ? '#f59e0b' : '#e2e8f0';
        return `<div style="background:${bg};border:1px solid ${bd};border-radius:8px;padding:12px;font-size:13px;opacity:${o.active?1:0.75}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
                <div style="font-weight:600;color:#1e293b;flex:1;margin-right:8px">${ti} ${o.address||'Nieznany adres'} ${isNew}${inact}</div>
                <div style="font-weight:700;color:#7c3aed;white-space:nowrap;font-size:15px">${o.price?o.price.toLocaleString('pl-PL')+' zł':'—'}</div>
            </div>
            ${media?`<div style="margin-bottom:4px">${media}</div>`:''}
            <div style="color:#475569;font-size:12px;margin-bottom:6px;line-height:1.4">${desc}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:4px">
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                    <span style="background:#f1f5f9;color:#64748b;border-radius:4px;padding:2px 6px;font-size:11px">${ti} ${tl}</span>
                    <span style="color:#94a3b8;font-size:11px">📅 ${o.first_seen||'—'}</span>
                </div>
                <a href="${o.url}" target="_blank" rel="noopener" style="background:#7c3aed;color:white;border-radius:6px;padding:4px 10px;text-decoration:none;font-size:12px;font-weight:600">Otwórz →</a>
            </div>
        </div>`;
    }).join('');
}

// ─────────────────────── DEEP-LINK ?offer=<id> ───────────────────────────────
// Otwiera mapę z konkretną ofertą wybraną z innej strony (np. top5.html).
// Wymusza włączenie odpowiedniej warstwy (active/inactive/approx*) gdyby była
// odznaczona, bo inaczej setView nie pokaże markera.

function focusOfferFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const targetId = params.get('offer');
    if (!targetId) return;

    const match = allMarkers.find(item =>
        item.offers && item.offers.some(o => o.id === targetId)
    );

    if (!match) {
        console.warn(`⚠️ Oferta ${targetId} nie znaleziona na mapie (brak coords lub usunięta z bazy)`);
        showOfferNotFoundToast(targetId);
        return;
    }

    // Wybierz checkbox warstwy odpowiadający tej ofercie i upewnij się że jest zaznaczony
    let layerCheckboxId;
    if (!match.hasNumber && match.isActive)       layerCheckboxId = 'layer-approx';
    else if (!match.hasNumber && !match.isActive) layerCheckboxId = 'layer-approx-inactive';
    else if (match.isActive)                      layerCheckboxId = 'layer-active';
    else                                          layerCheckboxId = 'layer-inactive';

    const checkbox = document.getElementById(layerCheckboxId);
    if (checkbox && !checkbox.checked) {
        checkbox.checked = true;
        // Przeładuj widoczność warstw po zmianie checkboxa
        if (typeof filterMarkers === 'function') filterMarkers();
    }

    // Mała zwłoka żeby Leaflet zdążył zaktualizować warstwy
    setTimeout(() => {
        map.setView(match.marker.getLatLng(), 17);
        match.marker.openPopup();
    }, 150);
}

function showOfferNotFoundToast(offerId) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
        background: #fff3cd; color: #856404; border: 1px solid #ffeeba;
        padding: 12px 20px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        font-size: 14px; z-index: 10000; max-width: 400px; text-align: center;
    `;
    toast.innerHTML = `⚠️ Oferta <code style="background:#fff;padding:2px 6px;border-radius:3px">${offerId}</code> nie ma współrzędnych na mapie (brak adresu lub została usunięta z bazy).`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 6000);
}

// ─────────────────────── INIT ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => { initMap(); loadData(); });


