import { useEffect, useState } from "react";
import { api, Doc, Folder, Me } from "../api";
import { fmtDate, t } from "../i18n";
import { ErrorBox, Field, Notice, StateBadge, useAction, useApi } from "../ui";
import { CaseAssign, DeadlineForm, DeadlineTable, TagEditor } from "./Organize";

type Journal = { id: number; ts: string; step: string; status: string; message: string; data: Record<string, unknown> | null };

export default function DocDetail({ id, me, onDone }: { id: number; me: Me; onDone?: () => void }) {
  const doc = useApi<Doc>(`documents/${id}`, [id]);
  const text = useApi<{ text: string; method: string | null }>(`documents/${id}/text`, [id]);
  const journal = useApi<Journal[]>(`documents/${id}/journal`, [id]);
  const folders = useApi<Folder[]>("folders");
  const [tab, setTab] = useState<"preview" | "text" | "journal">("preview");
  const [form, setForm] = useState({ folder: "", filename: "", document_type: "", sender: "", document_date: "", title: "" });
  const act = useAction();

  useEffect(() => {
    const d = doc.data;
    if (!d) return;
    setForm({
      folder: d.target_folder_drive_id ?? "",
      filename: d.target_name ?? "",
      document_type: d.document_type ?? "",
      sender: d.sender ?? "",
      document_date: d.document_date ?? "",
      title: d.title ?? "",
    });
  }, [doc.data]);

  if (doc.error) return <ErrorBox error={doc.error} />;
  const d = doc.data;
  if (!d) return <p className="text-sm muted">…</p>;
  const canEdit = me.role === "admin" || me.role === "editor";
  const reviewable = ["needs_review", "observed", "analyzed"].includes(d.state);
  const targets = (folders.data ?? []).filter((f) => f.role === "archive" || f.role === "archive_root" || f.role === "review");
  const dec = d.decision;

  const approve = () =>
    act.run(async () => {
      const corrections: Record<string, string> = {};
      for (const k of ["document_type", "sender", "document_date", "title"] as const) {
        const v = form[k].trim();
        if (v !== ((d[k] as string | null) ?? "")) corrections[k] = v;
      }
      await api.send("POST", `documents/${id}/approve`, {
        folder_drive_id: form.folder || null,
        filename: form.filename !== d.target_name ? form.filename : null,
        corrections: Object.keys(corrections).length ? corrections : null,
      });
      doc.reload();
      onDone?.();
    });
  const simple = (path: string) =>
    act.run(async () => {
      await api.send("POST", `documents/${id}/${path}`);
      doc.reload();
      journal.reload();
      onDone?.();
    });

  return (
    <div className="grid gap-4 xl:grid-cols-5">
      <div className="panel xl:col-span-3">
        <div className="flex gap-1 border-b border-slate-200 px-2 pt-2 dark:border-slate-800">
          {(["preview", "text", "journal"] as const).map((k) => (
            <button key={k} onClick={() => setTab(k)} className={`rounded-t px-3 py-1.5 text-sm ${tab === k ? "bg-slate-100 font-medium dark:bg-slate-800" : "muted"}`}>
              {t(k)}
            </button>
          ))}
        </div>
        <div className="h-[70vh]">
          {tab === "preview" && (d.mime_type === "application/pdf" || d.mime_type?.startsWith("image/") ? (
            <div className="h-full space-y-3 overflow-auto bg-slate-100 p-3 dark:bg-slate-950">
              {Array.from({ length: Math.min(d.page_count ?? 1, 30) }, (_, i) => (
                <img key={i} loading="lazy" alt={`Seite ${i + 1}`} className="mx-auto w-full max-w-3xl bg-white shadow" src={`api/documents/${id}/pages/${i + 1}.png`} />
              ))}
              {(d.page_count ?? 1) > 30 && <p className="text-center text-xs muted">Weitere Seiten im Download.</p>}
              <p className="text-center text-xs"><a className="text-brand-600 underline" href={`api/documents/${id}/file`} target="_blank" rel="noreferrer noopener">Original im Browser öffnen</a></p>
            </div>
          ) : (
            <p className="p-4 text-sm muted">Keine Vorschau verfügbar.</p>
          ))}
          {tab === "text" && (
            <pre className="h-full overflow-auto whitespace-pre-wrap p-4 font-mono text-xs">{text.data?.text || "(kein Text)"}</pre>
          )}
          {tab === "journal" && (
            <ul className="h-full space-y-1 overflow-auto p-4 text-xs">
              {(journal.data ?? []).map((j) => (
                <li key={j.id} className="flex gap-2">
                  <span className="whitespace-nowrap muted">{fmtDate(j.ts)}</span>
                  <span className={j.status === "error" ? "text-red-600" : j.status === "warn" ? "text-amber-600" : ""}>
                    [{j.step}] {j.message}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="space-y-3 xl:col-span-2">
        <div className="panel space-y-2 p-4 text-sm">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 font-medium break-words">{d.original_filename}</div>
            <StateBadge state={d.state} />
          </div>
          <div className="text-xs muted">
            #{d.id} · Quelle: {d.source_kind} · {d.page_count ?? "?"} Seite(n){d.ocr_used ? " · OCR" : ""} · {fmtDate(d.created_at)}
          </div>
          {d.email_meta && (
            <div className="text-xs muted">E-Mail: {String(d.email_meta.from_email ?? "")} – {String(d.email_meta.subject ?? "")}</div>
          )}
          {d.error && <ErrorBox error={d.error} />}
          {d.duplicate_of && <Notice tone="warn">Identische Datei bereits als Dokument #{d.duplicate_of} vorhanden.</Notice>}
          {d.drive_web_link && (
            <a className="text-brand-600 underline" href={d.drive_web_link} target="_blank" rel="noreferrer noopener">{t("open_in_drive")}</a>
          )}{" "}
          <a className="text-brand-600 underline" href={`api/documents/${id}/file?download=true`}>{t("download")}</a>
        </div>
        {dec && (dec.review_reasons?.length || dec.rules?.length || dec.ai) ? (
          <div className="panel space-y-1 p-4 text-sm">
            <div className="h2">Begründung</div>
            {dec.rules?.length ? <div>Regeln: {dec.rules.map((r) => r.name).join(", ")}</div> : null}
            {dec.ai?.reasoning && <div>KI ({dec.ai.model}): {dec.ai.reasoning}</div>}
            <div>Konfidenz: {d.confidence != null ? `${Math.round(d.confidence * 100)} %` : "–"}</div>
            {dec.review_reasons?.map((r, i) => <div key={i} className="text-amber-700 dark:text-amber-400">• {r}</div>)}
            {dec.ai?.uncertainties?.map((r, i) => <div key={`u${i}`} className="muted">? {r}</div>)}
          </div>
        ) : null}
        <div className="panel space-y-2 p-4">
          <div className="h2">{t("deadlines")}</div>
          <DeadlineTable items={d.deadlines ?? []} canEdit={canEdit} onChange={doc.reload} showDoc={false} compact />
          {canEdit && <DeadlineForm documentId={id} onSaved={doc.reload} compact />}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <div className="panel space-y-2 p-4">
            <div className="h2">{t("cases")}</div>
            <CaseAssign docId={id} cases={d.cases ?? []} canEdit={canEdit} onChange={doc.reload} />
          </div>
          <div className="panel space-y-2 p-4">
            <div className="h2">{t("tags")}</div>
            <TagEditor docId={id} tags={d.tags ?? []} canEdit={canEdit} onSaved={(tags) => doc.setData({ ...d, tags })} />
          </div>
        </div>
        <div className="panel space-y-3 p-4">
          <div className="h2">{t("metadata")}</div>
          <Field label={t("folder")}>
            <select className="input" value={form.folder} disabled={!canEdit} onChange={(e) => setForm({ ...form, folder: e.target.value })}>
              <option value="">– wählen –</option>
              {targets.map((f) => <option key={f.id} value={f.drive_id}>{f.path}</option>)}
            </select>
          </Field>
          <Field label={t("filename")}>
            <input className="input" value={form.filename} disabled={!canEdit} onChange={(e) => setForm({ ...form, filename: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label={t("type")}><input className="input" value={form.document_type} disabled={!canEdit} onChange={(e) => setForm({ ...form, document_type: e.target.value })} /></Field>
            <Field label={t("date")}><input className="input" type="date" value={form.document_date} disabled={!canEdit} onChange={(e) => setForm({ ...form, document_date: e.target.value })} /></Field>
          </div>
          <Field label={t("sender")}><input className="input" value={form.sender} disabled={!canEdit} onChange={(e) => setForm({ ...form, sender: e.target.value })} /></Field>
          <Field label={t("title")}><input className="input" value={form.title} disabled={!canEdit} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          <ErrorBox error={act.error} />
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              {reviewable && <button className="btn btn-primary" disabled={act.busy} onClick={approve}>{t("confirm")}</button>}
              {["needs_review", "observed", "excluded", "duplicate", "failed"].includes(d.state) && (
                <button className="btn" disabled={act.busy} onClick={() => simple("reprocess")}>{t("reanalyze")}</button>
              )}
              {reviewable && <button className="btn" disabled={act.busy} onClick={() => simple("skip")}>{t("skip")}</button>}
              {d.state === "done" && <button className="btn btn-danger" disabled={act.busy} onClick={() => simple("undo")}>{t("undo")}</button>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
