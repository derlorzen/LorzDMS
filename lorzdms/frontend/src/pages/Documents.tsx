import { useEffect, useRef, useState } from "react";
import { api, Doc, Me, TagCount } from "../api";
import { fmtDate, t } from "../i18n";
import DocDetail from "../components/DocDetail";
import { ErrorBox, Notice, StateBadge, useAction, useApi } from "../ui";

export default function Documents({ id, go, me }: { id?: number; go: (to: string) => void; me: Me }) {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const hashTag = () => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("tag") ?? "";
  const [tag, setTag] = useState(hashTag);
  const [query, setQuery] = useState(() => (hashTag() ? `&tag=${encodeURIComponent(hashTag())}` : ""));
  const tags = useApi<{ items: TagCount[] }>("tags");
  useEffect(() => {
    const on = () => {
      const h = hashTag();
      if (h && window.location.hash.startsWith("#/documents?")) {
        setTag(h);
        setQuery(`&tag=${encodeURIComponent(h)}`);
      }
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const list = useApi<{ total: number; items: Doc[] }>(`documents?limit=100${query}`, [query]);
  const fileRef = useRef<HTMLInputElement>(null);
  const act = useAction();
  const [uploaded, setUploaded] = useState<string | null>(null);

  if (id) {
    return (
      <>
        <button className="btn" onClick={() => go("documents")}>← {t("documents")}</button>
        <DocDetail id={id} me={me} />
      </>
    );
  }
  const apply = (e?: React.FormEvent) => {
    e?.preventDefault();
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (state) p.set("state", state);
    if (tag) p.set("tag", tag);
    setQuery(p.toString() ? `&${p}` : "");
  };
  const upload = (files: FileList | null) =>
    files &&
    act.run(async () => {
      const fd = new FormData();
      Array.from(files).forEach((f) => fd.append("files", f));
      const r = await api.form<{ results: { status: string }[] }>("documents/upload", fd);
      setUploaded(`${r.results.filter((x) => x.status === "created").length} von ${r.results.length} Dateien übernommen`);
      list.reload();
    });
  const canUpload = me.role === "admin" || me.role === "editor";
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="h1">{t("documents")} <span className="muted text-sm font-normal">({list.data?.total ?? 0})</span></h1>
        {canUpload && (
          <>
            <input ref={fileRef} type="file" multiple accept="application/pdf,image/png,image/jpeg,image/tiff" capture="environment" className="hidden" onChange={(e) => upload(e.target.files)} />
            <button className="btn btn-primary" disabled={act.busy} onClick={() => fileRef.current?.click()}>{t("upload")}</button>
          </>
        )}
      </div>
      {canUpload && (
        <div
          className="rounded-lg border-2 border-dashed border-slate-300 p-4 text-center text-sm muted dark:border-slate-700"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
        >
          Dateien hierher ziehen (PDF, PNG, JPG, TIFF)
        </div>
      )}
      {uploaded && <Notice tone="ok">{uploaded}</Notice>}
      <ErrorBox error={list.error || act.error} />
      <form onSubmit={apply} className="flex flex-wrap gap-2">
        <input className="input max-w-md" placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input w-48" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">Alle Status</option>
          <option value="done">archiviert</option>
          <option value="needs_review,observed">zur Prüfung / beobachtet</option>
          <option value="failed,quarantined">Fehler</option>
          <option value="duplicate">Duplikate</option>
        </select>
        <select className="input w-48" value={tag} onChange={(e) => setTag(e.target.value)} aria-label={t("tags")}>
          <option value="">Alle Tags</option>
          {(tags.data?.items ?? []).map((x) => <option key={x.tag} value={x.tag}>{x.tag} ({x.count})</option>)}
        </select>
        <button className="btn" type="submit">{t("search").replace(" …", "")}</button>
      </form>
      <div className="panel overflow-x-auto">
        <table className="tbl">
          <thead>
            <tr><th>Datei</th><th>{t("type")}</th><th>{t("sender")}</th><th>{t("date")}</th><th>{t("folder")}</th><th>{t("status")}</th><th>Erfasst</th></tr>
          </thead>
          <tbody>
            {(list.data?.items ?? []).map((d) => (
              <tr key={d.id} className="clickable" onClick={() => go(`documents/${d.id}`)}>
                <td className="max-w-xs">
                  <div className="truncate">{d.target_name ?? d.original_filename}</div>
                  {d.tags?.length ? <div className="truncate text-xs muted">{d.tags.join(" · ")}</div> : null}
                </td>
                <td>{d.document_type ?? "–"}</td>
                <td className="max-w-[10rem] truncate">{d.sender ?? "–"}</td>
                <td className="whitespace-nowrap">{d.document_date ?? "–"}</td>
                <td className="max-w-[14rem] truncate muted">{d.target_folder_path ?? "–"}</td>
                <td><StateBadge state={d.state} /></td>
                <td className="whitespace-nowrap muted">{fmtDate(d.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data?.items.length === 0 && <p className="p-4 text-sm muted">{t("empty")}</p>}
      </div>
    </>
  );
}
