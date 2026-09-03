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
        <h1>{titel}</h1>
        {zahl && <div className="seitenkopf-zahl">{zahl}</div>}
      </div>
      {children && <div className="btn-reihe">{children}</div>}
    </header>
  );
}
