// Hosts permitidos no CSP. Lemos as envs em build time — em dev caímos para
// localhost. Supabase usa subdomínio do projeto + wildcard storage.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:3333";

function origemDe(u) {
  try {
    const url = new URL(u);
    return `${url.protocol}//${url.host}`;
  } catch {
    return "";
  }
}

const supabaseOrigin = origemDe(supabaseUrl);
const supabaseWs = supabaseOrigin.replace(/^https?/, "wss");
const apiOrigin = origemDe(apiUrl);

const csp = [
  "default-src 'self'",
  // Next 14 injeta scripts inline; sem nonce, precisamos de 'unsafe-inline'.
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
  `img-src 'self' data: blob: ${supabaseOrigin}`.trim(),
  `connect-src 'self' ${supabaseOrigin} ${supabaseWs} ${apiOrigin}`.replace(/\s+/g, " ").trim(),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const isProd = process.env.NODE_ENV === "production";

// CSP só em produção. Em dev, o Next abre WebSocket (ws://...) para HMR
// e usa eval para Fast Refresh — uma CSP estrita quebra ambos.
const securityHeaders = [
  ...(isProd ? [{ key: "Content-Security-Policy", value: csp }] : []),
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [{ protocol: "https", hostname: "**" }],
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
