import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';
import * as api from '../lib/api';
import { errMessage } from '../lib/util';
import { Button, Modal, Notice } from './ui';

type Mode = 'login' | 'register' | 'forgot' | 'reset';

export function AuthDialog({ open, onClose, initial = 'login' }: { open: boolean; onClose: () => void; initial?: Mode }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>(initial);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const switchTo = (m: Mode) => { setMode(m); setError(null); setInfo(null); };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      if (mode === 'login') { await login(email, password); onClose(); }
      else if (mode === 'register') { await register(email, password); onClose(); }
      else if (mode === 'forgot') {
        const r = await api.forgotPassword(email);
        setInfo(r.message);
        if (r.dev_reset_token) setToken(r.dev_reset_token);
        setMode('reset');
      } else {
        const r = await api.resetPassword(token.trim(), password);
        setInfo(r.message);
        setPassword('');
        setMode('login');
      }
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const title = { login: 'Sign in', register: 'Create your account', forgot: 'Reset your password', reset: 'Choose a new password' }[mode];
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <form onSubmit={submit} className="space-y-4">
        {info && <Notice tone="info">{info}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
        {mode !== 'reset' && (
          <div>
            <label className="label" htmlFor="auth-email">Email</label>
            <input id="auth-email" className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
        )}
        {mode === 'reset' && (
          <div>
            <label className="label" htmlFor="auth-token">Reset token</label>
            <input id="auth-token" className="input" required value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
        )}
        {mode !== 'forgot' && (
          <div>
            <label className="label" htmlFor="auth-pw">{mode === 'reset' ? 'New password' : 'Password'}</label>
            <input id="auth-pw" className="input" type="password" required minLength={mode === 'login' ? 1 : 8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={(e) => setPassword(e.target.value)} />
            {mode !== 'login' && <p className="mt-1 text-xs text-slate-500">At least 8 characters.</p>}
          </div>
        )}
        <Button type="submit" variant="primary" className="w-full" loading={busy}>{title}</Button>
        <div className="flex flex-wrap justify-between gap-2 text-sm text-brand-700">
          {mode === 'login' && (<>
            <button type="button" className="hover:underline" onClick={() => switchTo('register')}>Create an account</button>
            <button type="button" className="hover:underline" onClick={() => switchTo('forgot')}>Forgot password?</button>
          </>)}
          {mode === 'register' && <button type="button" className="hover:underline" onClick={() => switchTo('login')}>I already have an account</button>}
          {(mode === 'forgot' || mode === 'reset') && <button type="button" className="hover:underline" onClick={() => switchTo('login')}>Back to sign in</button>}
        </div>
        <p className="text-xs text-slate-500">Accounts are optional. They add history and a saved-files workspace; every tool works without one.</p>
      </form>
    </Modal>
  );
}
