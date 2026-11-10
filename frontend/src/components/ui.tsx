import { useEffect, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '../lib/util';
import { Loader2, X } from './icons';

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = 'secondary', size = 'md', loading, icon, className, children, disabled, ...rest }: BtnProps) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50';
  const variants = {
    primary: 'bg-brand-600 text-white shadow-sm hover:bg-brand-700',
    secondary: 'border border-slate-300 bg-white text-slate-800 shadow-sm hover:bg-slate-50',
    ghost: 'text-slate-700 hover:bg-slate-100',
    danger: 'bg-red-600 text-white shadow-sm hover:bg-red-700',
  }[variant];
  const sizes = { sm: 'h-8 px-3 text-xs', md: 'h-10 px-4 text-sm', lg: 'h-12 px-6 text-base' }[size];
  return (
    <button className={cn(base, variants, sizes, className)} disabled={disabled || loading} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({
  label, className, children, active, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-40',
        active && 'bg-brand-50 text-brand-700 ring-1 ring-brand-200',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-2xl border border-slate-200 bg-white shadow-card', className)}>{children}</div>;
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' | 'brand' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700', green: 'bg-emerald-50 text-emerald-700', amber: 'bg-amber-50 text-amber-800',
    red: 'bg-red-50 text-red-700', brand: 'bg-brand-50 text-brand-700',
  }[tone];
  return <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', tones)}>{children}</span>;
}

export function ProgressBar({ value, indeterminate, className }: { value?: number; indeterminate?: boolean; className?: string }) {
  return (
    <div className={cn('h-2 w-full overflow-hidden rounded-full bg-slate-200', className)} role="progressbar" aria-valuenow={Math.round(value ?? 0)} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={cn('h-full rounded-full bg-brand-600 transition-all duration-300', indeterminate && 'w-1/3 animate-pulse')}
        style={indeterminate ? undefined : { width: `${Math.max(2, Math.min(100, value ?? 0))}%` }}
      />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-5 w-5 animate-spin text-brand-600', className)} />;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className={cn('relative w-full rounded-2xl bg-white p-6 shadow-pop', wide ? 'max-w-2xl' : 'max-w-md')}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <IconButton label="Close" onClick={onClose}>
            <X className="h-5 w-5" />
          </IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

export function FieldLabel({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {help && <span className="mt-1 block text-xs text-slate-500">{help}</span>}
    </label>
  );
}

export function Notice({ tone, title, children }: { tone: 'error' | 'warn' | 'info' | 'success'; title?: string; children: ReactNode }) {
  const t = {
    error: 'border-red-200 bg-red-50 text-red-800', warn: 'border-amber-200 bg-amber-50 text-amber-900',
    info: 'border-brand-200 bg-brand-50 text-brand-700', success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  }[tone];
  return (
    <div className={cn('rounded-xl border px-4 py-3 text-sm', t)} role={tone === 'error' ? 'alert' : 'status'}>
      {title && <div className="mb-0.5 font-semibold">{title}</div>}
      {children}
    </div>
  );
}
