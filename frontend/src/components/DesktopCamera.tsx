import { useEffect, useRef, useState } from 'react';
import { Camera, RotateCcw, Upload } from 'lucide-react';
import { cameraErrorMessage, startCamera, stopCamera } from '../lib/camera';
import { Modal, Notice, Spinner } from './Common';
import './DesktopCamera.css';

export default function DesktopCamera({ onCapture, onClose, onUpload, holding }: {
  onCapture: (file: File) => void;
  onClose: () => void;
  onUpload: () => void;
  holding: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const sessionRef = useRef(0);
  const [attempt, setAttempt] = useState(0);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'paused' | 'error'>('loading');
  const [error, setError] = useState('');
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    sessionRef.current += 1;
    setPhase('loading');
    setError('');
    const video = videoRef.current;
    let camera: MediaStream | null = null;
    const ended = () => {
      stopCamera(camera);
      setError('The camera stopped. Try again, or upload a photo.');
      setPhase('error');
    };
    const muted = () => { setError(''); setPhase('paused'); };
    const unmuted = () => {
      const tracks = camera?.getVideoTracks() || [];
      if (tracks.length && tracks.every(track => !track.muted && track.readyState === 'live')) {
        setPhase(video && video.readyState >= 2 && video.videoWidth > 0 ? 'ready' : 'loading');
      }
    };
    const fail = (failure: unknown) => { stopCamera(camera); setError(cameraErrorMessage(failure)); setPhase('error'); };
    let close = () => {};
    if (!window.isSecureContext) {
      setError('Open StyleReel using its HTTPS address to use your camera, or upload a photo.');
      setPhase('error');
    } else if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser does not support camera capture. Open StyleReel in a current browser, or upload a photo.');
      setPhase('error');
    } else {
      close = startCamera(navigator.mediaDevices, stream => {
        camera = stream;
        stream.getVideoTracks().forEach(track => {
          track.addEventListener('ended', ended);
          track.addEventListener('mute', muted);
          track.addEventListener('unmute', unmuted);
        });
        if (stream.getVideoTracks().some(track => track.muted)) muted();
        if (video) {
          video.srcObject = stream;
          const session = sessionRef.current;
          void video.play().catch(failure => { if (sessionRef.current === session) fail(failure); });
        }
      }, fail);
    }
    return () => {
      sessionRef.current += 1;
      camera?.getVideoTracks().forEach(track => {
        track.removeEventListener('ended', ended);
        track.removeEventListener('mute', muted);
        track.removeEventListener('unmute', unmuted);
      });
      close();
      if (video) video.srcObject = null;
    };
  }, [attempt]);

  async function capture() {
    const video = videoRef.current;
    if (!video || phase !== 'ready' || capturing || !video.videoWidth || !video.videoHeight) return;
    const stream = video.srcObject as MediaStream | null;
    const tracks = stream?.getVideoTracks() || [];
    if (!tracks.length || tracks.some(track => track.readyState !== 'live')) {
      setError('The camera stopped. Try again, or upload a photo.');
      setPhase('error');
      return;
    }
    if (tracks.some(track => track.muted)) { setPhase('paused'); return; }
    const session = sessionRef.current;
    setCapturing(true);
    setError('');
    try {
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 3072 / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Could not capture the photo. Try again, or upload a photo.');
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
        image => image ? resolve(image) : reject(new Error('Could not capture the photo. Try again, or upload a photo.')),
        'image/jpeg', 0.94,
      ));
      if (sessionRef.current === session) {
        onCapture(new File([blob], 'person-camera.jpg', { type: 'image/jpeg' }));
      }
    } catch (failure) {
      if (sessionRef.current === session) setError(failure instanceof Error ? failure.message : 'Could not capture the photo. Try again, or upload a photo.');
    } finally {
      if (sessionRef.current === session) setCapturing(false);
    }
  }

  return <Modal title="Take a photo" onClose={onClose}>
    <div className={`desktop-camera-preview ${phase === 'ready' ? 'camera-ready' : ''}`}>
      <video ref={videoRef} autoPlay muted playsInline aria-label="Live camera preview" onLoadedData={() => {
        const video = videoRef.current;
        const stream = video?.srcObject as MediaStream | null;
        const tracks = stream?.getVideoTracks() || [];
        if (phase !== 'error' && video && video.videoWidth > 0 && tracks.length && tracks.every(track => !track.muted && track.readyState === 'live')) setPhase('ready');
      }} />
      {phase !== 'ready' && <div className="desktop-camera-state">
        {phase === 'loading' ? <Spinner label="Allow camera access to start the preview" /> : <Camera size={38} aria-hidden="true" />}
      </div>}
    </div>
    <p className="desktop-camera-guidance">{holding
      ? 'Keep your face, full body, and the garment’s front and edges in view.'
      : 'Stand back so your face and full body are visible. Use soft, even lighting.'}</p>
    {error && <Notice tone="error">{error}</Notice>}
    {phase === 'paused' && <Notice>Your camera is paused. Resume it using your browser’s camera control, or close another tab using the camera. You can also upload a photo.</Notice>}
    <div className="desktop-camera-actions">
      {phase === 'error'
        ? <button className="button primary" onClick={() => setAttempt(value => value + 1)}><RotateCcw size={16} /> Try camera again</button>
        : <button className="button primary" onClick={capture} disabled={phase !== 'ready' || capturing}>{capturing ? <Spinner label="Capturing photo" /> : <><Camera size={16} /> Capture photo</>}</button>}
      <button className="button secondary" onClick={onUpload}><Upload size={16} /> Upload photo instead</button>
    </div>
    <p className="desktop-camera-local">Your camera photo stays on this device until you generate a look.</p>
  </Modal>;
}
