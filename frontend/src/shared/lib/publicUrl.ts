// Absolute URLs (canonical links, shared links) need the public address; VITE_PUBLIC_URL is set
// at image build time. Without it, the address the app was opened at stands in.
const BASE = (
  /^https?:\/\//.test(import.meta.env.VITE_PUBLIC_URL ?? "") ? import.meta.env.VITE_PUBLIC_URL! : window.location.origin
).replace(/\/$/, "");

export function publicUrl(path: string): string {
  return BASE + path;
}
