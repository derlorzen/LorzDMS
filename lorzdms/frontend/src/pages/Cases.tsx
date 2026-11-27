import { useEffect, useState } from "react";
import { api, Case, Me } from "../api";
import { fmtDate, fmtDay, t } from "../i18n";
import { DeadlineForm, DeadlineTable } from "../components/Organize";
import { ErrorBox, Field, Notice, Section, StateBadge, useAction, useApi } from "../ui";

export default function Cases({ id, go, me }: { id?: number; go: (to: string) => void; me: Me }) {
  if (id) return <CaseDetail id={id} go={go} me={me} />;
  return <CaseList go={go} me={me} />;
}

function CaseList({ go, me }: { go: (to: string) => void; me: Me }) {
  const [status, setStatus] = useState("open");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const list = useApi<{ items: Case[] }>(`cases?status=${status}${query ? `&q=${encodeURIComponent(query)}` : ""}`, [status, query]);
  const [f, setF] = useState({ title: "", reference: "", description: "" });
  const act = useAction();
  const canEdit = me.role === "admin" || me.role === "editor";
  const create = (e: React.FormEvent) => {
    e.preventDefault();
    act.run(async () => {
      const c = await api.send<Case>("POST", "cases", { title: f.title, reference: f.reference || null, description: f.description || null });
      go(`cases/${c.id}`);
    });
  };
  return (
    <>
      <h1 className="h1">{t("cases")}</h1>
      <p className="text-sm muted">
        Ein Vorgang bündelt zusammengehörige Dokumente und Fristen, z. B. einen Antrag mit Bescheid, Widerspruch und Antwort.
        Tragen Sie eine Referenz (Aktenzeichen, Vertrags-, Versicherungs- oder Kundennummer) ein, ordnet LorzDMS neue Dokumente mit genau dieser Nummer automatisch zu.
      </p>
      <ErrorBox error={list.error} />
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input className="input max-w-sm" placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input !w-40" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("status")}>
          <option value="open">{t("open")}</option>
          <option value="closed">abgeschlossen</option>
          <option value="all">{t("all")}</option>
        </select>
        <button className="btn">{t("search").replace(" …", "")}</button>
      </form>
      <div className="panel overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr><th>{t("title")}</th><th>{t("reference")}</th><th>{t("documents")}</th><th>Nächste Frist</th><th>Geändert</th></tr>
          </thead>
          <tbody>
            {(list.data?.items ?? []).map((c) => (
              <tr key={c.id} className={`clickable ${c.status === "closed" ? "opacity-60" : ""}`} onClick={() => go(`cases/${c.id}`)}>
                <td className="max-w-xs truncate font-medium">{c.title}</td>
                <td className="whitespace-nowrap">{c.reference ?? "–"}</td>
                <td>{c.document_count}</td>
                <td className="whitespace-nowrap">{c.next_due ? `${fmtDay(c.next_due)} (${c.open_deadlines})` : "–"}</td>
                <td className="whitespace-nowrap muted">{fmtDate(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data?.items.length === 0 && <p className="p-4 text-sm muted">{t("empty")}</p>}
      </div>
      {canEdit && (
        <Section title={t("new_case")}>
          <form onSubmit={create} className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label={t("title")}><input className="input" required maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
              <Field label={`${t("reference")} (optional)`}><input className="input" maxLength={120} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} placeholder="z. B. PK-4711/26" /></Field>
            </div>
            <Field label={`${t("description")} (optional)`}><textarea className="input" rows={2} maxLength={4000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
            <ErrorBox error={act.error} />
            <button className="btn btn-primary" disabled={act.busy || !f.title.trim()}>{t("add")}</button>
          </form>
        </Section>
      )}
    </>
  );
}

function CaseDetail({ id, go, me }: { id: number; go: (to: string) => void; me: Me }) {
  const c = useApi<Case>(`cases/${id}`, [id]);
  const [f, setF] = useState({ title: "", reference: "", description: "" });
  const act = useAction();
  const canEdit = me.role === "admin" || me.role === "editor";
  useEffect(() => {
    if (c.data) setF({ title: c.data.title, reference: c.data.reference ?? "", description: c.data.description ?? "" });
  }, [c.data]);
  if (c.error) return <><button className="btn" onClick={() => go("cases")}>← {t("cases")}</button><ErrorBox error={c.error} /></>;
  const d = c.data;
  if (!d) return <p className="text-sm muted">…</p>;
  const patch = (body: Record<string, unknown>) => act.run(async () => { c.setData(await api.send<Case>("PATCH", `cases/${id}`, body)); });
  const remove = () => {
    if (!window.confirm(`Vorgang „${d.title}“ löschen? Die Dokumente bleiben erhalten, nur die Zuordnung entfällt.`)) return;
    act.run(async () => { await api.send("DELETE", `cases/${id}`); go("cases"); });
  };
  const unlink = (docId: number) => act.run(async () => { await api.send("DELETE", `cases/${id}/documents/${docId}`); c.reload(); });
  return (
    <>
      <button className="btn" onClick={() => go("cases")}>← {t("cases")}</button>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="h1">{d.title}</h1>
        {d.status === "closed" && <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs dark:bg-slate-800">abgeschlossen {fmtDate(d.closed_at)}</span>}
      </div>
      {d.description && <p className="whitespace-pre-wrap text-sm">{d.description}</p>}
      <ErrorBox error={act.error} />
      <Section title={`${t("deadlines")} (${d.open_deadlines} offen)`}>
        <DeadlineTable items={d.deadlines ?? []} canEdit={canEdit} onChange={c.reload} go={go} />
        {canEdit && <div className="mt-3"><DeadlineForm caseId={id} onSaved={c.reload} /></div>}
      </Section>
      <Section title={`${t("documents")} (${d.document_count})`}>
        {(d.documents ?? []).length === 0 ? (
          <p className="text-sm muted">Noch keine Dokumente. Ordnen Sie Dokumente in der Dokumentansicht diesem Vorgang zu.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Datei</th><th>{t("type")}</th><th>{t("date")}</th><th>{t("status")}</th><th></th></tr></thead>
              <tbody>
                {(d.documents ?? []).map((doc) => (
                  <tr key={doc.id} className="clickable" onClick={() => go(`documents/${doc.id}`)}>
                    <td className="max-w-xs truncate">{doc.title || doc.target_name || doc.original_filename}</td>
                    <td>{doc.document_type ?? "–"}</td>
                    <td className="whitespace-nowrap">{doc.document_date ?? "–"}</td>
                    <td><StateBadge state={doc.state} /></td>
                    <td className="whitespace-nowrap text-right text-xs muted">
                      {doc.link_source === "auto" && "automatisch "}
                      {canEdit && <button className="btn !px-2 !py-0.5 text-xs" onClick={(e) => { e.stopPropagation(); unlink(doc.id); }}>{t("remove")}</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {canEdit && (
        <Section title={t("metadata")}>
          <div className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label={t("title")}><input className="input" maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
              <Field label={t("reference")}><input className="input" maxLength={120} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
            </div>
            <Field label={t("description")}><textarea className="input" rows={3} maxLength={4000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
            {d.reference && <Notice>Neue Dokumente mit der Referenz „{d.reference}“ werden automatisch zugeordnet, solange der Vorgang offen ist.</Notice>}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" disabled={act.busy || !f.title.trim()} onClick={() => patch({ title: f.title, reference: f.reference || null, description: f.description || null })}>{t("save")}</button>
              {d.status === "open"
                ? <button className="btn" disabled={act.busy} onClick={() => patch({ status: "closed" })}>{t("close_case")}</button>
                : <button className="btn" disabled={act.busy} onClick={() => patch({ status: "open" })}>{t("reopen")}</button>}
              {me.role === "admin" && <button className="btn btn-danger" disabled={act.busy} onClick={remove}>Vorgang löschen</button>}
            </div>
          </div>
        </Section>
      )}
    </>
  );
}
