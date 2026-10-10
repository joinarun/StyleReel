import { describe, expect, it } from 'vitest';
import type { GalleryItem, Job } from '../types';
import { preserveJobOnHome } from './resultSelection';
import { AsyncViewGate, ObservedResults, canApplyRecoveredWorkflow, pendingLookSnapshot } from './viewLifecycle';

const look = (id: string): GalleryItem => ({
  id, created_at: '2026-10-09', garment_names: ['Saree'], workflow: 'catalog',
  before: 'private-source', after: `generated-${id}`, provider: 'Google', model: 'pro', estimated_cost_usd: 0.25,
});
const job = (): Job => ({
  id: 'queued-look', status: 'queued', workflow: 'catalog', garment_names: ['Saree'],
  expected_calls: 1, estimated_cost_usd: 0.25,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(complete => { resolve = complete; });
  return { promise, resolve };
}

describe('asynchronous result dialogs', () => {
  it('accepts work only for the currently open view', () => {
    const gate = new AsyncViewGate();
    const current = gate.open('first');
    expect(gate.accepts(current)).toBe(true);
    gate.close();
    expect(gate.accepts(current)).toBe(false);
  });
  it('rejects a previous image callback after another image opens', () => {
    const gate = new AsyncViewGate();
    const first = gate.open('first');
    const second = gate.open('second');
    expect(gate.accepts(first)).toBe(false);
    expect(gate.accepts(second)).toBe(true);
  });
  it('rejects the prior session when the same image is reopened', () => {
    const gate = new AsyncViewGate();
    const first = gate.open('same-look');
    gate.close();
    const reopened = gate.open('same-look');
    expect(reopened.itemId).toBe(first.itemId);
    expect(reopened.revision).not.toBe(first.revision);
    expect(gate.accepts(first)).toBe(false);
    expect(gate.accepts(reopened)).toBe(true);
  });
  it('keeps a delayed completion from reopening a dialog closed by Home', async () => {
    const gate = new AsyncViewGate();
    const request = deferred<string>();
    const view = gate.open('look');
    const visible: string[] = [];
    const finished = request.promise.then(value => { if (gate.accepts(view)) visible.push(value); });
    gate.close();
    request.resolve('late-share-link');
    await finished;
    expect(visible).toEqual([]);
  });
  it('discards an older response while retaining a newer same-image response', async () => {
    const gate = new AsyncViewGate();
    const older = deferred<string>();
    const newer = deferred<string>();
    const visible: string[] = [];
    const first = gate.open('same-look');
    const firstFinished = older.promise.then(value => { if (gate.accepts(first)) visible.push(value); });
    const second = gate.open('same-look');
    const secondFinished = newer.promise.then(value => { if (gate.accepts(second)) visible.push(value); });
    newer.resolve('current-share-link');
    await secondFinished;
    older.resolve('stale-share-link');
    await firstFinished;
    expect(visible).toEqual(['current-share-link']);
  });
});

describe('gallery observation during result persistence', () => {
  it('waits for a freshly generated image that has not reached the gallery yet', () => {
    const observed = new ObservedResults();
    expect(observed.status('fresh', [])).toBe('waiting');
    expect(observed.status('fresh', [look('unrelated')])).toBe('waiting');
    expect(observed.status('fresh', [look('fresh')])).toBe('available');
  });
  it('recognizes deletion only after seeing the selected result in the gallery', () => {
    const observed = new ObservedResults();
    expect(observed.status('selected', [look('selected')])).toBe('available');
    expect(observed.status('selected', [])).toBe('removed');
    expect(observed.status('selected', [look('another')])).toBe('removed');
  });
  it('does not confuse removal of an observed image with a new unsynced image', () => {
    const observed = new ObservedResults();
    observed.status('older', [look('older')]);
    expect(observed.status('older', [])).toBe('removed');
    expect(observed.status('fresh', [])).toBe('waiting');
  });
  it('recognizes a result restored to the gallery after its removal', () => {
    const observed = new ObservedResults();
    observed.status('restored', [look('restored')]);
    observed.status('restored', []);
    expect(observed.status('restored', [look('restored')])).toBe('available');
  });
});

describe('Home during encrypted pending-job recovery', () => {
  it('applies recovered workflow only to the Home revision where recovery started', () => {
    expect(canApplyRecoveredWorkflow(0, 0)).toBe(true);
    expect(canApplyRecoveredWorkflow(5, 5)).toBe(true);
    expect(canApplyRecoveredWorkflow(5, 6)).toBe(false);
    expect(canApplyRecoveredWorkflow(5, 4)).toBe(false);
  });
  it('keeps a delayed recovered workflow from replacing a fresh Home selection', async () => {
    const recovered = deferred<string>();
    let homeRevision = 2;
    const startedAt = homeRevision;
    let workflow = 'catalog';
    const finished = recovered.promise.then(value => { if (canApplyRecoveredWorkflow(startedAt, homeRevision)) workflow = value; });
    homeRevision += 1;
    recovered.resolve('holding');
    await finished;
    expect(workflow).toBe('catalog');
  });
  it('preserves pending recovery on Home even before a job has been restored', () => {
    expect(preserveJobOnHome(null, false, false, true)).toBe(true);
    expect(preserveJobOnHome(null, false, false, false)).toBe(false);
    expect(preserveJobOnHome({ ...job(), status: 'succeeded' }, false, false, true)).toBe(true);
  });
});

describe('immutable pending-look metadata', () => {
  it('prefers provider and model metadata from the submitted job', () => {
    const submitted = { ...job(), provider_label: 'Google at submission', model: 'gemini-3-pro-image' };
    const snapshot = pendingLookSnapshot(submitted, 'source-at-submission', 'Changed provider', 'Changed model');
    expect(snapshot.provider).toBe('Google at submission');
    expect(snapshot.model).toBe('gemini-3-pro-image');
    expect(snapshot.before).toBe('source-at-submission');
  });
  it('uses submission-time defaults when older jobs lack provider metadata', () => {
    const snapshot = pendingLookSnapshot(job(), 'source', 'Google', 'pro-at-submission');
    expect(snapshot.provider).toBe('Google');
    expect(snapshot.model).toBe('pro-at-submission');
  });
  it('keeps cloned metadata stable when the original job is later mutated', () => {
    const submitted = { ...job(), error: { message: 'Original error' } };
    const snapshot = pendingLookSnapshot(submitted, 'source', 'Google', 'pro');
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.job)).toBe(true);
    expect(snapshot.job).not.toBe(submitted);
    expect(snapshot.job.garment_names).not.toBe(submitted.garment_names);
    submitted.id = 'another-job';
    submitted.status = 'failed';
    submitted.garment_names!.push('Different garment');
    submitted.error.message = 'Changed error';
    expect(snapshot.job.id).toBe('queued-look');
    expect(snapshot.job.status).toBe('queued');
    expect(snapshot.job.garment_names).toEqual(['Saree']);
    expect(snapshot.job.error).toEqual({ message: 'Original error' });
  });
});
