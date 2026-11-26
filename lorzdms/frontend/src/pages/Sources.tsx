import { useState } from "react";
import { api } from "../api";
import { fmtDate, t } from "../i18n";
import FolderPicker from "../components/FolderPicker";
import { ErrorBox, Field, Notice, Section, useAction, useApi } from "../ui";

type Source = { id: number; kind: string; name: string; account_id: number | null; config: Record<string, unknown>; enabled: number; poll_interval_seconds: number; last_sync_at: string | null; last_status: string | null; last_error: string | null };

export default function Sources() {
  const sources = useApi<Source[]>("sources");
  const accounts = useApi<{ accounts: { id: number; email: string; scopes: string }[] }>("google/status");
  const [kind, setKind] = useState<"gmail" | "drive">("gmail");
  const [name, setName] = useState("");
  const [account, setAccount] = useState<number | null>(null);
  const [query, setQuery] = useState("has:attachment filename:pdf newer_than:14d");
  const [interval, setIntervalS] = useState(300);
  const [folder, setFolder] = useState<{ id: string; path: string } | null>(null);
  const [recursive, setRecursive] = useState(false);
  const [images, setImages] = useState(false);
  const act = useAction();
  const acc = account ?? accounts.data?.accounts[0]?.id ?? null;

  const create = () =>
    act.run(async () => {
      const config = kind === "gmail"
        ? { query, extensions: images ? [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"] : [".pdf"] }
        : { folder_ids: folder ? [folder.id] : [], recursive };
      await api.send("POST", "sources", { kind, name: name || (kind === "gmail" ? "Gmail" : `Drive: ${folder?.path ?? ""}`), account_id: acc, config, poll_interval_seconds: interval });
      sources.reload();
    });
  const toggle = (s: Source) => act.run(async () => { await api.send("PATCH", `sources/${s.id}`, { enabled: !s.enabled }); sources.reload(); });
  const sync = (s: Source) => act.run(async () => { await api.send("POST", `sources/${s.id}/sync`); });

  return (
    <>
      <h1 className="h1">{t("sources")}</h1>
      <Notice>Gmail wird ausschließlich lesend angebunden (Berechtigung gmail.readonly). Nachrichten und Anhänge werden nie verändert, verschoben oder gelöscht. Ein bereits bestehender Gmail-Import kann parallel weiterlaufen; Duplikate werden per Prüfsumme erkannt.</Notice>
      <ErrorBox error={sources.error || act.error} />
      <Section title="Aktive Quellen">
        <table className="tbl">
          <thead><tr><th>Name</th><th>Typ</th><th>{t("last_sync")}</th><th>{t("status")}</th><th /></tr></thead>
          <tbody>
            {(sources.data ?? []).map((s) => (
              <tr key={s.id}>
                <td>{s.name}<div className="text-xs muted">{s.kind === "gmail" ? String(s.config.query ?? "") : s.kind === "drive" ? `${(s.config.folder_ids as string[] | undefined)?.length ?? 0} Ordner` : ""}</div></td>
                <td>{s.kind}</td>
                <td className="whitespace-nowrap">{fmtDate(s.last_sync_at)}</td>
                <td>{s.enabled ? s.last_status ?? "–" : "deaktiviert"}{s.last_error && <div className="text-xs text-red-600">{s.last_error}</div>}</td>
                <td className="whitespace-nowrap text-right">
                  <button className="btn mr-1" onClick={() => sync(s)}>{t("sync_now")}</button>
                  {s.kind !== "upload" && <button className="btn" onClick={() => toggle(s)}>{s.enabled ? "Deaktivieren" : "Aktivieren"}</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Quelle hinzufügen">
        {!accounts.data?.accounts.length ? (
          <p className="text-sm muted">Zuerst unter „Einrichtung“ ein Google-Konto verbinden.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Typ">
                  <select className="input" value={kind} onChange={(e) => setKind(e.target.value as "gmail" | "drive")}>
                    <option value="gmail">Gmail (lesend)</option>
                    <option value="drive">Google-Drive-Eingangsordner</option>
                  </select>
                </Field>
                <Field label="Konto">
                  <select className="input" value={acc ?? ""} onChange={(e) => setAccount(Number(e.target.value))}>
                    {accounts.data.accounts.map((a) => <option key={a.id} value={a.id}>{a.email}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Abfrageintervall (Sekunden)"><input className="input" type="number" min={60} value={interval} onChange={(e) => setIntervalS(Number(e.target.value))} /></Field>
              {kind === "gmail" ? (
                <>
                  <Field label="Gmail-Suchfilter (Erstimport und Vollabgleich)"><input className="input" value={query} onChange={(e) => setQuery(e.target.value)} /></Field>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={images} onChange={(e) => setImages(e.target.checked)} /> Auch Bildanhänge (JPG/PNG/TIFF) importieren</label>
                </>
              ) : (
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} /> Unterordner einbeziehen</label>
              )}
              <button className="btn btn-primary" disabled={act.busy || (kind === "drive" && !folder)} onClick={create}>{t("add")}</button>
            </div>
            {kind === "drive" && acc && (
              <div>
                <div className="label">Eingangsordner: {folder?.path ?? "noch nicht gewählt"}</div>
                <FolderPicker accountId={acc} onPick={(id, path) => setFolder({ id, path })} />
              </div>
            )}
          </div>
        )}
      </Section>
    </>
  );
}
