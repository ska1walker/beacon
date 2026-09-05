import Link from "next/link";

export function Seitenkopf({
  titel,
  zahl,
  pfad,
  children,
}: {
  titel: string;
  zahl?: string;
  pfad?: { text: string; href: string };
  children?: React.ReactNode;
}) {
  return (
    <header className="seitenkopf">
      <div>
        {pfad && (
          <div className="seitenkopf-pfad">
            <Link href={pfad.href}>{pfad.text}</Link>
          </div>
        )}
        {/* Titel und Anzahl nebeneinander, nicht untereinander: Der Kopf
            hat eine feste Höhe, die er mit der linken Spalte teilt. Eine
            zweite Zeile würde diese Linie zerreißen. */}
        <div className="seitenkopf-zeile">
          <h1>{titel}</h1>
          {zahl && <span className="seitenkopf-zahl">{zahl}</span>}
        </div>
      </div>
      {children && <div className="btn-reihe">{children}</div>}
    </header>
  );
}
