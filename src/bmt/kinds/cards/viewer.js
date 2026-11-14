// 3D preview for card decks: a stack that fans out into a grid of slowly
// spinning cards, with click-to-inspect. View-only by design.
import * as THREE from 'three';

const FOV = 32;
const TAU = Math.PI * 2;
const damp = (cur, target, rate, dt) => target + (cur - target) * Math.exp(-rate * dt);
const nearestTurn = (angle, offset = 0) => Math.round((angle - offset) / TAU) * TAU + offset;

function roundedRect(w, h, r) {
  const s = new THREE.Shape();
  const x = w / 2, y = h / 2;
  s.moveTo(-x + r, -y);
  s.lineTo(x - r, -y); s.absarc(x - r, -y + r, r, -Math.PI / 2, 0, false);
  s.lineTo(x, y - r); s.absarc(x - r, y - r, r, 0, Math.PI / 2, false);
  s.lineTo(-x + r, y); s.absarc(-x + r, y - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(-x, -y + r); s.absarc(-x + r, -y + r, r, Math.PI, Math.PI * 1.5, false);
  return s;
}

export function createViewer({ stage, toolbar, hint }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);
  const canvas = renderer.domElement;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.5, 4000);
  const deckRoot = new THREE.Group();
  scene.add(deckRoot);

  const dim = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ color: 0x07090c, transparent: true, opacity: 0, depthWrite: false }),
  );
  dim.scale.set(5000, 5000, 1);
  scene.add(dim);

  const loader = new THREE.TextureLoader();
  const textures = new Map(); // url -> THREE.Texture
  const maxAniso = renderer.capabilities.getMaxAnisotropy();

  let model = null;
  let geo = null; // shared geometries for the current card size
  let geoKey = '';
  let cards = [];
  let grid = { cols: 1, rows: 1, w: 1, h: 1 };
  const view = {
    mode: 'stack', focus: -1, spin: true, flipped: false, guides: false,
    zoom: 1, panX: 0, panY: 0, deckAngle: 0.55, dist: 30, started: false,
  };

  // ---------- toolbar ----------
  const buttons = {};
  function addButton(key, label, onClick) {
    const b = document.createElement('button');
    b.className = 'btn'; b.type = 'button'; b.textContent = label;
    b.addEventListener('click', onClick);
    toolbar.appendChild(b);
    buttons[key] = b;
  }
  addButton('mode', 'Spread out', () => setMode(view.mode === 'stack' ? 'spread' : 'stack'));
  addButton('spin', 'Spin', () => { view.spin = !view.spin; syncUI(); });
  addButton('flip', 'Show backs', () => { view.flipped = !view.flipped; view.spin = false; syncUI(); });
  addButton('guides', 'Safe area', () => { view.guides = !view.guides; syncUI(); });

  function syncUI() {
    buttons.mode.textContent = view.mode === 'stack' ? 'Spread out' : 'Stack';
    buttons.spin.setAttribute('aria-pressed', String(view.spin));
    buttons.flip.textContent = view.flipped ? 'Show fronts' : 'Show backs';
    buttons.guides.setAttribute('aria-pressed', String(view.guides));
    for (const c of cards) c.guides.visible = view.guides;
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

  // ---------- geometry ----------
  function buildGeometry(m) {
    const { trim_w_in: W, trim_h_in: H, bleed_in: B, safe_in: S, corner_radius_in: R, thickness_in: T } = m;
    const shape = roundedRect(W, H, R);
    const face = new THREE.ShapeGeometry(shape, 12);
    // Map the texture (which includes bleed) so only the trimmed area shows.
    const pos = face.attributes.position, uv = face.attributes.uv;
    for (let i = 0; i < pos.count; i++) {
      uv.setXY(i, (pos.getX(i) + W / 2 + B) / (W + 2 * B), (pos.getY(i) + H / 2 + B) / (H + 2 * B));
    }
    const edge = new THREE.ExtrudeGeometry(shape, { depth: T, bevelEnabled: false, curveSegments: 12 });
    edge.translate(0, 0, -T / 2);
    // The band between the trim line and the safe area, where content may get cut.
    const band = roundedRect(W, H, R);
    band.holes.push(new THREE.Path(roundedRect(W - 2 * S, H - 2 * S, Math.max(R - S, 0.02)).getPoints(8)));
    const safe = new THREE.ShapeGeometry(band, 12);
    return { face, edge, safe, W, H, T };
  }

  const edgeMaterials = [
    new THREE.MeshBasicMaterial({ visible: false }),
    new THREE.MeshBasicMaterial({ color: 0xece8df }),
  ];
  const guideMaterial = new THREE.MeshBasicMaterial({ color: 0xff2bd6, transparent: true, opacity: 0.45, depthWrite: false });

  function makeCard(index) {
    const holder = new THREE.Group();
    const spinner = new THREE.Group();
    holder.add(spinner);
    const mats = { front: new THREE.MeshBasicMaterial({ color: 0xffffff }), back: new THREE.MeshBasicMaterial({ color: 0xffffff }) };
    const z = geo.T / 2 + 0.0006;
    const front = new THREE.Mesh(geo.face, mats.front);
    front.position.z = z;
    const back = new THREE.Mesh(geo.face, mats.back);
    back.rotation.y = Math.PI; back.position.z = -z;
    front.userData.index = back.userData.index = index;
    const edge = new THREE.Mesh(geo.edge, edgeMaterials);
    const guides = new THREE.Group();
    const g1 = new THREE.Mesh(geo.safe, guideMaterial); g1.position.z = z + 0.003;
    const g2 = new THREE.Mesh(geo.safe, guideMaterial); g2.rotation.y = Math.PI; g2.position.z = -z - 0.003;
    guides.add(g1, g2);
    guides.visible = view.guides;
    spinner.add(front, back, edge, guides);
    deckRoot.add(holder);
    return { index, holder, spinner, mats, faces: [front, back], guides, angle: 0, phase: 0, urls: {} };
  }

  function setTexture(card, side, url) {
    if (card.urls[side] === url) return;
    card.urls[side] = url;
    let tex = textures.get(url);
    const apply = (t) => {
      if (card.urls[side] !== url) return;
      card.mats[side].map = t;
      card.mats[side].needsUpdate = true;
    };
    if (tex) { if (tex.image) apply(tex); else tex.userData.waiting.push(apply); return; }
    tex = loader.load(url, (t) => { t.userData.waiting.forEach((fn) => fn(t)); t.userData.waiting = []; });
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = maxAniso;
    tex.userData.waiting = [apply];
    textures.set(url, tex);
  }

  function update(state) {
    const m = state.model;
    const key = [m.trim_w_in, m.trim_h_in, m.bleed_in, m.safe_in, m.corner_radius_in, m.thickness_in].join(',');
    if (key !== geoKey || cards.length !== m.cards.length) {
      for (const c of cards) deckRoot.remove(c.holder);
      if (key !== geoKey) { geo = buildGeometry(m); geoKey = key; }
      model = m;
      cards = m.cards.map((_, i) => makeCard(i));
      if (view.focus >= cards.length) setMode('spread');
    }
    model = m;
    m.cards.forEach((ids, i) => {
      setTexture(cards[i], 'front', state.surfaces[ids.front]);
      setTexture(cards[i], 'back', state.surfaces[ids.back]);
    });
    // Free textures that no card uses any more.
    const live = new Set(Object.values(state.surfaces));
    for (const [url, tex] of textures) if (!live.has(url)) { tex.dispose(); textures.delete(url); }
    layoutGrid();
    syncUI();
    if (!view.started) { view.started = true; view.dist = distances().stack * 1.4; }
  }

  function describe(state) {
    const m = state.model;
    return m ? `${m.cards.length} cards · ${m.trim_w_in}″ × ${m.trim_h_in}″` : '';
  }

  // ---------- layout ----------
  const fit = (w, h) => {
    const t = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    return Math.max(h / 2 / t, w / 2 / t / camera.aspect);
  };

  function layoutGrid() {
    if (!geo) return;
    const n = cards.length, gap = 0.45;
    let best = null;
    for (let cols = 1; cols <= n; cols++) {
      const rows = Math.ceil(n / cols);
      const w = cols * geo.W + (cols - 1) * gap, h = rows * geo.H + (rows - 1) * gap;
      const d = fit(w * 1.06, h * 1.22);
      if (!best || d < best.d) best = { cols, rows, w, h, d, gap };
    }
    grid = best;
  }

  function distances() {
    return { stack: fit(geo.W * 2.1, geo.H * 1.7), spread: grid.d, focus: fit(geo.W * 1.5, geo.H * 1.3) };
  }

  // ---------- interaction ----------
  const pointer = { down: false, dragging: false, x: 0, y: 0, sx: 0, sy: 0 };
  const raycaster = new THREE.Raycaster();

  canvas.addEventListener('pointerdown', (e) => {
    pointer.down = true; pointer.dragging = false;
    pointer.x = pointer.sx = e.clientX; pointer.y = pointer.sy = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!pointer.down) return;
    const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
    pointer.x = e.clientX; pointer.y = e.clientY;
    if (!pointer.dragging && Math.hypot(e.clientX - pointer.sx, e.clientY - pointer.sy) > 5) pointer.dragging = true;
    if (!pointer.dragging) return;
    canvas.style.cursor = 'grabbing';
    if (view.mode === 'stack') view.deckAngle += dx * 0.01;
    else if (view.mode === 'focus') cards[view.focus].angle += dx * 0.012;
    else {
      const perPx = (2 * view.dist * Math.tan(THREE.MathUtils.degToRad(FOV / 2))) / canvas.clientHeight;
      view.panX -= dx * perPx; view.panY += dy * perPx;
    }
  });
  canvas.addEventListener('pointerup', (e) => {
    const wasDrag = pointer.dragging;
    pointer.down = false; pointer.dragging = false;
    canvas.style.cursor = 'grab';
    if (wasDrag || !cards.length) return;
    if (view.mode === 'stack') return setMode('spread');
    if (view.mode === 'focus') return setMode('spread');
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(cards.flatMap((c) => c.faces), false)[0];
    if (hit) setMode('focus', hit.object.userData.index);
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (view.mode !== 'spread') return;
    view.zoom = THREE.MathUtils.clamp(view.zoom * Math.exp(-e.deltaY * 0.0015), 0.5, 8);
  }, { passive: false });
  window.addEventListener('keydown', (e) => {
    if (e.target.closest && e.target.closest('button, input, textarea')) { if (e.key !== 'Escape') return; }
    if (e.key === 'Escape') setMode(view.mode === 'focus' ? 'spread' : 'stack');
    else if (view.mode === 'focus' && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      const n = cards.length;
      setMode('focus', (view.focus + (e.key === 'ArrowRight' ? 1 : n - 1)) % n);
    }
  });

  // ---------- render loop ----------
  function resize() {
    const w = stage.clientWidth || 1, h = stage.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
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
    if (!cards.length) { renderer.render(scene, camera); return; }

    const d = distances();
    const wantDist = view.mode === 'stack' ? d.stack : d.spread / view.zoom;
    view.dist = damp(view.dist, wantDist, 5, dt);
    camera.position.set(
      damp(camera.position.x, view.panX, 10, dt),
      damp(camera.position.y, view.panY, 10, dt),
      view.dist,
    );
    camera.lookAt(camera.position.x, camera.position.y, 0);

    // The stacked deck turns as a whole; spread out, each card turns on its own.
    const stacked = view.mode === 'stack';
    if (stacked) {
      if (view.spin && !pointer.dragging) view.deckAngle += dt * 0.45;
    } else {
      view.deckAngle = damp(view.deckAngle, nearestTurn(view.deckAngle), 6, dt);
    }
    deckRoot.rotation.x = damp(deckRoot.rotation.x, stacked ? -0.42 : 0, 6, dt);
    deckRoot.rotation.y = view.deckAngle;

    const n = cards.length;
    const pitch = geo.T + 0.004;
    const focusZ = Math.max(view.dist - d.focus, geo.W + 1);
    const stepX = geo.W + grid.gap, stepY = geo.H + grid.gap;
    const faceOffset = view.flipped ? Math.PI : 0;

    for (const c of cards) {
      const i = c.index;
      const col = i % grid.cols, row = Math.floor(i / grid.cols);
      const focused = view.mode === 'focus' && view.focus === i;
      if (stacked) target.set(0, 0, ((n - 1) / 2 - i) * pitch);
      else if (focused) target.set(camera.position.x, camera.position.y, focusZ);
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

      // Cheap shading: faces darken a little as they turn away.
      const world = c.spinner.rotation.y + deckRoot.rotation.y;
      const shade = 0.74 + 0.26 * Math.abs(Math.cos(world));
      c.mats.front.color.setScalar(shade);
      c.mats.back.color.setScalar(shade);
    }

    dim.position.set(camera.position.x, camera.position.y, focusZ - geo.W / 2 - 0.2);
    dim.material.opacity = damp(dim.material.opacity, view.mode === 'focus' ? 0.72 : 0, 8, dt);
    dim.visible = dim.material.opacity > 0.01;

    renderer.render(scene, camera);
  }
  requestAnimationFrame(frame);
  syncUI();

  return { update, describe };
}
