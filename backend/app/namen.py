"""Wer mit einem Namen gemeint ist.

Insilo kennt von den Menschen in einem Gespräch nur, was gesagt oder
eingetragen wurde: „Frau Lohse", „Berater Klein", „Herr Meyer". Keine
E-Mail, keine Kennung. Wer daraus einen Kontakt machen will, vergleicht
Namensteile, nicht ganze Zeichenketten — „Frau Lohse" und „Katrin Lohse"
sind dieselbe Person.

Stand bis 0.10.0 in `routers/notiz.py`. Seit dieselbe Frage auch bei
Besprechungen gestellt wird, steht sie hier, damit beide gleich antworten.
"""

# Anreden, die kein Namensteil sind. Ohne sie gilt „Frau Lohse" als
# unbekannt, obwohl Katrin Lohse im CRM steht.
ANREDEN = {"herr", "frau", "dr", "prof", "dipl", "ing", "herrn"}


def namensteile(name: str) -> set[str]:
    return {
        teil.strip(".,").lower()
        for teil in name.split()
        if teil.strip(".,").lower() not in ANREDEN and len(teil.strip(".,")) > 1
    }


def ist_bekannt(genannt: str, bekannte: list[str]) -> bool:
    """Ist diese Person im CRM zu finden?

    Verglichen werden Namensteile, nicht ganze Zeichenketten. „Frau Lohse"
    und „Katrin Lohse" sind dieselbe Person; ein Vergleich auf Gleichheit
    hätte sie als unbekannt gemeldet — und der Vertriebler hätte den
    Hinweis nach dem dritten Mal ignoriert.
    """
    teile = namensteile(genannt)
    if not teile:
        return False
    return any(teile & namensteile(bekannt) for bekannt in bekannte)
