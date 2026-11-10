import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import * as api from '../lib/api';
import { useAuth } from '../lib/auth';
import { useBeforeUnload } from '../lib/hooks';
import { useHealth } from '../lib/health';
import { stash } from '../lib/stash';
import { TOOL_BY_ID } from '../lib/tools';
import type { Tool } from '../lib/tools';
import { cn, errMessage, formatBytes, plural, triggerDownload } from '../lib/util';
import { AnnotationLayer } from '../components/AnnotationLayer';
import type { Ann, EditorTool, LayerApi, Style } from '../components/AnnotationLayer';
import { FileDropzone } from '../components/FileDropzone';
import { OptionsForm, defaultsFor, toOptions } from '../components/OptionsForm';
import type { Values } from '../components/OptionsForm';
import { PdfViewer } from '../components/PdfViewer';
import type { ViewerHandle } from '../components/PdfViewer';
import { SignaturePad } from '../components/SignaturePad';
import { ResultsPanel } from '../components/ResultsPanel';
import { Button, IconButton, Notice, ProgressBar, Spinner } from '../components/ui';
import {
  ArrowUpRight, Calendar, Circle, Download, Highlighter, ImageIcon, Minus, MessageSquare, MousePointer2, Pencil, PenTool,
  Redo2, Save, Share2, Square, Strikethrough, Type, Underline, Undo2, ZoomIn, ZoomOut, Maximize, Trash2,
} from '../components/icons';
import { useToast } from '../components/toast';

type Version = { id: string; label: string; rec: api.ApiFile; info: api.FileInfo };
type Tab = 'edit' | 'annotate' | 'resize' | 'compress' | 'rotate' | 'organize' | 'security' | 'export';

const DEFAULT_STYLE: Style = { font: 'helvetica', bold: false, italic: false, size: 14, color: '#000000', fill: null, stroke_width: 2, opacity: 1 };
const TEXT_TOOLS: { id: EditorTool; label: string; icon: typeof Type }[] = [
  { id: 'select', label: 'Select / move', icon: MousePointer2 },
  { id: 'text', label: 'Add text', icon: Type },
  { id: 'textbox', label: 'Text box', icon: Square },
  { id: 'date', label: 'Date', icon: Calendar },
  { id: 'replace', label: 'Edit existing text', icon: Pencil },
  { id: 'image', label: 'Image', icon: ImageIcon },
  { id: 'comment', label: 'Comment', icon: MessageSquare },
];
const MARK_TOOLS: { id: EditorTool; label: string; icon: typeof Type }[] = [
  { id: 'highlight', label: 'Highlight', icon: Highlighter },
  { id: 'underline', label: 'Underline', icon: Underline },
  { id: 'strike', label: 'Strikethrough', icon: Strikethrough },
  { id: 'freehand', label: 'Draw', icon: PenTool },
  { id: 'rect', label: 'Rectangle', icon: Square },
  { id: 'ellipse', label: 'Ellipse', icon: Circle },
  { id: 'line', label: 'Line', icon: Minus },
  { id: 'arrow', label: 'Arrow', icon: ArrowUpRight },
];

async function imageToDataUrl(file: File, maxDim = 1600): Promise<{ data: string; ratio: number }> {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('That image could not be read.')); i.src = url; });
    const k = Math.min(1, maxDim / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(img.naturalWidth * k)); c.height = Math.max(1, Math.round(img.naturalHeight * k));
    c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height);
    return { data: c.toDataURL('image/png'), ratio: c.width / c.height };
  } finally { URL.revokeObjectURL(url); }
}

export default function EditorPage() {
  const toast = useToast();
  const health = useHealth();
  const { user } = useAuth();
  const viewer = useRef<ViewerHandle>(null);

  const [versions, setVersions] = useState<Version[]>([]);
  const [vIdx, setVIdx] = useState(0);
  const cur = versions[vIdx] ?? null;
  const [loading, setLoading] = useState<string | null>(null);
  const [busyMsg, setBusyMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastJob, setLastJob] = useState<api.Job | null>(null);

  // annotations + history
  const [anns, setAnns] = useState<Ann[]>([]);
  const annsRef = useRef<Ann[]>([]);
  const past = useRef<Ann[][]>([]);
  const future = useRef<Ann[][]>([]);
  const base = useRef<Ann[] | null>(null);
  const [, force] = useState(0);
  const setA = (next: Ann[]) => { annsRef.current = next; setAnns(next); };
  const push = () => { past.current.push(annsRef.current); if (past.current.length > 200) past.current.shift(); future.current = []; force((n) => n + 1); };

  const [tool, setTool] = useState<EditorTool>('select');
  const [style, setStyle] = useState<Style>(DEFAULT_STYLE);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [pendingImage, setPendingImage] = useState<{ data: string; ratio: number } | null>(null);
  const [sigOpen, setSigOpen] = useState(false);
  const imgInput = useRef<HTMLInputElement>(null);

  const [zoom, setZoom] = useState<number | 'fit-width' | 'fit-page'>('fit-width');
  const [scale, setScale] = useState(1);
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState<Tab>('edit');
  const [lines, setLines] = useState<Record<string, api.TextLine[]>>({});
  const [pw, setPw] = useState('');
  const [authorised, setAuthorised] = useState(false);

  useBeforeUnload(anns.length > 0 || !!busyMsg);

  const layerApi: LayerApi = {
    add: (a) => { push(); setA([...annsRef.current, a]); },
    live: (id, patch) => setA(annsRef.current.map((a) => (a.id === id ? { ...a, ...patch } : a))),
    begin: () => { base.current = annsRef.current; },
    end: () => { if (base.current && base.current !== annsRef.current) { past.current.push(base.current); future.current = []; force((n) => n + 1); } base.current = null; },
    remove: (id) => { push(); setA(annsRef.current.filter((a) => a.id !== id)); setSelectedId((s) => (s === id ? null : s)); },
    select: setSelectedId,
    edit: (id) => { if (id) layerApi.begin(); else layerApi.end(); setEditingId(id); },
  };

  const undo = () => { const p = past.current.pop(); if (p) { future.current.push(annsRef.current); setA(p); setSelectedId(null); force((n) => n + 1); } };
  const redo = () => { const f = future.current.pop(); if (f) { past.current.push(annsRef.current); setA(f); setSelectedId(null); force((n) => n + 1); } };

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); }
      else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId) { e.preventDefault(); layerApi.remove(selectedId); }
      else if (e.key === 'Escape') { setSelectedId(null); setTool('select'); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  });

  // ---------------------------------------------------------------- loading files
  const addVersion = useCallback(async (rec: api.ApiFile, label: string) => {
    const info = await api.getInfo(rec.id);
    setVersions((v) => { const next = [...v, { id: rec.id, label, rec, info }]; setVIdx(next.length - 1); return next; });
    return info;
  }, []);

  const openFile = useCallback(async (file: File) => {
    setLoading('Uploading…'); setError(null);
    try {
      const [rec] = await api.uploadFiles([file], (f) => setLoading(`Uploading… ${Math.round(f * 100)}%`));
      await addVersion(rec, 'Original');
    } catch (e) { setError(errMessage(e)); } finally { setLoading(null); }
  }, [addVersion]);

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const f = stash.take().find((x) => x.name.toLowerCase().endsWith('.pdf'));
    if (f) void openFile(f);
  }, [openFile]);

  const needsPw = cur?.info.security?.needs_password;
  const sizes = useMemo(() => (cur?.info.page_sizes ?? []).map((p) => ({ w: p.w, h: p.h })), [cur]);
  const pageCount = cur?.info.pages ?? 0;

  // text lines for "edit existing text"
  useEffect(() => {
    if (tool !== 'replace' || !cur) return;
    [page - 1, page, page + 1].filter((p) => p >= 1 && p <= pageCount).forEach((p) => {
      const key = `${cur.id}:${p}`;
      if (lines[key]) return;
      setLines((l) => ({ ...l, [key]: [] }));
      api.getTextLines(cur.id, p).then((r) => setLines((l) => ({ ...l, [key]: r.lines }))).catch(() => undefined);
    });
  }, [tool, cur, page, pageCount, lines]);

  // ---------------------------------------------------------------- server work
  async function runJob(path: string, options: Record<string, unknown>, fileIds: string[], label: string): Promise<api.Job | null> {
    setError(null); setLastJob(null);
    setBusyMsg(label);
    try {
      let job = await api.runOperation(path, { fileIds, options });
      job = await api.waitForJob(job.id, (j) => setBusyMsg(j.message || label));
      if (job.status !== 'done') throw new Error(job.error?.message ?? 'The operation failed.');
      return job;
    } catch (e) { setError(errMessage(e)); return null; } finally { setBusyMsg(null); }
  }

  async function flush(): Promise<boolean> {
    if (!cur) return false;
    if (!annsRef.current.length) return true;
    const job = await runJob('/api/pdf/edit', { annotations: annsRef.current, ...(pw ? { password: pw } : {}) }, [cur.id], 'Applying your edits…');
    const out = job?.outputs[0];
    if (!job || !out) return false;
    await addVersion({ id: out.id, name: out.name, size: out.size, kind: out.kind, mime: out.mime, url: out.url, expires: 0 }, `Edits (${plural(annsRef.current.length, 'change')})`);
    setA([]); past.current = []; future.current = []; setSelectedId(null); setEditingId(null);
    job.warnings.forEach((w) => toast.info(w));
    return true;
  }

  async function applyTool(t: Tool, values: Values, extra: Record<string, unknown> = {}) {
    if (!cur) return;
    if (!(await flush())) return;
    const latest = versionsRef.current[versionsRef.current.length - 1] ?? cur;
    const options = { ...toOptions(t.fields, values), ...extra };
    const job = await runJob(t.endpoint, options, [latest.id], `${t.title}…`);
    if (!job) return;
    const out = job.outputs[0];
    if (t.id === 'protect' || !out || out.kind !== 'pdf') { setLastJob(job); toast.success(`${t.title} finished.`); return; }
    await addVersion({ id: out.id, name: out.name, size: out.size, kind: out.kind, mime: out.mime, url: out.url, expires: 0 }, t.title);
    setLastJob(job.meta?.message || job.warnings.length ? job : null);
    toast.success(String(job.meta?.message ?? `${t.title} applied.`));
  }
  const versionsRef = useRef<Version[]>([]);
  versionsRef.current = versions;

  async function unlock() {
    if (!cur) return;
    const job = await runJob('/api/pdf/unlock', { password: pw, confirm_authorized: authorised }, [cur.id], 'Unlocking with your password…');
    const out = job?.outputs[0];
    if (out) { await addVersion({ id: out.id, name: out.name, size: out.size, kind: out.kind, mime: out.mime, url: out.url, expires: 0 }, 'Unlocked working copy'); setPw(''); toast.info('This working copy is unprotected. Re-protect it in the Security tab before sharing.'); }
  }

  async function download() {
    if (!(await flush())) return;
    const v = versionsRef.current[versionsRef.current.length - 1];
    if (v) triggerDownload(api.absUrl(v.rec.url), v.rec.name);
  }
  async function share() {
    if (!(await flush())) return;
    const v = versionsRef.current[versionsRef.current.length - 1];
    if (!v) return;
    try {
      await navigator.clipboard.writeText(new URL(api.absUrl(v.rec.url), location.href).toString());
      toast.success('Temporary download link copied. It stops working when the file expires.');
    } catch { toast.error('Could not copy the link.'); }
  }
  async function saveWs() {
    if (!(await flush())) return;
    const v = versionsRef.current[versionsRef.current.length - 1];
    if (!v) return;
    try { await api.saveToWorkspace(v.id); toast.success('Saved to your workspace.'); } catch (e) { toast.error(errMessage(e)); }
  }

  // ---------------------------------------------------------------- style panel
  const selected = anns.find((a) => a.id === selectedId) ?? null;
  const shown: Style = selected ?? style;
  const lastStyleEdit = useRef(0);
  function updateStyle(patch: Partial<Style>) {
    setStyle((s) => ({ ...s, ...patch }));
    if (selected) {
      const now = Date.now();
      if (now - lastStyleEdit.current > 700) push();
      lastStyleEdit.current = now;
      layerApi.live(selected.id, patch);
    }
  }

  async function pickImage(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    try { setPendingImage(await imageToDataUrl(f)); setTool('image'); } catch (e) { toast.error(errMessage(e)); }
  }

  const clearAll = () => { if (!anns.length) return; push(); setA([]); setSelectedId(null); };
  const bump = (d: number) => setZoom(Math.round(Math.min(4, Math.max(0.25, scale + d)) * 100) / 100);

  // ---------------------------------------------------------------- render
  if (!cur) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <h1 className="mb-2 text-2xl font-bold text-slate-900">PDF Editor</h1>
        <p className="mb-6 text-sm text-slate-600">Add text, highlight, draw, insert images and signatures, edit existing text, then resize, compress, protect and export – all in one place.</p>
        {loading ? <div className="flex items-center gap-3 text-slate-600"><Spinner className="h-5 w-5" />{loading}</div> : <FileDropzone accept={['pdf']} multiple={false} onFiles={(f) => void openFile(f[0])} maxMB={health?.limits.max_file_mb ?? 100} />}
        {error && <div className="mt-4"><Notice tone="error">{error}</Notice></div>}
      </div>
    );
  }

  const ToolBtn = ({ t }: { t: { id: EditorTool; label: string; icon: typeof Type } }) => {
    const disabled = t.id === 'replace' && health && !health.features.replace_text;
    return (
      <button
        type="button"
        disabled={!!disabled}
        title={disabled ? 'Editing existing text needs PyMuPDF on the server' : t.label}
        aria-pressed={tool === t.id}
        onClick={() => { if (t.id === 'image') { imgInput.current?.click(); return; } setTool(t.id); }}
        className={cn('flex flex-col items-center gap-1 rounded-lg border p-2 text-[11px] leading-tight transition disabled:cursor-not-allowed disabled:opacity-40', tool === t.id ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50')}
      >
        <t.icon className="h-5 w-5" />{t.label}
      </button>
    );
  };

  const serverTab = (id: string, extraValues?: Record<string, unknown>) => <ServerPanel key={id} tool={TOOL_BY_ID[id]} busy={!!busyMsg} onApply={(v) => applyTool(TOOL_BY_ID[id], v, extraValues)} password={pw} />;
  const tabs: [Tab, string][] = [['edit', 'Edit'], ['annotate', 'Annotate'], ['resize', 'Resize'], ['compress', 'Compress'], ['rotate', 'Rotate'], ['organize', 'Organize'], ['security', 'Security'], ['export', 'Export']];

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col">
      {/* top bar */}
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 bg-white px-3 py-2">
        <span className="mr-2 max-w-[200px] truncate text-sm font-medium text-slate-800" title={cur.rec.name}>{cur.rec.name}</span>
        <span className="mr-2 text-xs text-slate-500">{plural(pageCount, 'page')} · {formatBytes(cur.rec.size)}</span>
        <IconButton label="Undo (Ctrl+Z)" disabled={!past.current.length} onClick={undo}><Undo2 className="h-4 w-4" /></IconButton>
        <IconButton label="Redo (Ctrl+Y)" disabled={!future.current.length} onClick={redo}><Redo2 className="h-4 w-4" /></IconButton>
        <IconButton label="Delete selected" disabled={!selectedId} onClick={() => selectedId && layerApi.remove(selectedId)}><Trash2 className="h-4 w-4" /></IconButton>
        <span className="mx-2 h-5 w-px bg-slate-200" />
        <IconButton label="Zoom out" onClick={() => bump(-0.15)}><ZoomOut className="h-4 w-4" /></IconButton>
        <span className="w-12 text-center text-xs tabular-nums text-slate-600">{Math.round(scale * 100)}%</span>
        <IconButton label="Zoom in" onClick={() => bump(0.15)}><ZoomIn className="h-4 w-4" /></IconButton>
        <IconButton label="Fit width" active={zoom === 'fit-width'} onClick={() => setZoom('fit-width')}><Maximize className="h-4 w-4" /></IconButton>
        <button className="rounded px-2 text-xs text-slate-600 hover:bg-slate-100" onClick={() => setZoom('fit-page')}>Fit page</button>
        <span className="ml-2 text-xs text-slate-500">Page {page} / {pageCount}</span>
        <div className="ml-auto flex items-center gap-2">
          {anns.length > 0 && <span className="text-xs text-amber-700">{plural(anns.length, 'unsaved edit')}</span>}
          <Button size="sm" icon={<Share2 className="h-4 w-4" />} onClick={share} disabled={!!busyMsg}>Share</Button>
          {user && <Button size="sm" icon={<Save className="h-4 w-4" />} onClick={saveWs} disabled={!!busyMsg}>Save</Button>}
          <Button size="sm" variant="primary" icon={<Download className="h-4 w-4" />} onClick={download} disabled={!!busyMsg || !!needsPw}>Download</Button>
        </div>
      </div>
      {busyMsg && <div className="bg-brand-50 px-4 py-1.5"><div className="mx-auto flex max-w-md items-center gap-3 text-xs text-brand-700"><span>{busyMsg}</span><ProgressBar indeterminate className="flex-1" /></div></div>}

      <div className="flex min-h-0 flex-1">
        {/* thumbnails */}
        <aside className="scroll-thin hidden w-32 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-2 md:block" aria-label="Page thumbnails">
          {!needsPw && Array.from({ length: Math.min(pageCount, 300) }, (_, i) => i + 1).map((n) => (
            <button key={n} onClick={() => viewer.current?.scrollToPage(n)} className={cn('mb-2 block w-full rounded-lg border-2 p-1 text-center', page === n ? 'border-brand-600' : 'border-transparent hover:border-slate-300')}>
              <img src={api.thumbUrl(cur.id, n, 160)} alt={`Page ${n}`} loading="lazy" className="mx-auto w-full" />
              <span className="text-[11px] text-slate-600">{n}</span>
            </button>
          ))}
        </aside>

        {/* canvas */}
        <div className="relative min-w-0 flex-1">
          {needsPw ? (
            <div className="mx-auto max-w-md p-8">
              <Notice tone="warn" title="This PDF is password protected">
                <p className="mb-3">Enter the password you were given. PDF Studio never guesses or bypasses passwords. Confirming creates an unprotected working copy so it can be edited.</p>
                <input type="password" className="input mb-2" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
                <label className="mb-3 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5" checked={authorised} onChange={(e) => setAuthorised(e.target.checked)} />I am authorised to open and edit this document.</label>
                <Button variant="primary" disabled={!pw || !authorised || !!busyMsg} onClick={unlock}>Unlock working copy</Button>
              </Notice>
            </div>
          ) : (
            <PdfViewer
              ref={viewer}
              key={cur.id}
              url={api.absUrl(cur.rec.url)}
              pageSizes={sizes}
              zoom={zoom}
              onScaleChange={setScale}
              onPageChange={setPage}
              className="h-full"
              renderOverlay={(o) => (
                <AnnotationLayer
                  page={o.page} width={o.width} height={o.height} scale={o.scale}
                  anns={anns} tool={tool} style={style} selectedId={selectedId} editingId={editingId} pendingImage={pendingImage}
                  textLines={lines[`${cur.id}:${o.page}`]} api={layerApi}
                />
              )}
            />
          )}
          {error && <div className="absolute bottom-4 left-1/2 z-10 w-full max-w-lg -translate-x-1/2 px-4"><Notice tone="error" title="That did not work"><div className="flex items-start justify-between gap-3"><span>{error}</span><button className="text-xs underline" onClick={() => setError(null)}>Dismiss</button></div></Notice></div>}
        </div>

        {/* sidebar */}
        <aside className="scroll-thin w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white">
          <div role="tablist" className="sticky top-0 z-10 flex flex-wrap gap-1 border-b border-slate-200 bg-white p-2">
            {tabs.map(([id, label]) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={cn('rounded-md px-2.5 py-1 text-xs font-medium', tab === id ? 'bg-brand-600 text-white' : 'text-slate-600 hover:bg-slate-100')}>{label}</button>
            ))}
          </div>
          <div className="space-y-4 p-4">
            {(tab === 'edit' || tab === 'annotate') && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  {(tab === 'edit' ? TEXT_TOOLS : MARK_TOOLS).map((t) => <ToolBtn key={t.id} t={t} />)}
                </div>
                {tab === 'edit' && <Button className="w-full" icon={<PenTool className="h-4 w-4" />} onClick={() => setSigOpen(true)}>Draw a signature</Button>}
                {tool === 'replace' && <Notice tone="info">Click a line of existing text on the page, then type the new text. The original is removed from the file, not just covered. Replacement uses a standard font, so the look may differ.</Notice>}
                {tool === 'image' && !pendingImage && <Notice tone="info">Choose an image first.</Notice>}
                <StylePanel style={shown} onChange={updateStyle} type={selected?.type ?? tool} />
                {selected && selected.type === 'comment' && <div><label className="label">Comment text</label><textarea className="input" rows={3} value={selected.text} onChange={(e) => layerApi.live(selected.id, { text: e.target.value })} /></div>}
                {anns.length > 0 && <Button size="sm" variant="ghost" onClick={clearAll}>Remove all unsaved edits</Button>}
                <p className="text-xs text-slate-500">Edits are drawn onto the PDF when you download, or when you use another tab. “Add text” covers the page; it does not erase the text underneath – use “Edit existing text” for that.</p>
              </>
            )}
            {tab === 'resize' && serverTab('resize')}
            {tab === 'compress' && serverTab('compress')}
            {tab === 'rotate' && serverTab('rotate')}
            {tab === 'organize' && (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">Reorder, delete, duplicate or insert pages with the visual page manager. Download your work first – the organizer opens a separate workspace.</p>
                {serverTab('blank-pages')}
                <Link to="/tools/organize" className="inline-block text-sm font-medium text-brand-700 hover:underline">Open the page organizer →</Link>
              </div>
            )}
            {tab === 'security' && (
              <div className="space-y-6">
                {serverTab('protect')}
                {serverTab('watermark')}
                {serverTab('flatten')}
              </div>
            )}
            {tab === 'export' && (
              <div className="space-y-4">
                <Button variant="primary" className="w-full" icon={<Download className="h-4 w-4" />} onClick={download} disabled={!!busyMsg}>Download PDF</Button>
                <div className="flex flex-col gap-1 text-sm">
                  <Link className="text-brand-700 hover:underline" to="/tools/pdf-to-image">Export pages as images →</Link>
                  <Link className="text-brand-700 hover:underline" to="/tools/pdf-to-word">Convert to Word →</Link>
                  <Link className="text-brand-700 hover:underline" to="/tools/page-numbers">Page numbers →</Link>
                  <Link className="text-brand-700 hover:underline" to="/tools/metadata">Edit metadata →</Link>
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-900">Version history</h3>
                  <ul className="space-y-1">
                    {versions.map((v, i) => (
                      <li key={v.id}>
                        <button disabled={!!busyMsg || anns.length > 0} onClick={() => setVIdx(i)} className={cn('flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm', i === vIdx ? 'bg-brand-50 text-brand-700' : 'hover:bg-slate-50')}>
                          <span>{i + 1}. {v.label}</span><span className="text-xs text-slate-500">{formatBytes(v.rec.size)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {vIdx < versions.length - 1 && <p className="mt-2 text-xs text-amber-700">You are viewing an earlier version. Download and Share always use the newest one.</p>}
                  {anns.length > 0 && <p className="mt-2 text-xs text-slate-500">Apply or discard your unsaved edits to switch versions.</p>}
                </div>
              </div>
            )}
            {lastJob && <ResultsPanel job={lastJob} onDeleted={() => setLastJob(null)} />}
          </div>
        </aside>
      </div>

      <input ref={imgInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => { void pickImage(e.target.files); e.target.value = ''; }} />
      <SignaturePad open={sigOpen} onClose={() => setSigOpen(false)} onDone={(data, ratio) => { setPendingImage({ data, ratio }); setTool('image'); setSigOpen(false); toast.info('Click on the page where the signature should go.'); }} />
    </div>
  );
}

function ServerPanel({ tool, onApply, busy, password }: { tool: Tool; onApply: (v: Values) => void; busy: boolean; password: string }) {
  const [values, setValues] = useState<Values>(() => defaultsFor(tool.fields));
  void password;
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-slate-900">{tool.title}</h3>
        <p className="text-xs text-slate-500">{tool.short}</p>
      </div>
      <OptionsForm fields={tool.fields} values={values} onChange={setValues} disabled={busy} />
      <Button className="w-full" variant="primary" disabled={busy} onClick={() => onApply(values)}>Apply {tool.title.toLowerCase()}</Button>
    </div>
  );
}

function StylePanel({ style, onChange, type }: { style: Style; onChange: (p: Partial<Style>) => void; type: string }) {
  const texty = ['text', 'textbox', 'date', 'replace', 'select', 'comment'].includes(type);
  const shapey = ['textbox', 'rect', 'ellipse', 'line', 'arrow', 'freehand', 'underline', 'strike', 'select', 'highlight'].includes(type);
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Style</h3>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-slate-600">Colour <input type="color" className="h-8 w-10 rounded border border-slate-300" value={style.color} onChange={(e) => onChange({ color: e.target.value })} /></label>
        {(type === 'rect' || type === 'ellipse' || type === 'select') && (
          <label className="flex items-center gap-2 text-xs text-slate-600">Fill
            <input type="color" className="h-8 w-10 rounded border border-slate-300" value={style.fill ?? '#ffffff'} onChange={(e) => onChange({ fill: e.target.value })} />
            <button className="text-[11px] text-brand-700 underline" onClick={() => onChange({ fill: null })}>none</button>
          </label>
        )}
      </div>
      {texty && (
        <>
          <div className="grid grid-cols-2 gap-2">
            <select aria-label="Font" className="input" value={style.font} onChange={(e) => onChange({ font: e.target.value as Style['font'] })}>
              <option value="helvetica">Helvetica</option><option value="times">Times</option><option value="courier">Courier</option>
            </select>
            <input aria-label="Font size" className="input" type="number" min={4} max={200} value={style.size} onChange={(e) => onChange({ size: Math.max(3, Number(e.target.value) || 14) })} />
          </div>
          <div className="flex gap-2">
            <button aria-pressed={style.bold} onClick={() => onChange({ bold: !style.bold })} className={cn('h-8 w-8 rounded border text-sm font-bold', style.bold ? 'border-brand-500 bg-brand-50' : 'border-slate-300')}>B</button>
            <button aria-pressed={style.italic} onClick={() => onChange({ italic: !style.italic })} className={cn('h-8 w-8 rounded border text-sm italic', style.italic ? 'border-brand-500 bg-brand-50' : 'border-slate-300')}>I</button>
          </div>
        </>
      )}
      {shapey && (
        <label className="block text-xs text-slate-600">Line width: {style.stroke_width}
          <input type="range" min={0} max={20} step={0.5} className="w-full accent-brand-600" value={style.stroke_width} onChange={(e) => onChange({ stroke_width: Number(e.target.value) })} />
        </label>
      )}
      <label className="block text-xs text-slate-600">Opacity: {Math.round(style.opacity * 100)}%
        <input type="range" min={0.1} max={1} step={0.05} className="w-full accent-brand-600" value={style.opacity} onChange={(e) => onChange({ opacity: Number(e.target.value) })} />
      </label>
    </div>
  );
}
