// Alle Aufrufe relativ (Ingress-Basispfad steht im <base href>).
export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      code = body.code;
    } catch {
      /* keine JSON-Antwort */
    }
    throw new ApiError(res.status, msg, code);
  }
  return res.json() as Promise<T>;
}

const H = { "X-Requested-With": "lorzdms" };

export const api = {
  get: <T,>(path: string) => fetch(`api/${path}`, { credentials: "same-origin" }).then((r) => handle<T>(r)),
  send: <T,>(method: string, path: string, body?: unknown) =>
    fetch(`api/${path}`, {
      method,
      credentials: "same-origin",
      headers: { ...H, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  form: <T,>(path: string, data: FormData) =>
    fetch(`api/${path}`, { method: "POST", credentials: "same-origin", headers: H, body: data }).then((r) => handle<T>(r)),
};

export type Doc = {
  id: number;
  source_kind: string;
  original_filename: string;
  mime_type: string | null;
  state: string;
  title: string | null;
  document_type: string | null;
  sender: string | null;
  document_date: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
  email_meta?: Record<string, unknown> | null;
  confidence: number | null;
  decision: {
    folder_drive_id?: string | null;
    confidence?: number;
    review_reasons?: string[];
    rules?: { id: number; name: string }[];
    ai?: { provider: string; model: string; reasoning?: string; uncertainties?: string[]; alternatives?: string[] } | null;
  } | null;
  target_folder_drive_id: string | null;
  target_folder_path: string | null;
  target_name: string | null;
  drive_file_id: string | null;
  drive_web_link: string | null;
  ocr_used: number;
  page_count: number | null;
  error: string | null;
  created_at: string;
  archived_at: string | null;
  duplicate_of: number | null;
  visibility: string;
  operations?: { id: number; kind: string; status: string; new_name: string; created_at: string }[];
  has_local_file?: boolean;
};

export type Folder = { id: number; account_id: number; drive_id: string; name: string; path: string; role: string; description: string | null };
export type Me = { id: number; name: string; role: "none" | "viewer" | "editor" | "admin" };
