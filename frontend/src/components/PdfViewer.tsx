import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode, type RefObject } from 'react';
import { pdfjs } from '../lib/pdfjs';
import type { PDFDocumentProxy, RenderTask } from '../lib/pdfjs';
import { cn } from '../lib/util';
import { Spinner } from './ui';

export type ViewerHandle = { scrollToPage: (n: number) => void };
export type OverlayProps = { page: number; width: number; height: number; scale: number };

type Props = {
  url: string;
  pageSizes: { w: number; h: number }[]; // visible size of each page in points
  zoom: number | 'fit-width' | 'fit-page';
  onScaleChange?: (s: number) => void;
  onPageChange?: (p: number) => void;
  renderOverlay?: (p: OverlayProps) => ReactNode;
  className?: string;
};

function usePdfDoc(url: string) {
  const [state, setState] = useState<{ doc: PDFDocumentProxy | null; error: string | null }>({ doc: null, error: null });
  useEffect(() => {
    let cancelled = false;
    setState({ doc: null, error: null });
    const task = pdfjs.getDocument({ url });
    task.promise
      .then((d) => {
        if (cancelled) void d.destroy();
        else setState({ doc: d, error: null });
      })
      .catch((e: Error) => {
        if (!cancelled) setState({ doc: null, error: e?.name === 'PasswordException' ? 'This PDF is password protected. Unlock it first.' : 'This PDF could not be displayed.' });
      });
    return () => {
      cancelled = true;
      void task.destroy().catch(() => undefined);
    };
  }, [url]);
  return state;
}

const MAX_CANVAS_PIXELS = 16_000_000;

function PageView({
  doc, pageNumber, width, height, scale, root, children,
}: {
  doc: PDFDocumentProxy; pageNumber: number; width: number; height: number; scale: number;
  root: RefObject<HTMLDivElement>; children?: ReactNode;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => setVisible(entries.some((e) => e.isIntersecting)), {
      root: root.current, rootMargin: '900px 0px',
    });
    io.observe(el);
    return () => io.disconnect();
  }, [root]);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    if (!visible) {
      c.width = 0; // release the bitmap for pages far from the viewport
      c.height = 0;
      return;
    }
    let cancelled = false;
    let task: RenderTask | null = null;
    (async () => {
      const page = await doc.getPage(pageNumber);
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const dpr = window.devicePixelRatio || 1;
      const s = Math.min(scale * dpr, Math.sqrt(MAX_CANVAS_PIXELS / (base.width * base.height)));
      const viewport = page.getViewport({ scale: s });
      c.width = Math.floor(viewport.width);
      c.height = Math.floor(viewport.height);
      c.style.width = `${width}px`;
      c.style.height = `${height}px`;
      const ctx = c.getContext('2d');
      if (!ctx) return;
      task = page.render({ canvasContext: ctx, viewport });
      await task.promise;
    })().catch((e: Error) => {
      if (e?.name !== 'RenderingCancelledException') console.error('PDF render failed', e);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [visible, doc, pageNumber, scale, width, height]);

  return (
    <div ref={wrap} data-page={pageNumber} className="relative mx-auto bg-white shadow-card ring-1 ring-slate-200" style={{ width, height }}>
      <canvas ref={canvas} className="block" />
      {children}
    </div>
  );
}

export const PdfViewer = forwardRef<ViewerHandle, Props>(function PdfViewer(
  { url, pageSizes, zoom, onScaleChange, onPageChange, renderOverlay, className }, ref,
) {
  const { doc, error } = usePdfDoc(url);
  const container = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 800, h: 600 });
  const lastPage = useRef(0);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setBox({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const maxW = Math.max(1, ...pageSizes.map((s) => s.w));
  const first = pageSizes[0] ?? { w: 595, h: 842 };
  const scale =
    typeof zoom === 'number'
      ? zoom
      : zoom === 'fit-width'
        ? Math.max(0.1, (box.w - 48) / maxW)
        : Math.max(0.1, Math.min((box.w - 48) / first.w, (box.h - 48) / first.h));

  useEffect(() => onScaleChange?.(scale), [scale, onScaleChange]);

  const scrollToPage = useCallback((n: number) => {
    const c = container.current;
    const el = c?.querySelector<HTMLElement>(`[data-page="${n}"]`);
    if (c && el) c.scrollTo({ top: el.offsetTop - 16, behavior: 'smooth' });
  }, []);
  useImperativeHandle(ref, () => ({ scrollToPage }), [scrollToPage]);

  // current page = the one crossing the upper third of the viewport
  const onScroll = useCallback(() => {
    const c = container.current;
    if (!c || !onPageChange) return;
    const probe = c.scrollTop + c.clientHeight / 3;
    let current = 1;
    c.querySelectorAll<HTMLElement>('[data-page]').forEach((el) => {
      if (el.offsetTop <= probe) current = Number(el.dataset.page);
    });
    if (current !== lastPage.current) {
      lastPage.current = current;
      onPageChange(current);
    }
  }, [onPageChange]);

  return (
    <div ref={container} onScroll={onScroll} className={cn('scroll-thin relative overflow-auto bg-slate-100', className)}>
      {error ? (
        <div className="flex h-full items-center justify-center p-8 text-sm text-slate-600">{error}</div>
      ) : !doc || pageSizes.length === 0 ? (
        <div className="flex h-full min-h-[200px] items-center justify-center"><Spinner className="h-8 w-8" /></div>
      ) : (
        <div className="flex flex-col gap-4 p-6">
          {pageSizes.map((s, i) => (
            <PageView key={i} doc={doc} pageNumber={i + 1} width={s.w * scale} height={s.h * scale} scale={scale} root={container}>
              {renderOverlay?.({ page: i + 1, width: s.w * scale, height: s.h * scale, scale })}
            </PageView>
          ))}
        </div>
      )}
    </div>
  );
});
