/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,

  // Baseline security headers for every response. The app makes no
  // third-party requests from the browser (everything goes through Next.js
  // API routes that proxy to the agent), and uses no inline event handlers,
  // so a strict CSP is workable. We allow inline <style> because Tailwind's
  // `style` props and the `<svg>` inline styles in ClusterMap would otherwise
  // need a nonce.
  async headers() {
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'", // Next.js inlines some bootstrap script
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      "connect-src 'self'", // /api/* are same-origin, so 'self' is enough
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ].join("; ");

    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "geolocation=(), camera=(), microphone=(), payment=()" },
        ],
      },
    ];
  },
};
export default nextConfig;
