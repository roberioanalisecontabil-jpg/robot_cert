/**
 * Fundo com parallax, variante "Montanhas" (05/11/2026).
 * Quatro cordilheiras no pé da janela com perspectiva atmosférica: a de
 * longe é a mais clara e a mais lenta, a de perto a mais escura e a mais
 * rápida. Névoa entre as camadas; lua só no escuro.
 * Carregado por ui-common.js, logo nunca no login. Custo: um listener
 * passivo + um requestAnimationFrame por quadro rolado, só `transform`.
 */
(function () {
  if (document.querySelector(".cg-fundo")) return;

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/static/fundo-parallax.css?v=fundo-montanhas-2026-11-05b";
  document.head.appendChild(link);

  // Sorteio com semente fixa: a paisagem é a mesma em toda tela e recarga.
  function sorteio(semente) {
    return function () {
      semente = (semente + 0x6D2B79F5) | 0;
      let t = Math.imul(semente ^ (semente >>> 15), 1 | semente);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Crista = soma de senoides com fases sorteadas + um pouco de ruído.
  function serra(semente, alto, base, amplitude, aspereza) {
    const r = sorteio(semente);
    const ondas = [1, 2.3, 5.1, 11].map(function (f) {
      return { f: f, fase: r() * Math.PI * 2, peso: 1 / f };
    });
    let d = "M0 " + alto;
    for (let x = 0; x <= 1600; x += 16) {
      let y = 0;
      for (const o of ondas) y += Math.sin(x / 1600 * Math.PI * 2 * o.f + o.fase) * o.peso;
      y = base - y * amplitude - (r() - 0.5) * aspereza;
      d += "L" + x + " " + y.toFixed(1);
    }
    d += "L1600 " + alto + "Z";
    return '<svg viewBox="0 0 1600 ' + alto + '" preserveAspectRatio="xMidYMax slice"><path d="' + d + '"/></svg>';
  }

  const fundo = document.createElement("div");
  fundo.className = "cg-fundo";
  fundo.setAttribute("aria-hidden", "true");
  fundo.innerHTML =
    '<i class="cg-fundo__astro" data-vel="0.01"></i>' +
    '<div class="cg-fundo__serra cg-fundo__serra--4" data-vel="0.015">' + serra(5, 400, 170, 70, 6) + "</div>" +
    '<div class="cg-fundo__serra cg-fundo__serra--3" data-vel="0.04">' + serra(17, 340, 170, 60, 8) + "</div>" +
    '<div class="cg-fundo__serra cg-fundo__serra--2" data-vel="0.075">' + serra(29, 280, 150, 55, 10) + "</div>" +
    '<div class="cg-fundo__serra cg-fundo__serra--1" data-vel="0.12">' + serra(41, 200, 110, 45, 12) + "</div>";
  document.body.prepend(fundo);

  const reduz = window.matchMedia("(prefers-reduced-motion: reduce)");
  const planos = Array.from(fundo.querySelectorAll("[data-vel]"));
  let pedido = 0;

  function aplicar() {
    pedido = 0;
    // a paisagem afunda com a rolagem; teto para não sumir em página longa
    const y = reduz.matches ? 0 : Math.min(window.scrollY, 1200);
    for (const p of planos) {
      p.style.transform = "translate3d(0," + (y * p.dataset.vel).toFixed(1) + "px,0)";
    }
  }

  window.addEventListener("scroll", function () {
    if (!pedido) pedido = requestAnimationFrame(aplicar);
  }, { passive: true });
  reduz.addEventListener("change", aplicar);
  aplicar();
})();
