import { useMemo } from 'react';
import { thumbUrl } from '../lib/api';
import { cn, pagesToRanges, rangesToPages } from '../lib/util';

type Props = {
  fileId: string;
  pages: number;
  selected: number[];
  onChange: (sel: number[]) => void;
  max?: number;
};

/** Visual page picker. Click toggles a page, shift-click selects a range. */
export function PagePicker({ fileId, pages, selected, onChange, max = 400 }: Props) {
  const set = useMemo(() => new Set(selected), [selected]);
  const shown = Math.min(pages, max);
  let last = -1;
  const click = (n: number, shift: boolean) => {
    const next = new Set(set);
    if (shift && last > 0) {
      const [a, b] = [Math.min(last, n), Math.max(last, n)];
      for (let i = a; i <= b; i++) next.add(i);
    } else if (next.has(n)) next.delete(n);
    else next.add(n);
    last = n;
    onChange([...next].sort((x, y) => x - y));
  };
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <button type="button" className="font-medium text-brand-700 hover:underline" onClick={() => onChange(Array.from({ length: pages }, (_, i) => i + 1))}>Select all</button>
        <span className="text-slate-300">|</span>
        <button type="button" className="font-medium text-brand-700 hover:underline" onClick={() => onChange([])}>Clear</button>
        <span className="ml-auto text-slate-500">{selected.length} of {pages} selected</span>
      </div>
      <div className="grid max-h-80 grid-cols-3 gap-2 overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-2 scroll-thin sm:grid-cols-4">
        {Array.from({ length: shown }, (_, i) => i + 1).map((n) => (
          <button
            key={n}
            type="button"
            onClick={(e) => click(n, e.shiftKey)}
            aria-pressed={set.has(n)}
            className={cn('relative overflow-hidden rounded-lg border-2 bg-white p-1 text-center transition', set.has(n) ? 'border-brand-600 ring-2 ring-brand-200' : 'border-transparent hover:border-slate-300')}
          >
            <img src={thumbUrl(fileId, n, 160)} alt={`Page ${n}`} loading="lazy" className="mx-auto h-28 w-full object-contain" />
            <span className="mt-1 block text-[11px] text-slate-600">{n}</span>
          </button>
        ))}
      </div>
      {pages > max && <p className="mt-1 text-xs text-slate-500">Only the first {max} thumbnails are shown – type ranges for the rest.</p>}
    </div>
  );
}

export const selectionToSpec = (sel: number[]) => (sel.length ? pagesToRanges(sel) : '');
export const specToSelection = (spec: string, total: number) => {
  const s = spec.trim().toLowerCase();
  if (!s) return [];
  if (s === 'all') return Array.from({ length: total }, (_, i) => i + 1);
  try { return rangesToPages(s, total); } catch { return []; }
};
