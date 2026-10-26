/* xV front end. Reads the analysis bundle (data/*.json) and either the live
   server (/api/meta + /stream) or, on static hosting, the recorded replay.json. */
'use strict';
const $ = id => document.getElementById(id);
const C = { ink: '#151412', paper: '#F2EEE5', green: '#2E8B3E', red: '#C0392B', blue: '#1F4E9C',
  muted: '#6b665c', panel: '#EBE6DA', gold: '#9a6b00' };
const LEAGUE_COL = { meridian: '#1F4E9C', calder: '#C0392B', northmarch: '#151412', isles: '#2E8B3E' };
const S = { meta: null, players: [], byId: {}, teams: {}, tables: {}, insights: null, fixtures: [],
  live: null, replay: null, charts: {} };

const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const ord = n => n == null ? '–' : n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'));
const leagueName = id => (S.meta.leagues.find(l => l.id === id) || {}).name || id;
const club = c => S.teams[c] || { name: c, colour: C.ink };
const roleName = r => (S.meta.roles.find(x => x.id === r) || {}).name || r;
const roleOf = r => S.meta.roles.find(x => x.id === r);
const statLabel = k => (S.meta.catalog[k] || S.meta.team_stats[k] || { label: k }).label;
function fmt(v, k) {
  if (v == null) return '–';
  const c = S.meta.catalog[k];
  if (!c) return Number.isInteger(v) ? v : (+v).toFixed(2);
  if (k === 'xg_per_shot') return (+v).toFixed(2);
  if (c.kind === 'pct') return (+v).toFixed(1) + '%';
  if (c.kind === 'total') return Math.round(v);
  if (c.kind === 'max') return (+v).toFixed(1);
  if (c.kind === 'avg') return (+v).toFixed(k === 'rating' ? 2 : 1);
  return (+v).toFixed(2);
}
function pctColor(p) {
  if (p == null) return '#d6cfbf';
  const t = p / 100, a = [192, 57, 43], m = [214, 207, 191], b = [46, 139, 62];
  const mix = (x, y, f) => x.map((v, i) => Math.round(v + (y[i] - v) * f));
  const c = t < .5 ? mix(a, m, t * 2) : mix(m, b, (t - .5) * 2);
  return `rgb(${c})`;
}
function opt(sel, items, val) {
  sel.innerHTML = items.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  if (val != null) sel.value = val;
}
function chart(id, cfg) { if (S.charts[id]) S.charts[id].destroy(); S.charts[id] = new Chart($(id), cfg); return S.charts[id]; }
Chart.defaults.font.family = "'IBM Plex Sans Condensed', 'Arial Narrow', sans-serif";
Chart.defaults.color = C.ink;

/* ---------------- boot ---------------- */
async function boot() {
  const get = p => fetch(p).then(r => r.json());
  const [meta, players, teams, insights, fixtures] = await Promise.all(
    ['data/meta.json', 'data/players.json', 'data/teams.json', 'data/insights.json', 'data/fixtures.json'].map(get));
  Object.assign(S, { meta, players, insights, fixtures, teams: teams.teams, tables: teams.tables, leagueZones: teams.league_zones || {} });
  players.forEach(p => S.byId[p.id] = p);
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => show(b.dataset.view));
  window.addEventListener('hashchange', () => show(location.hash.slice(1) || 'live', true));
  initPlayers(); initCompare(); initScatter(); initRankings(); initTeams(); renderLeagues();
  await initLive();
  requestAnimationFrame(tick);
  show(location.hash.slice(1) || 'live', true);
}
function show(view, fromHash) {
  if (!$('v-' + view)) view = 'live';
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.view === view));
  document.querySelectorAll('section.view').forEach(s => s.classList.toggle('on', s.id === 'v-' + view));
  if (!fromHash) history.replaceState(null, '', '#' + view);
  // canvases can only be drawn sharply while visible: redraw the view that just appeared
  if (view === 'scatter') renderScatter();
  if (view === 'players') renderPlayer();
  if (view === 'teams' && S.curTeam) renderTeam(S.curTeam);
  if (view === 'live') { drawLive(true); refreshZones(); }
}

/* ---------------- LIVE ---------------- */
async function initLive() {
  let live = null;
  if (!location.hostname.endsWith('github.io')) {
    try { const r = await fetch('api/meta'); if (r.ok && (r.headers.get('content-type') || '').includes('json')) live = await r.json(); } catch (e) { }
  }
  if (!live) { S.replay = await fetch('replay.json').then(r => r.json()); live = S.replay.meta; }
  S.live = live;
  const fx = live.fixture, H = club(fx.home), A = club(fx.away);
  opt($('persona'), live.personas, 'fan'); opt($('lang'), live.languages, 'en');
  [fx.home, fx.away].forEach(c => $('team').add(new Option(club(c).name, c)));
  const squad = S.players.filter(p => (p.club === fx.home || p.club === fx.away) && p.minutes > 0)
    .sort((a, b) => (a.club > b.club) - (a.club < b.club) || b.minutes - a.minutes);
  squad.forEach(p => $('followp').add(new Option(`${p.name} (${p.club}, ${p.role})`, p.id)));
  $('l-kicker').textContent = `${leagueName(fx.league)} · round ${fx.round} · ${S.replay ? 'recorded replay of the live pipeline' : 'live pipeline'} · narration: ${live.narration}`;
  $('l-title').innerHTML = `${esc(H.name)} <span style="color:var(--muted)">v</span> ${esc(A.name)}`;
  $('l-sub').textContent = `${ord(H.position)} v ${ord(A.position)} in the table · before kick-off xV's model gives ${pp(fx.model.home)} / ${pp(fx.model.draw)} / ${pp(fx.model.away)}, the market ${pp(fx.market.home)} / ${pp(fx.market.draw)} / ${pp(fx.market.away)}`;
  $('hname').textContent = fx.home; $('aname').textContent = fx.away;
  $('hchip').style.background = H.colour; $('achip').style.background = A.colour;
  $('pb-h').style.background = C.blue; $('pb-a').style.background = C.red;
  setProbs({ home: fx.model.home, draw: fx.model.draw, away: fx.model.away, why: ['pre-match'] });
  renderStats(null); probChart();
  $('go').onclick = kickOff;
  $('followp').onchange = () => { renderFollow(S.lastSnap); refreshZones(); drawLive(true); };
  opt($('z-team'), [['0', H.name], ['1', A.name]]);
  opt($('ov-side'), [['2', 'Both teams'], ['0', H.name], ['1', A.name]], '2');
  ['z-team', 'z-window', 'ov-side'].forEach(i => $(i).onchange = () => { refreshZones(); drawLive(true); });
  $('overlay').onchange = () => drawLive(true);
  document.querySelectorAll('#ltabs button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#ltabs button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.ltab').forEach(x => x.classList.toggle('on', x.id === 'lt-' + b.dataset.tab));
    refreshZones(); if (S.charts.probChart) S.charts.probChart.resize();
  });
  if (S.replay) setTrack(S.replay.track, S.replay.meta.half_time_offset);
  window.addEventListener('resize', () => { drawLive(true); refreshZones(); });
  drawLive(true); refreshZones();
}

/* ---------------- live pitch ---------------- */
const T = { meta: null, frames: [], at: [], acts: [], now: 0, playing: false, t0: 0, speed: 60, lastZones: 0 };
function setTrack(track, offset) {
  T.meta = track.players.map(p => ({ ...p, side: p.club === track.home ? 0 : 1 }));
  T.home = track.home; T.offset = offset || 0;
  if (track.frames) { T.all = track.frames; T.allAt = track.frames.map(f => f[1] + (f[0] === 2 ? T.offset : 0));
    T.frames = T.all; T.at = T.allAt; T.acts = S.replay ? S.replay.actions : []; T.now = 0; }
}
function frameIndex(at) {
  let lo = 0, hi = T.at.length - 1; if (hi < 0) return -1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (T.at[mid] <= at) lo = mid; else hi = mid - 1; }
  return lo;
}
function positionsAt(at) {
  const i = frameIndex(at); if (i < 0) return null;
  const a = T.frames[i], b = T.frames[i + 1] || a, ta = T.at[i], tb = T.at[i + 1] ?? ta;
  const f = tb > ta ? Math.min(1, Math.max(0, (at - ta) / (tb - ta))) : 0, lerp = (u, v) => u < 0 || v < 0 ? u : u + (v - u) * f;
  const players = [];
  T.meta.forEach((p, k) => { const x = lerp(a[5][2 * k], b[5][2 * k]), y = lerp(a[5][2 * k + 1], b[5][2 * k + 1]);
    if (x >= 0) players.push({ ...p, x: x / 10, y: y / 10 }); });
  return { players, bx: lerp(a[2], b[2]) / 10, by: lerp(a[3], b[3]) / 10, side: a[4] };
}
function visibleFrames() {  // frames in the chosen window, up to now
  const w = $('z-window').value, i = frameIndex(T.now); if (i < 0) return [];
  let fr = T.frames.slice(0, i + 1);
  if (w === '1' || w === '2') fr = fr.filter(f => f[0] === +w);
  if (w === '15') { const cut = T.now - 15 * 60, k0 = frameIndex(cut); fr = fr.slice(Math.max(0, k0)); }
  return fr;
}
function visibleActs() {
  const fr = visibleFrames(); if (!fr.length) return [];
  const key = a => a[0] * 1e6 + a[1], k0 = key(fr[0]), k1 = key(fr[fr.length - 1]);
  return T.acts.filter(a => key(a) >= k0 && key(a) <= k1);
}
const sides = () => { const s = +$('ov-side').value; return s === 2 ? [0, 1] : [s]; };
function drawLive(force) {
  const cv = $('pitch'); if (!cv || (!$('v-live').classList.contains('on') && !force)) return;
  const P = pitchCanvas(cv); if (!P) return; drawPitch(P);
  const mode = $('overlay').value, followId = $('followp').value, st = T.meta ? positionsAt(T.now) : null;
  let note = '', faded = false;
  if (T.meta && mode !== 'none') {
    const fr = visibleFrames(), acts = visibleActs();
    if (mode === 'thirds' || mode === 'half') {
      drawThirds(P);
      sides().forEach(s => { const z = liveZones(acts, fr, s); drawTeamLanes(P, s, mode === 'half' ? z.entries5Pct : z.entries3Pct, mode === 'half'); });
      note = 'each team\'s lanes are named from its own direction of attack; darker = more of its final-third entries';
    }
    if (mode === 'territory') { drawGrid(P, liveZones(acts, fr, 0).territory, { mode: 'div' }); note = 'blue squares: the home side had the ball there more; red: the away side'; }
    if (mode === 'occupancy') sides().forEach(s => drawGrid(P, occupancyGrid(s, fr), { rgb: s === 0 ? PITCH.homeRGB : PITCH.awayRGB, labels: sides().length === 1 ? '%' : false, alpha: sides().length === 1 ? .78 : .45 }));
    if (mode === 'heatteam') { sides().forEach(s => drawHeat(P, teamPoints(s, fr), { rgbRamp: sides().length === 2 ? (s === 0 ? 'blue' : 'red') : 'warm' })); faded = true; }
    if (mode === 'avg') { faded = true; }
    if (mode === 'passes') { sides().forEach(s => drawPassMap(P, acts, s)); faded = true; note = 'solid: completed, dashed: lost'; }
    if (mode === 'heat') { if (followId) drawHeat(P, followPoints(followId, fr)); else note = 'pick a player to follow'; faded = !!followId; }
  }
  if (st) {
    let carrier = null, best = 4;
    st.players.forEach(p => { const d = Math.hypot(p.x - st.bx, p.y - st.by); if (d < best) { best = d; carrier = p.id; } });
    drawPlayers(P, st.players, { follow: followId, carrier, faded });
    if (mode === 'avg') drawAvg(P, visibleFrames());
    if (!faded) drawBall(P, st.bx, st.by);
  }
  $('overlay-note').textContent = note;
}
function teamPoints(side, fr) {
  const pts = [];
  for (let k = 0; k < fr.length; k += 3) T.meta.forEach((p, i) => { if (p.side !== side || p.role === 'GK') return; const x = fr[k][5][2 * i]; if (x >= 0) pts.push([x / 10, fr[k][5][2 * i + 1] / 10]); });
  return pts;
}
function drawAvg(P, fr) {
  const acc = T.meta.map(() => [0, 0, 0]);
  for (let k = 0; k < fr.length; k += 2) T.meta.forEach((p, i) => { const x = fr[k][5][2 * i]; if (x >= 0) { acc[i][0] += x; acc[i][1] += fr[k][5][2 * i + 1]; acc[i][2]++; } });
  const show = sides();
  T.meta.forEach((p, i) => { if (!acc[i][2] || !show.includes(p.side) || acc[i][2] < 60) return;
    disc(P, acc[i][0] / acc[i][2] / 10, acc[i][1] / acc[i][2] / 10, { fill: p.side === 0 ? PITCH.home : PITCH.away, text: p.shirt, ring: PITCH.ink, ringW: 1.5,
      name: p.id === $('followp').value ? p.name.split(' ').slice(-1)[0] : '' }); });
}
function occupancyGrid(side, fr) {
  const g = new Array(96).fill(0);
  for (let k = 0; k < fr.length; k += 2) T.meta.forEach((p, i) => { if (p.side !== side) return; const x = fr[k][5][2 * i]; if (x >= 0) g[cellOf(x / 10, fr[k][5][2 * i + 1] / 10)]++; });
  const t = g.reduce((a, b) => a + b, 0) || 1; return g.map(v => Math.round(1000 * v / t) / 10);
}
function followPoints(pid, fr) {
  const i = T.meta.findIndex(p => p.id === pid); if (i < 0) return [];
  return (fr || visibleFrames()).filter((f, k) => k % 2 === 0 && f[5][2 * i] >= 0).map(f => [f[5][2 * i] / 10, f[5][2 * i + 1] / 10]);
}
function refreshZones() {
  if (!T.meta) return;
  const tab = (document.querySelector('#ltabs button.on') || {}).dataset?.tab;
  if (tab === 'zones') {
    const side = +$('z-team').value, z = liveZones(visibleActs(), visibleFrames(), side);
    const B = pitchCanvas($('z-bands')); if (B) { drawPitch(B, { arrow: true }); drawBands(B, z.bandsPct.map(v => Math.round(v))); }
    const R = pitchCanvas($('z-terr')); if (R) { drawPitch(R); drawGrid(R, z.territory, { mode: 'div' }); }
    const name = club(side === 0 ? S.live.fixture.home : S.live.fixture.away).name;
    $('z-lanes').innerHTML = `<div class="kicker">${esc(name)}: final-third entries by lane (${z.entries})</div>` +
      barRows(['Left', 'Centre', 'Right'], z.entries3Pct) + `<div class="kicker" style="margin-top:8px">Possession by third</div>` + barRows(['Defensive', 'Middle', 'Attacking'], z.possThirdsPct);
    $('z-half').innerHTML = `<div class="kicker">Entries by lane, with half-spaces</div>` + barRows(PITCH.lane5Names, z.entries5Pct);
  }
  const pid = $('followp').value;
  if (tab === 'player' && pid) {
    const pts = followPoints(pid), H = pitchCanvas($('f-heat')); if (H) { drawPitch(H); drawHeat(H, pts); }
    const g = new Array(96).fill(0); pts.forEach(([x, y]) => g[cellOf(x, y)]++); const t = pts.length || 1;
    const G = pitchCanvas($('f-grid')); if (G) { drawPitch(G); drawGrid(G, g.map(v => Math.round(1000 * v / t) / 10), { labels: '%', rgb: PITCH.goldRGB }); }
  }
}
function barRows(names, pct, rgb = 'var(--green)') {
  const mx = Math.max(...pct, 1);
  return names.map((n, i) => `<div class="archbar"><span>${esc(n)}</span><div class="track"><div class="fill" style="width:${100 * pct[i] / mx}%;background:${pct[i] === mx ? 'var(--gold)' : rgb}"></div></div><span class="num">${pct[i]}%</span></div>`).join('');
}
function tick() {
  if (T.playing && S.replay) {  // replay: the clock reveals frames up to now
    T.now = (performance.now() - T.t0) / 1000 * T.speed;
    if (T.now > T.at[T.at.length - 1]) T.playing = false;
  }
  drawLive();
  if (performance.now() - T.lastZones > 1000) { T.lastZones = performance.now(); refreshZones(); }
  requestAnimationFrame(tick);
}
const pp = x => Math.round(100 * x) + '%';
function setProbs(p) {
  ['h', 'd', 'a'].forEach((k, i) => {
    const v = p[['home', 'draw', 'away'][i]];
    $('pb-' + k).style.width = (100 * v) + '%'; $('pl-' + k).textContent = pp(v);
  });
  $('pb-why').textContent = (p.why || []).join('; ');
}
function probChart() {
  const fx = S.live.fixture;
  const flat = (v, col) => ({ label: '', data: [{ x: 0, y: 100 * v }, { x: 95, y: 100 * v }], borderColor: col, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, fill: false });
  chart('probChart', {
    type: 'line', data: { datasets: [
      { label: club(fx.home).name, data: [], borderColor: C.blue, backgroundColor: C.blue + '22', fill: 'origin', borderWidth: 2.2, pointRadius: 0, tension: .2 },
      { label: 'Draw', data: [], borderColor: '#8d8676', borderWidth: 1.6, pointRadius: 0, tension: .2 },
      { label: club(fx.away).name, data: [], borderColor: C.red, backgroundColor: C.red + '22', fill: 'origin', borderWidth: 2.2, pointRadius: 0, tension: .2 },
      flat(fx.market.home, C.blue), flat(fx.market.away, C.red)] },
    options: { animation: false, parsing: false, maintainAspectRatio: false, scales: { x: { type: 'linear', min: 0, max: 95, title: { display: true, text: 'minute' } },
      y: { min: 0, max: 100, ticks: { callback: v => v + '%' } } },
      plugins: { legend: { labels: { filter: i => i.text } } } } });
}
function pushProb(p) {
  const ch = S.charts.probChart; if (!ch) return;
  const x = Math.min(95, p.minute || 0), d = ch.data.datasets;
  if (d[0].data.length && d[0].data[d[0].data.length - 1].x === x) { d[0].data.pop(); d[1].data.pop(); d[2].data.pop(); }
  d[0].data.push({ x, y: 100 * p.home }); d[1].data.push({ x, y: 100 * p.draw }); d[2].data.push({ x, y: 100 * p.away }); ch.update('none');
}
const LIVE_ROWS = [['goals', 'Goals'], ['xg', 'Expected goals (xG)'], ['xg_last10', 'xG, last 10 minutes'], ['shots', 'Shots'], ['on_target', 'On target'],
  ['big_chances', 'Big chances'], ['possession', 'Possession %'], ['field_tilt', 'Field tilt %'], ['pass_accuracy', 'Pass accuracy %'],
  ['passes', 'Passes'], ['corners', 'Corners'], ['saves', 'Saves'], ['offsides', 'Offsides'], ['fouls', 'Fouls'], ['yellows', 'Yellow cards'], ['reds', 'Red cards']];
function renderStats(s) {
  const fx = S.live.fixture, h = s ? s.teams[fx.home] : {}, a = s ? s.teams[fx.away] : {};
  $('stats').innerHTML = `<div class="grid2">${[LIVE_ROWS.slice(0, 8), LIVE_ROWS.slice(8)].map(rows => `<div>${rows.map(([k, l]) => {
    const hv = +(h[k] ?? 0), av = +(a[k] ?? 0), t = hv + av || 1;
    return `<div class="statrow"><div class="v">${hv}</div><div class="mid">${l}<div class="bar2">
      <div style="width:${100 * hv / t}%;background:${C.blue}"></div><div style="width:${100 * av / t}%;background:${C.red}"></div></div></div>
      <div class="v r">${av}</div></div>`; }).join('')}</div>`).join('')}</div>`;
  if (!s) return;
  S.lastSnap = s;
  $('score').textContent = `${s.score[fx.home]} – ${s.score[fx.away]}`;
  $('clock').textContent = s.finished ? 'FT' : s.clock;
  if (s.probs) { setProbs(s.probs); pushProb(s.probs); }
  renderFollow(s);
}
function renderFollow(s) {
  const pid = $('followp').value;
  $('follow-card').style.display = pid ? '' : 'none'; $('follow-empty').style.display = pid ? 'none' : '';
  if (!pid) return;
  const p = S.byId[pid], line = s && s.players ? s.players[pid] : null;
  $('f-title').innerHTML = `${esc(p.name)} <span class="small">${esc(club(p.club).name)} · ${roleName(p.role)}${p.archetype ? ' · ' + esc(p.archetype.name) : ''}</span>`;
  const today = line ? Object.entries(line).filter(([k]) => !['id', 'name', 'team'].includes(k))
    .map(([k, v]) => `<span class="chip" style="margin:2px">${esc(k.replace(/_/g, ' '))} ${typeof v === 'number' ? (+v.toFixed(2)) : esc(v)}</span>`).join('') : '<span class="small">No involvement yet.</span>';
  $('f-body').innerHTML = `<div class="kicker">This match</div><div style="margin:6px 0 10px">${today}</div>
    <div class="kicker">Season, v ${roleName(p.role).toLowerCase()}s in ${esc(leagueName(p.league))}</div>${pctHead()}${roleOf(p.role).stats.map(k => pctRow(p, k, 'league')).join('')}`;
}
function addCard(ins) {
  const feed = $('feed'); if (feed.querySelector('.empty')) feed.innerHTML = '';
  const l = ins.line, el = document.createElement('div');
  const follow = $('followp').value && S.byId[$('followp').value];
  const mentions = follow && JSON.stringify(ins.facts).includes(follow.name);
  el.className = `ins k-${ins.kind}`;
  if (mentions) el.style.boxShadow = `0 0 0 3px ${C.gold}`;
  const src = l.source === 'template' ? 'template' : `${l.source} agent`;
  const check = l.grounded ? 'fact-checked: every number is in the evidence' : `model line rejected (${esc((l.rejected_reasons || []).join('; '))}), template shown`;
  el.innerHTML = `<div class="top"><span class="kicker">${esc(ins.kind.replace('_', ' '))}</span><span class="small">${esc(ins.clock)} · importance ${ins.importance}</span></div>
    <p>${esc(l.text)}</p>${(ins.depth || []).length ? `<div class="depth"><div class="kicker">In depth</div><ul>${ins.depth.map(d => `<li>${esc(d.text)}</li>`).join('')}</ul></div>` : ''}
    <details><summary>Why?</summary><ul>${ins.why.map(w => `<li>${esc(w.text)}</li>`).join('')}</ul>
    <div class="small">Source: ${src} · ${check}${l.note ? ' · ' + esc(l.note) : ''}</div><code>${esc(JSON.stringify(ins.facts, null, 1))}</code></details>`;
  feed.prepend(el);
  $('log-n').textContent = feed.querySelectorAll('.ins').length;
  if ($('pop').checked) popInsight(ins, mentions);
}
function popInsight(ins, mentions) {  // appears when it happens, then fades out
  const box = $('pops'), el = document.createElement('div');
  el.className = `pop k-${ins.kind}`;
  if (mentions) el.style.boxShadow = `0 0 0 3px ${C.gold}`;
  el.innerHTML = `<div class="k">${esc(ins.kind.replace('_', ' '))} · ${esc(ins.clock)}</div>${esc(ins.line.text)}`;
  box.prepend(el);
  while (box.children.length > 3) box.lastChild.remove();
  const life = 3500 + 4500 * ins.importance;
  setTimeout(() => el.classList.add('out'), life); setTimeout(() => el.remove(), life + 700);
}
let timers = [], es = null;
function kickOff() {
  timers.forEach(clearTimeout); timers = []; if (es) es.close();
  $('feed').innerHTML = '<div class="empty">Kick-off…</div>'; $('log-n').textContent = '0'; $('pops').innerHTML = '';
  probChart(); renderStats(null);
  const persona = $('persona').value, lang = $('lang').value, fav = $('team').value, speed = +$('speed').value;
  T.speed = speed;
  if (S.replay) { T.now = 0; T.t0 = performance.now(); T.playing = true; }
  if (!S.replay) {
    const q = new URLSearchParams({ persona, lang, team: fav, speed });
    T.frames = []; T.at = []; T.acts = []; T.now = 0;
    es = new EventSource('stream?' + q);
    es.addEventListener('hello', e => { const d = JSON.parse(e.data); setTrack(d.track, 0); T.frames = []; T.at = []; T.acts = []; });
    es.addEventListener('frames', e => { const d = JSON.parse(e.data);
      d.frames.forEach(f => { T.frames.push(f); T.at.push(f[6]); }); T.acts.push(...d.actions);
      if (T.at.length) T.now = T.at[T.at.length - 1]; });
    es.addEventListener('stats', e => renderStats(JSON.parse(e.data)));
    es.addEventListener('insight', e => addCard(JSON.parse(e.data)));
    es.addEventListener('done', () => { es.close(); $('clock').textContent = 'FT'; });
    return;
  }
  const minImp = S.live.persona_min[persona], tl = S.replay.timeline;
  for (const item of tl) {
    timers.push(setTimeout(() => {
      if (item.type === 'stats') return renderStats(item.data);
      const ins = item.data, bump = fav && ins.team === fav ? 0.15 : 0;
      if (ins.importance + bump < minImp - 1e-9) return;
      const line = item.lines[`${persona}|${lang}|${fav}`] || item.lines[`${persona}|${lang}|`] || item.lines[`${persona}|en|`];
      if (line) addCard({ ...ins, line });
    }, item.at * 1000 / speed));
  }
}

/* ---------------- shared: percentile row ---------------- */
function scopeKey(p, scope) { return scope === 'all' ? 'pct_all' : 'pct'; }
function avgOf(p, k, scope) { return (S.meta.averages[`${scope === 'all' ? 'all' : p.league}|${p.role}`] || {})[k]; }
const ELITE = 99;  // percentile from which a stat is marked gold
function pctHead() {
  return `<div class="pct head"><span>Stat</span><span>Value</span><span>Percentile (line = median)</span><span class="r">Better than</span><span class="r">Group avg</span></div>`;
}
function pctRow(p, k, scope) {
  const pc = p[scopeKey(p, scope)][k], v = p.values[k], avg = avgOf(p, k, scope), elite = pc != null && pc >= ELITE;
  return `<div class="pct${elite ? ' elite' : ''}"><span>${esc(statLabel(k))}</span><span class="num">${fmt(v, k)}</span>
    <div class="track" title="better than ${pc ?? '–'}% of the group"><div class="fill" style="width:${pc ?? 0}%;background:${elite ? 'var(--gold)' : pctColor(pc)}"></div><div class="avg" style="left:50%"></div></div>
    <span class="p">${pc == null ? '–' : pc + '%'}</span><span class="small num" style="text-align:right">${fmt(avg, k)}</span></div>`;
}

/* ---------------- PLAYERS ---------------- */
function initPlayers() {
  opt($('p-league'), S.meta.leagues.map(l => [l.id, l.name]));
  $('p-names').innerHTML = S.players.filter(p => p.minutes > 0).map(p => `<option value="${esc(p.name)}">${esc(club(p.club).name)} · ${p.role}</option>`).join('');
  const clubs = () => { const lg = S.meta.leagues.find(l => l.id === $('p-league').value);
    opt($('p-club'), S.tables[lg.id].map(c => [c, club(c).name])); squad(); };
  const squad = () => { const ps = S.players.filter(p => p.club === $('p-club').value)
      .sort((a, b) => S.meta.roles.findIndex(r => r.id === a.role) - S.meta.roles.findIndex(r => r.id === b.role) || b.minutes - a.minutes);
    opt($('p-player'), ps.map(p => [p.id, `${p.role} · ${p.name}${p.eligible ? '' : ' (few minutes)'}`])); renderPlayer(); };
  $('p-league').onchange = clubs; $('p-club').onchange = squad; $('p-player').onchange = renderPlayer; $('p-scope').onchange = renderPlayer;
  $('p-search').onchange = () => { const p = S.players.find(x => x.name === $('p-search').value); if (p) openPlayer(p.id); };
  clubs();
}
function openPlayer(id) {
  const p = S.byId[id]; $('p-league').value = p.league; $('p-league').onchange();
  $('p-club').value = p.club; $('p-club').onchange(); $('p-player').value = id; renderPlayer(); show('players');
}
function renderPlayer() {
  const p = S.byId[$('p-player').value]; if (!p) return;
  const scope = $('p-scope').value, rk = p['rank_' + (scope === 'all' ? 'all' : 'league')];
  const cats = {}; Object.entries(S.meta.catalog).forEach(([k, c]) => (cats[c.category] = cats[c.category] || []).push(k));
  const pk = scopeKey(p, scope), role = roleOf(p.role);
  const strong = role.stats.filter(k => p[pk][k] >= 80 && p[pk][k] < ELITE), weak = role.stats.filter(k => p[pk][k] != null && p[pk][k] <= 20);
  const elite = Object.keys(S.meta.catalog).filter(k => p[pk][k] >= ELITE && avgOf(p, k, scope));
  S.radarStats = S.radarStats && S.radarRole === p.role ? S.radarStats : role.stats.slice(); S.radarRole = p.role;
  $('p-body').innerHTML = `
  <div class="grid2"><div class="card">
    <div class="kicker">${esc(leagueName(p.league))} · ${esc(club(p.club).name)} · #${p.shirt}</div>
    <h2>${esc(p.name)}</h2>
    <p class="sub">${roleName(p.role)} · ${p.age} · ${p.height_cm} cm · ${p.foot === 'L' ? 'left' : 'right'}-footed</p>
    <div class="row">${p.archetype ? `<span class="chip ${p.archetype.clear ? 'green' : ''}">${esc(p.archetype.name)}</span>` : ''}
      <span class="chip">${p.apps} apps · ${p.starts} starts · ${p.minutes} min</span>
      <span class="chip ${p.eligible ? 'blue' : 'red'}">${p.eligible ? 'above' : 'below'} the minutes bar (${p.minutes_bar})</span></div>
    <p style="margin:12px 0 4px"><b style="font:28px var(--head)">${fmt(p.values.rating, 'rating')}</b> xV rating ·
      ${rk ? `${ord(rk.rank)} of ${rk.of} ${roleName(p.role).toLowerCase()}s ${scope === 'all' ? 'across all leagues' : 'in the league'}` : 'not ranked (below the minutes bar)'}</p>
    ${elite.length ? `<p style="margin:6px 0"><span class="chip gold">★ Elite</span> top 1% of ${roleName(p.role).toLowerCase()}s for <b>${elite.map(statLabel).join(', ')}</b></p>` : ''}
    <p class="small">${strong.length ? 'Strengths: ' + strong.map(statLabel).join(', ') + '. ' : ''}${weak.length ? 'Weaker: ' + weak.map(statLabel).join(', ') + '.' : ''}</p>
    <h3 style="margin-top:12px">Archetype</h3><p class="small">${p.archetype ? esc(p.archetype.desc) : ''} ${p.archetype && !p.archetype.clear ? 'Close call between the top two.' : ''}</p>
    ${(p.archetypes || []).map(a => `<div class="archbar"><span>${esc(a.name)}</span><div class="track"><div class="fill" style="width:${a.score}%"></div></div><span class="num">${a.score}</span></div>`).join('')}
  </div>
  <div class="card"><h3>Radar</h3><canvas id="radarP" height="300"></canvas>
    <div class="row small" style="margin:6px 0">Stats on the radar (percentiles ${scope === 'all' ? 'v all leagues' : 'v the league'}):
      <button id="rp-role">Role default</button><button id="rp-clear">Clear</button></div>
    <div class="statpick" id="rp-pick">${Object.keys(S.meta.catalog).map(k => `<label><input type="checkbox" value="${k}" ${S.radarStats.includes(k) ? 'checked' : ''}> ${esc(statLabel(k))}</label>`).join('')}</div></div></div>
  ${p.grid ? `<div class="card" style="margin-top:16px"><h3>Where ${esc(p.name.split(' ')[0])} plays <span class="small">season, synthetic tracking, attacking →</span></h3>
    <div class="grid2"><div><div class="kicker">Heatmap</div><canvas id="ph-heat" style="width:100%"></canvas></div>
    <div><div class="kicker">Squares occupied (% of time on the pitch) · ● average position</div><canvas id="ph-grid" style="width:100%"></canvas></div></div></div>` : ''}
  <div class="grid2" style="margin-top:16px"><div class="card"><h3>Ranking factors</h3>
    <p class="small">What drives the xV rating: average contribution per match (6.0 is the baseline; the role adjustment puts every role on the same scale).</p>
    <canvas id="factorsP" height="${40 + 22 * (p.rating_factors || []).length}"></canvas>
    <h3 style="margin-top:12px">Rating by round</h3><canvas id="formP" height="120"></canvas></div>
  <div class="card"><h3>Every stat <span class="small">v ${roleName(p.role).toLowerCase()}s ${scope === 'all' ? 'in all four leagues' : 'in ' + esc(leagueName(p.league))} · counting stats per 90 · ★ gold = top 1%</span></h3>
    ${pctHead()}${Object.entries(cats).map(([c, ks]) => [c, ks.filter(k => avgOf(p, k, scope))]).filter(([, ks]) => ks.length)
      .map(([c, ks]) => `<div class="cat">${esc(c)}</div>${ks.map(k => pctRow(p, k, scope)).join('')}`).join('')}
    <p class="small">Stats that don't apply to the role (group average 0) are hidden.</p></div></div>`;
  const pick = () => { S.radarStats = [...$('rp-pick').querySelectorAll('input:checked')].map(i => i.value); drawRadarP(p, scope); };
  $('rp-pick').onchange = pick;
  $('rp-role').onclick = () => { $('rp-pick').querySelectorAll('input').forEach(i => i.checked = role.stats.includes(i.value)); pick(); };
  $('rp-clear').onclick = () => { $('rp-pick').querySelectorAll('input').forEach(i => i.checked = false); pick(); };
  drawRadarP(p, scope);
  if (p.grid) {
    const H = pitchCanvas($('ph-heat')); if (H) { drawPitch(H, { arrow: true }); drawHeat(H, gridPoints(p.grid, p.id)); }
    const G = pitchCanvas($('ph-grid'));
    if (G) { drawPitch(G); drawGrid(G, p.grid, { labels: '%', rgb: PITCH.goldRGB });
      const [ax, ay] = G.pt(p.avg_pos[0], p.avg_pos[1]); G.ctx.beginPath(); G.ctx.arc(ax, ay, 7, 0, 7);
      G.ctx.fillStyle = PITCH.ink; G.ctx.fill(); G.ctx.strokeStyle = PITCH.paper; G.ctx.lineWidth = 2; G.ctx.stroke(); }
  }
  const f = p.rating_factors || [];
  chart('factorsP', { type: 'bar', data: { labels: f.map(x => x.factor), datasets: [{ data: f.map(x => x.per_match),
    backgroundColor: f.map(x => x.per_match >= 0 ? C.green : C.red) }] },
    options: { indexAxis: 'y', plugins: { legend: { display: false } }, animation: false } });
  chart('formP', { type: 'line', data: { labels: p.ratings.map(r => 'R' + r.round), datasets: [{ data: p.ratings.map(r => r.rating),
    borderColor: C.ink, pointBackgroundColor: p.ratings.map(r => r.rating >= 7 ? C.green : r.rating < 6 ? C.red : C.ink), tension: .2 }] },
    options: { plugins: { legend: { display: false } }, scales: { y: { suggestedMin: 5, suggestedMax: 8.5 } }, animation: false } });
}
function radarCfg(stats, sets) {
  return { type: 'radar', data: { labels: stats.map(statLabel), datasets: [
    ...sets.map(s => ({ label: s.label, data: s.data, borderColor: s.col, backgroundColor: s.col + '22', borderWidth: 2, pointRadius: 2 })),
    { label: 'Group median', data: stats.map(() => 50), borderColor: C.muted, borderDash: [4, 4], borderWidth: 1, pointRadius: 0, backgroundColor: 'transparent' }] },
    options: { animation: false, scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, backdropColor: 'transparent' }, pointLabels: { font: { size: 11 } } } } } };
}
function drawRadarP(p, scope) {
  const st = S.radarStats.length >= 3 ? S.radarStats : roleOf(p.role).stats, k = scopeKey(p, scope);
  chart('radarP', radarCfg(st, [{ label: p.name, data: st.map(s => p[k][s] ?? 0), col: C.blue }]));
}

/* ---------------- COMPARE ---------------- */
function initCompare() { $('c-mode').onchange = renderCompare; renderCompare(); }
function renderCompare() {
  const mode = $('c-mode').value, el = $('c-pickers');
  if (mode === 'players') {
    const eligible = S.players.filter(p => p.eligible).sort((a, b) => a.name.localeCompare(b.name));
    const o = eligible.map(p => `<option value="${p.id}">${esc(p.name)} (${p.role}, ${esc(club(p.club).name)})</option>`).join('');
    el.innerHTML = `<select id="c-a">${o}</select> v <select id="c-b">${o}</select>
      <span class="small">Each player is measured against their own role.</span>`;
    const st = eligible.filter(p => p.role === 'ST').sort((a, b) => b.values.rating - a.values.rating);
    $('c-a').value = st[0].id; $('c-b').value = st[1].id;
    ['c-a', 'c-b'].forEach(i => $(i).onchange = drawComparePlayers); drawComparePlayers();
  } else {
    const o = S.meta.leagues.map(l => `<optgroup label="${esc(l.name)}">${S.tables[l.id].map(c => `<option value="${c}">${esc(club(c).name)}</option>`).join('')}</optgroup>`).join('');
    el.innerHTML = `<select id="c-ta">${o}</select> v <select id="c-tb">${o}</select>`;
    $('c-ta').value = S.tables.meridian[0]; $('c-tb').value = S.tables.calder[0];
    ['c-ta', 'c-tb'].forEach(i => $(i).onchange = drawCompareTeams); drawCompareTeams();
  }
}
function drawComparePlayers() {
  const a = S.byId[$('c-a').value], b = S.byId[$('c-b').value];
  const scope = a.league === b.league ? 'league' : 'all', k = scopeKey(a, scope);
  const stats = [...new Set([...roleOf(a.role).stats, ...(a.role === b.role ? [] : roleOf(b.role).stats)])];
  let wa = 0, wb = 0;
  const rows = Object.keys(S.meta.catalog).map(s => {
    const pa = a[k][s], pb = b[k][s]; if (a.values[s] == null && b.values[s] == null) return '';
    const win = pa != null && pb != null && pa !== pb ? (pa > pb ? 'a' : 'b') : '';
    if (stats.includes(s)) { if (win === 'a') wa++; if (win === 'b') wb++; }
    return `<tr><td>${esc(statLabel(s))}</td><td class="n" style="${win === 'a' ? 'font-weight:700' : ''}">${fmt(a.values[s], s)} <span style="color:${pctColor(pa)}">(${pa ?? '–'})</span></td>
      <td class="n" style="${win === 'b' ? 'font-weight:700' : ''}">${fmt(b.values[s], s)} <span style="color:${pctColor(pb)}">(${pb ?? '–'})</span></td></tr>`;
  }).join('');
  $('c-body').innerHTML = `<div class="grid2"><div class="card"><h3>${esc(a.name)} <span style="color:var(--blue)">●</span> v ${esc(b.name)} <span style="color:var(--red)">●</span></h3>
    <p class="sub">On their key stats ${esc(a.name)} leads ${wa}, ${esc(b.name)} leads ${wb}. Percentiles ${scope === 'all' ? 'v all four leagues (different leagues)' : 'v ' + esc(leagueName(a.league))}, each against their own role.</p>
    <canvas id="radarC" height="320"></canvas></div>
    <div class="card tablewrap"><table><tr><th>Stat</th><th class="n">${esc(a.name)}</th><th class="n">${esc(b.name)}</th></tr>${rows}</table></div></div>`;
  chart('radarC', radarCfg(stats, [{ label: a.name, data: stats.map(s => a[k][s] ?? 0), col: C.blue }, { label: b.name, data: stats.map(s => b[k][s] ?? 0), col: C.red }]));
}
function drawCompareTeams() {
  const a = club($('c-ta').value), b = club($('c-tb').value); let wa = 0, wb = 0;
  const rows = Object.entries(S.meta.team_stats).map(([k, d]) => {
    const va = a.values[k], vb = b.values[k], better = va === vb ? '' : (d.higher_better ? va > vb : va < vb) ? 'a' : 'b';
    if (better === 'a') wa++; if (better === 'b') wb++;
    return `<tr><td>${esc(d.label)}</td><td class="n" style="${better === 'a' ? 'font-weight:700' : ''}">${va} <span class="small">${ord(a.ranks[k])}</span></td>
      <td class="n" style="${better === 'b' ? 'font-weight:700' : ''}">${vb} <span class="small">${ord(b.ranks[k])}</span></td></tr>`;
  }).join('');
  const keys = ['xgf', 'xga', 'shots_for', 'possession', 'field_tilt', 'ppda', 'crosses', 'aerials_won'];
  $('c-body').innerHTML = `<div class="grid2"><div class="card"><h3>${esc(a.name)} v ${esc(b.name)}</h3>
    <p class="sub">${esc(a.name)} (${ord(a.position)} in ${esc(leagueName(a.league))}, form ${a.form}) leads ${wa} measures; ${esc(b.name)} (${ord(b.position)} in ${esc(leagueName(b.league))}, form ${b.form}) leads ${wb}. Small ranks are each team's place in its own league.</p>
    <canvas id="teamC" height="260"></canvas></div><div class="card tablewrap"><table><tr><th>Measure</th><th class="n">${esc(a.name)}</th><th class="n">${esc(b.name)}</th></tr>${rows}</table></div></div>`;
  chart('teamC', { type: 'bar', data: { labels: keys.map(statLabel), datasets: [
    { label: a.name, data: keys.map(k => a.values[k]), backgroundColor: C.blue }, { label: b.name, data: keys.map(k => b.values[k]), backgroundColor: C.red }] },
    options: { indexAxis: 'y', animation: false } });
}

/* ---------------- SCATTER ---------------- */
function initScatter() {
  opt($('s-league'), [['all', 'All leagues'], ...S.meta.leagues.map(l => [l.id, l.name])]);
  ['s-entity', 's-league', 's-role', 's-x', 's-y', 's-elig'].forEach(i => $(i).onchange = () => { if (i === 's-entity') scatterAxes(); renderScatter(); });
  scatterAxes();
}
function scatterAxes() {
  const players = $('s-entity').value === 'players';
  $('s-role').style.display = players ? '' : 'none';
  opt($('s-role'), [['all', 'All players'], ...S.meta.roles.map(r => [r.id, r.name + 's'])], 'ST');
  const keys = players ? Object.keys(S.meta.catalog) : Object.keys(S.meta.team_stats);
  opt($('s-x'), keys.map(k => [k, statLabel(k)]), players ? 'npxg' : 'xgf');
  opt($('s-y'), keys.map(k => [k, statLabel(k)]), players ? 'goals' : 'xga');
}
const outlierLabels = {
  id: 'outliers', afterDatasetsDraw(ch) {
    const ctx = ch.ctx; ctx.save(); ctx.font = "600 11px 'IBM Plex Sans Condensed'"; ctx.fillStyle = C.ink;
    ch.data.datasets.forEach((ds, i) => ch.getDatasetMeta(i).data.forEach((pt, j) => { if (ds.data[j].lab) ctx.fillText(ds.data[j].lab, pt.x + 5, pt.y - 4); }));
    const a = ch.options.plugins.outliers; if (a) { const xs = ch.scales.x, ys = ch.scales.y; ctx.strokeStyle = C.muted; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(xs.getPixelForValue(a.mx), ys.top); ctx.lineTo(xs.getPixelForValue(a.mx), ys.bottom);
      ctx.moveTo(xs.left, ys.getPixelForValue(a.my)); ctx.lineTo(xs.right, ys.getPixelForValue(a.my)); ctx.stroke(); }
    ctx.restore();
  } };
function renderScatter() {
  if (!$('v-scatter').classList.contains('on')) return;
  const players = $('s-entity').value === 'players', lg = $('s-league').value, x = $('s-x').value, y = $('s-y').value;
  const role = $('s-role').value;
  let pts = players ? S.players.filter(p => (role === 'all' || p.role === role) && (!$('s-elig').checked || p.eligible))
    .map(p => ({ id: p.id, league: p.league, name: p.name, x: p.values[x], y: p.values[y] }))
    : Object.values(S.teams).map(t => ({ id: t.code, league: t.league, name: t.name, x: t.values[x], y: t.values[y] }));
  pts = pts.filter(p => (lg === 'all' || p.league === lg) && p.x != null && p.y != null);
  const mx = pts.reduce((s, p) => s + p.x, 0) / pts.length, my = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  const sd = k => Math.sqrt(pts.reduce((s, p) => s + (p[k] - (k === 'x' ? mx : my)) ** 2, 0) / pts.length) || 1;
  const sx = sd('x'), sy = sd('y');
  pts.forEach(p => p.z = Math.hypot((p.x - mx) / sx, (p.y - my) / sy));
  const top = new Set(pts.slice().sort((a, b) => b.z - a.z).slice(0, players ? 10 : 12).map(p => p.id));
  const sets = S.meta.leagues.filter(l => lg === 'all' || l.id === lg).map(l => ({ label: l.name, backgroundColor: LEAGUE_COL[l.id] + 'cc', pointRadius: role === 'all' ? 3 : 4,
    data: pts.filter(p => p.league === l.id).map(p => ({ x: p.x, y: p.y, id: p.id, name: p.name, lab: top.has(p.id) ? p.name.split(' ').slice(-1)[0] : '' })) }));
  chart('scatterChart', { type: 'scatter', data: { datasets: sets }, plugins: [outlierLabels],
    options: { animation: false, plugins: { outliers: { mx, my }, tooltip: { callbacks: { label: c => `${c.raw.name}: ${fmt(c.raw.x, x)}, ${fmt(c.raw.y, y)}` } } },
      scales: { x: { title: { display: true, text: statLabel(x) + (players && S.meta.catalog[x].kind === 'count' ? ' per 90' : '') } },
        y: { title: { display: true, text: statLabel(y) + (players && S.meta.catalog[y].kind === 'count' ? ' per 90' : '') } } },
      onClick: (e, els) => { if (players && els.length) { const r = S.charts.scatterChart.data.datasets[els[0].datasetIndex].data[els[0].index]; openPlayer(r.id); } } } });
  $('s-note').textContent = `${pts.length} ${players ? (role === 'all' ? 'players, all roles' : roleName(role).toLowerCase() + 's') : 'teams'}. Dashed lines are the averages. ${players ? 'Click a dot to open the player.' : ''}`;
}

/* ---------------- RANKINGS ---------------- */
const RK = { cols: null, filters: [], sort: 'rating', dir: 0 };
function initRankings() {
  opt($('r-league'), [['all', 'All leagues'], ...S.meta.leagues.map(l => [l.id, l.name])], 'all');
  opt($('r-role'), [['all', 'All players'], ...S.meta.roles.map(r => [r.id, r.name + 's'])], 'ST');
  opt($('r-stat'), Object.keys(S.meta.catalog).map(k => [k, statLabel(k)]), 'rating');
  const roleDefault = () => { const r = $('r-role').value; RK.cols = r === 'all' ? ['goals', 'npxg', 'xa', 'key_passes', 'tackles', 'interceptions', 'pass_pct'] : roleOf(r).stats.slice(); };
  roleDefault();
  $('r-role').onchange = () => { roleDefault(); renderRankPicker(); renderRankings(); };
  ['r-league', 'r-show', 'r-elig'].forEach(i => $(i).onchange = renderRankings);
  $('r-stat').onchange = () => { RK.sort = $('r-stat').value; RK.dir = 0; renderRankings(); };
  $('r-c-role').onclick = () => { roleDefault(); renderRankPicker(); renderRankings(); };
  $('r-c-all').onclick = () => { RK.cols = Object.keys(S.meta.catalog).filter(k => k !== 'rating'); renderRankPicker(); renderRankings(); };
  $('r-c-none').onclick = () => { RK.cols = []; renderRankPicker(); renderRankings(); };
  $('r-f-add').onclick = () => { RK.filters.push({ k: 'goals', min: '', max: '' }); renderRankFilters(); };
  renderRankPicker(); renderRankFilters(); renderRankings();
}
function renderRankPicker() {
  const cats = {}; Object.entries(S.meta.catalog).forEach(([k, c]) => { if (k !== 'rating') (cats[c.category] = cats[c.category] || []).push(k); });
  $('r-cols').innerHTML = Object.entries(cats).map(([c, ks]) => `<b style="width:100%;font-size:11px;letter-spacing:.08em;text-transform:uppercase">${esc(c)}</b>` +
    ks.map(k => `<label><input type="checkbox" value="${k}" ${RK.cols.includes(k) ? 'checked' : ''}> ${esc(statLabel(k))}</label>`).join('')).join('');
  $('r-cols').onchange = () => { RK.cols = [...$('r-cols').querySelectorAll('input:checked')].map(i => i.value); renderRankings(); };
}
function renderRankFilters() {
  const so = Object.keys(S.meta.catalog).map(k => `<option value="${k}">${esc(statLabel(k))}</option>`).join('');
  $('r-filters').innerHTML = RK.filters.length ? RK.filters.map((f, i) => `<div class="frow" data-i="${i}"><select data-f="k">${so}</select>
    from <input type="number" step="any" data-f="min" value="${f.min}" placeholder="min"> to <input type="number" step="any" data-f="max" value="${f.max}" placeholder="max">
    <label><input type="checkbox" data-f="pct" ${f.pct ? 'checked' : ''}> as percentile</label><button data-f="x">✕</button></div>`).join('') : '<span class="small">No filters. Add one to keep, say, only players with 0.3+ goals per 90.</span>';
  $('r-filters').querySelectorAll('.frow').forEach(row => {
    const f = RK.filters[+row.dataset.i];
    row.querySelector('[data-f=k]').value = f.k;
    row.querySelectorAll('[data-f]').forEach(el => el.onchange = el.oninput = () => {
      const t = el.dataset.f; if (t === 'x') return;
      f[t] = t === 'pct' ? el.checked : el.value; renderRankings(); });
    row.querySelector('[data-f=x]').onclick = () => { RK.filters.splice(+row.dataset.i, 1); renderRankFilters(); renderRankings(); };
  });
}
function renderRankings() {
  const lg = $('r-league').value, role = $('r-role').value, pk = lg === 'all' ? 'pct_all' : 'pct', show = $('r-show').value;
  const k = RK.sort, hb = S.meta.catalog[k].higher_better, dir = RK.dir || (hb ? -1 : 1);
  let rows = S.players.filter(p => (!$('r-elig').checked || p.eligible) && (role === 'all' || p.role === role) && (lg === 'all' || p.league === lg));
  for (const f of RK.filters) {
    const lo = f.min === '' ? -Infinity : +f.min, hi = f.max === '' ? Infinity : +f.max;
    rows = rows.filter(p => { const v = f.pct ? p[pk][f.k] : p.values[f.k]; return v != null && v >= lo && v <= hi; });
  }
  rows = rows.filter(p => p.values[k] != null).sort((a, b) => dir * (a.values[k] - b.values[k]));
  // columns grouped by category (Overall first), a double rule between groups
  const order = ['Overall', ...new Set(Object.values(S.meta.catalog).map(c => c.category).filter(c => c !== 'Overall'))];
  const groups = order.map(g => ({ g, cols: [...new Set(['rating', k, ...RK.cols])].filter(c => S.meta.catalog[c].category === g) })).filter(x => x.cols.length);
  const cols = groups.flatMap(x => x.cols), first = new Set(groups.map(x => x.cols[0]));
  const cell = (p, c) => {
    const v = p.values[c], pc = p[pk][c], elite = pc != null && pc >= ELITE;
    const txt = show === 'pct' ? (pc == null ? '–' : pc + '%') : fmt(v, c);
    const sub = show === 'both' && pc != null ? ` <span class="pv">${pc}%</span>` : '';
    return `<td class="cell${elite ? ' elite' : ''}${first.has(c) ? ' gs' : ''}${c === k ? ' sortcol' : ''}" style="background:${pc == null ? 'transparent' : pctTint(pc)}">${elite ? '<span class="star">★</span>' : ''}${txt}${sub}</td>`;
  };
  const shown = rows.slice(0, 200);
  $('r-body').innerHTML = `<table class="rank"><thead>
    <tr class="grp"><th colspan="4"></th>${groups.map(x => `<th colspan="${x.cols.length}" class="gs">${esc(x.g)}</th>`).join('')}</tr>
    <tr><th>#</th><th>Player</th><th>Archetype</th><th class="n">Min</th>
    ${cols.map(c => `<th class="n sort${c === k ? ' sorted' : ''}${first.has(c) ? ' gs' : ''}" data-k="${c}">${esc(statLabel(c))}${c === k ? (dir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('')}</tr></thead><tbody>
    ${shown.map((p, i) => `<tr class="click" data-id="${p.id}"><td>${i < 3 ? `<span class="medal m${i + 1}">${i + 1}</span>` : i + 1}</td>
      <td class="pname"><b>${esc(p.name)}</b> <span class="small"><span class="clubdot" style="background:${club(p.club).colour}"></span>${esc(club(p.club).code || p.club)} · ${p.role}${lg === 'all' ? ' · ' + esc(leagueName(p.league)).split(' ')[0] : ''}</span></td>
      <td class="small">${p.archetype ? `<span class="chip ${p.archetype.clear ? 'cyan' : ''}">${esc(p.archetype.name)}</span>` : ''}</td>
      <td class="n">${p.minutes}</td>${cols.map(c => cell(p, c)).join('')}</tr>`).join('')}</tbody></table>
    <p class="small">${rows.length} players${rows.length > 200 ? ' (first 200 shown)' : ''}. Counting stats are per 90 minutes. Percentiles compare each player with their own role ${lg === 'all' ? 'across all four leagues' : 'in the league'}; ★ gold = top 1%. Minutes bar: ${esc(S.meta.minutes_rule)}.</p>`;
  $('r-body').querySelectorAll('th.sort').forEach(th => th.onclick = () => {
    const c = th.dataset.k; if (RK.sort === c) RK.dir = -(RK.dir || (S.meta.catalog[c].higher_better ? -1 : 1)); else { RK.sort = c; RK.dir = 0; }
    $('r-stat').value = RK.sort; renderRankings(); });
  $('r-body').querySelectorAll('tr.click').forEach(tr => tr.onclick = () => openPlayer(tr.dataset.id));
}
function pctTint(p) {  // stronger, print-friendly heat for table cells
  const t = p / 100, lo = [192, 57, 43], mid = [248, 245, 238], hi = [46, 139, 62];
  const mix = (a, b, f) => a.map((v, i) => Math.round(v + (b[i] - v) * f));
  const c = t < .5 ? mix(lo, mid, t * 2) : mix(mid, hi, (t - .5) * 2), a = .15 + .55 * Math.abs(t - .5) * 2;
  return `rgba(${c},${a.toFixed(2)})`;
}

/* ---------------- TEAMS ---------------- */
function initTeams() {
  opt($('t-league'), S.meta.leagues.map(l => [l.id, l.name]));
  $('t-league').onchange = () => { renderTable(); renderTeam(S.tables[$('t-league').value][0]); };
  $('t-league').onchange();
  opt($('ta-scope'), [['all', 'All four leagues'], ...S.meta.leagues.map(l => [l.id, l.name])], 'all');
  ['ta-scope', 'ta-col'].forEach(i => $(i).onchange = renderAllTeams);
  renderAllTeams(); renderTakeaways();
}
function openTeam(c) {
  const t = club(c); $('t-league').value = t.league; renderTable(); renderTeam(c);
  $('t-team').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* all teams, side by side; grouped columns like the rankings */
const TGROUPS = [['Results', ['pts', 'ppg', 'gf', 'ga', 'gd', 'xpts']], ['Chances', ['xgf', 'xga', 'xgd', 'shots_for', 'shots_against', 'sot_for']],
  ['Style', ['possession', 'pass_pct', 'field_tilt', 'ppda', 'crosses', 'aerials_won', 'corners_for']], ['Discipline', ['fouls', 'yellows']],
  ['Patterns', ['clean_sheets', 'btts_pct', 'over25_pct', 'first_goal_pct', 'points_from_behind']]];
const TA = { sort: 'ppg', dir: -1 };
function renderAllTeams() {
  const scope = $('ta-scope').value, byLeague = $('ta-col').value === 'league';
  const teams = Object.values(S.teams).filter(t => scope === 'all' || t.league === scope);
  const k = TA.sort;
  teams.sort((a, b) => TA.dir * (a.values[k] - b.values[k]));
  const n = teams.length, short = { ppg: 'PPG', gf: 'GF', ga: 'GA', gd: 'GD', xpts: 'xPts', pts: 'Pts', xgf: 'xG for', xga: 'xG agst', xgd: 'xG diff' };
  const pctIn = (t, s) => {   // 100 = best in the view (or in own league)
    const d = S.meta.team_stats[s];
    if (byLeague) { const m = S.tables[t.league].length; return Math.round(100 * (m - t.ranks[s]) / (m - 1)); }
    const vals = teams.map(x => x.values[s]), better = vals.filter(v => d.higher_better ? v < t.values[s] : v > t.values[s]).length;
    return Math.round(100 * better / (n - 1));
  };
  const first = new Set(TGROUPS.map(g => g[1][0]));
  $('t-all').innerHTML = `<table class="rank"><thead><tr class="grp"><th colspan="3"></th>${TGROUPS.map(([g, ks]) => `<th colspan="${ks.length}" class="gs">${g}</th>`).join('')}</tr>
    <tr><th>#</th><th>Club</th><th>League</th>${TGROUPS.flatMap(g => g[1]).map(s => `<th class="n sort${s === k ? ' sorted' : ''}${first.has(s) ? ' gs' : ''}" data-k="${s}" title="${esc(S.meta.team_stats[s].label)}">${esc(short[s] || S.meta.team_stats[s].label)}${s === k ? (TA.dir < 0 ? ' ▼' : ' ▲') : ''}</th>`).join('')}</tr></thead><tbody>
    ${teams.map((t, i) => `<tr class="click" data-c="${t.code}"><td>${i < 3 ? `<span class="medal m${i + 1}">${i + 1}</span>` : i + 1}</td>
      <td class="pname"><span class="clubdot" style="background:${t.colour}"></span><b>${esc(t.name)}</b></td><td class="small">${esc(leagueName(t.league).split(' ')[0])} · ${ord(t.position)}</td>
      ${TGROUPS.flatMap(g => g[1]).map(s => { const pc = pctIn(t, s); return `<td class="cell${pc === 100 ? ' elite' : ''}${first.has(s) ? ' gs' : ''}${s === k ? ' sortcol' : ''}" style="background:${pctTint(pc)}">${t.values[s]}</td>`; }).join('')}</tr>`).join('')}</tbody></table>`;
  $('t-all').querySelectorAll('th.sort').forEach(th => th.onclick = () => {
    const s = th.dataset.k; TA.dir = TA.sort === s ? -TA.dir : (S.meta.team_stats[s].higher_better ? -1 : 1); TA.sort = s; renderAllTeams(); });
  $('t-all').querySelectorAll('tr.click').forEach(tr => tr.onclick = () => openTeam(tr.dataset.c));
}

/* takeaways: the standout clubs on a dozen measures, across all four leagues */
function renderTakeaways() {
  const T = Object.values(S.teams).filter(t => t.zones), avg = f => T.reduce((s, t) => s + f(t), 0) / T.length;
  const r1 = v => Math.round(v * 10) / 10, r2 = v => Math.round(v * 100) / 100;
  const items = [
    ['Best attack', 'gold', t => t.values.xgf, true, (t, a) => `${r2(t.values.xgf)} xG a game, against ${r2(a)} on average.`],
    ['Tightest defence', 'gold', t => -t.values.xga, true, (t, a) => `${r2(t.values.xga)} xG conceded a game (average ${r2(-a)}).`],
    ['Riding their luck', 'orange', t => t.values.pts - t.values.xpts, true, t => `${t.values.pts} points from chances worth ${t.values.xpts}: ${r1(t.values.pts - t.values.xpts)} more than expected.`],
    ['Deserve more', 'cyan', t => t.values.xpts - t.values.pts, true, t => `${t.values.pts} points, but their chances were worth ${t.values.xpts}.`],
    ['Highest press', 'gold', t => -t.values.ppda, true, (t, a) => `${t.values.ppda} opponent passes per defensive action (average ${r1(-a)}): the lower, the harder they press.`],
    ['Keep the ball', 'cyan', t => t.values.possession, true, (t, a) => `${t.values.possession}% possession on average (league-wide ${r1(a)}%).`],
    ['Cross-heavy', 'cyan', t => t.values.crosses, true, (t, a) => `${t.values.crosses} crosses a game (average ${r1(a)}).`],
    ['Comeback kings', 'gold', t => t.values.points_from_behind, true, t => `${t.values.points_from_behind} points won after going behind.`],
    ['Home fortress', 'orange', t => t.home_ppg - t.away_ppg, true, t => `${t.home_ppg} points a game at home, ${t.away_ppg} away.`],
    ['Set-piece threat', 'cyan', t => t.zones.assist_types[3] / Math.max(1, t.values.gf), true, t => `${t.zones.assist_types[3]} of their ${t.values.gf} goals came from corners.`],
    ['Half-space attackers', 'cyan', t => t.zones.entries5_pct[1] + t.zones.entries5_pct[3], true, (t, a) => `${r1(t.zones.entries5_pct[1] + t.zones.entries5_pct[3])}% of final-third entries through the half-spaces (average ${r1(a)}%).`],
    ['Wing play', 'cyan', t => t.zones.entries5_pct[0] + t.zones.entries5_pct[4], true, (t, a) => `${r1(t.zones.entries5_pct[0] + t.zones.entries5_pct[4])}% of entries down the wings (average ${r1(a)}%).`],
  ];
  $('t-take').innerHTML = items.map(([title, tone, f, , txt]) => {
    const best = T.reduce((b, t) => f(t) > f(b) ? t : b, T[0]), a = avg(f);
    return `<div class="obs" style="cursor:pointer" data-c="${best.code}"><span class="chip ${tone} tag">${esc(title)}</span>
      <b>${esc(best.name)}</b> <span class="small">(${esc(leagueName(best.league))}, ${ord(best.position)})</span><br>${esc(txt(best, a))}</div>`;
  }).join('');
  $('t-take').querySelectorAll('[data-c]').forEach(d => d.onclick = () => openTeam(d.dataset.c));
}
function renderTable() {
  const lg = $('t-league').value;
  $('t-table').innerHTML = `<h3>${esc(leagueName(lg))}</h3><table><tr><th>#</th><th>Club</th><th class="n">P</th><th class="n">W</th><th class="n">D</th><th class="n">L</th><th class="n">GD</th><th class="n">Pts</th><th class="n" title="expected points from xG">xPts</th><th>Form</th></tr>
    ${S.tables[lg].map(c => { const t = club(c), v = t.values; return `<tr class="click" data-c="${c}"><td>${t.position <= 3 ? `<span class="medal m${t.position}">${t.position}</span>` : t.position}</td><td><span style="display:inline-block;width:8px;height:8px;background:${t.colour}"></span> <b>${esc(t.name)}</b></td>
      <td class="n">${t.mp}</td><td class="n">${t.w}</td><td class="n">${t.d}</td><td class="n">${t.l}</td><td class="n">${v.gd}</td><td class="n"><b>${v.pts}</b></td>
      <td class="n ${v.pts > v.xpts ? 'neg' : 'pos'}">${v.xpts}</td><td class="num">${[...t.form].map(r => `<span style="color:${r === 'W' ? C.green : r === 'L' ? C.red : C.muted};font-weight:700">${r}</span>`).join('')}</td></tr>`; }).join('')}</table>
    <p class="small">xPts in red: the team has more points than its chances suggest; green: fewer.</p>`;
  $('t-table').querySelectorAll('tr.click').forEach(tr => tr.onclick = () => renderTeam(tr.dataset.c));
}
function renderTeam(c) {
  S.curTeam = c;
  const t = club(c), n = S.tables[t.league].length, best = S.players.filter(p => p.club === c && p.eligible).sort((a, b) => b.values.rating - a.values.rating).slice(0, 5);
  const rankChip = r => r === 1 ? 'gold' : r <= 3 ? 'cyan' : r >= n - 1 ? 'orange' : '';
  $('t-team').innerHTML = `<div class="kicker">${esc(leagueName(t.league))} · ${ord(t.position)}</div><h2>${esc(t.name)}</h2>
    <p class="sub">${t.w}-${t.d}-${t.l} · form ${t.form} · ${t.home_ppg} points per game at home, ${t.away_ppg} away</p>
    <table>${Object.entries(S.meta.team_stats).map(([k, d]) => `<tr><td>${esc(d.label)}</td><td class="n"><b>${t.values[k]}</b></td><td class="n"><span class="chip ${rankChip(t.ranks[k])}">${ord(t.ranks[k])} of ${n}</span></td></tr>`).join('')}</table>
    <h3 style="margin-top:12px">Best rated</h3>${best.map(p => `<div class="row" style="justify-content:space-between;cursor:pointer" data-id="${p.id}"><span>${esc(p.name)} <span class="small">${p.role} · ${esc(p.archetype ? p.archetype.name : '')}</span></span><b>${fmt(p.values.rating, 'rating')}</b></div>`).join('')}
    <h3 style="margin-top:12px">Match by match</h3><canvas id="teamXg" height="150"></canvas>`;
  $('t-team').querySelectorAll('[data-id]').forEach(d => d.onclick = () => openPlayer(d.dataset.id));
  chart('teamXg', { type: 'bar', data: { labels: t.matches.map(m => `R${m.round} ${m.home ? 'v' : '@'} ${m.opp}`), datasets: [
    { label: 'xG for', data: t.matches.map(m => m.xgf), backgroundColor: C.green }, { label: 'xG against', data: t.matches.map(m => -m.xga), backgroundColor: C.red }] },
    options: { animation: false, scales: { x: { stacked: true, ticks: { display: false } }, y: { stacked: true } } } });
  const z = t.zones, lz = S.leagueZones[t.league];
  $('t-zones').innerHTML = z ? `<div class="row" style="justify-content:space-between"><h3>${esc(t.name)}: zones</h3><span class="small">season · attacking ↑ · differences v the ${esc(leagueName(t.league))} average</span></div>
    <div class="grid3">
      <div><div class="kicker">Where passes are played</div><canvas id="tz-bands" style="width:100%"></canvas></div>
      <div><div class="kicker">Final-third entries by lane (${z.entries_pm} per match)</div><canvas id="tz-lanes" style="width:100%"></canvas>
        ${barRows(PITCH.lane5Names, z.entries5_pct)}</div>
      <div><div class="kicker">Territory with the ball</div><canvas id="tz-terr" style="width:100%"></canvas>
        <div class="kicker" style="margin-top:6px">Possession by third</div>${barRows(['Defensive', 'Middle', 'Attacking'], z.poss_thirds_pct)}</div></div>
    <div class="grid2" style="margin-top:12px">
      <div><div class="kicker">Assist areas: scoring</div><canvas id="tz-af" style="width:100%"></canvas>${assistTypes(z.assist_types)}</div>
      <div><div class="kicker">Assist areas: conceding</div><canvas id="tz-ac" style="width:100%"></canvas>${assistTypes(z.conceded_assist_types)}</div></div>` : '';
  if (z) drawTeamZones(t, z, lz);
}
function drawTeamZones(t, z, lz) {
  const B = pitchCanvas($('tz-bands'), true); if (B) { drawPitch(B, { arrow: true }); drawBands(B, z.pass_bands_pct.map(v => Math.round(v * 10) / 10), lz && lz.pass_bands_pct); }
  const L = pitchCanvas($('tz-lanes'), true); if (L) { drawPitch(L, { arrow: true }); drawThirds(L); drawLaneColumns(L, z.entries5_pct, true, PITCH.cyanRGB); }
  const R = pitchCanvas($('tz-terr'), true); if (R) { drawPitch(R, { arrow: true }); drawGrid(R, z.territory_pct, { rgb: PITCH.homeRGB, gold: true }); }
  const A = pitchCanvas($('tz-af'), true); if (A) { drawPitch(A, { arrow: true }); drawAssistZones(A, S.meta.assist_zones, z.assist_areas, '46,139,62'); }
  const D = pitchCanvas($('tz-ac'), true); if (D) { drawPitch(D, { arrow: true }); drawAssistZones(D, S.meta.assist_zones, z.conceded_assist_areas, PITCH.awayRGB); }
}
function assistTypes(v) {
  const names = ['Short pass', 'Cross', 'Long ball', 'Corner', 'Free kick', 'Penalty', 'Individual'], mx = Math.max(...v);
  return `<div class="row small" style="margin-top:6px;gap:4px">${names.map((n, i) => `<span class="chip ${v[i] === mx && mx ? 'gold' : ''}">${n} ${v[i]}</span>`).join('')}</div>`;
}

/* ---------------- LEAGUES ---------------- */
const OUT_LABEL = { home_win: 'Home win', draw: 'Draw', away_win: 'Away win', over25: 'Over 2.5 goals', under25: 'Under 2.5 goals',
  btts: 'Both teams score', late_goal: "Goal after 80'", red_card: 'Red card', comeback: 'Team behind avoids defeat', clean_sheet: 'A clean sheet' };
const lgName = id => leagueName(id);
const lgDot = id => `<span class="ldot" style="background:${LEAGUE_COL[id]}"></span>`;
function rangeBar(maxv, parts) {  // parts: [{type:'ci'|'pt'|'lo'|'mk'|'ln', a, b, col}]
  const X = v => Math.max(0, Math.min(100, 100 * v / maxv));
  return `<div class="range">${parts.map(p => p.type === 'ci' ? `<div class="ci" style="left:${X(p.a)}%;width:${X(p.b) - X(p.a)}%"></div>`
    : p.type === 'ln' ? `<div class="ln" style="left:${X(Math.min(p.a, p.b))}%;width:${Math.abs(X(p.b) - X(p.a))}%;background:${p.col}"></div>`
    : `<div class="${p.type}" style="left:${X(p.a)}%" title="${esc(p.t || '')}"></div>`).join('')}
    <span class="tick" style="left:0%">0</span><span class="tick" style="left:50%">${Math.round(maxv / 2)}%</span><span class="tick" style="left:100%">${maxv}%</span></div>`;
}
function renderLeagues() {
  const I = S.insights, L = I.leagues, ids = S.meta.leagues.map(l => l.id);
  document.querySelectorAll('#lg-nav a').forEach(a => a.onclick = e => { e.preventDefault(); $(a.getAttribute('href').slice(1)).scrollIntoView({ behavior: 'smooth' }); });

  // 1 · most likely
  $('o-likely').innerHTML = I.most_likely.map(s => {
    const top = L[s.most].rates[s.outcome], low = L[s.least].rates[s.outcome], maxv = Math.min(100, Math.ceil((top.ci90[1] + 8) / 10) * 10);
    return `<div class="lrow"><span class="what">${esc(OUT_LABEL[s.outcome] || s.outcome)}</span>
      <span class="who"><span>${lgDot(s.most)}<b>${esc(lgName(s.most))}</b> · ${top.pct}%</span><small>least: ${esc(lgName(s.least))} · ${low.pct}%</small></span>
      ${rangeBar(maxv, [{ type: 'ci', a: top.ci90[0], b: top.ci90[1] }, { type: 'lo', a: low.pct, t: 'least likely league' }, { type: 'pt', a: top.pct, t: 'most likely league' }])}
      <span class="tagc ${s.separated ? 'clear' : 'lean'}">${s.separated ? 'clear' : 'lean'}</span></div>`;
  }).join('') + `<p class="small" style="margin:8px 0 0">● most likely league (band = its 90% range) · ○ least likely league. ${L[ids[0]].matches} matches per league.</p>`;

  // 2 · comparison table, grouped
  const groups = [['Per match', [['goals_pm', 'Goals'], ['yellows_pm', 'Yellow cards'], ['corners_pm', 'Corners']], false],
    ['Results', [['home_win', 'Home win'], ['draw', 'Draw'], ['away_win', 'Away win']], true],
    ['Goals', [['over25', 'Over 2.5 goals'], ['btts', 'Both teams score'], ['late_goal', "Goal after 80'"]], true],
    ['Game flow', [['red_card', 'Red card'], ['comeback', 'Team behind avoids defeat'], ['clean_sheet', 'A clean sheet']], true]];
  const cls = (vals, v) => v === Math.max(...vals) ? 'best' : v === Math.min(...vals) ? 'low' : '';
  $('o-table').innerHTML = `<table class="ltable"><tr><th></th>${ids.map(i => `<th class="n lgtop" style="border-top-color:${LEAGUE_COL[i]}">${esc(L[i].name)}</th>`).join('')}</tr>
    ${groups.map(([g, rows, rate]) => `<tr><td class="grp" colspan="${ids.length + 1}">${g}</td></tr>` + rows.map(([k, l]) => {
      const vals = ids.map(i => rate ? L[i].rates[k].pct : L[i][k]);
      return `<tr><td>${l}</td>${ids.map((i, j) => { const m = rate ? L[i].market_expected_pct[k] : null;
        return `<td class="n ${cls(vals, vals[j])}">${vals[j]}${rate ? '%' : ''}${m != null ? ` <span class="imp" title="market implied">${m}%</span>` : ''}</td>`; }).join('')}</tr>`; }).join('')).join('')}</table>
    <p class="small" style="margin:8px 0 0"><span class="chip gold">gold</span> highest of the four · <span class="chip cyan">blue</span> lowest</p>`;

  // 3 · results v prices
  $('o-gaps').innerHTML = I.market_gaps.slice(0, 8).map(g => {
    const r = L[g.league].rates[g.outcome], maxv = Math.min(100, Math.ceil((Math.max(r.ci90[1], g.market) + 8) / 10) * 10);
    const tone = g.outside_range ? 'watch' : g.diff > 0 ? 'up' : 'down';
    return `<div class="lrow"><span class="what">${esc(OUT_LABEL[g.outcome] || g.outcome)}</span>
      <span class="who"><span>${lgDot(g.league)}<b>${esc(lgName(g.league))}</b></span><small>happened ${g.actual}% · priced ${g.market}%</small></span>
      ${rangeBar(maxv, [{ type: 'ci', a: r.ci90[0], b: r.ci90[1] }, { type: 'ln', a: g.market, b: g.actual, col: g.diff > 0 ? '#0E9FB3' : '#D97706' }, { type: 'mk', a: g.market, t: 'market implied' }, { type: 'pt', a: g.actual, t: 'what happened' }])}
      <span class="tagc ${tone}">${g.diff > 0 ? '+' : ''}${g.diff} pts${g.outside_range ? ' · watch' : ''}</span></div>`;
  }).join('') + `<p class="small" style="margin:8px 0 0"><span class="tagc watch">watch</span> the price sits outside the 90% range of the results: a real-looking gap, still to be confirmed.</p>`;

  // 4 · model v market
  const e = I.evaluation, rowsE = ['all', ...ids].filter(k => e[k]);
  const maxLL = Math.max(...rowsE.flatMap(k => [e[k].market_log_loss, e[k].model_log_loss])), minLL = Math.min(...rowsE.flatMap(k => [e[k].market_log_loss, e[k].model_log_loss]));
  const w = v => 15 + 85 * (v - minLL + .02) / (maxLL - minLL + .02);
  $('o-eval').innerHTML = `<table class="ltable"><tr><th>League</th><th class="n">Matches</th><th class="n">Market log-loss</th><th class="n">Model log-loss</th><th class="n">Market favourite won</th><th class="n">Model favourite won</th></tr>
    ${rowsE.map(k => { const r = e[k], mk = r.market_log_loss <= r.model_log_loss;
      return `<tr><td>${k === 'all' ? '<b>All four</b>' : lgDot(k) + esc(lgName(k))}</td><td class="n">${r.n}</td><td class="n ${mk ? 'best' : ''}">${r.market_log_loss}</td><td class="n ${mk ? '' : 'best'}">${r.model_log_loss}</td>
        <td class="n ${r.market_top_pick_right >= r.model_top_pick_right ? 'best' : ''}">${r.market_top_pick_right}%</td><td class="n ${r.model_top_pick_right > r.market_top_pick_right ? 'best' : ''}">${r.model_top_pick_right}%</td></tr>`; }).join('')}</table>
    <div class="evalbars">${rowsE.map(k => `<span>${k === 'all' ? '<b>All four</b>' : esc(lgName(k))}</span><div class="b">
      <div style="width:${w(e[k].market_log_loss)}%;background:#4a463f" title="market ${e[k].market_log_loss}"></div>
      <div style="width:${w(e[k].model_log_loss)}%;background:#0E9FB3" title="model ${e[k].model_log_loss}"></div></div>`).join('')}</div>
    <p class="small" style="margin:6px 0 0"><span class="key market"></span> market &nbsp;<span class="key model"></span> model · shorter bar = better (lower log-loss); gold cells = the better of the two</p>
    <div class="verdict">${e.all.market_log_loss < e.all.model_log_loss ? '<b>The market prices better than the model</b>, as real closing lines do: its prices already hold what public models know. xV uses its model to explain how a match is moving, not to beat the market.' : 'The model edges the market here; with this many matches that can be luck.'}</div>`;

  // 5 · next round
  $('o-fixtures').innerHTML = S.meta.leagues.map(l => `<div class="lg-league" style="border-color:${LEAGUE_COL[l.id]};color:${LEAGUE_COL[l.id]}">${esc(l.name)} · round ${S.fixtures.find(f => f.league === l.id)?.round ?? ''}</div>` +
    S.fixtures.filter(f => f.league === l.id).map(f => { const gap = Math.max(...['home', 'draw', 'away'].map(o => Math.abs(f.model[o] - f.market[o])));
      return `<div class="fx"><div class="teams"><b>${esc(club(f.home).name)}</b> v <b>${esc(club(f.away).name)}</b> ${gap >= .05 ? `<span class="tagc watch" style="margin-left:6px">differ by ${Math.round(100 * gap)} pts</span>` : ''}
        <small>over 2.5: model ${pp(f.model.over25)}, market ${pp(f.market.over25)} · both score: model ${pp(f.model.btts)}, market ${pp(f.market.btts)}</small></div>
        <div class="bars"><span>Model</span>${tri(f.model, 'model')}<span>Market</span>${tri(f.market, 'market')}</div></div>`; }).join('')).join('');
}
function tri(p, kind) {
  const cols = kind === 'model' ? ['#0E9FB3', '#a8dbe2', '#0a6f7d'] : ['#3d3a34', '#b8b1a2', '#6b665c'];
  const seg = (v, c, dark) => `<div style="width:${100 * v}%;background:${c};color:${dark ? '#151412' : '#fff'}">${Math.round(100 * v)}</div>`;
  return `<div class="tri" title="${kind}: home / draw / away">${seg(p.home, cols[0])}${seg(p.draw, cols[1], true)}${seg(p.away, cols[2])}</div>`;
}

boot().catch(e => { document.querySelector('main').insertAdjacentHTML('afterbegin', `<div class="card">Could not load: ${esc(e.message)}</div>`); console.error(e); });
