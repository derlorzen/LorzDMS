import { ReactNode, useCallback, useEffect, useState } from "react";
import { api } from "./api";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(() => {
    if (!path) return;
    setLoading(true);
    api
      .get<T>(path)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}

const STATE_STYLE: Record<string, string> = {
  done: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  needs_review: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  observed: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  quarantined: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  duplicate: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  excluded: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
};
const STATE_LABEL_DE: Record<string, string> = {
  new: "neu", fetched: "erfasst", validated: "geprüft", extracted: "Text erkannt", analyzed: "analysiert",
  observed: "beobachtet", needs_review: "zur Prüfung", approved: "freigegeben", archiving: "wird abgelegt",
  archived: "abgelegt", verified: "verifiziert", done: "archiviert", duplicate: "Duplikat", excluded: "ausgeschlossen",
  failed: "Fehler", quarantined: "Quarantäne",
};

export function StateBadge({ state }: { state: string }) {
  const de = navigator.language.toLowerCase().startsWith("de");
  return (
    <span className={`inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium ${STATE_STYLE[state] ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"}`}>
      {de ? STATE_LABEL_DE[state] ?? state : state.replace("_", " ")}
    </span>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</div>;
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "ok" }) {
  const cls = {
    info: "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200",
    warn: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200",
    ok: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  }[tone];
  return <div className={`rounded-md border px-3 py-2 text-sm ${cls}`}>{children}</div>;
}

export function Section({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
        <h2 className="h2">{title}</h2>
        <div className="flex gap-2">{actions}</div>
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, tone, onClick }: { label: string; value: number | string; tone?: string; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="panel flex flex-col items-start px-4 py-3 text-left hover:border-brand-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
      <span className="text-xs muted">{label}</span>
      <span className={`text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</span>
    </button>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run, setError };
}
