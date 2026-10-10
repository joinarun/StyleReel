import { describe, expect, it, vi } from 'vitest';
import { cameraErrorMessage, startCamera, usesNativeCamera } from './camera';

function fakeStream() {
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
  return { tracks, stream: { getTracks: () => tracks } as unknown as MediaStream };
}

describe('camera choice', () => {
  it('uses the laptop webcam rather than a capture file picker on Mac', () => {
    expect(usesNativeCamera({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', platform: 'MacIntel', maxTouchPoints: 0 })).toBe(false);
  });
  it('preserves native photo capture on Android and iPhone', () => {
    expect(usesNativeCamera({ userAgent: 'Mozilla/5.0 (Linux; Android 15; Pixel 8)', platform: 'Linux armv8l', maxTouchPoints: 5 })).toBe(true);
    expect(usesNativeCamera({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', platform: 'iPhone', maxTouchPoints: 5 })).toBe(true);
  });
  it('recognizes iPads using desktop Safari identification', () => {
    expect(usesNativeCamera({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', platform: 'MacIntel', maxTouchPoints: 5 })).toBe(true);
  });
});

describe('camera session privacy', () => {
  it('stops every active media track on close, without requesting microphone access', async () => {
    const { tracks, stream } = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    const ready = vi.fn();
    const close = startCamera({ getUserMedia }, ready, vi.fn());
    await Promise.resolve();
    expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: false }));
    expect(ready).toHaveBeenCalledWith(stream);
    close(); close();
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledTimes(1));
  });
  it('stops permission-granted streams that arrive after the dialog closes', async () => {
    const { tracks, stream } = fakeStream();
    let grant!: (stream: MediaStream) => void;
    const permission = new Promise<MediaStream>(resolve => { grant = resolve; });
    const ready = vi.fn();
    const close = startCamera({ getUserMedia: () => permission }, ready, vi.fn());
    close();
    grant(stream);
    await Promise.resolve();
    expect(ready).not.toHaveBeenCalled();
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledTimes(1));
  });
  it('does not update a closed camera after permission is rejected', async () => {
    let deny!: (error: unknown) => void;
    const permission = new Promise<MediaStream>((_, reject) => { deny = reject; });
    const failure = vi.fn();
    const close = startCamera({ getUserMedia: () => permission }, vi.fn(), failure);
    close();
    deny(new DOMException('Permission denied', 'NotAllowedError'));
    await Promise.resolve();
    expect(failure).not.toHaveBeenCalled();
  });
  it('cleans up a stream when attaching its preview fails', async () => {
    const { tracks, stream } = fakeStream();
    const failure = vi.fn();
    const error = new Error('Preview failed');
    startCamera({ getUserMedia: () => Promise.resolve(stream) }, () => { throw error; }, failure);
    await Promise.resolve();
    tracks.forEach(track => expect(track.stop).toHaveBeenCalledTimes(1));
    expect(failure).toHaveBeenCalledWith(error);
  });
});

describe('camera recovery guidance', () => {
  it('explains permission denial, missing cameras, and cameras in use', () => {
    expect(cameraErrorMessage(new DOMException('', 'NotAllowedError'))).toMatch(/System Settings/);
    expect(cameraErrorMessage(new DOMException('', 'NotFoundError'))).toMatch(/No camera was found/);
    expect(cameraErrorMessage(new DOMException('', 'NotReadableError'))).toMatch(/Close other apps/);
    expect(cameraErrorMessage(null)).toMatch(/upload a photo/);
  });
});
