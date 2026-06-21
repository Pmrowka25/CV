
DROP VIEW IF EXISTS v_ostatnie_pozycje CASCADE;
DROP TABLE IF EXISTS Ostrzezenia_Lotowe CASCADE;
DROP TABLE IF EXISTS Pomiary_Lotu CASCADE;
DROP TABLE IF EXISTS Samoloty CASCADE;
DROP TABLE IF EXISTS Linie_Lotnicze CASCADE;
DROP TABLE IF EXISTS Kraje CASCADE;
DROP TABLE IF EXISTS Logi_Importu CASCADE;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";




CREATE TABLE Kraje (
    kraj_id       SERIAL          PRIMARY KEY,
    kod_iso2      CHAR(2)         NOT NULL UNIQUE,
    kod_iso3      CHAR(3)         UNIQUE,
    nazwa         VARCHAR(100)    NOT NULL,
    region        VARCHAR(100),
    data_dodania  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    aktywny       BOOLEAN         NOT NULL DEFAULT TRUE
);




CREATE TABLE Linie_Lotnicze (
    linia_id          SERIAL          PRIMARY KEY,
    nazwa             VARCHAR(150)    NOT NULL,
    kod_icao          CHAR(3)         UNIQUE,
    kod_iata          CHAR(2)         UNIQUE,
    kraj_id           INT             REFERENCES Kraje(kraj_id) ON DELETE SET NULL,
    prefiks_callsign  VARCHAR(10),
    aktywna           BOOLEAN         NOT NULL DEFAULT TRUE,
    data_dodania      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);




CREATE TABLE Samoloty (
    samolot_id        SERIAL          PRIMARY KEY,
    icao24            CHAR(6)         NOT NULL UNIQUE,
    znak_rejestracji  VARCHAR(20),
    typ_samolotu      VARCHAR(100),
    kraj_id           INT             REFERENCES Kraje(kraj_id) ON DELETE SET NULL,
    linia_id          INT             REFERENCES Linie_Lotnicze(linia_id) ON DELETE SET NULL,
    data_pierwszego_lotu TIMESTAMPTZ,
    aktywny           BOOLEAN         NOT NULL DEFAULT TRUE,
    data_dodania      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    data_aktualizacji TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_samoloty_icao24 ON Samoloty(icao24);


CREATE TABLE Pomiary_Lotu (
    pomiar_id         BIGSERIAL       PRIMARY KEY,
    samolot_id        INT             NOT NULL REFERENCES Samoloty(samolot_id) ON DELETE CASCADE,
    icao24            CHAR(6)         NOT NULL,
    callsign          VARCHAR(20),
    kraj_id           INT             REFERENCES Kraje(kraj_id) ON DELETE SET NULL,
    longitude         DOUBLE PRECISION,
    latitude          DOUBLE PRECISION,
    baro_altitude     DOUBLE PRECISION,
    geo_altitude      DOUBLE PRECISION,
    velocity          DOUBLE PRECISION,
    true_track        DOUBLE PRECISION,
    vertical_rate     DOUBLE PRECISION,
    on_ground         BOOLEAN         NOT NULL DEFAULT FALSE,
    time_position     TIMESTAMPTZ     NOT NULL,
    last_contact      TIMESTAMPTZ,
    import_timestamp  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    squawk            VARCHAR(10),
    spi               BOOLEAN         DEFAULT FALSE,
    position_source   SMALLINT,
    CONSTRAINT uq_pomiary_icao24_time UNIQUE (icao24, time_position)
);

CREATE INDEX idx_pomiary_time_position ON Pomiary_Lotu(time_position DESC);
CREATE INDEX idx_pomiary_icao24 ON Pomiary_Lotu(icao24);



CREATE TABLE Ostrzezenia_Lotowe (
    ostrzezenie_id    SERIAL          PRIMARY KEY,
    pomiar_id         BIGINT          REFERENCES Pomiary_Lotu(pomiar_id) ON DELETE SET NULL,
    samolot_id        INT             REFERENCES Samoloty(samolot_id) ON DELETE SET NULL,
    icao24            CHAR(6)         NOT NULL,
    typ_ostrzezenia   VARCHAR(50)     NOT NULL,
    opis              TEXT,
    wartosc_anomalii  DOUBLE PRECISION,
    czas_wystapienia  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    potwierdzone      BOOLEAN         NOT NULL DEFAULT FALSE,
    notatka_operatora TEXT
);

CREATE TABLE IF NOT EXISTS Lotniska (
    lotnisko_id SERIAL PRIMARY KEY,
    kod_icao CHAR(4) NOT NULL UNIQUE,
    nazwa VARCHAR(150) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL
);


INSERT INTO Lotniska (kod_icao, nazwa, latitude, longitude) VALUES
    ('EPWA', 'Lotnisko Chopina w Warszawie', 52.1657, 20.9671),
    ('EPKK', 'Port Lotniczy Kraków-Balice', 50.0777, 19.7848),
    ('EPGD', 'Port Lotniczy Gdańsk', 54.3776, 18.4662),
    ('EDDB', 'Berlin Brandenburg', 52.3622, 13.5006),
    ('LKPR', 'Praga - Vaclav Havel', 50.1008, 14.2600),
    ('LOWW', 'Wiedeń - Schwechat', 48.1102, 16.5697)
ON CONFLICT (kod_icao) DO NOTHING;



CREATE TABLE Logi_Importu (
    log_id              SERIAL          PRIMARY KEY,
    czas_rozpoczecia    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    czas_zakonczenia    TIMESTAMPTZ,
    status              VARCHAR(20)     NOT NULL DEFAULT 'W_TOKU' 
                        CHECK (status IN ('W_TOKU', 'SUKCES', 'BLAD', 'CZESCIOWY')),
    liczba_pobranych    INT             DEFAULT 0,             
    liczba_dodanych     INT             DEFAULT 0,             
    liczba_pominietych  INT             DEFAULT 0,             
    bbox_min_lon        DOUBLE PRECISION,
    bbox_max_lon        DOUBLE PRECISION,
    bbox_min_lat        DOUBLE PRECISION,
    bbox_max_lat        DOUBLE PRECISION,
    url_zapytania       TEXT,
    wersja_skryptu      VARCHAR(50),
    komunikat_bledu     TEXT
);


INSERT INTO Kraje (kod_iso2, kod_iso3, nazwa, region) VALUES
    ('PL', 'POL', 'Polska', 'Europa Srodkowa'),
    ('DE', 'DEU', 'Niemcy', 'Europa Zachodnia'),
    ('CZ', 'CZE', 'Czechy', 'Europa Srodkowa'),
    ('SK', 'SVK', 'Słowacja', 'Europa Srodkowa'),
    ('HU', 'HUN', 'Węgry', 'Europa Srodkowa'),
    ('AT', 'AUT', 'Austria', 'Europa Srodkowa'),
    ('CH', 'CHE', 'Szwajcaria', 'Europa Zachodnia'),
    ('FR', 'FRA', 'Francja', 'Europa Zachodnia'),
    ('IT', 'ITA', 'Włochy', 'Europa Południowa'),
    ('ES', 'ESP', 'Hiszpania', 'Europa Południowa'),
    ('NL', 'NLD', 'Holandia', 'Europa Zachodnia'),
    ('BE', 'BEL', 'Belgia', 'Europa Zachodnia'),
    ('GB', 'GBR', 'Wielka Brytania', 'Europa Zachodnia'),
    ('SE', 'SWE', 'Szwecja', 'Skandynawia'),
    ('RO', 'ROU', 'Rumunia', 'Europa Wschodnia'),
    ('XX', 'XXX', 'Nieznany', NULL);


CREATE VIEW v_ostatnie_pozycje AS
SELECT DISTINCT ON (p.icao24)
    p.pomiar_id, p.icao24, p.callsign, p.latitude, p.longitude,
    p.baro_altitude, p.velocity, p.time_position,
    k.nazwa AS kraj_nazwa
FROM Pomiary_Lotu p
LEFT JOIN Kraje k ON k.kraj_id = p.kraj_id
ORDER BY p.icao24, p.time_position DESC;


CREATE OR REPLACE FUNCTION fn_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.data_aktualizacji = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_samoloty_update
    BEFORE UPDATE ON Samoloty
    FOR EACH ROW EXECUTE FUNCTION fn_update_timestamp();