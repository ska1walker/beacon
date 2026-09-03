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
    db_name: str = "aicrm"
    db_user: str = "aicrm"
    db_password: str = "aicrm_dev_only"

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

    # --- Entwicklung ---
    # Auf der Box steht der Envoy-Sidecar davor und setzt X-Bfl-User. Lokal
    # gibt es ihn nicht; dann tut dieser Name so, als wäre jemand angemeldet.
    # Auf der Box bleibt der Wert leer — ein fehlender Header ist dort ein
    # Fehler und kein Anlass, jemanden zu erfinden.
    dev_user: str = ""


settings = Settings()
