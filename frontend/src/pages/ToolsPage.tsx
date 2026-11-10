import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { CATEGORIES, TOOLS, toolPath } from '../lib/tools';
import type { Tool } from '../lib/tools';
import { ICONS, Search } from '../components/icons';

export function ToolCard({ tool, to }: { tool: Tool; to: string }) {
  const Icon = ICONS[tool.icon];
  return (
    <Link to={to} className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-card transition hover:border-brand-500/50 hover:shadow-pop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
      {Icon && <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><Icon className="h-5 w-5" /></span>}
      <span className="min-w-0">
        <span className="block font-semibold text-slate-900">{tool.title}</span>
        <span className="mt-0.5 block text-sm text-slate-500">{tool.short}</span>
      </span>
    </Link>
  );
}

export default function ToolsPage() {
  const [q, setQ] = useState('');
  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return s ? TOOLS.filter((t) => `${t.title} ${t.short} ${t.description}`.toLowerCase().includes(s)) : TOOLS;
  }, [q]);
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">All tools</h1>
      <div className="relative mt-4 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <input className="input pl-9" type="search" placeholder="Search tools…" aria-label="Search tools" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {list.length === 0 && <p className="mt-8 text-slate-500">No tool matches “{q}”.</p>}
      {CATEGORIES.map((c) => {
        const items = list.filter((t) => t.category === c);
        if (!items.length) return null;
        return (
          <section key={c} className="mt-8">
            <h2 className="mb-3 text-lg font-semibold text-slate-900">{c}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{items.map((t) => <ToolCard key={t.id} tool={t} to={toolPath(t)} />)}</div>
          </section>
        );
      })}
    </div>
  );
}
