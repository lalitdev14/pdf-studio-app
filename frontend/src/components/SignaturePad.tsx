import { useEffect, useRef, useState } from 'react';
import { Button, Modal } from './ui';

type Props = { open: boolean; onClose: () => void; onDone: (dataUrl: string, ratio: number) => void };

/** Draw a signature with mouse, touch or pen. Returns a transparent PNG cropped to the ink. */
export function SignaturePad({ open, onClose, onDone }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [empty, setEmpty] = useState(true);
  const [color, setColor] = useState('#111827');

  useEffect(() => {
    if (open) setEmpty(true);
  }, [open]);
  useEffect(() => {
    const c = ref.current;
    if (!open || !c) return;
    c.getContext('2d')?.clearRect(0, 0, c.width, c.height);
  }, [open]);

  const pos = (e: React.PointerEvent) => {
    const c = ref.current!;
    const r = c.getBoundingClientRect();
    return { x: ((e.clientX - r.left) * c.width) / r.width, y: ((e.clientY - r.top) * c.height) / r.height };
  };
  const down = (e: React.PointerEvent) => {
    const c = ref.current!;
    c.setPointerCapture(e.pointerId);
    drawing.current = true;
    const ctx = c.getContext('2d')!;
    const p = pos(e);
    ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + 0.1, p.y + 0.1); ctx.stroke();
    setEmpty(false);
  };
  const move = (e: React.PointerEvent) => {
    if (!drawing.current) return;
    const ctx = ref.current!.getContext('2d')!;
    const p = pos(e);
    ctx.lineTo(p.x, p.y); ctx.stroke();
  };
  const clear = () => { const c = ref.current!; c.getContext('2d')!.clearRect(0, 0, c.width, c.height); setEmpty(true); };

  function done() {
    const c = ref.current!;
    const ctx = c.getContext('2d')!;
    const { data, width, height } = ctx.getImageData(0, 0, c.width, c.height);
    let x0 = width, y0 = height, x1 = 0, y1 = 0;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (data[(y * width + x) * 4 + 3] > 0) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    if (x1 <= x0 || y1 <= y0) return;
    const pad = 6;
    x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(width - 1, x1 + pad); y1 = Math.min(height - 1, y1 + pad);
    const out = document.createElement('canvas');
    out.width = x1 - x0 + 1; out.height = y1 - y0 + 1;
    out.getContext('2d')!.drawImage(c, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    onDone(out.toDataURL('image/png'), out.width / out.height);
  }

  return (
    <Modal open={open} onClose={onClose} title="Draw your signature">
      <canvas ref={ref} width={700} height={260} onPointerDown={down} onPointerMove={move} onPointerUp={() => { drawing.current = false; }} className="w-full touch-none rounded-lg border border-slate-300 bg-white" style={{ cursor: 'crosshair' }} aria-label="Signature drawing area" />
      <div className="mt-3 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-600">Ink <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-8 w-10 rounded border border-slate-300" /></label>
        <Button size="sm" onClick={clear}>Clear</Button>
        <div className="ml-auto flex gap-2"><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={empty} onClick={done}>Place on page</Button></div>
      </div>
      <p className="mt-2 text-xs text-slate-500">This places a visual signature image. For a cryptographic digital signature use the Sign tool.</p>
    </Modal>
  );
}
