import { useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import type { TextLine } from '../lib/api';
import { clamp, uid } from '../lib/util';

export type AnnType =
  | 'text' | 'textbox' | 'date' | 'highlight' | 'underline' | 'strike' | 'rect' | 'ellipse'
  | 'line' | 'arrow' | 'freehand' | 'image' | 'comment' | 'replace';

export type Ann = {
  id: string; type: AnnType; page: number;
  x: number; y: number; w: number; h: number; x2?: number; y2?: number; points?: [number, number][];
  text: string; font: 'helvetica' | 'times' | 'courier'; bold: boolean; italic: boolean; size: number;
  color: string; fill: string | null; stroke_width: number; opacity: number; image?: string;
};

export type EditorTool = 'select' | AnnType;
export type Style = Pick<Ann, 'font' | 'bold' | 'italic' | 'size' | 'color' | 'fill' | 'stroke_width' | 'opacity'>;

export type LayerApi = {
  add: (a: Ann) => void;
  live: (id: string, patch: Partial<Ann>) => void;
  begin: () => void;
  end: () => void;
  remove: (id: string) => void;
  select: (id: string | null) => void;
  edit: (id: string | null) => void;
};

type Props = {
  page: number; width: number; height: number; scale: number;
  anns: Ann[]; tool: EditorTool; style: Style;
  selectedId: string | null; editingId: string | null;
  pendingImage: { data: string; ratio: number } | null;
  textLines?: TextLine[];
  api: LayerApi;
};

const FAMILY = { helvetica: 'Helvetica, Arial, sans-serif', times: '"Times New Roman", Times, serif', courier: '"Courier New", monospace' };
const DRAG_TOOLS: EditorTool[] = ['textbox', 'highlight', 'underline', 'strike', 'rect', 'ellipse', 'line', 'arrow', 'freehand'];
const BOX_TYPES: AnnType[] = ['textbox', 'highlight', 'underline', 'strike', 'rect', 'ellipse', 'image'];

export function newAnn(type: AnnType, page: number, style: Style, extra: Partial<Ann> = {}): Ann {
  return { id: uid(), type, page, x: 0, y: 0, w: 0, h: 0, text: '', ...style, ...extra };
}

export function AnnotationLayer({ page, width, height, scale, anns, tool, style, selectedId, editingId, pendingImage, textLines, api }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState<Ann | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const [hoverLine, setHoverLine] = useState<number | null>(null);
  const drag = useRef<null | { kind: 'move' | 'resize' | 'p1' | 'p2'; id: string; sx: number; sy: number; orig: Ann }>(null);
  const mine = anns.filter((a) => a.page === page);
  const selecting = tool === 'select';

  const frac = (e: { clientX: number; clientY: number }) => {
    const r = root.current!.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
  };

  // ------- creating
  function down(e: RPointerEvent) {
    if (e.button !== 0) return;
    if (selecting) { api.select(null); api.edit(null); return; }
    if (tool === 'replace') return;
    const p = frac(e);
    e.currentTarget.setPointerCapture(e.pointerId);
    api.edit(null);
    if (tool === 'text' || tool === 'date' || tool === 'comment') {
      const text = tool === 'date' ? new Date().toLocaleDateString() : '';
      const a = newAnn(tool, page, style, { x: p.x, y: p.y, text, ...(tool === 'comment' ? { color: '#d97706' } : {}) });
      api.add(a);
      api.select(a.id);
      if (tool !== 'date') api.edit(a.id);
      return;
    }
    if (tool === 'image') {
      if (!pendingImage) return;
      const wf = 0.3;
      const hf = (wf * width) / pendingImage.ratio / height;
      const a = newAnn('image', page, style, { x: clamp(p.x - wf / 2, 0, 1 - wf), y: clamp(p.y - hf / 2, 0, Math.max(0, 1 - hf)), w: wf, h: hf, image: pendingImage.data });
      api.add(a);
      api.select(a.id);
      return;
    }
    if (DRAG_TOOLS.includes(tool)) {
      const t = tool as AnnType;
      const extra: Partial<Ann> = { x: p.x, y: p.y };
      if (t === 'line' || t === 'arrow') { extra.x2 = p.x; extra.y2 = p.y; }
      if (t === 'freehand') extra.points = [[p.x, p.y]];
      if (t === 'highlight') { extra.color = style.color === '#000000' ? '#facc15' : style.color; extra.opacity = 0.4; }
      if (t === 'underline' || t === 'strike') extra.h = 0.02;
      start.current = p;
      setDraft(newAnn(t, page, style, extra));
    }
  }
  function move(e: RPointerEvent) {
    if (!draft) return;
    const p = frac(e);
    const s = start.current;
    if (draft.type === 'line' || draft.type === 'arrow') setDraft({ ...draft, x2: p.x, y2: p.y });
    else if (draft.type === 'freehand') {
      const pts = draft.points ?? [];
      const last = pts[pts.length - 1];
      if (!last || Math.hypot((p.x - last[0]) * width, (p.y - last[1]) * height) > 2) setDraft({ ...draft, points: [...pts, [p.x, p.y]] });
    } else setDraft({ ...draft, x: Math.min(s.x, p.x), y: Math.min(s.y, p.y), w: Math.abs(p.x - s.x), h: draft.type === 'underline' || draft.type === 'strike' ? Math.max(0.012, Math.abs(p.y - s.y)) : Math.abs(p.y - s.y) });
  }
  function up() {
    if (!draft) return;
    const d = { ...draft };
    setDraft(null);
    const pxW = d.w * width, pxH = d.h * height;
    const ok =
      d.type === 'freehand' ? (d.points?.length ?? 0) > 1 :
      d.type === 'line' || d.type === 'arrow' ? Math.hypot(((d.x2 ?? d.x) - d.x) * width, ((d.y2 ?? d.y) - d.y) * height) > 6 :
      d.type === 'textbox' ? pxW > 12 && pxH > 12 : pxW > 6 && (d.type === 'underline' || d.type === 'strike' || pxH > 4);
    if (!ok) {
      if (d.type === 'textbox') { // a click creates a default-size box
        const a = { ...d, w: Math.min(0.35, 1 - d.x), h: Math.min(0.08, 1 - d.y) };
        api.add(a); api.select(a.id); api.edit(a.id);
      }
      return;
    }
    api.add(d);
    api.select(d.id);
    if (d.type === 'textbox') api.edit(d.id);
  }

  // ------- moving / resizing
  function startDrag(e: RPointerEvent, a: Ann, kind: 'move' | 'resize' | 'p1' | 'p2') {
    if (!selecting || editingId === a.id) return;
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    api.select(a.id);
    api.begin();
    const p = frac(e);
    drag.current = { kind, id: a.id, sx: p.x, sy: p.y, orig: a };
  }
  function dragMove(e: RPointerEvent) {
    const d = drag.current;
    if (!d) return;
    const p = frac(e);
    const dx = p.x - d.sx, dy = p.y - d.sy;
    const o = d.orig;
    if (d.kind === 'move') {
      const patch: Partial<Ann> = { x: o.x + dx, y: o.y + dy };
      if (o.x2 !== undefined && o.y2 !== undefined) { patch.x2 = o.x2 + dx; patch.y2 = o.y2 + dy; }
      if (o.points) patch.points = o.points.map(([px, py]) => [px + dx, py + dy]);
      api.live(o.id, patch);
    } else if (d.kind === 'resize') api.live(o.id, { w: Math.max(0.01, o.w + dx), h: Math.max(0.01, o.h + dy) });
    else if (d.kind === 'p1') api.live(o.id, { x: o.x + dx, y: o.y + dy });
    else api.live(o.id, { x2: (o.x2 ?? o.x) + dx, y2: (o.y2 ?? o.y) + dy });
  }
  function dragEnd() {
    if (drag.current) { drag.current = null; api.end(); }
  }

  // ------- rendering helpers
  const px = (a: Ann) => ({ left: a.x * width, top: a.y * height });
  const fontPx = (a: Ann) => a.size * scale;
  const textStyle = (a: Ann): React.CSSProperties => ({
    fontFamily: FAMILY[a.font], fontWeight: a.bold ? 700 : 400, fontStyle: a.italic ? 'italic' : 'normal', fontSize: fontPx(a), color: a.color, opacity: a.opacity, lineHeight: 1.2, whiteSpace: 'pre-wrap',
  });
  const interact = selecting;

  const renderShape = (a: Ann, isDraft = false) => {
    const sw = Math.max(0.5, a.stroke_width * scale);
    const common = { opacity: a.type === 'highlight' ? (a.opacity < 1 ? a.opacity : 0.35) : a.opacity, style: { pointerEvents: interact && !isDraft ? ('all' as const) : ('none' as const), cursor: interact ? 'move' : undefined } };
    const h = (k: 'move') => ({ onPointerDown: (e: RPointerEvent) => startDrag(e, a, k) });
    const X = a.x * width, Y = a.y * height, W = a.w * width, H = a.h * height;
    switch (a.type) {
      case 'highlight': return <rect key={a.id} x={X} y={Y} width={W} height={H} fill={a.color} {...common} {...h('move')} />;
      case 'underline': return <line key={a.id} x1={X} x2={X + W} y1={Y + H} y2={Y + H} stroke={a.color} strokeWidth={sw} strokeLinecap="round" {...common} {...h('move')} />;
      case 'strike': return <line key={a.id} x1={X} x2={X + W} y1={Y + H / 2} y2={Y + H / 2} stroke={a.color} strokeWidth={sw} strokeLinecap="round" {...common} {...h('move')} />;
      case 'rect': return <rect key={a.id} x={X} y={Y} width={W} height={H} stroke={a.stroke_width > 0 ? a.color : 'none'} strokeWidth={sw} fill={a.fill ?? 'none'} fillOpacity={a.fill ? Math.min(a.opacity, 0.6) : 0} {...common} {...h('move')} />;
      case 'ellipse': return <ellipse key={a.id} cx={X + W / 2} cy={Y + H / 2} rx={W / 2} ry={H / 2} stroke={a.stroke_width > 0 ? a.color : 'none'} strokeWidth={sw} fill={a.fill ?? 'none'} fillOpacity={a.fill ? Math.min(a.opacity, 0.6) : 0} {...common} {...h('move')} />;
      case 'line':
      case 'arrow': {
        const x2 = (a.x2 ?? a.x) * width, y2 = (a.y2 ?? a.y) * height;
        const ang = Math.atan2(y2 - Y, x2 - X);
        const hs = Math.max(9, a.stroke_width * 4.5) * scale;
        return (
          <g key={a.id} {...common} {...h('move')}>
            <line x1={X} y1={Y} x2={x2} y2={y2} stroke={a.color} strokeWidth={sw} strokeLinecap="round" />
            {a.type === 'arrow' && <polygon fill={a.color} points={`${x2},${y2} ${x2 - hs * Math.cos(ang - 0.4)},${y2 - hs * Math.sin(ang - 0.4)} ${x2 - hs * Math.cos(ang + 0.4)},${y2 - hs * Math.sin(ang + 0.4)}`} />}
            <line x1={X} y1={Y} x2={x2} y2={y2} stroke="transparent" strokeWidth={Math.max(12, sw)} />
          </g>
        );
      }
      case 'freehand':
        return <polyline key={a.id} fill="none" stroke={a.color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" points={(a.points ?? []).map(([fx, fy]) => `${fx * width},${fy * height}`).join(' ')} {...common} {...h('move')} />;
      default: return null;
    }
  };

  const selected = mine.find((a) => a.id === selectedId) ?? null;
  const shapes = mine.filter((a) => !['text', 'textbox', 'date', 'image', 'comment', 'replace'].includes(a.type));
  const boxes = mine.filter((a) => ['text', 'textbox', 'date', 'image', 'comment', 'replace'].includes(a.type));

  function selectionBox() {
    if (!selected || ['text', 'date', 'comment', 'textbox', 'image', 'replace'].includes(selected.type)) return null;
    let x0: number, y0: number, x1: number, y1: number;
    if (selected.type === 'line' || selected.type === 'arrow') { x0 = Math.min(selected.x, selected.x2 ?? selected.x); x1 = Math.max(selected.x, selected.x2 ?? selected.x); y0 = Math.min(selected.y, selected.y2 ?? selected.y); y1 = Math.max(selected.y, selected.y2 ?? selected.y); }
    else if (selected.type === 'freehand') { const xs = (selected.points ?? []).map((p) => p[0]); const ys = (selected.points ?? []).map((p) => p[1]); x0 = Math.min(...xs); x1 = Math.max(...xs); y0 = Math.min(...ys); y1 = Math.max(...ys); }
    else { x0 = selected.x; y0 = selected.y; x1 = selected.x + selected.w; y1 = selected.y + selected.h; }
    return { x0: x0 * width - 3, y0: y0 * height - 3, x1: x1 * width + 3, y1: y1 * height + 3 };
  }
  const sb = selectionBox();
  const hasSize = (a: Ann) => BOX_TYPES.includes(a.type);
  const cursor = selecting ? 'default' : tool === 'replace' ? 'default' : tool === 'text' ? 'text' : 'crosshair';

  return (
    <div
      ref={root}
      className="absolute inset-0 select-none"
      style={{ cursor, touchAction: selecting ? 'auto' : 'none' }}
      onPointerDown={down}
      onPointerMove={(e) => { move(e); dragMove(e); }}
      onPointerUp={() => { up(); dragEnd(); }}
      onPointerCancel={() => { setDraft(null); dragEnd(); }}
    >
      <svg className="pointer-events-none absolute inset-0" width={width} height={height}>
        {shapes.map((a) => renderShape(a))}
        {draft && renderShape(draft, true)}
        {sb && selected && (
          <g style={{ pointerEvents: 'none' }}>
            <rect x={sb.x0} y={sb.y0} width={sb.x1 - sb.x0} height={sb.y1 - sb.y0} fill="none" stroke="#4f46e5" strokeDasharray="4 3" />
          </g>
        )}
      </svg>

      {boxes.map((a) => {
        const sel = a.id === selectedId;
        const editing = a.id === editingId;
        const pos = px(a);
        const ring = sel ? { outline: '1.5px dashed #4f46e5', outlineOffset: 2 } : {};
        if (a.type === 'image') {
          return <img key={a.id} src={a.image} alt="" draggable={false} onPointerDown={(e) => startDrag(e, a, 'move')} style={{ position: 'absolute', ...pos, width: a.w * width, height: a.h * height, opacity: a.opacity, cursor: interact ? 'move' : undefined, pointerEvents: interact ? 'auto' : 'none', ...ring }} />;
        }
        if (a.type === 'comment') {
          return (
            <div key={a.id} onPointerDown={(e) => startDrag(e, a, 'move')} onDoubleClick={() => api.edit(a.id)} title={a.text || 'Comment'}
              className="absolute flex h-7 w-7 items-center justify-center rounded-md bg-amber-300 text-xs font-bold text-amber-900 shadow"
              style={{ ...pos, cursor: interact ? 'move' : undefined, pointerEvents: interact ? 'auto' : 'none', ...ring }}>💬</div>
          );
        }
        const box = a.type === 'textbox' || a.type === 'replace';
        const content = editing ? (
          <textarea
            autoFocus
            value={a.text}
            placeholder={a.type === 'replace' ? '' : 'Type here'}
            onChange={(e) => api.live(a.id, { text: e.target.value })}
            onBlur={() => { api.edit(null); if (!a.text.trim() && a.type !== 'replace') api.remove(a.id); }}
            onPointerDown={(e) => e.stopPropagation()}
            className="resize-none overflow-hidden border-0 bg-white/80 p-0 outline-none"
            style={{ ...textStyle(a), width: box ? '100%' : Math.max(120, (a.text.split('\n').reduce((m, l) => Math.max(m, l.length), 0) + 2) * fontPx(a) * 0.6), height: box ? '100%' : Math.max(1, a.text.split('\n').length) * fontPx(a) * 1.25 + 4 }}
          />
        ) : <span style={textStyle(a)}>{a.text || (a.type === 'text' ? '' : '')}</span>;
        return (
          <div
            key={a.id}
            onPointerDown={(e) => startDrag(e, a, 'move')}
            onDoubleClick={() => interact && api.edit(a.id)}
            className="absolute"
            style={{
              ...pos,
              width: box ? a.w * width : undefined, height: box ? a.h * height : undefined, minWidth: 8, minHeight: 8,
              padding: a.type === 'textbox' ? 4 * scale : 0,
              border: a.type === 'textbox' ? `${Math.max(0.5, a.stroke_width / 2) * scale}px solid ${a.color}` : a.type === 'replace' ? '1px dashed #059669' : undefined,
              background: a.type === 'replace' ? '#fff' : undefined,
              cursor: interact ? (editing ? 'text' : 'move') : undefined, pointerEvents: interact ? 'auto' : 'none', ...ring,
            }}
          >
            {content}
          </div>
        );
      })}

      {/* handles */}
      {selected && interact && editingId !== selected.id && (
        <>
          {hasSize(selected) && <div role="presentation" onPointerDown={(e) => startDrag(e, selected, 'resize')} className="absolute h-3 w-3 cursor-nwse-resize rounded-sm border-2 border-brand-600 bg-white" style={{ left: (selected.x + selected.w) * width - 6, top: (selected.y + selected.h) * height - 6 }} />}
          {(selected.type === 'line' || selected.type === 'arrow') && (
            <>
              <div role="presentation" onPointerDown={(e) => startDrag(e, selected, 'p1')} className="absolute h-3 w-3 cursor-move rounded-full border-2 border-brand-600 bg-white" style={{ left: selected.x * width - 6, top: selected.y * height - 6 }} />
              <div role="presentation" onPointerDown={(e) => startDrag(e, selected, 'p2')} className="absolute h-3 w-3 cursor-move rounded-full border-2 border-brand-600 bg-white" style={{ left: (selected.x2 ?? selected.x) * width - 6, top: (selected.y2 ?? selected.y) * height - 6 }} />
            </>
          )}
        </>
      )}

      {/* pick-existing-text overlay for "Edit text" */}
      {tool === 'replace' && textLines?.map((l, i) => (
        <button
          key={i}
          type="button"
          title={`Edit: ${l.text}`}
          onMouseEnter={() => setHoverLine(i)}
          onMouseLeave={() => setHoverLine(null)}
          onClick={() => {
            const a = newAnn('replace', page, style, { x: l.x, y: l.y, w: l.w, h: l.h, text: l.text, size: l.size, color: '#000000', opacity: 1 });
            api.add(a); api.select(a.id); api.edit(a.id);
          }}
          className="absolute rounded-sm"
          style={{ left: l.x * width, top: l.y * height, width: l.w * width, height: l.h * height, background: hoverLine === i ? 'rgba(79,70,229,.18)' : 'rgba(79,70,229,.06)', outline: '1px solid rgba(79,70,229,.35)' }}
        />
      ))}
    </div>
  );
}
