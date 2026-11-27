import { useEffect, useState } from "react";
import { api, Deadline, DeadlineSummary, Me } from "../api";
import { fmtDate, t } from "../i18n";
import { DeadlineForm, DeadlineTable } from "../components/Organize";
import { ErrorBox, Field, Notice, Section, Stat, useAction, useApi } from "../ui";

type NotifyStatus = { available: boolean; service: string; enabled: boolean; last_run: { at: string; sent: number; status: string } | null };
type ReminderSettings = { reminders_enabled: boolean; reminder_days_default: number; reminder_hour: number; notify_service: string };

export default function Deadlines({ go, me }: { go: (to: string) => void; me: Me }) {
  const [status, setStatus] = useState("open");
  const list = useApi<{ items: Deadline[]; summary: DeadlineSummary }>(`deadlines?status=${status}`, [status]);
  const canEdit = me.role === "admin" || me.role === "editor";
  const s = list.data?.summary;
  return (
    <>
      <h1 className="h1">{t("deadlines")}</h1>
      <ErrorBox error={list.error} />
      <div className="grid grid-cols-3 gap-3 sm:max-w-xl">
        <Stat label={t("overdue")} value={s?.overdue ?? "–"} tone="text-red-600" onClick={() => setStatus("open")} />
        <Stat label={t("next_7_days")} value={s?.next_7_days ?? "–"} tone="text-amber-600" onClick={() => setStatus("open")} />
        <Stat label={t("open")} value={s?.open ?? "–"} onClick={() => setStatus("open")} />
      </div>
      <Section
        title={t("deadlines")}
        actions={
          <select className="input !w-40" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("status")}>
            <option value="open">{t("open")}</option>
            <option value="done">{t("done")}</option>
            <option value="dismissed">verworfen</option>
            <option value="all">{t("all")}</option>
          </select>
        }
      >
        <DeadlineTable items={list.data?.items ?? []} canEdit={canEdit} onChange={list.reload} go={go} />
      </Section>
      {canEdit && (
        <Section title={t("new_deadline")}>
          <p className="mb-2 text-xs muted">Frist ohne Dokument, z. B. Wiedervorlage oder Kündigungstermin. Fristen zu einem Dokument legen Sie in der Dokumentansicht an.</p>
          <DeadlineForm onSaved={list.reload} />
        </Section>
      )}
      {me.role === "admin" && <ReminderSetup />}
    </>
  );
}

function ReminderSetup() {
  const st = useApi<NotifyStatus>("deadlines/notify-status");
  const settings = useApi<ReminderSettings>("settings");
  const [f, setF] = useState<ReminderSettings | null>(null);
  const act = useAction();
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (settings.data) {
      const { reminders_enabled, reminder_days_default, reminder_hour, notify_service } = settings.data;
      setF({ reminders_enabled, reminder_days_default, reminder_hour, notify_service });
    }
  }, [settings.data]);
  if (!f) return null;
  const save = () => act.run(async () => {
    await api.send("PATCH", "settings", f);
    setMsg("Gespeichert.");
    st.reload();
  });
  const test = () => act.run(async () => {
    await api.send("POST", "deadlines/test-notification");
    setMsg("Testbenachrichtigung gesendet. Bitte in Home Assistant prüfen.");
  });
  const last = st.data?.last_run;
  return (
    <Section title={t("notifications")}>
      <div className="space-y-3">
        {st.data && !st.data.available && (
          <Notice tone="warn">Keine Verbindung zu Home Assistant. Die App braucht die Berechtigung „Home Assistant API“ (ab Version 0.2.0 gesetzt); nach dem Update die App einmal neu starten.</Notice>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Erinnerungen">
            <select className="input" value={f.reminders_enabled ? "1" : "0"} onChange={(e) => setF({ ...f, reminders_enabled: e.target.value === "1" })}>
              <option value="1">aktiv</option>
              <option value="0">aus</option>
            </select>
          </Field>
          <Field label="Dienst in Home Assistant">
            <input className="input" value={f.notify_service} onChange={(e) => setF({ ...f, notify_service: e.target.value.trim() })} placeholder="persistent_notification.create" />
          </Field>
          <Field label="Standard-Vorlauf (Tage)">
            <input className="input" type="number" min={0} max={365} value={f.reminder_days_default} onChange={(e) => setF({ ...f, reminder_days_default: Number(e.target.value) })} />
          </Field>
          <Field label="Frühestens ab (Uhr)">
            <input className="input" type="number" min={0} max={23} value={f.reminder_hour} onChange={(e) => setF({ ...f, reminder_hour: Number(e.target.value) })} />
          </Field>
        </div>
        <p className="text-xs muted">
          <code>persistent_notification.create</code> zeigt die Erinnerung in der Home-Assistant-Seitenleiste. Für Push aufs Handy z. B. <code>notify.mobile_app_&lt;gerät&gt;</code> eintragen.
          Gesendet werden nur Titel und Fälligkeit der Frist, keine Dokumentinhalte. Eine Vorab-Erinnerung kommt am Vorlauftag, eine zweite am Fälligkeitstag.
        </p>
        {last && <p className="text-xs muted">Letzte Prüfung: {fmtDate(last.at)} · {last.status === "ok" ? `${last.sent} gesendet` : "Home Assistant nicht erreichbar"}</p>}
        <ErrorBox error={act.error} />
        {msg && <Notice tone="ok">{msg}</Notice>}
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={act.busy} onClick={save}>{t("save")}</button>
          <button className="btn" disabled={act.busy || !st.data?.available} onClick={test}>Testbenachrichtigung</button>
        </div>
      </div>
    </Section>
  );
}
