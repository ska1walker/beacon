"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { OrgSettings } from "@/lib/typen";
import { Fehler } from "@/components/zustaende";
import { Erklaerung } from "@/components/erklaerung";

/** Der Postausgang — Marcs Relay oder jeder Dienst, der den Vertrag bedient. */
export function Postausgangblock() {
  const client = useQueryClient();
  const einst = useQuery({ queryKey: ["einstellungen"], queryFn: () => api.get<OrgSettings>("/api/settings") });
  const [url, setUrl] = useState(""); const [absender, setAbsender] = useState(""); const [geheim, setGeheim] = useState("");
  useEffect(() => { if (einst.data) { setUrl(einst.data.mail_endpoint_url ?? ""); setAbsender(einst.data.mail_absender ?? ""); } }, [einst.data]);
  const speichern = useMutation({
    mutationFn: () => api.put("/api/settings", { mail_endpoint_url: url, mail_absender: absender, mail_endpoint_secret: geheim }),
    onSuccess: () => { setGeheim(""); client.invalidateQueries({ queryKey: ["einstellungen"] }); client.invalidateQueries({ queryKey: ["post-status"] }); },
  });
  return (
    <section className="block">
      <div className="block-kopf">
        <h2>Versand über Relay</h2>
        <span className="stufe" data-art={einst.data?.mail_endpoint_url ? "won" : undefined}>{einst.data?.mail_endpoint_url ? "eingerichtet" : "nicht eingerichtet"}</span>
      </div>
      <div className="block-inhalt">
        <Erklaerung kurz="Optional: E-Mails über Relay statt über das eigene E-Mail-Konto verschicken." lang={<>E-Mails gehen nicht aus Beacon selbst hinaus, sondern an einen Dienst auf der Box — Relay, die Outlook-Alternative.
          Beacon schickt je Nachricht einen signierten POST mit <code>to</code>, <code>subject</code>, <code>text</code>; eingehende Mails
          nimmt es unter <code>/api/post/eingang/&lt;Quelle&gt;</code> entgegen (Quelle unter „Eingehende Quellen" anlegen).
          Der Vertrag steht in <code>backend/app/routers/post.py</code>.</>} />
        <form onSubmit={(e) => { e.preventDefault(); speichern.mutate(); }}>
          <div className="feld"><label htmlFor="po-url">Adresse des Postausgangs</label><input id="po-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://relay-…olares.com/api/send" /></div>
          <div className="feld"><label htmlFor="po-von">Absenderadresse</label><input id="po-von" type="email" value={absender} onChange={(e) => setAbsender(e.target.value)} placeholder="kai@aimighty.de" /></div>
          <div className="feld"><label htmlFor="po-geheim">Geheimnis für die Signatur</label><input id="po-geheim" type="password" autoComplete="off" value={geheim} onChange={(e) => setGeheim(e.target.value)} placeholder={einst.data?.mail_endpoint_secret_set ? "hinterlegt — leer lassen, um es zu behalten" : "keines hinterlegt"} /></div>
          {speichern.isError && <Fehler text={(speichern.error as Error).message} />}
          <div className="btn-reihe"><button type="submit" className="btn btn-primaer" disabled={speichern.isPending}>Speichern</button>{speichern.isSuccess && <span style={{ fontSize: "0.8125rem", color: "var(--am-erfolg)" }}>Gespeichert.</span>}</div>
        </form>
      </div>
    </section>
  );
}
