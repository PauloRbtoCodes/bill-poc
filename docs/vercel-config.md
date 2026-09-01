# Notas sobre o `vercel.json`

O arquivo é enxuto porque o schema da Vercel rejeita chaves extras (inclusive `"//"`
como comentário). O que cada parte faz:

- **Next.js na raiz.** A Vercel detecta o framework automaticamente quando o
  `package.json` está na raiz do projeto. Tentar mantê-lo em `apps/web` com a config
  legada (`builds` + `routes`) fazia o front dar 404 enquanto a API funcionava: aquela
  forma não mescla as rotas geradas pelo build do Next.

- **`functions` + `rewrites` para a API.** A função Python em `api/index.py` recebe
  `/api/*`. `rewrites` (ao contrário de `routes`) convive com o roteamento do Next.

- **`includeFiles: "apps/api/src/**"`.** O pacote `billpoc` mora fora do diretório da
  função. Sem isso o `import billpoc` falha em produção e passa despercebido no build.

Front e API no mesmo domínio — sem CORS, sem URL de backend no código.
