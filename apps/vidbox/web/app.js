// VidBox — логіка сайту
'use strict';
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
const app = $('#app'), sheet = $('#sheet'), panel = $('.panel', sheet);
const S = {videos: [], by: {}, folders: [], ffmpeg: false, pending: 0, spritesPending: 0, N: 20, weekSec: 0, week: null, loaded: false, dirty: false,
  cfg: {autoplay_next: true, next_delay: 8, resume: true, ui: {sort: 'score', dir: 'desc', group: 'all'}}};
const RM = matchMedia('(prefers-reduced-motion: reduce)');
const FINE = matchMedia('(hover: hover) and (pointer: fine)');
const LS = {
  get(k, d) { try { const v = localStorage.getItem('vb_' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('vb_' + k, JSON.stringify(v)); } catch (e) {} }
};
const isLite = () => document.documentElement.classList.contains('lite');   // «Оптимізована версія» для слабких ПК
const view = {folder: LS.get('folder', ''), q: ''};   // сортування й вигляд бібліотеки зберігаються на ПК (S.cfg.ui)

// ── іконки ──
const svg = (d, cls) => `<svg class="i${cls ? ' ' + cls : ''}" viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const I = {
  play: svg('<path d="M7 4.5v15l12.5-7.5z"/>', 'solid'),
  info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.2"/>'),
  close: svg('<path d="M6 6l12 12M18 6 6 18"/>'),
  up: svg('<path d="M7.5 10.5v9.5h-3.5v-9.5zM7.5 10.5 11 3.5c1.4 0 2.5 1.1 2.5 2.5v3h5a2 2 0 0 1 2 2.3l-1.1 6.9a2 2 0 0 1-2 1.8H7.5"/>'),
  down: svg('<path d="M16.5 13.5V4H20v9.5zM16.5 13.5 13 20.5c-1.4 0-2.5-1.1-2.5-2.5v-3h-5a2 2 0 0 1-2-2.3l1.1-6.9a2 2 0 0 1 2-1.8h9.9"/>'),
  dice: svg('<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><circle cx="8.5" cy="8.5" r=".6"/><circle cx="15.5" cy="8.5" r=".6"/><circle cx="12" cy="12" r=".6"/><circle cx="8.5" cy="15.5" r=".6"/><circle cx="15.5" cy="15.5" r=".6"/>'),
  refresh: svg('<path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5"/>'),
  restart: svg('<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v5h5"/>'),
  left: svg('<path d="m15 18-6-6 6-6"/>'),
  right: svg('<path d="m9 18 6-6-6-6"/>'),
  next: svg('<path d="M5.5 5v14l10-7zM18.5 5v14"/>'),
  chev: svg('<path d="m6 9 6 6 6-6"/>'),
  star: svg('<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>'),
  arrDown: svg('<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>'),
  arrUp: svg('<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>'),
  grid: svg('<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>'),
  folder: svg('<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  trash: svg('<path d="M4.5 7h15M10 11v6M14 11v6M6 7l.9 11.2a2 2 0 0 0 2 1.8h6.2a2 2 0 0 0 2-1.8L18 7M9 7V4.5h6V7"/>'),
  rew: svg('<path d="M11 18 4.5 12 11 6zM19.5 18 13 12l6.5-6z"/>', 'solid'),
  ff: svg('<path d="M13 6l6.5 6-6.5 6zM4.5 6 11 12l-6.5 6z"/>', 'solid'),
  back10: svg('<path d="M4.6 13a7.5 7.5 0 1 0 2.1-6.4M4.5 3.8v4h4"/><text x="12.3" y="15.6" text-anchor="middle" font-size="7.2" font-weight="700" fill="currentColor" stroke="none" font-family="system-ui,sans-serif">10</text>'),
  fwd10: svg('<path d="M19.4 13a7.5 7.5 0 1 1-2.1-6.4M19.5 3.8v4h-4"/><text x="11.7" y="15.6" text-anchor="middle" font-size="7.2" font-weight="700" fill="currentColor" stroke="none" font-family="system-ui,sans-serif">10</text>'),
  pip: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><rect x="12" y="11.5" width="7" height="5.5" rx="1" fill="currentColor" stroke="none"/>'),
  film: svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/>'),
  chip: svg('<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>'),
  disk: svg('<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>'),
  queue: svg('<path d="M4 6h16M4 12h16M4 18h10"/>'),
  clock: svg('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
  list: svg('<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 5v2M4.5 11v2M4.5 17v2"/>'),
};

// ── утиліти ──
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
function fmtDur(s) {
  if (!s || !isFinite(s)) return '0:00';
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
}
function fmtLen(s) {
  if (!s) return '';
  const h = Math.floor(s / 3600), m = Math.round(s % 3600 / 60);
  return h ? `${h} год ${m} хв` : (m ? `${m} хв` : `${Math.round(s)} с`);
}
const fmtSize = b => !b ? '' : b >= 1099511627776 ? (b / 1099511627776).toFixed(2).replace('.', ',') + ' ТБ' : b >= 1073741824 ? (b / 1073741824).toFixed(1).replace('.', ',') + ' ГБ' : b >= 1048576 ? Math.round(b / 1048576) + ' МБ' : Math.max(1, Math.round(b / 1024)) + ' КБ';
const fmtDate = ts => ts ? new Date(ts * 1000).toLocaleDateString('uk-UA', {day: 'numeric', month: 'long', year: 'numeric'}) : '';
function ago(ts) {
  if (!ts) return 'ніколи';
  const d = (Date.now() / 1000 - ts) / 86400;
  if (d < 1 / 24) return 'щойно';
  if (d < 1) return Math.round(d * 24) + ' год тому';
  if (d < 2) return 'вчора';
  if (d < 30) return Math.round(d) + ' дн. тому';
  if (d < 365) return Math.round(d / 30) + ' міс. тому';
  return Math.round(d / 365) + ' р. тому';
}
const plural = (n, a, b, c) => { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? a : (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? b : c); };
const views = n => n + ' ' + plural(n, 'перегляд', 'перегляди', 'переглядів');
const byName = (a, b) => a.title.localeCompare(b.title, 'uk', {numeric: true});
const shortFolder = f => { const p = f.split('/'); return p.length > 1 ? p.slice(1).join(' / ') : f; };
const pct = x => Math.round((x || 0) * 100);
function resLabel(v) {
  const h = Math.min(v.w || 0, v.h || 0) || v.h;
  if (!h) return '';
  return h >= 2000 ? '4K' : h >= 1400 ? '1440p' : h >= 1000 ? '1080p' : h >= 700 ? '720p' : h >= 460 ? '480p' : h + 'p';
}
const hasSprite = v => v.sprite > 0 && v.dur > 0;
const frameT = (v, i) => v.dur * (0.03 + 0.94 * i / (S.N - 1));
const spriteUrl = v => `/sprite/${v.id}?v=${v.sprite}`;
const frameBg = (v, i) => `background-image:url(${spriteUrl(v)});background-size:${S.N * 100}% 100%;background-position:${i / (S.N - 1) * 100}% 0`;
const loadedImgs = new Set();
function preload(url, cb) {
  if (loadedImgs.has(url)) return cb();
  const im = new Image();
  im.onload = () => { loadedImgs.add(url); cb(); };
  im.src = url;
}

async function api(url, opt) {
  opt = opt || {};
  if (opt.body && !opt.headers) opt.headers = {'Content-Type': 'application/json'};
  const r = await fetch(url, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('auth'); }
  return r.json();
}
async function load() {
  const d = await api('/api/library');
  for (const v of d.videos) v._r = (S.by[v.id] && S.by[v.id]._r) || Math.random();
  S.videos = d.videos;
  S.by = Object.fromEntries(d.videos.map(v => [v.id, v]));
  Object.assign(S.by, S.animeBy || {});   // серії аніме живуть окремо, але плеєр шукає відео тут
  Object.assign(S, {folders: d.folders, ffmpeg: d.ffmpeg, pending: d.pending, spritesPending: d.spritesPending, N: d.spriteN || 20, weekSec: d.weekSec, loaded: true});
  if (d.cfg) {
    const localUi = S.cfg.ui;
    S.cfg = d.cfg;
    if (localUi && Date.now() - uiSavedAt < 5000) S.cfg.ui = localUi;   // щойно змінене сортування не перетираємо
    if (d.cfg.theme && d.cfg.theme !== document.documentElement.dataset.theme) applyTheme(d.cfg.theme);
  }
}
let toastT;
function toast(msg, btn, fn) {
  const t = $('#toast');
  t.innerHTML = `<div class="dn"><b>vidbox</b>${esc(msg)}</div>` + (btn ? '<button>' + esc(btn) + '</button>' : '');
  if (btn) t.querySelector('button').onclick = () => { fn(); t.classList.remove('show'); };
  t.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove('show'), btn ? 6000 : 2600);
}

// ── теми, атмосфера, годинник ──
// Щоб додати тему: блок змінних у style.css + запис тут + назва в THEMES у vidbox.py.
const THEMES = [
  {id: 'arch', name: 'Arch', hint: 'Фірмовий синій Arch Linux', bg: '#0c0f14', p: '#141922', a: '#1793d1', a2: '#56c5f2'},
  {id: 'tokyo', name: 'Tokyo Night', hint: 'Нічне місто, синій з бузковим', bg: '#16161e', p: '#1a1b26', a: '#7aa2f7', a2: '#bb9af7'},
  {id: 'catppuccin', name: 'Catppuccin', hint: 'Mocha: м’які пастельні кольори', bg: '#11111b', p: '#1e1e2e', a: '#cba6f7', a2: '#89b4fa'},
  {id: 'dracula', name: 'Dracula', hint: 'Класика: фіолетовий і рожевий', bg: '#1e1f29', p: '#282a36', a: '#bd93f9', a2: '#ff79c6'},
  {id: 'gruvbox', name: 'Gruvbox', hint: 'Теплий ретро-помаранчевий', bg: '#1d2021', p: '#282828', a: '#fe8019', a2: '#b8bb26'},
  {id: 'cinema', name: 'Cinema', hint: 'Глибокий синій, як зал кінотеатру', bg: '#070b14', p: '#0e1524', a: '#2ea8ff', a2: '#8a6bff'},
  {id: 'nord', name: 'Nord', hint: 'Спокійний сіро-блакитний', bg: '#21262f', p: '#2b313c', a: '#88c0d0', a2: '#b48ead'},
  {id: 'sweet', name: 'Sweet', hint: 'Неоновий рожевий і бірюза', bg: '#100e1a', p: '#1a1729', a: '#ff4fd8', a2: '#38d9f5'},
  {id: 'exodia', name: 'Exodia', hint: 'Фіолетовий з кислотно-зеленим', bg: '#09060f', p: '#130e1e', a: '#b56bff', a2: '#46f59a'},
  {id: 'projector', name: 'Проєктор', hint: 'Тепле бурштинове світло', bg: '#0f1420', p: '#161d2b', a: '#f2b544', a2: '#ff7a59'},
];
function applyTheme(id) {
  const t = THEMES.find(x => x.id === id) || THEMES[0];
  document.documentElement.dataset.theme = t.id;
  LS.set('theme', t.id);
  const m = $('meta[name=theme-color]');
  if (m) m.content = t.bg;
  const fav = $('#favicon');   // значок вкладки «▶_» у кольорах теми
  if (fav) fav.href = 'data:image/svg+xml,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="${t.p}"/>` +
    `<rect x="2" y="2" width="60" height="60" rx="12" fill="none" stroke="${t.a}" stroke-opacity=".55" stroke-width="3"/><path d="M13 15v34l25-17z" fill="${t.a}"/><rect x="40" y="43" width="13" height="5" rx="1.5" fill="${t.a2}"/></svg>`);
}
let atmoUrl = '';
function setAtmo(v) {
  // розмитий кадр поточного відео як «шпалери» під усім сайтом
  const url = !v ? '' : v.thumb ? `/thumb/${v.id}?v=${v.thumb}` : hasSprite(v) ? hdUrl(v, 6) : '';
  if (url === atmoUrl) return;
  atmoUrl = url;
  $('#atmo').style.backgroundImage = url ? `url(${url})` : '';
}
// вікно як у тайловому менеджері та рядок промпту як у bash на Arch
const winBar = (title, extra) => `<header class="win-bar"><span class="dots"><i></i><i></i><i></i></span><span class="win-t">${title}</span>${extra || ''}</header>`;
const promptLine = (path, cmd, id) => `<p class="prompt"${id ? ` id="${id}"` : ''} aria-hidden="true"><span class="u">[vidbox@${esc(S.host || 'pc')}</span> <span class="p">${esc(path)}</span><span class="u">]$</span> <span class="c">${esc(cmd)}</span><i class="cur"></i></p>`;

// модулі верхньої панелі (як у polybar): відео, фонові задачі, відеокарта, вільне місце
let statusT = 0, statusFast = false;
async function pollStatus() {
  clearTimeout(statusT);
  if (!document.hidden) {
    try { const st = await api('/api/status'); S.host = st.host; renderMods(st); } catch (e) {}
  }
  statusT = setTimeout(pollStatus, statusFast ? 2000 : 6000);
}
function renderMods(st) {
  const m = [`<span class="mod lib" title="Відео в бібліотеці">${I.film}${st.videos}</span>`];
  if (st.conv) m.push(`<span class="mod act" title="Конвертую «${esc(st.conv.title)}»">${I.refresh}${esc(st.conv.enc || '')} ${Math.round(st.conv.progress * 100)}%${st.conv.fps ? ` <em>${st.conv.fps} к/с</em>` : ''}</span>`);
  else if (st.probe || st.sprites) m.push(`<span class="mod act" title="Готую обкладинки й нарізки кадрів у фоні">${I.refresh}кадри ${st.probe + st.sprites}</span>`);
  if (st.queue) m.push(`<span class="mod" title="Відео в черзі на конвертацію">${I.queue}${st.queue}</span>`);
  m.push(`<span class="mod hw" title="${esc(st.gpu || 'Відеокарта')}${st.hardware ? '' : ' (кодує процесор)'}">${I.chip}${st.hwChecked ? esc(st.enc) : '…'}</span>`);
  if (st.disk) m.push(`<span class="mod disk" title="Вільно на ${st.disk.count > 1 ? `${st.disk.count} дисках` : 'диску'} з відео: ${fmtSize(st.disk.free)} з ${fmtSize(st.disk.total)}">${I.disk}${fmtSize(st.disk.free)}</span>`);
  $('#mods').innerHTML = m.join('');
  fitBar();
  statusFast = !!(st.conv || st.queue);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) pollStatus(); });
// клавіатура як у тайловому WM: 1–5 робочі столи, / пошук, R випадкове
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
  const t = e.target;
  if (t.closest && t.closest('input, textarea, select, [contenteditable]')) { if (e.key === 'Escape' && t.id === 'q') t.blur(); return; }
  if (sheetId || !picker.hidden) return;
  const onPlayer = (baseHash || '').startsWith('/v/');
  if (e.key === '/' || e.code === 'Slash') { e.preventDefault(); $('#q').focus(); return; }
  if (onPlayer) return;
  if (/^Digit[1-6]$/.test(e.code)) { e.preventDefault(); go(['#/', '#/lib', '#/anime', '#/pl', '#/top', '#/settings'][+e.code.slice(5) - 1]); }
  else if (e.code === 'KeyR') { e.preventDefault(); randomVideo(false); }
});

function tick() {
  const d = new Date(), el = $('#clock');
  if (el) el.innerHTML = `<span class="d">${esc(d.toLocaleDateString('uk-UA', {weekday: 'short', day: 'numeric', month: 'short'}))}&nbsp;</span><b>${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}</b>`;
  fitBar();
}

// Верхній рядок завжди в один рядок і без обрізання: якщо не влазить (вузьке вікно, довгий статус, інші шрифти
// на Mac), ховаємо менш важливе по черзі — дату, лічильник і диск, підписи розділів, увесь статус.
function fitBar() {
  const bar = document.querySelector('.bar');
  if (!bar) return;
  const steps = ['f1', 'f2', 'f3', 'f4'];
  bar.classList.remove(...steps);
  for (const c of steps) {
    if (bar.scrollWidth <= bar.clientWidth + 1) break;
    bar.classList.add(c);
  }
}
addEventListener('resize', () => requestAnimationFrame(fitBar));
tick();
setInterval(tick, 15000);
applyTheme(document.documentElement.dataset.theme || 'arch');

// ── обкладинки й картки ──
function hue(id) { return parseInt(id.slice(0, 4), 16) % 360; }
function cover(v) {
  if (v.thumb) return `<img loading="${isLite() ? 'eager' : 'lazy'}" decoding="async" src="/thumb/${v.id}?v=${v.thumb}" alt="">`;
  if (hasSprite(v)) return `<div class="fill" style="${frameBg(v, 3)}"></div>`;
  return `<div class="ph" data-ph="${v.id}" style="--h:${hue(v.id)}"><span>${esc((v.title.trim()[0] || '?').toUpperCase())}</span></div>`;
}
function card(v, o) {
  o = o || {};
  const pr = v.pos && v.dur ? Math.min(100, v.pos / v.dur * 100) : 0;
  const meta = o.meta || [shortFolder(v.folder), v.views ? views(v.views) : ''];
  return `<a class="card" href="#/i/${v.id}"><div class="th" data-scrub="${v.id}">${cover(v)}` +
    (o.rank ? `<span class="rk">${o.rank}</span>` : '') +
    (v.views || v.vote ? `<span class="sc${v.score >= 70 ? ' hi' : ''}">${I.star}${Math.round(v.score)}</span>` : '') +
    (v.prep && !v.ready ? `<span class="fmt">${esc(v.ext.toUpperCase())}</span>` : '') +
    (v.dur && !o.rank ? `<span class="dur">${fmtDur(v.dur)}</span>` : '') +
    (pr > 1 ? `<span class="pbar"><i style="width:${pr}%"></i></span>` : '') +
    `</div><div class="ct">${esc(v.title)}</div><div class="cm">${meta.filter(Boolean).map(m => `<span>${esc(m)}</span>`).join('')}</div></a>`;
}
let shelfN = 0;
function shelf(title, sub, items, o) {
  o = o || {};
  if (!items.length) return '';
  const id = 'r' + (++shelfN);
  const H = o.small ? 'h3' : 'h2';
  return `<section class="shelf"><header><div><${H}>${esc(title)}</${H}>${sub ? `<p>${esc(sub)}</p>` : ''}</div>` +
    `<div class="arrows"><button class="btn icon ghost" data-scroll="${id}" data-dir="-1" aria-label="Гортати назад">${I.left}</button>` +
    `<button class="btn icon ghost" data-scroll="${id}" data-dir="1" aria-label="Гортати вперед">${I.right}</button></div></header>` +
    `<div class="row" id="${id}">${items.map((v, i) => card(v, {meta: o.meta ? o.meta(v) : null, rank: o.ranked ? i + 1 : 0})).join('')}</div></section>`;
}
function metaHTML(v, full) {
  const parts = [];
  if (v.dur) parts.push(`<span>${fmtLen(v.dur)}</span>`);
  if (resLabel(v)) parts.push(`<span>${resLabel(v)}</span>`);
  parts.push(`<span>${esc(v.ext.toUpperCase())}</span>`);
  if (full && v.size) parts.push(`<span>${fmtSize(v.size)}</span>`);
  if (v.views || v.vote) parts.push(`<span>Рейтинг <b>${Math.round(v.score)}</b></span>`);
  return parts.join('');
}

// ── наведення на картку: кадри біжать за курсором ──
let scrubEl = null;
function scrubClear() {
  if (!scrubEl) return;
  const o = scrubEl.querySelector('.scrub');
  if (o) o.remove();
  scrubEl = null;
}
document.addEventListener('mousemove', e => {
  if (!FINE.matches || isLite()) return;
  const th = e.target.closest ? e.target.closest('[data-scrub]') : null;
  if (th !== scrubEl) scrubClear();
  if (!th) return;
  const v = S.by[th.dataset.scrub];
  if (!v || !hasSprite(v)) return;
  scrubEl = th;
  let o = th.querySelector('.scrub');
  if (!o) {
    o = document.createElement('div');
    o.className = 'scrub';
    o.innerHTML = '<i></i><b></b>';
    th.appendChild(o);
    preload(spriteUrl(v), () => o.classList.add('ready'));
  }
  const r = th.getBoundingClientRect();
  const i = Math.floor(Math.min(.999, Math.max(0, (e.clientX - r.left) / r.width)) * S.N);
  if (o._i === i) return;
  o._i = i;
  o.style.cssText = frameBg(v, i);
  o.firstChild.style.width = ((i + 1) / S.N * 100) + '%';
  o.lastChild.textContent = fmtDur(frameT(v, i));
}, {passive: true});
document.addEventListener('mouseleave', scrubClear);

// ── переглядач кадрів (герой і вікно з інфою) ──
function frameViewer(screen, v, strip, onPick) {
  const layers = $$('.fr', screen), tc = $('.tc', screen);
  let i = -1, cur = 0, timer = null, hold = false, dead = false, hdT = null;
  function show(n) {
    n = (n + S.N) % S.N;
    if (n === i) return;
    i = n;
    const nx = layers[1 - cur], want = n;
    // спершу кадр з нарізки (миттєво), потім чіткий великий кадр, якщо курсор на ньому затримався
    nx.style.cssText = loadedImgs.has(hdUrl(v, want)) ? hdBg(v, want) : frameBg(v, want);
    clearTimeout(hdT);
    hdT = setTimeout(() => preload(hdUrl(v, want), () => {
      if (dead || i !== want) return;
      nx.style.cssText = hdBg(v, want);
      if (!hold) preload(hdUrl(v, (want + 1) % S.N), () => {});
    }), hold ? 220 : 0);
    nx.classList.add('on');
    layers[cur].classList.remove('on');
    cur = 1 - cur;
    if (tc) tc.textContent = fmtDur(frameT(v, i));
    if (strip) { $$('.on', strip).forEach(b => b.classList.remove('on')); const b = strip.querySelector(`[data-i="${i}"]`); if (b) b.classList.add('on'); }
  }
  const pos = e => { const r = screen.getBoundingClientRect(); return Math.floor(Math.min(.999, Math.max(0, (e.clientX - r.left) / r.width)) * S.N); };
  preload(spriteUrl(v), () => {
    if (dead) return;
    show(0);
    if (!RM.matches) timer = setInterval(() => { if (!hold && !document.hidden) show(i + 1); }, 1800);
  });
  screen.addEventListener('mousemove', e => { if (!FINE.matches) return; hold = true; screen.classList.add('live'); show(pos(e)); });
  screen.addEventListener('mouseleave', () => { hold = false; screen.classList.remove('live'); });
  if (strip) {
    strip.addEventListener('mouseover', e => { const b = e.target.closest('[data-i]'); if (b && FINE.matches) { hold = true; show(+b.dataset.i); } });
    strip.addEventListener('mouseleave', () => { hold = false; });
    strip.addEventListener('click', e => { const b = e.target.closest('[data-i]'); if (b) onPick(+b.dataset.i); });
  }
  return {stop() { dead = true; clearInterval(timer); clearTimeout(hdT); }};
}
const screenLayers = '<div class="fr"></div><div class="fr"></div><span class="tc"></span>';
const hdUrl = (v, i) => `/frame/${v.id}/${i}?v=${v.sprite}`;
const hdBg = (v, i) => `background-image:url(${hdUrl(v, i)});background-size:contain;background-repeat:no-repeat;background-position:center;background-color:#000`;

// ── навігація ──
// Посилання всередині сайту йдуть через pushState: так «Назад» і «Закрити» поводяться як у звичайному сайті.
let baseHash = null, listBase = '/', cleanup = null, sheetId = null, sheetRnd = false, sheetViewer = null;
const scrolls = {};
function go(href, replace) {
  const h = href.replace(/^#/, '');
  const isSheet = h.startsWith('/i/');
  const st = history.state || {};
  const steps = isSheet ? (replace ? (st.sheetSteps || 0) : (sheetId ? (st.sheetSteps || 0) + 1 : 1)) : 0;
  if (replace) history.replaceState({sheetSteps: steps}, '', '#' + h);
  else history.pushState({sheetSteps: steps}, '', '#' + h);
  route();
}
document.addEventListener('click', e => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  const a = e.target.closest('a[href^="#/"]');
  if (a) { e.preventDefault(); go(a.getAttribute('href')); return; }
  const sc = e.target.closest('[data-scroll]');
  if (sc) { const row = document.getElementById(sc.dataset.scroll); row.scrollBy({left: row.clientWidth * 0.9 * +sc.dataset.dir, behavior: 'smooth'}); return; }
  if (e.target.closest('[data-random]')) { e.preventDefault(); randomVideo(false); return; }
  if (e.target.closest('[data-close]')) { e.preventDefault(); closeSheet(); }
});
window.addEventListener('popstate', route);
window.addEventListener('hashchange', route);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (!picker.hidden) closePicker();
  else if (sheetId) closeSheet();
});

let routing = Promise.resolve();
function route() { routing = routing.then(doRoute, doRoute); return routing; }
async function doRoute() {
  const h = location.hash.slice(1) || '/';
  const parts = h.split('/').filter(Boolean);
  if (parts[0] === 'i') {
    // під вікном з інфою завжди сторінка зі списком, а не плеєр (щоб відео не грало на фоні)
    if (baseHash == null || baseHash.startsWith('/v/')) await renderBase(listBase);
    const rnd = parts[2] === 'r';
    if (sheetId !== parts[1] || sheetRnd !== rnd) await openSheet(parts[1], rnd);
    return;
  }
  if (sheetId) hideSheet();
  if (h !== baseHash) await renderBase(h);
  else if (S.dirty) { S.dirty = false; await renderBase(h, true); }
}
async function renderBase(h, keep) {
  if (cleanup) { try { cleanup(); } catch (e) {} cleanup = null; }
  if (baseHash != null) scrolls[baseHash] = window.scrollY;
  baseHash = h;
  const parts = h.split('/').filter(Boolean);
  if (parts[0] !== 'v') listBase = h;
  const tab = parts[0] === 'v' ? '' : (parts[0] || 'home');
  $$('[data-tab]').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
  shelfN = 0;
  try {
    if (parts[0] === 'v') await renderPlayer(parts[1], parts[2] != null ? +parts[2] : null);
    else if (parts[0] === 'lib') await renderLib();
    else if (parts[0] === 'top') await renderTop();
    else if (parts[0] === 'anime') await (parts[1] ? renderAnimeTitle(parts[1]) : renderAnime());
    else if (parts[0] === 'pl') await (parts[1] ? renderPlaylist(parts[1]) : renderPlaylists());
    else if (parts[0] === 'settings') await renderSettings();
    else await renderHome();
  } catch (e) {
    console.error(e);
    if (e.message !== 'auth') app.innerHTML = `<div class="empty"><h1 class="title">Немає зв'язку з комп'ютером</h1>Перевір, що VidBox запущений і телефон у тій самій Wi-Fi мережі.<br><br><button class="btn" onclick="location.reload()">Спробувати знову</button></div>`;
    return;
  }
  if (parts[0] !== 'v') window.scrollTo(0, scrolls[h] || 0);
}

// ── випадкове відео ──
function randomVideo(replace) {
  const pool = S.videos.filter(v => v.vote >= 0 && v.id !== sheetId);
  if (!pool.length) return toast('Бібліотека порожня');
  const w = pool.map(v => (v.views ? 1 : 3) * (v.vote > 0 ? 1.5 : 1));
  let r = Math.random() * w.reduce((a, b) => a + b, 0), pick = pool[pool.length - 1];
  for (let k = 0; k < pool.length; k++) { r -= w[k]; if (r <= 0) { pick = pool[k]; break; } }
  go('#/i/' + pick.id + '/r', replace);
}

// ── Головна ──
function weekRange(w) {
  const a = new Date(w.start + 'T12:00:00'), b = new Date(w.end + 'T12:00:00');
  const mon = d => d.toLocaleDateString('uk-UA', {day: 'numeric', month: 'long'});
  return a.getMonth() === b.getMonth() ? `${a.getDate()}–${mon(b)}` : `${mon(a)} – ${mon(b)}`;
}
// Прожектор: відео тижня + решта підбірки, гортаються самі кожні 8 секунд
function spotList(week) {
  const ids = [week.hero].concat(...week.sections.map(s => s.ids));
  return ids.filter((id, i) => id && ids.indexOf(id) === i && S.by[id]).slice(0, 6).map(id => S.by[id]);
}
function spotBg(v) {
  if (hasSprite(v)) return `background-image:url(${hdUrl(v, 6)})`;
  if (v.thumb) return `background-image:url(/thumb/${v.id}?v=${v.thumb})`;
  return `background-image:linear-gradient(135deg,hsl(${hue(v.id)} 35% 24%),transparent)`;
}
function cardBg(v) {
  if (v.thumb) return `background-image:url(/thumb/${v.id}?v=${v.thumb})`;
  return hasSprite(v) ? frameBg(v, 3) : `background-image:linear-gradient(135deg,hsl(${hue(v.id)} 35% 26%),hsl(${(hue(v.id) + 50) % 360} 35% 12%))`;
}
function spotDesc(v) {
  const where = `З папки «${shortFolder(v.folder)}».`;
  if (S.cfg.resume && v.pos > 15 && v.dur && v.pos < v.dur * 0.95) return `${where} Ти зупинився на ${fmtDur(v.pos)}, залишилось ${fmtLen(v.dur - v.pos)}.`;
  if (v.views) return `${where} Переглянуто ${v.views} ${plural(v.views, 'раз', 'рази', 'разів')}, востаннє ${ago(v.last)}. Рейтинг ${Math.round(v.score)} зі 100.`;
  return `${where} Ти його ще не дивився, додано ${ago(v.added)}.`;
}
function spotCopy(v, i) {
  const resume = S.cfg.resume && v.pos > 15 && v.dur && v.pos < v.dur * 0.95;
  const rated = v.views || v.vote;
  const chips = [v.dur ? `<span>${fmtLen(v.dur)}</span>` : '', resLabel(v) ? `<span>${resLabel(v)}</span>` : '', `<span>${esc(v.ext.toUpperCase())}</span>`,
    rated ? `<span${v.score >= 70 ? ' class="hl"' : ''}>★ ${Math.round(v.score)}</span>` : '<span class="hl">нове для тебе</span>'].join('');
  return `<div class="spot-copy" id="spotCopy"><p class="spot-kicker">#${i + 1} ${i ? 'у підбірці тижня' : 'відео тижня'}</p>
    <h1 class="spot-title">${esc(v.title)}</h1><div class="chipset">${chips}</div><p class="spot-desc">${esc(spotDesc(v))}</p>
    <div class="acts"><a class="btn primary" href="#/v/${v.id}">${I.play}${resume ? 'Продовжити' : 'Дивитися'}</a><a class="btn" href="#/i/${v.id}">${I.info}Детальніше</a></div></div>`;
}
function spotHTML(list) {
  const many = list.length > 1, nn = k => String(k).padStart(2, '0');
  return `<section class="spot" id="spot" aria-label="Підбірка тижня">
    ${list.map((v, i) => `<div class="spot-bg${i ? '' : ' on'}" style="${spotBg(v)}"></div>`).join('')}<div class="spot-shade"></div>
    <div class="spot-body">${spotCopy(list[0], 0)}
      ${many ? `<div class="spot-side"><p>У підбірці тижня</p><div class="spot-cards" id="spotCards">${list.map((v, i) =>
        `<button class="spot-card${i ? '' : ' on'}" data-i="${i}" style="${cardBg(v)}" aria-label="${esc(v.title)}"><small class="n">${nn(i + 1)}</small><span>${esc(v.title)}</span></button>`).join('')}</div></div>` : ''}
    </div>
    ${many ? `<div class="spot-nav"><button class="btn icon round" data-spot="-1" aria-label="Попереднє відео">${I.left}</button><span class="count"><b id="spotN">01</b> / ${nn(list.length)}</span>` +
      `<button class="btn icon round" data-spot="1" aria-label="Наступне відео">${I.right}</button></div><div class="spot-timer"><b id="spotT"></b></div>` : ''}
  </section>`;
}
function mountSpot(list) {
  const root = $('#spot');
  if (!root) return;
  setAtmo(list[0]);
  if (list.length < 2) return;
  const bar = $('#spotT'), cards = $('#spotCards');
  let i = 0;
  function goTo(n) {
    i = (n + list.length) % list.length;
    $$('.spot-bg', root).forEach((el, k) => el.classList.toggle('on', k === i));
    $$('.spot-card', root).forEach((el, k) => el.classList.toggle('on', k === i));
    const c = cards.children[i];
    if (c.offsetLeft < cards.scrollLeft || c.offsetLeft + c.offsetWidth > cards.scrollLeft + cards.clientWidth) cards.scrollTo({left: c.offsetLeft - 4, behavior: 'smooth'});
    const tmp = document.createElement('div');
    tmp.innerHTML = spotCopy(list[i], i);
    $('#spotCopy').replaceWith(tmp.firstElementChild);
    $('#spotN').textContent = String(i + 1).padStart(2, '0');
    setAtmo(list[i]);
    restart();
  }
  function restart() {
    if (RM.matches || isLite()) return;
    bar.classList.remove('run');
    void bar.offsetWidth;
    bar.classList.add('run');
  }
  bar.addEventListener('animationend', () => goTo(i + 1));   // смужка внизу добігла — наступне
  root.addEventListener('mouseenter', () => root.classList.add('hold'));
  root.addEventListener('mouseleave', () => root.classList.remove('hold'));
  root.addEventListener('focusin', () => root.classList.add('hold'));
  root.addEventListener('focusout', () => root.classList.remove('hold'));
  root.addEventListener('click', e => {
    const s = e.target.closest('[data-spot]');
    if (s) return goTo(i + +s.dataset.spot);
    const c = e.target.closest('.spot-card');
    if (c) goTo(+c.dataset.i);
  });
  let sx = null;   // свайп по банеру на телефоні
  root.addEventListener('pointerdown', e => { sx = e.pointerType === 'touch' && !e.target.closest('.spot-cards') ? e.clientX : null; });
  root.addEventListener('pointerup', e => { if (sx != null && Math.abs(e.clientX - sx) > 60) goTo(i + (e.clientX < sx ? 1 : -1)); sx = null; });
  restart();
}
async function renderHome() {
  const [, week] = await Promise.all([load(), api('/api/week')]);
  S.week = week;
  const vs = S.videos;
  if (!vs.length) {
    setAtmo(null);
    app.innerHTML = `<div class="empty"><h1 class="title">Тут поки порожньо</h1>VidBox не знайшов відео у вибраних папках. Підходять mp4, mkv, webm, mov, avi та інші.<br><br>` +
      `<a class="btn primary" href="#/settings">${I.folder}Додати папку</a> <button class="btn" id="rs">${I.refresh}Пересканувати</button></div>`;
    $('#rs').onclick = rescan;
    return;
  }
  const list = spotList(week);
  let html = promptLine('~', `vidbox --week ${week.week}`) + (list.length ? spotHTML(list) : '');
  const cont = vs.filter(v => S.cfg.resume && v.pos > 15 && v.dur && v.pos < v.dur * 0.95).sort((a, b) => b.posAt - a.posAt).slice(0, 12);
  html += shelf('Продовжити перегляд', '', cont, {meta: v => [shortFolder(v.folder), 'ще ' + fmtLen(v.dur - v.pos)]});
  html += `<section class="shelf"><header><div><h2>Плейлисти</h2><p>Збираються самі за тривалістю</p></div><a class="btn ghost" style="margin-left:auto" href="#/pl">${I.list}Усі</a></header>` +
    `<div class="plgrid home">${LEN_GROUPS.map(plCard).join('')}</div></section>`;
  const weekShelves = week.sections.map(s => shelf(s.title, s.sub, s.ids.map(i => S.by[i]).filter(Boolean), {small: true})).join('');
  html += `<section class="week win">${winBar(`~/підбірка-тижня/<b>${esc(week.week)}</b>`)}<div class="win-body"><div class="week-head"><h2 class="title">Підбірка тижня</h2><span class="dates">${weekRange(week)}</span>` +
    `<button class="btn ghost" id="wkr" aria-label="Зібрати іншу підбірку">${I.refresh}<span>Зібрати іншу</span></button></div>${weekShelves}</div></section>`;
  const best = vs.filter(v => v.views).sort((a, b) => b.score - a.score).slice(0, 10);
  if (best.length >= 3) html += shelf('Найкраще за рейтингом', 'Десятка, яку ти дивишся найохочіше', best, {ranked: true});
  html += shelf('Нещодавно додані', '', [...vs].sort((a, b) => b.added - a.added).slice(0, 14), {meta: v => [shortFolder(v.folder), ago(v.added)]});
  let foot = `У бібліотеці ${vs.length} відео. Цього тижня переглянуто ${fmtLen(S.weekSec) || '0 хв'}.`;
  if (S.spritesPending) foot += ` Нарізки кадрів ще готуються у фоні: залишилось ${S.spritesPending}.`;
  else if (!S.ffmpeg) foot += ' Щоб з’явились нарізки кадрів, поклади ffmpeg.exe поруч з vidbox.py.';
  html += `<p class="foot">${esc(foot)}</p>`;
  app.innerHTML = html;
  $('#wkr').onclick = async () => {
    S.week = await api('/api/week/refresh', {method: 'POST'});
    await renderBase(baseHash, true);
    toast('Зібрав нову підбірку');
  };
  mountSpot(list);
  wirePl(app);
}

// ── Бібліотека ──
// Кожне сортування має напрямок; підписи напрямку залежать від того, що сортуємо.
const SORTS = {
  score:  {label: 'Рейтинг', desc: 'Спершу найвищий', asc: 'Спершу найнижчий', key: v => v.score},
  added:  {label: 'Дата додавання', desc: 'Спершу нові', asc: 'Спершу старі', key: v => v.added || 0},
  name:   {label: 'Назва', asc: 'Від А до Я', desc: 'Від Я до А', cmp: byName, first: 'asc'},
  size:   {label: 'Розмір файлу', desc: 'Від більшого', asc: 'Від меншого', key: v => v.size || 0},
  dur:    {label: 'Тривалість', desc: 'Спершу довші', asc: 'Спершу коротші', key: v => v.dur || 0},
  res:    {label: 'Роздільність', desc: 'Спершу вища', asc: 'Спершу нижча', key: v => Math.min(v.w || 0, v.h || 0) || v.h || 0},
  views:  {label: 'Кількість переглядів', desc: 'Спершу найчастіші', asc: 'Спершу найрідші', key: v => v.views},
  last:   {label: 'Останній перегляд', desc: 'Спершу нещодавні', asc: 'Спершу давно не бачені', key: v => v.last || 0},
  folder: {label: 'Папка', asc: 'Від А до Я', desc: 'Від Я до А', first: 'asc',
           cmp: (a, b) => a.folder.localeCompare(b.folder, 'uk', {numeric: true}) || byName(a, b)},
  random: {label: 'Випадково', key: v => v._r},
};
function sorter(k, dir) {
  const s = SORTS[k] || SORTS.score, m = dir === 'asc' ? 1 : -1;
  const base = s.cmp || ((a, b) => s.key(a) - s.key(b));
  return (a, b) => m * base(a, b) || byName(a, b);
}
const ui = () => S.cfg.ui;
let uiSavedAt = 0;
function saveUi() {
  uiSavedAt = Date.now();
  api('/api/settings', {method: 'POST', body: JSON.stringify({ui: S.cfg.ui})}).then(() => { uiSavedAt = Date.now(); }).catch(() => {});
}
function filtered() {
  let vs = S.videos;
  if (view.folder) vs = vs.filter(v => v.folder === view.folder || v.folder.startsWith(view.folder + '/'));
  if (view.q) {
    const words = view.q.toLowerCase().split(/\s+/).filter(Boolean);
    vs = vs.filter(v => { const t = (v.title + ' ' + v.folder + ' ' + v.file).toLowerCase(); return words.every(w => t.includes(w)); });
  }
  return [...vs].sort(sorter(ui().sort, ui().dir));
}
function libMeta(v, grouped) {
  const k = ui().sort;
  const extra = k === 'size' ? fmtSize(v.size) : k === 'res' ? resLabel(v) : k === 'dur' ? fmtLen(v.dur)
    : k === 'added' ? 'додано ' + ago(v.added) : k === 'last' ? (v.last ? 'дивився ' + ago(v.last) : 'ще не дивився')
    : (v.views ? views(v.views) : (grouped ? fmtSize(v.size) : ''));
  return [grouped ? '' : shortFolder(v.folder), extra];
}
function libCmd() {
  const u = ui();
  return 'ls --sort=' + u.sort + (u.dir === 'asc' && u.sort !== 'random' ? ' --reverse' : '') + (u.group === 'folders' ? ' --group=folder' : u.group === 'duration' ? ' --group=length' : '') +
    (view.folder ? ` "${shortFolder(view.folder)}"` : '') + (view.q ? ` | grep -i "${view.q}"` : '');
}
function drawDir() {
  const u = ui(), s = SORTS[u.sort] || SORTS.score, b = $('#dir');
  b.innerHTML = u.sort === 'random' ? I.dice + '<span>Перемішати</span>' : (u.dir === 'asc' ? I.arrUp : I.arrDown) + `<span>${esc(s[u.dir])}</span>`;
  b.setAttribute('aria-label', u.sort === 'random' ? 'Перемішати ще раз' : 'Напрямок сортування: ' + s[u.dir]);
}
function drawGrid() {
  const vs = filtered(), g = $('#grid'), u = ui();
  $('#cnt').textContent = vs.length + ' відео';
  const pr = $('#libPrompt');
  if (pr) pr.outerHTML = promptLine('~/бібліотека', libCmd(), 'libPrompt');
  if (!vs.length) {
    g.className = 'grid';
    g.innerHTML = `<div class="empty" style="grid-column:1/-1">${view.q ? `Нічого не знайшлося за запитом «${esc(view.q)}». Спробуй інше слово або обери «Усі» папки.` : 'У цій папці немає відео.'}</div>`;
    return;
  }
  if (u.group !== 'folders' && u.group !== 'duration') {
    g.className = 'grid';
    g.innerHTML = vs.map(v => card(v, {meta: libMeta(v, false)})).join('');
    return;
  }
  // групи: «По папках» — кожна папка окремо; «За тривалістю» — до 20 хв, до години, понад годину
  let groups;
  if (u.group === 'duration') {
    groups = LEN_GROUPS.concat([{id: 'unknown', name: 'Тривалість ще невідома', hint: 'VidBox ще не прочитав ці файли', test: v => !(v.dur > 0)}])
      .map(gr => ({key: 'len:' + gr.id, name: gr.name, sub: gr.hint, list: vs.filter(gr.test), pl: gr.id !== 'unknown' ? gr.id : ''}))
      .filter(gr => gr.list.length);
  } else {
    const m = new Map();
    for (const v of vs) { if (!m.has(v.folder)) m.set(v.folder, []); m.get(v.folder).push(v); }
    const names = [...m.keys()].sort((a, b) => a.localeCompare(b, 'uk', {numeric: true}));
    if (u.sort === 'folder' && u.dir === 'desc') names.reverse();
    groups = names.map(f => { const parts = f.split('/'); return {key: f, name: parts[parts.length - 1], sub: parts.slice(0, -1).join(' / '), list: m.get(f)}; });
  }
  const closed = new Set(LS.get('closed', []));
  g.className = 'groups';
  g.innerHTML = groups.map(gr => {
    const size = gr.list.reduce((a, v) => a + (v.size || 0), 0), dur = gr.list.reduce((a, v) => a + (v.dur || 0), 0);
    return `<section class="fgroup${closed.has(gr.key) ? ' closed' : ''}" data-folder="${esc(gr.key)}">` +
      `<div class="fhead-row"><button class="fhead" aria-expanded="${!closed.has(gr.key)}">${I.chev}<span class="fname">${esc(gr.name)}</span>` +
      `<span class="fpath">${esc(gr.sub)}</span><span class="fstat">${gr.list.length} відео, ${fmtSize(size)}${dur ? ', ' + fmtLen(dur) : ''}</span></button>` +
      (gr.pl ? `<button class="btn ghost" data-play-pl="${gr.pl}">${I.play}Відтворити все</button>` : '') + `</div>` +
      `<div class="grid">${gr.list.map(v => card(v, {meta: libMeta(v, u.group === 'folders')})).join('')}</div></section>`;
  }).join('');
}
async function renderLib() {
  await load();
  if (view.folder && !S.folders.includes(view.folder)) view.folder = '';
  if (!SORTS[ui().sort]) ui().sort = 'score';
  const u = ui(), seg = (id, icon, text) => `<button data-group="${id}" class="${u.group === id || (id === 'all' && !['folders', 'duration'].includes(u.group)) ? 'on' : ''}">${icon}${text}</button>`;
  app.innerHTML = `${promptLine('~/бібліотека', libCmd(), 'libPrompt')}<div class="page-head"><h1 class="title">Бібліотека</h1><span class="count" id="cnt"></span><a class="btn ghost" style="margin-left:auto" href="#/top">${I.list}Рейтинг</a></div>
    <div class="toolbar">
      <div class="seg" role="group" aria-label="Вигляд бібліотеки">${seg('all', I.grid, 'Усі разом')}${seg('folders', I.folder, 'По папках')}${seg('duration', I.clock, 'За тривалістю')}</div>
      <span class="grow"></span>
      <label class="sel"><select id="sort" aria-label="Сортувати за">${Object.entries(SORTS).map(([k, s]) => `<option value="${k}"${k === u.sort ? ' selected' : ''}>${s.label}</option>`).join('')}</select>${I.chev}</label>
      <button class="btn" id="dir"></button>
      <button class="btn icon" id="rs" title="Пересканувати папки" aria-label="Пересканувати папки">${I.refresh}</button></div>
    ${S.folders.length > 1 ? `<div class="chips fl" id="chips"><button class="chip${view.folder ? '' : ' on'}" data-f="">Усі папки</button>` +
      S.folders.map(f => `<button class="chip${f === view.folder ? ' on' : ''}" data-f="${esc(f)}">${esc(shortFolder(f))}</button>`).join('') + `</div>` : ''}
    <div id="grid"></div>`;
  $$('[data-group]').forEach(b => b.setAttribute('aria-pressed', b.classList.contains('on')));
  drawDir();
  // Важливо: S.cfg.ui щоразу читаємо заново (ui()), бо фонове оновлення бібліотеки
  // підміняє S.cfg новим об'єктом. Раніше тут жила стара копія — і сортування «не спрацьовувало».
  $('#sort').onchange = e => {
    const u = ui();
    u.sort = e.target.value;
    u.dir = SORTS[u.sort].first || 'desc';
    if (u.sort === 'random') S.videos.forEach(v => v._r = Math.random());
    saveUi(); drawDir(); drawGrid();
  };
  $('#dir').onclick = () => {
    const u = ui();
    if (u.sort === 'random') S.videos.forEach(v => v._r = Math.random());
    else { u.dir = u.dir === 'asc' ? 'desc' : 'asc'; saveUi(); }
    drawDir(); drawGrid();
  };
  $$('[data-group]').forEach(b => b.onclick = () => {
    ui().group = b.dataset.group; saveUi();
    $$('[data-group]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
    drawGrid();
  });
  $('#grid').addEventListener('click', e => {
    const pl = e.target.closest('[data-play-pl]');
    if (pl) { playQueue(pl.dataset.playPl); return; }
    const h = e.target.closest('.fhead'); if (!h) return;
    const sec = h.closest('.fgroup'), f = sec.dataset.folder, closed = new Set(LS.get('closed', []));
    sec.classList.toggle('closed');
    if (sec.classList.contains('closed')) closed.add(f); else closed.delete(f);
    h.setAttribute('aria-expanded', !sec.classList.contains('closed'));
    LS.set('closed', [...closed]);
  });
  $('#rs').onclick = rescan;
  const chips = $('#chips');
  if (chips) chips.onclick = e => {
    const c = e.target.closest('.chip'); if (!c) return;
    view.folder = c.dataset.f; LS.set('folder', view.folder);
    $$('.chip', chips).forEach(x => x.classList.toggle('on', x === c));
    drawGrid();
  };
  drawGrid();
}
async function rescan() {
  toast('Сканую папки…');
  const r = await api('/api/rescan', {method: 'POST'});
  toast(r.new ? `Знайдено нових відео: ${r.new}` : 'Нових відео немає');
  await renderBase(baseHash, true);
}
$('#q').addEventListener('input', e => {
  view.q = e.target.value.trim();
  if (sheetId) hideSheet();
  if (baseHash !== '/lib') go('#/lib');
  else if ($('#grid')) drawGrid();
});

// ── Налаштування (зберігаються на ПК у config.json) ──
const fmtUp = s => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return d ? `${d} д ${h} год` : h ? `${h} год ${m} хв` : `${m} хв`; };

async function waitServer(msg) {
  toast(msg);
  await new Promise(r => setTimeout(r, 2500));
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch('/api/hello', {cache: 'no-store'}); if (r.ok) return location.reload(); } catch (e) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  toast('Сервер не відповідає. Перевір вікно VidBox на комп’ютері');
}

async function loadAdmin(row) {
  const box = $('#srvInfo'), log = $('#srvLog');
  if (!box) return;
  const a = await api('/api/admin');
  if (!a || a.error) { box.innerHTML = '<p class="note">Не вдалося отримати стан сервера.</p>'; return; }
  const disk = d => d.ok ? `${fmtSize(d.free)} вільно з ${fmtSize(d.total)}` : 'диск недоступний — перевір, чи підключений';
  const bat = a.battery ? `${a.battery.pct}% · ${a.battery.ac ? 'від мережі' : 'від батареї'}` : 'немає (стаціонарний ПК)';
  const ver = a.git ? `${a.version} · коміт ${esc(a.git.commit)} від ${new Date(a.git.date).toLocaleDateString('uk-UA')}` : `${a.version} · встановлено з архіву`;
  box.innerHTML = row('Комп’ютер', esc(a.os), `<code>${esc(a.host)}</code>`) +
    row('Працює', 'Від останнього запуску сервера.', `<span>${fmtUp(a.uptime)}</span>`) +
    row('Живлення', a.battery && !a.battery.ac ? 'Ноутбук не на зарядці — сервер вимкнеться, коли сяде батарея.' : '', `<span>${bat}</span>`) +
    a.disks.map(d => row('Диск з відео', `<code>${esc(d.path)}</code>`, `<span${d.ok ? '' : ' class="warn"'}>${disk(d)}</span>`)).join('') +
    row('Версія', '', `<span>${ver}</span>`);
  log.textContent = a.log.join('\n') || '(порожньо)';
  log.scrollTop = log.scrollHeight;
  $('#srvRe').onclick = async () => {
    if (!confirm('Перезапустити сервер VidBox?')) return;
    await api('/api/admin/restart', {method: 'POST'});
    waitServer('Перезапускаю сервер…');
  };
  $('#srvUpd').onclick = async e => {
    e.target.disabled = true;
    toast('Завантажую оновлення…');
    const r = await api('/api/admin/update', {method: 'POST'});
    e.target.disabled = false;
    if (!r.ok) return toast('Не вдалося оновити: ' + (r.error || 'невідома помилка'));
    if (!r.changed) return toast('Уже встановлено останню версію');
    waitServer('Оновлено, перезапускаю сервер…');
  };
}

async function renderSettings() {
  const st = await api('/api/settings');
  if (!S.loaded) await load();
  const sw = (k, on) => `<label class="sw"><input type="checkbox" data-k="${k}"${on ? ' checked' : ''}><i></i></label>`;
  const num = (k, val, min, max, step, unit) => `<span class="num"><input type="number" data-k="${k}" value="${val}" min="${min}" max="${max}" step="${step}" inputmode="decimal" aria-label="${unit}">${unit ? `<em>${unit}</em>` : ''}</span>`;
  const sel = (k, opts, cur, isNum) => `<label class="sel wide"><select data-k="${k}"${isNum ? ' data-num' : ''} aria-label="${k}">${opts.map(([v, t]) =>
    `<option value="${v}"${String(v) === String(cur) ? ' selected' : ''}>${t}</option>`).join('')}</select>${I.chev}</label>`;
  const row = (title, hint, control, id) => `<div class="srow"${id ? ` id="${id}"` : ''}><div class="sl"><b>${title}</b>${hint ? `<small>${hint}</small>` : ''}</div><div class="sc">${control}</div></div>`;
  const c = st.caches, used = b => fmtSize(b) || '0 МБ';
  app.innerHTML = `${promptLine('~/.config/vidbox', 'nvim config.json')}<div class="page-head"><h1 class="title">Налаштування</h1></div>
  <p class="lead">Зміни зберігаються одразу на комп’ютері, у файлі config.json, і діють після наступного запуску теж.</p>
  <div class="settings">
  <section class="set win">${winBar('~/.config/vidbox/тема')}<div class="win-body"><h2>Тема</h2>
    <p class="note" style="margin-top:0">Кольори всього сайту. Зберігається на ПК, тож тема однакова на всіх пристроях.</p>
    <div class="themes">${THEMES.map(t => `<button class="theme${st.theme === t.id ? ' on' : ''}" data-theme-pick="${t.id}" aria-pressed="${st.theme === t.id}" ` +
      `style="--t-bg:${t.bg};--t-p:${t.p};--t-a:${t.a};--t-a2:${t.a2}"><span class="tp"><i></i><i></i><i></i></span><b>${t.name}</b><small>${t.hint}</small></button>`).join('')}</div>
    ${row('Оптимізована версія', 'Для слабких чи старих комп’ютерів: без розмиття, світіння й анімацій, без кадрів при наведенні на картку, обкладинки вантажаться заздалегідь. Діє лише на цьому пристрої.', `<label class="sw"><input type="checkbox" id="litesw"${isLite() ? ' checked' : ''}><i></i></label>`)}
  </div></section>
  <section class="set win">${winBar('~/.config/vidbox/папки')}<div class="win-body"><h2>Папки з відео</h2>
    <div class="flist">${st.folders.map((f, i) => `<div class="frow">${I.folder}<div><b>${esc(f.path)}</b><small>${f.exists ? f.count + ' відео' : 'Папку не знайдено. Можливо, диск від’єднано.'}</small></div>` +
      `<button class="btn ghost icon" data-rm="${i}" title="Прибрати папку" aria-label="Прибрати папку ${esc(f.path)}"${st.folders.length < 2 ? ' disabled' : ''}>${I.trash}</button></div>`).join('')}</div>
    <div class="fadd"><input id="newf" type="text" placeholder="Шлях до папки, наприклад D:\\Фільми" aria-label="Шлях до нової папки">
      <button class="btn" id="browse">${I.folder}Огляд</button><button class="btn primary" id="addf">${I.plus}Додати</button></div>
    <p class="warn" id="ferr" hidden></p>
    ${row('Пересканувати зараз', 'Знайде нові файли й прибере видалені.', `<button class="btn" id="rescanNow">${I.refresh}Пересканувати</button>`)}
    ${row('Пересканувати автоматично', 'Як часто VidBox сам перевіряє папки.', num('rescan_min', st.rescan_min, 1, 1440, 1, 'хв'))}
  </div></section>
  <section class="set win">${winBar('~/.config/vidbox/аніме')}<div class="win-body"><h2>Аніме</h2>
    <p class="note" style="margin-top:0">Окремий розділ з постерами: кожна підпапка — тайтл, файли в ній — серії. Аніме не потрапляє в бібліотеку, рейтинг і «Продовжити». Обкладинки, жанри й описи — з AniList.</p>
    ${st.anime_folder ? `<div class="flist"><div class="frow">${I.folder}<div><b>${esc(st.anime_folder)}</b><small>${st.animeExists ? `${st.animeCount} ${plural(st.animeCount, 'серія', 'серії', 'серій')} · ${st.animeTitles} ${plural(st.animeTitles, 'тайтл', 'тайтли', 'тайтлів')}` : 'Папку не знайдено. Можливо, диск від’єднано.'}</small></div>` +
      `<button class="btn ghost icon" id="animeoff" title="Прибрати папку з аніме" aria-label="Прибрати папку з аніме">${I.trash}</button></div></div>`
    : `<div class="fadd"><input id="animef" type="text" placeholder="Шлях до папки з аніме, наприклад E:\\Аніме" aria-label="Шлях до папки з аніме">
      <button class="btn" id="animeBrowse">${I.folder}Огляд</button><button class="btn primary" id="animeset">${I.plus}Додати</button></div>`}
    <p class="warn" id="aerr" hidden></p>
  </div></section>
  <section class="set win">${winBar('~/.config/vidbox/перегляд')}<div class="win-body"><h2>Перегляд</h2>
    ${row('Продовжувати з місця, де зупинився', 'Якщо вимкнути, відео щоразу починається спочатку.', sw('resume', st.resume))}
    ${row('Вмикати наступне відео', 'Коли відео закінчилось, вмикається наступне з тієї ж папки.', sw('autoplay_next', st.autoplay_next))}
    ${row('Пауза перед наступним', 'Скільки секунд чекати, поки можна скасувати.', num('next_delay', st.next_delay, 3, 60, 1, 'с'))}
  </div></section>
  <section class="set win">${winBar('~/.cache/vidbox')}<div class="win-body"><h2>Обкладинки, кадри й кеш</h2>
    ${st.ffmpeg ? '' : `<p class="warn">ffmpeg не знайдено, тому нарізок кадрів і конвертації MKV/AVI немає. Запусти start.bat, він запропонує завантажити ffmpeg, або поклади ffmpeg.exe і ffprobe.exe поруч з vidbox.py.</p>`}
    ${row('Готувати нарізки кадрів у фоні', 'Для наведення на картку й сітки кадрів. Можна вимкнути на слабкому ПК: тоді кадри робляться лише для відкритих відео.', sw('sprites', st.sprites))}
    ${row('Кеш копій для телефону', `MP4-копії MKV/AVI. Зайнято ${used(c.prepared)}, старі видаляються самі, коли перевищено ліміт.`, num('cache_gb', st.cache_gb, 1, 100000, 1, 'ГБ') + `<button class="btn ghost" data-clear="prepared">Очистити</button>`)}
    ${row('Кеш великих кадрів', `Чіткі кадри для вікна з інфою. Зайнято ${used(c.frames)}.`, num('frames_cache_gb', st.frames_cache_gb, 0.5, 10000, 0.5, 'ГБ') + `<button class="btn ghost" data-clear="frames">Очистити</button>`)}
    ${row('Обкладинки й нарізки', `Зайнято ${used(c.thumbs + c.sprites)}.`, '')}
    ${row('Залишки видалених відео', st.orphans ? `${st.orphans} відео вже немає в папках, але їхні картинки ще в кеші. Статистика переглядів залишиться.` : 'Залишків немає.', st.orphans ? `<button class="btn ghost" data-clear="orphans">Прибрати</button>` : '')}
  </div></section>
  ${gpuSection(st, {sw, row, sel})}
  <section class="set win">${winBar('~/.config/vidbox/доступ')}<div class="win-body"><h2>Доступ</h2>
    ${row('Пароль для входу', st.hasPassword ? 'Увімкнено. Кожен пристрій вводить його один раз.' : 'Вимкнено: сайт відкриється будь-кому у твоїй Wi-Fi мережі.',
      `<input type="password" id="pw" placeholder="${st.hasPassword ? 'Новий пароль' : 'Пароль'}" autocomplete="new-password" aria-label="Пароль"><button class="btn" id="pwset">${st.hasPassword ? 'Змінити' : 'Встановити'}</button>${st.hasPassword ? '<button class="btn ghost" id="pwoff">Прибрати</button>' : ''}`)}
    ${row('Порт сайту', st.port !== st.portNow ? `Після перезапуску VidBox адреса зміниться на порт ${st.port}.` : 'Змінюй, лише якщо 8800 зайнятий іншою програмою. Діє після перезапуску.', num('port', st.port, 1024, 65535, 1, ''))}
    ${row('Відкривати сайт на ПК при запуску', '', sw('open_browser', st.open_browser))}
    ${row('Адреса для телефону', 'Телефон має бути в тій самій Wi-Fi мережі.', st.urls.length ? st.urls.map(u => `<code>${esc(u)}</code>`).join('') : '<span class="note">Не вдалося визначити</span>')}
    ${row('Апка для Android', 'Своя апка з плеєром: сама знаходить цей ПК у Wi-Fi, грає MKV, HEVC і AV1 без перекодування, звук у фоні й керування зі шторки.',
      `<a class="btn" href="https://github.com/AfricaEE112/hata/releases/latest" target="_blank" rel="noopener">${I.arrDown}Завантажити APK</a>`)}
  </div></section>
  <section class="set win" id="srv">${winBar('~/.local/share/vidbox/сервер')}<div class="win-body"><h2>Сервер</h2>
    <div id="srvInfo"><p class="note">Завантажую стан…</p></div>
    ${row('Оновити VidBox', 'Бере останню версію з GitHub і перезапускає сервер. Історія й налаштування не змінюються.', '<button class="btn" id="srvUpd">Оновити</button>')}
    ${row('Перезапустити сервер', 'Знадобиться, якщо щось зависло або після зміни порту. Відтворення на всіх пристроях перерветься на кілька секунд.', '<button class="btn ghost" id="srvRe">Перезапустити</button>')}
    <div class="srow col"><div class="sl"><b>Журнал</b><small>Останні повідомлення сервера, як у вікні консолі на комп’ютері.</small></div><pre class="srvlog" id="srvLog"></pre></div>
  </div></section>
  <section class="set win">${winBar('terminal — <b>vidbox --about</b>')}<div class="win-body"><h2>Про програму</h2>${fetchHTML(st)}</div></section></div>`;
  loadAdmin(row);
  $('#litesw').onchange = e => {
    document.documentElement.classList.toggle('lite', e.target.checked);
    LS.set('lite', e.target.checked);
    toast(e.target.checked ? 'Оптимізовану версію увімкнено на цьому пристрої' : 'Повну версію увімкнено');
  };
  const setAnime = async a => {
    if (a === null) return;
    const r = await api('/api/settings', {method: 'POST', body: JSON.stringify({anime_folder: a})});
    const e = $('#aerr');
    if (!r.ok) { e.textContent = r.error || 'Не вдалося зберегти'; e.hidden = false; return; }
    e.hidden = true;
    toast(a ? 'Папку з аніме додано, сканую…' : 'Розділ аніме вимкнено. Самі файли не видаляються');
    setTimeout(() => { if (baseHash === '/settings') renderBase('/settings', true); }, 1500);
  };
  const addAnime = () => { const v = $('#animef').value.trim(); if (!v) { $('#animef').focus(); return toast('Введи шлях або натисни «Огляд»'); } setAnime(v); };
  if ($('#animeset')) $('#animeset').onclick = addAnime;
  if ($('#animef')) $('#animef').onkeydown = e => { if (e.key === 'Enter') addAnime(); };
  if ($('#animeBrowse')) $('#animeBrowse').onclick = () => openPicker('', path => { $('#animef').value = path; });
  if ($('#animeoff')) $('#animeoff').onclick = () => { if (confirm('Прибрати папку з аніме? Розділ «Аніме» зникне, файли на диску лишаться.')) setAnime(''); };

  $$('[data-theme-pick]').forEach(b => b.onclick = () => {
    applyTheme(b.dataset.themePick);
    $$('[data-theme-pick]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
    save({theme: b.dataset.themePick}, 'Тему збережено');
  });
  const save = async (d, msg) => {
    const r = await api('/api/settings', {method: 'POST', body: JSON.stringify(d)});
    if (!r.ok) { const e = $('#ferr'); e.textContent = r.error || 'Не вдалося зберегти'; e.hidden = false; return r; }
    $('#ferr').hidden = true;
    for (const k in d) if (k in S.cfg) S.cfg[k] = d[k];
    toast(msg || 'Збережено');
    return r;
  };
  $$('[data-k]').forEach(el => el.onchange = () => {
    const k = el.dataset.k;
    const val = el.type === 'checkbox' ? el.checked : el.tagName === 'SELECT' ? (el.hasAttribute('data-num') ? +el.value : el.value) : +el.value;
    if (el.type === 'number' && !(val >= +el.min && val <= +el.max)) { toast(`Введи число від ${el.min} до ${el.max}`); return; }
    save({[k]: val}, k === 'port' ? 'Збережено. Новий порт запрацює після перезапуску VidBox' :
      k === 'hwaccel' ? 'Збережено. Нові конвертації підуть через вибраний режим' : null);
  });
  const hwre = $('#hwre');
  if (hwre) hwre.onclick = async () => {
    await api('/api/hw/detect', {method: 'POST'});
    toast('Перевіряю відеокарту, кілька секунд…');
    setTimeout(() => { if (baseHash === '/settings') renderBase('/settings', true); }, 5000);
  };
  const paths = st.folders.map(f => f.path);
  const setFolders = async (list, msg) => {
    const r = await save({folders: list}, msg);
    if (r.ok) setTimeout(() => { if (baseHash === '/settings') renderBase('/settings', true); }, 1500);
  };
  $$('[data-rm]').forEach(b => b.onclick = () => setFolders(paths.filter((_, i) => i !== +b.dataset.rm), 'Папку прибрано. Її відео зникнуть з бібліотеки, статистика збережеться'));
  const add = () => { const v = $('#newf').value.trim(); if (!v) { $('#newf').focus(); return toast('Введи шлях або натисни «Огляд»'); } setFolders(paths.concat(v), 'Папку додано, сканую…'); };
  $('#addf').onclick = add;
  $('#newf').onkeydown = e => { if (e.key === 'Enter') add(); };
  $('#browse').onclick = () => openPicker('', path => { $('#newf').value = path; });
  $('#rescanNow').onclick = async () => { await rescan(); };
  $$('[data-clear]').forEach(b => b.onclick = async () => {
    await api('/api/cache/clear', {method: 'POST', body: JSON.stringify({what: b.dataset.clear})});
    toast('Очищено'); renderBase('/settings', true);
  });
  const setPw = async pw => {
    const r = await api('/api/password', {method: 'POST', body: JSON.stringify({password: pw})});
    toast(r.hasPassword ? 'Пароль збережено' : 'Пароль прибрано'); renderBase('/settings', true);
  };
  $('#pwset').onclick = () => { const pw = $('#pw').value; if (pw.length < 3) return toast('Пароль має бути щонайменше з 3 символів'); setPw(pw); };
  const off = $('#pwoff'); if (off) off.onclick = () => setPw('');
}

// розділ «Відеокарта»
function gpuSection(st, h) {
  const hw = st.hw || {}, encs = hw.encoders || {};
  const names = {amd: 'AMD AMF', nvidia: 'NVIDIA NVENC', intel: 'Intel QSV', vaapi: 'VA-API'};
  const why = e => /немає в цій збірці/.test(e.err || '') ? 'немає в цій збірці ffmpeg' : 'немає такої відеокарти або драйвера';
  const list = Object.keys(encs).map(k => `<dt>${names[k] || k}</dt><dd class="${encs[k].ok ? 'ok' : 'no'}" title="${esc(encs[k].err || '')}">${encs[k].ok ? '✓ працює' : '✗ ' + why(encs[k])}</dd>`).join('');
  const status = !hw.checked ? '<p class="note">Перевіряю відеокарту…</p>' :
    `<dl class="hwlist"><dt>Відеокарта</dt><dd>${esc(hw.gpu || 'не визначено')}</dd>` +
    `<dt>Кодує зараз</dt><dd class="${hw.hardware ? 'ok' : ''}">${esc(hw.current)}${hw.hardware ? ' (апаратне)' : ' (процесор)'}</dd>` +
    `<dt>Декодування</dt><dd>${hw.decode ? esc(hw.decode.toUpperCase()) + (hw.zero_copy ? ', кадри не покидають відеокарту' : '') : '—'}</dd>${list}</dl>`;
  const L = hw.last;
  const last = L ? `${esc(L.title)}: ${esc(L.enc)}, ${L.fps || '?'} к/с${L.speed ? `, у ${String(L.speed).replace('.', ',')} раза швидше за реальний час` : ''}.` : 'Ще не було.';
  return `<section class="set win" id="gpu">${winBar('~/.config/vidbox/gpu')}<div class="win-body"><h2>Відеокарта</h2>
    <p class="note" style="margin-top:0">Відеокарта перекодовує для телефону те, що він не відкриває: AVI, 10-бітні аніме, HEVC за потреби. Якщо щось піде не так, VidBox сам повторить задачу процесором.</p>
    ${status}
    ${h.row('Прискорення', 'В режимі «Авто» береться AMD, потім NVIDIA, потім Intel.', h.sel('hwaccel', [['auto', 'Авто'], ['amd', 'AMD (AMF)'], ['nvidia', 'NVIDIA (NVENC)'], ['intel', 'Intel (QSV)'], ['vaapi', 'VA-API (Linux)'], ['off', 'Лише процесор']], st.hwaccel))}
    ${h.row('Роздільність копій для телефону', 'Більші відео зменшуються: менше місця і плавніше на телефоні.', h.sel('max_height', [[720, '720p'], [1080, '1080p'], [1440, '1440p'], [2160, '4K'], [0, 'Як в оригіналі']], st.max_height, true))}
    ${h.row('Готувати копії заздалегідь', 'Відеокарта у фоні конвертує всі несумісні відео, тож вони відкриваються одразу. Займає місце в кеші копій.', h.sw('prep_all', st.prep_all))}
    ${h.row('Кадри теж через відеокарту', 'Зазвичай так повільніше: на один кадр відеокарта довше запускається, ніж працює. Кадри й так беруться лише з ключових кадрів, тому це швидко.', h.sw('hw_frames', st.hw_frames))}
    ${h.row('Остання конвертація', last, `<button class="btn" id="hwre">${I.refresh}Перевірити ще раз</button>`)}
  </div></section>`;
}

// «Про програму» у стилі neofetch — привіт райсам Linux
function fetchHTML(st) {
  const logo = ['███', '██████', '█████████', '████████████', '███████████████', '████████████', '█████████', '██████', '███    ████████'].join('\n');
  const t = st.totals || {}, theme = (THEMES.find(x => x.id === st.theme) || THEMES[0]).name;
  const rows = [
    ['Версія', 'VidBox ' + st.version],
    ['Бібліотека', `${t.videos || 0} відео, ${fmtSize(t.size) || '0 МБ'}, ${fmtLen(t.dur) || '0 хв'}`],
    ['Папки', String(st.folders.length)],
    ['Тема', theme],
    ['ffmpeg', st.ffmpegVersion || (st.ffmpeg ? 'є' : 'не знайдено')],
    ['GPU', (st.hw && st.hw.gpu) || ''],
    ['Кодування', st.hw ? st.hw.current + (st.hw.hardware ? ' (апаратне)' : ' (процесор)') : ''],
    ['Python', st.python || ''],
    ['Система', st.os || ''],
    ['Працює', fmtLen(st.uptime) || 'щойно'],
    ['Адреса', (st.urls || [])[0] || ''],
    ['Дані', st.data],
  ].filter(r => r[1]);
  const head = 'vidbox@' + (st.host || 'pc');
  return `<div class="fetch"><pre aria-hidden="true">${logo}</pre><div><div class="u">vidbox<em>@</em>${esc(st.host || 'pc')}</div><div class="hr">${'-'.repeat(head.length)}</div>
    <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
    <div class="blocks">${['--bg', '--bg2', '--bg3', '--line', '--mute', '--fg', '--acc', '--acc2'].map(c => `<i style="background:var(${c})"></i>`).join('')}</div></div></div>`;
}

// ── Огляд папок на ПК (для «Додати папку») ──
const picker = $('#picker'), pickPanel = $('.panel', picker);
let pickCb = null;
function openPicker(start, cb) {
  pickCb = cb;
  picker.hidden = false;
  document.documentElement.classList.add('locked');
  requestAnimationFrame(() => picker.classList.add('open'));
  pickerGo(start);
}
function closePicker() {
  picker.classList.remove('open');
  if (!sheetId) document.documentElement.classList.remove('locked');
  setTimeout(() => { picker.hidden = true; }, 240);
}
async function pickerGo(path) {
  const d = await api('/api/fs?path=' + encodeURIComponent(path || ''));
  pickPanel.innerHTML = `${winBar(`pick-folder — <b>${esc(d.path || 'цей комп’ютер')}</b>`, `<button class="x" data-pclose aria-label="Закрити (Esc)">${I.close}</button>`)}<div class="pk"><h2>Вибери папку з відео</h2>
    <div class="pk-path">${d.path ? `<button class="btn icon ghost" data-go="${esc(d.parent || '')}" aria-label="На рівень вище">${I.left}</button><span>${esc(d.path)}</span>` : '<span>Цей комп’ютер</span>'}</div>
    ${d.error ? `<p class="warn">${esc(d.error)}</p>` : ''}
    ${d.quick && d.quick.length ? `<div class="pk-quick">${d.quick.map(q => `<button class="chip" data-go="${esc(q.path)}">${esc(q.name)}</button>`).join('')}</div>` : ''}
    <div class="pk-list">${d.dirs.length ? d.dirs.map(x => `<button class="pk-item" data-go="${esc(x.path)}">${I.folder}<span>${esc(x.name)}</span>${I.right}</button>`).join('') : '<p class="note">Вкладених папок немає.</p>'}</div>
    <div class="pk-foot">${d.path ? `<span class="note">${d.videos ? `${d.videos} відео прямо в цій папці` : 'Відео можуть бути у вкладених папках'}</span><button class="btn primary" data-pick="${esc(d.path)}">Вибрати цю папку</button>` : '<span class="note">Обери диск або папку</span>'}</div></div>`;
  const list = $('.pk-list', pickPanel); if (list) list.scrollTop = 0;
}
picker.addEventListener('click', e => {
  const g = e.target.closest('[data-go]');
  if (g) { pickerGo(g.dataset.go); return; }
  const pk = e.target.closest('[data-pick]');
  if (pk) { if (pickCb) pickCb(pk.dataset.pick); closePicker(); return; }
  if (e.target.closest('[data-pclose]')) closePicker();
});

// ── Плейлисти ──
// Збираються самі за тривалістю: нові відео потрапляють у потрібний плейлист автоматично.
// Черга відтворення живе в sessionStorage: плеєр бере «далі» з неї, а не з папки.
const LEN_GROUPS = [
  {id: 'short', name: 'До 20 хвилин', file: 'короткі', hint: 'Коли є кілька вільних хвилин', test: v => v.dur > 0 && v.dur < 1200},
  {id: 'mid', name: 'До години', file: 'середні', hint: 'Від 20 хвилин до години: серія чи документалка', test: v => v.dur >= 1200 && v.dur < 3600},
  {id: 'long', name: 'Понад годину', file: 'довгі', hint: 'Фільми й довгі записи на вечір', test: v => v.dur >= 3600},
];
const inOrder = (a, b) => a.folder.localeCompare(b.folder, 'uk', {numeric: true}) || byName(a, b);
function plItems(id) {
  const g = LEN_GROUPS.find(x => x.id === id);
  return g ? S.videos.filter(g.test).sort(inOrder) : [];
}
// ───────── Аніме: окремий розділ, тайтл = підпапка, серії по порядку ─────────
S.animeBy = {};
function animeRegister(t) {
  for (const e of t.eps) { e._r = Math.random(); S.animeBy[e.id] = e; S.by[e.id] = e; }
}
function playAnime(t, id) {
  setQueue({pl: 'anime', anime: t.sid, name: t.title, ids: t.eps.map(e => e.id)});
  go('#/v/' + id);
}
async function loadAnimeEp(id) {
  const t = await api('/api/anime/ep/' + id).catch(() => null);
  if (!t || !t.eps) return;
  animeRegister(t);
  const q = getQueue();
  if (!(q && q.ids && q.ids.includes(id))) setQueue({pl: 'anime', anime: t.sid, name: t.title, ids: t.eps.map(e => e.id)});
}
const animeCard = t => {
  const pct = t.cont && t.cont.dur ? Math.min(100, t.cont.pos / t.cont.dur * 100) : 0;
  return `<a class="acard" href="#/anime/${t.sid}"><div class="poster"><img loading="lazy" decoding="async" src="${t.cover}" alt="" onerror="this.remove()"><span class="ph">${esc((t.title.trim()[0] || '?').toUpperCase())}</span>
    ${t.cont ? `<span class="aep">Серія ${t.cont.ep}</span>` : t.watched && t.watched === t.n ? '<span class="aep done">Переглянуто</span>' : ''}
    ${pct ? `<span class="pbar"><i style="width:${pct}%"></i></span>` : ''}</div>
    <b>${esc(t.title)}</b><small>${t.meta && t.meta.year ? t.meta.year + ' · ' : ''}${t.n} ${plural(t.n, 'серія', 'серії', 'серій')}${t.watched && t.watched < t.n ? ` · переглянуто ${t.watched}` : ''}</small></a>`;
};
async function renderAnime() {
  const d = await api('/api/anime');
  const head = `${promptLine('~/аніме', 'ls')}<div class="page-head"><h1 class="title">Аніме</h1>${d.titles.length ? `<span class="count">${d.titles.length}</span>` : ''}</div>`;
  if (!d.folder) {
    app.innerHTML = head + `<div class="empty"><p>Вкажи папку з аніме в налаштуваннях. Кожна підпапка в ній стане окремим тайтлом, а файли в ній — серіями.</p><br><a class="btn primary" href="#/settings">Відкрити налаштування</a></div>`;
    return;
  }
  if (!d.titles.length) { app.innerHTML = head + `<div class="empty"><p>У папці <code>${esc(d.folder)}</code> поки немає відео. Поклади кожен тайтл в окрему підпапку.</p></div>`; return; }
  const cont = d.titles.filter(t => t.cont).sort((a, b) => b.lastAt - a.lastAt);
  app.innerHTML = head +
    (cont.length ? `<section class="ashelf"><h2>Продовжити</h2><div class="agrid">${cont.map(animeCard).join('')}</div></section>` : '') +
    `<section class="ashelf">${cont.length ? '<h2>Усі тайтли</h2>' : ''}<div class="agrid">${d.titles.map(animeCard).join('')}</div></section>`;
}
const ANIME_FMT = {TV:'серіал',TV_SHORT:'короткий серіал',MOVIE:'фільм',OVA:'OVA',ONA:'ONA',SPECIAL:'спешл',MUSIC:'кліп'};
function animeMeta(t) {
  const m = t.meta;
  if (!m) return '';
  const alt = [m.english, m.romaji, m.native].filter((x, i, a) => x && x !== t.title && a.indexOf(x) === i).slice(0, 2);
  const row = [m.year, ANIME_FMT[m.format] || m.format, m.episodes ? `${m.episodes} ${plural(m.episodes, 'серія', 'серії', 'серій')} у сезоні` : '', m.score ? `★ ${(m.score / 10).toFixed(1).replace('.', ',')}` : '']
    .filter(Boolean).map(x => `<span class="tag">${esc(x)}</span>`).join('');
  return (alt.length ? `<p class="aalt">${alt.map(esc).join(' · ')}</p>` : '') +
    `<div class="ameta">${row}${(m.genres || []).map(g => `<span class="tag ghost">${esc(g)}</span>`).join('')}</div>`;
}
async function renderAnimeTitle(sid) {
  const t = await api('/api/anime/' + sid).catch(() => null);
  if (!t || !t.eps) { app.innerHTML = `<div class="empty"><h1 class="title">Тайтл не знайдено</h1><br><a class="btn" href="#/anime">До аніме</a></div>`; return; }
  animeRegister(t);
  const c = t.cont, first = t.eps[0];
  const startId = c ? c.id : first.id;
  const label = c ? (c.pos > 5 ? `Продовжити серію ${c.ep}` : `Дивитися серію ${c.ep}`) : 'Дивитися з першої серії';
  app.innerHTML = `${promptLine('~/аніме/' + esc(t.title), 'ls')}
    <div class="ahead"><div class="poster big"><img src="${t.cover}" alt="" onerror="this.remove()"><span class="ph">${esc((t.title.trim()[0] || '?').toUpperCase())}</span></div>
    <div class="ainfo"><h1 class="title">${esc(t.title)}</h1>${animeMeta(t)}<p class="lead">${t.n} ${plural(t.n, 'серія', 'серії', 'серій')}${t.watched ? ` · переглянуто ${t.watched} з ${t.n}` : ''}</p>
    <div class="acts"><button class="btn primary" id="aplay">${I.play}${label}</button><a class="btn ghost" href="#/anime">Усі тайтли</a></div></div></div>
    ${t.meta && t.meta.desc ? `<details class="adesc"><summary>Опис з AniList</summary><p>${esc(t.meta.desc).replace(/\n/g, '<br>')}</p><a href="${esc(t.meta.url)}" target="_blank" rel="noopener">Відкрити на AniList</a></details>` : ''}
    <ol class="eps">${t.eps.map(e => {
      const pct = e.dur && e.pos > 5 && !e.done ? Math.min(100, e.pos / e.dur * 100) : 0;
      return `<li><button class="ep${e.id === startId ? ' cur' : ''}${e.done ? ' done' : ''}" data-ep="${e.id}">
        <span class="thumb">${e.thumb ? `<img decoding="async" src="/thumb/${e.id}?v=${e.thumb}" alt="">` : ''}${pct ? `<span class="pbar"><i style="width:${pct}%"></i></span>` : ''}</span>
        <span class="n">${e.ep}</span><span class="et"><b>Серія ${e.ep}${e.etitle ? ' · ' + esc(e.etitle) : ''}</b><small>${e.dur ? fmtLen(e.dur) : ''}${e.done ? ' · переглянуто' : pct ? ` · залишилось ${fmtLen(e.dur - e.pos)}` : ''}</small></span></button></li>`;
    }).join('')}</ol>`;
  $('#aplay').onclick = () => playAnime(t, startId);
  $$('[data-ep]').forEach(b => b.onclick = () => playAnime(t, b.dataset.ep));
}

function getQueue() { try { return JSON.parse(sessionStorage.getItem('vb_queue')); } catch (e) { return null; } }
function setQueue(q) { try { if (q) sessionStorage.setItem('vb_queue', JSON.stringify(q)); else sessionStorage.removeItem('vb_queue'); } catch (e) {} }
function shuffled(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function playQueue(id, startId, shuffle) {
  const g = LEN_GROUPS.find(x => x.id === id);
  let vs = plItems(id);
  if (!g || !vs.length) return toast('У цьому плейлисті поки немає відео');
  if (shuffle) vs = shuffled(vs);
  const ids = vs.map(v => v.id);
  setQueue({pl: id, name: g.name, ids, shuffle: !!shuffle});
  go('#/v/' + (startId || ids[0]));
}
function queueFor(v) {
  const q = getQueue();
  return q && Array.isArray(q.ids) && q.ids.includes(v.id) ? q : null;
}
function mosaic(list) {
  const four = list.slice().sort((a, b) => (b.added || 0) - (a.added || 0)).slice(0, 4);
  const tiles = four.map(v => cover(v));
  // якщо відео менше чотирьох — добираємо інші кадри з тих самих відео, щоб обкладинка не була порожньою
  const withFrames = four.filter(hasSprite);
  for (let k = 0; tiles.length < 4 && withFrames.length; k++) {
    const v = withFrames[k % withFrames.length];
    tiles.push(`<div class="fill" style="${frameBg(v, [9, 15, 6, 18][k % 4])}"></div>`);
  }
  while (tiles.length < 4) tiles.push('');
  return `<div class="mosaic">${tiles.map(t => `<div class="th">${t}</div>`).join('')}</div>`;
}
function plCard(g) {
  const list = plItems(g.id), dur = list.reduce((a, v) => a + (v.dur || 0), 0);
  return `<article class="plcard win">${winBar(`~/плейлисти/<b>${esc(g.file)}.m3u</b>`)}<a class="plcover" href="#/pl/${g.id}" aria-label="${esc(g.name)}">${mosaic(list)}</a>
    <div class="plinfo"><a href="#/pl/${g.id}"><h3 class="title">${esc(g.name)}</h3></a><p>${esc(g.hint)}</p>
      <div class="chipset"><span>${list.length} відео</span>${dur ? `<span>${fmtLen(dur)}</span>` : ''}</div>
      <div class="acts">${list.length ? `<button class="btn primary" data-play-pl="${g.id}">${I.play}Відтворити</button><button class="btn" data-shuffle-pl="${g.id}">${I.dice}Перемішати</button>` : '<span class="note">Поки порожньо</span>'}</div></div></article>`;
}
function wirePl(root) {
  root.addEventListener('click', e => {
    const p = e.target.closest('[data-play-pl]');
    if (p) { e.preventDefault(); playQueue(p.dataset.playPl); return; }
    const s = e.target.closest('[data-shuffle-pl]');
    if (s) { e.preventDefault(); playQueue(s.dataset.shufflePl, null, true); return; }
    const t = e.target.closest('[data-track]');
    if (t && !e.target.closest('a')) { e.preventDefault(); playQueue(t.dataset.pl, t.dataset.track); }
  });
}
async function renderPlaylists() {
  await load();
  app.innerHTML = `${promptLine('~/плейлисти', 'ls *.m3u')}<div class="page-head"><h1 class="title">Плейлисти</h1></div>
    <p class="lead">Збираються самі за тривалістю відео. Нові файли потрапляють у потрібний плейлист автоматично, а відтворення йде підряд, одне за одним.</p>
    <div class="plgrid">${LEN_GROUPS.map(plCard).join('')}</div>`;
  wirePl(app);
}
async function renderPlaylist(id) {
  await load();
  const g = LEN_GROUPS.find(x => x.id === id);
  if (!g) { app.innerHTML = `<div class="empty"><h1 class="title">Плейлист не знайдено</h1><a class="btn" href="#/pl">До плейлистів</a></div>`; return; }
  const list = plItems(id), dur = list.reduce((a, v) => a + (v.dur || 0), 0), unseen = list.filter(v => !v.views).length;
  app.innerHTML = `${promptLine('~/плейлисти', `cat ${g.file}.m3u`)}
    <section class="plhead">${mosaic(list)}<div><p class="spot-kicker">Плейлист</p><h1 class="title">${esc(g.name)}</h1><p class="lead">${esc(g.hint)}</p>
      <div class="chipset"><span>${list.length} відео</span>${dur ? `<span>${fmtLen(dur)}</span>` : ''}${unseen ? `<span class="hl">${unseen} ще не бачив</span>` : ''}</div>
      <div class="acts">${list.length ? `<button class="btn primary" data-play-pl="${id}">${I.play}Відтворити все</button><button class="btn" data-shuffle-pl="${id}">${I.dice}Перемішати</button>` : ''}
        <a class="btn ghost" href="#/pl">Усі плейлисти</a></div></div></section>
    ${list.length ? `<ol class="tracks">${list.map((v, i) => `<li class="track" data-track="${v.id}" data-pl="${id}" tabindex="0" role="button" aria-label="Відтворити ${esc(v.title)}">
        <span class="tn">${String(i + 1).padStart(2, '0')}</span><div class="th" data-scrub="${v.id}">${cover(v)}${v.pos && v.dur ? `<span class="pbar"><i style="width:${Math.min(100, v.pos / v.dur * 100)}%"></i></span>` : ''}</div>
        <div class="tt"><div class="ct">${esc(v.title)}</div><div class="cm"><span>${esc(shortFolder(v.folder))}</span>${v.views ? `<span>${views(v.views)}</span>` : ''}</div></div>
        <span class="td">${fmtDur(v.dur)}</span><a class="btn icon ghost" href="#/i/${v.id}" aria-label="Інфо">${I.info}</a></li>`).join('')}</ol>`
      : `<div class="empty">Поки немає відео такої довжини. Щойно з'являться, вони потраплять сюди самі.</div>`}`;
  wirePl(app);
  app.querySelectorAll('.track').forEach(t => t.addEventListener('keydown', e => { if (e.key === 'Enter') playQueue(id, t.dataset.track); }));
}

// ── Рейтинг ──
async function renderTop() {
  await load();
  const rated = S.videos.filter(v => v.views || v.vote).sort(sorter('score', 'desc'));
  const rest = S.videos.length - rated.length;
  let html = `${promptLine('~/рейтинг', `sort -k score -rn | head -${rated.length}`)}<div class="page-head"><h1 class="title">Рейтинг</h1></div>
    <p class="lead">Складається сам із того, як ти дивишся: наскільки досматриваєш відео (45%), як часто до нього вертаєшся, і свіжі перегляди тут важать більше (40%), плюс твої лайки й дизлайки (15%).</p>`;
  if (!rated.length) html += `<div class="empty"><h1 class="title">Рейтинг ще порожній</h1>Подивись кілька відео, і він збереться сам.</div>`;
  html += '<div class="ranks">' + rated.map((v, i) => `<a class="rank-row" href="#/i/${v.id}"><span class="n">${i + 1}</span><div class="th" data-scrub="${v.id}">${cover(v)}</div>
    <div class="ri"><div class="ct">${esc(v.title)}</div><div class="minibars">
      <span>Досмотр <i><b style="width:${pct(v.avg)}%"></b></i>${v.avg != null ? pct(v.avg) + '%' : '—'}</span>
      <span>Вертаєшся <i><b style="width:${pct(v.pop)}%"></b></i></span>
      <span>${views(v.views)}${v.vote > 0 ? ', лайк' : v.vote < 0 ? ', дизлайк' : ''}</span></div></div>
    <div class="big">${Math.round(v.score)}</div></a>`).join('') + '</div>';
  if (rest && rated.length) html += `<p class="foot">Ще ${rest} відео без оцінки. Вони з’являться тут, щойно ти їх переглянеш.</p>`;
  app.innerHTML = html;
}

// ── Вікно з інфою про відео ──
function sheetHTML(v, rnd) {
  const has = hasSprite(v);
  const resume = S.cfg.resume && v.pos > 15 && v.dur && v.pos < v.dur * 0.95;
  const sib = S.videos.filter(x => x.folder === v.folder).sort(byName);
  const k = sib.findIndex(x => x.id === v.id);
  const more = sib.slice(k + 1).concat(sib.slice(0, k)).slice(0, 14);
  const framesBlock = has
    ? `<div class="frames" id="shFrames">${Array.from({length: S.N}, (_, i) =>
        `<button class="fcell" data-i="${i}" aria-label="Дивитися з ${fmtDur(frameT(v, i))}"><span class="fimg" style="${frameBg(v, i)}"></span>${fmtDur(frameT(v, i))}</button>`).join('')}</div>`
    : (S.ffmpeg && v.sprite === 0 && v.dur
      ? `<div class="frames">${Array.from({length: 8}, () => '<span class="fcell"><span class="fimg skel"></span></span>').join('')}</div><p class="note">Нарізаю кадри з цього відео, кілька секунд…</p>`
      : `<p class="note">${S.ffmpeg ? 'З цього файлу не вдалося взяти кадри.' : 'Щоб тут з’явились кадри з відео, поклади ffmpeg.exe і ffprobe.exe поруч з vidbox.py і перезапусти VidBox.'}</p>`);
  const vcodec = [v.vc ? v.vc.toUpperCase() : '', v.w ? v.w + '×' + v.h : ''].filter(Boolean).join(', ');
  return `${winBar(`info — <b>${esc(v.file)}</b>`, `<button class="x" data-close aria-label="Закрити (Esc)">${I.close}</button>`)}
  <div class="sh-media"><div class="screen" id="shScreen">${has ? screenLayers : `<div class="cv">${cover(v)}</div>`}</div>
    <a class="btn primary play" href="#/v/${v.id}">${I.play}${resume ? 'Продовжити з ' + fmtDur(v.pos) : 'Дивитися'}</a></div>
  <div class="sh-body">
    <h1 class="title" id="shTitle">${esc(v.title)}</h1>
    <div class="meta">${metaHTML(v, true)}</div>
    ${resume ? `<div class="resume"><span class="pbar"><i style="width:${v.pos / v.dur * 100}%"></i></span><span>Залишилось ${fmtLen(v.dur - v.pos)}</span><a href="#/v/${v.id}/0">${I.restart}З початку</a></div>` : ''}
    <div class="acts">
      <button class="btn icon${v.vote > 0 ? ' on' : ''}" data-vote="1" aria-label="Подобається" aria-pressed="${v.vote > 0}">${I.up}</button>
      <button class="btn icon${v.vote < 0 ? ' on' : ''}" data-vote="-1" aria-label="Не подобається" aria-pressed="${v.vote < 0}">${I.down}</button>
      ${rnd ? `<button class="btn ghost" data-reroll>${I.dice}Інше випадкове</button>` : ''}
    </div>
    <div class="sh-cols">
      <section><h2>Кадри</h2>${framesBlock}</section>
      <aside>
        <section><h2>Рейтинг</h2><div id="shRating">${ratingHTML(v)}</div></section>
        <section><h2>Файл</h2><dl class="file">
          <dt>Назва</dt><dd>${esc(v.file)}</dd>
          <dt>Папка</dt><dd>${esc(v.folder.split('/').join(' / '))}</dd>
          <dt>Формат</dt><dd>${esc(v.ext.toUpperCase())}${v.prep ? (v.ready ? ', є копія MP4 для телефону' : ', для телефону буде копія MP4') : ''}</dd>
          ${vcodec ? `<dt>Відео</dt><dd>${esc(vcodec)}</dd>` : ''}
          ${v.ac ? `<dt>Звук</dt><dd>${esc(v.ac.toUpperCase())}</dd>` : ''}
          <dt>Розмір</dt><dd>${fmtSize(v.size)}</dd>
          <dt>Додано</dt><dd>${fmtDate(v.added)}</dd></dl></section>
      </aside>
    </div>
    ${shelf('Ще з цієї папки', '', more.filter(x => x.id !== v.id))}
  </div>`;
}
function ratingHTML(v) {
  return `<div class="rating"><div class="big">${Math.round(v.score)}<small>зі 100</small></div><div class="bars">
    <div>Досмотр<i><b style="width:${pct(v.avg)}%"></b></i><em>${v.avg != null ? pct(v.avg) + '%' : '—'}</em></div>
    <div>Вертаєшся<i><b style="width:${pct(v.pop)}%"></b></i><em>${pct(v.pop)}%</em></div>
    <div>Твоя оцінка<i><b style="width:${v.vote > 0 ? 100 : v.vote < 0 ? 0 : 50}%"></b></i><em>${v.vote > 0 ? 'лайк' : v.vote < 0 ? 'дизлайк' : '—'}</em></div></div></div>
    <p class="note">${v.views ? `${views(v.views)}, востаннє ${ago(v.last)}.` : 'Ще не дивився. Рейтинг складеться після перегляду.'}</p>`;
}
async function openSheet(id, rnd) {
  if (!S.loaded) await load();
  const v = S.by[id];
  if (!v) { toast('Відео не знайдено'); return closeSheet(); }
  if (sheetViewer) sheetViewer.stop();
  scrubClear();
  sheetId = id; sheetRnd = rnd;
  document.documentElement.classList.add('locked');
  sheet.hidden = false;
  fillSheet(v, rnd);
  panel.scrollTop = 0;
  requestAnimationFrame(() => { sheet.classList.add('open'); panel.focus({preventScroll: true}); });
  if (!hasSprite(v) && S.ffmpeg && v.sprite === 0 && v.dur) {
    api('/api/sprite/' + v.id, {method: 'POST'}).then(r => {
      v.sprite = r.sprite;
      if (sheetId === v.id) { const top = panel.scrollTop; fillSheet(v, rnd); panel.scrollTop = top; }
    }).catch(() => {});
  }
}
function fillSheet(v, rnd) {
  if (sheetViewer) { sheetViewer.stop(); sheetViewer = null; }
  panel.innerHTML = sheetHTML(v, rnd);
  panel.setAttribute('aria-labelledby', 'shTitle');
  if (hasSprite(v)) sheetViewer = frameViewer($('#shScreen', panel), v, $('#shFrames', panel), i => go(`#/v/${v.id}/${Math.floor(frameT(v, i))}`));
  $$('[data-vote]', panel).forEach(b => b.onclick = async () => {
    const val = +b.dataset.vote;
    v.vote = v.vote === val ? 0 : val;
    $$('[data-vote]', panel).forEach(x => { const on = +x.dataset.vote === v.vote; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); });
    const r = await api('/api/vote', {method: 'POST', body: JSON.stringify({id: v.id, vote: v.vote})});
    if (r.ok) { Object.assign(v, {score: r.score, views: r.views, avg: r.avg, cmp: r.cmp, pop: r.pop, last: r.last}); $('#shRating', panel).innerHTML = ratingHTML(v); S.dirty = true; }
  });
  const rr = $('[data-reroll]', panel);
  if (rr) rr.onclick = () => randomVideo(true);
}
function hideSheet() {
  if (!sheetId) return;
  sheetId = null; sheetRnd = false;
  if (sheetViewer) { sheetViewer.stop(); sheetViewer = null; }
  sheet.classList.remove('open');
  document.documentElement.classList.remove('locked');
  setTimeout(() => { if (!sheetId) { sheet.hidden = true; panel.innerHTML = ''; } }, 260);
}
function closeSheet() {
  const st = history.state || {};
  if (st.sheetSteps > 0) history.go(-st.sheetSteps);
  else { history.replaceState({}, '', '#' + (baseHash || '/')); route(); }
}

// ── Плеєр ──
// Власний плеєр замість стандартного: кадри над смугою перемотки, жести, гарячі клавіші,
// швидкість, картинка в картинці, екран «далі», керування з шторки телефона (Media Session).
const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
const PI = {
  play: '<path d="M7 4.5v15l12.5-7.5z"/>',
  pause: '<path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z"/>',
  vol: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  volOff: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>',
  fs: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  fsExit: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
};
const rateLabel = r => (r === 1 ? '1' : String(r).replace('.', ',')) + '×';
let wantFs = false;   // наступне відео відкрити теж на весь екран

function playerHTML(v, next) {
  const pp = `${svg(PI.play, 'solid ic-play')}${svg(PI.pause, 'solid ic-pause')}`;
  return `<div class="vp paused" id="vp" tabindex="-1" aria-label="Відеоплеєр">
  <video id="pv" playsinline preload="metadata"${v.thumb ? ` poster="/thumb/${v.id}?v=${v.thumb}"` : ''}></video>
  <div class="vp-hit"></div>
  <div class="vp-ui">
    <div class="vp-fade vp-top"><div class="vp-title"><b>${esc(v.title)}</b><span>${esc(shortFolder(v.folder))}</span></div></div>
    <div class="vp-fade vp-center">
      <button class="vp-cskip" data-a="back" aria-label="Назад на 10 секунд">${I.back10}</button>
      <button class="vp-big" data-a="play" aria-label="Відтворити або пауза">${pp}</button>
      <button class="vp-cskip" data-a="fwd" aria-label="Вперед на 10 секунд">${I.fwd10}</button>
    </div>
    <div class="vp-spin"></div>
    <div class="vp-tap l"><span>${I.rew}10 с</span></div><div class="vp-tap r"><span>10 с${I.ff}</span></div>
    <div class="vp-badge"></div>
    <div class="vp-toast"></div>
    <div class="vp-fade vp-bottom">
      <div class="vp-seek" role="slider" tabindex="0" aria-label="Перемотування" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
        <div class="vp-rail"><i class="vp-buf"></i><i class="vp-hov"></i><i class="vp-fill"></i><b class="vp-knob"></b></div>
        <div class="vp-pv${hasSprite(v) ? '' : ' notime-img'}"><div class="vp-pv-img"></div><span></span></div>
      </div>
      <div class="vp-row">
        <button class="vp-b" data-a="play" title="Пауза (Пробіл)" aria-label="Відтворити або пауза">${pp}</button>
        <button class="vp-b" data-a="back" title="Назад 10 с (J)" aria-label="Назад на 10 секунд">${I.back10}</button>
        <button class="vp-b" data-a="fwd" title="Вперед 10 с (L)" aria-label="Вперед на 10 секунд">${I.fwd10}</button>
        ${next ? `<button class="vp-b" data-a="next" title="Наступне відео (N)" aria-label="Наступне відео">${I.next}</button>` : ''}
        <div class="vp-vol"><button class="vp-b" data-a="mute" title="Звук (M)" aria-label="Увімкнути або вимкнути звук">${svg(PI.vol, 'ic-vol')}${svg(PI.volOff, 'ic-vol-off')}</button>
          <input type="range" min="0" max="1" step="0.02" aria-label="Гучність"></div>
        <span class="vp-time"><span class="vp-cur">0:00</span> <span class="sep">/</span> <span class="vp-dur">${fmtDur(v.dur)}</span></span>
        <span class="vp-grow"></span>
        <button class="vp-b vp-txt" data-a="quality" title="Якість" aria-label="Якість відео">Авто</button>
        <button class="vp-b vp-txt" data-a="speed" title="Швидкість (Shift + &lt; &gt;)" aria-label="Швидкість відтворення">1×</button>
        <button class="vp-b" data-a="pip" title="Картинка в картинці (P)" aria-label="Картинка в картинці">${I.pip}</button>
        <button class="vp-b" data-a="fs" title="На весь екран (F)" aria-label="На весь екран">${svg(PI.fs, 'ic-fs')}${svg(PI.fsExit, 'ic-fs-exit')}</button>
      </div>
    </div>
    <div class="vp-menu" hidden></div>
    <div class="vp-end" hidden></div>
    <div class="vp-msg" hidden></div>
  </div></div>`;
}

function mountPlayer(vp, v, o) {
  const q = s => vp.querySelector(s);
  const video = q('video'), seek = q('.vp-seek'), rail = q('.vp-rail');
  const fill = q('.vp-fill'), buf = q('.vp-buf'), hov = q('.vp-hov'), knob = q('.vp-knob');
  const pvBox = q('.vp-pv'), pvImg = q('.vp-pv-img'), pvTime = q('.vp-pv span');
  const curEl = q('.vp-cur'), durEl = q('.vp-dur'), volIn = q('.vp-vol input'), speedBtn = q('[data-a=speed]');
  const menu = q('.vp-menu'), endBox = q('.vp-end'), msg = q('.vp-msg'), badge = q('.vp-badge'), vtoast = q('.vp-toast'), hit = q('.vp-hit');
  const touch = matchMedia('(hover: none)').matches;
  let idleT = 0, raf = 0, dragging = false, dead = false, badgeT = 0, toastT2 = 0, endT = 0, holding = false;
  const D = () => (isFinite(video.duration) && video.duration > 0) ? video.duration : (v.dur || 0);
  video.volume = LS.get('vol', 1);
  video.muted = LS.get('muted', false);
  video.defaultPlaybackRate = video.playbackRate = LS.get('rate', 1);

  // ── малювання ──
  const setPos = f => { fill.style.transform = `scaleX(${f})`; knob.style.left = (f * 100) + '%'; };
  function draw() {
    if (dragging) return;
    const d = D(), f = d ? Math.min(1, video.currentTime / d) : 0;
    setPos(f);
    curEl.textContent = fmtDur(video.currentTime);
    seek.setAttribute('aria-valuenow', Math.round(f * 100));
    if (o.onTime) o.onTime(video.currentTime);
  }
  function drawBuf() {
    const d = D(), b = video.buffered;
    let end = 0;
    for (let i = 0; i < b.length; i++) if (b.start(i) <= video.currentTime + 1) end = Math.max(end, b.end(i));
    if (d) buf.style.transform = `scaleX(${Math.min(1, end / d)})`;
  }
  function loop() { draw(); if (!video.paused && !dead) raf = requestAnimationFrame(loop); }
  const stateUI = () => { vp.classList.toggle('playing', !video.paused); vp.classList.toggle('paused', video.paused); };
  const drawVol = () => { vp.classList.toggle('muted', video.muted || video.volume === 0); volIn.value = video.muted ? 0 : video.volume; };
  const drawRate = () => { speedBtn.textContent = rateLabel(video.playbackRate); };

  // ── показ і приховування керування ──
  function poke() {
    vp.classList.remove('idle');
    clearTimeout(idleT);
    if (!video.paused && !dragging && menu.hidden) idleT = setTimeout(() => vp.classList.add('idle'), touch ? 3200 : 2400);
  }
  const hideUI = () => { if (!video.paused) { clearTimeout(idleT); vp.classList.add('idle'); } };
  function showBadge(html, ms) {
    badge.innerHTML = html;
    badge.classList.add('show');
    clearTimeout(badgeT);
    if (ms) badgeT = setTimeout(() => badge.classList.remove('show'), ms);
  }
  function vpToast(text, btn, fn) {
    vtoast.innerHTML = '<span>' + esc(text) + '</span>' + (btn ? `<button>${esc(btn)}</button>` : '');
    if (btn) vtoast.querySelector('button').onclick = e => { e.stopPropagation(); fn(); vtoast.classList.remove('show'); };
    vtoast.classList.add('show');
    clearTimeout(toastT2);
    toastT2 = setTimeout(() => vtoast.classList.remove('show'), btn ? 6000 : 1800);
  }

  // ── дії ──
  const play = () => { if (video.paused) { endBox.hidden = true; video.play().catch(() => {}); } else video.pause(); };
  function skip(s) { video.currentTime = Math.max(0, Math.min(Math.max(0, D() - 0.25), video.currentTime + s)); draw(); }
  function setVol(x) {
    video.volume = Math.max(0, Math.min(1, x));
    video.muted = video.volume === 0;
    showBadge(`${svg(video.muted ? PI.volOff : PI.vol)}${Math.round(video.volume * 100)}%`, 900);
  }
  function setRate(r) { video.playbackRate = video.defaultPlaybackRate = r; LS.set('rate', r); drawRate(); showBadge(rateLabel(r), 800); }
  const fsEl = () => document.fullscreenElement || document.webkitFullscreenElement;
  function toggleFs() {
    if (fsEl()) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
    const req = vp.requestFullscreen || vp.webkitRequestFullscreen;
    if (!req) return iosFs();
    try {
      const p = req.call(vp);
      if (p && p.then) p.then(lockLand).catch(iosFs); else lockLand();
    } catch (e) { iosFs(); }
  }
  function lockLand() { if (touch && screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(() => {}); }
  function iosFs() { if (video.webkitEnterFullscreen) video.webkitEnterFullscreen(); }   // iPhone: системний повноекранний режим
  function onFs() {
    vp.classList.toggle('fs', fsEl() === vp);
    if (!fsEl() && screen.orientation && screen.orientation.unlock) { try { screen.orientation.unlock(); } catch (e) {} }
  }
  const pipOk = (document.pictureInPictureEnabled && video.requestPictureInPicture) ||
    (video.webkitSupportsPresentationMode && video.webkitSupportsPresentationMode('picture-in-picture'));
  if (!pipOk) q('[data-a=pip]').hidden = true;
  function togglePip() {
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {});
    else if (video.requestPictureInPicture && document.pictureInPictureEnabled) video.requestPictureInPicture().catch(() => vpToast('Картинка в картинці зараз недоступна'));
    else if (video.webkitSetPresentationMode) video.webkitSetPresentationMode(video.webkitPresentationMode === 'picture-in-picture' ? 'inline' : 'picture-in-picture');
  }
  function openMenu(kind) {
    menu.dataset.kind = kind;
    menu.innerHTML = kind === 'quality' && o.quality
      ? '<p>Якість</p>' + o.quality.items().map(x => `<button data-q="${x.id}" class="${x.on ? 'on' : ''}"${x.off ? ' disabled' : ''}>${x.name}<small>${esc(x.hint)}</small></button>`).join('')
      : '<p>Швидкість</p>' + RATES.map(r => `<button data-rate="${r}" class="${r === video.playbackRate ? 'on' : ''}">${r === 1 ? 'Звичайна' : rateLabel(r)}</button>`).join('');
    menu.hidden = false;
    clearTimeout(idleT);
    vp.classList.remove('idle');
  }
  const closeMenu = () => { if (!menu.hidden) { menu.hidden = true; poke(); } };
  function flash(side) { const el = q('.vp-tap.' + side); el.classList.remove('go'); void el.offsetWidth; el.classList.add('go'); }
  const act = {
    play, back: () => skip(-10), fwd: () => skip(10),
    mute: () => { video.muted = !video.muted; if (!video.muted && video.volume === 0) video.volume = 0.6; },
    speed: () => (menu.hidden || menu.dataset.kind !== 'speed' ? openMenu('speed') : closeMenu()),
    quality: () => (menu.hidden || menu.dataset.kind !== 'quality' ? openMenu('quality') : closeMenu()),
    pip: togglePip, fs: toggleFs, next: () => { if (o.onNext) { wantFs = !!fsEl(); o.onNext(); } },
  };

  vp.addEventListener('click', e => {
    const r = e.target.closest('[data-rate]');
    if (r) { setRate(+r.dataset.rate); closeMenu(); return; }
    const qb = e.target.closest('[data-q]');
    if (qb) { closeMenu(); if (o.quality) o.quality.pick(qb.dataset.q); return; }
    const b = e.target.closest('[data-a]');
    if (b && act[b.dataset.a]) { act[b.dataset.a](); poke(); return; }
    if (!menu.hidden && !e.target.closest('.vp-menu')) closeMenu();
  });
  vp.addEventListener('mousemove', poke);
  vp.addEventListener('mouseleave', () => { if (!video.paused && !dragging) { clearTimeout(idleT); vp.classList.add('idle'); } });

  // ── клік і жести по самому відео ──
  // Мишка: клік — пауза, подвійний клік — весь екран.
  // Палець: тап — показати/сховати керування, подвійний тап зліва/справа — ±10 с, утримання — 2×.
  let lastTap = 0, tapT = 0, holdT = 0, downX = 0, downY = 0;
  hit.addEventListener('pointerdown', e => {
    downX = e.clientX; downY = e.clientY;
    if (!menu.hidden) return;
    if (e.pointerType === 'mouse') return;
    holdT = setTimeout(() => {
      if (video.paused) return;
      holding = true;
      video.playbackRate = 2;
      showBadge(`2×${I.ff}`);
    }, 480);
  });
  hit.addEventListener('pointermove', e => { if (Math.abs(e.clientX - downX) + Math.abs(e.clientY - downY) > 16) clearTimeout(holdT); });
  const endHold = () => {
    clearTimeout(holdT);
    if (!holding) return false;
    holding = false;
    video.playbackRate = LS.get('rate', 1);
    badge.classList.remove('show');
    return true;
  };
  hit.addEventListener('pointercancel', endHold);
  hit.addEventListener('contextmenu', e => e.preventDefault());
  hit.addEventListener('pointerup', e => {
    if (!menu.hidden) { closeMenu(); return; }
    const now = Date.now();
    if (e.pointerType === 'mouse') {
      if (e.button !== 0) return;
      if (now - lastTap < 280) { lastTap = 0; play(); toggleFs(); } else { lastTap = now; play(); }
      poke();
      return;
    }
    if (endHold()) return;
    const r = vp.getBoundingClientRect(), x = (e.clientX - r.left) / r.width;
    const side = x < 0.35 ? 'l' : x > 0.65 ? 'r' : '';
    clearTimeout(tapT);
    if (side && now - lastTap < 320) {
      lastTap = now;
      skip(side === 'l' ? -10 : 10);
      flash(side);
      return;
    }
    lastTap = now;
    const toggle = () => { if (vp.classList.contains('idle') || video.paused) poke(); else hideUI(); };
    if (side) tapT = setTimeout(toggle, 300); else toggle();
  });

  // ── смуга перемотки з кадрами ──
  const frac = e => { const r = rail.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)); };
  function preview(f) {
    const d = D();
    if (!d) return;
    const r = seek.getBoundingClientRect();
    pvTime.textContent = fmtDur(f * d);
    if (hasSprite(v)) pvImg.style.cssText = frameBg(v, Math.max(0, Math.min(S.N - 1, Math.round((f - 0.03) / 0.94 * (S.N - 1)))));
    const half = hasSprite(v) ? 110 : 34;
    pvBox.style.left = Math.max(half, Math.min(r.width - half, f * r.width)) + 'px';
    pvBox.classList.add('show');
    hov.style.transform = `scaleX(${f})`;
  }
  seek.addEventListener('pointerdown', e => {
    dragging = true;
    try { seek.setPointerCapture(e.pointerId); } catch (err) {}
    vp.classList.add('scrubbing');
    clearTimeout(idleT);
    const f = frac(e);
    preview(f); setPos(f); curEl.textContent = fmtDur(f * D());
  });
  seek.addEventListener('pointermove', e => {
    const f = frac(e);
    if (dragging || e.pointerType === 'mouse') preview(f);
    if (dragging) { setPos(f); curEl.textContent = fmtDur(f * D()); }
  });
  const endDrag = (e, apply) => {
    if (!dragging) return;
    dragging = false;
    vp.classList.remove('scrubbing');
    if (apply) { video.currentTime = frac(e) * D(); endBox.hidden = true; }
    if (e.pointerType !== 'mouse') pvBox.classList.remove('show');
    draw(); poke();
  };
  seek.addEventListener('pointerup', e => endDrag(e, true));
  seek.addEventListener('pointercancel', e => endDrag(e, false));
  seek.addEventListener('pointerleave', () => { if (!dragging) pvBox.classList.remove('show'); });
  volIn.addEventListener('input', () => { video.volume = +volIn.value; video.muted = +volIn.value === 0; });

  // ── події відео ──
  video.addEventListener('play', () => { stateUI(); cancelAnimationFrame(raf); loop(); poke(); endBox.hidden = true; clearTimeout(endT); });
  video.addEventListener('pause', () => { stateUI(); draw(); poke(); });
  video.addEventListener('timeupdate', () => { if (video.paused) draw(); });
  video.addEventListener('seeked', () => { draw(); drawBuf(); });
  video.addEventListener('progress', drawBuf);
  video.addEventListener('durationchange', () => { durEl.textContent = fmtDur(D()); });
  video.addEventListener('waiting', () => vp.classList.add('loading'));
  ['playing', 'canplay', 'seeked', 'pause', 'error'].forEach(ev => video.addEventListener(ev, () => vp.classList.remove('loading')));
  video.addEventListener('volumechange', () => { drawVol(); LS.set('vol', video.volume); LS.set('muted', video.muted); });
  video.addEventListener('ratechange', () => { if (!holding) drawRate(); });
  video.addEventListener('ended', () => { stateUI(); vp.classList.remove('idle'); showEnd(); });
  video.addEventListener('error', () => { if (video.error && video.getAttribute('src') && o.onError) o.onError(video.error.code); });
  document.addEventListener('fullscreenchange', onFs);
  document.addEventListener('webkitfullscreenchange', onFs);

  // ── гарячі клавіші (працюють і в українській розкладці) ──
  function onKey(e) {
    if (dead || e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t.closest && t.closest('input, textarea, select, [contenteditable]') && t !== volIn) return;
    if ((e.code === 'Space' || e.code === 'Enter') && t.closest && t.closest('button, a')) return;
    if (sheetId || !picker.hidden) return;
    let ok = true;
    if (e.shiftKey && (e.code === 'Period' || e.code === 'Comma')) {
      const i = RATES.indexOf(video.playbackRate), n = RATES[Math.max(0, Math.min(RATES.length - 1, (i < 0 ? 2 : i) + (e.code === 'Period' ? 1 : -1)))];
      setRate(n);
    } else switch (e.code) {
      case 'Space': case 'KeyK': play(); break;
      case 'ArrowLeft': skip(-5); showBadge(`${I.rew}5 с`, 600); break;
      case 'ArrowRight': skip(5); showBadge(`5 с${I.ff}`, 600); break;
      case 'KeyJ': skip(-10); showBadge(`${I.rew}10 с`, 600); break;
      case 'KeyL': skip(10); showBadge(`10 с${I.ff}`, 600); break;
      case 'ArrowUp': setVol(video.volume + 0.05); break;
      case 'ArrowDown': setVol(video.volume - 0.05); break;
      case 'KeyM': act.mute(); showBadge(video.muted ? `${svg(PI.volOff)}Без звуку` : `${svg(PI.vol)}${Math.round(video.volume * 100)}%`, 900); break;
      case 'KeyF': toggleFs(); break;
      case 'KeyP': togglePip(); break;
      case 'KeyN': if (o.onNext) act.next(); else ok = false; break;
      case 'Comma': if (video.paused) { video.currentTime = Math.max(0, video.currentTime - 1 / 25); draw(); } break;
      case 'Period': if (video.paused) { video.currentTime += 1 / 25; draw(); } break;
      default:
        if (/^(Digit|Numpad)[0-9]$/.test(e.code)) { video.currentTime = D() * (+e.code.slice(-1)) / 10; draw(); }
        else ok = false;
    }
    if (ok) { e.preventDefault(); poke(); }
  }
  document.addEventListener('keydown', onKey);

  // ── шторка телефона / мультимедійні клавіші ──
  const ms = 'mediaSession' in navigator ? navigator.mediaSession : null;
  const msh = (a, f) => { try { ms.setActionHandler(a, f); } catch (e) {} };
  if (ms) {
    try {
      ms.metadata = new MediaMetadata({title: v.title, artist: shortFolder(v.folder), album: 'VidBox',
        artwork: v.thumb ? [{src: `${location.origin}/thumb/${v.id}?v=${v.thumb}`, sizes: '480x270', type: 'image/jpeg'}] : []});
    } catch (e) {}
    msh('play', () => video.play()); msh('pause', () => video.pause());
    msh('seekbackward', d => skip(-((d && d.seekOffset) || 10))); msh('seekforward', d => skip((d && d.seekOffset) || 10));
    msh('seekto', d => { video.currentTime = d.seekTime; draw(); });
    msh('nexttrack', o.onNext ? () => act.next() : null);
  }

  // ── кінець відео: «далі» з таймером ──
  function showEnd() {
    const n = o.next;
    if (!n) {
      endBox.innerHTML = `<div class="vp-end-card"><div class="vp-end-info"><p>Відео закінчилось</p><b>${esc(v.title)}</b>` +
        `<div class="acts"><button class="btn primary" data-end="replay">${I.restart}Переглянути ще раз</button></div></div></div>`;
    } else {
      const auto = S.cfg.autoplay_next, t = S.cfg.next_delay || 8;
      const bg = n.thumb ? `background-image:url(/thumb/${n.id}?v=${n.thumb})` : (hasSprite(n) ? frameBg(n, 3) : '');
      endBox.innerHTML = `<div class="vp-end-card"><div class="vp-end-th" style="${bg}">${auto ? `<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" class="run" style="--t:${t}s"/></svg>` : ''}</div>
        <div class="vp-end-info"><p>${auto ? `Далі через ${t} с` : 'Далі'}</p><b>${esc(n.title)}</b><div class="acts">
          <button class="btn primary" data-end="next">${I.play}Дивитися</button>${auto ? '<button class="btn" data-end="cancel">Скасувати</button>' : ''}
          <button class="btn ghost" data-end="replay">${I.restart}Ще раз</button></div></div></div>`;
      if (auto) endT = setTimeout(() => { if (!dead) act.next(); }, t * 1000);
    }
    endBox.hidden = false;
  }
  endBox.addEventListener('click', e => {
    const b = e.target.closest('[data-end]');
    if (!b) return;
    e.stopPropagation();
    clearTimeout(endT);
    const a = b.dataset.end;
    if (a === 'next') act.next();
    else if (a === 'replay') { endBox.hidden = true; video.currentTime = 0; video.play().catch(() => {}); }
    else { const ring = q('.vp-end circle'); if (ring) ring.classList.remove('run'); q('.vp-end-info p').textContent = 'Далі'; b.remove(); }
  });

  drawVol(); drawRate(); draw();
  const qBtn = q('[data-a=quality]');
  if (!o.quality) qBtn.hidden = true;
  return {
    video, toast: vpToast, poke,
    setQuality(text) { qBtn.textContent = text; },
    msg(html) { msg.innerHTML = html; msg.hidden = false; vp.classList.remove('loading'); },
    hideMsg() { msg.hidden = true; msg.innerHTML = ''; },
    msgEl: msg,
    enterFs() { const req = vp.requestFullscreen || vp.webkitRequestFullscreen; if (req) { try { const p = req.call(vp); if (p && p.catch) p.catch(() => {}); } catch (e) {} } },
    destroy() {
      dead = true;
      cancelAnimationFrame(raf); clearTimeout(idleT); clearTimeout(endT); clearTimeout(tapT); clearTimeout(holdT);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('fullscreenchange', onFs);
      document.removeEventListener('webkitfullscreenchange', onFs);
      if (document.pictureInPictureElement === video) document.exitPictureInPicture().catch(() => {});
      if (ms) { ['play', 'pause', 'seekbackward', 'seekforward', 'seekto', 'nexttrack'].forEach(a => msh(a, null)); try { ms.metadata = null; } catch (e) {} }
    },
  };
}

// ── якість: потік з перекодуванням на льоту (/live) ──
// Підміняємо час і тривалість на самому <video>: решта плеєра бачить позицію від початку файлу,
// а перемотка просто запитує новий потік з потрібного місця.
function liveAdapter(el, v) {
  const P = HTMLMediaElement.prototype, d = n => Object.getOwnPropertyDescriptor(P, n);
  const CT = d('currentTime'), DU = d('duration'), BU = d('buffered');
  const st = {h: 0, off: 0, pend: null, timer: 0, play: false};
  const go = (t, play) => { st.off = t; st.pend = null; el.src = `/live/${v.id}?h=${st.h}&t=${t.toFixed(2)}`; if (play) el.play().catch(() => {}); };
  Object.defineProperty(el, 'currentTime', {configurable: true,
    get() { return !st.h ? CT.get.call(el) : st.pend != null ? st.pend : st.off + CT.get.call(el); },
    set(x) {
      if (!st.h) { CT.set.call(el, x); return; }
      const t = Math.max(0, Math.min(+x || 0, Math.max(0, (v.dur || 0) - 1)));
      if (st.pend == null) st.play = !el.paused || el.ended;
      st.pend = t;
      clearTimeout(st.timer);
      st.timer = setTimeout(() => go(t, st.play), 300);   // кілька натискань стрілок = один запит
    }});
  Object.defineProperty(el, 'duration', {configurable: true, get() { return st.h ? (v.dur || NaN) : DU.get.call(el); }});
  Object.defineProperty(el, 'buffered', {configurable: true, get() {
    const b = BU.get.call(el);
    return st.h ? {length: b.length, start: i => st.off + b.start(i), end: i => st.off + b.end(i)} : b;
  }});
  return {
    get h() { return st.h; },
    play(h, t) { clearTimeout(st.timer); st.h = h; go(t, true); },
    stop() { clearTimeout(st.timer); st.h = 0; st.pend = null; },
  };
}

const VC_MIME = {av1: 'av01.0.13M.08', hevc: 'hvc1.1.6.L153.B0', h264: 'avc1.640033', vp9: 'vp09.00.51.08'};

/** «Авто»: чи браузер сам потягне файл. Якщо ні або важко (4K без апаратного декодування) — висота для /live. */
async function autoQuality(v) {
  if (!S.ffmpeg) return 0;
  const src = Math.min(v.w || 0, v.h || 0) || v.h || 0;
  const c = navigator.connection;
  if (c && (c.saveData || /(^|-)2g|3g/.test(c.effectiveType || '')) && src > 720) return 720;
  const codec = VC_MIME[(v.vc || '').toLowerCase()];
  if (!codec || !navigator.mediaCapabilities) return 0;
  try {
    const r = await navigator.mediaCapabilities.decodingInfo({type: 'file', video: {
      contentType: `video/mp4; codecs="${codec}"`, width: v.w || 1920, height: v.h || 1080,
      bitrate: v.dur ? Math.round(v.size * 8 / v.dur) : 8e6, framerate: 30}});
    if (!r.supported) return Math.min(1080, Math.max(480, src >= 1080 ? 1080 : src >= 720 ? 720 : 480));
    if (!r.powerEfficient && src > 1080) return 1080;   // напр. 4K AV1 на старому Маку: декодує процесор і смикається
  } catch (e) {}
  return 0;
}

function nextOf(v) {
  const q = queueFor(v);
  if (q) { const nid = q.ids[q.ids.indexOf(v.id) + 1]; return (nid && S.by[nid]) || null; }
  const sib = S.videos.filter(x => x.folder === v.folder).sort(byName);
  const i = sib.findIndex(x => x.id === v.id);
  if (i >= 0 && i < sib.length - 1) return sib[i + 1];
  return S.videos.filter(x => x.id !== v.id && !x.views && x.vote >= 0).sort((a, b) => a._r - b._r)[0] || null;
}
async function renderPlayer(id, startAt) {
  if (!S.loaded) await load();
  if (!S.by[id]) await loadAnimeEp(id);
  const v = S.by[id];
  if (!v) { app.innerHTML = `<div class="empty"><h1 class="title">Відео не знайдено</h1>Можливо, файл перемістили або видалили.<br><br><a class="btn" href="#/">На головну</a></div>`; return; }
  window.scrollTo(0, 0);
  setAtmo(v);
  const next = nextOf(v), has = hasSprite(v), fmt = v.ext.toUpperCase();
  const sib = S.videos.filter(x => x.folder === v.folder).sort(byName);
  const k = sib.findIndex(x => x.id === v.id);
  const q = queueFor(v), qi = q ? q.ids.indexOf(v.id) : -1;
  const more = q ? q.ids.slice(qi + 1).map(i => S.by[i]).filter(Boolean).slice(0, 14)
    : sib.slice(k + 1).concat(sib.slice(0, k)).filter(x => x.id !== v.id).slice(0, 14);
  app.innerHTML = `<div class="theatre">${playerHTML(v, next)}</div>
  <div class="pwrap">${promptLine('~/' + v.folder.split('/').pop(), `mpv "${v.file}"`)}
    <div class="phead"><div><h1 class="title">${esc(v.title)}</h1><div class="meta">${metaHTML(v)}<span>${esc(shortFolder(v.folder))}</span></div></div>
      <div class="acts">
        <button class="btn icon${v.vote > 0 ? ' on' : ''}" data-pvote="1" aria-label="Подобається">${I.up}</button>
        <button class="btn icon${v.vote < 0 ? ' on' : ''}" data-pvote="-1" aria-label="Не подобається">${I.down}</button>
        <a class="btn ghost" href="#/i/${v.id}">${I.info}Інфо</a>
        ${next ? `<a class="btn" href="#/v/${next.id}">${I.next}Далі</a>` : ''}</div></div>
    ${has ? `<section><h2>Кадри</h2><div class="frames compact" id="pvFrames">${Array.from({length: S.N}, (_, i) =>
      `<button class="fcell" data-i="${i}" aria-label="Перейти до ${fmtDur(frameT(v, i))}"><span class="fimg" style="${frameBg(v, i)}"></span>${fmtDur(frameT(v, i))}</button>`).join('')}</div></section>` : ''}
    <p class="keys"><span><kbd>Пробіл</kbd>пауза</span><span><kbd>←</kbd><kbd>→</kbd>5 с</span><span><kbd>J</kbd><kbd>L</kbd>10 с</span><span><kbd>↑</kbd><kbd>↓</kbd>гучність</span>
      <span><kbd>F</kbd>весь екран</span><span><kbd>M</kbd>звук</span><span><kbd>Shift</kbd><kbd>&lt;</kbd><kbd>&gt;</kbd>швидкість</span><span><kbd>0</kbd>…<kbd>9</kbd>перейти</span>${next ? '<span><kbd>N</kbd>наступне</span>' : ''}</p>
    ${q ? `<div class="qbar">${I.list}<span>${q.anime ? `Аніме <a href="#/anime/${q.anime}">` : `Плейлист <a href="#/pl/${q.pl}">`}${esc(q.name)}</a>${q.shuffle ? ', перемішаний' : ''}</span><b>${qi + 1} з ${q.ids.length}</b><button class="btn ghost" id="qexit">${q.anime ? 'Вийти зі серій' : 'Вийти з плейлиста'}</button></div>` : ''}
    ${shelf(q ? 'Далі в плейлисті' : 'Ще з цієї папки', '', more)}
  </div>`;
  const qx = $('#qexit');
  if (qx) qx.onclick = () => { setQueue(null); renderBase(baseHash, true); toast('Плейлист завершено, далі піде наступне з папки'); };

  const vp = $('#vp');
  const strip = $('#pvFrames');
  let litFrame = -1;
  function lightFrame(t) {   // підсвічує кадр у смужці під плеєром, який зараз грає
    if (!strip || !v.dur) return;
    let n = 0;
    for (let i = 0; i < S.N; i++) if (frameT(v, i) <= t + 0.5) n = i;
    if (n === litFrame) return;
    litFrame = n;
    $$('.on', strip).forEach(x => x.classList.remove('on'));
    strip.children[n].classList.add('on');
  }
  let quality = 'auto';
  try { quality = localStorage.getItem('vb_quality') || 'auto'; } catch (e) {}
  const srcH = Math.min(v.w || 0, v.h || 0) || v.h || 0;
  const fitH = want => [1080, 720, 480].find(h => h <= want && h <= Math.max(srcH || want, 480)) || 480;
  const QUALS = [
    {id: 'auto', name: 'Авто', hint: 'Браузер тягне файл — оригінал, ні — перекодування на ПК'},
    {id: 'orig', name: 'Оригінал', hint: [v.res || resLabel(v), (v.vc || '').toUpperCase()].filter(Boolean).join(', ') + ' без перекодування'},
    {id: '1080', name: '1080p', hint: '≈ 6 Мбіт/с, перекодовує ПК'},
    {id: '720', name: '720p', hint: '≈ 3 Мбіт/с'},
    {id: '480', name: '480p', hint: '≈ 1,5 Мбіт/с, коли зв’язок слабкий'},
  ];
  const player = mountPlayer(vp, v, {next, onNext: next ? () => go('#/v/' + next.id, true) : null, onError: onPlayError, onTime: lightFrame,
    quality: {
      items: () => QUALS.map(x => ({...x, on: x.id === quality, off: !S.ffmpeg && !['auto', 'orig'].includes(x.id)})),
      pick: id => { quality = id; try { localStorage.setItem('vb_quality', id); } catch (e) {} reopen(); },
    }});
  const pv = player.video;
  const live = liveAdapter(pv, v);
  if (wantFs) { wantFs = false; player.enterFs(); }
  const sid = Math.random().toString(36).slice(2) + Date.now().toString(36);
  let watched = 0, lastT = null, startPos = null, timer = null, ended = false, dead = false, rawMode = false, captured = !!v.thumb;
  const dur = () => (isFinite(pv.duration) && pv.duration > 0) ? pv.duration : (v.dur || 0);

  $$('[data-pvote]').forEach(b => b.onclick = async () => {
    const val = +b.dataset.pvote;
    v.vote = v.vote === val ? 0 : val;
    $$('[data-pvote]').forEach(x => x.classList.toggle('on', +x.dataset.pvote === v.vote));
    const r = await api('/api/vote', {method: 'POST', body: JSON.stringify({id: v.id, vote: v.vote})});
    if (r.ok) Object.assign(v, {score: r.score, views: r.views, avg: r.avg, cmp: r.cmp, pop: r.pop, last: r.last});
  });
  if (strip) strip.onclick = e => {
    const b = e.target.closest('[data-i]'); if (!b) return;
    if (pv.getAttribute('src')) { pv.currentTime = frameT(v, +b.dataset.i); pv.play().catch(() => {}); window.scrollTo({top: 0, behavior: 'smooth'}); }
  };

  // ── облік перегляду (для рейтингу й «продовжити») ──
  function ping(isEnd) {
    if (startPos == null || (watched < 1 && !isEnd)) return;
    const d = dur();
    const p = {sid, id: v.id, pos: isEnd ? d : pv.currentTime, dur: d, watched: Math.round(watched * 10) / 10, start: startPos, ended: !!isEnd};
    v.pos = (isEnd || (d && p.pos >= d * 0.95)) ? 0 : p.pos;
    v.posAt = Date.now() / 1000;
    S.dirty = true;
    const body = JSON.stringify(p);
    try { if (navigator.sendBeacon && navigator.sendBeacon('/api/ping', new Blob([body], {type: 'application/json'}))) return; } catch (e) {}
    fetch('/api/ping', {method: 'POST', body, headers: {'Content-Type': 'application/json'}, keepalive: true}).catch(() => {});
  }
  function capture() {
    // без ffmpeg обкладинка знімається прямо з плеєра і зберігається на ПК
    try {
      const w = 480, h = Math.round(w * pv.videoHeight / pv.videoWidth) || 270;
      const c = document.createElement('canvas'); c.width = w; c.height = h;
      c.getContext('2d').drawImage(pv, 0, 0, w, h);
      c.toBlob(b => {
        if (b) fetch('/api/thumb/' + v.id, {method: 'POST', body: b, headers: {'Content-Type': 'image/jpeg'}})
          .then(r => r.json()).then(j => { if (j.thumb) v.thumb = j.thumb; }).catch(() => {});
      }, 'image/jpeg', 0.8);
    } catch (e) {}
  }
  function qLabel() { player.setQuality(live.h ? live.h + 'p' : quality === 'auto' ? 'Авто' : 'Ориг.'); }
  async function pickH() {
    if (quality === 'orig') return 0;
    if (/^\d+$/.test(quality)) return S.ffmpeg && (!srcH || srcH > +quality) ? +quality : 0;
    return autoQuality(v);
  }
  function resumeAt() {
    if (startAt != null) return startAt;
    return S.cfg.resume && v.pos > 15 && v.dur && v.pos < v.dur * 0.95 ? v.pos : 0;
  }
  function startLive(h, t) {
    player.hideMsg();
    rawMode = false;
    live.play(fitH(h), t);
    vp.classList.add('loading');
    qLabel();
  }
  async function begin() {
    const h = await pickH();
    if (dead) return;
    const t = resumeAt();
    if (h || (v.prep && !v.ready && S.ffmpeg)) {
      startLive(h || 1080, t);
      if (t && startAt == null) player.toast('Продовжую з ' + fmtDur(t), 'З початку', () => { pv.currentTime = 0; if (watched < 30) startPos = 0; });
    } else if (v.prep && !v.ready) prepareFlow();
    else start('/stream/' + v.id);
  }
  async function reopen() {   // змінили якість: продовжуємо з того самого місця
    const t = pv.getAttribute('src') ? pv.currentTime : resumeAt();
    const h = await pickH();
    if (h) { startLive(h, t); player.toast('Якість: ' + live.h + 'p'); return; }
    live.stop();
    player.hideMsg();
    pv.addEventListener('loadedmetadata', () => { pv.currentTime = t; }, {once: true});
    pv.src = '/stream/' + v.id;
    pv.play().catch(() => {});
    qLabel();
    player.toast('Якість: ' + (quality === 'auto' ? 'авто, оригінал' : 'оригінал'));
  }
  function start(src) {
    live.stop();
    qLabel();
    player.hideMsg();
    pv.addEventListener('loadedmetadata', () => {
      const d = dur();
      if (startAt != null) pv.currentTime = startAt;
      else if (S.cfg.resume && v.pos > 15 && d && v.pos < d * 0.95) {
        pv.currentTime = v.pos;
        player.toast('Продовжую з ' + fmtDur(v.pos), 'З початку', () => { pv.currentTime = 0; if (watched < 30) startPos = 0; });
      }
    }, {once: true});
    pv.src = src;
    vp.classList.add('loading');
    pv.play().catch(() => { vp.classList.remove('loading'); player.poke(); });
  }
  pv.addEventListener('playing', () => { if (startPos == null) startPos = pv.currentTime; lastT = pv.currentTime; });
  pv.addEventListener('timeupdate', () => {
    const t = pv.currentTime;
    if (lastT != null && !pv.seeking && !pv.paused) { const d = t - lastT; if (d > 0 && d < 3) watched += d; }
    lastT = t;
    if (!captured && pv.videoWidth && t > Math.min(5, dur() * 0.1)) { captured = true; capture(); }
  });
  pv.addEventListener('seeking', () => { lastT = null; });
  pv.addEventListener('pause', () => ping(false));
  pv.addEventListener('ended', () => { ended = true; ping(true); });
  timer = setInterval(() => { if (!pv.paused) ping(false); }, 10000);
  const onHide = () => { if (document.visibilityState === 'hidden') ping(false); };
  document.addEventListener('visibilitychange', onHide);
  cleanup = () => {
    dead = true; clearInterval(timer);
    document.removeEventListener('visibilitychange', onHide);
    if (!ended) ping(false);
    player.destroy();
    live.stop();
    pv.pause(); pv.removeAttribute('src'); pv.load();
  };

  // ── формати, які телефон не відкриває: копія MP4 через ffmpeg ──
  player.msgEl.addEventListener('click', e => {
    const b = e.target.closest('[data-m]');
    if (!b) return;
    e.stopPropagation();
    if (b.dataset.m === 'raw') { rawMode = true; start('/stream/' + v.id + '?raw=1'); }
    else prepareFlow(true);
  });
  function prepareFlow(force) {   // force: перекодувати в H.264 навіть HEVC (для старих телефонів)
    if (!S.ffmpeg) {
      player.msg(`<p>Формат ${esc(fmt)} браузер може не відкрити.<small>Поклади ffmpeg.exe поруч з vidbox.py, і VidBox сам конвертуватиме такі файли.</small></p><button class="btn primary" data-m="raw">Спробувати відкрити</button>`);
      return;
    }
    rawMode = false;
    player.msg(`<p>Готую копію у форматі MP4, щоб відео точно відкрилось.<small>Зазвичай це хвилина-дві. Наступного разу відкриється одразу.</small></p>` +
      `<div class="prog"><i id="pg"></i></div><span class="note" id="pgt">В черзі</span><button class="btn ghost" data-m="raw">Відкрити без конвертації</button>`);
    let first = true;
    const poll = async () => {
      if (dead || rawMode) return;
      try {
        const st = await api('/api/prepare/' + v.id + (first && force ? '?mode=h264' : ''), first ? {method: 'POST'} : undefined);
        first = false;
        if (dead || rawMode) return;
        if (st.state === 'ready') { v.ready = true; start('/stream/' + v.id + '?r=' + Date.now()); return; }
        if (st.state === 'error') { $('#pgt').textContent = 'Не вдалося конвертувати: ' + (st.error || 'невідома помилка'); return; }
        $('#pg').style.width = (st.progress * 100).toFixed(1) + '%';
        $('#pgt').textContent = st.state === 'queued' ? 'В черзі' :
          `${Math.round(st.progress * 100)}%${st.enc ? ', ' + (st.enc === 'CPU' ? 'процесор' : st.enc === 'copy' ? 'перепаковую без перекодування' : 'відеокарта ' + st.enc) : ''}${st.fps ? `, ${st.fps} к/с` : ''}`;
      } catch (e) {}
      setTimeout(poll, 1200);
    };
    poll();
  }
  function onPlayError() {
    if (live.h) { live.stop(); prepareFlow(true); return; }   // потік не пішов — готуємо копію
    if (S.ffmpeg) { startLive(1080, pv.currentTime || resumeAt()); return; }   // браузер не тягне файл — перекодування на льоту
    if (S.ffmpeg && !v.ready) {
      player.msg(`<p>Браузер не зміг відтворити цей файл.<small>VidBox може зробити сумісну копію MP4 через ffmpeg.</small></p><button class="btn primary" data-m="prep">Зробити сумісну копію</button>`);
    } else {
      player.msg(`<p>Браузер не зміг відтворити цей файл.<small>${S.ffmpeg ? 'Спробуй відкрити його на комп’ютері або в іншому браузері.' : 'Поклади ffmpeg.exe поруч з vidbox.py, і VidBox зможе робити сумісні копії.'}</small></p>`);
    }
  }
  begin();
}

// обкладинки й нарізки, які ще готуються на ПК, підтягуються самі
setInterval(async () => {
  if (!(S.pending || S.spritesPending) || document.hidden || (baseHash || '').startsWith('/v/')) return;
  try { await load(); } catch (e) { return; }
  $$('[data-ph]').forEach(el => {
    const v = S.by[el.dataset.ph];
    if (v && (v.thumb || hasSprite(v))) el.outerHTML = cover(v);
  });
}, 6000);

pollStatus().then(route, route);
