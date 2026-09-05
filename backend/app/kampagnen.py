"""Kampagnen — Marketing-Post an eine Liste, mit Buch und Klickzählung.

Was hier passiert, in einem Satz: Eine Liste sagt, wen man meint; der
Kontakt sagt, ob man ihm schreiben darf; die Kampagne schreibt jedem,
bei dem beides stimmt, eine Zeile ins Buch (`mails`), und die Schleife
schickt sie hinaus.

Drei Regeln, die man an einem Fall erkennt:

- **Ohne belegte Einwilligung keine Mail** — `bestaetigt` oder
  `bestandskunde`, sonst wird übergangen und gezählt. Die Liste wird
  dabei nicht angefasst; sie ist eine Absicht, kein Beleg.
- **Jeder Link in der Mail wird zu einem Klick-Link**, je Empfänger
  einer. Gezählt wird am Link (0018), nicht an der Kampagne — die Zahl
  entsteht beim Lesen aus den Zeilen und kann nicht falsch werden.
- **Eine Kampagne startet einmal.** Was danach kommt, ist eine neue.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import orjson

from app import links, segmente, versand

# Adressen im Text — http(s)://… bis zum nächsten Leerzeichen oder einer
# schließenden Klammer/Anführung. Eigene Links (Abmelden, Bestätigen)
# bleiben, wie sie sind: Ein Abmeldelink hinter einem Zähler wäre ein
# Abmeldelink, der von uns abhängt.
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")

EMPFAENGER_SQL = """
select k.id, k.email, k.first_name, k.last_name, k.job_title, f.name as company_name,
       k.marketing_einwilligung::text as einwilligung
  from public.contacts k
  left join public.companies f on f.id = k.company_id
 where k.deleted_at is null
"""


async def liste_laden(conn, liste_id: UUID) -> dict[str, Any] | None:
    z = await conn.fetchrow("select * from public.listen where id = $1 and deleted_at is null", liste_id)
    return dict(z) if z else None


def _filter(liste: dict[str, Any]) -> tuple[list[segmente.Bedingung], str]:
    roh = liste.get("filter") or []
    if isinstance(roh, str | bytes):
        roh = orjson.loads(roh)
    return segmente.bedingungen_aus(roh), liste.get("verknuepfung") or "und"


async def empfaenger(conn, liste: dict[str, Any], *, hoechstens: int = 5000) -> list[dict[str, Any]]:
    """Wen die Liste meint — statisch aus den Mitgliedern, aktiv aus dem Filter."""
    args: list[Any] = []
    sql = EMPFAENGER_SQL
    if liste["art"] == "statisch":
        args.append(liste["id"])
        sql += " and exists (select 1 from public.listen_mitglieder m where m.liste_id = $1 and m.contact_id = k.id)"
    else:
        bedingungen, verknuepfung = _filter(liste)
        sql += segmente.filter_zu_sql("contacts", bedingungen, args, verknuepfung=verknuepfung)
    sql += f" order by k.last_name nulls last, k.first_name nulls last limit {int(hoechstens)}"
    return [dict(z) for z in await conn.fetch(sql, *args)]


def darf(kontakt: dict[str, Any]) -> bool:
    return bool(kontakt.get("email")) and kontakt.get("einwilligung") in ("bestaetigt", "bestandskunde")


async def vorschau(conn, liste: dict[str, Any] | None) -> dict[str, int]:
    """Wie viele die Liste meint, und wie vielen man schreiben darf."""
    if liste is None:
        return {"gemeint": 0, "berechtigt": 0, "uebergangen": 0}
    alle = await empfaenger(conn, liste)
    ok = sum(1 for k in alle if darf(k))
    return {"gemeint": len(alle), "berechtigt": ok, "uebergangen": len(alle) - ok}


async def links_umschreiben(conn, org_id: UUID, text: str, *, basis: str, contact_id: UUID, kampagne_id: UUID) -> str:
    """Jede Adresse im Text wird ein Klick-Link — je Empfänger ein eigener."""
    ergebnis: list[str] = []
    pos = 0
    for m in _URL.finditer(text):
        url = m.group(0)
        ergebnis.append(text[pos:m.start()])
        if "/o/" in url and url.startswith(basis):
            ergebnis.append(url)
        else:
            token = await links.anlegen(conn, org_id, "klick", contact_id=contact_id, ziel_url=url, kampagne_id=kampagne_id)
            ergebnis.append(links.adresse(basis, "klick", token))
        pos = m.end()
    ergebnis.append(text[pos:])
    return "".join(ergebnis)


async def starten(conn, org_id: UUID, kampagne: dict[str, Any], *, actor: UUID) -> dict[str, int]:
    """Schreibt für jeden berechtigten Empfänger eine Zeile ins Buch.

    Der Versand selbst läuft in der Schleife (main._versandschleife) —
    eine Kampagne mit tausend Empfängern soll den Knopf nicht eine
    Minute lang festhalten. Gibt zurück, wie viele gemeint, eingereiht
    und übergangen wurden.
    """
    if kampagne["status"] != "entwurf":
        raise versand.Unmoeglich("Diese Kampagne ist schon gestartet.")
    if not (kampagne.get("betreff") or "").strip() or not (kampagne.get("text") or "").strip():
        raise versand.Unmoeglich("Betreff und Text fehlen noch.")
    liste = await liste_laden(conn, kampagne["liste_id"]) if kampagne.get("liste_id") else None
    if liste is None:
        raise versand.Unmoeglich("Die Kampagne hat keine Liste.")

    einst = await versand._einstellungen(conn, org_id)
    basis = versand.basis_url(einst)
    if not basis:
        raise versand.Unmoeglich("Die Adresse der öffentlichen Links fehlt — unter Einstellungen → E-Mail.")
    if versand.marketing_konto(einst) is None:
        raise versand.Unmoeglich("Kein Versandweg für Marketing-Post — SMTP-Konto oder Brevo unter Einstellungen.")

    alle = await empfaenger(conn, liste)
    eingereiht = 0
    uebergangen = 0
    async with conn.transaction():
        for k in alle:
            if not darf(k):
                uebergangen += 1
                continue
            werte = versand.platzhalter_aus(k)
            betreff = versand.rendern(kampagne["betreff"], werte)
            text = versand.rendern(kampagne["text"], {**werte, "abmeldelink": "{{abmeldelink}}"})
            text = await links_umschreiben(conn, org_id, text, basis=basis, contact_id=k["id"], kampagne_id=kampagne["id"])
            await versand.einreihen(
                conn, org_id, art="marketing", an=k["email"], betreff=betreff, text=text,
                contact_id=k["id"], created_by=actor, kampagne_id=kampagne["id"],
            )
            eingereiht += 1
        await conn.execute(
            """
            update public.kampagnen
               set status = 'laeuft', gestartet_am = now(), gestartet_von = $2,
                   empfaenger = $3, uebergangen = $4, updated_at = now()
             where id = $1
            """,
            kampagne["id"], actor, eingereiht, uebergangen,
        )
    return {"gemeint": len(alle), "eingereiht": eingereiht, "uebergangen": uebergangen}


async def kennzahlen(conn, kampagne_id: UUID) -> dict[str, int]:
    """Aus den Zeilen gerechnet, nie gespeichert."""
    m = await conn.fetchrow(
        """
        select count(*) filter (where status = 'gesendet') as gesendet,
               count(*) filter (where status = 'wartend') as wartend,
               count(*) filter (where status = 'fehlgeschlagen') as fehlgeschlagen
          from public.mails where kampagne_id = $1
        """,
        kampagne_id,
    )
    li = await conn.fetchrow(
        """
        select coalesce(sum(benutzt_anzahl) filter (where art = 'klick'), 0) as klicks,
               count(distinct contact_id) filter (where art = 'klick' and benutzt_anzahl > 0) as klicker,
               count(*) filter (where art = 'abmelden' and benutzt_am is not null) as abgemeldet
          from public.oeffentliche_links where kampagne_id = $1
        """,
        kampagne_id,
    )
    return {
        "gesendet": m["gesendet"], "wartend": m["wartend"], "fehlgeschlagen": m["fehlgeschlagen"],
        "klicks": int(li["klicks"]), "klicker": li["klicker"], "abgemeldet": li["abgemeldet"],
    }


def wirksamer_status(kampagne: dict[str, Any], zahlen: dict[str, int]) -> str:
    """`laeuft` ohne wartende Zeile ist `abgeschlossen` — gerechnet, nicht gespeichert."""
    if kampagne["status"] == "laeuft" and zahlen["wartend"] == 0:
        return "abgeschlossen"
    return kampagne["status"]
