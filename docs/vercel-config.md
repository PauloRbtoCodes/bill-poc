# Notas sobre o `vercel.json`

O arquivo é enxuto porque o schema da Vercel rejeita chaves extras (inclusive `"//"`
como comentário). O que cada parte faz:

- **`builds` com dois runtimes.** Monorepo com Next.js em `apps/web` e a API Python em
  `api/`. A forma declarativa é a que suporta dois frameworks em diretórios diferentes;
  a detecção automática assume um só na raiz.

- **`includeFiles: "apps/api/src/**"`.** O pacote `billpoc` mora fora do diretório da
  função (`api/`). Sem isso o `import billpoc` falha em produção e passa despercebido no
  build local.

- **`routes`.** `/api/*` vai para a função Python; o resto o `@vercel/next` resolve.
  Front e API no mesmo domínio — sem CORS, sem URL de backend no código.
