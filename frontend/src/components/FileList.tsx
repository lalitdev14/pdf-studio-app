import { useState } from 'react';
import type { UploadItem } from '../lib/hooks';
import type { Tool } from '../lib/tools';
import { cn, formatBytes, plural } from '../lib/util';
import { Badge, ProgressBar, Spinner } from './ui';
import { ChevronDown, ChevronLeft, ChevronRight, GripVertical, Lock, Trash2, AlertTriangle } from './icons';
import { thumbUrl } from '../lib/api';

type Props = {
  items: UploadItem[];
  tool?: Pick<Tool, 'perFilePages' | 'passwords'>;
  onRemove: (key: string) => void;
  onMove: (from: number, to: number) => void;
  onPatch: (key: string, p: Partial<UploadItem>) => void;
  sortable?: boolean;
};

export function FileList({ items, tool, onRemove, onMove, onPatch, sortable }: Props) {
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  return (
    <ul className="space-y-2">
      {items.map((it, idx) => {
        const needsPw = it.info?.security?.needs_password;
        const unreadable = it.info?.security?.unreadable;
        return (
          <li
            key={it.key}
            draggable={sortable && items.length > 1}
            onDragStart={() => setDrag(idx)}
            onDragOver={(e) => { if (drag !== null) { e.preventDefault(); setOver(idx); } }}
            onDrop={(e) => { e.preventDefault(); if (drag !== null && drag !== idx) onMove(drag, idx); setDrag(null); setOver(null); }}
            onDragEnd={() => { setDrag(null); setOver(null); }}
            className={cn('rounded-xl border bg-white p-3 shadow-card', over === idx && drag !== idx ? 'border-brand-500' : 'border-slate-200', drag === idx && 'opacity-50')}
          >
            <div className="flex items-center gap-3">
              {sortable && items.length > 1 && <GripVertical className="h-5 w-5 shrink-0 cursor-grab text-slate-400" aria-hidden />}
              <div className="flex h-14 w-11 shrink-0 items-center justify-center overflow-hidden rounded border border-slate-200 bg-slate-50">
                {it.status === 'uploading' ? <Spinner className="h-4 w-4" /> : it.record?.kind === 'pdf' && it.info && !needsPw && !unreadable ? (
                  <img src={thumbUrl(it.record.id, 1, 120)} alt="" className="h-full w-full object-contain" loading="lazy" />
                ) : needsPw ? <Lock className="h-5 w-5 text-amber-600" /> : <span className="text-[10px] font-semibold uppercase text-slate-400">{it.name.split('.').pop()}</span>}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-900" title={it.name}>{it.name}</p>
                <p className="text-xs text-slate-500">
                  {formatBytes(it.size)}
                  {it.info?.pages ? ` · ${plural(it.info.pages, 'page')}` : ''}
                </p>
                {it.status === 'uploading' && <ProgressBar value={it.progress} className="mt-1" />}
                {it.status === 'error' && <p className="mt-1 flex items-center gap-1 text-xs text-red-600"><AlertTriangle className="h-3.5 w-3.5" />{it.error}</p>}
                {unreadable && <p className="mt-1 text-xs text-amber-700">This PDF looks damaged. Try the Repair tool first.</p>}
              </div>
              {needsPw && <Badge tone="amber">Password needed</Badge>}
              {sortable && items.length > 1 && (
                <div className="flex">
                  <button aria-label="Move up" className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30" disabled={idx === 0} onClick={() => onMove(idx, idx - 1)}><ChevronLeft className="h-4 w-4 rotate-90" /></button>
                  <button aria-label="Move down" className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30" disabled={idx === items.length - 1} onClick={() => onMove(idx, idx + 1)}><ChevronRight className="h-4 w-4 rotate-90" /></button>
                </div>
              )}
              <button aria-label={`Remove ${it.name}`} className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => onRemove(it.key)}><Trash2 className="h-4 w-4" /></button>
            </div>
            {tool?.passwords && tool.passwords !== 'none' && (needsPw || it.password) && (
              <div className="mt-3">
                <label className="label" htmlFor={`pw-${it.key}`}>Password for this PDF</label>
                <input id={`pw-${it.key}`} type="password" autoComplete="off" className="input" value={it.password} onChange={(e) => onPatch(it.key, { password: e.target.value })} placeholder="Enter the password you were given" />
              </div>
            )}
            {tool?.perFilePages && it.status === 'ready' && (
              <details className="mt-2 text-sm">
                <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-brand-700"><ChevronDown className="h-3.5 w-3.5" />Use only some pages</summary>
                <input aria-label={`Pages of ${it.name}`} className="input mt-2" placeholder="all, or e.g. 1-3,5" value={it.pages} onChange={(e) => onPatch(it.key, { pages: e.target.value })} />
              </details>
            )}
          </li>
        );
      })}
    </ul>
  );
}
