import { useState } from 'react';
import * as api from '../lib/api';
import { formatBytes, plural, triggerDownload } from '../lib/util';
import { useAuth } from '../lib/auth';
import { Button, Card, Notice } from './ui';
import { Download, FileText, Save, Trash2, CheckCircle2 } from './icons';
import { useToast } from './toast';
import { errMessage } from '../lib/util';

type Props = {
  job: api.Job;
  onUseAsInput?: (o: api.JobOutput) => void;
  onPreview?: (o: api.JobOutput) => void;
  onDeleted?: () => void;
};

export function ResultsPanel({ job, onUseAsInput, onPreview, onDeleted }: Props) {
  const toast = useToast();
  const { user } = useAuth();
  const [deleted, setDeleted] = useState(false);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const m = job.meta ?? {};
  const isCompress = job.op.includes('compress');

  async function deleteNow() {
    await Promise.all(job.outputs.map((o) => api.deleteFile(o.url).catch(() => undefined)));
    setDeleted(true);
    toast.info('Your result files were deleted from the server.');
    onDeleted?.();
  }
  async function save(o: api.JobOutput) {
    try {
      await api.saveToWorkspace(o.id);
      setSaved((s) => new Set(s).add(o.id));
      toast.success('Saved to your workspace.');
    } catch (e) {
      toast.error(errMessage(e));
    }
  }

  if (deleted) return <Notice tone="info">Result files were deleted. Run the tool again to create new ones.</Notice>;

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-2 text-emerald-700">
        <CheckCircle2 className="h-5 w-5" />
        <h2 className="text-base font-semibold">{m.message && !isCompress ? String(m.message) : isCompress ? 'Compression finished' : 'Your result is ready'}</h2>
      </div>

      {isCompress && (
        <div className="mb-4">
          <Notice tone={m.reduced ? 'success' : 'warn'}>
            {String(m.message ?? '')}
            {typeof m.original_size === 'number' && typeof m.compressed_size === 'number' && (
              <div className="mt-1 text-xs opacity-90">
                {formatBytes(m.original_size)} → {formatBytes(m.compressed_size)}
                {m.reduced ? ` (−${m.reduction_pct}%)` : ' (no change)'}
              </div>
            )}
          </Notice>
        </div>
      )}

      {job.warnings.length > 0 && (
        <div className="mb-4 space-y-2">
          {job.warnings.map((w, i) => <Notice key={i} tone="warn">{w}</Notice>)}
        </div>
      )}

      <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
        {job.outputs.map((o) => (
          <li key={o.id} className="flex flex-wrap items-center gap-3 p-3">
            <FileText className="h-5 w-5 shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900" title={o.name}>{o.name}</p>
              <p className="text-xs text-slate-500">{formatBytes(o.size)}</p>
            </div>
            {o.kind === 'pdf' && onPreview && <Button size="sm" onClick={() => onPreview(o)}>Preview</Button>}
            {o.kind === 'pdf' && onUseAsInput && <Button size="sm" onClick={() => onUseAsInput(o)}>Use as input</Button>}
            {user && <Button size="sm" icon={<Save className="h-4 w-4" />} disabled={saved.has(o.id)} onClick={() => save(o)}>{saved.has(o.id) ? 'Saved' : 'Save'}</Button>}
            <Button size="sm" variant="primary" icon={<Download className="h-4 w-4" />} onClick={() => triggerDownload(api.absUrl(o.url), o.name)}>Download</Button>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {job.outputs.length > 1 && (
          <Button variant="primary" icon={<Download className="h-4 w-4" />} onClick={() => triggerDownload(api.zipUrl(job.id), 'pdf-studio-results.zip')}>
            Download all ({plural(job.outputs.length, 'file')}) as ZIP
          </Button>
        )}
        <Button variant="ghost" icon={<Trash2 className="h-4 w-4" />} onClick={deleteNow}>Delete files now</Button>
      </div>
      <p className="mt-3 text-xs text-slate-500">Files are removed automatically from the server after a short time.</p>
    </Card>
  );
}
