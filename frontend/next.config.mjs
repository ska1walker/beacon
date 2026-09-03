/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone: das Container-Abbild trägt nur, was zur Laufzeit gebraucht
  // wird. Auf der Box zählt jedes hundert Megabyte.
  output: "standalone",
  // Keine Telemetrie — Kernprinzip, nicht Geschmackssache.
  async rewrites() {
    // Im Browser läuft alles über denselben Ursprung; der Envoy-Sidecar
    // sieht dadurch jeden API-Aufruf und prüft ihn. Ein direkter Aufruf
    // des Backends aus dem Browser käme an ihm vorbei.
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
