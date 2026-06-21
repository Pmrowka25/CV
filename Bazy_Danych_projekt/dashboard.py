"""
dashboard.py
============
Dashboard Streamlit do wizualizacji danych lotniczych z OpenSky Network.
Podłącza się do bazy PostgreSQL i oferuje 3 wizualizacje oraz 10 filtrów.

Wizualizacje:
  1. Mapa punktowa aktualnych pozycji samolotów (st.map)
  2. Wykres liniowy średniej prędkości w czasie (Plotly)
  3. Wykres słupkowy liczby pomiarów wg kraju (Plotly)

Filtry (panel boczny):
  1. Kraj pochodzenia
  2. Zakres dat (od)
  3. Zakres dat (do)
  4. Minimalna wysokość
  5. Maksymalna wysokość
  6. Minimalna prędkość
  7. Maksymalna prędkość
  8. Status (na ziemi / w powietrzu)
  9. ID samolotu (ICAO24)
  10. Znak wywoławczy (Callsign)

Uruchomienie:
    streamlit run dashboard.py

Wersja: 1.0.0
"""

"""
dashboard.py
============
Dashboard Streamlit do wizualizacji danych lotniczych z OpenSky Network.
Podłącza się do bazy PostgreSQL i oferuje 3 wizualizacje oraz rozbudowane filtry.

Wersja: 1.1.0 (Połączona wersja z geofencingiem i przełącznikiem czasu)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import requests

import streamlit as st
import plotly.express as px

# ---------------------------------------------------------------------------
# Konfiguracja strony Streamlit
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="OpenSky Dashboard – Ruch Lotniczy",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Ładowanie konfiguracji z .env
# ---------------------------------------------------------------------------
load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME", "opensky"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# ---------------------------------------------------------------------------
# Funkcje pomocnicze – połączenie z bazą i cachowanie danych
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        return conn
    except psycopg2.OperationalError as e:
        st.error(f"❌ Nie można połączyć się z bazą danych: {e}")
        st.stop()

@st.cache_data(ttl=60, show_spinner="Pobieram dane...")
def fetch_data(query: str, params: tuple | None = None) -> pd.DataFrame:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            return pd.DataFrame(rows) if rows else pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Błąd zapytania SQL: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def fetch_distinct_countries() -> pd.DataFrame:
    query = """
        SELECT DISTINCT k.kraj_id, k.nazwa, k.kod_iso2
        FROM Kraje k
        JOIN Pomiary_Lotu p ON p.kraj_id = k.kraj_id
        ORDER BY k.nazwa
    """
    return fetch_data(query)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_airlines() -> pd.DataFrame:
    query = "SELECT kod_icao, nazwa FROM Linie_Lotnicze ORDER BY nazwa"
    return fetch_data(query)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_airports() -> pd.DataFrame:
    query = "SELECT kod_icao, nazwa, latitude AS lat, longitude AS lon FROM Lotniska"
    return fetch_data(query)

# ---------------------------------------------------------------------------
# Budowanie dynamicznego zapytania SQL z filtrami
# ---------------------------------------------------------------------------

def build_where_clause(filters: dict) -> tuple[str, tuple]:
    conditions = []
    params = []

    if filters.get("kraj_ids"):
        placeholders = ", ".join(["%s"] * len(filters["kraj_ids"]))
        conditions.append(f"p.kraj_id IN ({placeholders})")
        params.extend(filters["kraj_ids"])

    if filters.get("data_od"):
        conditions.append("p.time_position >= %s")
        params.append(filters["data_od"])
        
    if filters.get("data_do"):
        conditions.append("p.time_position <= %s")
        params.append(filters["data_do"])

    if filters.get("min_wysokosc") is not None:
        conditions.append("p.baro_altitude >= %s")
        params.append(filters["min_wysokosc"])
        
    if filters.get("max_wysokosc") is not None:
        conditions.append("p.baro_altitude <= %s")
        params.append(filters["max_wysokosc"])

    if filters.get("min_predkosc") is not None:
        conditions.append("p.velocity >= %s")
        params.append(filters["min_predkosc"])
        
    if filters.get("max_predkosc") is not None:
        conditions.append("p.velocity <= %s")
        params.append(filters["max_predkosc"])

    if filters.get("status") is not None:
        conditions.append("p.on_ground = %s")
        params.append(filters["status"])

    if filters.get("icao24"):
        conditions.append("p.icao24 = %s")
        params.append(filters["icao24"].strip().lower())

    if filters.get("callsign"):
        conditions.append("p.callsign ILIKE %s")
        params.append(f"%{filters['callsign'].strip().upper()}%")

    # Filtr 11: Linia lotnicza
    if filters.get("linie_icao"):
        placeholders = ", ".join(["%s"] * len(filters["linie_icao"]))
        conditions.append(f"SUBSTRING(p.callsign FROM 1 FOR 3) IN ({placeholders})")
        params.extend(filters["linie_icao"])

    # Filtr 12: Promień wokół lotniska (Geofencing)
    if filters.get("airport_lat") is not None and filters.get("airport_lon") is not None and filters.get("airport_radius"):
        lat = filters["airport_lat"]
        lon = filters["airport_lon"]
        radius = filters["airport_radius"]
        conditions.append(
            "(SQRT(POWER(p.latitude - %s, 2) + POWER((p.longitude - %s) * COS(RADIANS(%s)), 2)) * 111.32) <= %s"
        )
        params.extend([lat, lon, lat, radius])

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, tuple(params)


# =============================================================================
# INTERFEJS UŻYTKOWNIKA
# =============================================================================

st.title("✈️ OpenSky Network – Dashboard Ruchu Lotniczego")
st.caption("Dane w czasie bliskim rzeczywistemu z obszaru Europy Środkowej.")

# ---------------------------------------------------------------------------
# Panel boczny – Filtry
# ---------------------------------------------------------------------------
st.sidebar.header("🔍 Filtry")
filters: dict = {}

countries_df = fetch_distinct_countries()
if not countries_df.empty:
    kraj_options = countries_df["nazwa"].tolist()
    kraj_mapping = dict(zip(countries_df["nazwa"], countries_df["kraj_id"]))
    wybrane_kraje = st.sidebar.multiselect(
        "1. Kraj pochodzenia",
        options=kraj_options,
        default=[],
        help="Wybierz jeden lub więcej krajów. Puste = wszystkie.",
        key="filter_kraje",
    )
    if wybrane_kraje:
        filters["kraj_ids"] = [kraj_mapping[k] for k in wybrane_kraje]

st.sidebar.markdown("---")
domyslna_data_od = datetime.now(timezone.utc).date() - timedelta(days=7)
domyslna_data_do = datetime.now(timezone.utc).date()

data_od = st.sidebar.date_input(
    "2. Data początkowa (od)",
    value=domyslna_data_od,
    help="Pomiary od tej daty (włącznie).",
    key="filter_data_od",
)
data_do = st.sidebar.date_input(
    "3. Data końcowa (do)",
    value=domyslna_data_do,
    help="Pomiary do tej daty (włącznie).",
    key="filter_data_do",
)
if data_od:
    filters["data_od"] = datetime.combine(data_od, datetime.min.time(), tzinfo=timezone.utc)
if data_do:
    filters["data_do"] = datetime.combine(data_do, datetime.max.time(), tzinfo=timezone.utc)

st.sidebar.markdown("---")
col_alt1, col_alt2 = st.sidebar.columns(2)
with col_alt1:
    min_wys = st.number_input(
        "4. Min. wysokość [m]",
        min_value=0.0,
        value=None,
        step=100.0,
        format="%.0f",
        help="Minimalna wysokość barometryczna.",
        key="filter_min_wys",
    )
with col_alt2:
    max_wys = st.number_input(
        "5. Max. wysokość [m]",
        min_value=0.0,
        value=None,
        step=1000.0,
        format="%.0f",
        help="Maksymalna wysokość barometryczna.",
        key="filter_max_wys",
    )
filters["min_wysokosc"] = min_wys if min_wys and min_wys > 0 else None
filters["max_wysokosc"] = max_wys if max_wys and max_wys > 0 else None

st.sidebar.markdown("---")
col_spd1, col_spd2 = st.sidebar.columns(2)
with col_spd1:
    min_spd = st.number_input(
        "6. Min. prędkość [m/s]",
        min_value=0.0,
        value=None,
        step=10.0,
        format="%.0f",
        help="Minimalna prędkość naziemna.",
        key="filter_min_spd",
    )
with col_spd2:
    max_spd = st.number_input(
        "7. Max. prędkość [m/s]",
        min_value=0.0,
        value=None,
        step=50.0,
        format="%.0f",
        help="Maksymalna prędkość naziemna.",
        key="filter_max_spd",
    )
filters["min_predkosc"] = min_spd if min_spd and min_spd > 0 else None
filters["max_predkosc"] = max_spd if max_spd and max_spd > 0 else None

st.sidebar.markdown("---")
status_opcje = ["Wszystkie", "W powietrzu", "Na ziemi"]
wybrany_status = st.sidebar.radio(
    "8. Status lotu",
    options=status_opcje,
    index=0,
    help="Filtruj samoloty w powietrzu lub na ziemi.",
    key="filter_status",
)
if wybrany_status == "W powietrzu":
    filters["status"] = False
elif wybrany_status == "Na ziemi":
    filters["status"] = True

st.sidebar.markdown("---")
icao_input = st.sidebar.text_input(
    "9. ICAO24 (hex)",
    value="",
    max_chars=6,
    help="6-znakowy adres transpondera Mode-S, np. 3c6444.",
    key="filter_icao24",
)
filters["icao24"] = icao_input.strip() if icao_input.strip() else None



# ---------------------------------------------------------------------------
# Filtr 10: Callsign
# ---------------------------------------------------------------------------
callsign_input = st.sidebar.text_input(
    "10. Znak wywoławczy (Callsign)",
    value="",
    help="Fragment znaku wywoławczego, np. LOT lub RYR.",
    key="filter_callsign",
)
filters["callsign"] = callsign_input.strip() if callsign_input.strip() else None

# ---------------------------------------------------------------------------
# Filtr 11: Linia lotnicza
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
airlines_df = fetch_airlines()
if not airlines_df.empty:
    airline_options = [f"{row['nazwa']} ({row['kod_icao']})" for _, row in airlines_df.iterrows()]
    airline_mapping = {f"{row['nazwa']} ({row['kod_icao']})": row['kod_icao'] for _, row in airlines_df.iterrows()}
    
    wybrane_linie = st.sidebar.multiselect(
        "11. Linia lotnicza",
        options=airline_options,
        default=[],
        key="filter_linie",
    )
    if wybrane_linie:
        filters["linie_icao"] = [airline_mapping[k] for k in wybrane_linie]

# ---------------------------------------------------------------------------
# Filtr 12 i 13: Strefa wokół lotniska
# ---------------------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("📍 Strefa wokół lotniska")
airports_df = fetch_airports()
if not airports_df.empty:
    airport_opts = ["Brak"] + [f"{r['nazwa']} ({r['kod_icao']})" for _, r in airports_df.iterrows()]
    wybrane_lotnisko = st.sidebar.selectbox("12. Wybierz lotnisko", options=airport_opts, key="filter_lotnisko")

    if wybrane_lotnisko != "Brak":
        icao_wybranego = wybrane_lotnisko.split("(")[-1].replace(")", "")
        wybrane_dane = airports_df[airports_df["kod_icao"] == icao_wybranego].iloc[0]
        promien = st.sidebar.slider("13. Promień strefy [km]", min_value=10, max_value=150, value=50, step=10, key="filter_promien")
        
        filters["airport_lat"] = float(wybrane_dane["lat"])
        filters["airport_lon"] = float(wybrane_dane["lon"])
        filters["airport_radius"] = promien

# ---------------------------------------------------------------------------
# Inteligentny reset
# ---------------------------------------------------------------------------
def reset_all_filters():
    """Czyści wszystkie klucze w session_state zaczynające się od 'filter_'."""
    for key in list(st.session_state.keys()):
        if key.startswith("filter_"):
            del st.session_state[key]

st.sidebar.markdown("---")
st.sidebar.button("🔄 Resetuj wszystkie filtry", on_click=reset_all_filters)
st.sidebar.markdown("---")
st.sidebar.caption(f"🕒 Odświeżono: {datetime.now().strftime('%H:%M:%S')}")

where_sql, where_params = build_where_clause(filters)

# ---------------------------------------------------------------------------
# Kafle metryczne (KPI)
# ---------------------------------------------------------------------------
st.subheader("📊 Podsumowanie")
metric_query = f"""
    SELECT
        COUNT(*)                                   AS liczba_pomiarow,
        COUNT(DISTINCT icao24)                     AS unikalne_samoloty,
        ROUND(AVG(baro_altitude)::NUMERIC, 0)      AS srednia_wysokosc,
        ROUND(AVG(velocity)::NUMERIC, 1)           AS srednia_predkosc,
        COUNT(*) FILTER (WHERE on_ground = FALSE)  AS w_powietrzu,
        COUNT(*) FILTER (WHERE on_ground = TRUE)   AS na_ziemi
    FROM Pomiary_Lotu p
    {where_sql}
"""
metrics_df = fetch_data(metric_query, where_params)

col1, col2, col3, col4, col5, col6 = st.columns(6)
with col1:
    val = metrics_df['liczba_pomiarow'].iloc[0] if not metrics_df.empty else 0
    st.metric("📡 Pomiary", f"{val:,}" if val is not None else "0")
with col2:
    val = metrics_df['unikalne_samoloty'].iloc[0] if not metrics_df.empty else 0
    st.metric("✈️ Samoloty", f"{val:,}" if val is not None else "0")
with col3:
    val = metrics_df['srednia_wysokosc'].iloc[0] if not metrics_df.empty else None
    st.metric("📏 Śr. wysokość", f"{val:,.0f} m" if val is not None else "brak danych")
with col4:
    val = metrics_df['srednia_predkosc'].iloc[0] if not metrics_df.empty else None
    st.metric("💨 Śr. prędkość", f"{val:,.1f} m/s" if val is not None else "brak danych")
with col5:
    val = metrics_df['w_powietrzu'].iloc[0] if not metrics_df.empty else 0
    st.metric("🟢 W powietrzu", f"{val:,}" if val is not None else "0")
with col6:
    val = metrics_df['na_ziemi'].iloc[0] if not metrics_df.empty else 0
    st.metric("🟤 Na ziemi", f"{val:,}" if val is not None else "0")

st.markdown("---")

# =============================================================================
# WIZUALIZACJA 1: Mapa punktowa
# =============================================================================
st.subheader("🗺️ Mapa – Aktualne pozycje samolotów")

map_full_query = f"""
    SELECT DISTINCT ON (p.icao24)
        p.icao24,
        p.callsign,
        p.latitude,
        p.longitude,
        p.baro_altitude,
        p.velocity,
        p.on_ground,
        p.time_position,
        k.nazwa AS kraj
    FROM Pomiary_Lotu p
    LEFT JOIN Kraje k ON k.kraj_id = p.kraj_id
    WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
    {("AND " + where_sql.replace("WHERE ", "")) if where_sql else ""}
    ORDER BY p.icao24, p.time_position DESC
    LIMIT 500
"""
# Przekazujemy where_params, aby zmienne z filtrów zadziałały w mapie
map_df = fetch_data(map_full_query, where_params)

if not map_df.empty and "latitude" in map_df.columns and "longitude" in map_df.columns:
    map_df = map_df.rename(columns={"latitude": "lat", "longitude": "lon"})
    map_df['color'] = '#0044ff' 
    map_df['size'] = 50

    st.sidebar.markdown("---")
    pokaz_lotniska = st.sidebar.checkbox("📍 Pokaż lotniska na mapie", value=True)
    if pokaz_lotniska:
        if not airports_df.empty:
            airports_df['color'] = '#ff0000'
            airports_df['size'] = 250
            map_df = pd.concat([map_df, airports_df], ignore_index=True)

    st.map(map_df, latitude='lat', longitude='lon', color='color', size='size', width='stretch')
    st.caption(f"Liczba wyświetlonych punktów: {len(map_df)}")
else:
    st.info("ℹ️ Brak danych spełniających kryteria filtrowania dla mapy.")

st.markdown("---")

# =============================================================================
# WIZUALIZACJA 2: Wykres liniowy (Z modyfikacją kolegi)
# =============================================================================
st.subheader("📈 Średnia prędkość w czasie")

agregacja = st.radio(
    "Wybierz precyzję czasu:",
    ["Godzinowa", "Minutowa"],
    index=0,
    horizontal=True,
    help="Zmień na 'Minutowa', jeśli masz mało danych z jednej godziny, aby zobaczyć więcej punktów.",
    key="filter_agregacja",
)
unit = 'hour' if agregacja == "Godzinowa" else 'minute'

line_query = f"""
    SELECT
        DATE_TRUNC('{unit}', time_position)::TIMESTAMP  AS czas,
        ROUND(AVG(velocity)::NUMERIC, 2)               AS srednia_predkosc_ms,
        COUNT(*)                                        AS liczba_pomiarow,
        ROUND(AVG(baro_altitude)::NUMERIC, 0)           AS srednia_wysokosc_m
    FROM Pomiary_Lotu p
    {where_sql}
      AND velocity IS NOT NULL
    GROUP BY czas
    ORDER BY czas
"""
line_df = fetch_data(line_query, where_params)

if not line_df.empty:
    fig_line = px.line(
        line_df, x="czas", y="srednia_predkosc_ms",
        title=f"Średnia prędkość naziemna [m/s] ({agregacja.lower()})",
        labels={"czas": "Czas (UTC)", "srednia_predkosc_ms": "Średnia prędkość [m/s]"},
        markers=True,
    )
    fig_line.update_traces(line=dict(width=2))
    fig_line.update_layout(hovermode="x unified", height=400, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig_line, use_container_width=True)

    with st.expander("📏 Zobacz również: Średnia wysokość w czasie"):
        fig_alt = px.line(
            line_df, x="czas", y="srednia_wysokosc_m",
            title=f"Średnia wysokość barometryczna [m] ({agregacja.lower()})",
            labels={"czas": "Czas (UTC)", "srednia_wysokosc_m": "Średnia wysokość [m]"},
            markers=True, color_discrete_sequence=["#2ca02c"],
        )
        fig_alt.update_traces(line=dict(width=2))
        fig_alt.update_layout(hovermode="x unified", height=350, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig_alt, use_container_width=True)
else:
    st.info("ℹ️ Brak danych do wygenerowania wykresu liniowego.")

st.markdown("---")

# =============================================================================
# WIZUALIZACJA 3: Wykres słupkowy
# =============================================================================
st.subheader("📊 Liczba pomiarów według kraju")

bar_query = f"""
    SELECT
        COALESCE(k.nazwa, 'Nieznany')      AS kraj,
        COUNT(*)                           AS liczba_pomiarow,
        COUNT(DISTINCT p.icao24)           AS unikalne_samoloty,
        ROUND(AVG(p.velocity)::NUMERIC, 2) AS srednia_predkosc_ms
    FROM Pomiary_Lotu p
    LEFT JOIN Kraje k ON k.kraj_id = p.kraj_id
    {where_sql}
    GROUP BY k.nazwa
    ORDER BY liczba_pomiarow DESC
    LIMIT 15
"""
bar_df = fetch_data(bar_query, where_params)

if not bar_df.empty:
    fig_bar = px.bar(
        bar_df, x="kraj", y="liczba_pomiarow",
        title="TOP 15 krajów wg liczby pomiarów",
        labels={"kraj": "Kraj", "liczba_pomiarow": "Liczba pomiarów"},
        color="srednia_predkosc_ms", color_continuous_scale="Viridis",
        hover_data=["unikalne_samoloty", "srednia_predkosc_ms"],
    )
    fig_bar.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=20), coloraxis_colorbar=dict(title="Śr. prędkość [m/s]"))
    st.plotly_chart(fig_bar, use_container_width=True)

    with st.expander("📋 Zobacz dane tabelaryczne"):
        st.dataframe(
            bar_df, use_container_width=True, hide_index=True,
            column_config={
                "kraj": "Kraj",
                "liczba_pomiarow": "Pomiary",
                "unikalne_samoloty": "Unikalne samoloty",
                "srednia_predkosc_ms": st.column_config.NumberColumn("Śr. prędkość [m/s]", format="%.2f"),
            },
        )
else:
    st.info("ℹ️ Brak danych do wygenerowania wykresu słupkowego.")

# =============================================================================
# Wyszukiwarka Tras
# =============================================================================
st.markdown("---")
st.subheader("🛫 Sprawdź trasę samolotu (Skąd -> Dokąd)")
st.caption("Wpisz znak wywoławczy (Callsign), aby sprawdzić w publicznej bazie zaplanowaną trasę lotu.")

kol_wyszukiwarki, kol_wyniku = st.columns([1, 2])
with kol_wyszukiwarki:
    szukany_callsign = st.text_input("Znak wywoławczy (np. LOT, RYR, AFR):", max_chars=8)
    sprawdz_btn = st.button("🔍 Szukaj trasy")

with kol_wyniku:
    if sprawdz_btn and szukany_callsign:
        szukany_callsign = szukany_callsign.strip().upper()
        url_trasy = f"https://opensky-network.org/api/routes?callsign={szukany_callsign}"
        try:
            resp = requests.get(url_trasy, timeout=5)
            if resp.status_code == 200:
                dane_trasy = resp.json()
                trasa = dane_trasy.get("route", [])
                if len(trasa) >= 2:
                    st.success(f"**Lot {szukany_callsign}**\n\n🛫 **Wyleciał z:** {trasa[0]} (Kod ICAO)\n\n🛬 **Leci do:** {trasa[1]} (Kod ICAO)")
                else:
                    st.info(f"Znaleziono lot {szukany_callsign}, ale baza OpenSky nie ma pełnych danych o trasie.")
            elif resp.status_code == 404:
                st.warning(f"Brak informacji o trasie dla {szukany_callsign}. Może to być lot prywatny lub wojskowy.")
            else:
                st.error("Wystąpił problem z połączeniem z bazą tras OpenSky.")
        except Exception as e:
            st.error(f"Błąd zapytania: {e}")

st.markdown("---")
st.caption(f"Projekt semestralny | Dashboard v1.1.0 | Ostatnie odświeżenie: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")