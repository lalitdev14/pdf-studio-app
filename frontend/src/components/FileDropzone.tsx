import { useRef, useState, type DragEvent } from 'react';
import { cn, fileExt, formatBytes } from '../lib/util';
import { Upload } from './icons';
import { useToast } from './toast';

type Props = {
  accept: string[]; // extensions without dot
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  maxMB?: number;
  title?: string;
  hint?: string;
  compact?: boolean;
  disabled?: boolean;
  className?: string;
};

export function FileDropzone({ accept, multiple = true, onFiles, maxMB = 100, title, hint, compact, disabled, className }: Props) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const toast = useToast();

  function take(list: FileList | File[] | null) {
    if (!list || disabled) return;
    const good: File[] = [];
    for (const f of Array.from(list)) {
      if (!accept.includes(fileExt(f.name))) toast.error(`“${f.name}” is not a supported file type here (${accept.join(', ').toUpperCase()}).`);
      else if (f.size > maxMB * 1024 * 1024) toast.error(`“${f.name}” is ${formatBytes(f.size)} – the limit is ${maxMB} MB.`);
      else if (f.size === 0) toast.error(`“${f.name}” is empty.`);
      else good.push(f);
    }
    if (good.length) onFiles(multiple ? good : good.slice(0, 1));
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        'rounded-2xl border-2 border-dashed bg-white text-center transition',
        over ? 'border-brand-500 bg-brand-50' : 'border-slate-300 hover:border-brand-500/60',
        compact ? 'p-4' : 'p-8 sm:p-12',
        disabled && 'opacity-60',
        className,
      )}
    >
      <div className={cn('mx-auto flex items-center justify-center rounded-full bg-brand-50 text-brand-600', compact ? 'mb-2 h-10 w-10' : 'mb-4 h-14 w-14')}>
        <Upload className={compact ? 'h-5 w-5' : 'h-7 w-7'} />
      </div>
      <p className={cn('font-semibold text-slate-900', compact ? 'text-sm' : 'text-lg')}>{title ?? (multiple ? 'Drag and drop files here' : 'Drag and drop a file here')}</p>
      <p className="mt-1 text-sm text-slate-500">or</p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="mt-2 inline-flex h-10 items-center rounded-lg bg-brand-600 px-5 text-sm font-medium text-white shadow-sm hover:bg-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed"
      >
        Browse files
      </button>
      <input
        ref={input}
        type="file"
        hidden
        multiple={multiple}
        accept={accept.map((e) => '.' + e).join(',')}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = '';
        }}
      />
      <p className="mt-3 text-xs text-slate-500">{hint ?? `${accept.map((e) => e.toUpperCase()).join(', ')} · up to ${maxMB} MB each`}</p>
    </div>
  );
}
