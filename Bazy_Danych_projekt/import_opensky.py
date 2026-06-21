"""
import_opensky.py
================
Skrypt importujący dane lotnicze z OpenSky Network REST API do PostgreSQL.

Architektura:
- Używa python-dotenv do ładowania poświadczeń z pliku .env
- Loguje każde uruchomienie w tabeli Logi_Importu (start → koniec + status)
- Wstawia dane z INSERT ... ON CONFLICT DO NOTHING (eliminacja duplikatów)
- Obsługuje upsert tabeli Samoloty (nowe samoloty są dodawane automatycznie)
- Przystosowany do uruchamiania przez cron lub pętlę z sleep

Uruchomienie:
    python import_opensky.py              # jednorazowo
    python import_opensky.py --loop       # ciągły import co INTERVAL_SEC sekund

Cron (co 5 minut):
    */5 * * * * /path/to/venv/bin/python /path/to/import_opensky.py >> /var/log/opensky.log 2>&1

Wersja: 1.0.0
"""

import os
import sys
import time
import logging
import argparse
import traceback
from datetime import datetime, timezone

import requests
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# Konfiguracja loggera – zapisuje do stdout (cron przekieruje do pliku)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Stałe konfiguracyjne

SCRIPT_VERSION = "1.0.0"

# Bounding Box: Europa Środkowa (lon_min, lat_min, lon_max, lat_max)
# Obejmuje: PL, DE, CZ, SK, HU, AT i okolice
BBOX = {
    "min_lon": 10.0,
    "min_lat": 47.0,
    "max_lon": 25.0,
    "max_lat": 55.0,
}

# Interwał między importami w trybie --loop (sekundy)
INTERVAL_SEC = int(os.getenv("IMPORT_INTERVAL_SEC", "300"))  # domyślnie 5 minut

# URL endpointu OpenSky – wersja publiczna (bez uwierzytelnienia, limit req/h)
OPENSKY_URL = (
    "https://opensky-network.org/api/states/all"
    "?lamin={min_lat}&lomin={min_lon}&lamax={max_lat}&lomax={max_lon}"
)

# Mapa: indeks kolumny w odpowiedzi API → nazwa pola
# Zgodnie z dokumentacją: https://openskynetwork.github.io/opensky-api/rest.html
STATE_FIELDS = [
    "icao24",        # 0  – string
    "callsign",      # 1  – string (może być None)
    "origin_country",# 2  – string
    "time_position", # 3  – Unix timestamp (int) lub None
    "last_contact",  # 4  – Unix timestamp (int)
    "longitude",     # 5  – float lub None
    "latitude",      # 6  – float lub None
    "baro_altitude", # 7  – float lub None [m]
    "on_ground",     # 8  – bool
    "velocity",      # 9  – float lub None [m/s]
    "true_track",    # 10 – float lub None [stopnie]
    "vertical_rate", # 11 – float lub None [m/s]
    "sensors",       # 12 – lista (pomijamy)
    "geo_altitude",  # 13 – float lub None [m]
    "squawk",        # 14 – string lub None
    "spi",           # 15 – bool
    "position_source",# 16 – int (0=ADS-B, 1=ASTERIX, 2=MLAT, 3=FLARM)
]



# Funkcje pomocnicze


def load_env() -> dict:
    """Ładuje zmienne środowiskowe z pliku .env i zwraca słownik DSN."""
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Brakujące zmienne środowiskowe w .env: {', '.join(missing)}"
        )
    return {
        "host":     os.getenv("DB_HOST"),
        "port":     int(os.getenv("DB_PORT", "5432")),
        "dbname":   os.getenv("DB_NAME"),
        "user":     os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }


def get_db_connection(dsn: dict) -> psycopg2.extensions.connection:
    """Otwiera i zwraca połączenie z PostgreSQL."""
    conn = psycopg2.connect(**dsn)
    conn.autocommit = False
    return conn


def ts_to_utc(unix_ts) -> datetime | None:
    """Konwertuje Unix timestamp (int) na datetime ze strefą UTC lub None."""
    if unix_ts is None:
        return None
    return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc)


def state_to_dict(state: list) -> dict:
    """Mapuje listę wartości z API na słownik z nazwami pól."""
    d = {}
    for i, field in enumerate(STATE_FIELDS):
        d[field] = state[i] if i < len(state) else None
    return d


# Funkcje bazodanowe

def start_log(cur, url: str) -> int:
    """
    Zapisuje fakt rozpoczęcia importu w tabeli Logi_Importu.
    Zwraca log_id nowo utworzonego rekordu.
    """
    cur.execute(
        """
        INSERT INTO Logi_Importu
            (status, bbox_min_lon, bbox_max_lon, bbox_min_lat, bbox_max_lat,
             url_zapytania, wersja_skryptu)
        VALUES
            ('W_TOKU', %(min_lon)s, %(max_lon)s, %(min_lat)s, %(max_lat)s,
             %(url)s, %(ver)s)
        RETURNING log_id
        """,
        {**BBOX, "url": url, "ver": SCRIPT_VERSION},
    )
    return cur.fetchone()[0]


def finish_log(cur, log_id: int, status: str,
               pobrane: int, dodane: int, pominiete: int,
               blad: str | None = None):
    """Aktualizuje rekord logu po zakończeniu importu."""
    cur.execute(
        """
        UPDATE Logi_Importu
        SET    czas_zakonczenia   = NOW(),
               status             = %(status)s,
               liczba_pobranych   = %(pobrane)s,
               liczba_dodanych    = %(dodane)s,
               "liczba_pominietych" = %(pominiete)s,
               komunikat_bledu   = %(blad)s
        WHERE  log_id = %(log_id)s
        """,
        {
            "status":    status,
            "pobrane":   pobrane,
            "dodane":    dodane,
            "pominiete": pominiete,
            "blad":      blad,
            "log_id":    log_id,
        },
    )


def get_or_create_kraj(cur, iso_code: str | None) -> int | None:
    """
    Zwraca kraj_id dla podanego kodu ISO2.
    Jeśli kraj nie istnieje w słowniku, wstawia go z kodem 'XX' (Nieznany).
    """
    if not iso_code:
        return None

    # OpenSky zwraca pełne nazwy krajów, nie kody ISO.
    # Używamy mapowania nazwa→ISO2 (uproszczone, rozszerzalne).
    NAME_TO_ISO2 = {
        "Poland": "PL", "Germany": "DE", "Czech Republic": "CZ",
        "Slovakia": "SK", "Hungary": "HU", "Austria": "AT",
        "Switzerland": "CH", "France": "FR", "Italy": "IT",
        "Spain": "ES", "Netherlands": "NL", "Belgium": "BE",
        "United Kingdom": "GB", "Sweden": "SE", "Norway": "NO",
        "Denmark": "DK", "Finland": "FI", "Romania": "RO",
        "Ukraine": "UA", "Croatia": "HR", "Slovenia": "SI",
        "Lithuania": "LT", "Latvia": "LV", "Estonia": "EE",
    }

    iso2 = NAME_TO_ISO2.get(iso_code, None)

    if iso2:
        cur.execute("SELECT kraj_id FROM Kraje WHERE kod_iso2 = %s", (iso2,))
        row = cur.fetchone()
        if row:
            return row[0]

    # Nieznany kraj – wstawiamy do słownika lub używamy istniejącego 'XX'
    cur.execute("SELECT kraj_id FROM Kraje WHERE kod_iso2 = 'XX'")
    row = cur.fetchone()
    return row[0] if row else None


def upsert_samolot(cur, icao24: str, kraj_id: int | None) -> int:
    """
    Wstawia nowy samolot lub zwraca istniejący samolot_id.
    Nie nadpisuje istniejących danych (ON CONFLICT DO NOTHING).
    """
    cur.execute(
        """
        INSERT INTO Samoloty (icao24, kraj_id)
        VALUES (%s, %s)
        ON CONFLICT (icao24) DO NOTHING
        """,
        (icao24, kraj_id),
    )
    cur.execute("SELECT samolot_id FROM Samoloty WHERE icao24 = %s", (icao24,))
    return cur.fetchone()[0]


def insert_pomiary_batch(cur, records: list[dict]) -> tuple[int, int]:
    """
    Wstawia listę pomiarów do Pomiary_Lotu używając:
      INSERT ... ON CONFLICT (icao24, time_position) DO NOTHING
    Zwraca (liczba_dodanych, liczba_pominietych).
    """
    if not records:
        return 0, 0

    sql = """
        INSERT INTO Pomiary_Lotu (
            samolot_id, icao24, callsign, kraj_id,
            longitude, latitude, baro_altitude, geo_altitude,
            velocity, true_track, vertical_rate,
            on_ground, time_position, last_contact,
            squawk, spi, position_source
        ) VALUES (
            %(samolot_id)s, %(icao24)s, %(callsign)s, %(kraj_id)s,
            %(longitude)s, %(latitude)s, %(baro_altitude)s, %(geo_altitude)s,
            %(velocity)s, %(true_track)s, %(vertical_rate)s,
            %(on_ground)s, %(time_position)s, %(last_contact)s,
            %(squawk)s, %(spi)s, %(position_source)s
        )
        ON CONFLICT (icao24, time_position) DO NOTHING
    """

    before = cur.rowcount  # nie jest wiarygodne dla executemany – liczymy inaczej

    # execute_values jest znacznie szybsze niż executemany dla dużych zbiorów
    inserted = 0
    for rec in records:
        cur.execute(sql, rec)
        inserted += cur.rowcount  # 1 = wstawiono, 0 = pominięto (conflict)

    skipped = len(records) - inserted
    return inserted, skipped


def generate_warnings(cur, records: list[dict]):
    """
    Generuje ostrzeżenia lotowe dla anomalnych pomiarów:
    - LOW_ALTITUDE: samolot w powietrzu poniżej 300 m
    - HIGH_DESCENT: prędkość pionowa < -15 m/s
    - NO_POSITION:  brak danych GPS
    """
    warnings = []
    for rec in records:
        if not rec.get("on_ground") and rec.get("baro_altitude") is not None:
            if 0 < rec["baro_altitude"] < 300:
                warnings.append({
                    "icao24":          rec["icao24"],
                    "samolot_id":      rec.get("samolot_id"),
                    "typ":             "LOW_ALTITUDE",
                    "opis":            f"Samolot {rec['icao24']} leci na bardzo niskiej wysokości.",
                    "wartosc_anomalii": rec["baro_altitude"],
                })
        if rec.get("vertical_rate") is not None and rec["vertical_rate"] < -15:
            warnings.append({
                "icao24":          rec["icao24"],
                "samolot_id":      rec.get("samolot_id"),
                "typ":             "HIGH_DESCENT",
                "opis":            f"Gwałtowne opadanie: {rec['vertical_rate']:.1f} m/s",
                "wartosc_anomalii": rec["vertical_rate"],
            })
        if rec.get("latitude") is None or rec.get("longitude") is None:
            warnings.append({
                "icao24":     rec["icao24"],
                "samolot_id": rec.get("samolot_id"),
                "typ":        "NO_POSITION",
                "opis":       f"Brak danych GPS dla samolotu {rec['icao24']}.",
                "wartosc_anomalii": None,
            })

    if warnings:
        cur.executemany(
            """
            INSERT INTO Ostrzezenia_Lotowe
                (icao24, samolot_id, typ_ostrzezenia, opis, wartosc_anomalii)
            VALUES
                (%(icao24)s, %(samolot_id)s, %(typ)s, %(opis)s, %(wartosc_anomalii)s)
            """,
            warnings,
        )
        log.info(f"Wygenerowano {len(warnings)} ostrzeżeń lotowych.")



# Główna funkcja importu

def run_import(dsn: dict) -> bool:
    """
    Wykonuje jeden cykl importu danych z API OpenSky.
    Zwraca True przy sukcesie, False przy błędzie krytycznym.
    """
    url = OPENSKY_URL.format(**BBOX)
    log.info("=" * 65)
    log.info(f"Rozpoczynanie importu | {datetime.now(timezone.utc).isoformat()}")
    log.info(f"  URL: {url}")

    conn = None
    log_id = None
    status = "BLAD"
    pobrane = dodane = pominiete = 0
    error_msg = None

    try:
        conn = get_db_connection(dsn)
        with conn.cursor() as cur:
            # --- Krok 1: Zapis startu w Logi_Importu ---
            log_id = start_log(cur, url)
            conn.commit()
            log.info(f"Log importu zarejestrowany (log_id={log_id})")

            # --- Krok 2: Pobranie danych z API ---
            log.info("Odpytywanie OpenSky Network API...")
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                raise RuntimeError(f"Błąd HTTP {e.response.status_code}: {e}")
            except requests.exceptions.ConnectionError:
                raise RuntimeError("Brak połączenia z API OpenSky Network.")
            except requests.exceptions.Timeout:
                raise RuntimeError("Timeout przy pobieraniu danych z API (>30s).")

            payload = resp.json()
            states = payload.get("states") or []
            pobrane = len(states)
            log.info(f"Pobrano {pobrane} pomiarów z API (czas: {payload.get('time')})")

            if pobrane == 0:
                log.warning("API zwróciło 0 stanów – brak danych w bounding boxie?")
                finish_log(cur, log_id, "SUKCES", 0, 0, 0)
                conn.commit()
                return True

            # --- Krok 3: Przetwarzanie i zapis rekordów ---
            records_to_insert = []

            for state in states:
                d = state_to_dict(state)

                # Pomiń rekordy bez icao24
                if not d["icao24"]:
                    continue

                d["icao24"]      = d["icao24"].strip().lower()
                d["callsign"]    = d["callsign"].strip() if d["callsign"] else None
                d["time_position"] = ts_to_utc(d["time_position"])
                d["last_contact"]  = ts_to_utc(d["last_contact"])

                # Pomijamy rekordy bez time_position (wymagany dla klucza unikalnego)
                if d["time_position"] is None:
                    continue

                # Upsert krajów i samolotów (słowniki)
                kraj_id   = get_or_create_kraj(cur, d["origin_country"])
                samolot_id = upsert_samolot(cur, d["icao24"], kraj_id)

                records_to_insert.append({
                    "samolot_id":     samolot_id,
                    "icao24":         d["icao24"],
                    "callsign":       d["callsign"],
                    "kraj_id":        kraj_id,
                    "longitude":      d["longitude"],
                    "latitude":       d["latitude"],
                    "baro_altitude":  d["baro_altitude"],
                    "geo_altitude":   d["geo_altitude"],
                    "velocity":       d["velocity"],
                    "true_track":     d["true_track"],
                    "vertical_rate":  d["vertical_rate"],
                    "on_ground":      bool(d["on_ground"]),
                    "time_position":  d["time_position"],
                    "last_contact":   d["last_contact"],
                    "squawk":         d["squawk"],
                    "spi":            bool(d["spi"]) if d["spi"] is not None else False,
                    "position_source": d["position_source"],
                })

            # Zapis pomiarów (batch)
            dodane, pominiete = insert_pomiary_batch(cur, records_to_insert)
            log.info(f"Wstawiono: {dodane} | Pominięto (duplikaty): {pominiete}")

            # Generowanie ostrzeżeń
            generate_warnings(cur, records_to_insert)

            # --- Krok 4: Aktualizacja logu – sukces ---
            status = "SUKCES"
            finish_log(cur, log_id, status, pobrane, dodane, pominiete)
            conn.commit()
            log.info(f"Import zakończony sukcesem (log_id={log_id})")
            return True

    except Exception as exc:
        error_msg = traceback.format_exc()
        log.error(f"  ✗ Krytyczny błąd importu:\n{error_msg}")
        if conn and log_id:
            try:
                conn.rollback()
                with conn.cursor() as cur:
                    finish_log(cur, log_id, "BLAD", pobrane, dodane, pominiete, error_msg)
                conn.commit()
            except Exception as inner:
                log.error(f"Nie można zapisać błędu w logu: {inner}")
        return False

    finally:
        if conn:
            conn.close()
            log.info("Połączenie z bazą zamknięte.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import danych OpenSky → PostgreSQL")
    parser.add_argument(
        "--loop",
        action="store_true",
        help=f"Tryb ciągły: powtarzaj import co {INTERVAL_SEC}s (IMPORT_INTERVAL_SEC).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    dsn = load_env()

    if args.loop:
        log.info(f"Tryb pętli – interwał: {INTERVAL_SEC}s. Przerwij przez Ctrl+C.")
        while True:
            run_import(dsn)
            log.info(f"Czekam {INTERVAL_SEC}s na następny import...")
            time.sleep(INTERVAL_SEC)
    else:
        success = run_import(dsn)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
