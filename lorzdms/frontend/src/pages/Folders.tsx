import { useState } from "react";
import { api, Folder } from "../api";
import { t } from "../i18n";
import FolderPicker from "../components/FolderPicker";
import { ErrorBox, Field, Notice, Section, useAction, useApi } from "../ui";

const ROLES: Record<string, string> = {
  archive_root: "Archiv (Wurzel)",
  archive: "Ablageziel",
  inbox: "Eingang (nur lesen/verschieben)",
  review: "Manuelle Prüfung",
};

export default function Folders() {
  const folders = useApi<Folder[]>("folders");
  const accounts = useApi<{ accounts: { id: number; email: string }[] }>("google/status");
  const [account, setAccount] = useState<number | null>(null);
  const [role, setRole] = useState("archive_root");
  const [importSubs, setImportSubs] = useState(true);
  const act = useAction();
  const acc = account ?? accounts.data?.accounts[0]?.id ?? null;
  const add = (id: string) =>
    act.run(async () => {
      await api.send("POST", "folders", { account_id: acc, drive_id: id, role, import_subfolders: importSubs });
      folders.reload();
    });
  const describe = (f: Folder) => {
    const d = window.prompt("Beschreibung für die Klassifizierung (z. B. 'Rechnungen von Hosting-Anbietern')", f.description ?? "");
    if (d !== null) act.run(async () => { await api.send("PATCH", `folders/${f.id}`, { description: d }); folders.reload(); });
  };
  return (
    <>
      <h1 className="h1">{t("folders")}</h1>
      <Notice>
        LorzDMS schreibt ausschließlich in freigegebene Archiv- und Prüfordner. Eingangsordner werden nur gelesen; Dateien daraus werden nach
        erfolgreicher Ablage verschoben (die Drive-Datei-ID bleibt erhalten). Gelöscht wird nie.
      </Notice>
      <ErrorBox error={folders.error || act.error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Freigegebene Ordner">
          <table className="tbl">
            <thead><tr><th>Pfad</th><th>Rolle</th><th /></tr></thead>
            <tbody>
              {(folders.data ?? []).map((f) => (
                <tr key={f.id}>
                  <td>
                    <div>{f.path}</div>
                    {f.description && <div className="text-xs muted">{f.description}</div>}
                  </td>
                  <td className="whitespace-nowrap text-xs">{ROLES[f.role] ?? f.role}</td>
                  <td className="whitespace-nowrap text-right">
                    <button className="btn mr-1" onClick={() => describe(f)}>Beschreibung</button>
                    <button className="btn btn-danger" onClick={() => act.run(async () => { await api.send("DELETE", `folders/${f.id}`); folders.reload(); })}>{t("remove")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {folders.data?.length === 0 && <p className="text-sm muted">{t("empty")}</p>}
        </Section>
        <Section title="Ordner freigeben">
          {!accounts.data?.accounts.length ? (
            <p className="text-sm muted">Zuerst unter „Einrichtung“ ein Google-Konto verbinden.</p>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Konto">
                  <select className="input" value={acc ?? ""} onChange={(e) => setAccount(Number(e.target.value))}>
                    {accounts.data.accounts.map((a) => <option key={a.id} value={a.id}>{a.email}</option>)}
                  </select>
                </Field>
                <Field label="Rolle">
                  <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                    {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </Field>
              </div>
              {(role === "archive_root" || role === "archive") && (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={importSubs} onChange={(e) => setImportSubs(e.target.checked)} />
                  Bestehende Unterordner als Ablageziele übernehmen (nur lesend)
                </label>
              )}
              {acc && <FolderPicker accountId={acc} onPick={(id) => add(id)} />}
            </div>
          )}
        </Section>
      </div>
    </>
  );
}
