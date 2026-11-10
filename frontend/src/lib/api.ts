// Typed client for the PDF Studio API.

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code = 'error', status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export type ApiFile = {
  id: string;
  name: string;
  size: number;
  kind: string;
  mime: string;
  url: string; // signed, expiring download path
  expires: number;
};

export type PageSize = { w: number; h: number; rotation: number };

export type SecurityInfo = {
  encrypted: boolean;
  needs_password: boolean;
  method?: string;
  allow_print?: boolean;
  allow_copy?: boolean;
  allow_edit?: boolean;
  unreadable?: boolean;
};

export type FileInfo = ApiFile & {
  pages?: number | null;
  page_sizes?: PageSize[];
  metadata?: Record<string, string>;
  security?: SecurityInfo;
};

export type JobOutput = { id: string; name: string; size: number; kind: string; mime: string; url: string };

export type Job = {
  id: string;
  op: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  message: string;
  outputs: JobOutput[];
  error: { code: string; message: string } | null;
  meta: Record<string, any>;
  warnings: string[];
};

export type Health = {
  status: string;
  version: string;
  limits: { max_file_mb: number; max_request_mb: number; max_files: number; max_pages: number; file_ttl_minutes: number };
  features: { ocr: boolean; office: boolean; replace_text: boolean; digital_signature: boolean; heic: boolean };
};

// ---------------------------------------------------------------- auth token
const TOKEN_KEY = 'pdfstudio_token';
let token: string | null = null;
try {
  token = localStorage.getItem(TOKEN_KEY);
} catch {
  /* storage blocked */
}
export function getToken(): string | null {
  return token;
}
export function setToken(t: string | null): void {
  token = t;
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}
const authHeaders = (): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {});

// ------------------------------------------------------------------ helpers
function errorFrom(status: number, data: any): ApiError {
  const msg =
    data?.error?.message ?? (typeof data?.detail === 'string' ? data.detail : undefined) ?? `Request failed (${status})`;
  return new ApiError(msg, data?.error?.code ?? 'error', status);
}

export async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers: { ...authHeaders(), ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 'network');
  }
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) throw errorFrom(res.status, data);
  return data as T;
}

function sendForm(path: string, form: FormData, onProgress?: (frac: number) => void, signal?: AbortSignal): Promise<any> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', API_BASE + path);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      let data: any = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(errorFrom(xhr.status, data));
    };
    xhr.onerror = () => reject(new ApiError('Cannot reach the server. Check your connection and try again.', 'network'));
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'));
    signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(form);
  });
}

// ------------------------------------------------------------------- files
export async function uploadFiles(
  files: File[],
  onProgress?: (frac: number) => void,
  signal?: AbortSignal,
): Promise<ApiFile[]> {
  const form = new FormData();
  files.forEach((f) => form.append('files', f, f.name));
  const data = await sendForm('/api/files', form, onProgress, signal);
  return data.files as ApiFile[];
}

export const getInfo = (id: string) => request<FileInfo>('GET', `/api/files/${id}/info`);
export const getHealth = () => request<Health>('GET', '/api/health');
export const thumbUrl = (id: string, page: number, width = 220) =>
  `${API_BASE}/api/files/${id}/pages/${page}/thumbnail?width=${width}`;
export const absUrl = (path: string) => API_BASE + path;
export const zipUrl = (jobId: string) => `${API_BASE}/api/jobs/${jobId}/zip`;
export type TextLine = { x: number; y: number; w: number; h: number; text: string; size: number };
export const getTextLines = (id: string, page: number) =>
  request<{ page: number; lines: TextLine[] }>('GET', `/api/files/${id}/pages/${page}/text-lines`);

/** Best-effort removal of a server-side copy. `url` is the signed download path. */
export async function deleteFile(url: string): Promise<void> {
  try {
    await request('DELETE', url.replace('/download', ''));
  } catch {
    /* already gone */
  }
}

// -------------------------------------------------------------- operations
export type RunArgs = { files?: File[]; fileIds?: string[]; options?: Record<string, unknown> };

export async function runOperation(
  path: string,
  args: RunArgs,
  onUploadProgress?: (frac: number) => void,
  signal?: AbortSignal,
): Promise<Job> {
  const options = args.options ?? {};
  if (args.files && args.files.length) {
    const form = new FormData();
    args.files.forEach((f) => form.append('files', f, f.name));
    form.append('file_ids', JSON.stringify(args.fileIds ?? []));
    form.append('options', JSON.stringify(options));
    return sendForm(path, form, onUploadProgress, signal);
  }
  return request<Job>('POST', path, { file_ids: args.fileIds ?? [], options }, signal);
}

export const getJob = (id: string) => request<Job>('GET', `/api/jobs/${id}`);
export const cancelJob = (id: string) => request<Job>('POST', `/api/jobs/${id}/cancel`);

export async function waitForJob(id: string, onUpdate?: (j: Job) => void, signal?: AbortSignal): Promise<Job> {
  let delay = 350;
  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const job = await getJob(id);
    onUpdate?.(job);
    if (job.status === 'done' || job.status === 'failed' || job.status === 'cancelled') return job;
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay + 100, 1000);
  }
}

// -------------------------------------------------------------------- auth
export type User = { id: number; email: string };
export type Session = { token: string; user: User };
export const register = (email: string, password: string) => request<Session>('POST', '/api/auth/register', { email, password });
export const login = (email: string, password: string) => request<Session>('POST', '/api/auth/login', { email, password });
export const me = () => request<{ user: User }>('GET', '/api/auth/me');
export const forgotPassword = (email: string) =>
  request<{ message: string; dev_reset_token?: string }>('POST', '/api/auth/forgot', { email });
export const resetPassword = (tokenValue: string, password: string) =>
  request<{ message: string }>('POST', '/api/auth/reset', { token: tokenValue, password });
export const changePassword = (old_password: string, new_password: string) =>
  request<Session>('POST', '/api/auth/password', { old_password, new_password });
export const deleteAccount = (password: string) => request('DELETE', '/api/auth/account', { password });

export type HistoryItem = {
  id: number;
  op: string;
  status: string;
  created: number;
  outputs: { id: string; name: string; size: number }[];
};
export type SavedFile = { id: string; name: string; size: number; kind: string; created: number };
export const getHistory = () => request<{ items: HistoryItem[] }>('GET', '/api/me/history');
export const clearHistory = () => request('DELETE', '/api/me/history');
export const listSaved = () => request<{ files: SavedFile[] }>('GET', '/api/me/files');
export const saveToWorkspace = (file_id: string) => request<SavedFile>('POST', '/api/me/files', { file_id });
export const openSaved = (id: string) => request<ApiFile>('POST', `/api/me/files/${id}/open`);
export const deleteSaved = (id: string) => request('DELETE', `/api/me/files/${id}`);

export async function downloadSaved(f: SavedFile): Promise<void> {
  const res = await fetch(`${API_BASE}/api/me/files/${f.id}/download`, { headers: authHeaders() });
  if (!res.ok) throw errorFrom(res.status, await res.json().catch(() => null));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = f.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
