import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Tool } from '../lib/tools';
import { useBeforeUnload, useOperation, useUploads } from '../lib/hooks';
import { stash } from '../lib/stash';
import { cn, plural, uid } from '../lib/util';
import { thumbUrl } from '../lib/api';
import { FileDropzone } from '../components/FileDropzone';
import { ResultsPanel } from '../components/ResultsPanel';
import { Button, Card, Notice, ProgressBar } from '../components/ui';
import { Copy, FileText, Lock, Plus, Redo2, RotateCcw, RotateCw, Trash2, Undo2 } from '../components/icons';
import { useHealth } from '../lib/health';
import { ToolHeader } from './ToolPage';

type Entry = { id: string; src: number; page: number; rotate: number };
type Snap = { entries: Entry[]; sel: string[] };

export default function OrganizePage({ tool }: { tool: Tool }) {
  const health = useHealth();
  const op = useOperation();
  const srcs = useUploads(21); // srcs.items[0] is the document, the rest are insert sources
  const [snap, setSnap] = useState<Snap>({ entries: [], sel: [] });
  const past = useRef<Snap[]>([]);
  const future = useRef<Snap[]>([]);
  const [, bump] = useState(0);
  const [drag, setDrag] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const loaded = useRef<Set<string>>(new Set());
  const started = useRef(false);
  useBeforeUnload(op.isBusy);

  const commit = useCallback((next: Snap) => {
    past.current.push(snap);
    if (past.current.length > 100) past.current.shift();
    future.current = [];
    setSnap(next);
  }, [snap]);
  const undo = () => { const p = past.current.pop(); if (p) { future.current.push(snap); setSnap(p); bump((n) => n + 1); } };
  const redo = () => { const f = future.current.pop(); if (f) { past.current.push(snap); setSnap(f); bump((n) => n + 1); } };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const f = stash.take().filter((x) => x.name.toLowerCase().endsWith('.pdf'));
    if (f.length) srcs.add(f.slice(0, 1));
  }, [srcs]);

  // when a source finishes loading, append (main doc) its pages
  useEffect(() => {
    srcs.items.forEach((it, idx) => {
      if (it.status !== 'ready' || !it.info?.pages || loaded.current.has(it.key)) return;
      if (it.info.security?.needs_password) return;
      loaded.current.add(it.key);
      if (idx === 0) {
        const entries = Array.from({ length: it.info.pages }, (_, i) => ({ id: uid(), src: 0, page: i + 1, rotate: 0 }));
        past.current = []; future.current = [];
        setSnap({ entries, sel: [] });
      }
    });
  }, [srcs.items]);

  const main = srcs.items[0];
  const needsPw = srcs.items.filter((i) => i.info?.security?.needs_password);
  const toggle = (id: string, multi: boolean) => setSnap((s) => ({ ...s, sel: multi ? (s.sel.includes(id) ? s.sel.filter((x) => x !== id) : [...s.sel, id]) : s.sel.length === 1 && s.sel[0] === id ? [] : [id] }));
  const selSet = useMemo(() => new Set(snap.sel), [snap.sel]);
  const targets = (id?: string) => (id ? [id] : snap.sel);

  const rotate = (delta: number, id?: string) => {
    const t = new Set(targets(id));
    if (!t.size) return;
    commit({ ...snap, entries: snap.entries.map((e) => (t.has(e.id) ? { ...e, rotate: (e.rotate + delta + 360) % 360 } : e)) });
  };
  const del = (id?: string) => {
    const t = new Set(targets(id));
    if (!t.size) return;
    if (t.size >= snap.entries.length) return;
    commit({ entries: snap.entries.filter((e) => !t.has(e.id)), sel: snap.sel.filter((x) => !t.has(x)) });
  };
  const dup = (id?: string) => {
    const t = new Set(targets(id));
    if (!t.size) return;
    const out: Entry[] = [];
    for (const e of snap.entries) { out.push(e); if (t.has(e.id)) out.push({ ...e, id: uid() }); }
    commit({ ...snap, entries: out });
  };
  const keepOnly = () => {
    if (!snap.sel.length) return;
    commit({ entries: snap.entries.filter((e) => selSet.has(e.id)), sel: [] });
  };
  const reverse = () => commit({ ...snap, entries: [...snap.entries].reverse() });
  const dropOn = (targetId: string) => {
    if (!drag || drag === targetId) return;
    const ids = selSet.has(drag) ? snap.entries.filter((e) => selSet.has(e.id)).map((e) => e.id) : [drag];
    if (ids.includes(targetId)) return;
    const moving = snap.entries.filter((e) => ids.includes(e.id));
    const rest = snap.entries.filter((e) => !ids.includes(e.id));
    const at = rest.findIndex((e) => e.id === targetId);
    const origTarget = snap.entries.findIndex((e) => e.id === targetId);
    const origDrag = snap.entries.findIndex((e) => e.id === drag);
    const insertAt = origDrag < origTarget ? at + 1 : at; // dragging forward drops after the target
    commit({ ...snap, entries: [...rest.slice(0, insertAt), ...moving, ...rest.slice(insertAt)] });
  };

  // insert pages from another PDF after the last selected page (or at the end)
  const [insertFor, setInsertFor] = useState<number | null>(null);
  const addSource = (files: File[]) => srcs.add(files);
  const insertSource = (idx: number) => {
    const it = srcs.items[idx];
    if (!it?.info?.pages) return;
    const pagesN = it.info.pages;
    const add: Entry[] = Array.from({ length: pagesN }, (_, i) => ({ id: uid(), src: idx, page: i + 1, rotate: 0 }));
    let at = snap.entries.length;
    if (snap.sel.length) at = Math.max(...snap.sel.map((id) => snap.entries.findIndex((e) => e.id === id))) + 1;
    commit({ ...snap, entries: [...snap.entries.slice(0, at), ...add, ...snap.entries.slice(at)] });
    setInsertFor(null);
  };

  const unusedSources = new Set(snap.entries.map((e) => e.src));
  const canRun = snap.entries.length > 0 && !needsPw.some((i) => !i.password) && srcs.items.every((i) => i.status === 'ready');

  async function run() {
    // only send sources that are referenced; renumber src indexes
    const used = [...unusedSources].sort((a, b) => a - b);
    const map = new Map(used.map((s, i) => [s, i]));
    const ids = used.map((s) => srcs.items[s].record!.id);
    const passwords = used.map((s) => srcs.items[s].password);
    await op.run(tool.endpoint, {
      fileIds: ids,
      options: { pages: snap.entries.map((e) => ({ src: map.get(e.src)!, page: e.page, rotate: e.rotate })), passwords },
    });
  }

  const job = op.state.job;
  const total = snap.entries.length;
  const origTotal = main?.info?.pages ?? 0;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <ToolHeader tool={tool} />
      {!main ? (
        <FileDropzone accept={['pdf']} multiple={false} onFiles={srcs.add} maxMB={health?.limits.max_file_mb ?? 100} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-card">
            <span className="flex items-center gap-1.5 px-2 text-sm text-slate-700"><FileText className="h-4 w-4 text-slate-400" /><span className="max-w-[200px] truncate">{main.name}</span></span>
            <span className="text-xs text-slate-500">{plural(total, 'page')}{origTotal && total !== origTotal ? ` (was ${origTotal})` : ''}</span>
            <div className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" />
            <Button size="sm" icon={<Undo2 className="h-4 w-4" />} disabled={!past.current.length} onClick={undo}>Undo</Button>
            <Button size="sm" icon={<Redo2 className="h-4 w-4" />} disabled={!future.current.length} onClick={redo}>Redo</Button>
            <div className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" />
            <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} disabled={!snap.sel.length} onClick={() => rotate(-90)}>Left</Button>
            <Button size="sm" icon={<RotateCw className="h-4 w-4" />} disabled={!snap.sel.length} onClick={() => rotate(90)}>Right</Button>
            <Button size="sm" icon={<Copy className="h-4 w-4" />} disabled={!snap.sel.length} onClick={() => dup()}>Duplicate</Button>
            <Button size="sm" icon={<Trash2 className="h-4 w-4" />} disabled={!snap.sel.length || snap.sel.length >= total} onClick={() => del()}>Delete</Button>
            <Button size="sm" disabled={!snap.sel.length || snap.sel.length >= total} onClick={keepOnly}>Keep only selected</Button>
            <Button size="sm" onClick={reverse}>Reverse</Button>
            <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setInsertFor(-1)}>Insert PDF…</Button>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="ghost" onClick={() => setSnap((s) => ({ ...s, sel: snap.entries.map((e) => e.id) }))}>Select all</Button>
              <Button size="sm" variant="ghost" disabled={!snap.sel.length} onClick={() => setSnap((s) => ({ ...s, sel: [] }))}>Clear</Button>
            </div>
          </div>

          {insertFor !== null && (
            <Card className="space-y-3 p-4">
              <p className="text-sm font-medium text-slate-800">Insert all pages of another PDF {snap.sel.length ? 'after the selected page' : 'at the end'}</p>
              {srcs.items.slice(1).filter((i) => i.status === 'ready' && i.info?.pages && !i.info.security?.needs_password).map((it) => {
                const idx = srcs.items.indexOf(it);
                return <div key={it.key} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm"><span className="truncate">{it.name} · {plural(it.info!.pages!, 'page')}</span><Button size="sm" variant="primary" onClick={() => insertSource(idx)}>Insert</Button></div>;
              })}
              {srcs.items.length < 21 && <FileDropzone compact multiple={false} accept={['pdf']} onFiles={addSource} title="Choose a PDF to insert" />}
              <Button size="sm" variant="ghost" onClick={() => setInsertFor(null)}>Close</Button>
            </Card>
          )}

          {needsPw.length > 0 && (
            <Notice tone="warn" title="Password required">
              {needsPw.map((i) => (
                <div key={i.key} className="mt-2 flex items-center gap-2"><Lock className="h-4 w-4" /><span className="truncate">{i.name}</span>
                  <input type="password" className="input max-w-xs" placeholder="Password" value={i.password} onChange={(e) => srcs.patch(i.key, { password: e.target.value })} />
                  <Button size="sm" onClick={() => { loaded.current.delete(i.key); void import('../lib/api').then(async (api) => { const info = await api.getInfo(i.record!.id).catch(() => null); srcs.patch(i.key, { info: info ?? i.info }); }); }}>Retry</Button>
                </div>
              ))}
              <p className="mt-2 text-xs">PDF Studio can only open protected files when you provide the password. Locked pages are previewed after the server unlocks them for processing.</p>
            </Notice>
          )}

          <p className="text-xs text-slate-500">Click pages to select (Ctrl/⌘-click for several), drag to reorder. Changes are applied when you press “Apply changes”.</p>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6" aria-label="Pages">
            {snap.entries.map((e, i) => {
              const src = srcs.items[e.src];
              const rec = src?.record;
              return (
                <li
                  key={e.id}
                  draggable
                  onDragStart={() => setDrag(e.id)}
                  onDragOver={(ev) => { ev.preventDefault(); setOverId(e.id); }}
                  onDragLeave={() => setOverId((o) => (o === e.id ? null : o))}
                  onDrop={() => { dropOn(e.id); setDrag(null); setOverId(null); }}
                  onDragEnd={() => { setDrag(null); setOverId(null); }}
                  className={cn('group relative rounded-xl border-2 bg-white p-2 shadow-card transition', selSet.has(e.id) ? 'border-brand-600 ring-2 ring-brand-200' : 'border-transparent', overId === e.id && drag !== e.id && 'border-dashed border-brand-500', drag === e.id && 'opacity-40')}
                  onClick={(ev) => toggle(e.id, ev.ctrlKey || ev.metaKey || ev.shiftKey)}
                >
                  <div className="flex h-32 items-center justify-center overflow-hidden rounded bg-slate-50">
                    {rec && !src.info?.security?.needs_password ? (
                      <img src={thumbUrl(rec.id, e.page, 200)} alt={`Page ${e.page}`} loading="lazy" draggable={false} className="max-h-full max-w-full object-contain transition-transform" style={{ transform: `rotate(${e.rotate}deg)`, maxHeight: e.rotate % 180 ? '7rem' : undefined, maxWidth: e.rotate % 180 ? '7rem' : undefined }} />
                    ) : <Lock className="h-6 w-6 text-slate-300" />}
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-slate-600">
                    <span>{i + 1}{e.src > 0 && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">ext</span>}</span>
                    <span className="hidden gap-0.5 group-hover:flex group-focus-within:flex">
                      <button aria-label={`Rotate page ${i + 1}`} className="rounded p-0.5 hover:bg-slate-100" onClick={(ev) => { ev.stopPropagation(); rotate(90, e.id); }}><RotateCw className="h-3.5 w-3.5" /></button>
                      <button aria-label={`Duplicate page ${i + 1}`} className="rounded p-0.5 hover:bg-slate-100" onClick={(ev) => { ev.stopPropagation(); dup(e.id); }}><Copy className="h-3.5 w-3.5" /></button>
                      <button aria-label={`Delete page ${i + 1}`} disabled={total <= 1} className="rounded p-0.5 text-red-600 hover:bg-red-50 disabled:opacity-30" onClick={(ev) => { ev.stopPropagation(); del(e.id); }}><Trash2 className="h-3.5 w-3.5" /></button>
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="sticky bottom-0 z-10 -mx-4 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
            {op.isBusy ? (
              <div className="mx-auto flex max-w-md items-center gap-3"><ProgressBar value={op.state.progress} indeterminate={op.state.phase === 'queued'} className="flex-1" /><Button onClick={op.cancel}>Cancel</Button></div>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-600">{plural(total, 'page')} in the new document</span>
                <Button variant="primary" size="lg" disabled={!canRun} onClick={run}>Apply changes</Button>
              </div>
            )}
            {op.state.phase === 'failed' && op.state.error && <div className="mt-2"><Notice tone="error" title="That did not work">{op.state.error}</Notice></div>}
          </div>
        </div>
      )}
      {op.state.phase === 'done' && job && <div className="mt-6"><ResultsPanel job={job} /></div>}
    </div>
  );
}
