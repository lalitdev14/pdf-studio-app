import { useNavigate } from 'react-router-dom';
import { CATEGORIES, TOOLS, acceptExt, toolPath } from '../lib/tools';
import { stash } from '../lib/stash';
import { fileExt } from '../lib/util';
import { FileDropzone } from '../components/FileDropzone';
import { ToolCard } from './ToolsPage';
import { useToast } from '../components/toast';
import { useHealth } from '../lib/health';

export default function Home() {
  const nav = useNavigate();
  const toast = useToast();
  const health = useHealth();

  function route(files: File[]) {
    const ext = fileExt(files[0].name);
    if (files.every((f) => acceptExt('image').includes(fileExt(f.name)))) { stash.set(files); nav('/tools/image-to-pdf'); return; }
    if (files.every((f) => fileExt(f.name) === 'pdf')) {
      stash.set(files);
      nav(files.length > 1 ? '/tools/merge' : '/editor');
      return;
    }
    const office = TOOLS.find((t) => t.endpoint.endsWith('office-to-pdf') && acceptExt(t.accept).includes(ext));
    if (office) { stash.set(files); nav(toolPath(office)); return; }
    toast.error('Pick one kind of file at a time (PDFs, images or Office documents).');
  }

  const all = ['pdf', ...acceptExt('image'), 'docx', 'doc', 'odt', 'xlsx', 'xls', 'ods', 'pptx', 'ppt', 'odp'];
  return (
    <div>
      <section className="bg-gradient-to-b from-brand-50 to-white">
        <div className="mx-auto max-w-3xl px-4 pb-10 pt-12 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Every PDF tool in one place</h1>
          <p className="mx-auto mt-3 max-w-xl text-slate-600">Edit, convert, merge, split, compress, protect and more. Files are processed for real on the server and deleted automatically.</p>
          <FileDropzone className="mt-8" accept={all} onFiles={route} maxMB={health?.limits.max_file_mb ?? 100} title="Drop a PDF, images or an Office file" hint="We’ll open the right tool for you – or pick one below." />
        </div>
      </section>
      <section className="mx-auto max-w-6xl space-y-10 px-4 py-10">
        {CATEGORIES.map((c) => (
          <div key={c}>
            <h2 className="mb-3 text-lg font-semibold text-slate-900">{c}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {TOOLS.filter((t) => t.category === c).map((t) => <ToolCard key={t.id} tool={t} to={toolPath(t)} />)}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
