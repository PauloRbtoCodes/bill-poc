/**
 * Junta os artboards `.dc.html` num único arquivo que serve para as duas coisas:
 *
 *   na tela   — modo apresentação, um slide por vez, navegável pelo teclado
 *   no papel  — um slide por página, tamanho exato, pronto para virar PDF
 *
 * São o mesmo documento porque são o mesmo conteúdo: separar em dois arquivos criaria
 * duas versões para manter em sincronia, e a que não está aberta é sempre a
 * desatualizada. O que muda entre os dois é só CSS — `@media screen` monta o palco,
 * `@media print` desmonta e pagina.
 *
 * A ordem vem do `canvas.json`, que já é a fonte da verdade sobre a sequência.
 *
 *   node montar.mjs > apresentacao.html
 */

import { readFileSync } from "node:fs";

const LARGURA = 1440;
const ALTURA = 810;

const canvas = JSON.parse(readFileSync("canvas.json", "utf8"));

// Linha a linha, esquerda para a direita — como a apresentação é lida no canvas.
const ordem = [...canvas.artboards].sort((a, b) => a.y - b.y || a.x - b.x);

const paginas = ordem.map(({ file, title }, i) => {
  const bruto = readFileSync(file, "utf8");
  const dentro = bruto.match(/<x-dc>([\s\S]*?)<\/x-dc>/);
  if (!dentro) throw new Error(`${file}: não achei o bloco <x-dc>`);

  const corpo = dentro[1].replace(/<helmet>[\s\S]*?<\/helmet>/, "").trim();
  const rotulo = (title ?? file).replace(/"/g, "&quot;");
  return `<section class="slide" data-n="${i + 1}" data-titulo="${rotulo}">\n${corpo}\n</section>`;
});

process.stdout.write(`<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contas a pagar Bill</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
  /* O <helmet> de cada artboard é removido na montagem, então a regra que lá dentro
     conserta a caixa precisa ser repetida aqui. Sem ela o container interno soma
     height:100% com o próprio padding e estoura a moldura por 134px. */
  *, *::before, *::after { box-sizing: border-box; }

  html, body { margin: 0; padding: 0; background: #07061a; }

  .slide {
    width: ${LARGURA}px;
    height: ${ALTURA}px;
    overflow: hidden;
    flex-shrink: 0;
  }

  /* Fundos e gradientes: sem isto o Chrome os descarta na impressão e um deck escuro
     sai em branco. */
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  /* Sem uma cor explícita, um link renderiza no azul padrão do navegador — ilegível
     sobre o fundo escuro, e o helmet de cada artboard (que define a sua) é removido
     na montagem. */
  a { text-decoration: none; color: #c4c0ff; }

  /* ======================================================================
     TELA — modo apresentação
     ====================================================================== */
  @media screen {
    body {
      height: 100dvh;
      overflow: hidden;
      display: grid;
      place-items: center;
      font-family: Inter, system-ui, sans-serif;
    }

    /* O palco escala o slide inteiro para caber na janela, seja ela qual for. O slide
       continua com 1440×810 reais — só o transform muda — então nada reflui e o
       layout é idêntico ao do PDF. */
    #palco {
      width: ${LARGURA}px;
      height: ${ALTURA}px;
      transform-origin: center center;
      position: relative;
    }

    .slide {
      position: absolute;
      inset: 0;
      opacity: 0;
      visibility: hidden;
      transition: opacity 180ms ease;
    }
    .slide[data-ativo] { opacity: 1; visibility: visible; }

    /* Barra de progresso: fina, no rodapé, sem roubar atenção do conteúdo. */
    #progresso {
      position: fixed; left: 0; bottom: 0; height: 3px; z-index: 10;
      background: linear-gradient(90deg, #4b39ef, #727de4);
      transition: width 220ms ease;
      box-shadow: 0 0 10px -1px #727de4;
    }

    #contador {
      position: fixed; right: 22px; bottom: 18px; z-index: 10;
      font-family: Outfit, sans-serif; font-size: 13px; letter-spacing: .04em;
      color: rgba(250,255,253,.35);
      font-variant-numeric: tabular-nums;
      transition: opacity 300ms ease;
    }

    #ajuda {
      position: fixed; left: 22px; bottom: 16px; z-index: 10;
      font-size: 12px; color: rgba(250,255,253,.3);
      transition: opacity 400ms ease;
    }
    body.quieto #ajuda, body.quieto #contador { opacity: 0; }

    /* Visão geral (tecla O ou Esc): todos os slides em grade, clicáveis. */
    #grade {
      position: fixed; inset: 0; z-index: 20; display: none;
      background: rgba(7,6,26,.97);
      overflow-y: auto; padding: 32px;
    }
    body.vendo-grade #grade { display: grid; }
    #grade {
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 22px; align-content: start;
    }
    .miniatura {
      position: relative; aspect-ratio: 16 / 9; overflow: hidden;
      border-radius: 10px; border: 1px solid rgba(255,255,255,.12);
      cursor: pointer; background: #14103d;
      transition: border-color 140ms ease, transform 140ms ease;
    }
    .miniatura:hover { border-color: #727de4; transform: translateY(-2px); }
    .miniatura[data-atual] { border-color: #c4c0ff; box-shadow: 0 0 0 2px rgba(196,192,255,.3); }
    .miniatura span {
      position: absolute; inset: auto 0 0 0; z-index: 2; padding: 8px 10px;
      background: linear-gradient(transparent, rgba(7,6,26,.92));
      font-size: 12px; color: rgba(250,255,253,.85);
    }
  }

  /* ======================================================================
     IMPRESSÃO — um slide por página
     ====================================================================== */
  @media print {
    @page { size: ${LARGURA}px ${ALTURA}px; margin: 0; }

    #progresso, #contador, #ajuda, #grade { display: none !important; }
    body { display: block; }
    #palco { transform: none !important; width: auto; height: auto; }

    .slide {
      position: static;
      opacity: 1 !important;
      visibility: visible !important;
      page-break-after: always;
      break-after: page;
      page-break-inside: avoid;
      break-inside: avoid;
    }
    .slide:last-child { page-break-after: auto; break-after: auto; }
  }
</style>
</head>
<body>

<div id="palco">
${paginas.join("\n\n")}
</div>

<div id="progresso"></div>
<p id="contador"></p>
<p id="ajuda">← → navegar · F tela cheia · O visão geral</p>
<div id="grade"></div>

<script>
(() => {
  const slides = [...document.querySelectorAll('.slide')];
  const palco = document.getElementById('palco');
  const progresso = document.getElementById('progresso');
  const contador = document.getElementById('contador');
  const grade = document.getElementById('grade');
  let atual = 0;

  // Escala o palco para caber na janela sem nunca cortar. O slide mantém 1440×810
  // reais — só o transform muda — então o layout é byte a byte o mesmo do PDF.
  function ajustar() {
    const escala = Math.min(innerWidth / ${LARGURA}, innerHeight / ${ALTURA});
    palco.style.transform = 'scale(' + escala + ')';
  }

  function ir(n) {
    atual = Math.max(0, Math.min(slides.length - 1, n));
    slides.forEach((s, i) => s.toggleAttribute('data-ativo', i === atual));
    progresso.style.width = ((atual + 1) / slides.length * 100) + '%';
    contador.textContent = (atual + 1) + ' / ' + slides.length;
    grade.querySelectorAll('.miniatura').forEach((m, i) =>
      m.toggleAttribute('data-atual', i === atual));
    // O hash deixa recarregar a página sem perder o lugar — útil quando algo trava
    // no meio de uma apresentação.
    history.replaceState(null, '', '#' + (atual + 1));
  }

  // A visão geral usa iframes com o mesmo documento, cada um travado num slide.
  // Clonar os nós daria conflito de id e de estilo entre as cópias.
  function montarGrade() {
    if (grade.dataset.pronta) return;
    slides.forEach((s, i) => {
      const cel = document.createElement('div');
      cel.className = 'miniatura';
      cel.innerHTML = '<span>' + s.dataset.titulo + '</span>';
      const frame = document.createElement('iframe');
      frame.src = location.pathname + '#' + (i + 1);
      Object.assign(frame.style, {
        width: '${LARGURA}px', height: '${ALTURA}px', border: '0',
        transformOrigin: 'top left', position: 'absolute', top: '0', left: '0',
        pointerEvents: 'none',
      });
      cel.appendChild(frame);
      const escalar = () => {
        frame.style.transform = 'scale(' + (cel.clientWidth / ${LARGURA}) + ')';
      };
      new ResizeObserver(escalar).observe(cel);
      cel.onclick = () => { ir(i); document.body.classList.remove('vendo-grade'); };
      grade.appendChild(cel);
    });
    grade.dataset.pronta = '1';
  }

  addEventListener('keydown', (e) => {
    const naGrade = document.body.classList.contains('vendo-grade');
    switch (e.key) {
      case 'ArrowRight': case 'ArrowDown': case ' ': case 'PageDown':
        e.preventDefault(); ir(atual + 1); break;
      case 'ArrowLeft': case 'ArrowUp': case 'PageUp':
        e.preventDefault(); ir(atual - 1); break;
      case 'Home': ir(0); break;
      case 'End': ir(slides.length - 1); break;
      case 'f': case 'F':
        document.fullscreenElement ? document.exitFullscreen()
                                   : document.documentElement.requestFullscreen();
        break;
      case 'o': case 'O':
        montarGrade(); document.body.classList.toggle('vendo-grade'); break;
      case 'Escape':
        if (naGrade) document.body.classList.remove('vendo-grade');
        break;
      default:
        if (/^[0-9]$/.test(e.key)) ir(Number(e.key) - 1);
    }
  });

  // Clique avança; clique no terço esquerdo volta. É o gesto que se espera de um
  // apresentador com o mouse na mão e sem olhar para o teclado.
  addEventListener('click', (e) => {
    if (document.body.classList.contains('vendo-grade')) return;
    ir(e.clientX < innerWidth / 3 ? atual - 1 : atual + 1);
  });

  // A ajuda some sozinha depois de um tempo parado, e volta ao menor movimento.
  let ocioso;
  const acordar = () => {
    document.body.classList.remove('quieto');
    clearTimeout(ocioso);
    ocioso = setTimeout(() => document.body.classList.add('quieto'), 3500);
  };
  ['mousemove', 'keydown', 'click'].forEach((ev) => addEventListener(ev, acordar));

  addEventListener('resize', ajustar);
  ajustar();
  acordar();
  ir(Number(location.hash.slice(1)) - 1 || 0);
})();
</script>
</body>
</html>
`);
