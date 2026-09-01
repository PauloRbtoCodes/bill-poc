/** @type {import('next').NextConfig} */
export default {
  // Em desenvolvimento a API roda separada, em :8000, e o rewrite evita CORS.
  // Em produção na Vercel o roteamento é feito pelo vercel.json, que manda /api/* para
  // a função Python — então o rewrite aqui só atrapalharia.
  async rewrites() {
    if (process.env.VERCEL) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};
