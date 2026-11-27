import { useState } from "react";
import { api, Case, CaseLink, Deadline, DeadlineKind, TagCount } from "../api";
import { fmtDay, t } from "../i18n";
import { ErrorBox, useAction, useApi } from "../ui";

export const KIND_LABEL: Record<DeadlineKind, string> = {
  payment: "Zahlung", cancellation: "Kündigung", objection: "Widerspruch", response: "Antwort",
  appointment: "Termin", resubmission: "Wiedervorlage", other: "Sonstige Frist",
};

export function DueBadge({ d }: { d: Deadline }) {
  if (d.status === "done") return <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">{t("done")}</span>;
  if (d.status === "dismissed") return <span className="rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">verworfen</span>;
  const n = d.days_left;
  const cls = n < 0 ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
    : n <= 7 ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
    : "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300";
  const label = n < 0 ? `${-n} T überfällig` : n === 0 ? "heute" : n === 1 ? "morgen" : `in ${n} T`;
  return <span className={`whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{label}</span>;
}

export function DeadlineTable({ items, canEdit, onChange, go, showDoc = true, compact = false }: {
  items: Deadline[]; canEdit: boolean; onChange: () => void; go?: (to: string) => void; showDoc?: boolean; compact?: boolean;
}) {
  const act = useAction();
  const set = (d: Deadline, status: string) => act.run(async () => { await api.send("PATCH", `deadlines/${d.id}`, { status }); onChange(); });
  const del = (d: Deadline) => act.run(async () => { await api.send("DELETE", `deadlines/${d.id}`); onChange(); });
  if (!items.length) return <p className="text-sm muted">{t("empty")}</p>;
  const buttons = (d: Deadline) =>
    d.status === "open" ? (
      <>
        <button className="btn btn-primary !px-2 !py-0.5 text-xs" disabled={act.busy} onClick={() => set(d, "done")}>{t("done")}</button>{" "}
        <button className="btn !px-2 !py-0.5 text-xs" disabled={act.busy} onClick={() => (d.source === "document" ? set(d, "dismissed") : del(d))}>
          {d.source === "document" ? t("dismiss") : t("remove")}
        </button>
      </>
    ) : (
      <button className="btn !px-2 !py-0.5 text-xs" disabled={act.busy} onClick={() => set(d, "open")}>{t("reopen")}</button>
    );
  const origin = (d: Deadline) =>
    d.source === "document" && (
      <div className="text-xs muted" title={d.quote ?? undefined}>
        aus Dokument erkannt{d.explicit === 0 ? " (berechnet, bitte prüfen)" : ""}{d.quote ? ` · „${d.quote.slice(0, 80)}“` : ""}
      </div>
    );
  if (compact)
    return (
      <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
        <ErrorBox error={act.error} />
        {items.map((d) => (
          <li key={d.id} className={`space-y-1 py-2 ${d.status !== "open" ? "opacity-60" : ""}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="whitespace-nowrap font-medium">{fmtDay(d.due_date)}</span>
              <DueBadge d={d} />
              <span className="text-xs muted">{KIND_LABEL[d.kind] ?? d.kind}</span>
            </div>
            <div className="break-words">{d.title}</div>
            {origin(d)}
            {canEdit && <div>{buttons(d)}</div>}
          </li>
        ))}
      </ul>
    );
  return (
    <div className="overflow-x-auto">
      <ErrorBox error={act.error} />
      <table className="tbl">
        <thead>
          <tr><th>{t("due")}</th><th></th><th>{t("title")}</th><th>{t("kind")}</th>{showDoc && <th>Dokument / Vorgang</th>}{canEdit && <th></th>}</tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.id} className={d.status !== "open" ? "opacity-60" : ""}>
              <td className="whitespace-nowrap">{fmtDay(d.due_date)}</td>
              <td><DueBadge d={d} /></td>
              <td className="max-w-xs">
                <div className="truncate">{d.title}</div>
                {origin(d)}
              </td>
              <td className="whitespace-nowrap">{KIND_LABEL[d.kind] ?? d.kind}</td>
              {showDoc && (
                <td className="max-w-[16rem] text-xs">
                  {d.document_id && (
                    <a className="block truncate text-brand-600 underline" href={`#/documents/${d.document_id}`} onClick={(e) => { if (go) { e.preventDefault(); go(`documents/${d.document_id}`); } }}>
                      {d.document_title || d.document_filename || `#${d.document_id}`}
                    </a>
                  )}
                  {d.case_id && <a className="block truncate muted underline" href={`#/cases/${d.case_id}`}>{d.case_title}</a>}
                </td>
              )}
              {canEdit && (
                <td className="whitespace-nowrap text-right">{buttons(d)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DeadlineForm({ documentId, caseId, onSaved, compact = false }: { documentId?: number; caseId?: number; onSaved: () => void; compact?: boolean }) {
  const [f, setF] = useState({ title: "", due_date: "", kind: "other" as DeadlineKind, remind_days: "" });
  const act = useAction();
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    act.run(async () => {
      await api.send("POST", "deadlines", {
        title: f.title, due_date: f.due_date, kind: f.kind,
        remind_days: f.remind_days === "" ? null : Number(f.remind_days),
        document_id: documentId ?? null, case_id: caseId ?? null,
      });
      setF({ title: "", due_date: "", kind: "other", remind_days: "" });
      onSaved();
    });
  };
  return (
    <form onSubmit={save} className="space-y-2">
      <div className={compact ? "grid grid-cols-2 gap-2" : "grid gap-2 sm:grid-cols-[1fr_10rem_10rem_7rem_auto]"}>
        <input className={`input ${compact ? "col-span-2" : ""}`} placeholder={t("title")} value={f.title} maxLength={200} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <input className="input" type="date" required value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} aria-label={t("due")} />
        <select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as DeadlineKind })} aria-label={t("kind")}>
          {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input className="input" type="number" min={0} max={365} placeholder="Vorlauf (Tage)" title={t("remind_days")} value={f.remind_days} onChange={(e) => setF({ ...f, remind_days: e.target.value })} />
        <button className="btn btn-primary" disabled={act.busy || !f.due_date}>{t("add")}</button>
      </div>
      <ErrorBox error={act.error} />
    </form>
  );
}

export function TagEditor({ docId, tags, canEdit, onSaved }: { docId: number; tags: string[]; canEdit: boolean; onSaved: (tags: string[]) => void }) {
  const [input, setInput] = useState("");
  const all = useApi<{ items: TagCount[] }>(canEdit ? "tags" : null);
  const act = useAction();
  const save = (next: string[]) => act.run(async () => {
    const r = await api.send<{ tags: string[] }>("PUT", `documents/${docId}/tags`, { tags: next });
    onSaved(r.tags);
    all.reload();
  });
  const add = (e?: React.FormEvent) => {
    e?.preventDefault();
    const v = input.trim();
    if (!v) return;
    setInput("");
    save([...tags, ...v.split(",").map((x) => x.trim()).filter(Boolean)]);
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {tags.length === 0 && <span className="text-xs muted">keine Tags</span>}
        {tags.map((tag) => (
          <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs text-brand-700 dark:bg-brand-700/30 dark:text-brand-100">
            <a href={`#/documents?tag=${encodeURIComponent(tag)}`} className="hover:underline">{tag}</a>
            {canEdit && <button type="button" aria-label={`${tag} entfernen`} className="opacity-60 hover:opacity-100" disabled={act.busy} onClick={() => save(tags.filter((x) => x !== tag))}>×</button>}
          </span>
        ))}
      </div>
      {canEdit && (
        <form onSubmit={add} className="flex gap-2">
          <input className="input" list={`tags-${docId}`} placeholder="Tag hinzufügen (Komma trennt)" maxLength={200} value={input} onChange={(e) => setInput(e.target.value)} />
          <datalist id={`tags-${docId}`}>{(all.data?.items ?? []).map((x) => <option key={x.tag} value={x.tag} />)}</datalist>
          <button className="btn" disabled={act.busy || !input.trim()}>{t("add")}</button>
        </form>
      )}
      <ErrorBox error={act.error} />
    </div>
  );
}

export function CaseAssign({ docId, cases, canEdit, onChange }: { docId: number; cases: CaseLink[]; canEdit: boolean; onChange: () => void }) {
  const open = useApi<{ items: Case[] }>(canEdit ? "cases?status=open" : null);
  const [pick, setPick] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const act = useAction();
  const linked = new Set(cases.map((c) => c.id));
  const link = () => act.run(async () => {
    if (pick === "new") {
      await api.send("POST", "cases", { title: newTitle.trim(), document_ids: [docId] });
      setNewTitle("");
      open.reload();
    } else {
      await api.send("POST", `cases/${pick}/documents`, { document_id: docId });
    }
    setPick("");
    onChange();
  });
  const unlink = (id: number) => act.run(async () => { await api.send("DELETE", `cases/${id}/documents/${docId}`); onChange(); });
  return (
    <div className="space-y-2 text-sm">
      {cases.length === 0 && <div className="text-xs muted">keinem Vorgang zugeordnet</div>}
      {cases.map((c) => (
        <div key={c.id} className="flex items-center justify-between gap-2">
          <a className="truncate text-brand-600 underline" href={`#/cases/${c.id}`}>{c.title}</a>
          <span className="flex shrink-0 items-center gap-2 text-xs muted">
            {c.source === "auto" && "automatisch"}
            {c.status === "closed" && "abgeschlossen"}
            {canEdit && <button className="btn !px-2 !py-0.5 text-xs" disabled={act.busy} onClick={() => unlink(c.id)}>{t("remove")}</button>}
          </span>
        </div>
      ))}
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <select className="input min-w-0 flex-1" value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Vorgang zuordnen …</option>
            {(open.data?.items ?? []).filter((c) => !linked.has(c.id)).map((c) => (
              <option key={c.id} value={c.id}>{c.title}{c.reference ? ` (${c.reference})` : ""}</option>
            ))}
            <option value="new">+ {t("new_case")}</option>
          </select>
          {pick === "new" && <input className="input min-w-0 flex-1" placeholder={t("title")} value={newTitle} maxLength={200} onChange={(e) => setNewTitle(e.target.value)} />}
          <button className="btn" disabled={act.busy || !pick || (pick === "new" && !newTitle.trim())} onClick={link}>{t("add")}</button>
        </div>
      )}
      <ErrorBox error={act.error} />
    </div>
  );
}
