/* xV pitch drawing: pitch, zones, heatmaps, players, pass maps. Canvas, print look.
   Pitch coordinates: x 0-100 along the pitch, y 0-100 across (105 x 68 m).
   Horizontal views: x left to right. Vertical views (team zones): x bottom to top, so the
   team attacks upward and its left is on the left. */
'use strict';
const PITCH = {
  ink: '#151412', paper: '#F8F5EE', grass: '#EFEADF', line: 'rgba(21,20,18,.55)',
  home: '#1F4E9C', away: '#C0392B', homeGK: '#7aa0d8', awayGK: '#e6a39b',
  homeRGB: '31,78,156', awayRGB: '192,57,43', gold: '#C8930E', goldRGB: '200,147,14', cyan: '#0E9FB3', cyanRGB: '14,159,179',
  lane5: [0, 100 * 13.85 / 68, 100 * 24.84 / 68, 100 * 43.16 / 68, 100 * 54.15 / 68, 100],
  lane5Names: ['Left wing', 'Left half-space', 'Centre', 'Right half-space', 'Right wing'],
  gx: 12, gy: 8,
};
const FONT = (w, px, fam = 'IBM Plex Sans Condensed') => `${w} ${px}px '${fam}'`;

/* returns null while the canvas is hidden (drawing then would be blurry); callers redraw on show */
function pitchCanvas(canvas, vertical = false) {
  if (!canvas || !canvas.clientWidth) return null;
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth;
  const h = Math.round(vertical ? w * 105 / 68 : w * 68 / 105) + 2 * Math.round(w / 60);
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); canvas.style.height = h + 'px';
  }
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const m = Math.round(w / 60), W = w - 2 * m, H = h - 2 * m;
  const pt = vertical ? (x, y) => [m + y / 100 * W, m + (1 - x / 100) * H] : (x, y) => [m + x / 100 * W, m + y / 100 * H];
  const rect = (x0, y0, x1, y1) => { const [a, b] = pt(x0, y0), [c, d] = pt(x1, y1);
    return [Math.min(a, c), Math.min(b, d), Math.abs(c - a), Math.abs(d - b)]; };
  return { ctx, w, h, W, H, m, pt, rect, vertical, fs: Math.max(11, Math.round(w / 55)), dpr };
}

function drawPitch(P, { arrow = false } = {}) {
  const { ctx, pt, rect } = P, px = v => v / 105 * 100, py = v => v / 68 * 100;
  ctx.fillStyle = PITCH.paper; ctx.fillRect(0, 0, P.w, P.h);
  for (let i = 0; i < 12; i += 2) { ctx.fillStyle = PITCH.grass; ctx.fillRect(...rect(i * 100 / 12, 0, (i + 1) * 100 / 12, 100)); }
  ctx.strokeStyle = PITCH.line; ctx.lineWidth = 1.2;
  const r = (x0, y0, x1, y1) => ctx.strokeRect(...rect(px(x0), py(y0), px(x1), py(y1)));
  r(0, 0, 105, 68); r(0, 13.85, 16.5, 54.15); r(88.5, 13.85, 105, 54.15); r(0, 24.85, 5.5, 43.15); r(99.5, 24.85, 105, 43.15);
  ctx.beginPath(); ctx.moveTo(...pt(50, 0)); ctx.lineTo(...pt(50, 100)); ctx.stroke();
  const [cx, cy] = pt(50, 50), rad = 9.15 / 105 * (P.vertical ? P.H : P.W);  // the pitch keeps its true aspect
  ctx.beginPath(); ctx.arc(cx, cy, rad, 0, 7); ctx.stroke();
  if (arrow) { ctx.fillStyle = PITCH.ink; ctx.font = FONT(600, P.fs - 1); ctx.textAlign = 'center';
    const [ax, ay] = P.vertical ? [P.w / 2, P.m - 2 + P.fs] : [P.w / 2, P.m + P.fs]; ctx.fillText(P.vertical ? 'attacking ↑' : 'attacking →', ax, ay); ctx.textAlign = 'start'; }
}

function label(P, text, x, y, { colour = PITCH.ink, size = 0, weight = 700, align = 'center', bg = true } = {}) {
  const { ctx } = P, [sx, sy] = P.pt(x, y);
  ctx.font = FONT(weight, size || P.fs); ctx.textAlign = align; ctx.textBaseline = 'middle';
  if (bg) { const w = ctx.measureText(text).width + 8; ctx.fillStyle = 'rgba(248,245,238,.85)';
    ctx.fillRect(align === 'center' ? sx - w / 2 : sx - 4, sy - (size || P.fs) * .7, w, (size || P.fs) * 1.4); }
  ctx.fillStyle = colour; ctx.fillText(text, sx, sy); ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
}

/* lanes per team: shares (3) shade each lane inside that team's attacking third; labels from its own view */
function drawTeamLanes(P, side, shares, five = false) {
  const { ctx } = P, rgb = side === 0 ? PITCH.homeRGB : PITCH.awayRGB;
  const edges = five ? PITCH.lane5 : [0, 100 / 3, 200 / 3, 100], names = five ? PITCH.lane5Names : ['Left', 'Centre', 'Right'];
  const max = Math.max(...shares, 1), xa = side === 0 ? [50, 100] : [0, 50];
  for (let i = 0; i < names.length; i++) {
    const [y0, y1] = side === 0 ? [edges[i], edges[i + 1]] : [100 - edges[i + 1], 100 - edges[i]];
    ctx.fillStyle = `rgba(${rgb},${.06 + .42 * shares[i] / max})`; ctx.fillRect(...P.rect(xa[0], y0, xa[1], y1));
    ctx.strokeStyle = `rgba(${rgb},.7)`; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.2; ctx.strokeRect(...P.rect(xa[0], y0, xa[1], y1)); ctx.setLineDash([]);
    label(P, names[i].toUpperCase(), side === 0 ? 92 : 8, (y0 + y1) / 2, { colour: `rgb(${rgb})`, size: P.fs - (five ? 2 : 0) });
  }
}
function drawThirds(P) {
  const { ctx } = P; ctx.save(); ctx.strokeStyle = 'rgba(21,20,18,.45)'; ctx.setLineDash([6, 5]); ctx.lineWidth = 1.3;
  [100 / 3, 200 / 3].forEach(v => { ctx.beginPath(); ctx.moveTo(...P.pt(v, 0)); ctx.lineTo(...P.pt(v, 100)); ctx.stroke(); });
  ctx.restore();
  ['DEFENSIVE', 'MIDDLE', 'ATTACKING'].forEach((t, i) => label(P, t + ' THIRD', i * 100 / 3 + 100 / 6, 97, { size: P.fs - 2, weight: 600, colour: '#3d3a34' }));
}

/* grid: 96 values (12 x 8, row-major, in the frame of the given points). mode 'seq' or 'div' (blue/red) */
function drawGrid(P, vals, { mode = 'seq', labels = false, alpha = .78, rgb = PITCH.homeRGB, gold = false } = {}) {
  const { ctx } = P, gx = PITCH.gx, gy = PITCH.gy, max = Math.max(...vals.map(Math.abs)) || 1;
  for (let j = 0; j < gy; j++) for (let i = 0; i < gx; i++) {
    const v = vals[j * gx + i]; if (!v) continue;
    const [x, y, w, h] = P.rect(i * 100 / gx, j * 100 / gy, (i + 1) * 100 / gx, (j + 1) * 100 / gy);
    const a = alpha * Math.abs(v) / max;
    ctx.fillStyle = mode === 'div' ? `rgba(${v > 0 ? PITCH.homeRGB : PITCH.awayRGB},${a})` : `rgba(${gold && v === max ? PITCH.goldRGB : rgb},${a})`;
    ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
    if (labels && Math.abs(v) >= max * .2) { ctx.fillStyle = a > .5 ? '#fff' : PITCH.ink; ctx.font = FONT(600, P.fs - 2, 'IBM Plex Mono');
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(Math.round(Math.abs(v)) + (labels === '%' ? '%' : ''), x + w / 2, y + h / 2); }
  }
  ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
}

/* smooth heatmap: soft splats rendered at device resolution, then a colour ramp */
function drawHeat(P, points, { radius = 0, rgbRamp = 'warm' } = {}) {
  if (!points.length) return;
  const dpr = P.dpr, off = document.createElement('canvas'); off.width = Math.round(P.w * dpr); off.height = Math.round(P.h * dpr);
  const o = off.getContext('2d'), r = (radius || P.w / 26) * dpr, a = Math.min(.22, 40 / points.length + .02);
  for (const [x, y] of points) { const [sx, sy] = P.pt(x, y), X = sx * dpr, Y = sy * dpr;
    const g = o.createRadialGradient(X, Y, 0, X, Y, r); g.addColorStop(0, `rgba(0,0,0,${a})`); g.addColorStop(1, 'rgba(0,0,0,0)');
    o.fillStyle = g; o.fillRect(X - r, Y - r, 2 * r, 2 * r); }
  const img = o.getImageData(0, 0, off.width, off.height), d = img.data; let mx = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > mx) mx = d[i];
  const ramp = rgbRamp === 'blue' ? t => [31 + 60 * (1 - t), 78 + 120 * (1 - t), 156 + 60 * (1 - t)]
    : rgbRamp === 'red' ? t => [192 + 40 * (1 - t), 57 + 140 * (1 - t), 43 + 140 * (1 - t)]
    : t => t < .5 ? [46 + 368 * t, 139 + 82 * t, 62 - 40 * t] : [230 - 76 * (t - .5), 180 - 246 * (t - .5), 42];
  for (let i = 0; i < d.length; i += 4) { const t = d[i + 3] / (mx || 1); if (t < .05) { d[i + 3] = 0; continue; }
    const c = ramp(t); d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = Math.round(210 * Math.min(1, t * 1.35)); }
  o.putImageData(img, 0, 0); const { ctx } = P; ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(off, 0, 0); ctx.restore();
}

function gridPoints(grid, seedText = '') {
  let s = 7; for (const ch of seedText) s = (s * 31 + ch.charCodeAt(0)) % 2147483647;
  const rnd = () => (s = (s * 48271) % 2147483647) / 2147483647, pts = [];
  grid.forEach((v, k) => { const n = Math.round(v * 3), i = k % PITCH.gx, j = Math.floor(k / PITCH.gx);
    for (let r = 0; r < n; r++) pts.push([(i + rnd()) * 100 / PITCH.gx, (j + rnd()) * 100 / PITCH.gy]); });
  return pts;
}

function disc(P, x, y, { fill, text, ring = PITCH.paper, ringW = 1.2, r = 0, textColour = PITCH.paper, name = '' }) {
  const { ctx } = P, [sx, sy] = P.pt(x, y), R = r || Math.max(8, P.w / 68);
  ctx.beginPath(); ctx.arc(sx, sy, R, 0, 7); ctx.fillStyle = fill; ctx.fill(); ctx.lineWidth = ringW; ctx.strokeStyle = ring; ctx.stroke();
  ctx.fillStyle = textColour; ctx.font = FONT(700, Math.round(R * 1.05)); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, sx, sy + .5);
  if (name) { ctx.font = FONT(600, P.fs - 2); ctx.fillStyle = PITCH.ink; ctx.fillText(name, sx, sy - R - P.fs * .6); }
  ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
}
function drawPlayers(P, players, { follow = null, carrier = null, faded = false } = {}) {
  for (const p of players) {
    const home = p.side === 0, gk = p.role === 'GK';
    P.ctx.globalAlpha = faded ? .25 : 1;
    disc(P, p.x, p.y, { fill: gk ? (home ? PITCH.homeGK : PITCH.awayGK) : (home ? PITCH.home : PITCH.away), text: p.shirt,
      textColour: gk ? PITCH.ink : PITCH.paper, ring: p.id === follow ? PITCH.gold : PITCH.paper, ringW: p.id === follow ? 3 : 1.2,
      name: !faded && (p.id === carrier || p.id === follow) ? p.name.split(' ').slice(-1)[0] : '' });
  }
  P.ctx.globalAlpha = 1;
}
function drawBall(P, x, y) {
  const { ctx } = P, [sx, sy] = P.pt(x, y);
  ctx.beginPath(); ctx.arc(sx, sy, Math.max(4, P.w / 160), 0, 7); ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = 1.6; ctx.strokeStyle = PITCH.ink; ctx.stroke();
}
/* pass map: completed passes solid, failed dashed; arrows on completed passes */
function drawPassMap(P, acts, side) {
  const { ctx } = P;
  for (const a of acts) {
    if (side !== 2 && a[2] !== side) continue;
    if (!['pass', 'cross', 'long'].includes(a[3])) continue;
    const [x0, y0] = P.pt(a[4], a[5]), [x1, y1] = P.pt(a[6], a[7]), rgb = a[2] === 0 ? PITCH.homeRGB : PITCH.awayRGB;
    ctx.strokeStyle = a[8] ? `rgba(${rgb},.55)` : `rgba(${rgb},.22)`; ctx.lineWidth = a[3] === 'pass' ? 1.1 : 1.8;
    ctx.setLineDash(a[8] ? [] : [3, 3]); ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
    if (a[8]) { const ang = Math.atan2(y1 - y0, x1 - x0); ctx.beginPath(); ctx.moveTo(x1, y1);
      ctx.lineTo(x1 - 6 * Math.cos(ang - .4), y1 - 6 * Math.sin(ang - .4)); ctx.lineTo(x1 - 6 * Math.cos(ang + .4), y1 - 6 * Math.sin(ang + .4));
      ctx.closePath(); ctx.fillStyle = `rgba(${rgb},.6)`; ctx.fill(); }
  }
  ctx.setLineDash([]);
}

/* FM-style strip: 6 bands along the attack, shares and the difference to the league */
function drawBands(P, pct, compare) {
  const { ctx } = P, max = Math.max(...pct) || 1;
  pct.forEach((v, i) => {
    const [x, y, w, h] = P.rect(i * 100 / 6, 0, (i + 1) * 100 / 6, 100);
    ctx.fillStyle = `rgba(46,139,62,${.12 + .62 * v / max})`; ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
    label(P, v + '%', (i + .5) * 100 / 6, P.vertical ? 50 : 82, { size: P.fs + 2, bg: true });
    if (compare) { const d = Math.round((v - compare[i]) * 10) / 10;
      label(P, `${d > 0 ? '+' : ''}${d} v avg`, (i + .5) * 100 / 6, P.vertical ? 80 : 93, { size: P.fs - 2, weight: 600, colour: d > 0 ? '#2E8B3E' : d < 0 ? '#C0392B' : PITCH.ink }); }
  });
}
/* shares by lane as columns along the pitch (vertical views) */
function drawLaneColumns(P, shares, five = false, rgb = '46,139,62') {
  const edges = five ? PITCH.lane5 : [0, 100 / 3, 200 / 3, 100], max = Math.max(...shares, 1);
  shares.forEach((v, i) => { P.ctx.fillStyle = `rgba(${rgb},${.1 + .6 * v / max})`; const [x, y, w, h] = P.rect(66.7, edges[i], 100, edges[i + 1]);
    P.ctx.fillRect(x + 1, y + 1, w - 2, h - 2); label(P, v + '%', 84, (edges[i] + edges[i + 1]) / 2, { size: P.fs - (five ? 2 : 0) }); });
}
/* assist zones (team frame) with counts; gold on the busiest zone */
function drawAssistZones(P, zones, counts, rgb) {
  const max = Math.max(...counts, 1);
  zones.forEach((z, i) => {
    const [x, y, w, h] = P.rect(z.x0, z.y0, z.x1, z.y1), c = counts[i] || 0;
    if (i === 1) { /* box centre is drawn under the six-yard box */ }
    P.ctx.fillStyle = c === max && c > 0 ? `rgba(${PITCH.goldRGB},.85)` : `rgba(${rgb},${.08 + .62 * c / max})`;
    P.ctx.fillRect(x, y, w, h); P.ctx.strokeStyle = PITCH.ink; P.ctx.lineWidth = 1; P.ctx.strokeRect(x, y, w, h);
  });
  zones.forEach((z, i) => { const c = counts[i] || 0; if (!c) return;
    const cx = i === 1 ? 88 : (z.x0 + z.x1) / 2;  // box centre label sits below the six-yard box
    label(P, String(c), cx, (z.y0 + z.y1) / 2, { size: P.fs + 1, bg: false, colour: c / max > .55 ? '#fff' : PITCH.ink }); });
}

/* zone numbers from live actions/frames (same definitions as analytics/zones.py), side 0 = home */
function lane3(y) { return y < 100 / 3 ? 0 : y < 200 / 3 ? 1 : 2; }
function lane5(y) { const e = PITCH.lane5; for (let i = 1; i < 5; i++) if (y < e[i]) return i - 1; return 4; }
function cellOf(x, y) { return Math.min(PITCH.gy - 1, Math.max(0, Math.floor(y / 100 * PITCH.gy))) * PITCH.gx + Math.min(PITCH.gx - 1, Math.max(0, Math.floor(x / 100 * PITCH.gx))); }
function teamFrame(side, x, y) { return side === 0 ? [x, y] : [100 - x, 100 - y]; }
function liveZones(actions, frames, side) {
  const z = { bands: [0, 0, 0, 0, 0, 0], entries3: [0, 0, 0], entries5: [0, 0, 0, 0, 0], possThirds: [0, 0, 0], territory: new Array(96).fill(0) };
  for (const a of actions) {
    if (a[2] !== side) continue;
    const [x] = teamFrame(side, a[4], a[5]), [ex, ey] = teamFrame(side, a[6], a[7]);
    if (a[3] === 'pass' || a[3] === 'cross' || a[3] === 'long') {
      z.bands[Math.min(5, Math.floor(x / 100 * 6))]++;
      if (a[8] && ex > 200 / 3 && x <= 200 / 3) { z.entries3[lane3(ey)]++; z.entries5[lane5(ey)]++; }
    }
  }
  for (const f of frames) {
    const s = f[4], [bx] = teamFrame(side, f[2] / 10, f[3] / 10);
    if (s === side) z.possThirds[bx < 100 / 3 ? 0 : bx < 200 / 3 ? 1 : 2]++;
    z.territory[cellOf(f[2] / 10, f[3] / 10)] += s === 0 ? 1 : -1;
  }
  const pct = v => { const t = v.reduce((a, b) => a + b, 0); return v.map(x => t ? Math.round(1000 * x / t) / 10 : 0); };
  return { bandsPct: pct(z.bands), entries3Pct: pct(z.entries3), entries5Pct: pct(z.entries5), possThirdsPct: pct(z.possThirds),
    entries: z.entries3.reduce((a, b) => a + b, 0), territory: z.territory };
}
