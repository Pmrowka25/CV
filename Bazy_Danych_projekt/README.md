# OpenSky Network – Projekt Semestralny

**Przedmiot:** Wprowadzenie do baz danych  
**Zespół:** Piotr Mrówka, Michał Midor, Tomasz Mazur


**Źródło danych:** [OpenSky Network REST API](https://openskynetwork.github.io/opensky-api/)  
**Stos technologiczny:** PostgreSQL · Python · Streamlit · Plotly

\---

## Opis projektu

Projekt obejmuje zaprojektowanie relacyjnej bazy danych dla ruchu lotniczego, cykliczny import danych z API OpenSky Network (Bounding Box: Europa Środkowa) oraz interaktywny dashboard wizualizacyjny z co najmniej 10 filtrami.

### Zakres projektu:

1. **Baza danych** – 4 tabele merytoryczne + 1 słownikowa + 1 techniczna
2. **Import danych** – skrypt Python z obsługą duplikatów i logowaniem
3. **Zapytania SQL** – 5 zaawansowanych zapytań analitycznych
4. **Dashboard** – 3 wizualizacje + 10 filtrów (Streamlit)

\---

## Struktura projektu

```text
projekt/
├── .env.example        # Szablon zmiennych środowiskowych
├── .env                # Plik z danymi dostępowymi do bazy (NIE commituj!)
├── README.md           # Ten plik
├── pyproject.toml      # Zależności Python (uv)
├── schema.sql          # Skrypt DDL – tworzenie tabel, indeksów, widoków
├── import\\\\\\\_opensky.py   # Skrypt importu danych z API do PostgreSQL
├── queries.sql         # 5 zaawansowanych zapytań analitycznych SQL
└── dashboard.py        # Dashboard Streamlit z wizualizacjami
```

## Wymagania

* **Python 3.11+**
* **PostgreSQL 15+** (lub kompatybilny)
* **uv** – menedżer środowiska wirtualnego ([instrukcja instalacji](https://docs.astral.sh/uv/))

## Instrukcja uruchomienia

### 1\. Klonowanie repozytorium

Sklonuj repozytorium i przejdź do katalogu projektu:

```bash
git clone <repo-url>
cd projekt/
```

### 2\. Przygotowanie środowiska wirtualnego

Utwórz i aktywuj środowisko wirtualne przy pomocy `uv`.

**Linux / macOS:**

```bash
uv venv
source .venv/bin/activate
```

**Windows (CMD):**

```cmd
uv venv
.venv\\\\\\\\Scripts\\\\\\\\activate
```

**Windows (PowerShell):**

```powershell
uv venv
.\\\\\\\\.venv\\\\\\\\Scripts\\\\\\\\Activate.ps1
```

### 3\. Instalacja zależności

```bash
uv pip install -r requirements.txt
```

### 4\. Konfiguracja zmiennych środowiskowych

Skopiuj szablon pliku `.env` i uzupełnij dane połączeniowe do bazy danych:

**Linux / macOS:**

```bash
cp .env.example .env
```

**Windows (CMD / PowerShell):**

```cmd
copy .env.example .env
```

Otwórz plik `.env` w edytorze tekstu i wpisz poprawne wartości dla: `DB\\\\\\\_HOST`, `DB\\\\\\\_PORT`, `DB\\\\\\\_NAME`, `DB\\\\\\\_USER`, `DB\\\\\\\_PASSWORD`.

### 5\. Inicjalizacja bazy danych i ładowanie schematu

Wybierz instrukcję odpowiednią dla Twojego systemu operacyjnego i konfiguracji PostgreSQL.

#### Opcja A: Linux (Debian/Ubuntu z domyślną instalacją)

*Uwaga: Wiele dystrybucji używa uwierzytelniania `peer` dla połączeń lokalnych, dlatego należy wywołać komendy z poziomu konta systemowego `postgres`:*

```bash
sudo -u postgres psql -c "CREATE DATABASE opensky;"
sudo -u postgres psql -d opensky -f schema.sql
```

#### Opcja B: macOS (Homebrew)

Jeśli PostgreSQL został uruchomiony jako usługa Homebrew:

```bash
psql -U postgres -c "CREATE DATABASE opensky;"
psql -U postgres -d opensky -f schema.sql
```

Jeżeli serwer wymaga podania hasła (metoda `md5`), użyj:

```bash
PGPASSWORD='twoje\\\\\\\_haslo' psql -h localhost -U postgres -c "CREATE DATABASE opensky;"
PGPASSWORD='twoje\\\\\\\_haslo' psql -h localhost -U postgres -d opensky -f schema.sql
```

#### Opcja C: Windows (CMD / PowerShell)

Upewnij się, że narzędzie `psql` jest dodane do zmiennej środowiskowej PATH (lub skorzystaj z aplikacji *SQL Shell (psql)*):

```cmd
psql -h localhost -U postgres -W -c "CREATE DATABASE opensky;"
psql -h localhost -U postgres -W -d opensky -f schema.sql
```

### 6\. Uruchomienie aplikacji

Po poprawnym skonfigurowaniu bazy uruchom skrypt importu danych oraz aplikację Streamlit:

```bash
# Uruchomienie jednorazowego importu
python import\\\\\\\_opensky.py

# LUB uruchomienie importu w pętli (tryb ciągły)
python import\\\\\\\_opensky.py --loop

# Uruchomienie dashboardu wizualizacyjnego
streamlit run dashboard.py
```

## Porady i rozwiązywanie problemów

* **Błąd "Peer authentication failed for user 'postgres'":** Na systemach Linux użycie przedrostka `sudo -u postgres ...` lub zmiana metody uwierzytelniania na `md5` w pliku konfiguracyjnym `pg\\\\\\\_hba.conf` (wymaga restartu serwera PostgreSQL) i ustawienie hasła dla użytkownika.
* **Połączenie z bazą:** Należy upewnić się, czy wartości wpisane w pliku `.env` są identyczne z konfiguracją serwera oraz czy usługa PostgreSQL nasłuchuje na wskazanym porcie.
* **Dane historyczne (backfill):** Darmowy punkt końcowy API `states/all` zwraca wyłącznie stan ruchu lotniczego w milisekundzie zapytania. Aby gromadzić dane długofalowo, należy uruchomić skrypt importu w trybie ciągłym (`--loop`) ze stałym interwałem czasowym (polling) bądź skorzystać z płatnego dostępu do historycznych dumpów OpenSky.

