import { useState } from "react";
import { api, Me, TagCount } from "../api";
import { t } from "../i18n";
import { ErrorBox, Notice, Section, useAction, useApi } from "../ui";

export default function Tags({ go, me }: { go: (to: string) => void; me: Me }) {
  const list = useApi<{ items: TagCount[] }>("tags");
  const [edit, setEdit] = useState<{ old: string; value: string } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const act = useAction();
  const isAdmin = me.role === "admin";
  const rename = (old: string, value: string | null) => act.run(async () => {
    const r = await api.send<{ changed: number }>("POST", "tags/rename", { old, new: value });
    setMsg(value ? `„${old}“ in ${r.changed} Dokument(en) zu „${value}“ geändert.` : `„${old}“ aus ${r.changed} Dokument(en) entfernt.`);
    setEdit(null);
    list.reload();
  });
  return (
    <>
      <h1 className="h1">{t("tags")}</h1>
      <p className="text-sm muted">Tags vergibt die KI bei der Analyse, Regeln können welche setzen, und Sie können sie in der Dokumentansicht ändern. Klicken Sie auf einen Tag, um die Dokumente zu sehen.</p>
      <ErrorBox error={list.error || act.error} />
      {msg && <Notice tone="ok">{msg}</Notice>}
      <Section title={`${t("tags")} (${list.data?.items.length ?? 0})`}>
        {list.data?.items.length === 0 && <p className="text-sm muted">{t("empty")}</p>}
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {(list.data?.items ?? []).map((x) => (
            <li key={x.tag} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              {edit?.old === x.tag ? (
                <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); if (edit.value.trim()) rename(x.tag, edit.value.trim()); }}>
                  <input className="input max-w-xs" autoFocus maxLength={40} value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />
                  <button className="btn btn-primary" disabled={act.busy}>{t("save")}</button>
                  <button type="button" className="btn" onClick={() => setEdit(null)}>{t("cancel")}</button>
                </form>
              ) : (
                <button className="text-left text-brand-600 hover:underline" onClick={() => go(`documents?tag=${encodeURIComponent(x.tag)}`)}>
                  {x.tag} <span className="muted">({x.count})</span>
                </button>
              )}
              {isAdmin && edit?.old !== x.tag && (
                <span className="flex gap-1">
                  <button className="btn !px-2 !py-0.5 text-xs" onClick={() => setEdit({ old: x.tag, value: x.tag })}>Umbenennen</button>
                  <button className="btn btn-danger !px-2 !py-0.5 text-xs" disabled={act.busy}
                    onClick={() => window.confirm(`Tag „${x.tag}“ aus ${x.count} Dokument(en) entfernen? Die Dokumente selbst bleiben unverändert.`) && rename(x.tag, null)}>
                    {t("remove")}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
        {isAdmin && <p className="mt-3 text-xs muted">Umbenennen auf einen bereits vorhandenen Tag führt beide zusammen.</p>}
      </Section>
    </>
  );
}
