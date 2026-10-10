#!/usr/bin/env node
/** Local component verification with Chrome's synthetic webcam. No login, uploads, or AI calls. */
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const frontend = resolve(root, 'frontend');
const requireFrontend = createRequire(resolve(frontend, 'package.json'));
const { createServer } = requireFrontend('vite');
const { chromium, devices } = requireFrontend('playwright');
const output = resolve(root, 'verification/browser/camera-report.json');
const checks = [];
const record = name => checks.push({ name, passed: true });
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const server = await createServer({ root: frontend, configFile: resolve(frontend, 'vite.config.ts'), appType: 'custom', server: { host: '127.0.0.1', port: 0 } });
const html = `<!doctype html><html><head><title>Camera verification</title></head><body><div id="root"></div><script type="module">
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import PhotoPicker from '/src/components/PhotoPicker.tsx';
import '/src/styles.css';
function Harness(){const[file,setFile]=useState(null);const[disabled,setDisabled]=useState(false);return React.createElement(React.Fragment,null,
React.createElement('button',{onClick:()=>setDisabled(true),id:'leave-photo'},'Leave photo screen'),
React.createElement(PhotoPicker,{file,disabled,holding:false,onChange:next=>{window.__cameraFile=next;setFile(next)}}));}
createRoot(document.getElementById('root')).render(React.createElement(Harness));
</script></body></html>`;
server.middlewares.use((req, res, next) => {
  if (req.url?.split('?')[0] !== '/__camera_test__') return next();
  void server.transformIndexHtml('/__camera_test__', html).then(transformed => { res.setHeader('Content-Type', 'text/html'); res.end(transformed); }).catch(error => { res.statusCode = 500; res.end(String(error)); });
});
let browser;
const errors = [];
try {
  await server.listen();
  const address = server.httpServer.address();
  const url = `http://127.0.0.1:${address.port}/__camera_test__`;
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36' });
  await context.addInitScript(() => {
    window.__cameraStreams = [];
    window.__cameraRequests = [];
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async constraints => {
      window.__cameraRequests.push(constraints);
      if (window.__cameraDeferred) await new Promise(resolve => { window.__grantCamera = resolve; });
      const stream = await original(constraints);
      window.__cameraStreams.push(stream);
      return stream;
    };
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  const uploads = [];
  page.on('request', request => { if (request.method() === 'POST' && /\/api\//.test(request.url())) uploads.push(request.url()); });
  await page.goto(url);
  await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
  const capture = page.getByRole('button', { name: 'Capture photo', exact: true });
  await capture.waitFor();
  await page.waitForFunction(() => { const button = Array.from(document.querySelectorAll('button')).find(button => button.textContent.includes('Capture photo')); return button && !button.disabled; });
  const dimensions = await page.locator('video').evaluate(video => ({ width: video.videoWidth, height: video.videoHeight }));
  assert(dimensions.width > 0 && dimensions.height > 0, 'Webcam preview did not produce video frames.');
  record('Mac desktop uses a live webcam preview');
  await page.evaluate(() => {
    const track = window.__cameraStreams[0].getVideoTracks()[0];
    window.__mockCameraMuted = true;
    Object.defineProperty(track, 'muted', { configurable: true, get: () => window.__mockCameraMuted });
    track.dispatchEvent(new Event('mute'));
  });
  await page.getByText('Your camera is paused.', { exact: false }).waitFor();
  assert(await capture.isDisabled(), 'A paused camera still allowed capturing black frames.');
  assert(await page.evaluate(() => !window.__cameraFile), 'Pausing the camera created a photo.');
  await page.evaluate(() => { window.__mockCameraMuted = false; window.__cameraStreams[0].getVideoTracks()[0].dispatchEvent(new Event('unmute')); });
  await page.waitForFunction(() => { const button = Array.from(document.querySelectorAll('button')).find(button => button.textContent.includes('Capture photo')); return button && !button.disabled; });
  assert(await page.getByText('Your camera is paused.', { exact: false }).count() === 0, 'Resuming the camera kept paused guidance visible.');
  record('Safari-style track mute disables capture and unmute restores the preview');
  await page.evaluate(() => { window.__mockCameraMuted = true; });
  await capture.click();
  await page.getByText('Your camera is paused.', { exact: false }).waitFor();
  assert(await capture.isDisabled() && await page.evaluate(() => !window.__cameraFile), 'Capture saved a muted frame before a mute event arrived.');
  await page.evaluate(() => { window.__mockCameraMuted = false; window.__cameraStreams[0].getVideoTracks()[0].dispatchEvent(new Event('unmute')); });
  await page.waitForFunction(() => { const button = Array.from(document.querySelectorAll('button')).find(button => button.textContent.includes('Capture photo')); return button && !button.disabled; });
  record('Capture independently rejects muted tracks before drawing a frame');
  await capture.click();
  await page.getByAltText('Your selected photo').waitFor();
  const image = await page.evaluate(async () => {
    const file = window.__cameraFile;
    const bitmap = await createImageBitmap(file);
    return { name: file.name, type: file.type, size: file.size, width: bitmap.width, height: bitmap.height };
  });
  assert(image.name === 'person-camera.jpg' && image.type === 'image/jpeg' && image.size > 0, 'Capture did not return a valid JPEG file.');
  assert(image.width === dimensions.width && image.height === dimensions.height, 'Camera capture distorted the original frame.');
  await page.waitForFunction(() => window.__cameraStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')));
  record('Capture creates a local JPEG and stops every media track');
  assert(await page.getByRole('button', { name: 'Crop', exact: true }).isVisible(), 'Captured photo cannot be cropped.');
  record('Captured photo retains the crop workflow');
  await page.getByRole('button', { name: 'Remove', exact: true }).click();
  await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
  await page.waitForFunction(() => window.__cameraStreams.length === 2);
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.waitForFunction(() => window.__cameraStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')));
  record('Closing the camera stops all tracks');
  await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
  await page.waitForFunction(() => window.__cameraStreams.length === 3);
  await page.evaluate(() => document.querySelector('#leave-photo').click());
  await page.waitForFunction(() => !document.querySelector('[role="dialog"]') && window.__cameraStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')));
  record('Disabling a hidden photo pane closes its dialog and camera');
  await page.reload();
  await page.evaluate(() => { window.__cameraDeferred = true; });
  await page.getByRole('button', { name: 'Take a photo', exact: true }).click();
  await page.waitForFunction(() => typeof window.__grantCamera === 'function');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.evaluate(() => window.__grantCamera());
  await page.waitForFunction(() => window.__cameraStreams.length === 1 && window.__cameraStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended')));
  record('Permission granted after closing is immediately stopped');
  assert(uploads.length === 0, 'Camera interaction uploaded a photograph.');
  assert(await page.evaluate(() => window.__cameraRequests.every(request => request.audio === false)), 'Camera requested microphone access.');
  record('Camera capture requests no microphone and sends no uploads');
  const denied = await context.newPage();
  await denied.addInitScript(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError')); });
  await denied.goto(url);
  await denied.getByRole('button', { name: 'Take a photo', exact: true }).click();
  const notice = denied.getByRole('alert');
  await notice.waitFor();
  assert((await notice.textContent()).includes('System Settings'), 'Permission failure lacked Mac camera guidance.');
  assert(await denied.getByRole('button', { name: 'Try camera again' }).isVisible(), 'Camera failure had no retry.');
  const chooser = await Promise.all([denied.waitForEvent('filechooser'), denied.getByRole('button', { name: 'Upload photo instead' }).click()]);
  assert(chooser[0], 'Upload fallback did not open the file picker.');
  assert(await denied.getByRole('dialog').count() === 0, 'Upload fallback kept the webcam dialog open.');
  record('Denied camera permission provides retry and upload fallback');
  for (const device of ['Pixel 7', 'iPhone 13', 'iPad Pro 11']) {
    const mobile = await browser.newContext(devices[device]);
    const mobilePage = await mobile.newPage();
    await mobilePage.goto(url);
    const [nativePicker] = await Promise.all([mobilePage.waitForEvent('filechooser'), mobilePage.getByRole('button', { name: 'Take a photo', exact: true }).click()]);
    assert(await nativePicker.element().getAttribute('capture') === 'user', `${device} lost native capture.`);
    assert(await mobilePage.getByRole('dialog').count() === 0, `${device} opened the desktop webcam dialog.`);
    record(`${device} preserves native camera capture`);
    await mobile.close();
  }
  assert(errors.length === 0, `Camera component raised browser errors: ${errors.join('; ')}`);
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify({ checked_at: new Date().toISOString(), passed: true, browser: 'Chrome with a synthetic webcam', physical_camera_testing: false, checks, errors }, null, 2) + '\n');
  console.log(`Camera browser verification passed: ${checks.length} checks.`);
} catch (error) {
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify({ checked_at: new Date().toISOString(), passed: false, checks, errors: [...errors, String(error)] }, null, 2) + '\n');
  throw error;
} finally {
  await browser?.close();
  await server.close();
}
