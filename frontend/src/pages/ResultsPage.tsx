import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import * as api from '../lib/api';
import { errMessage } from '../lib/util';
import { ResultsPanel } from '../components/ResultsPanel';
import { Notice, Spinner } from '../components/ui';

export default function ResultsPage() {
  const { jobId = '' } = useParams();
  const [job, setJob] = useState<api.Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.getJob(jobId).then(setJob).catch((e) => setErr(errMessage(e)));
  }, [jobId]);
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="mb-4 text-2xl font-bold text-slate-900">Results</h1>
      {err && <Notice tone="error" title="Could not load this result">{err} The files may have expired.</Notice>}
      {!job && !err && <Spinner className="h-6 w-6" />}
      {job?.status === 'done' && <ResultsPanel job={job} />}
      {job && job.status !== 'done' && <Notice tone="info">This job is {job.status}.</Notice>}
      <Link to="/tools" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">Back to tools</Link>
    </div>
  );
}
