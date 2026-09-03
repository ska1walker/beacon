"""Die Punktzahl eines Geschäfts.

Sie wird gerechnet, nicht vergeben. Eine Zahl, die jemand von Hand setzt,
sagt über den Vergebenden mehr aus als über das Geschäft — und zwei Leute
vergeben sie unterschiedlich, womit die Prognose wertlos wird.
"""

from app.schemas import Qualifizierung

# Gewichte, die sich addieren. Sie stehen hier und nicht in der Datenbank:
# Ändert sich die Gewichtung, ändert sich die Bedeutung *aller* alten
# Zahlen mit — das ist eine Entscheidung, die in den Code gehört und
# nachvollziehbar sein muss, nicht in ein Einstellungsfeld.
#
# Wer entscheidet und ob Geld da ist, wiegt am schwersten: Daran scheitern
# Geschäfte spät. Der Standort wiegt wenig, weil er selten das Hindernis
# ist — aber er wiegt nicht null, weil er es manchmal doch ist.
GEWICHTE: list[tuple[str, int, str]] = [
    ("bedarf", 25, "Wofür genau — welches Problem soll gelöst werden?"),
    ("entscheider", 25, "Wer entscheidet, und ist er schon im Gespräch?"),
    ("budget_geklaert", 20, "Ist Geld dafür da und in welchem Rahmen?"),
    ("ausloeser", 15, "Warum jetzt — was hat den Anstoß gegeben?"),
    ("zeitrahmen", 10, "Bis wann soll es laufen?"),
    ("standort_geklaert", 5, "Passt die Hardware ins Haus — Platz, Strom, Netz?"),
]


def _gefuellt(wert: object) -> bool:
    if isinstance(wert, bool):
        return wert
    return bool(wert and str(wert).strip())


def punkte(q: Qualifizierung) -> int:
    return sum(g for feld, g, _ in GEWICHTE if _gefuellt(getattr(q, feld, None)))


def offen(q: Qualifizierung) -> list[str]:
    """Was noch fehlt, als Frage formuliert.

    Eine Punktzahl allein sagt niemandem, was als Nächstes zu tun ist.
    Diese Liste tut es.
    """
    return [frage for feld, _, frage in GEWICHTE if not _gefuellt(getattr(q, feld, None))]
