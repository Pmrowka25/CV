SET client_encoding = 'UTF8';

SELECT
    k.nazwa                                      AS kraj,
    k.kod_iso2,
    COUNT(DISTINCT p.icao24)                     AS liczba_unikalnych_samolotow,
    COUNT(*)                                     AS liczba_pomiarow,
    ROUND(AVG(p.baro_altitude)::NUMERIC, 1)      AS srednia_wysokosc_m,
    ROUND(AVG(p.velocity)::NUMERIC, 2)           AS srednia_predkosc_ms,
    MIN(p.time_position)                         AS pierwszy_pomiar,
    MAX(p.time_position)                         AS ostatni_pomiar
FROM  Pomiary_Lotu p
JOIN  Kraje k         ON k.kraj_id = p.kraj_id
WHERE p.on_ground = FALSE                        
  AND p.baro_altitude IS NOT NULL
GROUP BY k.kraj_id, k.nazwa, k.kod_iso2
ORDER BY liczba_unikalnych_samolotow DESC
LIMIT 10;


WITH godzinowe AS (
    SELECT
        EXTRACT(HOUR FROM time_position)::INT        AS godzina_utc,
        COUNT(*)                                      AS liczba_pomiarow,
        COUNT(DISTINCT icao24)                        AS unikalne_samoloty,
        ROUND(AVG(velocity)::NUMERIC, 2)              AS srednia_predkosc_ms,
        ROUND(AVG(baro_altitude)::NUMERIC, 1)         AS srednia_wysokosc_m
    FROM  Pomiary_Lotu
    WHERE on_ground = FALSE
      AND time_position >= NOW() - INTERVAL '7 days'  
    GROUP BY godzina_utc
),
ze_srednia AS (
    SELECT *,
        ROUND(AVG(liczba_pomiarow) OVER ()::NUMERIC, 1)  AS srednia_calodobowa,
        LAG(liczba_pomiarow, 1) OVER (ORDER BY godzina_utc) AS poprzednia_godzina
    FROM godzinowe
)
SELECT
    godzina_utc,
    liczba_pomiarow,
    unikalne_samoloty,
    srednia_predkosc_ms,
    srednia_wysokosc_m,
    srednia_calodobowa,
    ROUND(
        (liczba_pomiarow - srednia_calodobowa) / NULLIF(srednia_calodobowa, 0) * 100,
        1
    )                                                    AS odchylenie_od_sredniej_pct,
    CASE
        WHEN liczba_pomiarow = MAX(liczba_pomiarow) OVER () THEN 'SZCZYT'
        WHEN liczba_pomiarow = MIN(liczba_pomiarow) OVER () THEN 'MINIMUM'
        ELSE ''
    END                                                  AS oznaczenie
FROM ze_srednia
ORDER BY godzina_utc;

WITH loty_per_linia AS (
    SELECT
        ll.linia_id,
        ll.nazwa                                  AS linia_lotnicza,
        ll.kod_icao,
        k.nazwa                                   AS kraj_linii,
        COUNT(DISTINCT p.icao24)                  AS samoloty,
        COUNT(DISTINCT
            CONCAT(p.icao24, '_',
                   DATE_TRUNC('hour', p.time_position)::TEXT)
        )                                         AS przyblizna_liczba_lotow,
        ROUND(AVG(p.velocity)::NUMERIC, 2)        AS srednia_predkosc_ms,
        ROUND(AVG(p.baro_altitude)::NUMERIC, 1)   AS srednia_wysokosc_m,
        ROUND(MAX(p.velocity)::NUMERIC, 2)        AS maks_predkosc_ms,
        COUNT(*) FILTER (WHERE p.on_ground = TRUE) AS pomiary_na_ziemi,
        COUNT(*) FILTER (WHERE p.on_ground = FALSE) AS pomiary_w_powietrzu
    FROM Linie_Lotnicze ll
    JOIN Samoloty s         ON s.linia_id = ll.linia_id
    JOIN Pomiary_Lotu p     ON p.icao24   = s.icao24
    LEFT JOIN Kraje k       ON k.kraj_id  = ll.kraj_id
    WHERE p.time_position >= NOW() - INTERVAL '30 days'
    GROUP BY ll.linia_id, ll.nazwa, ll.kod_icao, k.nazwa
    HAVING COUNT(DISTINCT p.icao24) >= 1
)
SELECT
    RANK() OVER (ORDER BY przyblizna_liczba_lotow DESC) AS pozycja,
    linia_lotnicza,
    kod_icao,
    kraj_linii,
    samoloty,
    przyblizna_liczba_lotow,
    srednia_predkosc_ms,
    srednia_wysokosc_m,
    maks_predkosc_ms,
    ROUND(
        pomiary_w_powietrzu::NUMERIC / NULLIF(pomiary_na_ziemi + pomiary_w_powietrzu, 0) * 100,
        1
    )                                                   AS pct_w_powietrzu
FROM loty_per_linia
ORDER BY przyblizna_liczba_lotow DESC
LIMIT 20;


WITH dzienne_logi AS (
    SELECT
        DATE_TRUNC('day', czas_rozpoczecia)::DATE     AS dzien,
        COUNT(*)                                       AS uruchomienia_ogolem,
        COUNT(*) FILTER (WHERE status = 'SUKCES')      AS sukcesy,
        COUNT(*) FILTER (WHERE status = 'BLAD')        AS bledy,
        COUNT(*) FILTER (WHERE status = 'CZESCIOWY')   AS czesciowe,
        SUM(liczba_pobranych)                          AS pobranych_ogolem,
        SUM(liczba_dodanych)                           AS dodanych_ogolem,
        SUM("liczba_pominietych")                      AS pominietych_ogolem,
        ROUND(AVG(
            EXTRACT(EPOCH FROM (czas_zakonczenia - czas_rozpoczecia))
        )::NUMERIC, 1)                                 AS sredni_czas_importu_sek,
        MAX(EXTRACT(EPOCH FROM (czas_zakonczenia - czas_rozpoczecia)))::INT
                                                       AS maks_czas_sek
    FROM Logi_Importu
    WHERE czas_rozpoczecia >= NOW() - INTERVAL '30 days'
    GROUP BY dzien
)
SELECT
    dzien,
    uruchomienia_ogolem,
    sukcesy,
    bledy,
    ROUND(sukcesy::NUMERIC / NULLIF(uruchomienia_ogolem, 0) * 100, 1)  AS skutecznosc_pct,
    pobranych_ogolem,
    dodanych_ogolem,
    pominietych_ogolem,
    ROUND(
        pominietych_ogolem::NUMERIC / NULLIF(pobranych_ogolem, 0) * 100, 1
    )                                                                    AS pct_duplikatow,
    sredni_czas_importu_sek,
    maks_czas_sek,
    CASE
        WHEN bledy > 0           THEN 'Błędy'
        WHEN sukcesy = 0         THEN 'Brak danych'
        WHEN pominietych_ogolem::NUMERIC / NULLIF(pobranych_ogolem,0) > 0.9
                                 THEN ' Dużo duplikatów'
        ELSE                          'OK'
    END                                                                  AS ocena
FROM dzienne_logi
ORDER BY dzien DESC;


WITH statystyki_samolotow AS (
    SELECT
        p.icao24,
        s.znak_rejestracji,
        s.typ_samolotu,
        k.nazwa                                         AS kraj_rejestracji,
        COUNT(*)                                        AS liczba_pomiarow,
        ROUND(MIN(p.velocity)::NUMERIC, 2)              AS min_predkosc_ms,
        ROUND(MAX(p.velocity)::NUMERIC, 2)              AS maks_predkosc_ms,
        ROUND(AVG(p.velocity)::NUMERIC, 2)              AS avg_predkosc_ms,
        ROUND(STDDEV(p.velocity)::NUMERIC, 2)           AS odchylenie_std_predkosci,
        ROUND((MAX(p.velocity) - MIN(p.velocity))::NUMERIC, 2)  AS rozstep_predkosci_ms,
        ROUND(MIN(p.baro_altitude)::NUMERIC, 1)         AS min_wysokosc_m,
        ROUND(MAX(p.baro_altitude)::NUMERIC, 1)         AS maks_wysokosc_m,
        MIN(p.time_position)                            AS pierwszy_pomiar,
        MAX(p.time_position)                            AS ostatni_pomiar,
        COUNT(*) FILTER (WHERE p.on_ground = FALSE)     AS pomiary_w_locie,
        COUNT(*) FILTER (WHERE p.vertical_rate < -5)    AS momenty_opadania
    FROM Pomiary_Lotu p
    LEFT JOIN Samoloty s ON s.icao24   = p.icao24
    LEFT JOIN Kraje    k ON k.kraj_id  = s.kraj_id
    WHERE p.velocity IS NOT NULL
      AND p.time_position >= NOW() - INTERVAL '24 hours'
    GROUP BY p.icao24, s.znak_rejestracji, s.typ_samolotu, k.nazwa
    HAVING COUNT(*) >= 3                                
),
z_percentylami AS (
    SELECT *,
        NTILE(4) OVER (ORDER BY rozstep_predkosci_ms DESC)  AS kwartal_rozstepu,
        NTILE(4) OVER (ORDER BY odchylenie_std_predkosci DESC) AS kwartal_zmiennosci
    FROM statystyki_samolotow
)
SELECT
    icao24,
    COALESCE(znak_rejestracji, 'N/A')                  AS rejestracja,
    COALESCE(typ_samolotu, 'Nieznany')                  AS typ,
    COALESCE(kraj_rejestracji, 'Nieznany')              AS kraj,
    liczba_pomiarow,
    min_predkosc_ms,
    maks_predkosc_ms,
    avg_predkosc_ms,
    odchylenie_std_predkosci,
    rozstep_predkosci_ms,
    min_wysokosc_m,
    maks_wysokosc_m,
    ROUND(
        EXTRACT(EPOCH FROM (ostatni_pomiar - pierwszy_pomiar)) / 60, 1
    )                                                   AS czas_obserwacji_min,
    momenty_opadania,
    CASE kwartal_rozstepu
        WHEN 1 THEN 'Bardzo wysoka zmienność'
        WHEN 2 THEN 'Wysoka zmienność'
        WHEN 3 THEN 'Niska zmienność'
        WHEN 4 THEN 'Bardzo niska zmienność'
    END                                                 AS kategoria_zmiennosci
FROM z_percentylami
WHERE kwartal_rozstepu = 1                              
ORDER BY rozstep_predkosci_ms DESC
LIMIT 25;