import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from './api';
import { errMessage, moveItem, uid } from './util';
import { useToast } from '../components/toast';

// ------------------------------------------------------------ running a tool
export type OpPhase = 'idle' | 'uploading' | 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
export type OpState = { phase: OpPhase; progress: number; message: string; job: api.Job | null; error: string | null };
const IDLE: OpState = { phase: 'idle', progress: 0, message: '', job: null, error: null };

export function useOperation() {
  const [state, setState] = useState<OpState>(IDLE);
  const abort = useRef<AbortController | null>(null);
  const jobId = useRef<string | null>(null);
  const busy = useRef(false);

  const run = useCallback(async (path: string, args: api.RunArgs): Promise<api.Job | null> => {
    if (busy.current) return null; // never process the same request twice
    busy.current = true;
    const ctrl = new AbortController();
    abort.current = ctrl;
    jobId.current = null;
    setState({ phase: 'uploading', progress: 0, message: 'Uploading…', job: null, error: null });
    try {
      let job = await api.runOperation(
        path, args,
        (f) => setState((s) => ({ ...s, phase: 'uploading', progress: f * 100, message: 'Uploading…' })),
        ctrl.signal,
      );
      jobId.current = job.id;
      job = await api.waitForJob(
        job.id,
        (j) => setState({ phase: j.status === 'queued' ? 'queued' : j.status === 'running' ? 'running' : 'running', progress: j.progress, message: j.message, job: j, error: null }),
        ctrl.signal,
      );
      if (job.status === 'done') setState({ phase: 'done', progress: 100, message: 'Done', job, error: null });
      else if (job.status === 'cancelled') setState({ ...IDLE, phase: 'cancelled', message: 'Cancelled' });
      else setState({ phase: 'failed', progress: 0, message: '', job, error: job.error?.message ?? 'The operation failed.' });
      return job;
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        setState({ ...IDLE, phase: 'cancelled', message: 'Cancelled' });
      } else {
        setState({ ...IDLE, phase: 'failed', error: errMessage(e) });
      }
      return null;
    } finally {
      busy.current = false;
    }
  }, []);

  const cancel = useCallback(async () => {
    abort.current?.abort();
    if (jobId.current) {
      try {
        await api.cancelJob(jobId.current);
      } catch {
        /* job already finished */
      }
    }
  }, []);

  const reset = useCallback(() => setState(IDLE), []);
  const isBusy = state.phase === 'uploading' || state.phase === 'queued' || state.phase === 'running';
  return { state, run, cancel, reset, isBusy };
}

// ----------------------------------------------------------------- uploads
export type UploadItem = {
  key: string;
  name: string;
  size: number;
  status: 'uploading' | 'ready' | 'error';
  progress: number;
  error?: string;
  record?: api.ApiFile;
  info?: api.FileInfo;
  password: string;
  pages: string; // per-file page selection (merge)
};

export function useUploads(max: number) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const ref = useRef<UploadItem[]>([]);
  const toast = useToast();
  ref.current = items;

  const patch = useCallback((key: string, p: Partial<UploadItem>) => {
    setItems((l) => l.map((i) => (i.key === key ? { ...i, ...p } : i)));
  }, []);

  const upload = useCallback(
    async (key: string, file: File) => {
      try {
        const [rec] = await api.uploadFiles([file], (f) => patch(key, { progress: f * 100 }));
        let info: api.FileInfo | undefined;
        if (rec.kind === 'pdf') {
          try {
            info = await api.getInfo(rec.id);
          } catch {
            /* damaged PDFs still upload (Repair tool); no preview available */
          }
        }
        patch(key, { status: 'ready', progress: 100, record: rec, info });
      } catch (e) {
        patch(key, { status: 'error', error: errMessage(e) });
      }
    },
    [patch],
  );

  const add = useCallback(
    (files: File[]) => {
      const room = max - ref.current.length;
      if (files.length > room) toast.error(room <= 0 ? `You can add at most ${max} file(s) here.` : `Only ${room} more file(s) fit – extra files were skipped.`);
      const take = files.slice(0, Math.max(0, room));
      const fresh: UploadItem[] = take.map((f) => ({ key: uid(), name: f.name, size: f.size, status: 'uploading', progress: 0, password: '', pages: '' }));
      if (!fresh.length) return;
      setItems((l) => [...l, ...fresh]);
      fresh.forEach((it, i) => void upload(it.key, take[i]));
    },
    [max, toast, upload],
  );

  const remove = useCallback((key: string) => {
    const it = ref.current.find((i) => i.key === key);
    if (it?.record) void api.deleteFile(it.record.url);
    setItems((l) => l.filter((i) => i.key !== key));
  }, []);

  const move = useCallback((from: number, to: number) => setItems((l) => moveItem(l, from, to)), []);

  const replaceWith = useCallback(async (rec: api.ApiFile) => {
    const key = uid();
    setItems([{ key, name: rec.name, size: rec.size, status: 'uploading', progress: 100, password: '', pages: '' }]);
    try {
      const info = rec.kind === 'pdf' ? await api.getInfo(rec.id) : undefined;
      patch(key, { status: 'ready', record: rec, info });
    } catch (e) {
      patch(key, { status: 'error', error: errMessage(e) });
    }
  }, [patch]);

  const clear = useCallback(() => {
    ref.current.forEach((i) => i.record && void api.deleteFile(i.record.url));
    setItems([]);
  }, []);

  return { items, add, remove, move, patch, replaceWith, clear };
}

/** Warn before leaving while work is in flight. */
export function useBeforeUnload(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [active]);
}
