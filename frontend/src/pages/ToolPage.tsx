import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { TOOL_BY_ID, acceptExt, condMet } from '../lib/tools';
import type { Tool } from '../lib/tools';
import * as api from '../lib/api';
import { useBeforeUnload, useOperation, useUploads } from '../lib/hooks';
import { stash } from '../lib/stash';
import { plural } from '../lib/util';
import { FileDropzone } from '../components/FileDropzone';
import { FileList } from '../components/FileList';
import { OptionsForm, defaultsFor, toOptions } from '../components/OptionsForm';
import type { Values } from '../components/OptionsForm';
import { PagePicker, selectionToSpec, specToSelection } from '../components/PageThumbs';
import { ResultsPanel } from '../components/ResultsPanel';
import { PdfViewer } from '../components/PdfViewer';
import { Button, Card, Modal, Notice, ProgressBar } from '../components/ui';
import { ICONS, ChevronLeft } from '../components/icons';
import { useHealth } from '../lib/health';
import ImageToPdfPage from './ImageToPdfPage';
import OrganizePage from './OrganizePage';

export default function ToolPage() {
  const { toolId = '' } = useParams();
  const tool = TOOL_BY_ID[toolId];
  if (!tool) return <Navigate to="/tools" replace />;
  if (tool.special === 'editor') return <Navigate to="/editor" replace />;
  if (tool.special === 'image-to-pdf') return <ImageToPdfPage key={tool.id} tool={tool} />;
  if (tool.special === 'organize') return <OrganizePage key={tool.id} tool={tool} />;
  return <GenericTool key={tool.id} tool={tool} />;
}

export function ToolHeader({ tool }: { tool: Tool }) {
  const Icon = ICONS[tool.icon];
  return (
    <div className="mb-6">
      <Link to="/tools" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ChevronLeft className="h-4 w-4" />All tools</Link>
      <div className="flex items-start gap-3">
        {Icon && <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><Icon className="h-6 w-6" /></span>}
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{tool.title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">{tool.description}</p>
        </div>
      </div>
    </div>
  );
}

function GenericTool({ tool }: { tool: Tool }) {
  const health = useHealth();
  const max = tool.extraFile ? 1 : tool.maxFiles;
  const main = useUploads(max);
  const extra = useUploads(1);
  const op = useOperation();
  const [values, setValues] = useState<Values>(() => defaultsFor(tool.fields));
  const [confirm, setConfirm] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<{ name: string; url: string; sizes: { w: number; h: number }[] } | null>(null);
  const started = useRef(false);

  useBeforeUnload(op.isBusy);

  // files handed over from the home page
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const f = stash.take().filter((x) => acceptExt(tool.accept).includes(x.name.split('.').pop()?.toLowerCase() ?? ''));
    if (f.length) main.add(f);
  }, [main, tool.accept]);

  const ready = main.items.filter((i) => i.status === 'ready' && i.record);
  const uploading = main.items.some((i) => i.status === 'uploading') || extra.items.some((i) => i.status === 'uploading');
  const first = ready[0];
  const firstInfo = first?.info;
  const extraVisible = tool.extraFile && condMet(tool.extraFile.showIf, values);
  const extraReady = extra.items.find((i) => i.status === 'ready' && i.record);
  const flagMissing = tool.featureFlag && health && !health.features[tool.featureFlag];
  const needMin = tool.extraFile ? 1 : tool.minFiles;

  // pre-fill metadata form from the uploaded file
  const metaFor = useRef<string | null>(null);
  useEffect(() => {
    if (!tool.prefillMetadata || !firstInfo?.metadata || metaFor.current === first?.key) return;
    metaFor.current = first?.key ?? null;
    setValues((v) => ({ ...v, ...Object.fromEntries(Object.entries(firstInfo.metadata ?? {}).filter(([k]) => k in v)) }));
  }, [tool.prefillMetadata, firstInfo, first?.key]);

  // seed the metadata defaults of text fields as "" so they show current values
  const pageField = tool.pagePicker;
  const pagesTotal = firstInfo?.pages ?? 0;

  const blocked = useMemo(() => {
    if (flagMissing) return 'This feature is not available on this server.';
    if (ready.length < needMin) return `Add ${plural(needMin, 'file')} to continue.`;
    if (uploading) return 'Waiting for uploads to finish…';
    if (tool.accept === 'pdf') {
      const bad = ready.find((i) => i.info?.security?.needs_password && !i.password);
      if (bad && tool.passwords && tool.passwords !== 'none') return `Enter the password for “${bad.name}”.`;
      if (ready.some((i) => i.info?.security?.unreadable)) return 'A PDF is damaged – use the Repair tool first.';
    }
    if (tool.extraFile?.required && extraVisible && !extraReady) return `Add: ${tool.extraFile.label}`;
    if (tool.confirm && !confirm) return 'Please confirm the statement below.';
    return null;
  }, [flagMissing, ready, needMin, uploading, tool, extraVisible, extraReady, confirm]);

  async function run() {
    const options = toOptions(tool.fields, values);
    if (tool.passwords === 'single') {
      if (ready[0].password) options.password = ready[0].password;
    } else if (tool.passwords === 'list') {
      options.passwords = ready.map((i) => i.password);
    }
    if (tool.perFilePages) options.pages = ready.map((i) => i.pages.trim());
    if (tool.confirm) options.confirm_authorized = confirm;
    const ids = ready.map((i) => i.record!.id);
    if (extraVisible && extraReady) ids.push(extraReady.record!.id);
    await op.run(tool.endpoint, { fileIds: ids, options });
  }

  async function useResultAsInput(o: api.JobOutput) {
    const rec: api.ApiFile = { id: o.id, name: o.name, size: o.size, kind: o.kind, mime: o.mime, url: o.url, expires: 0 };
    await main.replaceWith(rec);
    op.reset();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function preview(o: api.JobOutput) {
    try {
      const info = await api.getInfo(o.id);
      setPreviewUrl({ name: o.name, url: api.absUrl(o.url), sizes: (info.page_sizes ?? []).map((p) => ({ w: p.w, h: p.h })) });
    } catch {
      /* preview is optional */
    }
  }

  const job = op.state.job;
  const Done = op.state.phase === 'done' && job;
  const showPicker = pageField && first?.info && !first.info.security?.needs_password && pagesTotal > 0 && pagesTotal <= 500;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <ToolHeader tool={tool} />
      {flagMissing && <div className="mb-4"><Notice tone="warn" title="Not available">This server is missing the software this tool needs, so it is turned off instead of pretending to work. See the README for setup instructions.</Notice></div>}
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          {main.items.length === 0 ? (
            <FileDropzone accept={acceptExt(tool.accept)} multiple={max > 1} onFiles={main.add} maxMB={health?.limits.max_file_mb ?? 100} />
          ) : (
            <>
              <FileList items={main.items} tool={tool} onRemove={main.remove} onMove={main.move} onPatch={main.patch} sortable={max > 1} />
              {main.items.length < max && <FileDropzone compact accept={acceptExt(tool.accept)} onFiles={main.add} title="Add more files" maxMB={health?.limits.max_file_mb ?? 100} />}
            </>
          )}
          {extraVisible && tool.extraFile && (
            <Card className="p-4">
              <p className="mb-2 text-sm font-medium text-slate-800">{tool.extraFile.label}</p>
              {extra.items.length === 0 ? (
                <FileDropzone compact multiple={false} accept={acceptExt(tool.extraFile.accept)} onFiles={extra.add} />
              ) : (
                <FileList items={extra.items} onRemove={extra.remove} onMove={extra.move} onPatch={extra.patch} />
              )}
            </Card>
          )}
          {showPicker && first?.record && (
            <Card className="p-4">
              <p className="mb-2 text-sm font-medium text-slate-800">Pick pages visually <span className="font-normal text-slate-500">(or type ranges in the options)</span></p>
              <PagePicker
                fileId={first.record.id}
                pages={pagesTotal}
                selected={specToSelection(String(values[pageField!] ?? ''), pagesTotal)}
                onChange={(sel) => setValues((v) => ({ ...v, [pageField!]: sel.length === pagesTotal ? 'all' : selectionToSpec(sel) }))}
              />
            </Card>
          )}
        </div>

        <aside className="space-y-4">
          <Card className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-900">Options</h2>
            {tool.fields.length === 0 && <p className="text-sm text-slate-500">No options needed.</p>}
            <OptionsForm fields={tool.fields} values={values} onChange={setValues} disabled={op.isBusy} />
            {tool.confirm && (
              <label className="flex items-start gap-2 text-sm text-slate-800">
                <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                {tool.confirm}
              </label>
            )}
            {op.isBusy ? (
              <div className="space-y-2">
                <ProgressBar value={op.state.progress} indeterminate={op.state.phase === 'queued'} />
                <p className="text-xs text-slate-600" aria-live="polite">{op.state.message || 'Working…'}</p>
                <Button className="w-full" onClick={op.cancel}>Cancel</Button>
              </div>
            ) : (
              <>
                <Button variant="primary" size="lg" className="w-full" disabled={!!blocked} onClick={run}>{tool.title}</Button>
                {blocked && <p className="text-xs text-slate-500">{blocked}</p>}
              </>
            )}
            {op.state.phase === 'failed' && op.state.error && <Notice tone="error" title="That did not work">{op.state.error}</Notice>}
            {op.state.phase === 'cancelled' && <Notice tone="info">Cancelled.</Notice>}
          </Card>
        </aside>
      </div>

      {Done && job && (
        <div className="mt-8">
          <ResultsPanel job={job} onUseAsInput={useResultAsInput} onPreview={preview} />
        </div>
      )}

      <Modal open={!!previewUrl} onClose={() => setPreviewUrl(null)} title={previewUrl?.name ?? 'Preview'} wide>
        {previewUrl && <PdfViewer url={previewUrl.url} pageSizes={previewUrl.sizes} zoom="fit-width" className="h-[70vh] rounded-lg" />}
      </Modal>
    </div>
  );
}
