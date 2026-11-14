// 3D preview for card decks: a stack that fans out into a grid of slowly
// spinning cards, with click-to-inspect. View-only by design.
//
// Each card face is the live HTML page that gets printed, placed in 3D with
// three.js's CSS3DRenderer. Nothing is rasterized ahead of time, so edits show
// immediately and the preview is the print.
import * as THREE from 'three';
import { CSS3DRenderer, CSS3DObject } from 'three/addons/renderers/CSS3DRenderer.js';

const PX = 96; // CSS px per inch
const FOV = 32;
const TAU = Math.PI * 2;
const FOCUS_RES = 2; // the inspected card is laid out at this multiple so it stays sharp up close
const damp = (cur, target, rate, dt) => target + (cur - target) * Math.exp(-rate * dt);
const nearestTurn = (angle, offset = 0) => Math.round((angle - offset) / TAU) * TAU + offset;

const STYLE = `
.bmt-face { backface-visibility: hidden; -webkit-backface-visibility: hidden; cursor: pointer; }
.bmt-inner { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
.bmt-clip { position: absolute; inset: 0; background: #fff; }
.bmt-clip iframe { position: absolute; left: 0; top: 0; border: 0; pointer-events: none; background: #fff; }
.bmt-shade { position: absolute; inset: 0; background: #05070a; opacity: var(--shade, 0); pointer-events: none; }
/* Print guides, as on the vendor's template: the red zone outside the trim
   line is cut off; keep text and key art inside the dashed safe line. */
.bmt-guides { position: absolute; inset: 0; overflow: hidden; pointer-events: none; display: none; }
.bmt-face.guides .bmt-guides { display: block; }
.bmt-face.guides .bmt-clip { clip-path: none !important; }
.bmt-trim { position: absolute; border: 1.5px solid #d6302b; box-shadow: 0 0 0 999px rgba(226, 84, 74, 0.6); }
.bmt-safe { position: absolute; border: 1.5px dashed #b0268f; }
.bmt-side { backface-visibility: visible; pointer-events: none; }
`;

export function createViewer({ stage, toolbar, hint, hud = [] }) {
  const style = document.createElement('style');
  style.textContent = STYLE;
  document.head.appendChild(style);

  const renderer = new CSS3DRenderer();
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 1, 100000);
  const deckRoot = new THREE.Group();
  scene.add(deckRoot);

  let dims = null; // card measurements in px
  let dimsKey = '';
  let cards = [];
  let sides = [];
  let grid = { cols: 1, rows: 1, w: 1, h: 1, d: 1, gap: 0 };
  const view = {
    mode: 'stack', focus: -1, spin: true, flipped: false, guides: false,
    zoom: 1, panX: 0, panY: 0, deckAngle: 0.55, dist: 3000, sideFade: 1, started: false,
  };

  // ---------- toolbar ----------
  const buttons = {};
  function addButton(key, label, title, onClick) {
    const b = document.createElement('button');
    b.className = 'btn'; b.type = 'button'; b.textContent = label; b.title = title;
    b.addEventListener('click', onClick);
    toolbar.appendChild(b);
    buttons[key] = b;
  }
  addButton('mode', 'Spread out', 'Switch between the stacked deck and all cards laid out', () => setMode(view.mode === 'stack' ? 'spread' : 'stack'));
  addButton('spin', 'Spin', 'Turn the cards slowly to show both sides', () => { view.spin = !view.spin; syncUI(); });
  addButton('flip', 'Show backs', 'Stop spinning and show one side of every card', () => { view.flipped = !view.flipped; view.spin = false; syncUI(); });
  addButton('guides', 'Print guides', 'Red zone: cut off when trimmed. Dashed line: keep text and key art inside it.', () => { view.guides = !view.guides; syncUI(); });

  function syncUI() {
    buttons.mode.textContent = view.mode === 'stack' ? 'Spread out' : 'Stack';
    buttons.spin.setAttribute('aria-pressed', String(view.spin));
    buttons.flip.textContent = view.flipped ? 'Show fronts' : 'Show backs';
    buttons.guides.setAttribute('aria-pressed', String(view.guides));
    for (const c of cards) {
      for (const f of c.faces) f.el.classList.toggle('guides', view.guides);
      setRes(c, view.mode === 'focus' && view.focus === c.index ? FOCUS_RES : 1);
    }
    const n = cards.length;
    hint.textContent =
      view.mode === 'stack' ? `Click the deck to spread out all ${n} cards · drag to turn it`
      : view.mode === 'spread' ? 'Click a card to inspect it · drag to pan · scroll to zoom'
      : `Card ${view.focus + 1} of ${n} · drag to turn · ← → for other cards · click to close`;
  }

  function setMode(mode, focus = -1) {
    view.mode = mode;
    view.focus = focus;
    if (mode === 'stack') { view.panX = 0; view.panY = 0; view.zoom = 1; view.flipped = false; }
    syncUI();
  }

  // ---------- cards ----------
  function measure(m) {
    const r = (inches) => Math.round(inches * PX * 100) / 100;
    const d = {
      W: r(m.trim_w_in), H: r(m.trim_h_in), B: r(m.bleed_in), S: r(m.safe_in),
      R: r(m.corner_radius_in), T: m.thickness_in * PX,
    };
    d.PW = d.W + 2 * d.B; d.PH = d.H + 2 * d.B;
    d.pitch = Math.max(d.T, 1.4); // spacing of cards in the stack
    return d;
  }

  function makeFace(index, side) {
    const { B, S, R, PW, PH } = dims;
    const el = document.createElement('div');
    el.className = 'bmt-face';
    el.dataset.index = index;
    const inner = document.createElement('div');
    inner.className = 'bmt-inner';
    inner.style.width = PW + 'px'; inner.style.height = PH + 'px';
    // Show only what survives trimming: crop the bleed and round the corners.
    const clip = document.createElement('div');
    clip.className = 'bmt-clip';
    clip.style.clipPath = `inset(${B}px round ${R}px)`;
    const frame = document.createElement('iframe');
    frame.style.width = PW + 'px'; frame.style.height = PH + 'px';
    frame.setAttribute('scrolling', 'no'); frame.tabIndex = -1;
    frame.title = `card ${index + 1} ${side}`;
    const shade = document.createElement('div');
    shade.className = 'bmt-shade';
    clip.append(frame, shade);
    const guides = document.createElement('div');
    guides.className = 'bmt-guides';
    const trim = document.createElement('div');
    trim.className = 'bmt-trim';
    trim.style.inset = B + 'px'; trim.style.borderRadius = R + 'px';
    const safe = document.createElement('div');
    safe.className = 'bmt-safe';
    safe.style.inset = (B + S) + 'px'; safe.style.borderRadius = Math.max(R - S, 2) + 'px';
    guides.append(trim, safe);
    inner.append(clip, guides);
    el.append(inner);
    const obj = new CSS3DObject(el);
    return { el, inner, frame, obj, v: null };
  }

  function setRes(card, k) {
    if (card.res === k) return;
    card.res = k;
    for (const f of card.faces) {
      f.el.style.width = dims.PW * k + 'px';
      f.el.style.height = dims.PH * k + 'px';
      f.inner.style.transform = k === 1 ? '' : `scale(${k})`;
      f.obj.scale.setScalar(1 / k);
    }
  }

  function makeCard(index) {
    const holder = new THREE.Group();
    const spinner = new THREE.Group();
    holder.add(spinner);
    const front = makeFace(index, 'front');
    const back = makeFace(index, 'back');
    front.obj.position.z = 0.3;
    back.obj.position.z = -0.3;
    back.obj.rotation.y = Math.PI;
    spinner.add(front.obj, back.obj);
    deckRoot.add(holder);
    const card = { index, holder, spinner, front, back, faces: [front, back], angle: 0, phase: 0, dim: 0, shade: -1, res: 0 };
    setRes(card, 1);
    return card;
  }

  // The stack's paper edges: four striped panels around the pile of cards.
  function makeSides(n) {
    for (const s of sides) deckRoot.remove(s.obj);
    const { W, H, R, pitch } = dims;
    const depth = n * pitch;
    const stripes = (deg) => `repeating-linear-gradient(${deg}deg, #f3efe6 0 ${pitch * 0.7}px, #cfc8ba ${pitch * 0.7}px ${pitch}px)`;
    const make = (w, h, bg, place) => {
      const el = document.createElement('div');
      el.className = 'bmt-side';
      el.style.width = w + 'px'; el.style.height = h + 'px'; el.style.background = bg;
      const obj = new CSS3DObject(el);
      place(obj);
      deckRoot.add(obj);
      return { el, obj };
    };
    sides = [
      make(depth, H - 2 * R, stripes(90), (o) => { o.rotation.y = Math.PI / 2; o.position.x = W / 2; }),
      make(depth, H - 2 * R, stripes(90), (o) => { o.rotation.y = -Math.PI / 2; o.position.x = -W / 2; }),
      make(W - 2 * R, depth, stripes(0), (o) => { o.rotation.x = -Math.PI / 2; o.position.y = H / 2; }),
      make(W - 2 * R, depth, stripes(0), (o) => { o.rotation.x = Math.PI / 2; o.position.y = -H / 2; }),
    ];
  }

  function update(state) {
    const m = state.model;
    const key = [m.trim_w_in, m.trim_h_in, m.bleed_in, m.safe_in, m.corner_radius_in, m.thickness_in].join(',');
    if (key !== dimsKey || cards.length !== m.cards.length) {
      for (const c of cards) deckRoot.remove(c.holder);
      dims = measure(m); dimsKey = key;
      cards = m.cards.map((_, i) => makeCard(i));
      makeSides(cards.length);
      if (view.focus >= cards.length) setMode('spread');
    }
    m.cards.forEach((ids, i) => {
      for (const side of ['front', 'back']) {
        const face = cards[i][side], s = state.surfaces[ids[side]];
        if (s && face.v !== s.v) { face.v = s.v; face.frame.src = s.url; }
      }
    });
    syncUI();
    measureInsets();
    layoutGrid();
    if (!view.started) { view.started = true; view.dist = distances().stack * 1.4; }
  }

  function describe(state) {
    const m = state.model;
    return m ? `${m.cards.length} cards · ${m.trim_w_in}″ × ${m.trim_h_in}″` : '';
  }

  // ---------- layout ----------
  // Space taken by the page's controls at the top and bottom, in px, so the
  // cards are fitted into (and centred on) what is left.
  const insets = { top: 0, bottom: 0 };
  function measureInsets() {
    const H = stage.clientHeight || 1;
    let top = 0, bottom = 0;
    for (const el of hud) {
      const r = el.getBoundingClientRect();
      if (!r.height) continue;
      if ((r.top + r.bottom) / 2 < H / 2) top = Math.max(top, r.bottom); else bottom = Math.max(bottom, H - r.top);
    }
    insets.top = Math.min(top, H * 0.3); insets.bottom = Math.min(bottom, H * 0.3);
  }
  const TAN = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
  const fit = (w, h) => {
    const usable = 1 - (insets.top + insets.bottom) / (stage.clientHeight || 1);
    return Math.max(h / 2 / TAN / usable, w / 2 / TAN / camera.aspect);
  };
  // World units per screen px at a given distance from the camera.
  const perPx = (dist) => (2 * dist * TAN) / (stage.clientHeight || 1);
  // How far to lower the camera so the content sits in the middle of the usable area.
  const shiftY = (dist) => ((insets.bottom - insets.top) / 2) * perPx(dist);

  function layoutGrid() {
    if (!dims) return;
    const n = cards.length, gap = 0.45 * PX;
    let best = null;
    for (let cols = 1; cols <= n; cols++) {
      const rows = Math.ceil(n / cols);
      const w = cols * dims.W + (cols - 1) * gap, h = rows * dims.H + (rows - 1) * gap;
      const d = fit(w * 1.06, h * 1.08);
      if (!best || d < best.d) best = { cols, rows, w, h, d, gap };
    }
    grid = best;
  }

  function distances() {
    return { stack: fit(dims.W * 2.1, dims.H * 1.55), spread: grid.d, focus: fit(dims.W * 1.25, dims.H * 1.12) };
  }

  // ---------- interaction ----------
  const pointer = { down: false, dragging: false, x: 0, y: 0, sx: 0, sy: 0, index: -1 };

  stage.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const face = e.target.closest && e.target.closest('.bmt-face');
    pointer.down = true; pointer.dragging = false;
    pointer.index = face ? Number(face.dataset.index) : -1;
    pointer.x = pointer.sx = e.clientX; pointer.y = pointer.sy = e.clientY;
  });
  window.addEventListener('pointermove', (e) => {
    if (!pointer.down) return;
    const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
    pointer.x = e.clientX; pointer.y = e.clientY;
    if (!pointer.dragging && Math.hypot(e.clientX - pointer.sx, e.clientY - pointer.sy) > 5) pointer.dragging = true;
    if (!pointer.dragging || !cards.length) return;
    stage.style.cursor = 'grabbing';
    if (view.mode === 'stack') view.deckAngle += dx * 0.01;
    else if (view.mode === 'focus') cards[view.focus].angle += dx * 0.012;
    else {
      view.panX -= dx * perPx(view.dist); view.panY += dy * perPx(view.dist);
    }
  });
  window.addEventListener('pointerup', () => {
    if (!pointer.down) return;
    const wasDrag = pointer.dragging;
    pointer.down = false; pointer.dragging = false;
    stage.style.cursor = '';
    if (wasDrag || !cards.length) return;
    if (view.mode === 'stack') setMode('spread');
    else if (view.mode === 'focus') setMode('spread');
    else if (pointer.index >= 0) setMode('focus', pointer.index);
  });
  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (view.mode !== 'spread') return;
    view.zoom = THREE.MathUtils.clamp(view.zoom * Math.exp(-e.deltaY * 0.0015), 0.5, 8);
  }, { passive: false });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') setMode(view.mode === 'focus' ? 'spread' : 'stack');
    else if (view.mode === 'focus' && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      const n = cards.length;
      setMode('focus', (view.focus + (e.key === 'ArrowRight' ? 1 : n - 1)) % n);
    }
  });

  // ---------- render loop ----------
  function resize() {
    const w = stage.clientWidth || 1, h = stage.clientHeight || 1;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    measureInsets();
    layoutGrid();
  }
  new ResizeObserver(resize).observe(stage);
  resize();

  const target = new THREE.Vector3();
  let last = performance.now();
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.3);
    last = now;
    if (!cards.length) return;

    const d = distances();
    const stacked = view.mode === 'stack';
    view.dist = damp(view.dist, stacked ? d.stack : d.spread / view.zoom, 5, dt);
    camera.position.set(
      damp(camera.position.x, view.panX, 10, dt),
      damp(camera.position.y, view.panY - shiftY(view.dist), 10, dt),
      view.dist,
    );
    camera.lookAt(camera.position.x, camera.position.y, 0);

    // The stacked deck turns as a whole; spread out, each card turns on its own.
    if (stacked) {
      if (view.spin && !pointer.dragging) view.deckAngle += dt * 0.45;
    } else {
      view.deckAngle = damp(view.deckAngle, nearestTurn(view.deckAngle), 6, dt);
    }
    deckRoot.rotation.x = damp(deckRoot.rotation.x, stacked ? -0.42 : 0, 6, dt);
    deckRoot.rotation.y = view.deckAngle;

    view.sideFade = damp(view.sideFade, stacked && !view.guides ? 1 : 0, stacked ? 5 : 20, dt);
    for (const s of sides) {
      s.obj.visible = view.sideFade > 0.02;
      s.el.style.opacity = view.sideFade.toFixed(2);
    }

    const n = cards.length;
    const focusZ = Math.max(view.dist - d.focus, dims.W + PX);
    const stepX = dims.W + grid.gap, stepY = dims.H + grid.gap;
    const faceOffset = view.flipped ? Math.PI : 0;

    for (const c of cards) {
      const i = c.index;
      const col = i % grid.cols, row = Math.floor(i / grid.cols);
      const focused = view.mode === 'focus' && view.focus === i;
      if (stacked) target.set(0, 0, ((n - 1) / 2 - i) * dims.pitch);
      else if (focused) target.set(camera.position.x, camera.position.y + shiftY(view.dist - focusZ), focusZ);
      else target.set((col - (grid.cols - 1) / 2) * stepX, ((grid.rows - 1) / 2 - row) * stepY, 0);
      const rate = stacked ? 7 : 9 - 4 * (i / n);
      c.holder.position.set(
        damp(c.holder.position.x, target.x, rate, dt),
        damp(c.holder.position.y, target.y, rate, dt),
        damp(c.holder.position.z, target.z, rate, dt),
      );

      const dragged = focused && pointer.dragging;
      if (stacked) c.angle = damp(c.angle, nearestTurn(c.angle), 8, dt);
      else if (dragged) { /* the pointer is turning it */ }
      else if (view.spin) c.angle += dt * 0.75;
      else c.angle = damp(c.angle, nearestTurn(c.angle, faceOffset), 7, dt);
      // A gentle wave across the columns so fronts and backs are both always in view.
      c.phase = damp(c.phase, !stacked && view.spin && !focused ? col * 0.5 : 0, 4, dt);
      c.spinner.rotation.y = c.angle + c.phase;

      // Cheap shading: faces darken a little as they turn away, and the rest
      // of the deck dims while one card is being inspected.
      c.dim = damp(c.dim, view.mode === 'focus' && !focused ? 0.72 : 0, 8, dt);
      const facing = Math.abs(Math.cos(c.spinner.rotation.y + deckRoot.rotation.y));
      const shade = Math.round((1 - (1 - 0.26 * (1 - facing)) * (1 - c.dim)) * 50) / 50;
      if (shade !== c.shade) {
        c.shade = shade;
        for (const f of c.faces) f.el.style.setProperty('--shade', shade);
      }
    }
    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
  syncUI();

  return { update, describe };
}
