import { useState } from "react";
import { api, Folder, Me } from "../api";
import { t } from "../i18n";
import { ErrorBox, Field, Notice, Section, useAction, useApi } from "../ui";

type Rule = { id: number; name: string; priority: number; enabled: boolean; conditions: unknown; actions: Record<string, unknown>; stop_processing: boolean };

const EXAMPLE_COND = { all: [{ field: "sender_domain", op: "equals", value: "beispiel.de" }, { field: "text", op: "contains", value: "Rechnung" }] };

export default function Rules({ me }: { me: Me }) {
  const rules = useApi<Rule[]>("rules");
  const folders = useApi<Folder[]>("folders");
  const [edit, setEdit] = useState<Partial<Rule> & { condText: string; actText: string } | null>(null);
  const [test, setTest] = useState<string | null>(null);
  const act = useAction();
  const isAdmin = me.role === "admin";
  const startNew = () => setEdit({ name: "", priority: 100, enabled: true, stop_processing: true, condText: JSON.stringify(EXAMPLE_COND, null, 2), actText: JSON.stringify({ folder_drive_id: "", document_type: "Rechnung", tags: [] }, null, 2) });
  const parse = () => {
    if (!edit) throw new Error("");
    return { name: edit.name, priority: edit.priority ?? 100, enabled: edit.enabled ?? true, stop_processing: edit.stop_processing ?? true, conditions: JSON.parse(edit.condText), actions: JSON.parse(edit.actText) };
  };
  const save = () => act.run(async () => {
    const body = parse();
    if (edit?.id) await api.send("PUT", `rules/${edit.id}`, body); else await api.send("POST", "rules", body);
    setEdit(null);
    rules.reload();
  });
  const runTest = () => act.run(async () => {
    const r = await api.send<{ tested: number; matches: { id: number; filename: string }[] }>("POST", "rules/test", parse());
    setTest(`${r.matches.length} von ${r.tested} vorhandenen Dokumenten würden passen${r.matches.length ? ": " + r.matches.slice(0, 8).map((m) => m.filename).join(", ") : ""}`);
  });
  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="h1">{t("rules")}</h1>
        {isAdmin && <button className="btn btn-primary" onClick={startNew}>Neue Regel</button>}
      </div>
      <Notice>Regeln werden nach Priorität (kleinste Zahl zuerst) geprüft und haben Vorrang vor KI-Vorschlägen. Felder: filename, text, subject, sender_email, sender_domain, sender_name, source_kind, source_name, document_type, sender, mime_type, tags. Operatoren: equals, not_equals, contains, not_contains, starts_with, ends_with, regex, in, exists, gte, lte. Aktionen: folder_drive_id, document_type, sender, tags, filename_template, review, exclude, visibility. Ein grafischer Regel-Editor ist noch nicht umgesetzt.</Notice>
      <ErrorBox error={rules.error || act.error} />
      {edit && (
        <Section title={edit.id ? "Regel bearbeiten" : "Neue Regel"} actions={<button className="btn" onClick={() => setEdit(null)}>{t("cancel")}</button>}>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Name"><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Priorität"><input className="input" type="number" value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: Number(e.target.value) })} /></Field>
              <label className="mt-5 flex items-center gap-2 text-sm"><input type="checkbox" checked={edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} /> aktiv</label>
            </div>
            <Field label="Bedingungen (JSON)"><textarea className="input h-56 font-mono text-xs" value={edit.condText} onChange={(e) => setEdit({ ...edit, condText: e.target.value })} /></Field>
            <div>
              <Field label="Aktionen (JSON)"><textarea className="input h-40 font-mono text-xs" value={edit.actText} onChange={(e) => setEdit({ ...edit, actText: e.target.value })} /></Field>
              <div className="mt-2 text-xs muted">Ordner-IDs:</div>
              <ul className="max-h-24 overflow-auto text-xs">
                {(folders.data ?? []).filter((f) => f.role !== "inbox").map((f) => <li key={f.id}><code>{f.drive_id}</code> {f.path}</li>)}
              </ul>
            </div>
          </div>
          {test && <div className="mt-3"><Notice>{test}</Notice></div>}
          <div className="mt-3 flex gap-2">
            <button className="btn" onClick={runTest} disabled={act.busy}>Testlauf</button>
            <button className="btn btn-primary" onClick={save} disabled={act.busy}>{t("save")}</button>
          </div>
        </Section>
      )}
      <div className="panel overflow-x-auto">
        <table className="tbl">
          <thead><tr><th>Prio</th><th>Name</th><th>Aktionen</th><th>{t("status")}</th><th /></tr></thead>
          <tbody>
            {(rules.data ?? []).map((r) => (
              <tr key={r.id}>
                <td>{r.priority}</td>
                <td>{r.name}</td>
                <td className="font-mono text-xs">{JSON.stringify(r.actions)}</td>
                <td>{r.enabled ? "aktiv" : "aus"}</td>
                <td className="whitespace-nowrap text-right">
                  {isAdmin && <>
                    <button className="btn mr-1" onClick={() => setEdit({ ...r, condText: JSON.stringify(r.conditions, null, 2), actText: JSON.stringify(r.actions, null, 2) })}>Bearbeiten</button>
                    <button className="btn btn-danger" onClick={() => window.confirm("Regel löschen?") && act.run(async () => { await api.send("DELETE", `rules/${r.id}`); rules.reload(); })}>{t("remove")}</button>
                  </>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rules.data?.length === 0 && <p className="p-4 text-sm muted">{t("empty")}</p>}
      </div>
    </>
  );
}
