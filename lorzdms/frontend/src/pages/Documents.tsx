import { useEffect, useRef, useState } from "react";
import { api, Doc, Me, TagCount } from "../api";
import { fmtDate, t } from "../i18n";
import DocDetail from "../components/DocDetail";
import { ErrorBox, Notice, StateBadge, useAction, useApi } from "../ui";

type Filters = { document_types: string[]; senders: string[]; folders: { path: string; count: number }[]; years: string[] };
type F = { q: string; state: string; tag: string; document_type: string; sender: string; folder: string; year: string; sort: string };
const EMPTY: F = { q: "", state: "", tag: "", document_type: "", sender: "", folder: "", year: "", sort: "newest" };
const PAGE = 60;

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

const fromHash = (): F => {
  const p = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  return { ...EMPTY, ...Object.fromEntries([...p].filter(([k]) => k in EMPTY)) };
};

function toQuery(f: F): string {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  for (const k of ["state", "tag", "document_type", "sender", "folder"] as const) if (f[k]) p.set(k, f[k]);
  if (f.year) {
    p.set("date_from", `${f.year}-01-01`);
    p.set("date_to", `${f.year}-12-31`);
  }
  if (f.sort !== "newest") p.set("sort", f.sort);
  return p.toString();
}

export default function Documents({ id, go, me }: { id?: number; go: (to: string) => void; me: Me }) {
  const [form, setForm] = useState<F>(fromHash);
  const [applied, setApplied] = useState<F>(fromHash);
  const [view, setView] = useState<"grid" | "list">(() => (store("lorzdms.view") === "list" ? "list" : "grid"));
  const [limit, setLimit] = useState(PAGE);
  const query = toQuery(applied);
  const list = useApi<{ total: number; items: Doc[] }>(id ? null : `documents?limit=${limit}${query ? `&${query}` : ""}`, [query, limit, id]);
  const meta = useApi<Filters>("meta/filters");
  const tags = useApi<{ items: TagCount[] }>("tags");
  const fileRef = useRef<HTMLInputElement>(null);
  const act = useAction();
  const [uploaded, setUploaded] = useState<string | null>(null);

  useEffect(() => {
    const on = () => {
      if (window.location.hash.startsWith("#/documents?")) {
        const f = fromHash();
        setForm(f);
        setApplied(f);
        setLimit(PAGE);
      }
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  if (id) {
    return (
      <>
        <button className="btn" onClick={() => window.history.length > 1 ? window.history.back() : go("documents")}>← {t("documents")}</button>
        <DocDetail id={id} me={me} />
      </>
    );
  }
  const apply = (next: F) => {
    setForm(next);
    setApplied(next);
    setLimit(PAGE);
  };
  const set = (k: keyof F, v: string) => apply({ ...form, [k]: v });
  const active = (Object.keys(EMPTY) as (keyof F)[]).filter((k) => k !== "sort" && k !== "q" && applied[k]);
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
  const items = list.data?.items ?? [];
  const m = meta.data;
  // Übergeordnete Ordner mit aufsummierter Anzahl ergänzen (Filter schließt Unterordner ein)
  const folderOptions = (() => {
    const sums = new Map<string, number>();
    for (const f of m?.folders ?? []) {
      const parts = f.path.split("/");
      for (let i = 1; i <= parts.length; i++) {
        const p = parts.slice(0, i).join("/");
        sums.set(p, (sums.get(p) ?? 0) + f.count);
      }
    }
    return [...sums.entries()].sort(([a], [b]) => a.localeCompare(b, "de"));
  })();
  const label: Record<string, string> = { state: t("status"), tag: "Tag", document_type: t("type"), sender: t("sender"), folder: "Ordner", year: "Jahr" };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="h1">{t("documents")} <span className="muted text-sm font-normal">({list.data?.total ?? 0})</span></h1>
        <div className="flex gap-2">
          <div className="inline-flex overflow-hidden rounded-md border border-slate-300 dark:border-slate-700" role="group" aria-label="Ansicht">
            {(["grid", "list"] as const).map((v) => (
              <button key={v} className={`px-3 py-1.5 text-sm ${view === v ? "bg-brand-600 text-white" : "bg-white dark:bg-slate-900"}`}
                onClick={() => { setView(v); store("lorzdms.view", v); }}>
                {v === "grid" ? "Kacheln" : "Liste"}
              </button>
            ))}
          </div>
          {canUpload && (
            <>
              <input ref={fileRef} type="file" multiple accept="application/pdf,image/png,image/jpeg,image/tiff" capture="environment" className="hidden" onChange={(e) => upload(e.target.files)} />
              <button className="btn btn-primary" disabled={act.busy} onClick={() => fileRef.current?.click()}>{t("upload")}</button>
            </>
          )}
        </div>
      </div>
      {uploaded && <Notice tone="ok">{uploaded}</Notice>}
      <ErrorBox error={list.error || act.error} />

      <form onSubmit={(e) => { e.preventDefault(); apply(form); }} className="panel space-y-2 p-3">
        <div className="flex gap-2">
          <input className="input" type="search" placeholder="Volltext durchsuchen …" value={form.q} onChange={(e) => setForm({ ...form, q: e.target.value })} />
          <button className="btn btn-primary" type="submit">{t("search").replace(" …", "")}</button>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
          <select className="input" value={form.document_type} onChange={(e) => set("document_type", e.target.value)} aria-label={t("type")}>
            <option value="">Alle Typen</option>
            {(m?.document_types ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <input className="input" list="senders" placeholder={`${t("sender")} …`} value={form.sender}
            onChange={(e) => setForm({ ...form, sender: e.target.value })} onBlur={() => form.sender !== applied.sender && apply(form)} aria-label={t("sender")} />
          <datalist id="senders">{(m?.senders ?? []).map((x) => <option key={x} value={x} />)}</datalist>
          <select className="input" value={form.folder} onChange={(e) => set("folder", e.target.value)} aria-label="Ordner">
            <option value="">Alle Ordner</option>
            {folderOptions.map(([path, n]) => (
              <option key={path} value={path}>{"\u00a0\u00a0".repeat(path.split("/").length - 1)}{path.split("/").pop()} ({n})</option>
            ))}
          </select>
          <select className="input" value={form.year} onChange={(e) => set("year", e.target.value)} aria-label="Jahr">
            <option value="">Alle Jahre</option>
            {(m?.years ?? []).map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
          <select className="input" value={form.tag} onChange={(e) => set("tag", e.target.value)} aria-label="Tag">
            <option value="">Alle Tags</option>
            {(tags.data?.items ?? []).map((x) => <option key={x.tag} value={x.tag}>{x.tag} ({x.count})</option>)}
          </select>
          <select className="input" value={form.state} onChange={(e) => set("state", e.target.value)} aria-label={t("status")}>
            <option value="">Alle Status</option>
            <option value="done">archiviert</option>
            <option value="needs_review,observed">zur Prüfung / beobachtet</option>
            <option value="failed,quarantined">Fehler</option>
            <option value="duplicate">Duplikate</option>
          </select>
          <select className="input" value={form.sort} onChange={(e) => set("sort", e.target.value)} aria-label="Sortierung">
            <option value="newest">Zuletzt erfasst</option>
            <option value="date_desc">Datum, neueste zuerst</option>
            <option value="date_asc">Datum, älteste zuerst</option>
            <option value="sender">{t("sender")} A–Z</option>
          </select>
        </div>
        {active.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 text-xs">
            {active.map((k) => (
              <button type="button" key={k} onClick={() => set(k, "")}
                className="rounded-full bg-brand-100 px-2 py-0.5 text-brand-700 hover:bg-brand-200 dark:bg-brand-700/30 dark:text-brand-100">
                {label[k]}: {applied[k]} ×
              </button>
            ))}
            <button type="button" className="muted underline" onClick={() => apply({ ...EMPTY, sort: form.sort })}>alle Filter löschen</button>
          </div>
        )}
      </form>

      {canUpload && (
        <div
          className="hidden rounded-lg border-2 border-dashed border-slate-300 p-3 text-center text-sm muted dark:border-slate-700 sm:block"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
        >
          Dateien hierher ziehen (PDF, PNG, JPG, TIFF)
        </div>
      )}

      {view === "grid" ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
          {items.map((d) => <Card key={d.id} d={d} onOpen={() => go(`documents/${d.id}`)} onFilter={set} />)}
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr><th>Datei</th><th>{t("type")}</th><th>{t("sender")}</th><th>{t("date")}</th><th>{t("folder")}</th><th>{t("status")}</th><th>Erfasst</th></tr>
            </thead>
            <tbody>
              {items.map((d) => (
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
        </div>
      )}
      {list.data && items.length === 0 && <p className="p-4 text-sm muted">{t("empty")}</p>}
      {list.data && items.length < list.data.total && (
        <div className="text-center">
          <button className="btn" disabled={list.loading} onClick={() => setLimit(Math.min(limit + PAGE, 200))}>
            Mehr anzeigen ({items.length} von {list.data.total})
          </button>
          {limit >= 200 && <p className="mt-1 text-xs muted">Bitte Filter verwenden, um die Auswahl einzugrenzen.</p>}
        </div>
      )}
    </>
  );
}

function Card({ d, onOpen, onFilter }: { d: Doc; onOpen: () => void; onFilter: (k: keyof F, v: string) => void }) {
  const [broken, setBroken] = useState(false);
  const previewable = d.mime_type === "application/pdf" || d.mime_type?.startsWith("image/") || !d.mime_type;
  const name = d.title || d.target_name || d.original_filename;
  return (
    <div className="panel group flex flex-col overflow-hidden hover:border-brand-500">
      <button onClick={onOpen} className="relative block aspect-[3/4] w-full overflow-hidden bg-slate-100 dark:bg-slate-800" aria-label={`${name} öffnen`}>
        {previewable && !broken ? (
          <img loading="lazy" alt="" src={`api/documents/${d.id}/pages/1.png?width=300`} onError={() => setBroken(true)}
            className="h-full w-full object-cover object-top transition-transform group-hover:scale-[1.02]" />
        ) : (
          <span className="flex h-full items-center justify-center text-3xl muted">📄</span>
        )}
        <span className="absolute right-1.5 top-1.5"><StateBadge state={d.state} /></span>
      </button>
      <div className="min-w-0 space-y-0.5 p-2 text-xs">
        <button onClick={onOpen} className="line-clamp-2 block w-full break-words text-left text-sm font-medium hover:underline">{name}</button>
        <div className="truncate muted">
          {d.document_date ? new Date(`${d.document_date}T12:00:00`).toLocaleDateString("de-DE") : "ohne Datum"}
          {d.sender ? ` · ${d.sender}` : ""}
        </div>
        <div className="flex flex-wrap gap-1 pt-0.5">
          {d.document_type && (
            <button onClick={() => onFilter("document_type", d.document_type!)} className="rounded bg-slate-100 px-1.5 py-0.5 hover:bg-slate-200 dark:bg-slate-800">{d.document_type}</button>
          )}
          {d.tags?.slice(0, 3).map((tag) => (
            <button key={tag} onClick={() => onFilter("tag", tag)} className="rounded-full bg-brand-100 px-1.5 py-0.5 text-brand-700 hover:bg-brand-200 dark:bg-brand-700/30 dark:text-brand-100">{tag}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
