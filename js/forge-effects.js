/**
 * Armory Forge Systems — Forge Effects Engine v2
 * Pass 1: Ember particles, heat shimmer, spark bursts, molten glow
 * Pass 2: Cooling reveals, header scorch, progress bar, anvil strikes
 */
(function () {
  'use strict';

  // ── Canvas Ember System ──────────────────────────────────
  const canvas = document.getElementById('forge-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let w, h;
  const embers = [];
  const MAX_EMBERS = 80;

  function resize() {
    w = canvas.width = canvas.offsetWidth;
    h = canvas.height = canvas.offsetHeight;
  }
  window.addEventListener('resize', resize);
  resize();

  // ── Ember Particle ───────────────────────────────────────
  class Ember {
    constructor() {
      this.reset(true);
    }

    reset(initial) {
      this.x = Math.random() * w;
      this.y = initial ? Math.random() * h : h + 20;
      this.r = Math.random() * 3 + 1;
      this.vx = (Math.random() - 0.5) * 0.8;
      this.vy = -(Math.random() * 1.2 + 0.4);
      this.life = Math.random() * 0.7 + 0.3;
      this.flicker = Math.random() * Math.PI * 2;
      this.flickerSpeed = Math.random() * 0.04 + 0.01;
      this.decay = Math.random() * 0.003 + 0.001;
      this.color = Math.random() < 0.6
        ? { r: 255, g: 140 + Math.floor(Math.random() * 60), b: 20 }
        : { r: 255, g: 60 + Math.floor(Math.random() * 40), b: 0 };
    }

    update() {
      this.y += this.vy;
      this.x += this.vx + Math.sin(this.flicker) * 0.3;
      this.flicker += this.flickerSpeed;
      this.life -= this.decay;
      if (this.life <= 0 || this.y < -10 || this.x < -10 || this.x > w + 10) {
        this.reset(false);
      }
    }

    draw(ctx) {
      const alpha = this.life * (0.7 + Math.sin(this.flicker) * 0.3);
      const grad = ctx.createRadialGradient(this.x, this.y, 0, this.x, this.y, this.r * 2.5);
      grad.addColorStop(0, `rgba(${this.color.r},${this.color.g},${this.color.b},${alpha})`);
      grad.addColorStop(0.4, `rgba(${this.color.r},${this.color.g},${this.color.b},${alpha * 0.6})`);
      grad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.r * 2.5, 0, Math.PI * 2);
      ctx.fillStyle = grad;
      ctx.fill();
    }
  }

  for (let i = 0; i < MAX_EMBERS; i++) embers.push(new Ember());

  // ── Spark (short-lived burst particle) ────────────────────
  class Spark {
    constructor(x, y, angle, speed, color, size) {
      this.x = x;
      this.y = y;
      this.vx = Math.cos(angle) * speed;
      this.vy = Math.sin(angle) * speed;
      this.life = 1;
      this.decay = Math.random() * 0.03 + 0.02;
      this.color = color || { r: 255, g: 180, b: 40 };
      this.size = size || Math.random() * 2 + 1;
    }
    update() {
      this.x += this.vx;
      this.y += this.vy;
      this.vy += 0.05;
      this.life -= this.decay;
      return this.life > 0;
    }
    draw(ctx) {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.size * this.life, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${this.color.r},${this.color.g},${this.color.b},${this.life})`;
      ctx.fill();
    }
  }

  const sparks = [];

  function sparkBurst(x, y, count = 20, intensity = 1) {
    const speedMul = intensity;
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.5;
      const speed = (Math.random() * 4 + 2) * speedMul;
      const color = Math.random() < 0.5
        ? { r: 255, g: 180, b: 40 }
        : { r: 255, g: 100, b: 10 };
      sparks.push(new Spark(x, y, angle, speed, color, Math.random() * 3 + 1.5));
    }
    for (let i = 0; i < Math.floor(6 * intensity); i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = (Math.random() * 1.5 + 0.5) * speedMul;
      sparks.push(new Spark(x, y, angle, speed, { r: 255, g: 160, b: 30 }, Math.random() * 4 + 2));
    }
  }

  // Anvil strike burst (downward-focused, heavier)
  function anvilStrike(x, y) {
    for (let i = 0; i < 35; i++) {
      const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 0.8;
      const speed = Math.random() * 6 + 3;
      sparks.push(new Spark(x, y, angle, speed,
        { r: 255, g: 200, b: 50 }, Math.random() * 4 + 2));
    }
    for (let i = 0; i < 15; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = Math.random() * 8 + 4;
      sparks.push(new Spark(x, y, angle, speed,
        { r: 255, g: 120, b: 20 }, Math.random() * 5 + 3));
    }
  }

  // ── Render loop ──────────────────────────────────────────
  function animate() {
    ctx.clearRect(0, 0, w, h);
    for (const e of embers) { e.update(); e.draw(ctx); }
    for (let i = sparks.length - 1; i >= 0; i--) {
      if (!sparks[i].update()) sparks.splice(i, 1);
      else sparks[i].draw(ctx);
    }
    requestAnimationFrame(animate);
  }
  animate();

  // ═══════════════════════════════════════════════════════════
  // PASS 2 — Scroll-Driven Effects
  // ═══════════════════════════════════════════════════════════

  // ── Scroll progress bar ──────────────────────────────────
  const progressBar = document.createElement('div');
  progressBar.id = 'forge-progress';
  document.body.prepend(progressBar);

  // ── Header scorch on scroll ──────────────────────────────
  const header = document.querySelector('header');
  const heroSection = document.getElementById('hero');

  function updateScrollFX() {
    const scrollY = window.scrollY;
    const docH = document.documentElement.scrollHeight - window.innerHeight;
    const pct = docH > 0 ? Math.min((scrollY / docH) * 100, 100) : 0;

    // Progress bar
    progressBar.style.width = pct + '%';

    // Header scorch: intensifies after 100px of scroll
    if (scrollY > 80) {
      header.classList.add('forge-scorched');
    } else {
      header.classList.remove('forge-scorched');
    }
  }

  // ── Cooling reveal observer ──────────────────────────────
  const forgeReveals = document.querySelectorAll('.hidden, .services, .about, .forge-banner');

  // Convert existing .hidden elements to .forge-reveal
  forgeReveals.forEach((el) => {
    if (el.classList.contains('hidden')) {
      el.classList.remove('hidden');
      el.classList.add('forge-reveal');
    }
    // Also target cards and titles inside
    el.querySelectorAll('.card').forEach(c => c.classList.add('forge-reveal'));
    el.querySelectorAll('h2').forEach(h => {
      if (!h.closest('.hero') && !h.closest('.contact')) {
        h.classList.add('forge-title');
      }
    });
  });

  // Also add forge-reveal to the about-image
  const aboutImage = document.querySelector('.about-image');
  if (aboutImage) aboutImage.classList.add('forge-reveal');

  const coolingObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        // Cool the element
        entry.target.classList.add('forge-cooled');

        // Brand titles inside
        entry.target.querySelectorAll('.forge-title').forEach(t => {
          setTimeout(() => t.classList.add('forge-branded'), 200);
        });

        // Fire spark burst — intensified for sections
        const rect = entry.target.getBoundingClientRect();
        const isSection = entry.target.tagName === 'SECTION';
        const sparkCount = isSection ? 40 : 15;
        const intensity = isSection ? 1.5 : 1;
        sparkBurst(
          rect.left + rect.width / 2,
          rect.top + (isSection ? 30 : rect.height / 2),
          sparkCount,
          intensity
        );

        // Anvil strike for forge-banner
        if (entry.target.id === 'forge-banner') {
          setTimeout(() => anvilStrike(rect.left + rect.width / 2, rect.top + 120), 500);
          setTimeout(() => anvilStrike(rect.left + rect.width * 0.3, rect.top + 80), 800);
          setTimeout(() => anvilStrike(rect.left + rect.width * 0.7, rect.top + 100), 1000);
        }
      }
    });
  }, { threshold: 0.2 });

  // Observe all forge-reveal elements
  document.querySelectorAll('.forge-reveal').forEach(el => coolingObserver.observe(el));

  // ── Heat haze strips on sections ─────────────────────────
  document.querySelectorAll('section').forEach((section) => {
    if (section.id === 'hero') return;
    const haze = document.createElement('div');
    haze.className = 'heat-haze';
    section.style.position = section.style.position || 'relative';
    section.insertBefore(haze, section.firstChild);

    const hazeObserver = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) haze.classList.add('active');
        else haze.classList.remove('active');
      });
    }, { threshold: 0.1 });
    hazeObserver.observe(section);
  });

  // ── Scroll listener ──────────────────────────────────────
  let scrollTicking = false;
  window.addEventListener('scroll', () => {
    if (!scrollTicking) {
      requestAnimationFrame(() => {
        updateScrollFX();
        scrollTicking = false;
      });
      scrollTicking = true;
    }
  });
  updateScrollFX(); // initial

  // ── Button hover spark trail ─────────────────────────────
  document.querySelectorAll('.btn, .btn-primary').forEach((btn) => {
    btn.addEventListener('mouseenter', () => {
      const rect = btn.getBoundingClientRect();
      sparkBurst(rect.left + rect.width / 2, rect.top + rect.height / 2, 10, 0.8);
    });
  });

  // ── Card hover edge sparks ───────────────────────────────
  document.querySelectorAll('.card, .tech-card').forEach((card) => {
    card.addEventListener('mouseenter', () => {
      const rect = card.getBoundingClientRect();
      for (let i = 0; i < 5; i++) {
        sparkBurst(rect.left + (rect.width / 4) * (i + 0.5), rect.bottom - 4, 4, 0.7);
      }
    });
  });

  // ── Expose API ──────────────────────────────────────────
  window.AFSForge = { sparkBurst, anvilStrike };
})();
