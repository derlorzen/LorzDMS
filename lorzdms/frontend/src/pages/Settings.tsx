import { useEffect, useState } from "react";
import { api, Me } from "../api";
import { fmtDate, t } from "../i18n";
import { ErrorBox, Field, Notice, Section, useAction, useApi } from "../ui";

type S = {
  processing_mode: string; auto_threshold: number; suggest_threshold: number; ai_confidence_cap: number; allow_external_ai: boolean;
  ai_provider: { kind: string; base_url?: string; model?: string; has_key?: boolean; external?: boolean } | null;
  ocr_provider: { kind: string; has_key?: boolean } | null; allow_external_ocr: boolean;
  filename_template: string; original_strategy: string; review_sensitive: boolean; test_run_ok: boolean;
  runtime: Record<string, string | number>;
};
type U = { id: number; name: string; display_name: string | null; role: string; last_seen_at: string | null };

export default function Settings({ me }: { me: Me }) {
  const s = useApi<S>("settings");
  const users = useApi<U[]>("users");
  const jobs = useApi<{ stats: { by_state: Record<string, number> }; items: { id: number; kind: string; state: string; attempts: number; last_error: string | null }[] }>("jobs?state=dead");
  const [form, setForm] = useState<Partial<S>>({});
  const [ai, setAi] = useState({ kind: "none", base_url: "", model: "", api_key: "" });
  const [ocr, setOcr] = useState({ kind: "local", api_key: "", allow_external_ocr: false });
  const act = useAction();
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    if (!s.data) return;
    setForm(s.data);
    setOcr({ kind: s.data.ocr_provider?.kind ?? "local", api_key: "", allow_external_ocr: !!s.data.allow_external_ocr });
    const p = s.data.ai_provider;
    setAi({ kind: p?.kind ?? "none", base_url: p?.base_url ?? "", model: p?.model ?? "", api_key: "" });
  }, [s.data]);
  if (!s.data) return <ErrorBox error={s.error} />;
  const save = () => act.run(async () => {
    const keys = ["processing_mode", "auto_threshold", "suggest_threshold", "ai_confidence_cap", "allow_external_ai", "filename_template", "original_strategy", "review_sensitive"] as const;
    const body: Record<string, unknown> = {};
    keys.forEach((k) => { if (form[k] !== s.data![k]) body[k] = form[k]; });
    if (Object.keys(body).length) await api.send("PATCH", "settings", body);
    setSaved("Gespeichert");
    s.reload();
  });
  const saveAi = () => act.run(async () => {
    const r = await api.send<{ external: boolean; allowed: boolean }>("PUT", "settings/ai-provider", { ...ai, api_key: ai.api_key || null });
    setSaved(r.external && !r.allowed ? "Gespeichert – externer Provider wird erst nach Freigabe genutzt" : "KI-Provider gespeichert");
    s.reload();
  });
  const saveOcr = () => act.run(async () => {
    await api.send("PUT", "settings/ocr-provider", { ...ocr, api_key: ocr.api_key || null });
    setSaved("OCR-Provider gespeichert");
    s.reload();
  });
  return (
    <>
      <h1 className="h1">{t("settings")}</h1>
      <ErrorBox error={act.error} />
      {saved && <Notice tone="ok">{saved}</Notice>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Verarbeitung" actions={<button className="btn btn-primary" onClick={save} disabled={act.busy}>{t("save")}</button>}>
          <div className="space-y-3">
            <Field label={t("mode")}>
              <select className="input" value={form.processing_mode} onChange={(e) => setForm({ ...form, processing_mode: e.target.value })}>
                <option value="observe">{t("mode_observe")}</option>
                <option value="review">{t("mode_review")}</option>
                <option value="auto" disabled={!s.data.test_run_ok}>{t("mode_auto")}{s.data.test_run_ok ? "" : " (erst nach Testlauf)"}</option>
              </select>
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Automatisch ab"><input className="input" type="number" step="0.01" min={0} max={1} value={form.auto_threshold} onChange={(e) => setForm({ ...form, auto_threshold: Number(e.target.value) })} /></Field>
              <Field label="Vorschlag ab"><input className="input" type="number" step="0.01" min={0} max={1} value={form.suggest_threshold} onChange={(e) => setForm({ ...form, suggest_threshold: Number(e.target.value) })} /></Field>
              <Field label="KI-Deckel"><input className="input" type="number" step="0.01" min={0} max={1} value={form.ai_confidence_cap} onChange={(e) => setForm({ ...form, ai_confidence_cap: Number(e.target.value) })} /></Field>
            </div>
            <p className="text-xs muted">KI-Entscheidungen ohne Regel werden auf den KI-Deckel begrenzt (Standard 0,94 &lt; 0,95), bis die Schwellen anhand realer Ergebnisse überprüft wurden. Regeln ergeben Konfidenz 1,0.</p>
            <Field label="Dateinamensvorlage"><input className="input font-mono" value={form.filename_template} onChange={(e) => setForm({ ...form, filename_template: e.target.value })} /></Field>
            <p className="text-xs muted">Felder: {"{document_date} {sender} {document_type} {reference} {title} {original_name} {year} {month} {person} {amount}"}</p>
            <Field label="Originale und OCR-Derivate">
              <select className="input" value={form.original_strategy} onChange={(e) => setForm({ ...form, original_strategy: e.target.value })}>
                <option value="original_only">Original unverändert ablegen, OCR nur als Suchindex (empfohlen)</option>
                <option value="original_plus_derivative">Original ablegen (Derivat-Ablage folgt)</option>
                <option value="derivative_only">Durchsuchbares OCR-PDF ablegen (nie bei signierten PDFs)</option>
              </select>
            </Field>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!form.review_sensitive} onChange={(e) => setForm({ ...form, review_sensitive: e.target.checked })} /> Hochsensible Dokumente immer prüfen</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!form.allow_external_ai} onChange={(e) => setForm({ ...form, allow_external_ai: e.target.checked })} /> Externe KI-Provider erlauben (Dokumenttext verlässt das Netzwerk)</label>
          </div>
        </Section>
        <Section title="OCR – Texterkennung" actions={<button className="btn btn-primary" onClick={saveOcr} disabled={act.busy}>{t("save")}</button>}>
          <div className="space-y-3">
            <Field label="Typ">
              <select className="input" value={ocr.kind} onChange={(e) => setOcr({ ...ocr, kind: e.target.value, allow_external_ocr: false, api_key: "" })}>
                <option value="local">Lokal – OCRmyPDF / Tesseract</option>
                <option value="nvidia_nemotron_ocr_v2">NVIDIA Nemotron OCR v2 (multilingual)</option>
              </select>
            </Field>
            {ocr.kind === "nvidia_nemotron_ocr_v2" && <>
              <Field label="POST-Endpunkt"><input className="input" readOnly value="https://ai.api.nvidia.com/v1/cv/nvidia/nemotron-ocr-v2" /></Field>
              <Field label="Modell"><input className="input" readOnly value="nvidia/nemotron-ocr-v2" /></Field>
              <Field label={`API-Key${s.data.ocr_provider?.has_key ? " (gespeichert – leer lassen zum Beibehalten)" : ""}`}>
                <input className="input" type="password" name="lorzdms-nvidia-ocr-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" value={ocr.api_key} onChange={(e) => setOcr({ ...ocr, api_key: e.target.value })} />
              </Field>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={ocr.allow_external_ocr} onChange={(e) => setOcr({ ...ocr, allow_external_ocr: e.target.checked })} /> Externe OCR erlauben (gescannte Seitenbilder werden an NVIDIA übertragen)</label>
              <p className="text-xs muted">Multilinguales Standardmodell, keine Englisch-Beschränkung im Request. Deutsch ist in der NVIDIA Model Card nicht ausdrücklich zugesichert. Das Original bleibt unverändert; NVIDIA erzeugt kein durchsuchbares PDF-Derivat. Die KI-Sortierung wird separat konfiguriert.</p>
            </>}
          </div>
        </Section>
        <Section title="KI-Provider" actions={<button className="btn btn-primary" onClick={saveAi} disabled={act.busy}>{t("save")}</button>}>
          <div className="space-y-3">
            <Field label="Typ">
              <select className="input" value={ai.kind} onChange={(e) => {
                const kind = e.target.value;
                setAi(kind === "openrouter_decider" ? { kind, base_url: "https://openrouter.ai/api/alpha", model: "perplexity/pplx-decider-v1.3:free", api_key: "" } : { ...ai, kind, base_url: ai.kind === "openrouter_decider" ? "" : ai.base_url, model: ai.kind === "openrouter_decider" ? "" : ai.model, api_key: "" });
              }}>
                <option value="none">Keine KI – nur Regeln</option>
                <option value="ollama">Ollama (lokal oder im Heimnetz)</option>
                <option value="openai_compatible">OpenAI-kompatibel (OpenAI, OpenRouter, Mistral, LM Studio, vLLM …)</option>
                <option value="anthropic">Anthropic</option>
                <option value="openrouter_decider">OpenRouter – Perplexity Decider v1.3 (free)</option>
              </select>
            </Field>
            {ai.kind !== "none" && <>
              <Field label="Basis-URL"><input className="input" name="lorzdms-ai-base-url" readOnly={ai.kind === "openrouter_decider"} autoComplete="off" spellCheck={false} placeholder={ai.kind === "ollama" ? "http://192.168.1.10:11434" : ai.kind === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1"} value={ai.base_url} onChange={(e) => setAi({ ...ai, base_url: e.target.value })} /></Field>
              <Field label="Modell"><input className="input" name="lorzdms-ai-model" readOnly={ai.kind === "openrouter_decider"} autoComplete="off" spellCheck={false} value={ai.model} onChange={(e) => setAi({ ...ai, model: e.target.value })} /></Field>
              <Field label={`API-Key${s.data.ai_provider?.has_key ? " (gespeichert – leer lassen zum Beibehalten)" : ""}`}><input className="input" type="password" name="lorzdms-ai-api-key" autoComplete="new-password" data-1p-ignore data-lpignore="true" value={ai.api_key} onChange={(e) => setAi({ ...ai, api_key: e.target.value })} /></Field>
            </>}
            {ai.kind === "openrouter_decider" && <p className="text-xs muted">Native Decisions-API für Dokumenttyp, Vertraulichkeit und Ordnerwahl; Extractions-API für belegte Textfelder. Bis zu 254 freigegebene Ordner. Keine Chat-Completions. Bestehende Regeln und Prüfgrenzen bleiben aktiv. Externe KI muss freigegeben sein. Die Alpha-API und kostenlose Modelle unterliegen Verfügbarkeits- und Nutzungslimits.</p>}
            <p className="text-xs muted">Gemini, Azure OpenAI und weitere Anbieter sind über OpenAI-kompatible Endpunkte nutzbar; eigene Adapter folgen.</p>
          </div>
        </Section>
        <Section title="Benutzer">
          <table className="tbl">
            <thead><tr><th>Name</th><th>Rolle</th><th>Zuletzt</th></tr></thead>
            <tbody>
              {(users.data ?? []).map((u) => (
                <tr key={u.id}>
                  <td>{u.display_name || u.name}</td>
                  <td>
                    <select className="input" value={u.role} disabled={u.id === me.id} onChange={(e) => act.run(async () => { await api.send("PATCH", `users/${u.id}`, { role: e.target.value }); users.reload(); })}>
                      <option value="none">kein Zugriff</option><option value="viewer">Lesen</option><option value="editor">Prüfen</option><option value="admin">Administrator</option>
                    </select>
                  </td>
                  <td className="whitespace-nowrap muted">{fmtDate(u.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
        <Section title="System" actions={<>
          <button className="btn" onClick={() => act.run(async () => { await api.send("POST", "processing/pause"); setSaved("Verarbeitung pausiert"); })}>Pausieren</button>
          <button className="btn" onClick={() => act.run(async () => { await api.send("POST", "processing/resume"); setSaved("Verarbeitung fortgesetzt"); })}>Fortsetzen</button>
        </>}>
          <div className="space-y-2 text-sm">
            {Object.entries(s.data.runtime).map(([k, v]) => <div key={k} className="flex justify-between gap-2"><span className="muted">{k}</span><code className="text-xs">{String(v)}</code></div>)}
            <div className="pt-2 h2">Endgültig fehlgeschlagene Jobs: {jobs.data?.stats.by_state.dead ?? 0}</div>
            {(jobs.data?.items ?? []).slice(0, 5).map((j) => <div key={j.id} className="text-xs text-red-600">#{j.id} {j.kind}: {j.last_error}</div>)}
            {(jobs.data?.stats.by_state.dead ?? 0) > 0 && <button className="btn" onClick={() => act.run(async () => { await api.send("POST", "jobs/retry-dead"); jobs.reload(); })}>Erneut versuchen</button>}
            <p className="text-xs muted">Ressourcenlimits (OCR-Zeitlimit, Dateigröße, Verarbeitungsfenster) werden in den App-Optionen von Home Assistant eingestellt.</p>
          </div>
        </Section>
      </div>
    </>
  );
}
