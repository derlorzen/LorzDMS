import { useState } from "react";
import { api, Doc, Me } from "../api";
import { t } from "../i18n";
import DocDetail from "../components/DocDetail";
import { ErrorBox, Notice, StateBadge, useAction, useApi } from "../ui";

export default function Review({ id, go, me }: { id?: number; go: (to: string) => void; me: Me }) {
  const list = useApi<{ total: number; items: Doc[] }>("documents?state=needs_review,observed&limit=200");
  const [selected, setSelected] = useState<number[]>([]);
  const act = useAction();
  const items = list.data?.items ?? [];
  const current = id ?? items[0]?.id;
  const batch = () =>
    act.run(async () => {
      const r = await api.send<{ results: { id: number; ok: boolean; error?: string }[] }>("POST", "documents/approve-batch", { ids: selected });
      const failed = r.results.filter((x) => !x.ok);
      setSelected([]);
      list.reload();
      if (failed.length) act.setError(`${failed.length} nicht freigegeben: ${failed[0].error}`);
    });
  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="h1">{t("review")} <span className="muted text-sm font-normal">({list.data?.total ?? 0})</span></h1>
        {selected.length > 0 && (
          <button className="btn btn-primary" disabled={act.busy} onClick={batch}>{selected.length} Vorschläge bestätigen</button>
        )}
      </div>
      <ErrorBox error={list.error || act.error} />
      {items.length === 0 ? (
        <Notice tone="ok">Keine Dokumente zur Prüfung.</Notice>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <ul className="panel max-h-[80vh] divide-y divide-slate-100 overflow-auto text-sm dark:divide-slate-800">
            {items.map((d) => (
              <li key={d.id} className={`flex items-start gap-2 px-3 py-2 ${d.id === current ? "bg-brand-50 dark:bg-brand-700/20" : ""}`}>
                <input type="checkbox" className="mt-1" aria-label="auswählen" checked={selected.includes(d.id)} disabled={!d.target_folder_drive_id}
                  onChange={(e) => setSelected(e.target.checked ? [...selected, d.id] : selected.filter((x) => x !== d.id))} />
                <button className="min-w-0 flex-1 text-left" onClick={() => go(`review/${d.id}`)}>
                  <div className="truncate">{d.target_name ?? d.original_filename}</div>
                  <div className="flex items-center gap-2 text-xs muted">
                    <StateBadge state={d.state} />
                    {d.confidence != null && <span>{Math.round(d.confidence * 100)} %</span>}
                    <span className="truncate">{d.target_folder_path ?? "kein Ordner"}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
          {current && <DocDetail key={current} id={current} me={me} onDone={list.reload} />}
        </div>
      )}
    </>
  );
}
