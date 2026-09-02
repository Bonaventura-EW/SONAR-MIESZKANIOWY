---
id:          2026-09-02-unified-nav-header
repo:        Bonaventura-EW/SONAR-MIESZKANIOWY
family:      sonary
date:        2026-09-02
category:    css-refactor
what:        Jedna wspólna belka nawigacji (assets/header.css, klasa .sm-header) na wszystkich 9 zakładkach zamiast pięciu różnych belek kopiowanych inline po plikach HTML.
why:         Zakładki miały pięć różnych nagłówków i trzy różne listy linków — z czterech stron jedynym wyjściem był „← Powrót do mapy", a linku do nowszych zakładek (Okazje, Ceny/m²) nie było prawie znikąd. Belka trzymana w .container renderowała się jako wyspa 1200–1400 px zamiast na całą szerokość okna.
how:         Konstrukcja przeniesiona z SONAR-a POKOJOWEGO (sp-header): brand (logo + „NAZWA SONARU · nazwa zakładki") po lewej, komplet pigułek po prawej, aktywna wyróżniona, jeden plik CSS jako jedyne źródło prawdy. Nagłówek wyjęty przed .container, padding strony przeniesiony z body do .container. Zakładka generowana z Pythona dostała ten sam blok w szablonie generatora, nie tylko w wygenerowanym pliku. Paleta celowo została lokalna (fiolet), zmienia się tylko konstrukcja.
surface:     docs/assets/header.css, docs/*.html (9 stron), docs/assets/style.css, src/skipped_debug_generator.py
generality:  family
propagate:   maybe
commit:      d38d225
---

# Kontekst

Zmiana jest **powrotem** propagacji: to POKOJOWY miał już ujednoliconą belkę
(`assets/header.css`, klasa `sp-header`, wpis w jego CHANGELOG-u z 2026-08-31),
a MIESZKANIOWY został z pięcioma wariantami. Bracia, którzy tego jeszcze nie
mają (np. DZIAŁKOWY), dostają tu gotowy wzorzec.

Dwie rzeczy, których w wersji brata nie było, a warto przenieść:

1. **Próg 560 px** — przy `white-space: nowrap` na h1 pełne „SONAR … · nazwa
   zakładki" wypycha belkę poza ekran wąskiego telefonu. Poniżej 560 px
   chowamy separator i nazwę zakładki; niesie ją aktywna pigułka.
2. **Szablon generatora, nie wygenerowany plik.** Strona diagnostyczna powstaje
   w Pythonie — belka podmieniona wyłącznie w `docs/*.html` wróciłaby do starej
   wersji przy najbliższym skanie. To pułapka wspólna dla wszystkich sonarów.

Celowo LOKALNE: paleta. Rozważaliśmy przejęcie „Warm Sunset" brata 1:1
(pomarańcz → czerwień → róż), ale wtedy po zrzucie ekranu nie widać, w którym
sonarze się jest — kolor belki jest jedynym szybkim rozróżnikiem. Przenoś
konstrukcję i responsywność, nie hex-y.
