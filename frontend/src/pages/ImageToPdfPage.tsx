import { useEffect, useMemo, useRef, useState } from 'react';
import type { Tool } from '../lib/tools';
import { useBeforeUnload, useOperation } from '../lib/hooks';
import { stash } from '../lib/stash';
import { acceptExt } from '../lib/tools';
import { cn, fileExt, formatBytes, moveItem, plural, uid } from '../lib/util';
import { FileDropzone } from '../components/FileDropzone';
import { ResultsPanel } from '../components/ResultsPanel';
import { Button, Card, FieldLabel, Notice, ProgressBar } from '../components/ui';
import { ChevronLeft, ChevronRight, RotateCw, Trash2 } from '../components/icons';
import { useHealth } from '../lib/health';
import { ToolHeader } from './ToolPage';

type Img = { key: string; file: File; url: string | null; rot: number; w: number; h: number };

const SIZES_MM: Record<string, [number, number]> = { a3: [297, 420], a4: [210, 297], a5: [148, 210], letter: [215.9, 279.4], legal: [215.9, 355.6] };
const MARGINS: Record<string, number> = { none: 0, small: 10, medium: 20, large: 30 };

export default function ImageToPdfPage({ tool }: { tool: Tool }) {
  const health = useHealth();
  const op = useOperation();
  const [imgs, setImgs] = useState<Img[]>([]);
  const imgsRef = useRef<Img[]>([]);
  imgsRef.current = imgs;
  const [o, setO] = useState({
    mode: 'combined', page_size: 'a4', custom_width_mm: 210, custom_height_mm: 297, orientation: 'portrait', fit: 'fit',
    margin: 'small', margin_mm: 10, background: '#ffffff', quality: 90, page_numbers: false, output_name: '',
  });
  const set = <K extends keyof typeof o>(k: K, v: (typeof o)[K]) => setO((s) => ({ ...s, [k]: v }));
  const [drag, setDrag] = useState<number | null>(null);
  useBeforeUnload(op.isBusy);

  const add = (files: File[]) => {
    const fresh: Img[] = files.map((file) => {
      const canPreview = !['heic', 'heif', 'tif', 'tiff'].includes(fileExt(file.name));
      const img: Img = { key: uid(), file, url: canPreview ? URL.createObjectURL(file) : null, rot: 0, w: 0, h: 0 };
      if (img.url) {
        const el = new Image();
        el.onload = () => setImgs((l) => l.map((i) => (i.key === img.key ? { ...i, w: el.naturalWidth, h: el.naturalHeight } : i)));
        el.src = img.url;
      }
      return img;
    });
    setImgs((l) => [...l, ...fresh].slice(0, tool.maxFiles));
  };

  useEffect(() => {
    const f = stash.take().filter((x) => acceptExt('image').includes(fileExt(x.name)));
    if (f.length) add(f);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => () => imgsRef.current.forEach((i) => i.url && URL.revokeObjectURL(i.url)), []);

  const remove = (key: string) => setImgs((l) => {
    const it = l.find((i) => i.key === key);
    if (it?.url) URL.revokeObjectURL(it.url);
    return l.filter((i) => i.key !== key);
  });
  const rotate = (key: string) => setImgs((l) => l.map((i) => (i.key === key ? { ...i, rot: (i.rot + 90) % 360 } : i)));
  const move = (a: number, b: number) => setImgs((l) => (b < 0 || b >= l.length ? l : moveItem(l, a, b)));

  const totalSize = imgs.reduce((s, i) => s + i.file.size, 0);
  const customBad = o.page_size === 'custom' && !(o.custom_width_mm > 10 && o.custom_height_mm > 10);

  async function run() {
    const options: Record<string, unknown> = {
      mode: o.mode, page_size: o.page_size, orientation: o.orientation, fit: o.fit, margin: o.margin,
      background: o.background, quality: o.quality, page_numbers: o.page_numbers, rotations: imgs.map((i) => i.rot),
    };
    if (o.margin === 'custom') options.margin_mm = o.margin_mm;
    if (o.page_size === 'custom') { options.custom_width_mm = o.custom_width_mm; options.custom_height_mm = o.custom_height_mm; }
    if (o.output_name.trim()) options.output_name = o.output_name.trim();
    await op.run(tool.endpoint, { files: imgs.map((i) => i.file), options });
  }

  // live preview geometry (relative units)
  const preview = useMemo(() => {
    let [pw, ph] = o.page_size === 'custom' ? [o.custom_width_mm || 210, o.custom_height_mm || 297] : SIZES_MM[o.page_size] ?? [210, 297];
    const first = imgs[0];
    if (o.page_size === 'image' && first && first.w) [pw, ph] = first.rot % 180 ? [first.h, first.w] : [first.w, first.h];
    const landscape = o.orientation === 'landscape' || (o.orientation === 'auto' && first && first.w && (first.rot % 180 ? first.h > first.w : first.w > first.h));
    if (o.page_size !== 'image' && landscape !== pw > ph && o.orientation !== 'portrait') [pw, ph] = [ph, pw];
    if (o.page_size !== 'image' && o.orientation === 'portrait' && pw > ph) [pw, ph] = [ph, pw];
    const m = o.page_size === 'image' ? 0 : o.margin === 'custom' ? o.margin_mm : MARGINS[o.margin] ?? 10;
    return { pw, ph, m };
  }, [o, imgs]);

  const job = op.state.job;
  const maxPrev = 260;
  const sc = Math.min(maxPrev / preview.pw, 340 / preview.ph);
  const first = imgs[0];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <ToolHeader tool={tool} />
      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          {imgs.length === 0 ? (
            <FileDropzone accept={acceptExt('image')} onFiles={add} maxMB={health?.limits.max_file_mb ?? 100} hint="JPG, PNG, WEBP, BMP, TIFF, HEIC · up to 200 images" />
          ) : (
            <>
              <div className="flex items-center justify-between text-sm text-slate-600">
                <span>{plural(imgs.length, 'image')} · {formatBytes(totalSize)} · drag to reorder</span>
                <button className="text-red-600 hover:underline" onClick={() => { imgs.forEach((i) => i.url && URL.revokeObjectURL(i.url)); setImgs([]); }}>Remove all</button>
              </div>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {imgs.map((im, idx) => (
                  <li
                    key={im.key}
                    draggable
                    onDragStart={() => setDrag(idx)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => { if (drag !== null && drag !== idx) move(drag, idx); setDrag(null); }}
                    className={cn('group relative rounded-xl border border-slate-200 bg-white p-2 shadow-card', drag === idx && 'opacity-50')}
                  >
                    <div className="flex h-32 items-center justify-center overflow-hidden rounded-lg bg-slate-50">
                      {im.url ? <img src={im.url} alt={im.file.name} className="max-h-full max-w-full object-contain transition-transform" style={{ transform: `rotate(${im.rot}deg)`, maxHeight: im.rot % 180 ? '8rem' : undefined }} /> : <span className="text-xs text-slate-400">No preview ({fileExt(im.file.name).toUpperCase()})</span>}
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-700" title={im.file.name}>{idx + 1}. {im.file.name}</p>
                    <div className="mt-1 flex items-center justify-between">
                      <div className="flex">
                        <button aria-label="Move earlier" disabled={idx === 0} onClick={() => move(idx, idx - 1)} className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
                        <button aria-label="Move later" disabled={idx === imgs.length - 1} onClick={() => move(idx, idx + 1)} className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
                      </div>
                      <div className="flex">
                        <button aria-label="Rotate 90°" onClick={() => rotate(im.key)} className="rounded p-1 text-slate-500 hover:bg-slate-100"><RotateCw className="h-4 w-4" /></button>
                        <button aria-label="Remove image" onClick={() => remove(im.key)} className="rounded p-1 text-slate-500 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <FileDropzone compact accept={acceptExt('image')} onFiles={add} title="Add more images" />
            </>
          )}
        </div>

        <aside className="space-y-4">
          <Card className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-900">Options</h2>
            <FieldLabel label="Output">
              <select className="input" value={o.mode} onChange={(e) => set('mode', e.target.value)}>
                <option value="combined">One PDF with all images</option>
                <option value="separate">One PDF per image (ZIP)</option>
              </select>
            </FieldLabel>
            <FieldLabel label="Page size">
              <select className="input" value={o.page_size} onChange={(e) => set('page_size', e.target.value)}>
                <option value="a4">A4</option><option value="a3">A3</option><option value="a5">A5</option>
                <option value="letter">US Letter</option><option value="legal">US Legal</option>
                <option value="image">Same as image</option><option value="custom">Custom…</option>
              </select>
            </FieldLabel>
            {o.page_size === 'custom' && (
              <div className="grid grid-cols-2 gap-3">
                <FieldLabel label="Width (mm)"><input className="input" type="number" min={11} max={5000} value={o.custom_width_mm} onChange={(e) => set('custom_width_mm', Number(e.target.value))} /></FieldLabel>
                <FieldLabel label="Height (mm)"><input className="input" type="number" min={11} max={5000} value={o.custom_height_mm} onChange={(e) => set('custom_height_mm', Number(e.target.value))} /></FieldLabel>
              </div>
            )}
            {o.page_size !== 'image' && (
              <>
                <FieldLabel label="Orientation">
                  <select className="input" value={o.orientation} onChange={(e) => set('orientation', e.target.value)}>
                    <option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="auto">Automatic (match each image)</option>
                  </select>
                </FieldLabel>
                <FieldLabel label="Image fit">
                  <select className="input" value={o.fit} onChange={(e) => set('fit', e.target.value)}>
                    <option value="fit">Fit inside page (whole image visible)</option><option value="fill">Fill page (may crop)</option><option value="original">Original size (centred)</option>
                  </select>
                </FieldLabel>
                <FieldLabel label="Margin">
                  <select className="input" value={o.margin} onChange={(e) => set('margin', e.target.value)}>
                    <option value="none">None</option><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option><option value="custom">Custom…</option>
                  </select>
                </FieldLabel>
                {o.margin === 'custom' && <FieldLabel label="Margin (mm)"><input className="input" type="number" min={0} max={100} value={o.margin_mm} onChange={(e) => set('margin_mm', Number(e.target.value))} /></FieldLabel>}
                <FieldLabel label="Background colour"><input type="color" className="h-9 w-16 cursor-pointer rounded border border-slate-300 bg-white p-1" value={o.background} onChange={(e) => set('background', e.target.value)} /></FieldLabel>
              </>
            )}
            <FieldLabel label={`JPEG quality: ${o.quality}`} help="Higher keeps more detail and makes a larger file.">
              <input type="range" min={10} max={100} step={5} className="w-full accent-brand-600" value={o.quality} onChange={(e) => set('quality', Number(e.target.value))} />
            </FieldLabel>
            <label className="flex items-center gap-2 text-sm text-slate-800"><input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600" checked={o.page_numbers} onChange={(e) => set('page_numbers', e.target.checked)} />Add page numbers</label>
            <FieldLabel label="File name (optional)"><input className="input" maxLength={120} placeholder="images.pdf" value={o.output_name} onChange={(e) => set('output_name', e.target.value)} /></FieldLabel>

            {first && (
              <div>
                <span className="label">Page preview</span>
                <div className="flex justify-center rounded-lg bg-slate-100 p-3">
                  <div className="relative shadow-card" style={{ width: preview.pw * sc, height: preview.ph * sc, background: o.background }}>
                    {first.url && (
                      <div className="absolute flex items-center justify-center overflow-hidden" style={{ inset: preview.m * sc }}>
                        <img src={first.url} alt="" style={{ transform: `rotate(${first.rot}deg)`, maxWidth: o.fit === 'fill' ? 'none' : '100%', maxHeight: o.fit === 'fill' ? 'none' : '100%', width: o.fit === 'fill' ? '100%' : undefined, height: o.fit === 'fill' ? '100%' : undefined, objectFit: o.fit === 'fill' ? 'cover' : 'contain' }} />
                      </div>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-center text-xs text-slate-500">Approximate preview of the first page</p>
              </div>
            )}

            {op.isBusy ? (
              <div className="space-y-2">
                <ProgressBar value={op.state.progress} indeterminate={op.state.phase === 'queued'} />
                <p className="text-xs text-slate-600">{op.state.message}</p>
                <Button className="w-full" onClick={op.cancel}>Cancel</Button>
              </div>
            ) : (
              <Button variant="primary" size="lg" className="w-full" disabled={!imgs.length || customBad} onClick={run}>Convert to PDF</Button>
            )}
            {op.state.phase === 'failed' && op.state.error && <Notice tone="error" title="That did not work">{op.state.error}</Notice>}
          </Card>
        </aside>
      </div>
      {op.state.phase === 'done' && job && <div className="mt-8"><ResultsPanel job={job} /></div>}
    </div>
  );
}
