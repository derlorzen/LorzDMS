import { useState } from "react";
import { useApi } from "../ui";

type Item = { id: string; name: string };

// Navigiert lesend durch die Drive-Ordner eines Kontos.
export default function FolderPicker({ accountId, onPick }: { accountId: number; onPick: (id: string, path: string) => void }) {
  const [stack, setStack] = useState<Item[]>([{ id: "root", name: "Meine Ablage" }]);
  const cur = stack[stack.length - 1];
  const list = useApi<Item[]>(`google/accounts/${accountId}/folders?parent=${encodeURIComponent(cur.id)}`, [cur.id, accountId]);
  const path = stack.slice(1).map((s) => s.name).join("/");
  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-800">
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-2 py-1.5 text-xs dark:border-slate-800">
        {stack.map((s, i) => (
          <button key={s.id} className="hover:underline" onClick={() => setStack(stack.slice(0, i + 1))}>{i > 0 && "/ "}{s.name}</button>
        ))}
      </div>
      <ul className="max-h-64 overflow-auto text-sm">
        {list.loading && <li className="px-3 py-2 muted">…</li>}
        {list.error && <li className="px-3 py-2 text-red-600">{list.error}</li>}
        {(list.data ?? []).map((f) => (
          <li key={f.id} className="flex items-center justify-between px-3 py-1 hover:bg-slate-50 dark:hover:bg-slate-800/50">
            <button className="flex-1 text-left" onClick={() => setStack([...stack, f])}>📁 {f.name}</button>
          </li>
        ))}
        {list.data?.length === 0 && <li className="px-3 py-2 muted">Keine Unterordner</li>}
      </ul>
      {cur.id !== "root" && (
        <div className="border-t border-slate-200 p-2 dark:border-slate-800">
          <button className="btn btn-primary" onClick={() => onPick(cur.id, path)}>„{path}“ auswählen</button>
        </div>
      )}
    </div>
  );
}
