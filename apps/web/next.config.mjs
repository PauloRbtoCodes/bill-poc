/** @type {import('next').NextConfig} */
export default {
  // A API roda separada, em :8000. O rewrite deixa o front chamar /api/* sem CORS
  // e sem espalhar a URL do backend por todo componente.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*` }];
  },
};
