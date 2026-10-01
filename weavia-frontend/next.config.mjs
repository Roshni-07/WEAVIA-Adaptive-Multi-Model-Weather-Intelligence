const API = process.env.WEAVIA_API || "http://127.0.0.1:8000";
/** UI consumes the API only. /api/v1/* is proxied to FastAPI so the browser never needs CORS. */
export default {
  reactStrictMode: true,
  transpilePackages: ["three"],
  async rewrites() { return [{ source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` }]; },
};
