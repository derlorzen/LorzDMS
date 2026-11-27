import { useEffect, useState } from "react";
import { Me } from "./api";
import { t } from "./i18n";
import { useApi } from "./ui";
import Dashboard from "./pages/Dashboard";
import Review from "./pages/Review";
import Documents from "./pages/Documents";
import Sources from "./pages/Sources";
import Folders from "./pages/Folders";
import Rules from "./pages/Rules";
import Settings from "./pages/Settings";
import Setup from "./pages/Setup";
import Deadlines from "./pages/Deadlines";
import Cases from "./pages/Cases";
import Tags from "./pages/Tags";

export function useRoute(): [string[], (to: string) => void] {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "dashboard").split("/");
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [route, (to: string) => (window.location.hash = `#/${to}`)];
}

const NAV: { key: string; label: string; admin?: boolean }[] = [
  { key: "dashboard", label: t("dashboard") },
  { key: "review", label: t("review") },
  { key: "documents", label: t("documents") },
  { key: "deadlines", label: t("deadlines") },
  { key: "cases", label: t("cases") },
  { key: "tags", label: t("tags") },
  { key: "sources", label: t("sources"), admin: true },
  { key: "folders", label: t("folders"), admin: true },
  { key: "rules", label: t("rules") },
  { key: "settings", label: t("settings"), admin: true },
  { key: "setup", label: t("setup"), admin: true },
];

export default function App() {
  const me = useApi<Me>("me");
  const [route, go] = useRoute();
  const [menu, setMenu] = useState(false);
  const status = useApi<{ setup_completed: boolean }>(me.data && me.data.role !== "none" ? "setup/status" : null, [me.data?.role]);

  useEffect(() => {
    if (status.data && !status.data.setup_completed && me.data?.role === "admin" && route[0] === "dashboard" && !window.location.hash) go("setup");
  }, [status.data, me.data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (me.error) return <div className="p-6 text-sm">{me.error}</div>;
  if (!me.data) return <div className="p-6 text-sm muted">…</div>;
  if (me.data.role === "none")
    return (
      <div className="mx-auto max-w-lg p-8">
        <h1 className="h1 mb-2">{t("no_access")}</h1>
        <p className="text-sm muted">{t("no_access_text")}</p>
      </div>
    );
  const isAdmin = me.data.role === "admin";
  const page = route[0].split("?")[0];
  const id = route[1] ? Number(route[1]) : undefined;
  return (
    <div className="flex min-h-screen">
      <nav className={`${menu ? "block" : "hidden"} fixed inset-y-0 left-0 z-20 w-52 shrink-0 border-r border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900 md:static md:block`}>
        <div className="px-4 py-4 text-base font-semibold tracking-tight">LorzDMS</div>
        <ul className="space-y-0.5 px-2 text-sm">
          {NAV.filter((n) => !n.admin || isAdmin).map((n) => (
            <li key={n.key}>
              <a
                href={`#/${n.key}`}
                onClick={() => setMenu(false)}
                className={`block rounded-md px-3 py-1.5 ${page === n.key ? "bg-brand-100 font-medium text-brand-700 dark:bg-brand-700/30 dark:text-brand-100" : "hover:bg-slate-200/60 dark:hover:bg-slate-800"}`}
              >
                {n.label}
              </a>
            </li>
          ))}
        </ul>
        <div className="absolute bottom-3 px-4 text-xs muted">
          {me.data.name} · {me.data.role}
        </div>
      </nav>
      <main className="min-w-0 flex-1">
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800 md:hidden">
          <button className="btn" onClick={() => setMenu(!menu)} aria-label="Menü">☰</button>
          <span className="font-semibold">LorzDMS</span>
        </div>
        <div className="mx-auto max-w-7xl space-y-4 p-4">
          {page === "dashboard" && <Dashboard go={go} />}
          {page === "review" && <Review id={id} go={go} me={me.data} />}
          {page === "documents" && <Documents id={id} go={go} me={me.data} />}
          {page === "deadlines" && <Deadlines go={go} me={me.data} />}
          {page === "cases" && <Cases id={id} go={go} me={me.data} />}
          {page === "tags" && <Tags go={go} me={me.data} />}
          {page === "sources" && isAdmin && <Sources />}
          {page === "folders" && isAdmin && <Folders />}
          {page === "rules" && <Rules me={me.data} />}
          {page === "settings" && isAdmin && <Settings me={me.data} />}
          {page === "setup" && isAdmin && <Setup go={go} />}
        </div>
      </main>
    </div>
  );
}
