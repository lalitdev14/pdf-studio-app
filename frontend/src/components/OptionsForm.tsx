import type { Field } from '../lib/tools';
import { condMet } from '../lib/tools';
import { FieldLabel } from './ui';

export type Values = Record<string, string | number | boolean>;

export function defaultsFor(fields: Field[]): Values {
  const v: Values = {};
  for (const f of fields) v[f.key] = f.default;
  return v;
}

/** Convert form state into the JSON the backend models expect. Empty optional strings are dropped. */
export function toOptions(fields: Field[], values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (!condMet(f.showIf, values)) continue;
    const raw = values[f.key];
    switch (f.type) {
      case 'select':
        out[f.key] = f.numeric ? Number(raw) : raw;
        break;
      case 'number':
      case 'range':
        out[f.key] = Number(raw);
        break;
      case 'intlist':
        out[f.key] = String(raw).split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => Number.isFinite(n));
        break;
      case 'text':
      case 'textarea':
      case 'password':
        if (String(raw) !== '' || f.sendEmpty) out[f.key] = raw;
        break;
      default:
        out[f.key] = raw;
    }
  }
  return out;
}

export function OptionsForm({
  fields, values, onChange, disabled,
}: { fields: Field[]; values: Values; onChange: (v: Values) => void; disabled?: boolean }) {
  const set = (k: string, v: string | number | boolean) => onChange({ ...values, [k]: v });
  return (
    <div className="space-y-4">
      {fields.filter((f) => condMet(f.showIf, values)).map((f) => {
        const id = `opt-${f.key}`;
        if (f.type === 'checkbox') {
          return (
            <label key={f.key} className="flex cursor-pointer items-start gap-2 text-sm text-slate-800">
              <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" checked={Boolean(values[f.key])} disabled={disabled} onChange={(e) => set(f.key, e.target.checked)} />
              <span>
                {f.label}
                {f.help && <span className="block text-xs text-slate-500">{f.help}</span>}
              </span>
            </label>
          );
        }
        return (
          <FieldLabel key={f.key} label={f.label} help={f.help}>
            {f.type === 'select' ? (
              <select id={id} className="input" disabled={disabled} value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)}>
                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : f.type === 'number' ? (
              <input id={id} className="input" type="number" disabled={disabled} min={f.min} max={f.max} step={f.step ?? 1} value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value === '' ? '' : Number(e.target.value))} />
            ) : f.type === 'range' ? (
              <div className="flex items-center gap-3">
                <input id={id} type="range" className="flex-1 accent-brand-600" disabled={disabled} min={f.min} max={f.max} step={f.step} value={Number(values[f.key])} onChange={(e) => set(f.key, Number(e.target.value))} />
                <span className="w-14 text-right text-sm tabular-nums text-slate-700">{String(values[f.key])}{f.unit ?? ''}</span>
              </div>
            ) : f.type === 'color' ? (
              <input id={id} type="color" className="h-9 w-16 cursor-pointer rounded border border-slate-300 bg-white p-1" disabled={disabled} value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)} />
            ) : f.type === 'textarea' ? (
              <textarea id={id} className="input min-h-[80px]" disabled={disabled} placeholder={f.placeholder} value={String(values[f.key])} onChange={(e) => set(f.key, e.target.value)} />
            ) : (
              <input
                id={id}
                className="input"
                disabled={disabled}
                type={f.type === 'password' ? 'password' : 'text'}
                autoComplete={f.type === 'password' ? 'new-password' : 'off'}
                placeholder={'placeholder' in f ? f.placeholder : undefined}
                value={String(values[f.key])}
                onChange={(e) => set(f.key, e.target.value)}
              />
            )}
          </FieldLabel>
        );
      })}
    </div>
  );
}
