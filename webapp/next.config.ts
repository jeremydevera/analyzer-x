import type { NextConfig } from "next";

const API = process.env.API_ORIGIN ?? "http://127.0.0.1:8787";

const nextConfig: NextConfig = {
  /* The API is proxied through this server, so the operator has ONE url and
   * the browser never makes a cross-origin request. Same rewrite in dev and
   * production, so what is verified is what ships. */
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
  /* A DOWNLOAD IS NOT A PAGE VIEW. Next's rewrite proxy gives an upstream
   * request 30 seconds and then answers "Internal Server Error" itself:
   *   next/dist/server/lib/router-utils/proxy-request.js
   *   proxyTimeout: proxyTimeout === null ? undefined : proxyTimeout || 30000
   * The operator's CSV download died on exactly that, twice, at 30.018 s and
   * 30.017 s — the API was still working on it. Cold on this store (28.65 GB,
   * mechanical disk, a backtest writing beside it) their own filter
   * (win rate >= 90, TP <= 4, SL <= 2, flat) needs 126.1 s to its first row,
   * and a `days` window re-measures every row it writes (~0.09 s a row, so a
   * 2,000-row window is ~3 minutes). http-proxy's timeout is an INACTIVITY
   * timeout, so a stream that is flowing never trips it; this only has to
   * cover the wait for the first byte. 30 minutes. */
  experimental: { proxyTimeout: 1_800_000 },
  webpack(config) {
    config.module.rules.push({
      test: /\.svg$/,
      use: ["@svgr/webpack"],
    });
    return config;
  },
    
    turbopack: {
      rules: {
        '*.svg': {
          loaders: ['@svgr/webpack'],
          as: '*.js',
        },
      },
    },
  
};

export default nextConfig;
