import { useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { AuthDialog } from './AuthDialog';
import { Button } from './ui';
import { FileText, LogOut, User } from './icons';

export function Header() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100'}`;
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
        <Link to="/" className="flex items-center gap-2 font-bold text-slate-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white"><FileText className="h-5 w-5" /></span>
          PDF Studio
        </Link>
        <nav className="ml-2 hidden gap-1 sm:flex" aria-label="Main">
          <NavLink to="/tools" className={link}>All tools</NavLink>
          <NavLink to="/editor" className={link}>Editor</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {user ? (
            <>
              <Link to="/account" className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"><User className="h-4 w-4" /><span className="hidden max-w-[160px] truncate sm:inline">{user.email}</span></Link>
              <Button size="sm" variant="ghost" icon={<LogOut className="h-4 w-4" />} onClick={logout}>Sign out</Button>
            </>
          ) : (
            <Button size="sm" variant="primary" onClick={() => setOpen(true)}>Sign in</Button>
          )}
        </div>
      </div>
      <AuthDialog open={open} onClose={() => setOpen(false)} />
    </header>
  );
}
