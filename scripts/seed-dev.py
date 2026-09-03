#!/usr/bin/env python3
"""Beispieldaten für die Entwicklung.

Läuft gegen die laufende API, nicht gegen die Datenbank: Damit prüft das
Skript nebenbei die Schreibpfade und legt nichts an, was die Anwendung
selbst nicht anlegen könnte.

    python3 scripts/seed-dev.py [http://localhost:8000]
"""

import sys
from datetime import date, timedelta

import httpx

BASIS = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

FIRMEN = [
    {
        "name": "Nordlicht Steuerberatung",
        "domain": "nordlicht-stb.de",
        "industry": "Steuerberatung",
        "employee_count": 34,
        "city": "Lüneburg",
        "lifecycle_stage": "opportunity",
        "source": "Empfehlung",
        "description": "Sucht Entlastung bei der Auswertung von Jahresabschlüssen. Mandantendaten dürfen das Haus nicht verlassen — Kammerauflage.",
    },
    {
        "name": "Hanseatic Legal Partner",
        "domain": "hanseatic-legal.de",
        "industry": "Kanzlei",
        "employee_count": 78,
        "city": "Hamburg",
        "lifecycle_stage": "qualified",
        "source": "Messe",
        "description": "Wirtschaftskanzlei, Due-Diligence-Prüfungen. Zwei Partner treiben das Thema, die IT ist skeptisch.",
    },
    {
        "name": "Meyer Präzisionstechnik",
        "domain": "meyer-praezision.de",
        "industry": "Maschinenbau",
        "employee_count": 210,
        "city": "Wolfsburg",
        "lifecycle_stage": "opportunity",
        "source": "Website",
        "description": "Monatsabschluss und Abweichungsberichte laufen heute über drei Excel-Dateien und einen Mitarbeiter.",
    },
    {
        "name": "Elbufer Consulting",
        "domain": "elbufer-consulting.de",
        "industry": "Beratung",
        "employee_count": 12,
        "city": "Hamburg",
        "lifecycle_stage": "lead",
        "source": "LinkedIn",
        "description": "Erste Anfrage über das Kontaktformular. Bedarf noch unklar.",
    },
    {
        "name": "Krüger Logistik",
        "domain": "krueger-logistik.de",
        "industry": "Logistik",
        "employee_count": 95,
        "city": "Bremen",
        "lifecycle_stage": "customer",
        "source": "Empfehlung",
        "description": "Assistent seit Juni im Einsatz, fünf Nutzer. Erweiterung auf Analyst im Gespräch.",
    },
]

KONTAKTE = [
    ("Nordlicht Steuerberatung", "Andrea", "Vosskamp", "a.vosskamp@nordlicht-stb.de", "Partnerin", "Entscheiderin"),
    ("Nordlicht Steuerberatung", "Tim", "Reinhardt", "t.reinhardt@nordlicht-stb.de", "IT-Leitung", "Prüfer"),
    ("Hanseatic Legal Partner", "Dr. Julia", "Ahrend", "ahrend@hanseatic-legal.de", "Partnerin", "Fürsprecherin"),
    ("Hanseatic Legal Partner", "Sven", "Kolb", "kolb@hanseatic-legal.de", "IT-Leitung", "Blockierer"),
    ("Meyer Präzisionstechnik", "Bernd", "Meyer", "b.meyer@meyer-praezision.de", "Geschäftsführung", "Entscheider"),
    ("Meyer Präzisionstechnik", "Katrin", "Lohse", "k.lohse@meyer-praezision.de", "Leitung Controlling", "Anwenderin"),
    ("Elbufer Consulting", "Marco", "Thiele", "thiele@elbufer-consulting.de", "Inhaber", "Entscheider"),
    ("Krüger Logistik", "Petra", "Krüger", "p.krueger@krueger-logistik.de", "Geschäftsführung", "Entscheiderin"),
]

# (Firma, Name, Produkt, Betrag netto in Euro, Stufe, Tage bis Abschluss, nächster Schritt)
DEALS = [
    ("Nordlicht Steuerberatung", "Analyst — Jahresabschlussauswertung", "analyst", 14500, "Angebot", 21,
     "Angebot nachfassen, Frau Vosskamp hat Rückfragen zur Kammerauflage"),
    ("Hanseatic Legal Partner", "Analyst — Due Diligence", "analyst", 14500, "Vorführung", 45,
     "Termin für Vorführung mit Herrn Kolb finden"),
    ("Meyer Präzisionstechnik", "Experte — Monatsabschluss", "experte", 22500, "Verhandlung", 14,
     "Servicetage nachverhandeln, 12 sind zu knapp"),
    ("Elbufer Consulting", "Assistent — 5 Nutzer", "assistent", 9900, "Erstkontakt", 60,
     "Bedarf klären, erstes Telefonat vereinbaren"),
    ("Krüger Logistik", "Analyst — Erweiterung", "analyst", 14500, "Qualifiziert", 35,
     "Ist-Aufnahme im Controlling"),
    ("Krüger Logistik", "Assistent — Erstinstallation", "assistent", 9900, "Gewonnen", -40, None),
]

NOTIZEN = [
    ("Nordlicht Steuerberatung", "call", "Telefonat Frau Vosskamp",
     "45 Minuten. Kernfrage war nicht der Preis, sondern ob die Kammer den Betrieb im eigenen Haus als ausreichend ansieht. Zusage: schriftliche Beschreibung des Datenwegs bis Freitag."),
    ("Hanseatic Legal Partner", "meeting", "Vor-Ort-Termin",
     "Frau Dr. Ahrend treibt das Thema. Herr Kolb hat drei Einwände: Wartung, Stromaufnahme, Ausfallsicherheit. Der dritte ist der ernste."),
    ("Meyer Präzisionstechnik", "email", "Angebot versendet",
     "Experte mit 12 Servicetagen. Herr Meyer hat am selben Tag geantwortet und nach 20 Tagen gefragt."),
]


def main() -> None:
    with httpx.Client(base_url=BASIS, timeout=30.0) as c:
        stufen = {
            s["name"]: s["id"]
            for s in c.get("/api/pipelines").raise_for_status().json()[0]["stages"]
        }

        firmen: dict[str, str] = {}
        for f in FIRMEN:
            antwort = c.post("/api/companies", json=f)
            antwort.raise_for_status()
            firmen[f["name"]] = antwort.json()["id"]
            print(f"Firma   {f['name']}")

        kontakte: dict[str, str] = {}
        for firma, vorname, nachname, mail, position, rolle in KONTAKTE:
            antwort = c.post(
                "/api/contacts",
                json={
                    "first_name": vorname,
                    "last_name": nachname,
                    "email": mail,
                    "job_title": position,
                    "buying_role": rolle,
                    "company_id": firmen[firma],
                    "lifecycle_stage": "qualified",
                },
            )
            antwort.raise_for_status()
            kontakte[mail] = antwort.json()["id"]
            print(f"Kontakt {vorname} {nachname}")

        for firma, name, produkt, betrag, stufe, tage, schritt in DEALS:
            antwort = c.post(
                "/api/deals",
                json={
                    "name": name,
                    "company_id": firmen[firma],
                    "product": produkt,
                    "amount_cents": betrag * 100,
                    "close_date": str(date.today() + timedelta(days=tage)),
                    "next_step": schritt,
                },
            )
            antwort.raise_for_status()
            deal_id = antwort.json()["id"]
            if stufe != "Erstkontakt":
                c.post(f"/api/deals/{deal_id}/stage", json={"stage_id": stufen[stufe]}).raise_for_status()
            print(f"Deal    {name} → {stufe}")

        for firma, art, betreff, text in NOTIZEN:
            c.post(
                "/api/activities",
                json={"kind": art, "subject": betreff, "body": text, "company_id": firmen[firma]},
            ).raise_for_status()
            print(f"Notiz   {betreff}")

        c.post(
            "/api/tasks",
            json={
                "title": "Datenweg-Beschreibung an Nordlicht senden",
                "due_at": f"{date.today() + timedelta(days=2)}T09:00:00",
                "company_id": firmen["Nordlicht Steuerberatung"],
            },
        ).raise_for_status()
        c.post(
            "/api/tasks",
            json={
                "title": "Servicetage Meyer intern abstimmen",
                "due_at": f"{date.today()}T16:00:00",
                "company_id": firmen["Meyer Präzisionstechnik"],
            },
        ).raise_for_status()
        print("Aufgaben angelegt")


if __name__ == "__main__":
    main()
