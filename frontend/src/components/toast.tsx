import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, X, XCircle } from './icons';
import { uid } from '../lib/util';

type Kind = 'success' | 'error' | 'info';
type ToastItem = { id: string; kind: Kind; message: string };
type Api = { success: (m: string) => void; error: (m: string) => void; info: (m: string) => void };

const Ctx = createContext<Api>({ success: () => {}, error: () => {}, info: () => {} });
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: string) => setItems((l) => l.filter((t) => t.id !== id)), []);
  const push = useCallback(
    (kind: Kind, message: string) => {
      const id = uid();
      setItems((l) => [...l.slice(-3), { id, kind, message }]);
      setTimeout(() => dismiss(id), kind === 'error' ? 8000 : 4500);
    },
    [dismiss],
  );
  const api = useMemo<Api>(
    () => ({ success: (m) => push('success', m), error: (m) => push('error', m), info: (m) => push('info', m) }),
    [push],
  );
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-pop">
            {t.kind === 'success' ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" /> : t.kind === 'error' ? <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" /> : <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />}
            <p className="flex-1 text-sm text-slate-800">{t.message}</p>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-slate-400 hover:text-slate-700">
              <X className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
