/** Phones and iPads keep their native camera picker; laptops use a live webcam. */
export function usesNativeCamera(device: Pick<Navigator, 'userAgent' | 'platform' | 'maxTouchPoints'>): boolean {
  return /Android|iPhone|iPad|iPod/i.test(device.userAgent)
    || (device.platform === 'MacIntel' && device.maxTouchPoints > 1);
}

export function stopCamera(stream: MediaStream | null): void {
  stream?.getTracks().forEach(track => track.stop());
}

export function cameraErrorMessage(error: unknown): string {
  const name = error && typeof error === 'object' && 'name' in error ? String(error.name) : '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return 'Camera access was blocked. Allow camera access for this site in your browser and in System Settings → Privacy & Security → Camera, then try again. You can also upload a photo.';
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return 'No camera was found. Connect or enable a camera, then try again, or upload a photo.';
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return 'Your camera is busy or unavailable. Close other apps using it, then try again, or upload a photo.';
  }
  if (name === 'SecurityError') {
    return 'This browser has disabled camera access. Allow it in your browser settings, or upload a photo.';
  }
  return 'Could not start your camera. Check camera access in your browser settings, then try again, or upload a photo.';
}

/** Handles permission prompts that finish after the user closes the camera. */
export function startCamera(
  mediaDevices: Pick<MediaDevices, 'getUserMedia'>,
  onStream: (stream: MediaStream) => void,
  onError: (error: unknown) => void,
): () => void {
  let closed = false;
  let stream: MediaStream | null = null;
  void (async () => {
    try {
      const next = await mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'user' }, width: { ideal: 1536 }, height: { ideal: 2048 } },
      });
      if (closed) { stopCamera(next); return; }
      stream = next;
      onStream(next);
    } catch (error) {
      stopCamera(stream);
      stream = null;
      if (!closed) onError(error);
    }
  })();
  return () => { closed = true; stopCamera(stream); stream = null; };
}
