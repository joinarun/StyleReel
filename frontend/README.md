# StyleReel frontend

React 19, TypeScript, Vite, Tailwind 4, and Firebase Authentication. The FastAPI service serves `dist` in production. Local Vite requests `/api` through its proxy to `127.0.0.1:8000`.

```sh
npm ci
npm run dev
npm test
npm run build
```

The app obtains Firebase configuration from `/api/config`; no AI provider credentials are compiled into the browser. Email/password sign-in initializes reCAPTCHA Enterprise through the Firebase SDK. Accounts are administrator-created. The Auth emulator is connected only when the server explicitly returns its URL.

Photographs stay local until the user checks provider consent and submits. Protected photos are downloaded with Firebase ID-token authorization and displayed through short-lived object URLs. JPEG, PNG, WebP, and HEIC inputs are accepted; HEIC conversion occurs on the backend if the browser cannot decode the preview. Browsers with camera support can capture photos through the operating system’s camera picker. Cropping is available for browser-decodable photos.

The browser gallery encrypts all image bytes and garment metadata using AES-GCM with a stable account-specific key obtained from the authenticated backend. The key is imported as non-exportable, kept in memory, and cleared on logout. IndexedDB contains opaque IDs, account IDs, IVs, and ciphertext. Clearing browser data deletes this device’s collection. The same gallery does not synchronize across devices. Sharing a local result uploads it to temporary storage only when requested, then creates a 15-minute revocable bearer link. Share tokens are in URL fragments and are POSTed to the download endpoint.

`npm test` covers selection compatibility, native/sequential call estimates, encrypted storage and account isolation, logout locking, quota error guidance, and authenticated requests. Responsive CSS includes phone and tablet layouts; automated viewport inspection is separate from physical camera/device testing.
