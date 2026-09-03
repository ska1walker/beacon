import { AlertTriangle, Inbox } from "lucide-react";

export function Laedt({ text = "Wird geladen …" }: { text?: string }) {
  return (
    <div className="leerzustand">
      <p>{text}</p>
    </div>
  );
}

export function Fehler({ text }: { text: string }) {
  // Farbe trägt die Aussage nie allein: Zeichen und Satz stehen daneben.
  return (
    <div className="hinweis" data-art="fehler" role="alert">
      <AlertTriangle size={16} aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}

export function Leer({ titel, text }: { titel: string; text: string }) {
  return (
    <div className="leerzustand">
      <Inbox size={24} aria-hidden="true" />
      <h4>{titel}</h4>
      <p>{text}</p>
    </div>
  );
}
