# Projekt: Układ sterowania procesem nagrzewania płynu

### Opis projektu
Głównym celem projektu było zaprojektowanie i implementacja zaawansowanego układu automatycznej regulacji obiektu cieplno-hydraulicznego w środowisku CODESYS. Projekt łączy w sobie zagadnienia modelowania matematycznego procesów fizycznych z praktyczną implementacją algorytmów sterowania na sterowniku PLC.

### Realizowane scenariusze pracy
System został zaprojektowany do pracy w dwóch odmiennych trybach:
1. **Tryb sekwencyjny (Maszyna Stanów):** Realizuje cykliczny proces technologiczny polegający na napełnianiu zbiornika do zadanego poziomu, nagrzewaniu medium do temperatury docelowej oraz odlewaniu gotowej porcji produktu.
2. **Tryb ciągły (Regulacja PID):** Skupia się na utrzymaniu stabilnych parametrów (poziomu i temperatury) przy stałym przepływie medium. Wykorzystuje dwa sprzężone ze sobą regulatory PID, które sterują zaworem wlotowym oraz mocą grzałki.

### Logika i funkcjonalności
* **Modelowanie matematyczne:** Wewnątrz sterownika zaimplementowano model fizyczny obiektu (bilans masy i energii) w języku ST, co pozwala na realistyczną symulację bez użycia fizycznego sprzętu.
* **Architektura oprogramowania:** Kod został podzielony na moduły odpowiedzialne za symulację, skalowanie sygnałów, logikę sterowania oraz obsługę błędów.
* **System bezpieczeństwa:** Nadrzędna logika blokad chroni urządzenia wykonawcze (np. zabezpieczenie grzałki przed pracą na sucho) i reaguje na awarie czujników lub pomp.
* **HMI:** Intuicyjny panel wizualizacyjny umożliwia monitorowanie procesów w czasie rzeczywistym oraz ręczne sterowanie układem.

### Technologie
* **Środowisko:** CODESYS
* **Języki programowania:** Ladder Diagram (LD), Structured Text (ST)
* **Metody sterowania:** Regulatory PID, Automaty skończone (FSM)
