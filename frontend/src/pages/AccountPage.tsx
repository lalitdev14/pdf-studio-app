import { useEffect, useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import { useAuth } from '../lib/auth';
import { errMessage, formatBytes } from '../lib/util';
import { Button, Card, Modal, Notice } from '../components/ui';
import { useToast } from '../components/toast';
import { stash } from '../lib/stash';

export default function AccountPage() {
  const { user, ready, logout, adopt } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [history, setHistory] = useState<api.HistoryItem[]>([]);
  const [files, setFiles] = useState<api.SavedFile[]>([]);
  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [delOpen, setDelOpen] = useState(false);
  const [delPw, setDelPw] = useState('');
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api.getHistory().then((r) => setHistory(r.items)).catch(() => undefined);
    api.listSaved().then((r) => setFiles(r.files)).catch(() => undefined);
  }, [user]);

  if (!ready) return null;
  if (!user) return <Navigate to="/" replace />;

  async function changePw(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      adopt(await api.changePassword(oldPw, newPw));
      setOldPw(''); setNewPw('');
      toast.success('Password changed.');
    } catch (x) { setErr(errMessage(x)); }
  }
  async function remove() {
    try { await api.deleteAccount(delPw); logout(); toast.info('Your account and saved files were deleted.'); nav('/'); }
    catch (x) { toast.error(errMessage(x)); }
  }
  async function openInEditor(f: api.SavedFile) {
    try {
      const rec = await api.openSaved(f.id);
      const blob = await (await fetch(api.absUrl(rec.url))).blob();
      stash.set([new File([blob], rec.name, { type: rec.mime })]);
      nav('/editor');
    } catch (x) { toast.error(errMessage(x)); }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Your account</h1>
      <p className="text-sm text-slate-600">{user.email}</p>

      <Card className="p-5">
        <h2 className="mb-3 font-semibold text-slate-900">Saved files</h2>
        {files.length === 0 ? <p className="text-sm text-slate-500">Nothing saved yet. Use “Save” on a result to keep it here.</p> : (
          <ul className="divide-y divide-slate-100">
            {files.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate">{f.name} <span className="text-slate-400">· {formatBytes(f.size)}</span></span>
                {f.kind === 'pdf' && <Button size="sm" onClick={() => openInEditor(f)}>Open in editor</Button>}
                <Button size="sm" onClick={() => api.downloadSaved(f).catch((x) => toast.error(errMessage(x)))}>Download</Button>
                <Button size="sm" variant="ghost" onClick={async () => { await api.deleteSaved(f.id); setFiles((l) => l.filter((x) => x.id !== f.id)); }}>Delete</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">Recent activity</h2>
          {history.length > 0 && <Button size="sm" variant="ghost" onClick={async () => { await api.clearHistory(); setHistory([]); }}>Clear history</Button>}
        </div>
        {history.length === 0 ? <p className="text-sm text-slate-500">No activity yet.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {history.map((h, i) => <li key={i} className="flex justify-between py-2"><span>{h.op}</span><span className="text-slate-500">{new Date(h.created * 1000).toLocaleString()}</span></li>)}
          </ul>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 font-semibold text-slate-900">Change password</h2>
        <form onSubmit={changePw} className="grid gap-3 sm:grid-cols-2">
          <input className="input" type="password" required autoComplete="current-password" placeholder="Current password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} />
          <input className="input" type="password" required minLength={8} autoComplete="new-password" placeholder="New password (8+ characters)" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
          <div className="sm:col-span-2"><Button type="submit" variant="primary">Update password</Button></div>
        </form>
        {err && <div className="mt-3"><Notice tone="error">{err}</Notice></div>}
      </Card>

      <Card className="p-5">
        <h2 className="mb-1 font-semibold text-slate-900">Delete account</h2>
        <p className="mb-3 text-sm text-slate-600">Permanently removes your account, history and saved files.</p>
        <Button variant="danger" onClick={() => setDelOpen(true)}>Delete my account</Button>
      </Card>

      <Modal open={delOpen} onClose={() => setDelOpen(false)} title="Delete account?">
        <p className="mb-3 text-sm text-slate-600">This cannot be undone. Enter your password to confirm.</p>
        <input className="input mb-3" type="password" autoComplete="current-password" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
        <div className="flex justify-end gap-2"><Button onClick={() => setDelOpen(false)}>Cancel</Button><Button variant="danger" disabled={!delPw} onClick={remove}>Delete</Button></div>
      </Modal>
    </div>
  );
}
