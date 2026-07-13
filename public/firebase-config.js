// ---------------------------------------------------------------------------
// Firebase WEB config for the dashboard (client-side, read-only).
//
// These values are NOT secret — a Firebase web apiKey is a public project
// identifier, and data is protected by the Firestore security rules (public
// read, no client write). It is safe to commit and to serve to browsers.
//
// HOW TO FILL THIS IN:
//   Firebase console → your "PIZZA TRAKER" project → Project settings (gear)
//   → "Your apps" → Web app (</>). Copy the firebaseConfig object here.
//   If you have no web app yet, click "Add app" → Web, give it a nickname,
//   and Firebase will show you these values.
// ---------------------------------------------------------------------------
window.FIREBASE_CONFIG = {
  apiKey: "AIzaSyCdRE_y1Vil0ABy-rdbED5KghX5zpB_gnQ",
  authDomain: "pizza-traker-7b255.firebaseapp.com",
  projectId: "pizza-traker-7b255",
  storageBucket: "pizza-traker-7b255.firebasestorage.app",
  messagingSenderId: "1064759464975",
  appId: "1:1064759464975:web:68c5aec436ad0df6133f7a",
  measurementId: "G-YW533F0902"
};

// Optional: URL of the "refresh now" trigger (the small Vercel function that
// kicks off the GitHub Actions scraper). Leave empty to hide the button.
// Example: "https://pizza-price-tracker.vercel.app/api/refresh"
window.REFRESH_ENDPOINT = "";
