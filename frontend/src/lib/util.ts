import clsx, { type ClassValue } from 'clsx';

export const cn = (...v: ClassValue[]) => clsx(v);

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return '';
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
}

export const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`;

export const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

/** [1,2,3,5,7,8] -> "1-3,5,7-8" */
export function pagesToRanges(pages: number[]): string {
  const s = [...new Set(pages)].sort((a, b) => a - b);
  const out: string[] = [];
  let i = 0;
  while (i < s.length) {
    let j = i;
    while (j + 1 < s.length && s[j + 1] === s[j] + 1) j++;
    out.push(j > i ? `${s[i]}-${s[j]}` : `${s[i]}`);
    i = j + 1;
  }
  return out.join(',');
}

/** "1-3,5" -> [1,2,3,5] (ignores anything it cannot parse; server validates for real) */
export function rangesToPages(spec: string, total: number): number[] {
  const out = new Set<number>();
  for (const part of spec.replace(/\s/g, '').split(',')) {
    const m = /^(\d*)-(\d*)$/.exec(part);
    if (m) {
      const a = m[1] ? +m[1] : 1;
      const b = m[2] ? +m[2] : total;
      for (let p = Math.max(1, a); p <= Math.min(total, b); p++) out.add(p);
    } else if (/^\d+$/.test(part) && +part >= 1 && +part <= total) out.add(+part);
  }
  return [...out].sort((a, b) => a - b);
}

export function triggerDownload(url: string, name: string) {
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function fileExt(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i + 1).toLowerCase();
}

export const IMAGE_EXT = ['jpg', 'jpeg', 'png', 'webp', 'bmp', 'tif', 'tiff', 'heic', 'heif'];
export const WORD_EXT = ['docx', 'doc', 'odt'];
export const EXCEL_EXT = ['xlsx', 'xls', 'ods'];
export const PPT_EXT = ['pptx', 'ppt', 'odp'];

/** Moves item `from` to index `to` in a new array. */
export function moveItem<T>(arr: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= arr.length || to >= arr.length) return arr;
  const copy = arr.slice();
  const [it] = copy.splice(from, 1);
  copy.splice(to, 0, it);
  return copy;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong.';
}
