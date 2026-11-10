import { Component, Suspense, lazy, type ReactNode } from 'react';
import { Route, Routes } from 'react-router-dom';
import { Header } from './components/Header';
import { Spinner } from './components/ui';
import Home from './pages/Home';
import ToolsPage from './pages/ToolsPage';
import ToolPage from './pages/ToolPage';
import ResultsPage from './pages/ResultsPage';
import AccountPage from './pages/AccountPage';
import NotFound from './pages/NotFound';

const EditorPage = lazy(() => import('./pages/EditorPage'));

class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-md px-4 py-24 text-center">
        <h1 className="text-xl font-bold text-slate-900">Something went wrong</h1>
        <p className="mt-2 text-sm text-slate-600">The page hit an unexpected error. Your files on the server are unaffected.</p>
        <button className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white" onClick={() => location.reload()}>Reload</button>
      </div>
    );
  }
}

export default function App() {
  return (
    <div className="flex min-h-full flex-col bg-slate-50">
      <Header />
      <main className="flex-1">
        <Boundary>
          <Suspense fallback={<div className="flex justify-center py-24"><Spinner className="h-8 w-8" /></div>}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/tools" element={<ToolsPage />} />
              <Route path="/tools/:toolId" element={<ToolPage />} />
              <Route path="/editor" element={<EditorPage />} />
              <Route path="/results/:jobId" element={<ResultsPage />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </Boundary>
      </main>
      <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-500">PDF Studio · files are deleted automatically · passwords are never bypassed</footer>
    </div>
  );
}
