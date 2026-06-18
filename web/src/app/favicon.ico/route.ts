const FAVICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#101820"/>
  <path d="M18 42h28" stroke="#e7f0ea" stroke-width="4" stroke-linecap="round"/>
  <path d="M22 38l9-12 8 7 8-15" fill="none" stroke="#39c980" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="47" cy="18" r="4" fill="#f6c85f"/>
</svg>`;

export function GET() {
  return new Response(FAVICON_SVG, {
    headers: {
      "content-type": "image/svg+xml; charset=utf-8",
      "cache-control": "public, max-age=86400",
    },
  });
}
