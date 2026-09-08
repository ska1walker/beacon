"""Laufzeit-Konfiguration aus Umgebungsvariablen.

Nichts, was Olares injiziert, steht hier fest verdrahtet: Die Werte für
Postgres kommen zur Laufzeit aus dem Helm-Chart (`.Values.postgres.*`).
Die Vorgaben taugen für die lokale Entwicklung und sonst nirgends.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Datenbank ---
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "beacon"
    db_user: str = "beacon"
    db_password: str = "beacon_dev_only"

    # --- Anwendung ---
    app_lang: str = "de"
    app_timezone: str = "Europe/Berlin"

    # --- Ablage ---
    # Der einzige Ort, der eine Deinstallation überlebt (permission.appData).
    # Olares erlaubt nur /app/data, /app/cache und /app/Home; lokal zeigt
    # die .env auf einen Ordner im Repo.
    app_data_dir: str = "/app/data"

    # Wie viele Sicherungen aufgehoben werden. Vierzehn Tage sind lang
    # genug, um einen Fehler zu bemerken, und kurz genug, dass die Ablage
    # einer Box das trägt.
    sicherung_behalten: int = 14

    # Abstand zwischen den selbsttätigen Sicherungen. Sechs Stunden heißt:
    # Im schlimmsten Fall ist ein halber Arbeitstag verloren.
    sicherung_intervall_stunden: float = 6.0
    # Wie oft nachgesehen wird, ob sich etwas geändert hat. Geschrieben wird
    # nur bei Änderung — und spätestens nach dem Intervall oben.
    sicherung_pruefung_minuten: float = 5.0

    # --- Sprachmodell ---
    # Kein Vorgabewert, aus demselben Grund wie bei Insilo: jede geratene
    # Adresse ist bei einer anderen Box falsch. Die Olares-App-Kennung von
    # LiteLLM wird erst bei dessen Installation vergeben. Leer heißt „noch
    # nicht eingerichtet" — die Oberfläche sagt das, statt in einen
    # Verbindungsfehler zu laufen. Pro Organisation überschreibbar in
    # public.org_settings.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Wie lange ein Modellaufruf höchstens dauern darf. Ein lokales Modell
    # auf der Box antwortet langsamer als eine Cloud-API; 120 s ist
    # gemessen an AIM Qwen3.6 mit langem Kontext knapp, aber tragbar.
    llm_timeout_s: float = 120.0

    # --- Öffentliche Links ---
    # Die Domain, unter der Olares den ersten Entrance führt
    # (`.Values.domain.beacon`, z. B. 4d3bf559.kaivostudio.olares.de). Daraus
    # leitet app/versand.py die Adresse des öffentlichen Entrance ab. Leer
    # heißt: nicht bekannt — dann muss sie in den Einstellungen stehen.
    app_domain: str = ""

    # --- Anmeldung ---
    # "olares": Die Identität kommt aus dem Kopf X-Bfl-User, den der
    # Envoy-Sidecar setzt — der Weg, solange der Entrance `internal` ist.
    # "eigen": Beacon meldet selbst an, der Kopf wird **vollständig
    # ignoriert**. Ohne das wäre er bei offenem Entrance eine
    # Selbstbedienung: Jeder erfundene Name legte Nutzer, Organisation und
    # Owner-Rolle an.
    anmeldung_modus: str = "olares"

    # Wie lange eine Sitzung höchstens gilt und wie lange sie still sein
    # darf. Dreißig Tage sind bequem, sieben Tage Stille sind die Grenze —
    # ein vergessener Browser im Zug soll nicht einen Monat offen stehen.
    sitzung_tage: int = 30
    sitzung_leerlauf_tage: int = 7
    einladung_tage: int = 7

    # --- Entwicklung ---
    # Auf der Box steht der Envoy-Sidecar davor und setzt X-Bfl-User. Lokal
    # gibt es ihn nicht; dann tut dieser Name so, als wäre jemand angemeldet.
    # Auf der Box bleibt der Wert leer — ein fehlender Header ist dort ein
    # Fehler und kein Anlass, jemanden zu erfinden.
    dev_user: str = ""


settings = Settings()
