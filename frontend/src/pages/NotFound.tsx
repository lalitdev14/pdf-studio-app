import { Link } from 'react-router-dom';
export default function NotFound() {
  return (
    <div className="mx-auto max-w-md px-4 py-24 text-center">
      <h1 className="text-2xl font-bold text-slate-900">Page not found</h1>
      <p className="mt-2 text-slate-600">That page does not exist.</p>
      <Link to="/" className="mt-6 inline-block font-medium text-brand-700 hover:underline">Back to home</Link>
    </div>
  );
}
