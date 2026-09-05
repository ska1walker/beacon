#!/usr/bin/env python3
"""Manifest gegen das Application-Objekt auf der Box halten.

Ein `helm upgrade` tauscht die Workloads, liest aber das OlaresManifest
nicht neu ein. Entrances und Richtlinien im Application-Objekt sind
Installationsmetadaten: Sie stehen so, wie sie bei der Installation
waren — wie die eingefrorenen Werte (Constraint 9). Zweimal heute daran
gestolpert: eine Zwei-Faktor-Regel, die im Objekt weiterlebte, nachdem
sie aus dem Manifest verschwunden war, und ein neuer Entrance, der im
Manifest stand und im Objekt nicht ankam.

Dazu die Adresse, unter der ein Entrance von außen erreichbar ist: nicht
`<name>.<nutzer>.<zone>` (das gibt es nur für Systemapps — für alles
andere antwortet das Gateway mit 421, egal welches authLevel), sondern
`<appid><index>.<nutzer>.<zone>` mit `appid = md5(<appname>)[:8]` und dem
null-basierten Index im Manifest. Stundenlang am falschen Host gemessen.

Dieses Skript zeigt beide Seiten nebeneinander und nennt jede Abweichung.
Es ändert nichts. Aufruf vom Mac aus:

    python3 scripts/box-abgleich.py [olares@192.168.1.17]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

BOX = sys.argv[1] if len(sys.argv) > 1 else "olares@192.168.1.17"
MANIFEST = Path(__file__).resolve().parents[1] / "olares" / "OlaresManifest.yaml"
KUBE = "KUBECONFIG=/etc/rancher/k3s/k3s.yaml"


def manifest_entrances() -> list[dict]:
    """Ohne YAML-Bibliothek: Die Entrance-Blöcke sind flach und regelmäßig."""
    text = MANIFEST.read_text()
    block = text.split("entrances:", 1)[1].split("\n\n#", 1)[0]
    eintraege = []
    for teil in re.split(r"\n  - ", block)[1:]:
        e = {}
        # `teil` beginnt nach dem Trennen bereits mit "name: …".
        for zeile in teil.splitlines():
            m = re.match(r"\s*([a-zA-Z]+):\s*(.+?)\s*$", zeile)
            if m and not zeile.strip().startswith("#"):
                e[m.group(1)] = m.group(2)
        if e.get("name"):
            eintraege.append(e)
    return eintraege


def objekt() -> dict:
    roh = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", BOX,
         f"{KUBE} kubectl get application -A -o json"],
        capture_output=True, text=True,
    ).stdout
    d = json.loads(roh)
    for it in d["items"]:
        if it["metadata"]["name"].endswith("-beacon"):
            return it
    raise SystemExit("Kein beacon-Application-Objekt auf der Box.")


def zone(owner: str) -> str:
    """`bytetrade.io/zone` am User-Objekt, z. B. `kaivostudio.olares.de`."""
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", BOX,
         f"{KUBE} kubectl get user {owner} -o jsonpath='{{.metadata.annotations.bytetrade\\.io/zone}}'"],
        capture_output=True, text=True,
    ).stdout.strip() or f"{owner}.olares.de"


def main() -> int:
    soll = {e["name"]: e for e in manifest_entrances()}
    ist_obj = objekt()
    ist = {e["name"]: e for e in (ist_obj["spec"].get("entrances") or [])}
    abweichungen = 0

    print(f"{'Entrance':<14} {'Manifest':<28} Objekt")
    print("-" * 70)
    for name in sorted(set(soll) | set(ist)):
        s, i = soll.get(name), ist.get(name)
        links = f"{s['host']}:{s['port']} {s['authLevel']}" if s else "—"
        rechts = f"{i['host']}:{i['port']} {i['authLevel']}" if i else "—"
        gleich = bool(s and i and str(s["port"]) == str(i["port"])
                      and s["host"] == i["host"] and s["authLevel"] == i["authLevel"])
        marke = "  " if gleich else "!!"
        if not gleich:
            abweichungen += 1
        print(f"{marke} {name:<11} {links:<28} {rechts}")

    print()
    appid = ist_obj["spec"].get("appid", "?")
    z = zone(ist_obj["spec"].get("owner", "?"))
    status = {e["name"]: e.get("state") for e in (ist_obj.get("status", {}).get("entranceStatuses") or [])}
    print("Adressen von außen (Index = Reihenfolge im Objekt):")
    for idx, e in enumerate(ist_obj["spec"].get("entrances") or []):
        st = status.get(e["name"], "fehlt im Status — Olares füllt ihn nur beim Anlegen; für die Erreichbarkeit ohne Belang")
        print(f"   https://{appid}{idx}.{z}   {e['name']} ({e['authLevel']}) · Status: {st}")

    print()
    pol_roh = ist_obj["spec"].get("settings", {}).get("policy")
    subs = []
    if pol_roh:
        try:
            pol = json.loads(pol_roh)
            subs = next(iter(pol.values())).get("sub_policies") or []
        except Exception:
            pass
    im_manifest = "policies:" in MANIFEST.read_text().split("# Bewusst **keine** `policies`", 1)[0]
    print("Richtlinien: Manifest", "hat welche" if im_manifest else "keine",
          "· Objekt", f"{len(subs)} Unterregel(n)" if subs else "keine")
    if bool(subs) != im_manifest:
        abweichungen += 1
        print("!! Richtlinien weichen ab")

    print()
    print("ABWEICHUNGEN:", abweichungen, "" if abweichungen else "— Objekt und Manifest sagen dasselbe")
    return 1 if abweichungen else 0


if __name__ == "__main__":
    raise SystemExit(main())
