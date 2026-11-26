import { useRef, useState } from "react";
import { api } from "../api";
import { t } from "../i18n";
import { ErrorBox, Field, Notice, useAction, useApi } from "../ui";

type Status = {
  admin_exists: boolean; ocr_available: boolean; free_disk_mb: number; google_client: boolean; google_accounts: number;
  archive_folders: number; inbox_sources: number; rules: number; ai_provider: { kind: string } | null; test_run_ok: boolean;
  setup_completed: boolean; processing_mode: string; local_inbox: string | null;
};
type GStatus = {
  client: { client_type: string; client_id: string; project_id: string | null } | null;
  redirect_uri: string; redirect_problems: string[]; required_apis: string[];
  accounts: { id: number; email: string; scopes: string; status: string; last_error: string | null }[];
};
type Report = { ok: boolean; checks: { name: string; ok: boolean; detail: string; required: boolean }[] };

function Step({ n, title, done, children }: { n: number; title: string; done: boolean; children?: React.ReactNode }) {
  return (
    <div className="panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${done ? "bg-emerald-600 text-white" : "bg-slate-200 dark:bg-slate-700"}`}>{done ? "✓" : n}</span>
        <h2 className="h2">{title}</h2>
      </div>
      <div className="space-y-2 pl-8 text-sm">{children}</div>
    </div>
  );
}

export default function Setup({ go }: { go: (to: string) => void }) {
  const st = useApi<Status>("setup/status");
  const g = useApi<GStatus>("google/status");
  const act = useAction();
  const fileRef = useRef<HTMLInputElement>(null);
  const [manual, setManual] = useState({ client_id: "", client_secret: "", client_type: "installed" });
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [pasted, setPasted] = useState("");
  const [driveMode, setDriveMode] = useState("full");
  const [report, setReport] = useState<Report | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const s = st.data;
  if (!s) return <ErrorBox error={st.error} />;
  const reload = () => { st.reload(); g.reload(); };

  const uploadClient = (file?: File) => act.run(async () => {
    const fd = new FormData();
    if (file) fd.append("file", file); else Object.entries(manual).forEach(([k, v]) => fd.append(k, v));
    const r = await api.form<{ client_type: string; redirect_problems: string[] }>("google/client", fd);
    setMsg(`OAuth-Client gespeichert (Typ: ${r.client_type === "installed" ? "Desktop-App" : "Webanwendung"})`);
    reload();
  });
  const authorize = () => act.run(async () => {
    const r = await api.send<{ auth_url: string }>("POST", "google/authorize", { drive_mode: driveMode, gmail: true });
    setAuthUrl(r.auth_url);
    window.open(r.auth_url, "_blank", "noopener");
  });
  const complete = () => act.run(async () => {
    const r = await api.send<{ email: string; missing_scopes: string[] }>("POST", "google/complete", { redirect_url: pasted });
    setMsg(`Verbunden: ${r.email}${r.missing_scopes.length ? ` – nicht erteilt: ${r.missing_scopes.join(", ")}` : ""}`);
    setAuthUrl(null);
    setPasted("");
    reload();
  });
  const testAccount = (id: number) => act.run(async () => {
    const r = await api.send<{ drive: { ok: boolean; error?: string }; gmail: { ok: boolean; error?: string } }>("POST", `google/accounts/${id}/test`);
    setMsg(`Drive: ${r.drive.ok ? "ok" : r.drive.error} · Gmail: ${r.gmail.ok ? "ok" : r.gmail.error}`);
  });
  const testRun = () => act.run(async () => { setReport(await api.send<Report>("POST", "setup/test-run")); reload(); });
  const activate = (mode: string) => act.run(async () => {
    await api.send("PATCH", "settings", { processing_mode: mode });
    await api.send("POST", "setup/complete");
    setMsg("Einrichtung abgeschlossen");
    reload();
  });

  return (
    <>
      <h1 className="h1">{t("setup")}</h1>
      <ErrorBox error={act.error} />
      {msg && <Notice tone="ok">{msg}</Notice>}
      <Step n={1} title="Administrator" done={s.admin_exists}>Sie sind LorzDMS-Administrator. Weitere Home-Assistant-Benutzer erhalten erst nach Freigabe unter Einstellungen Zugriff.</Step>
      <Step n={2} title="Systemprüfung" done={s.ocr_available && s.free_disk_mb > 500}>
        <div>OCR (OCRmyPDF/Tesseract): {s.ocr_available ? "verfügbar" : "nicht verfügbar"} · Freier Speicher: {s.free_disk_mb} MB</div>
        {s.local_inbox && <div>Lokaler Eingang: <code>{s.local_inbox}</code> (z. B. für Scanner/SMB)</div>}
      </Step>
      <Step n={3} title="Google verbinden (Drive und Gmail)" done={s.google_accounts > 0}>
        <details open={!s.google_client}>
          <summary className="cursor-pointer font-medium">Anleitung Google Cloud</summary>
          <ol className="mt-2 list-decimal space-y-1 pl-5 muted">
            <li>console.cloud.google.com → Projekt wählen (ein bestehendes Projekt kann weiterverwendet werden).</li>
            <li>APIs aktivieren: {g.data?.required_apis.join(", ")}.</li>
            <li>OAuth-Zustimmungsbildschirm: Typ „Extern“, eigene Adresse als Testnutzer. Im Testmodus laufen Refresh-Tokens nach 7 Tagen ab – für Dauerbetrieb die App veröffentlichen („In Produktion“); bei eingeschränkten Scopes zeigt Google dann einen Warnhinweis, eine Verifizierung ist für die private Nutzung nicht zwingend.</li>
            <li>Anmeldedaten → OAuth-Client-ID → Typ <b>Desktop-App</b> (empfohlen). Bei Typ Webanwendung muss <code>{g.data?.redirect_uri}</code> als Weiterleitungs-URI eingetragen werden.</li>
            <li>JSON herunterladen und hier hochladen.</li>
          </ol>
        </details>
        {g.data?.client ? (
          <div>OAuth-Client: <code>{g.data.client.client_id.slice(0, 18)}…</code> ({g.data.client.client_type === "installed" ? "Desktop-App" : "Webanwendung"}{g.data.client.project_id ? `, Projekt ${g.data.client.project_id}` : ""})</div>
        ) : null}
        {g.data?.redirect_problems.map((p, i) => <Notice key={i} tone="warn">{p}</Notice>)}
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={(e) => e.target.files?.[0] && uploadClient(e.target.files[0])} />
          <button className="btn" onClick={() => fileRef.current?.click()}>Client-JSON hochladen</button>
          <details>
            <summary className="cursor-pointer text-xs muted">manuell eingeben</summary>
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              <input className="input" placeholder="Client-ID" value={manual.client_id} onChange={(e) => setManual({ ...manual, client_id: e.target.value })} />
              <input className="input" placeholder="Client-Secret" type="password" value={manual.client_secret} onChange={(e) => setManual({ ...manual, client_secret: e.target.value })} />
              <button className="btn" onClick={() => uploadClient()}>Speichern</button>
            </div>
          </details>
        </div>
        {g.data?.client && (
          <div className="space-y-2 pt-2">
            <Field label="Drive-Berechtigung">
              <select className="input max-w-xl" value={driveMode} onChange={(e) => setDriveMode(e.target.value)}>
                <option value="full">Vollzugriff (drive) – nötig, um bestehende Ordner und Dateien zu lesen und zu verschieben</option>
                <option value="file">Nur eigene Dateien (drive.file) – bestehende Ordner/Eingänge sind dann nicht nutzbar</option>
              </select>
            </Field>
            <p className="text-xs muted">Gmail wird nur mit <code>gmail.readonly</code> angefragt. LorzDMS kann E-Mails weder ändern noch löschen.</p>
            <button className="btn btn-primary" onClick={authorize} disabled={act.busy}>Google-Konto verbinden</button>
            {authUrl && (
              <div className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-800">
                <p>Ein neues Fenster mit der Google-Anmeldung wurde geöffnet (<a className="text-brand-600 underline" href={authUrl} target="_blank" rel="noreferrer noopener">erneut öffnen</a>). Nach der Zustimmung leitet Google auf <code>{g.data.redirect_uri}</code> weiter – die Seite lädt nicht, das ist richtig. Kopieren Sie die <b>komplette Adresse aus der Adresszeile</b> und fügen Sie sie hier ein:</p>
                <input className="input font-mono text-xs" placeholder="http://127.0.0.1:8765/oauth2callback?state=…&code=…" value={pasted} onChange={(e) => setPasted(e.target.value)} />
                <button className="btn btn-primary" onClick={complete} disabled={!pasted || act.busy}>Verbindung abschließen</button>
              </div>
            )}
          </div>
        )}
        {g.data?.accounts.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{a.email}</span>
            <span className={a.status === "connected" ? "text-emerald-600" : "text-red-600"}>{a.status === "connected" ? "verbunden" : "Neuanmeldung nötig"}</span>
            <span className="text-xs muted">{a.scopes.includes("gmail.readonly") ? "Gmail lesend · " : ""}{a.scopes.includes("auth/drive ") || a.scopes.endsWith("auth/drive") ? "Drive voll" : "Drive eingeschränkt"}</span>
            <button className="btn" onClick={() => testAccount(a.id)}>Verbindung testen</button>
            {a.status !== "connected" && <button className="btn" onClick={authorize}>Neu verbinden</button>}
          </div>
        ))}
      </Step>
      <Step n={4} title="Archiv- und Eingangsordner auswählen" done={s.archive_folders > 0}>
        <p>Wählen Sie den Archiv-Wurzelordner (bestehende Unterordner werden lesend übernommen) sowie optional einen Prüfordner.</p>
        <button className="btn" onClick={() => go("folders")}>Zu den Ordnern</button>
      </Step>
      <Step n={5} title="Quellen: Gmail und Drive-Eingang" done={s.inbox_sources > 0}>
        <p>Ihr bestehender Gmail-PDF-Import kann parallel weiterlaufen. Er wird von LorzDMS weder deaktiviert noch verändert.</p>
        <button className="btn" onClick={() => go("sources")}>Zu den Quellen</button>
      </Step>
      <Step n={6} title="KI-Provider (optional)" done={!!s.ai_provider && s.ai_provider.kind !== "none"}>
        <p>Ohne KI arbeitet LorzDMS mit Regeln und legt Unklares zur Prüfung vor. Externe Anbieter werden nur nach ausdrücklicher Freigabe genutzt.</p>
        <button className="btn" onClick={() => go("settings")}>Zu den Einstellungen</button>
      </Step>
      <Step n={7} title="Ablageregeln" done={s.rules > 0}>
        <button className="btn" onClick={() => go("rules")}>Zu den Regeln</button>
      </Step>
      <Step n={8} title="Testlauf" done={s.test_run_ok}>
        <p>Prüft OCR mit einem Beispiel-Scan, Regeln, Dateinamensvorlage, Erreichbarkeit der Archivordner und ggf. die KI – ohne Änderungen in Google Drive.</p>
        <button className="btn btn-primary" onClick={testRun} disabled={act.busy}>{act.busy ? "Läuft …" : "Testlauf starten"}</button>
        {report && (
          <ul className="space-y-1">
            {report.checks.map((c, i) => <li key={i} className={c.ok ? "text-emerald-700 dark:text-emerald-400" : c.required ? "text-red-600" : "text-amber-600"}>{c.ok ? "✓" : "✗"} {c.name} {c.detail && <span className="muted">– {c.detail}</span>}</li>)}
          </ul>
        )}
      </Step>
      <Step n={9} title="Verarbeitung aktivieren" done={s.setup_completed}>
        <p>Aktueller Modus: <b>{s.processing_mode}</b>. Empfehlung: zunächst „Jede Ablage bestätigen“, nach einigen korrekten Vorschlägen „Automatisch“.</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn" onClick={() => activate("observe")}>Nur beobachten</button>
          <button className="btn btn-primary" onClick={() => activate("review")}>Mit Bestätigung starten</button>
          <button className="btn" disabled={!s.test_run_ok} onClick={() => activate("auto")}>Automatisch starten</button>
        </div>
      </Step>
    </>
  );
}
