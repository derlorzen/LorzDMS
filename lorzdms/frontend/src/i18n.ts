const de = {
  dashboard: "Übersicht", review: "Prüfung", documents: "Dokumente", sources: "Quellen", folders: "Ordner",
  rules: "Regeln", settings: "Einstellungen", setup: "Einrichtung", search: "Suchen …", upload: "Hochladen",
  inbox: "Im Eingang", processing: "In Verarbeitung", needs_review: "Zur Prüfung", archived: "Archiviert",
  duplicates: "Duplikate", failed: "Fehlgeschlagen", observed: "Beobachtet", recent: "Neueste Dokumente",
  confirm: "Bestätigen", reanalyze: "Erneut analysieren", skip: "Überspringen", undo: "Rückgängig",
  folder: "Ablageordner", filename: "Dateiname", type: "Dokumenttyp", sender: "Absender", date: "Datum",
  title: "Titel", reasons: "Prüfgründe", text: "Volltext", preview: "Vorschau", journal: "Protokoll",
  metadata: "Metadaten", save: "Speichern", cancel: "Abbrechen", add: "Hinzufügen", remove: "Entfernen",
  sync_now: "Jetzt synchronisieren", status: "Status", last_sync: "Letzte Synchronisierung", none: "–",
  mode: "Verarbeitungsmodus", mode_observe: "Beobachten (keine Änderungen)", mode_review: "Jede Ablage bestätigen",
  mode_auto: "Automatisch ab Schwellenwert", worker: "Hintergrunddienst", no_access: "Kein Zugriff",
  no_access_text: "Ihr Home-Assistant-Benutzer ist für LorzDMS noch nicht freigegeben. Bitte wenden Sie sich an einen LorzDMS-Administrator.",
  open_in_drive: "In Google Drive öffnen", download: "Herunterladen", empty: "Keine Einträge",
  deadlines: "Fristen", cases: "Vorgänge", tags: "Tags", due: "Fällig", overdue: "Überfällig", next_7_days: "Nächste 7 Tage",
  open_cases: "Offene Vorgänge", done: "Erledigt", dismiss: "Verwerfen", reopen: "Wieder öffnen", close_case: "Abschließen",
  new_deadline: "Neue Frist", new_case: "Neuer Vorgang", reference: "Referenz", description: "Beschreibung", kind: "Art",
  remind_days: "Erinnern (Tage vorher)", notifications: "Benachrichtigungen", all: "Alle", open: "Offen",
};
type Dict = typeof de;
const en: Dict = {
  dashboard: "Overview", review: "Review", documents: "Documents", sources: "Sources", folders: "Folders",
  rules: "Rules", settings: "Settings", setup: "Setup", search: "Search …", upload: "Upload",
  inbox: "In inbox", processing: "Processing", needs_review: "Needs review", archived: "Archived",
  duplicates: "Duplicates", failed: "Failed", observed: "Observed", recent: "Recent documents",
  confirm: "Confirm", reanalyze: "Re-analyse", skip: "Skip", undo: "Undo",
  folder: "Target folder", filename: "File name", type: "Document type", sender: "Sender", date: "Date",
  title: "Title", reasons: "Review reasons", text: "Full text", preview: "Preview", journal: "Log",
  metadata: "Metadata", save: "Save", cancel: "Cancel", add: "Add", remove: "Remove",
  sync_now: "Sync now", status: "Status", last_sync: "Last sync", none: "–",
  mode: "Processing mode", mode_observe: "Observe (no changes)", mode_review: "Confirm every filing",
  mode_auto: "Automatic above threshold", worker: "Background worker", no_access: "No access",
  no_access_text: "Your Home Assistant user has not been granted access to LorzDMS yet. Please ask a LorzDMS administrator.",
  open_in_drive: "Open in Google Drive", download: "Download", empty: "No entries",
  deadlines: "Deadlines", cases: "Cases", tags: "Tags", due: "Due", overdue: "Overdue", next_7_days: "Next 7 days",
  open_cases: "Open cases", done: "Done", dismiss: "Dismiss", reopen: "Reopen", close_case: "Close",
  new_deadline: "New deadline", new_case: "New case", reference: "Reference", description: "Description", kind: "Kind",
  remind_days: "Remind (days before)", notifications: "Notifications", all: "All", open: "Open",
};

const lang = (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en";
const dict: Dict = lang === "de" ? de : en;
export const t = (k: keyof Dict): string => dict[k] ?? k;
export const locale = lang === "de" ? "de-DE" : "en-GB";
export const fmtDay = (iso?: string | null) => (iso ? new Date(`${iso}T12:00:00`).toLocaleDateString(locale, { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }) : "–");
export const fmtDate = (iso?: string | null) => (iso ? new Date(iso).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" }) : "–");
