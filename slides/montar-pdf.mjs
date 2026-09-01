/**
 * Junta os artboards `.dc.html` num único HTML paginado, pronto para virar PDF.
 *
 * Cada slide é um `.dc.html` autocontido — bom para o canvas, onde cada um roda no seu
 * próprio iframe, e ruim para imprimir, onde tudo precisa estar numa página só. Este
 * script tira o embrulho (`<x-dc>`, `<helmet>`, o script do runtime) e remonta o miolo
 * de cada slide como uma página de 1440×810.
 *
 * A ordem vem do `canvas.json`, não da ordem alfabética dos arquivos: o canvas já é a
 * fonte da verdade sobre a sequência da apresentação, e duplicar essa ordem aqui seria
 * criar duas listas para manter em sincronia.
 *
 *   node montar-pdf.mjs > slides.html
 */

import { readFileSync } from "node:fs";

const LARGURA = 1440;
const ALTURA = 810;

const canvas = JSON.parse(readFileSync("canvas.json", "utf8"));

// Ordena pela posição no canvas — linha a linha, esquerda para a direita, que é como a
// apresentação é lida.
const ordem = [...canvas.artboards].sort((a, b) => a.y - b.y || a.x - b.x);

const paginas = ordem.map(({ file, title }) => {
  const bruto = readFileSync(file, "utf8");

  // O conteúdo visível é o que está entre <x-dc> e </x-dc>, menos o <helmet>
  // (fontes e estilos globais, que sobem uma vez só para o documento inteiro).
  const dentro = bruto.match(/<x-dc>([\s\S]*?)<\/x-dc>/);
  if (!dentro) throw new Error(`${file}: não achei o bloco <x-dc>`);

  const corpo = dentro[1].replace(/<helmet>[\s\S]*?<\/helmet>/, "").trim();
  return `<section class="slide" data-titulo="${title ?? file}">\n${corpo}\n</section>`;
});

process.stdout.write(`<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Contas a pagar Bill — slides</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
  /* Página do tamanho exato do slide: sem margem, sem escala, sem corte. */
  @page { size: ${LARGURA}px ${ALTURA}px; margin: 0; }

  html, body { margin: 0; padding: 0; background: #0a0820; }

  /* O <helmet> de cada artboard é removido na montagem (fontes e estilos globais
     sobem uma vez só, no <head> daqui), então a regra que lá dentro conserta a caixa
     precisa ser repetida aqui. Sem ela o container interno soma height:100% com o
     próprio padding, vira 944px numa moldura de 810 e perde 134px pelo rodapé. */
  *, *::before, *::after { box-sizing: border-box; }

  .slide {
    width: ${LARGURA}px;
    height: ${ALTURA}px;
    overflow: hidden;
    /* Cada slide é uma página. \`avoid\` interno impede que o Chrome tente quebrar
       um slide ao meio quando o conteúdo chega perto do limite. */
    page-break-after: always;
    break-after: page;
    page-break-inside: avoid;
    break-inside: avoid;
  }
  .slide:last-child { page-break-after: auto; break-after: auto; }

  /* Sem isso o Chrome descarta os fundos e gradientes na impressão, e um deck escuro
     sai em branco. */
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

  a { text-decoration: none; }
</style>
</head>
<body>
${paginas.join("\n\n")}
</body>
</html>
`);
