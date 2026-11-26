import { Doc } from "../api";
import { fmtDate, t } from "../i18n";
import { ErrorBox, Notice, Section, Stat, StateBadge, useApi } from "../ui";

type Dash = {
  counts: Record<string, number>;
  recent: Doc[];
  sources: { id: number; kind: string; name: string; enabled: number; last_sync_at: string | null; last_status: string | null; last_error: string | null; email: string | null; account_status: string | null }[];
  jobs: { by_state: Record<string, number> };
  monthly: { month: string; n: number }[];
  ocr_avg_seconds: number | null;
  worker_heartbeat: string | null;
  processing_paused: boolean;
  mode: string;
  ocr_available: boolean;
  ai_configured: boolean;
};

const sum = (c: Record<string, number>, keys: string[]) => keys.reduce((a, k) => a + (c[k] ?? 0), 0);

export default function Dashboard({ go }: { go: (to: string) => void }) {
  const { data, error } = useApi<Dash>("dashboard");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <p className="muted text-sm">…</p>;
  const c = data.counts;
  const hb = data.worker_heartbeat ? (Date.now() - new Date(data.worker_heartbeat).getTime()) / 1000 : Infinity;
  const workerOk = hb < 120;
  const modeLabel = { observe: t("mode_observe"), review: t("mode_review"), auto: t("mode_auto") }[data.mode] ?? data.mode;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="h1">{t("dashboard")}</h1>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded border border-slate-300 px-2 py-1 dark:border-slate-700">{t("mode")}: <b>{modeLabel}</b></span>
          <span className={`rounded px-2 py-1 ${workerOk ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"}`}>
            {t("worker")}: {workerOk ? "aktiv" : "keine Rückmeldung"}
          </span>
          <span className={`rounded px-2 py-1 ${data.ocr_available ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" : "bg-red-100 text-red-800"}`}>OCR: {data.ocr_available ? "bereit" : "nicht verfügbar"}</span>
          <span className="rounded border border-slate-300 px-2 py-1 dark:border-slate-700">KI: {data.ai_configured ? "konfiguriert" : "nur Regeln"}</span>
        </div>
      </div>
      {data.processing_paused && <Notice tone="warn">Die Verarbeitung ist pausiert.</Notice>}
      {data.mode === "observe" && <Notice>Beobachtungsmodus: LorzDMS analysiert Dokumente, verändert aber nichts in Google Drive. Umstellen unter Einstellungen.</Notice>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label={t("processing")} value={sum(c, ["new", "fetched", "validated", "extracted", "analyzed", "approved", "archiving", "archived", "verified"])} onClick={() => go("documents")} />
        <Stat label={t("needs_review")} value={sum(c, ["needs_review"])} tone="text-amber-600" onClick={() => go("review")} />
        <Stat label={t("observed")} value={sum(c, ["observed"])} onClick={() => go("review")} />
        <Stat label={t("archived")} value={sum(c, ["done"])} tone="text-emerald-600" onClick={() => go("documents")} />
        <Stat label={t("duplicates")} value={sum(c, ["duplicate"])} onClick={() => go("documents")} />
        <Stat label={t("failed")} value={sum(c, ["failed", "quarantined"]) + (data.jobs.by_state.dead ?? 0)} tone="text-red-600" onClick={() => go("documents")} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Section title={t("recent")}>
            {data.recent.length === 0 ? (
              <p className="text-sm muted">{t("empty")}</p>
            ) : (
              <table className="tbl">
                <thead>
                  <tr><th>Datei</th><th>{t("status")}</th><th>{t("folder")}</th><th>Erfasst</th></tr>
                </thead>
                <tbody>
                  {data.recent.map((d) => (
                    <tr key={d.id} className="clickable" onClick={() => go(`documents/${d.id}`)}>
                      <td className="max-w-xs truncate">{d.target_name ?? d.original_filename}</td>
                      <td><StateBadge state={d.state} /></td>
                      <td className="max-w-[14rem] truncate muted">{d.target_folder_path ?? "–"}</td>
                      <td className="whitespace-nowrap muted">{fmtDate(d.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </div>
        <Section title={t("sources")}>
          <ul className="space-y-2 text-sm">
            {data.sources.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{s.name}</div>
                  <div className="truncate text-xs muted">{s.email ?? s.kind} · {fmtDate(s.last_sync_at)}</div>
                  {s.last_error && <div className="text-xs text-red-600">{s.last_error}</div>}
                </div>
                <span className={`text-xs ${s.last_status === "ok" ? "text-emerald-600" : s.last_status ? "text-red-600" : "muted"}`}>{s.enabled ? s.last_status ?? "–" : "aus"}</span>
              </li>
            ))}
          </ul>
          <div className="mt-4 text-xs muted">
            Ø OCR-Dauer: {data.ocr_avg_seconds ?? "–"} s · Jobs: {Object.entries(data.jobs.by_state).map(([k, v]) => `${k} ${v}`).join(", ") || "–"}
          </div>
        </Section>
      </div>
    </>
  );
}
