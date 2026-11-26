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
  upload: svg('<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M4.5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V15"/>'),
  download: svg('<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M4.5 15v3.5a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V15"/>'),
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
    if (d.cfg.hataTheme) { S.hataTheme = d.cfg.hataTheme; LS.set('hataTheme', d.cfg.hataTheme); }
    if (d.cfg.theme && (d.cfg.theme !== S.themeSel || realTheme(d.cfg.theme) !== document.documentElement.dataset.theme)) applyTheme(d.cfg.theme);
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
  // схеми панелі Хати
  {id: 'chai', name: 'Чай', hint: 'Хата: теплий темний з м’ятним', bg: '#161511', p: '#1d1b16', a: '#7cc6b1', a2: '#e3c16f', hata: 1},
  {id: 'nich', name: 'Ніч', hint: 'Хата: глибокий синій', bg: '#181825', p: '#1e1e2e', a: '#89b4fa', a2: '#cba6f7', hata: 1},
  {id: 'lain', name: 'lain', hint: 'Хата: холодний сірий, як у Lain', bg: '#16181e', p: '#1c1e25', a: '#b4c3f0', a2: '#e8a0b4', hata: 1},
  {id: 'yahoda', name: 'Ягода', hint: 'Хата: ягідний з рожевим', bg: '#220c1b', p: '#2a1022', a: '#f4a6d7', a2: '#c9a4f5', hata: 1},
  {id: 'nothing', name: 'nothing', hint: 'Хата: чорний і білий з червоним', bg: '#000000', p: '#0a0a0a', a: '#f2f2f2', a2: '#e8352f', hata: 1},
  {id: 'papir', name: 'Папір', hint: 'Хата: світла, як папір', bg: '#e9e1cf', p: '#f3ecdc', a: '#2f7d6d', a2: '#946a0c', hata: 1},
];
// «Як у Хаті»: тема йде за схемою, вибраною в панелі Хати (сервер підказує, яка вона зараз)
const realTheme = id => id === 'hata' ? (S.hataTheme || LS.get('hataTheme', 'chai')) : id;
function applyTheme(id) {
  S.themeSel = id;
  const t = THEMES.find(x => x.id === realTheme(id)) || THEMES[0];
  document.documentElement.dataset.theme = t.id;
  LS.set('theme', t.id);
  const mc = $('meta[name=color-scheme]');
  if (mc) mc.content = t.id === 'papir' ? 'light' : 'dark';
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
  const onPlayer = /^\/(v|r)\//.test(baseHash || '');
  if (e.key === '/' || e.code === 'Slash') { e.preventDefault(); $('#q').focus(); return; }
  if (onPlayer) return;
  if (/^Digit[1-7]$/.test(e.code)) { e.preventDefault(); go(['#/', '#/lib', '#/anime', '#/manga', '#/pl', '#/top', '#/settings'][+e.code.slice(5) - 1]); }
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
  const tab = parts[0] === 'v' ? '' : parts[0] === 'r' ? 'manga' : (parts[0] || 'home');
  $$('[data-tab]').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
  shelfN = 0;
  try {
    if (parts[0] === 'v') await renderPlayer(parts[1], parts[2] != null ? +parts[2] : null);
    else if (parts[0] === 'lib') await renderLib();
    else if (parts[0] === 'top') await renderTop();
    else if (parts[0] === 'anime') await (parts[1] ? renderAnimeTitle(parts[1]) : renderAnime());
    else if (parts[0] === 'manga') await (parts[1] ? renderMangaTitle(parts[1]) : renderManga());
    else if (parts[0] === 'r') await renderReader(parts[1], parts[2] != null ? +parts[2] : null);
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
    ${(() => {
      const card = (t, id, name, hint) => `<button class="theme${st.theme === id ? ' on' : ''}" data-theme-pick="${id}" aria-pressed="${st.theme === id}" ` +
        `style="--t-bg:${t.bg};--t-p:${t.p};--t-a:${t.a};--t-a2:${t.a2}"><span class="tp"><i></i><i></i><i></i></span><b>${name}</b><small>${hint}</small></button>`;
      const now = THEMES.find(t => t.id === (st.hataTheme || 'chai'));
      return `<div class="themes">${THEMES.filter(t => !t.hata).map(t => card(t, t.id, t.name, t.hint)).join('')}</div>
        <h3 class="themes-h">Схеми Хати</h3>
        <div class="themes">${st.hataTheme ? card(now, 'hata', 'Як у Хаті', `Зараз «${esc(now.name)}». Змінюєш схему в панелі — VidBox теж`) : ''}${THEMES.filter(t => t.hata).map(t => card(t, t.id, t.name, t.hint.replace(/^Хата: /, ''))).join('')}</div>`;
    })()}
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
  <section class="set win">${winBar('~/.config/vidbox/манга')}<div class="win-body"><h2>Манга</h2>
    <p class="note" style="margin-top:0">Читалка з обкладинками: кожна підпапка або архів .zip/.cbz — тайтл, картинки — сторінки, підпапки й архіви всередині — розділи. Обкладинки й описи — з AniList, а якщо там немає — з MangaUpdates.</p>
    ${st.manga_folder ? `<div class="flist"><div class="frow">${I.folder}<div><b>${esc(st.manga_folder)}</b><small>${st.mangaExists ? `${st.mangaTitles} ${plural(st.mangaTitles, 'тайтл', 'тайтли', 'тайтлів')} · ${st.mangaChapters} ${plural(st.mangaChapters, 'розділ', 'розділи', 'розділів')}` : 'Папку не знайдено. Можливо, диск від’єднано.'}</small></div>` +
      `<button class="btn ghost" id="mangaReset" title="Скинути опис і обкладинки з інтернету для всіх тайтлів">Скинути дані</button>` +
      `<button class="btn ghost icon" id="mangaRe" title="Переглянути папку заново" aria-label="Переглянути папку з мангою заново">${I.refresh}</button><button class="btn ghost icon" id="mangaoff" title="Прибрати папку з мангою" aria-label="Прибрати папку з мангою">${I.trash}</button></div></div>`
    : `${(st.mangaSuggest || []).length ? `<div class="msug"><span>Знайшов:</span>${st.mangaSuggest.map(p => `<button class="btn" data-msug="${esc(p)}">${I.plus}${esc(p)}</button>`).join('')}</div>` : ''}
      <div class="fadd"><input id="mangaf" type="text" placeholder="Шлях до папки з мангою, наприклад /srv/disks/disk/IMG.Manga" aria-label="Шлях до папки з мангою">
      <button class="btn" id="mangaBrowse">${I.folder}Огляд</button><button class="btn primary" id="mangaset">${I.plus}Додати</button></div>`}
    <p class="warn" id="merr" hidden></p>
  </div></section>
  <section class="set win" id="aiSet">${winBar('~/.config/vidbox/субтитри-ші')}<div class="win-body"><h2>Субтитри ШІ</h2><div id="aiBody"><p class="note">Завантажую…</p></div></div></section>
  <section class="set win" id="glSet">${winBar('~/.config/vidbox/глосарій')}<div class="win-body"><h2>Глосарій</h2><div id="glMain"></div></div></section>
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

  drawAiSet();
  glossPanel($('#glMain'), '_');
  const setManga = async a => {
    const r = await api('/api/settings', {method: 'POST', body: JSON.stringify({manga_folder: a})});
    const e = $('#merr');
    if (!r.ok) { e.textContent = r.error || 'Не вдалося зберегти'; e.hidden = false; return; }
    e.hidden = true;
    toast(a ? 'Папку з мангою додано, переглядаю…' : 'Розділ манги вимкнено. Самі файли не видаляються');
    setTimeout(() => { if (baseHash === '/settings') renderBase('/settings', true); }, 1500);
  };
  const addManga = () => { const v = $('#mangaf').value.trim(); if (!v) { $('#mangaf').focus(); return toast('Введи шлях або натисни «Огляд»'); } setManga(v); };
  if ($('#mangaset')) $('#mangaset').onclick = addManga;
  if ($('#mangaf')) $('#mangaf').onkeydown = e => { if (e.key === 'Enter') addManga(); };
  if ($('#mangaBrowse')) $('#mangaBrowse').onclick = () => openPicker('', path => { $('#mangaf').value = path; });
  $$('[data-msug]').forEach(b => b.onclick = () => setManga(b.dataset.msug));
  if ($('#mangaoff')) $('#mangaoff').onclick = () => { if (confirm('Прибрати папку з мангою? Розділ «Манга» стане порожнім, файли на диску лишаться, прогрес читання збережеться.')) setManga(''); };
  if ($('#mangaReset')) $('#mangaReset').onclick = async () => {
    if (!confirm('Скинути опис, теги й обкладинки з інтернету для ВСІХ тайтлів манги? Обкладинками стануть перші сторінки, автоматично VidBox більше не шукатиме. Для окремого тайтлу пошук можна повернути на його сторінці. Прогрес читання не зміниться.')) return;
    const r = await api('/api/manga/reset', {method: 'POST', body: JSON.stringify({all: true})});
    toast(r.ok ? `Скинуто для ${r.n} ${plural(r.n, 'тайтлу', 'тайтлів', 'тайтлів')}` : (r.error || 'Не вдалося'));
  };
  if ($('#mangaRe')) $('#mangaRe').onclick = async () => { const r = await api('/api/manga/rescan', {method: 'POST', body: '{}'}); toast(`Знайдено ${r.titles} ${plural(r.titles, 'тайтл', 'тайтли', 'тайтлів')}`); renderBase('/settings', true); };
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
  // Для Intel показуємо й саму помилку ffmpeg: з нею одразу видно, чого бракує (драйвера, доступу до відеоядра…)
  const detail = (k, e) => !e.ok && e.err && !/немає в цій збірці/.test(e.err) && (k === 'vaapi' || k === 'intel') && /intel/i.test(hw.gpu || '')
    ? `<br><small class="mono" style="opacity:.75">${esc(e.err.slice(-160))}</small>` : '';
  const list = Object.keys(encs).map(k => `<dt>${names[k] || k}</dt><dd class="${encs[k].ok ? 'ok' : 'no'}" title="${esc(encs[k].err || '')}">${encs[k].ok ? '✓ працює' + (encs[k].lp ? ' (енергоощадний режим)' : '') : '✗ ' + why(encs[k])}${detail(k, encs[k])}</dd>`).join('');
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
const animeSrc = m => m.src === 'web' ? (m.site || 'сайту') : 'AniList';
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
    ${t.meta && t.meta.desc ? `<details class="adesc"><summary>Опис з ${esc(animeSrc(t.meta))}</summary><p>${esc(t.meta.desc).replace(/\n/g, '<br>')}</p><a href="${esc(t.meta.url)}" target="_blank" rel="noopener">Відкрити на ${esc(animeSrc(t.meta))}</a></details>` : ''}
    <ol class="eps">${t.eps.map(e => {
      const pct = e.dur && e.pos > 5 && !e.done ? Math.min(100, e.pos / e.dur * 100) : 0;
      return `<li><button class="ep${e.id === startId ? ' cur' : ''}${e.done ? ' done' : ''}" data-ep="${e.id}">
        <span class="thumb">${e.thumb ? `<img decoding="async" src="/thumb/${e.id}?v=${e.thumb}" alt="">` : ''}${pct ? `<span class="pbar"><i style="width:${pct}%"></i></span>` : ''}</span>
        <span class="n">${e.ep}</span><span class="et"><b>Серія ${e.ep}${e.etitle ? ' · ' + esc(e.etitle) : ''}</b><small>${e.dur ? fmtLen(e.dur) : ''}${e.done ? ' · переглянуто' : pct ? ` · залишилось ${fmtLen(e.dur - e.pos)}` : ''}</small></span></button></li>`;
    }).join('')}</ol>`;
  app.insertAdjacentHTML('beforeend', `<section class="msrc"><p>${t.meta ? `Постер і опис з <a href="${esc(t.meta.url)}" target="_blank" rel="noopener">${esc(animeSrc(t.meta))}</a>.` : 'AniList цей тайтл поки не знайшов.'}
      ${t.meta ? 'Не той тайтл?' : 'Знаєш, де він є?'} Встав посилання з AniList, MyAnimeList, Shikimori чи іншого сайту або точну назву.</p>
      <div class="fadd"><input id="alink" type="text" value="${esc(t.hint || '')}" placeholder="https://anilist.co/anime/…, https://myanimelist.net/anime/…, будь-яке посилання або назва" aria-label="Посилання на сторінку тайтлу або назва"><button class="btn" id="alinkset">Шукати</button></div></section>`);
  $('#alinkset').onclick = async () => {
    const r = await api('/api/anime/link', {method: 'POST', body: JSON.stringify({sid, link: $('#alink').value.trim()})});
    if (!r.ok) return toast(r.error || 'Не вдалося');
    toast('Шукаю. Постер і опис з’являться за кілька секунд');
    setTimeout(() => { if (baseHash === '/anime/' + sid) renderBase(baseHash, true); }, 6000);
  };
  $('#alink').onkeydown = e => { if (e.key === 'Enter') $('#alinkset').click(); };
  $('#aplay').onclick = () => playAnime(t, startId);
  api('/api/aisubs').then(st => {
    if (!st || !st.ready || !$('#aplay')) return;
    $('#aplay').parentElement.insertAdjacentHTML('beforeend', `<button class="btn ghost" id="aisubs" title="Зробити українські субтитри ШІ для всіх серій">Субтитри ШІ</button><button class="btn ghost" id="agloss" title="Підказки для перекладу цього аніме">Глосарій</button>`);
    $('#agloss').onclick = () => {
      if ($('#aglossBox')) return $('#aglossBox').remove();
      $('#aplay').parentElement.insertAdjacentHTML('afterend', `<section id="aglossBox" class="set win" style="margin:16px 0">${winBar(`~/anime/${esc(t.title)}/глосарій`)}<div class="win-body"><h2>Глосарій</h2><div id="aglossBody"></div>
        <div class="srow"><div class="sl"><b>Субтитри ШІ цього аніме</b><small>Оригінальні субтитри у відео не зачіпаються.</small></div><div class="sc"><button class="btn ghost" id="aiRedoAll" title="Видалити й одразу перекласти заново — разом з аналізом серій">Перекласти заново</button><button class="btn ghost" id="aiDelAll">${I.trash}Видалити для всіх серій</button></div></div></div></section>`);
      glossPanel($('#aglossBody'), t.sid, t.title);
      $('#aiRedoAll').onclick = async () => {
        if (!confirm('Видалити готові субтитри ШІ цього аніме й одразу перекласти їх заново? Аналіз серій і «Знайдено автоматично» в глосарії зберуться наново; твої записи в глосарії лишаться.')) return;
        const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify({op: 'redo', sid: t.sid})});
        toast(!r.ok ? 'Не вдалося' : r.count ? `${r.count} ${plural(r.count, 'серія', 'серії', 'серій')} знову в черзі` + (r.glossCleared ? ' · автоглосарій очищено' : '') : 'Готових субтитрів ШІ тут ще немає');
      };
      $('#aiDelAll').onclick = async () => {
        if (!confirm('Видалити українські й інші субтитри ШІ всіх серій цього аніме? Оригінальні субтитри у відео не зачіпаються.')) return;
        const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify({op: 'delete', sid: t.sid})});
        toast(r.ok ? 'Субтитри ШІ видалено' : 'Не вдалося');
      };
    };
    $('#aisubs').onclick = async () => {
      if (!confirm(`Зробити українські субтитри для ${t.eps.length} ${plural(t.eps.length, 'серії', 'серій', 'серій')}? Це у фоні, орієнтовно 15–40 хв на серію.`)) return;
      const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify({op: 'add', ids: t.eps.map(e => e.id)})});
      toast(r.ok ? 'Додав у чергу. Хід видно в Налаштуваннях → «Субтитри ШІ»' : 'Не вдалося');
    };
  }).catch(() => {});
  $$('[data-ep]').forEach(b => b.onclick = () => playAnime(t, b.dataset.ep));
}

// ── манга ──
// Бібліотека з обкладинками, сторінка тайтлу з розділами й читалка: справа наліво (як у японській манзі),
// зліва направо, стрічкою або розворотом. Прогрес зберігається на сервері, тож продовжити можна з будь-якого пристрою.
const MG = {filter: LS.get('mfilter', 'all'), sort: LS.get('msort', 'name')};
const MG_MODES = [['rtl', '← По сторінці', 'Справа наліво, як у японській манзі'], ['ltr', 'По сторінці →', 'Зліва направо'],
  ['strip', 'Стрічка', 'Усі сторінки вниз одна за одною'], ['spread', 'Розворот', 'Дві сторінки поруч, справа наліво']];
const MG_STATUS = {FINISHED: 'завершена', RELEASING: 'виходить', NOT_YET_RELEASED: 'анонс', CANCELLED: 'скасована', HIATUS: 'на паузі'};
const MG_FMT = {MANGA: 'манга', ONE_SHOT: 'ваншот', NOVEL: 'ранобе', Manga: 'манга', Manhwa: 'манхва', Manhua: 'маньхуа', Doujinshi: 'доджінші'};
const mgState = t => t.read >= t.n ? 'done' : (t.lastAt ? 'reading' : 'none');
const chPos = c => c.label + (c.pages > 1 ? ` · стор. ${c.page} / ${c.pages}` : '');
function mgProgress(t) {
  if (t.single) return t.cont ? t.cont.page / t.cont.pages : (t.read ? 1 : 0);
  return Math.min(1, (t.read + (t.cont && t.cont.pages ? (t.cont.page - 1) / t.cont.pages : 0)) / t.n);
}
// томи, зібрані з окремих тек, називаємо томами, а не розділами
const mgUnits = (t, n) => `${n} ${t.vols ? plural(n, 'том', 'томи', 'томів') : plural(n, 'розділ', 'розділи', 'розділів')}`;
function mgSub(t) {
  if (t.read >= t.n) return t.single ? `${t.pages} стор. · прочитано` : `${mgUnits(t, t.n)} · прочитано`;
  if (t.single) return t.cont ? `стор. ${t.cont.page} / ${t.pages}` : `${t.pages} ${plural(t.pages, 'сторінка', 'сторінки', 'сторінок')}`;
  return t.lastAt ? `${t.vols ? 'т.' : 'гл.'} ${t.read} / ${t.n}` : mgUnits(t, t.n);
}
const mangaCard = t => {
  const p = mgProgress(t), st = mgState(t);
  const badge = t.new ? `<span class="aep">+${t.new} ${plural(t.new, 'нова', 'нові', 'нових')}</span>` : st === 'done' ? '<span class="aep done">✓ прочитано</span>' : '';
  return `<a class="acard" href="#/manga/${t.tid}"><div class="poster"><img loading="lazy" decoding="async" src="${t.cover}" alt="" onerror="this.remove()"><span class="ph">${esc((t.title.trim()[0] || '?').toUpperCase())}</span>
    ${badge}${p > 0 && st !== 'done' ? `<span class="pbar"><i style="width:${(p * 100).toFixed(1)}%"></i></span>` : ''}</div>
    <b>${esc(t.title)}</b><small>${t.meta && t.meta.year ? t.meta.year + ' · ' : ''}${mgSub(t)}</small></a>`;
};
const mgRead = (cid, page) => `#/r/${cid}${page > 1 ? '/' + page : ''}`;
function contCard(t) {
  const c = t.cont, p = c.pages ? (c.page - 1) / c.pages : 0;
  return `<a class="mcont" href="${mgRead(c.cid, c.page)}"><span class="poster"><img loading="lazy" decoding="async" src="${t.cover}" alt="" onerror="this.remove()"><span class="ph">${esc((t.title.trim()[0] || '?').toUpperCase())}</span></span>
    <span class="mc-t"><b>${esc(t.title)}</b><small>${esc(t.single ? `стор. ${c.page} / ${c.pages}` : `${c.label} · стор. ${c.page} / ${c.pages}`)}</small>
    <span class="mc-bar"><i style="width:${(p * 100).toFixed(1)}%"></i></span><em>${esc(ago(t.lastAt))}</em></span></a>`;
}
const MG_FILTERS = [['all', 'Усі'], ['reading', 'Читаю'], ['new', 'Нові розділи'], ['done', 'Прочитано'], ['none', 'Не почато']];
const MG_SORTS = {name: ['за назвою', byName], last: ['нещодавно читані', (a, b) => b.lastAt - a.lastAt || byName(a, b)],
  added: ['нещодавно додані', (a, b) => b.added - a.added || byName(a, b)], size: ['найдовші', (a, b) => b.pages - a.pages || byName(a, b)]};
async function renderManga() {
  const d = await api('/api/manga');
  const head = `${promptLine('~/манга', 'ls')}<div class="page-head"><h1 class="title">Манга</h1>${d.titles.length ? `<span class="count">${d.titles.length}</span>` : ''}</div>`;
  if (!d.folder || d.missing) {
    app.innerHTML = head + `<div class="empty"><p>${d.missing ? `Папку <code>${esc(d.folder)}</code> не знайдено. Можливо, диск від’єднано.` : 'Вкажи папку з мангою в налаштуваннях. Кожна підпапка або архів .zip/.cbz у ній стане тайтлом, а картинки — сторінками.'}</p><br><a class="btn primary" href="#/settings">Відкрити налаштування</a></div>`;
    return;
  }
  if (!d.titles.length) {
    app.innerHTML = head + `<div class="empty"><p>${d.scanning ? 'Переглядаю папку…' : `У папці <code>${esc(d.folder)}</code> поки немає манги. Поклади кожен тайтл в окрему підпапку з картинками.`}</p></div>`;
    if (d.scanning) setTimeout(() => { if (baseHash === '/manga') renderBase('/manga', true); }, 2500);
    return;
  }
  const cont = d.titles.filter(t => t.cont && t.lastAt).sort((a, b) => b.lastAt - a.lastAt).slice(0, 6);
  app.innerHTML = head + `<p class="lead mstat">${d.titles.length} ${plural(d.titles.length, 'тайтл', 'тайтли', 'тайтлів')} · ${d.chapters} ${plural(d.chapters, 'розділ', 'розділи', 'розділів')} · <code>${esc(d.folder)}</code></p>` +
    (cont.length ? `<section class="ashelf"><h2>Продовжити читати</h2><div class="mconts">${cont.map(contCard).join('')}</div></section>` : '') +
    `<section class="ashelf"><div class="mtools"><div class="chips" role="group" aria-label="Фільтр">${MG_FILTERS.map(([k, l]) =>
      `<button class="chip${MG.filter === k ? ' on' : ''}" data-mf="${k}" aria-pressed="${MG.filter === k}">${l}<span class="n"></span></button>`).join('')}</div>
      <label class="sel"><span class="sr">Сортування</span><select id="msort">${Object.entries(MG_SORTS).map(([k, [l]]) => `<option value="${k}"${MG.sort === k ? ' selected' : ''}>${l}</option>`).join('')}</select>${I.chev}</label></div>
      <div class="agrid" id="mgrid"></div></section>`;
  const draw = () => {
    const pass = t => MG.filter === 'all' || (MG.filter === 'new' ? t.new > 0 : mgState(t) === MG.filter);
    $$('[data-mf]').forEach(b => { const k = b.dataset.mf; $('.n', b).textContent = k === 'all' ? '' : ' ' + d.titles.filter(t => k === 'new' ? t.new > 0 : mgState(t) === k).length; });
    const list = d.titles.filter(pass).sort(MG_SORTS[MG.sort][1]);
    $('#mgrid').innerHTML = list.length ? list.map(mangaCard).join('') : `<p class="note">Тут поки порожньо.</p>`;
  };
  draw();
  $$('[data-mf]').forEach(b => b.onclick = () => {
    MG.filter = b.dataset.mf; LS.set('mfilter', MG.filter);
    $$('[data-mf]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
    draw();
  });
  $('#msort').onchange = e => { MG.sort = e.target.value; LS.set('msort', MG.sort); draw(); };
}
function mangaMeta(t) {
  const m = t.meta;
  if (!m) return '';
  const alt = [m.english, m.romaji, m.native, ...(m.alt || [])].filter((x, i, a) => x && x !== t.title && a.indexOf(x) === i).slice(0, 3);
  const row = [m.year, MG_FMT[m.format] || m.format, m.chapters ? `${m.chapters} ${plural(m.chapters, 'розділ', 'розділи', 'розділів')}` : m.volumes ? `${m.volumes} т.` : '',
    MG_STATUS[m.status] || m.status, m.score ? `★ ${(m.score / 10).toFixed(1).replace('.', ',')}` : ''].filter(Boolean).map(x => `<span class="tag">${esc(x)}</span>`).join('');
  const who = [['автор', m.artists], ['серія', m.series], ['персонажі', m.characters]].filter(([, v]) => v && v.length)
    .map(([k, v]) => `<span><em>${k}</em> ${v.map(esc).join(', ')}</span>`);
  if (m.lang) who.push(`<span><em>мова</em> ${esc(m.lang)}</span>`);
  return (alt.length ? `<p class="aalt">${alt.map(esc).join(' · ')}</p>` : '') + (who.length ? `<p class="mwho">${who.join('')}</p>` : '') +
    `<div class="ameta">${row}${(m.genres || []).map(g => `<span class="tag ghost">${esc(g)}</span>`).join('')}</div>`;
}
const mgSrc = m => ({anilist: 'AniList', mangaupdates: 'MangaUpdates', hitomi: 'Hitomi'})[m.src] || m.site || 'сайту';
async function setMangaMode(tid, mode) {
  await api('/api/manga/mode', {method: 'POST', body: JSON.stringify({tid, mode})}).catch(() => null);
}
async function renderMangaTitle(tid) {
  const t = await api('/api/manga/t/' + tid).catch(() => null);
  if (!t || !t.chapters) { app.innerHTML = `<div class="empty"><h1 class="title">Тайтл не знайдено</h1><br><a class="btn" href="#/manga">До манги</a></div>`; return; }
  const c = t.cont, first = t.chapters[0];
  const label = c ? (t.single ? `Продовжити <em>стор. ${c.page}</em>` : `Продовжити <em>${esc(c.label)} · стор. ${c.page}</em>`) : t.read >= t.n ? 'Читати ще раз' : 'Почати читати';
  const segs = Math.min(30, Math.max(10, t.n)), p = mgProgress(t);
  const src = t.meta ? mgSrc(t.meta) : '';
  const desc = t.meta && t.meta.desc;
  app.innerHTML = `${promptLine('~/манга/' + t.title, 'ls')}
    <a class="mback" href="#/manga">${I.left}манга</a>
    <div class="ahead mhead"><div class="poster big"><img src="${t.cover}" alt="" onerror="this.remove()"><span class="ph">${esc((t.title.trim()[0] || '?').toUpperCase())}</span></div>
    <div class="ainfo"><h1 class="title">${esc(t.title)}</h1>${mangaMeta(t)}
      ${desc ? `<p class="mdesc" id="mdesc">${esc(desc).replace(/\n/g, '<br>')}</p>${desc.length > 260 ? '<button class="linkbtn" id="mmore">Детальніше</button>' : ''}` : ''}
      <div class="acts"><a class="btn primary" href="${c ? mgRead(c.cid, c.page) : mgRead(first.cid)}">${I.play}${label}</a>${c ? `<a class="btn ghost" href="${mgRead(first.cid)}">З початку</a>` : ''}</div>
      <div class="mmode" role="group" aria-label="Як читати цей тайтл"><span>читати</span>${MG_MODES.map(([k, l, h]) =>
        `<button class="${t.mode === k ? 'on' : ''}" data-mm="${k}" title="${h}" aria-pressed="${t.mode === k}">${l}</button>`).join('')}</div>
      <div class="mprog"><div><span>${t.single ? (c ? `стор. ${c.page} з ${t.pages}` : `${t.pages} ${plural(t.pages, 'сторінка', 'сторінки', 'сторінок')}`) : `прочитано ${t.read} з ${t.n}`}</span><span>${Math.round(p * 100)}%</span></div>
        <span class="msegs" aria-hidden="true">${Array.from({length: segs}, (_, i) => `<i class="${(i + 1) / segs <= p + 1e-9 ? 'on' : (i / segs < p ? 'part' : '')}"></i>`).join('')}</span></div>
    </div></div>
    ${t.single ? '' : `<section class="win mch">${winBar('~/манга/' + esc(t.folder))}<div class="win-body">
      <div class="mch-head"><h2>${t.vols ? 'Томи' : 'Розділи'}</h2><span class="count">${t.n}</span><span class="sp"></span>
        <button class="btn ghost" id="mflip">${MG.newest ? I.arrDown + 'нові зверху' : I.arrUp + 'з першої'}</button></div>
      <ol class="mlist" id="mlist"></ol></div></section>`}
    <section class="msrc"><p>${t.meta ? `Дані з <a href="${esc(t.meta.url)}" target="_blank" rel="noopener">${esc(src)}</a>${t.meta.src === 'hitomi' ? ', обкладинка — своя (cover.jpg або перша сторінка)' : ''}.`
        : t.reset ? 'Дані скинуто: опису немає, обкладинка — перша сторінка, автоматично VidBox більше не шукає.' : 'AniList і MangaUpdates цей тайтл поки не знайшли, тому обкладинка — перша сторінка.'}
      ${t.meta ? 'Не той тайтл?' : 'Знаєш, де він є?'} Встав посилання з AniList, MangaUpdates, Hitomi чи іншого сайту або точну назву${t.reset ? ' (порожнє поле — шукати автоматично, як раніше)' : ''}.</p>
      <div class="fadd"><input id="mlink" type="text" value="${esc(t.hint)}" placeholder="https://anilist.co/manga/…, https://hitomi.la/…, будь-яке посилання або назва" aria-label="Посилання на сторінку тайтлу або назва"><button class="btn" id="mlinkset">Шукати</button></div>
      ${t.reset ? '' : `<button class="btn ghost" id="mreset" style="margin-top:12px">${I.trash}Скинути дані</button>`}</section>`;
  $$('[data-mm]').forEach(b => b.onclick = () => {
    $$('[data-mm]').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', x === b); });
    setMangaMode(tid, b.dataset.mm);
  });
  if ($('#mmore')) $('#mmore').onclick = e => { $('#mdesc').classList.add('open'); e.target.remove(); };
  $('#mlink').onkeydown = e => { if (e.key === 'Enter') $('#mlinkset').click(); };
  if ($('#mreset')) $('#mreset').onclick = async () => {
    if (!confirm('Скинути опис, теги й обкладинку з інтернету для цього тайтлу? Обкладинкою стане перша сторінка. Прогрес читання не зміниться.')) return;
    const r = await api('/api/manga/reset', {method: 'POST', body: JSON.stringify({tid})});
    toast(r.ok ? 'Дані скинуто' : (r.error || 'Не вдалося'));
    renderBase(baseHash, true);
  };
  $('#mlinkset').onclick = async () => {
    await api('/api/manga/link', {method: 'POST', body: JSON.stringify({tid, link: $('#mlink').value.trim()})});
    toast('Шукаю. Опис і обкладинка з’являться за кілька секунд');
    setTimeout(() => { if (baseHash === '/manga/' + tid) renderBase(baseHash, true); }, 6000);
  };
  if (t.single) return;
  const draw = () => {
    const list = MG.newest ? t.chapters.slice().reverse() : t.chapters;
    $('#mlist').innerHTML = list.map(ch => {
      const cur = c && c.cid === ch.cid, part = !ch.done && ch.page > 0;
      const st = ch.done ? '✓ прочитано' : part ? `стор. ${ch.page} / ${ch.pages}` : ch.new ? 'нова' : '';
      const sub = [ch.sub, `${ch.pages} ${plural(ch.pages, 'сторінка', 'сторінки', 'сторінок')}`].filter(Boolean).join(' · ');
      return `<li class="${ch.done ? 'done' : ''}${cur ? ' cur' : ''}${ch.new && !ch.done ? ' new' : ''}"><a href="${mgRead(ch.cid, part ? ch.page : 0)}"><i class="dot" aria-hidden="true"></i>
        <span class="ml-t"><b>${esc(ch.label)}</b><small>${esc(sub)}</small></span>
        <span class="ml-bar" aria-hidden="true"><i style="width:${ch.done ? 100 : part ? (ch.page / ch.pages * 100).toFixed(1) : 0}%"></i></span><span class="ml-st">${st}</span></a>
        <button class="btn ghost icon mtick" data-tick="${ch.cid}" title="${ch.done ? 'Позначити непрочитаним' : 'Позначити прочитаним'}" aria-label="${ch.done ? 'Позначити непрочитаним' : 'Позначити прочитаним'}: ${esc(ch.label)}" aria-pressed="${ch.done}">✓</button></li>`;
    }).join('');
    $$('[data-tick]').forEach(b => b.onclick = async () => {
      const i = t.chapters.findIndex(x => x.cid === b.dataset.tick), ch = t.chapters[i];
      let cids = [ch.cid];
      if (!ch.done) {
        const before = t.chapters.slice(0, i).filter(x => !x.done);
        if (before.length && confirm(`Позначити прочитаними й ${before.length} ${plural(before.length, 'попередній розділ', 'попередні розділи', 'попередніх розділів')}?`)) cids = before.map(x => x.cid).concat(cids);
      }
      await api('/api/manga/mark', {method: 'POST', body: JSON.stringify({cids, read: !ch.done})});
      renderBase(baseHash, true);
    });
  };
  draw();
  $('#mflip').onclick = e => {
    MG.newest = !MG.newest; LS.set('mnewest', MG.newest);
    e.currentTarget.innerHTML = MG.newest ? I.arrDown + 'нові зверху' : I.arrUp + 'з першої';
    draw();
  };
}
MG.newest = LS.get('mnewest', false);

// ── читалка ──
async function renderReader(cid, startPage) {
  const ch = await api('/api/manga/ch/' + cid).catch(() => null);
  if (!ch || !ch.pages) { app.innerHTML = `<div class="empty"><h1 class="title">Розділ не знайдено</h1>Можливо, файли перемістили.<br><br><a class="btn" href="#/manga">До манги</a></div>`; return; }
  const N = ch.pages, url = n => `/manga/page/${cid}/${n}`;
  let mode = ch.mode, page = Math.min(N, Math.max(1, startPage || (ch.done ? 1 : ch.page) || 1));
  let shown = [], ended = false, saveT = 0, uiOn = true, io = null;
  const dims = {};      // n → ширина/висота, щоб розвороти-скани (ширші за висоту) показувати поодинці
  const imgs = {};
  const load = n => {
    if (n < 1 || n > N) return null;
    if (!imgs[n]) {
      const im = new Image();
      im.decoding = 'async';
      imgs[n] = new Promise(res => { im.onload = () => { dims[n] = im.naturalWidth / im.naturalHeight; res(im); }; im.onerror = () => res(null); });
      im.src = url(n);
    }
    return imgs[n];
  };
  document.documentElement.classList.add('locked', 'reading');
  app.innerHTML = `<div class="rd" id="rd" data-mode="${mode}">
    <div class="rd-stage" id="rdStage" aria-live="polite"></div>
    <div class="rd-strip" id="rdStrip" hidden></div>
    <div class="rd-end" id="rdEnd" hidden></div>
    <header class="rd-top"><a class="btn ghost icon" href="#/manga/${ch.tid}" aria-label="До тайтлу">${I.left}</a>
      <div class="rd-t"><b>${esc(ch.title)}</b><small id="rdPos"></small></div>
      <div class="rd-modes" role="group" aria-label="Режим читання">${MG_MODES.map(([k, l, h]) => `<button data-rm="${k}" title="${h}">${l}</button>`).join('')}</div>
      <button class="btn ghost rd-m1" id="rdMode" aria-label="Змінити режим читання"></button>
      <button class="btn ghost icon rd-fs" id="rdFs" title="На весь екран (F)" aria-label="На весь екран">⛶</button></header>
    <footer class="rd-bot">
      <button class="btn ghost" id="rdPrevCh"></button>
      <span class="rd-n" id="rdA"></span><input type="range" id="rdSlider" min="1" max="${N}" value="${page}" aria-label="Сторінка"><span class="rd-n" id="rdB"></span>
      <button class="btn ghost" id="rdNextCh"></button></footer>
    <p class="rd-hint" id="rdHint" aria-hidden="true"></p></div>`;
  const rd = $('#rd'), stage = $('#rdStage'), strip = $('#rdStrip'), endEl = $('#rdEnd'), slider = $('#rdSlider');
  const rtl = () => mode === 'rtl' || mode === 'spread';
  const save = (done) => {
    clearTimeout(saveT);
    const body = JSON.stringify({cid, page, done: !!done});
    saveT = setTimeout(() => api('/api/manga/progress', {method: 'POST', body}).catch(() => {}), done ? 0 : 700);
  };
  const flush = () => { clearTimeout(saveT); try { navigator.sendBeacon('/api/manga/progress', JSON.stringify({cid, page})); } catch (e) {} };
  const setUi = on => { uiOn = on; rd.classList.toggle('ui', on); };
  const pos = () => {
    $('#rdPos').textContent = `${ch.count > 1 ? ch.label + ' · ' : ''}стор. ${shown.length > 1 ? shown.join('–') : page} / ${N}`;
    slider.value = page;
  };
  const chBtns = () => {
    // кнопки розділів стоять з того боку, куди гортаємо: справа наліво «далі» — ліворуч
    const a = $('#rdPrevCh'), b = $('#rdNextCh');
    const lab = (t, left) => t ? (left ? I.left + esc(t.label) : esc(t.label) + I.right) : '';
    const [l, r] = rtl() ? ['next', 'prev'] : ['prev', 'next'];
    a.innerHTML = lab(ch[l], true); a.dataset.go = l; a.style.visibility = ch[l] ? '' : 'hidden';
    b.innerHTML = lab(ch[r], false); b.dataset.go = r; b.style.visibility = ch[r] ? '' : 'hidden';
    a.title = ch[l] ? (l === 'next' ? 'Наступний розділ' : 'Попередній розділ') : '';
    b.title = ch[r] ? (r === 'next' ? 'Наступний розділ' : 'Попередній розділ') : '';
    slider.dir = rtl() ? 'rtl' : 'ltr';
    $('#rdA').textContent = rtl() ? N : 1;
    $('#rdB').textContent = rtl() ? 1 : N;
    $$('[data-rm]').forEach(x => { x.classList.toggle('on', x.dataset.rm === mode); x.setAttribute('aria-pressed', x.dataset.rm === mode); });
    $('#rdMode').textContent = {rtl: '← стор.', ltr: 'стор. →', strip: 'стрічка', spread: 'розворот'}[mode];
  };
  const wide = n => dims[n] > 1.05;
  async function draw() {
    ended = false;
    endEl.hidden = true;
    stage.hidden = false;
    if (mode === 'spread' && page > 1 && page % 2) page -= 1;   // розвороти: 1 окремо, далі 2–3, 4–5…
    const want = page;
    let two = mode === 'spread' && page > 1 && page < N;
    const [a, b] = await Promise.all([load(page), two ? load(page + 1) : null]);
    if (want !== page || mode === 'strip') return;
    if (two && (wide(page) || wide(page + 1) || !b)) two = false;
    shown = two ? [page, page + 1] : [page];
    const el = n => `<img src="${url(n)}" alt="Сторінка ${n}" draggable="false">`;
    stage.innerHTML = two ? el(page + 1) + el(page) : el(page);   // розворот справа наліво: менша сторінка праворуч
    stage.classList.toggle('two', two);
    pos();
    save(false);
    for (let k = 1; k <= 4; k++) load(page + shown.length - 1 + k);
  }
  function showEnd() {
    ended = true;
    page = N;
    save(true);
    stage.hidden = true;
    endEl.hidden = false;
    endEl.innerHTML = `<div class="rd-card"><p class="ok">✓ ${esc(ch.count > 1 ? ch.label : ch.title)} — прочитано</p>
      ${ch.next ? `<h2>Далі: ${esc(ch.next.label)}</h2><p>${ch.next.pages} ${plural(ch.next.pages, 'сторінка', 'сторінки', 'сторінок')}</p><a class="btn primary" href="#/r/${ch.next.cid}" id="rdGoNext">${I.play}Читати далі</a>`
        : `<h2>${ch.count > 1 ? 'Це останній розділ' : 'Кінець'}</h2><p>Нові розділи з’являться тут, щойно ти покладеш їх у папку.</p>`}
      <a class="btn ghost" href="#/manga/${ch.tid}">До тайтлу</a></div>`;
    setUi(true);
    const g = $('#rdGoNext');
    if (g) g.focus({preventScroll: true});
  }
  const step = d => {
    if (mode === 'strip') return;
    if (ended) { if (d < 0) { ended = false; draw(); } else if (ch.next) go('#/r/' + ch.next.cid, true); return; }
    if (d > 0) {
      const nxt = page + shown.length;
      if (nxt > N) return showEnd();
      page = nxt;
    } else {
      if (page <= 1) return ch.prev ? toast(`Це перша сторінка. Попередній розділ: ${ch.prev.label}`) : null;
      page = Math.max(1, page - (mode === 'spread' && page > 2 ? 2 : 1));
    }
    if (uiOn) { setUi(false); if (rd.contains(document.activeElement)) document.activeElement.blur(); }
    draw();
  };
  // стрічка: усі сторінки вниз, поточну визначаємо за тим, що на екрані
  function drawStrip() {
    stage.hidden = true;
    endEl.hidden = true;
    strip.hidden = false;
    strip.innerHTML = Array.from({length: N}, (_, i) => `<img data-n="${i + 1}" loading="lazy" decoding="async" src="${url(i + 1)}" alt="Сторінка ${i + 1}">`).join('') +
      `<div class="rd-card in-strip">${ch.next ? `<h2>Далі: ${esc(ch.next.label)}</h2><a class="btn primary" href="#/r/${ch.next.cid}">${I.play}Читати далі</a>` : `<h2>${ch.count > 1 ? 'Це останній розділ' : 'Кінець'}</h2>`}<a class="btn ghost" href="#/manga/${ch.tid}">До тайтлу</a></div>`;
    shown = [page];
    io = new IntersectionObserver(es => {
      for (const e of es) if (e.isIntersecting) { page = +e.target.dataset.n; shown = [page]; pos(); save(page >= N); }
    }, {root: strip, rootMargin: '-45% 0px -45% 0px'});
    $$('img', strip).forEach(im => { io.observe(im); im.onload = () => im.classList.add('ok'); });
    const target = strip.querySelector(`[data-n="${page}"]`);
    if (target && page > 1) requestAnimationFrame(() => target.scrollIntoView());
    pos();
  }
  const setMode = m => {
    if (m === mode) return;
    mode = m;
    rd.dataset.mode = m;
    setMangaMode(ch.tid, m);
    if (io) { io.disconnect(); io = null; }
    strip.hidden = m !== 'strip';
    strip.innerHTML = m === 'strip' ? strip.innerHTML : '';
    chBtns();
    if (m === 'strip') drawStrip(); else draw();
    toast(MG_MODES.find(x => x[0] === m)[2]);
  };
  $$('[data-rm]').forEach(b => b.onclick = () => setMode(b.dataset.rm));
  $('#rdMode').onclick = () => { const k = MG_MODES.findIndex(x => x[0] === mode); setMode(MG_MODES[(k + 1) % MG_MODES.length][0]); };
  $('#rdPrevCh').onclick = $('#rdNextCh').onclick = e => {
    const t = ch[e.currentTarget.dataset.go];
    if (t) go('#/r/' + t.cid, true);
  };
  slider.oninput = () => { if (mode === 'strip') { const im = strip.querySelector(`[data-n="${slider.value}"]`); if (im) im.scrollIntoView(); return; } page = +slider.value; draw(); };
  $('#rdFs').onclick = () => { if (document.fullscreenElement) document.exitFullscreen(); else if (rd.requestFullscreen) rd.requestFullscreen().catch(() => {}); };
  // дотики: краї — гортати, середина — показати/сховати панель; свайп — гортати
  let sx = 0, sy = 0, st = 0;
  stage.addEventListener('pointerdown', e => { sx = e.clientX; sy = e.clientY; st = Date.now(); });
  stage.addEventListener('pointerup', e => {
    const dx = e.clientX - sx, dy = e.clientY - sy;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5 && Date.now() - st < 800) { step((dx > 0) === rtl() ? 1 : -1); return; }
    if (Math.abs(dx) > 10 || Math.abs(dy) > 10) return;
    const x = e.clientX / innerWidth;
    if (x < 0.34) step(rtl() ? 1 : -1);
    else if (x > 0.66) step(rtl() ? -1 : 1);
    else setUi(!uiOn);
  });
  strip.addEventListener('click', e => { if (!e.target.closest('a')) setUi(!uiOn); });
  const key = e => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest('input, select, textarea')) return;
    const k = e.key;
    if ((k === ' ' || k === 'Enter') && e.target.closest('button, a')) return;
    if (k === 'Escape') { if (!document.fullscreenElement) go('#/manga/' + ch.tid); return; }
    if (k === 'f' || k === 'F' || k === 'а' || k === 'А') { e.preventDefault(); $('#rdFs').click(); return; }
    if (mode === 'strip') return;
    if (k === 'ArrowLeft') { e.preventDefault(); step(rtl() ? 1 : -1); }
    else if (k === 'ArrowRight') { e.preventDefault(); step(rtl() ? -1 : 1); }
    else if (k === ' ' || k === 'PageDown' || k === 'ArrowDown') { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
    else if (k === 'PageUp' || k === 'ArrowUp' || k === 'Backspace') { e.preventDefault(); step(-1); }
    else if (k === 'Home') { e.preventDefault(); page = 1; draw(); }
    else if (k === 'End') { e.preventDefault(); page = N; draw(); }
  };
  document.addEventListener('keydown', key);
  const vis = () => { if (document.hidden) flush(); };
  document.addEventListener('visibilitychange', vis);
  addEventListener('pagehide', flush);
  cleanup = () => {
    flush();
    if (io) io.disconnect();
    document.removeEventListener('keydown', key);
    document.removeEventListener('visibilitychange', vis);
    removeEventListener('pagehide', flush);
    document.documentElement.classList.remove('locked', 'reading');
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  };
  chBtns();
  setUi(true);
  if (mode === 'strip') drawStrip(); else await draw();
  if (!LS.get('mhint', false) && mode !== 'strip') {
    const h = $('#rdHint');
    h.textContent = rtl() ? 'Торкнись лівого краю — далі, правого — назад. Середина ховає панель.' : 'Торкнись правого краю — далі, лівого — назад. Середина ховає панель.';
    h.classList.add('show');
    setTimeout(() => h.classList.remove('show'), 4200);
    LS.set('mhint', true);
  }
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

// Субтитри ШІ: стан однієї позиції черги звичайними словами
function aiStateText(a) {
  const pct = Math.round((a.p || 0) * 100) + ' %';
  return {queued: 'у черзі', audio: 'готую звук', model: 'завантажую модель (перший раз ~1,5 ГБ)', recog: `розпізнаю мову · ${pct}`, context: `читаю серію: персонажі, сленг, контекст · ${pct}`,
    translate: `${a.src === 'subs' ? 'перекладаю англійські субтитри' : 'перекладаю українською'} · ${pct}`, done: 'готово', error: 'не вдалося'}[a.state] || a.state;
}
let aiSetT = 0;
async function drawAiSet(st) {
  clearTimeout(aiSetT);
  const box = $('#aiBody');
  if (!box) return;
  st = st || await api('/api/aisubs').catch(() => null);
  if (!st || !st.queue || !$('#aiBody')) return;
  const busy = st.install === 'run' || (st.bench && st.bench.run) || st.queue.some(x => !['done', 'error'].includes(x.state));
  box.innerHTML = `<p class="note" style="margin-top:0">VidBox сам слухає відео (Whisper — прямо на цьому комп’ютері) і робить субтитри, а українською їх перекладає вибраний перекладач (локальна модель на ПК, Gemini, DeepL або Azure). Серія на 24 хв — орієнтовно 15–40 хв, усе у фоні з низьким пріоритетом. Запустити — у плеєрі (кнопка CC → «Українські (ШІ)») або на сторінці аніме для всіх серій.</p>` +
    (!st.linux ? `<p class="warn">Поки працює лише на Linux (на Хаті).</p>`
    : !st.ready ? (st.install === 'run' ? `<p class="note">⏳ ${esc(st.log || 'Встановлюю…')} Це кілька хвилин.</p>`
      : `${st.install === 'error' ? `<p class="warn">${esc(st.log)}</p>` : ''}<button class="btn primary" id="aiInstall">${I.plus}Встановити розпізнавання</button><p class="note">Завантажиться ≈ 400 МБ, а з першим відео — модель ще ≈ 1,5 ГБ (швидша — ≈ 0,5 ГБ).</p>`)
    : `<div class="srow"><div class="sl"><b>Модель</b><small>Точніша — краще чує японську й шумні сцени; швидша — помітно швидше, але більше помилок.</small></div>
        <div class="sc"><div class="seg" id="aiModel"><button data-m="large-v3-turbo" class="${st.model === 'large-v3-turbo' ? 'on' : ''}">точніша</button><button data-m="small" class="${st.model === 'small' ? 'on' : ''}">швидша</button></div></div></div>
      <div class="srow"><div class="sl"><b>Звідки брати текст</b><small>Якщо у відео є англійські субтитри, перекладати їх — текст від людей, точний час, серія за хвилину. Інакше — розпізнавати звук.</small></div>
        <div class="sc"><div class="seg" id="aiSrc"><button data-src="subs" class="${st.source !== 'audio' ? 'on' : ''}">англ. субтитри</button><button data-src="audio" class="${st.source === 'audio' ? 'on' : ''}">завжди звук</button></div></div></div>
      <div class="srow"><div class="sl"><b>Спершу прочитати серію</b><small>Перед перекладом модель (локальна або Gemini) читає всю серію: про що вона, хто з персонажів чоловік чи жінка (закінчення «втомився/втомилася»), як хто говорить, який сленг. Персонажі й терміни самі додаються в глосарій аніме — твої правки не змінюються. Плюс 1–3 запити на серію.</small></div>
        <div class="sc"><div class="seg" id="aiCtx"><button data-c="1" class="${st.context !== false ? 'on' : ''}">так</button><button data-c="0" class="${st.context === false ? 'on' : ''}">ні</button></div></div></div>
      <div class="srow"><div class="sl"><b>Перекласти бібліотеку</b><small>Додає в чергу всі серії аніме без українських субтитрів ШІ — по порядку серій, тож глосарій кожного тайтлу накопичується від першої до останньої. Серія ≈ 5–7 хв на локальній моделі; сотня серій — це ніч.</small></div>
        <div class="sc"><button class="btn" data-bulk="adult">Усі 18+</button><button class="btn ghost" data-bulk="all">Усе аніме</button></div></div>
      <div class="srow"><div class="sl"><b>Готові субтитри</b><small>Які тайтли вже перекладені й коли. Старий переклад (напр. зроблений іншою моделлю) можна прибрати або одразу перекласти заново — разом з аналізом серії. Оригінальні субтитри у відео не зачіпаються.</small></div>
        <div class="sc"><button class="btn ghost" id="aiDoneBtn">Показати</button></div></div>
      <div id="aiDone"></div>
      <div class="srow"><div class="sl"><b>Ядро перекладу</b><small>Нове (тест): кожна репліка має номер, переклад іде сценами, кожен варіант перевіряється — вигадані слова (словник української), русизми, рід за мовцем, зсув рядків, заборони глосарію; що не пройшло — модель виправляє адресно з поясненням причини. Біля субтитрів — звіт qa.json із сумнівними репліками. Поки лише для локальної моделі. Порівняти ядра — «Перевірити модель» з кожним.</small></div>
        <div class="sc"><div class="seg" id="aiCore"><button data-core="old" class="${st.trCore !== 'new' ? 'on' : ''}">старе</button><button data-core="new" class="${st.trCore === 'new' ? 'on' : ''}">нове (тест)</button></div></div></div>
      ${st.trCore === 'new' ? `<div class="srow"><div class="sl"><b>Рецензент змісту</b><small>Лише в новому ядрі. Після перекладу модель ще раз читає пари «оригінал → переклад» і виправляє помилки сенсу, яких не бачать правила: CPR — «штучне дихання», а не «серцебиття»; «finish the order» — не «кінчити»; не той мовець чи ім'я. Кожне виправлення проходить ту саму перевірку. ≈ +10–20 % часу.</small></div>
        <div class="sc"><div class="seg" id="aiRev"><button data-rv="1" class="${st.review !== false ? 'on' : ''}">так</button><button data-rv="0" class="${st.review === false ? 'on' : ''}">ні</button></div></div></div>` : ''}
      <div class="srow"><div class="sl"><b>Перевірити модель</b><small>Сталий тест якості: ${st.bench && st.bench.last ? st.bench.last.total : 210} реплік із 19 сцен, де раніше траплялися помилки (зсув рядків, вигадані слова, рід, «Дайкі» замість Daisuke, CPR, «finish the order»…). Оцінка — частка реплік без помилок; її видно в історії, тож можна порівнювати моделі, налаштування й нові версії перекладу. ≈ 15–25 хв на ПК; черга на цей час чекає.</small></div>
        <div class="sc">${st.bench && st.bench.run ? '<button class="btn ghost" id="aiBenchStop">Зупинити</button>' : '<button class="btn" id="aiBenchRun">Запустити</button>'}<button class="btn ghost" id="aiBenchHist">Історія</button></div></div>
      <div id="aiBench">${aiBenchLine(st.bench)}</div>
      <div class="srow"><div class="sl"><b>18+ лише локально</b><small>Тайтли з набором «Хентай 18+» перекладає тільки модель на ПК. Якщо ПК вимкнений чи спить — серія чекає й повторює спробу кожні 2 хв, а не йде в Gemini (той відмовить чи пом'якшить і витратить ліміт).</small></div>
        <div class="sc"><div class="seg" id="aiAdl"><button data-al="1" class="${st.adultLocal !== false ? 'on' : ''}">так</button><button data-al="0" class="${st.adultLocal === false ? 'on' : ''}">ні</button></div></div></div>
      <div class="srow"><div class="sl"><b>Жорсткіше для 18+</b><small>Лише для аніме з набором «Хентай 18+». Після перекладу модель ще раз проходить репліки з грубою чи відвертою лексикою і прибирає пом'якшення: «до біса» → «до усрачки», «бовдур» → «дебіл». Плюс 1–3 запити на серію.</small></div>
        <div class="sc"><div class="seg" id="aiHard"><button data-h="1" class="${st.harden !== false ? 'on' : ''}">так</button><button data-h="0" class="${st.harden === false ? 'on' : ''}">ні</button></div></div></div>
      <div class="srow"><div class="sl"><b>Швидкість</b><small>Максимальна — усі 8 потоків процесора, і Хата на час розпізнавання вмикає режим продуктивності: швидше, але ноутбук гарячіший і вентилятор гучніший. Якість однакова.</small></div>
        <div class="sc"><div class="seg" id="aiSpeed"><button data-s="normal" class="${st.speed !== 'max' ? 'on' : ''}">звичайна</button><button data-s="max" class="${st.speed === 'max' ? 'on' : ''}">максимальна</button></div></div></div>
      <div class="srow"><div class="sl"><b>Перекладач</b><small>Перекладає основний; коли в нього скінчився ліміт — наступний, у якого є ключ. ${!(st.local || st.gemini || st.deepl || st.azure) ? 'Без жодного ключа будуть лише субтитри мовою оригіналу.' : ''}</small></div>
        <div class="sc"><div class="seg" id="aiMain">${['local', 'gemini', 'deepl', 'azure'].map(k => `<button data-tm="${k}" class="${st.trMain === k ? 'on' : ''}">${TRN[k]}</button>`).join('')}</div></div></div>
      ${trLocal(st)}
      ${trKey('gemini', st.gemini, `Безкоштовно і без картки: <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a> → «Create API key». Мовна модель — краще тримає тон діалогів. На безкоштовному тарифі Google може використовувати тексти для навчання.${st.geminiModel ? ` Модель: ${esc(st.geminiModel)}.` : ''}`)}
      ${trKey('deepl', st.deepl, `<a href="https://www.deepl.com/pro-api" target="_blank" rel="noopener">deepl.com/pro-api</a> → вкладка API → план Developer: 1 млн символів одноразово. Серія аніме японською ≈ 2 тис. символів.<small id="aiUsage"></small>`)}
      ${trKey('azure', st.azure, `Microsoft Translator: 2 млн символів щомісяця безкоштовно (тариф F0). Ключ і регіон — у ресурсі Translator на portal.azure.com → «Keys and Endpoint».`)}</div>`) +
    (st.queue.length ? `<h3 style="margin:16px 0 6px">Черга</h3><div class="flist">${st.queue.map(x => `<div class="frow"><div><b>${esc(x.title)}</b>
        <small style="color:var(${x.state === 'error' ? '--red, #e66' : '--mute'})">${esc(aiStateText(x))}${x.via && x.state === 'done' ? ' · ' + (x.src === 'subs' ? 'з англ. субтитрів · ' : '') + TRN[x.via] : ''}${x.err ? ' — ' + esc(x.err) : ''}</small></div>
        <button class="btn ghost icon" data-airm="${esc(x.id)}" title="${['done', 'error'].includes(x.state) ? 'Прибрати зі списку' : 'Скасувати'}" aria-label="Прибрати">${I.trash}</button></div>`).join('')}</div>
      ${st.queue.some(x => ['done', 'error'].includes(x.state)) ? '<button class="btn ghost" id="aiClear" style="margin-top:8px">Прибрати готові</button>' : ''}` : '');
  const post = async b => { const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify(b)}); if (r.ok === false && r.error) toast(r.error); return r; };
  if ($('#aiInstall')) $('#aiInstall').onclick = async () => drawAiSet(await post({op: 'install'}));
  $$('#aiModel [data-m]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', model: b.dataset.m})));
  $$('#aiSpeed [data-s]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', speed: b.dataset.s})));
  if ($('#aiPin')) $('#aiPin').onchange = async e => { drawAiSet(await post({op: 'save', localPin: e.target.value})); toast(e.target.value ? 'Перекладатиме ' + e.target.value : 'Модель — як у LM Studio'); };
  $$('#aiPar [data-par]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', localPar: +b.dataset.par})));
  $$('#aiAdl [data-al]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', adultLocal: b.dataset.al === '1'})));
  $$('[data-bulk]').forEach(b => b.onclick = async () => {
    const scope = b.dataset.bulk, pre = await post({op: 'add_bulk', scope, dry: true});
    if (!pre.ok) return;
    if (!pre.count) return toast(scope === 'adult' ? 'Усі серії 18+ уже перекладені або в черзі' : 'Усі серії вже перекладені або в черзі');
    if (!confirm(`Додати в чергу ${pre.count} ${plural(pre.count, 'серію', 'серії', 'серій')} з ${pre.titles} ${plural(pre.titles, 'тайтлу', 'тайтлів', 'тайтлів')}? Це ≈ ${pre.count * 6 < 60 ? pre.count * 6 + ' хв' : Math.round(pre.count * 6 / 60) + ' год'} на локальній моделі — ПК має бути ввімкнений.`)) return;
    const r = await post({op: 'add_bulk', scope});
    if (r.ok) { drawAiSet(r); toast(`Додав ${r.count} ${plural(r.count, 'серію', 'серії', 'серій')}`); }
  });
  $$('#aiCore [data-core]').forEach(b => b.onclick = async () => { drawAiSet(await post({op: 'save', trCore: b.dataset.core})); toast(b.dataset.core === 'new' ? 'Нове ядро: наступні серії й тест — ним' : 'Старе ядро'); });
  $$('#aiRev [data-rv]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', review: b.dataset.rv === '1'})));
  if ($('#aiBenchRun')) $('#aiBenchRun').onclick = async () => {
    if (!confirm('Запустити тест якості? ≈ 15–25 хв, ПК з моделлю має бути ввімкнений. Черга перекладу на цей час чекає.')) return;
    drawAiSet(await post({op: 'bench'}));
  };
  if ($('#aiBenchStop')) $('#aiBenchStop').onclick = async () => { drawAiSet(await post({op: 'bench_stop'})); toast('Зупиняю після поточної сцени'); };
  if ($('#aiBenchHist')) $('#aiBenchHist').onclick = () => aiBenchHist(post);
  if ($('#aiDoneBtn')) $('#aiDoneBtn').onclick = () => { if ($('#aiDone').innerHTML) { $('#aiDone').innerHTML = ''; $('#aiDoneBtn').textContent = 'Показати'; } else aiDoneDraw(post); };
  $$('#aiHard [data-h]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', harden: b.dataset.h === '1'})));
  $$('#aiCtx [data-c]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', context: b.dataset.c === '1'})));
  $$('#aiSrc [data-src]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', source: b.dataset.src})));
  $$('#aiMain [data-tm]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', main: b.dataset.tm})));
  $$('[data-savekey]').forEach(b => b.onclick = async () => {
    const k = b.dataset.savekey, v = $('#key_' + k).value.trim();
    if (!v) { $('#key_' + k).focus(); return toast(k === 'local' ? 'Впиши адресу ПК, напр. 192.168.3.50:1234' : 'Встав ключ ' + TRN[k]); }
    const body = {op: 'save', [k === 'deepl' ? 'key' : k]: v};
    if (k === 'azure') body.region = $('#key_region').value.trim();
    if (k === 'local' && $('#key_localtok').value.trim()) body.localKey = $('#key_localtok').value.trim();
    b.disabled = true; b.textContent = 'Перевіряю…';
    const r = await post(body);
    if (!r || r.ok !== true) { b.disabled = false; b.textContent = 'Зберегти'; if (r && r.ok !== false) toast(r.error || 'Не вдалося зберегти'); return; }
    drawAiSet(r);
    if (k === 'deepl') { const u = await post({op: 'usage'}); toast(u.ok ? 'Ключ DeepL працює' : 'Ключ збережено, але DeepL відповів: ' + u.error); }
    else toast(k === 'gemini' ? `Ключ Gemini працює (${r.geminiModel})` : k === 'local' ? `ПК на зв’язку, модель: ${r.localModel}` : 'Ключ Azure збережено');
  });
  $$('[data-forget]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'save', forget: [b.dataset.forget + '_key']})));
  if ($('#aiUse')) $('#aiUse').onclick = async () => {
    const u = await post({op: 'usage'});
    $('#aiUsage').textContent = u.ok ? `Цього місяця використано ${u.used.toLocaleString('uk-UA')} з ${u.limit.toLocaleString('uk-UA')} символів.` : u.error;
  };
  $$('[data-airm]').forEach(b => b.onclick = async () => drawAiSet(await post({op: 'remove', id: b.dataset.airm})));
  if ($('#aiClear')) $('#aiClear').onclick = async () => drawAiSet(await post({op: 'clear'}));
  if (busy) aiSetT = setTimeout(() => { if ($('#aiBody') && !$('#aiBody').contains(document.activeElement)) drawAiSet(); else if ($('#aiBody')) aiSetT = setTimeout(drawAiSet, 4000); }, 4000);
}

// Готові субтитри ШІ по тайтлах: «Перекласти заново» (видалити + у чергу) і «Видалити» — для тайтлу або для всіх,
// зроблених раніше за вибрану дату (щоб прибрати переклади старої моделі одним натиском).
function aiBenchWhen(m) { return m && m.at ? new Date(m.at * 1000).toLocaleString('uk-UA', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : ''; }
function aiBenchLine(b) {
  if (!b) return '';
  if (b.run) return `<p class="note">⏳ Тест іде: ${Math.round((b.p || 0) * 100)} %</p>`;
  const l = b.last;
  return (b.err ? `<p class="warn">${esc(b.err)}</p>` : '') +
    (l ? `<p class="note">Останній: <b>${l.score} %</b> (${l.passed} з ${l.total}) · ${esc(aiBenchWhen(l.meta))}${l.meta.model ? ' · ' + esc(l.meta.model) : ''}</p>` : '');
}
async function aiBenchHist(post) {
  const box = $('#aiBench');
  const r = await post({op: 'bench_list'});
  if (!r.ok) return;
  const R = r.runs || [];
  if (!R.length) { box.innerHTML = '<p class="note">Тест ще не запускали.</p>'; return; }
  box.innerHTML = `<div class="flist">${R.map((x, i) => {
    const prev = R[i + 1], d = prev ? Math.round((x.score - prev.score) * 10) / 10 : null;
    return `<div class="frow"><div><b>${x.score} %</b> <small>${x.passed} з ${x.total}${d !== null ? ` · <span style="color:var(${d >= 0 ? '--acc' : '--red, #e66'})">${d >= 0 ? '+' : ''}${d}</span>` : ''}</small>
      <small style="display:block;color:var(--mute)">${esc(aiBenchWhen(x.meta))} · ${esc(x.meta.model || x.meta.translator || '')} · ядро: ${x.meta.core === 'old' ? 'старе' : x.meta.core === 'new' ? 'нове' + (x.meta.review ? ' + рецензент' : '') : esc(x.meta.core || '')}${x.meta.finished === false ? ' · зупинено' : ''}</small></div>
      <button class="btn ghost" data-bench="${esc(x.id)}">Звіт</button></div>`;
  }).join('')}</div><div id="aiBenchRep"></div>`;
  $$('[data-bench]').forEach(b => b.onclick = async () => {
    const g = await post({op: 'bench_get', id: b.dataset.bench});
    if (!g.ok) return;
    const rep = g.report, F = rep.fails || [];
    const url = URL.createObjectURL(new Blob([JSON.stringify(rep, null, 1)], {type: 'application/json'}));
    $('#aiBenchRep').innerHTML = `<p class="note">${rep.score} % · ${rep.passed} з ${rep.total} · не виконано очікувань: ${rep.expect_failed} · <a href="${url}" download="vidbox-test-${esc(b.dataset.bench)}.json">завантажити звіт</a></p>` +
      `<div class="flist">${F.map(f => `<div class="frow"><div><small style="color:var(--mute)">${esc(f.case)} · ${f.n + 1}</small><br>${esc(f.en)}<br><b>${esc(f.uk || '—')}</b>
        <small style="display:block;color:var(--red, #e66)">${esc([...f.expect, ...f.block].join('; '))}</small>${f.why ? `<small style="display:block;color:var(--mute)">${esc(f.why)}</small>` : ''}${f.core ? `<small style="display:block;color:var(--mute)">ядро: ${esc(f.core.status)}, спроб ${f.core.tries}${f.core.who ? ', мовець «' + esc(f.core.who) + '»' : ''}${f.core.to ? ' → «' + esc(f.core.to) + '»' : ''}</small>` : ''}</div></div>`).join('')}</div>`;
  });
}
async function aiDoneDraw(post) {
  const box = $('#aiDone');
  if (!box) return;
  const r = await post({op: 'done_list'});
  if (!r.ok) return;
  $('#aiDoneBtn').textContent = 'Сховати';
  const T = r.titles || [];
  if (!T.length) { box.innerHTML = '<p class="note">Готових субтитрів ШІ ще немає.</p>'; return; }
  const day = t => new Date(t * 1000).toLocaleDateString('uk-UA', {day: 'numeric', month: 'short'});
  const when = t => day(t.oldest) === day(t.newest) ? day(t.newest) : day(t.oldest) + ' – ' + day(t.newest);
  const all = T.reduce((a, t) => a + t.n, 0);
  box.innerHTML = `<div class="srow"><div class="sl"><b>Усі ${all} ${plural(all, 'серія', 'серії', 'серій')}</b><small>Лише зроблені до:</small></div>
      <div class="sc"><input type="date" id="aiBefore" aria-label="Зроблені до цієї дати" value="${new Date().toISOString().slice(0, 10)}">
      <button class="btn" data-dall="redo">Перекласти заново</button><button class="btn ghost" data-dall="delete">${I.trash}Видалити</button></div></div>
    <div class="srow"><div class="sl"><b>Завантажити архівом</b><small>Оригінальні субтитри (з яких перекладали), переклад і аналіз серії — одним .zip, по теках тайтлів. Зручно, щоб перевірити якість чи віддати на розбір.</small></div>
      <div class="sc"><button class="btn" data-zip="today">Зроблені сьогодні</button><button class="btn ghost" data-zip="all">Усі</button></div></div>
    <div class="flist">${T.map((t, k) => `<div class="frow"><div><b>${esc(t.title)}</b><small style="color:var(--mute)">${t.n} з ${t.total} ${plural(t.total, 'серії', 'серій', 'серій')} · ${when(t)}</small></div>
      <div style="display:flex;gap:6px"><a class="btn ghost icon" href="/api/aisubs/export?${t.sid ? 'sid=' + encodeURIComponent(t.sid) : 'ids=' + t.ids.join(',')}" download title="Завантажити оригінал і переклад архівом" aria-label="Завантажити">⤓</a><button class="btn ghost" data-dt="${k}" data-act="redo" title="Видалити й одразу перекласти заново">Заново</button>
      <button class="btn ghost icon" data-dt="${k}" data-act="delete" title="Видалити субтитри ШІ тайтлу" aria-label="Видалити">${I.trash}</button></div></div>`).join('')}</div>`;
  const go = async (b, what, n) => {
    if (!confirm(b.op === 'redo' ? `Видалити субтитри ШІ ${what} (${n} ${plural(n, 'серія', 'серії', 'серій')}) і одразу перекласти заново? Аналіз серії теж зробиться наново, а в тайтлах, що переробляються повністю, — і «Знайдено автоматично» в глосарії (твої записи лишаться).`
      : `Видалити субтитри ШІ ${what} (${n} ${plural(n, 'серія', 'серії', 'серій')})? Оригінальні субтитри у відео не зачіпаються.`)) return;
    const r = await post(b);
    if (!r.ok) return;
    toast(b.op === 'redo' ? `${r.count} ${plural(r.count, 'серія', 'серії', 'серій')} знову в черзі` + (r.glossCleared ? ` · автоглосарій очищено в ${r.glossCleared} ${plural(r.glossCleared, 'тайтлі', 'тайтлах', 'тайтлах')}` : '') : `Видалено: ${r.count}`);
    drawAiSet(r).then(() => aiDoneDraw(post));
  };
  $$('[data-dt]', box).forEach(b => b.onclick = () => {
    const t = T[+b.dataset.dt];
    go(Object.assign({op: b.dataset.act}, t.sid ? {sid: t.sid} : {ids: t.ids}), `«${t.title}»`, t.n);
  });
  $$('[data-zip]', box).forEach(b => b.onclick = () => {
    const d = new Date(); d.setHours(0, 0, 0, 0);
    const a = document.createElement('a');
    a.href = '/api/aisubs/export' + (b.dataset.zip === 'today' ? '?since=' + d.getTime() / 1000 : '');
    a.download = ''; document.body.appendChild(a); a.click(); a.remove();
  });
  $$('[data-dall]', box).forEach(b => b.onclick = () => {
    const v = $('#aiBefore').value, before = v ? new Date(v + 'T23:59:59').getTime() / 1000 : 0;
    const n = T.reduce((a, t) => a + (t.oldest < before ? t.n : 0), 0);
    go({op: b.dataset.dall, all: true, before}, v ? `усіх серій, зроблених до ${day(before)} включно` : 'усіх серій', n);
  });
}

// ── Глосарій: однаковий блок у Налаштуваннях (sid '_') і на сторінці аніме. Файл (.csv/.tsv/.md/.txt) — перетягнути
// або «Завантажити файл»; таблиця з пошуком, правка рядка — клік по ньому, експорт у .csv (той самий формат, що читає імпорт).
const GL_REG = ['вульгарне', 'розмовне', 'нейтральне', 'ніжне', 'вигук', 'запозичення', "ім'я"];
function glossPanel(host, sid, title) {
  if (!host) return;
  const G = {notes: '', items: [], auto: [], autoBad: [], autoOpen: false, q: '', more: 120, file: null, sets: [], setsAuto: true, adultAuto: null, avail: [], view: ''};
  const post = async b => { const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify(Object.assign({sid}, b))}); if (r.ok === false) toast(r.error || 'Не вдалося'); return r; };
  const save = async () => { const r = await post({op: 'gloss', notes: G.notes, items: G.items}); if (r.ok) { G.items = r.items; G.notes = r.notes; } return r; };
  const list = () => { const q = G.q.toLowerCase(); return q ? G.items.filter(it => it.some(x => x.toLowerCase().includes(q))) : G.items; };
  const rows = () => {
    const l = list();
    if (!G.items.length) return `<div class="gl-empty">${I.upload}<b>Перетягни сюди файл глосарію</b><small>.csv із srt_glossary.py, таблицю .md або .txt рядками «Rimuru = Рімуру»</small></div>`;
    if (!l.length) return `<p class="note">Нічого не знайдено.</p>`;
    return l.slice(0, G.more).map(it => `<div class="gl-row" data-gt="${esc(it[0])}" tabindex="0" title="Змінити">
        <b>${esc(it[0])}</b><span class="gl-tr">${esc(it[1])}</span>${it[2] ? `<i class="gl-reg">${esc(it[2])}</i>` : '<i></i>'}<small>${esc(it[3])}</small>
        <button class="btn ghost icon" data-gdel="${esc(it[0])}" title="Прибрати" aria-label="Прибрати ${esc(it[0])}">${I.trash}</button></div>`).join('') +
      (l.length > G.more ? `<button class="btn ghost" id="glMore" style="margin-top:10px">Показати ще ${Math.min(500, l.length - G.more)} з ${l.length - G.more}</button>` : '');
  };
  const setsHtml = () => {
    if (!G.avail.length) return '';
    if (sid === '_') return `<div class="srow" style="align-items:flex-start"><div class="sl"><b>Набори глосаріїв</b><small>Готові глосарії, що йдуть разом із VidBox. Вмикаються для кожного аніме окремо — на його сторінці → «Глосарій»: «Аніме» — для всіх, «Хентай 18+» — сам для тайтлів, які AniList позначає 18+. Твої записи тут і в тайтлі важливіші за набори.</small></div></div>
      <div class="gl-sets">${G.avail.map(a => `<button class="chip${G.view === a.id ? ' on' : ''}" data-glview="${esc(a.id)}" title="${esc(a.desc)}">${esc(a.name)} · ${a.n}${a.adult && !/18\+/.test(a.name) ? ' · 18+' : ''}</button>`).join('')}</div>${viewHtml()}`;
    const why = G.setsAuto ? (G.adultAuto ? 'Вибрано автоматично: AniList позначає тайтл як 18+.' : G.adultAuto === false ? 'Вибрано автоматично: тайтл не 18+.' : 'Вибрано автоматично (даних AniList про 18+ немає).') : 'Вибрано вручну.';
    return `<div class="srow" style="align-items:flex-start"><div class="sl"><b>Набори глосаріїв</b><small>${why} Набір «18+» вмикає переклад без цензури — лише для дорослих тайтлів. ${G.setsAuto ? '' : '<a href="#" data-glauto>Повернути автоматичний вибір</a>'}</small></div></div>
      <div class="gl-sets">${G.avail.map(a => `<button class="chip${G.sets.includes(a.id) ? ' on' : ''}" data-glset="${esc(a.id)}" title="${esc(a.desc)}" aria-pressed="${G.sets.includes(a.id)}">${esc(a.name)} · ${a.n}${a.adult && !/18\+/.test(a.name) ? ' · 18+' : ''}</button>`).join('')}</div>`;
  };
  const viewHtml = () => {
    const a = G.view && G.viewData;
    if (!a) return '';
    return `<div class="gl-view"><p class="note" style="margin-top:6px">${esc(a.desc)}</p>${a.notes ? `<p class="note" style="white-space:pre-line">${esc(a.notes)}</p>` : ''}
      <div class="gl-head"><b>Термін</b><b>Переклад</b><b>Регістр</b><b>Примітка</b><i></i></div>
      <div class="gl-list">${a.items.map(it => `<div class="gl-row ro"><b>${esc(it[0])}</b><span class="gl-tr">${esc(it[1])}</span>${it[2] ? `<i class="gl-reg">${esc(it[2])}</i>` : '<i></i>'}<small>${esc(it[3])}</small><i></i></div>`).join('')}</div></div>`;
  };
  const exportCsv = (list, suffix) => {
    const cell = x => /[;"\n]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x;
    const csv = '﻿Термін;Переклад;Регістр;Примітка\n' + list.map(it => it.map(cell).join(';')).join('\n') + '\n';
    const u = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
    const l = document.createElement('a'); l.href = u; l.download = `глосарій ${sid === '_' ? 'загальний' : (title || sid).replace(/[\\/:*?"<>|]+/g, ' ').trim()}${suffix}.csv`;
    document.body.appendChild(l); l.click(); l.remove(); setTimeout(() => URL.revokeObjectURL(u), 2000);
  };
  const autoHtml = () => {
    if (sid === '_' || !G.auto.length) return '';
    return `<div class="srow" style="align-items:flex-start"><div class="sl"><b>Знайдено автоматично · ${G.auto.length}</b><small>Персонажі й терміни, які модель знайшла, читаючи серії. Вони найменш важливі — набори й твої записи їх перекривають. Правильне — ✓ переносить у твій глосарій, хибне — прибери.${G.autoBad.length ? ` Перекреслені (${G.autoBad.length}) схожі на помилки моделі (латиниця, заборонені слова наборів, задовгі фрази, звертання замість імені) або дублюють запис набору чи твій — і в переклад не йдуть.` : ''}</small></div>
      <div class="sc"><button class="btn ghost" data-gla="toggle">${G.autoOpen ? 'Сховати' : 'Показати'}</button><button class="btn ghost" data-gla="export">${I.download}Експорт .csv</button><button class="btn ghost" data-gla="clear">${I.trash}Очистити</button></div></div>
      ${G.autoOpen ? `<div class="gl-list">${G.auto.map(it => `<div class="gl-row ro${G.autoBad.includes(it[0]) ? ' bad' : ''}"${G.autoBad.includes(it[0]) ? ' title="Схоже на помилку моделі — у переклад не йде"' : ''}><b>${esc(it[0])}</b><span class="gl-tr">${esc(it[1])}</span>${it[2] ? `<i class="gl-reg">${esc(it[2])}</i>` : '<i></i>'}<small>${esc(it[3])}</small>
        <span class="gl-act"><button class="btn ghost icon" data-glpro="${esc(it[0])}" title="У мій глосарій" aria-label="Перенести ${esc(it[0])} у мій глосарій">✓</button><button class="btn ghost icon" data-gldel="${esc(it[0])}" title="Прибрати" aria-label="Прибрати ${esc(it[0])}">${I.trash}</button></span></div>`).join('')}</div>` : ''}`;
  };
  const draw = () => {
    host.innerHTML = setsHtml() + `<p class="note" style="margin-top:${G.avail.length ? 14 : 0}px">${sid === '_' ? 'Діє для всіх відео.' : `Тільки для «${esc(title || '')}» — разом із загальним із Налаштувань; переклади тут важливіші.`} Gemini й локальна модель отримують правила і ті терміни, що трапляються в репліках, які саме перекладаються, тож глосарій може бути великим. DeepL і Azure глосарій не використовують.</p>
      <div class="gl-tools"><input type="search" id="glQ_${sid}" placeholder="Пошук у ${G.items.length} ${plural(G.items.length, 'терміні', 'термінах', 'термінах')}…" value="${esc(G.q)}" aria-label="Пошук у глосарії">
        <input type="file" id="glF_${sid}" accept=".csv,.tsv,.md,.txt,text/csv,text/plain,text/markdown" hidden>
        <button class="btn primary" data-gl="file">${I.upload}Завантажити файл</button>
        ${G.items.length ? `<button class="btn ghost" data-gl="export">${I.download}Експорт .csv</button><button class="btn ghost" data-gl="clear">${I.trash}Очистити</button>` : ''}</div>
      ${G.file ? `<div class="gl-imp"><div><b>${esc(G.file.name)}</b><small>${G.items.length ? 'Ті самі терміни з файлу замінять наявні.' : ''}</small></div>
        ${G.items.length ? '<button class="btn primary" data-gl="merge">Додати до наявних</button><button class="btn ghost" data-gl="replace">Замінити все</button>' : '<button class="btn primary" data-gl="replace">Завантажити</button>'}
        <button class="btn ghost" data-gl="cancel">Скасувати</button></div>` : ''}
      <div class="gl-head"><b>Термін</b><b>Переклад</b><b>Регістр</b><b>Примітка</b><i></i></div>
      <div class="gl-list" id="glL_${sid}">${rows()}</div>
      <div class="fadd gl-add"><input id="glT_${sid}" placeholder="термін, напр. senpai" aria-label="Термін"><input id="glR_${sid}" placeholder="переклад" aria-label="Переклад">
        <input id="glG_${sid}" list="glRegs" placeholder="регістр" aria-label="Регістр" style="max-width:140px"><input id="glN_${sid}" placeholder="примітка" aria-label="Примітка">
        <button class="btn primary" data-gl="add">${I.plus}Додати</button></div>
      <datalist id="glRegs">${GL_REG.map(x => `<option value="${esc(x)}">`).join('')}</datalist>
      ${autoHtml()}
      <div class="srow" style="align-items:flex-start"><div class="sl"><b>Правила</b><small>Вільним текстом, для всього перекладу: «звертання -san/-chan лишати», «героїня говорить на «ви»», «стогони не перекладати дослівно».</small></div></div>
      <div class="fadd" style="align-items:flex-start"><textarea id="glNotes_${sid}" rows="3" style="flex:1;min-height:70px;resize:vertical" placeholder="Звертання -san/-chan не перекладати">${esc(G.notes)}</textarea><button class="btn primary" data-gl="notes">Зберегти</button></div>`;
    bind();
  };
  const redrawList = () => { const L = $('#glL_' + sid); if (L) { L.innerHTML = rows(); bindRows(); } };
  const bindRows = () => {
    $$('[data-gdel]', host).forEach(b => b.onclick = async e => {
      e.stopPropagation();
      G.items = G.items.filter(it => it[0] !== b.dataset.gdel);
      if ((await save()).ok) draw();
    });
    $$('.gl-row:not(.ro)', host).forEach(r => r.onclick = r.onkeydown = e => {
      if (e.type === 'keydown' && e.key !== 'Enter') return;
      const it = G.items.find(x => x[0] === r.dataset.gt); if (!it) return;
      ['T', 'R', 'G', 'N'].forEach((k, i) => $(`#gl${k}_${sid}`).value = it[i] || '');
      $('#glR_' + sid).focus();
    });
    if ($('#glMore', host)) $('#glMore', host).onclick = () => { G.more += 500; redrawList(); };
  };
  const pick = f => {
    if (!f) return;
    if (f.size > 900000) return toast('Файл завеликий (до ~900 КБ)');
    const rd = new FileReader();
    rd.onload = () => { G.file = {name: f.name, text: rd.result}; draw(); };
    rd.readAsText(f, 'utf-8');
  };
  const bind = () => {
    $$('[data-glset]', host).forEach(b => b.onclick = async () => {
      const id = b.dataset.glset, on = G.sets.includes(id);
      const a = G.avail.find(x => x.id === id);
      if (!on && a && a.adult && !confirm(`Увімкнути «${a.name}» для цього тайтлу? Переклад буде без цензури, з відвертою лексикою.`)) return;
      const r = await post({op: 'gloss_sets', sets: on ? G.sets.filter(x => x !== id) : G.sets.concat([id])});
      if (r.ok) { Object.assign(G, {sets: r.sets, setsAuto: r.setsAuto, adultAuto: r.adultAuto}); draw(); }
    });
    if ($('[data-glauto]', host)) $('[data-glauto]', host).onclick = async e => {
      e.preventDefault();
      const r = await post({op: 'gloss_sets', sets: null});
      if (r.ok) { Object.assign(G, {sets: r.sets, setsAuto: r.setsAuto, adultAuto: r.adultAuto}); draw(); }
    };
    const autoAct = async (act, term) => {
      const r = await post({op: 'gloss_auto', act, term});
      if (r.ok) { Object.assign(G, {items: r.items, auto: r.auto || [], autoBad: r.autoBad || []}); draw(); }
    };
    $$('[data-gla]', host).forEach(b => b.onclick = () => {
      if (b.dataset.gla === 'toggle') { G.autoOpen = !G.autoOpen; return draw(); }
      if (b.dataset.gla === 'export') return exportCsv(G.auto, ' (авто)');
      if (confirm(`Прибрати всі ${G.auto.length} автоматично знайдених термінів? Твої записи й набори не зміняться.`)) autoAct('clear');
    });
    $$('[data-glpro]', host).forEach(b => b.onclick = () => autoAct('promote', b.dataset.glpro));
    $$('[data-gldel]', host).forEach(b => b.onclick = () => autoAct('delete', b.dataset.gldel));
    $$('[data-glview]', host).forEach(b => b.onclick = async () => {
      if (G.view === b.dataset.glview) { G.view = ''; return draw(); }
      const r = await post({op: 'gloss_set_view', id: b.dataset.glview});
      if (r.ok) { G.view = b.dataset.glview; G.viewData = r; draw(); }
    });
    const q = $('#glQ_' + sid);
    q.oninput = () => { G.q = q.value; G.more = 120; redrawList(); };
    $('#glF_' + sid).onchange = e => pick(e.target.files[0]);
    $$('[data-gl]', host).forEach(b => b.onclick = async () => {
      const a = b.dataset.gl;
      if (a === 'file') return $('#glF_' + sid).click();
      if (a === 'cancel') { G.file = null; return draw(); }
      if (a === 'merge' || a === 'replace') {
        if (a === 'replace' && G.items.length && !confirm(`Замінити всі ${G.items.length} термінів вмістом файлу?`)) return;
        b.disabled = true;
        const r = await post({op: 'gloss_import', name: G.file.name, text: G.file.text, mode: a});
        if (!r.ok) { b.disabled = false; return; }
        const was = G.items.length; Object.assign(G, {items: r.items, notes: r.notes, file: null, q: ''}); draw();
        return toast(a === 'merge' ? `Додано ${Math.max(0, r.items.length - was)} нових, усього ${r.items.length}` : `Завантажено ${r.items.length} термінів`);
      }
      if (a === 'export') return exportCsv(G.items, '');
      if (a === 'clear') {
        if (!confirm(`Прибрати всі ${G.items.length} термінів? Правила лишаться. Порада: спершу «Експорт .csv».`)) return;
        G.items = []; if ((await save()).ok) draw(); return;
      }
      if (a === 'add') {
        const v = ['T', 'R', 'G', 'N'].map(k => $(`#gl${k}_${sid}`).value.trim());
        if (!v[0] || !v[1]) { $(v[0] ? '#glR_' + sid : '#glT_' + sid).focus(); return toast('Потрібні термін і переклад'); }
        const had = G.items.some(it => it[0].toLowerCase() === v[0].toLowerCase());
        G.items = G.items.filter(it => it[0].toLowerCase() !== v[0].toLowerCase()).concat([v]);
        if ((await save()).ok) { draw(); toast(had ? 'Змінено' : 'Додано'); $('#glT_' + sid).focus(); }
        return;
      }
      if (a === 'notes') { G.notes = $('#glNotes_' + sid).value; if ((await save()).ok) toast('Правила збережено'); }
    });
    $$(`#glT_${sid},#glR_${sid},#glG_${sid},#glN_${sid}`).forEach(i => i.onkeydown = e => { if (e.key === 'Enter') $('[data-gl="add"]', host).click(); });
    bindRows();
  };
  host.ondragover = e => { e.preventDefault(); host.classList.add('gl-over'); };
  host.ondragleave = e => { if (!host.contains(e.relatedTarget)) host.classList.remove('gl-over'); };
  host.ondrop = e => { e.preventDefault(); host.classList.remove('gl-over'); pick(e.dataTransfer.files[0]); };
  host.innerHTML = '<p class="note">Завантажую…</p>';
  post({op: 'gloss_get'}).then(r => { if (r.ok) Object.assign(G, {items: r.items, notes: r.notes, auto: r.auto || [], autoBad: r.autoBad || [], sets: r.sets || [], setsAuto: r.setsAuto !== false, adultAuto: r.adultAuto, avail: r.setsAvail || []}); draw(); });
}

const TRN = {local: 'Локальна', gemini: 'Gemini', deepl: 'DeepL', azure: 'Azure'};
function trLocal(st) {
  return `<div class="srow"><div class="sl"><b>Локальна модель (ПК)</b><small>${st.local ? `<b style="color:var(--acc)">Підключено: ${esc(st.localUrl)}${st.localModel ? ' · ' + esc(st.localModel) : ''}.</b> ` : ''}Модель на твоєму ПК через LM Studio: без лімітів і цензури, тексти нікуди не йдуть. У LM Studio: Model Server → «Serve on Local Network» → Start. Впиши адресу ПК у домашній мережі (порт 1234) і, якщо задав, API-токен. Коли ПК вимкнений — перекладе наступний перекладач (крім 18+, якщо «18+ лише локально»: ті серії чекають ПК).</small></div></div>
    <div class="fadd"><input id="key_local" autocomplete="off" value="${esc(st.localUrl ? st.localUrl.replace(/^https?:\/\//, '').replace(/\/v1$/, '') : '')}" placeholder="192.168.3.50:1234" aria-label="Адреса ПК з моделлю">
      <input id="key_localtok" type="password" autocomplete="off" style="max-width:190px" placeholder="${st.localToken ? '•••• токен збережено' : 'токен (якщо є)'}" aria-label="API-токен LM Studio">
      <button class="btn primary" data-savekey="local">Перевірити й зберегти</button>${st.local ? '<button class="btn ghost" data-forget="local">Забути</button>' : ''}</div>` +
    (st.local ? `<div class="srow"><div class="sl"><b>Модель</b><small>Яку модель LM Studio має завантажувати для перекладу. «Як у LM Studio» — ту, що там уже завантажена, а якщо жодної — ту, що була минулого разу. Іншу модель, що висить у LM Studio, VidBox сам вивантажить. Велику MoE-модель (напр. Gemma 4 26B-A4B на 12 ГБ) у LM Studio треба налаштувати: експерти (MoE-шари) на CPU, Max Concurrent 1 — інакше вона вилізе з відеопам'яті й драйвер може падати.</small></div>
      <div class="sc"><label class="sel wide"><select id="aiPin" aria-label="Модель для перекладу"><option value="">Як у LM Studio${st.localModel ? ' (зараз: ' + esc(st.localModel) + ')' : ''}</option>${(st.localModels || []).map(m => `<option value="${esc(m)}" ${st.localPin === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label></div></div>` : '') +
    (st.local ? `<div class="srow"><div class="sl"><b>Одночасних запитів до ПК</b><small>Скільки шматків серії модель перекладає разом. <b>На картах з 12 ГБ і менше — 1</b>: на RX 6700 XT два запити не влізли у відеопам'ять, і LM Studio падав. 2–3 — для карт з 16–24 ГБ. Зміна діє одразу; якщо на кількох запитах LM Studio видає помилку — до кінця серії VidBox перекладає по одному. У LM Studio «Parallel» має бути не менше, а «Context Length» — ≈ 4 тис. на кожен запит (2 → 8192, 3 → 12288). Не влізе в контекст — VidBox перекладе ці репліки по одній.</small></div>
      <div class="sc"><div class="seg" id="aiPar">${[1, 2, 3].map(n => `<button data-par="${n}" class="${(st.localPar || 1) === n ? 'on' : ''}">${n}</button>`).join('')}</div></div></div>` : '');
}
function trKey(k, has, hint) {
  return `<div class="srow"><div class="sl"><b>Ключ ${TRN[k]}</b><small>${has ? '<b style="color:var(--acc)">Ключ збережено.</b> ' : ''}${hint}</small></div></div>
    <div class="fadd"><input id="key_${k}" type="password" autocomplete="off" placeholder="${has ? '•••••••• (вставити новий, щоб замінити)' : `Ключ ${TRN[k]}`}" aria-label="Ключ ${TRN[k]}">
      ${k === 'azure' ? '<input id="key_region" style="max-width:150px" placeholder="регіон, напр. westeurope" aria-label="Регіон Azure">' : ''}
      <button class="btn primary" data-savekey="${k}">Зберегти</button>${has ? `<button class="btn ghost" data-forget="${k}">Забути</button>` : ''}${k === 'deepl' && has ? '<button class="btn" id="aiUse">Скільки лишилось</button>' : ''}</div>`;
}
function subName(t) {
  let n = '';
  try { if (t.lang) n = new Intl.DisplayNames(['uk'], {type: 'language'}).of(t.lang); } catch (e) {}
  if (!n) return t.label || `Доріжка ${t.n + 1}`;
  if (t.ai) return `${n} · ШІ`;
  return t.label && t.label.toLowerCase() !== n.toLowerCase() ? `${n} · ${t.label}` : n;
}
function parseVtt(txt) {
  const ts = x => { const p = x.trim().split(':').map(Number); return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1]; };
  const out = [];
  for (const block of txt.replace(/\r/g, '').split(/\n\n+/)) {
    const lines = block.split('\n'), i = lines.findIndex(l => l.includes('-->'));
    if (i < 0) continue;
    const [a, b] = lines[i].split('-->'), text = lines.slice(i + 1).join('\n').trim();
    if (text) out.push({s: ts(a), e: ts(b.trim().split(/\s+/)[0]), t: text});
  }
  return out.sort((x, y) => x.s - y.s);
}
// Лишаємо курсив/жирний/підкреслення, прибираємо теги ASS ({\an8} тощо) і решту розмітки.
const cueHTML = t => esc(t.replace(/\{[^}]*\}/g, '').replace(/\\N/gi, '\n')).replace(/&lt;(\/?)(i|b|u)&gt;/g, '<$1$2>')
  .replace(/&lt;[^&]*?&gt;/g, '').replace(/\n/g, '<br>');

function playerHTML(v, next) {
  const pp = `${svg(PI.play, 'solid ic-play')}${svg(PI.pause, 'solid ic-pause')}`;
  return `<div class="vp paused" id="vp" tabindex="-1" aria-label="Відеоплеєр">
  <video id="pv" playsinline preload="metadata"${v.thumb ? ` poster="/thumb/${v.id}?v=${v.thumb}"` : ''}></video>
  <div class="vp-hit"></div>
  <div class="vp-subs" aria-hidden="true"></div>
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
        <button class="vp-b vp-txt vp-cc" data-a="subs" title="Субтитри (C)" aria-label="Субтитри" hidden>CC</button>
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
  const subsEl = q('.vp-subs'), ccBtn = q('[data-a=subs]');
  const SB = {list: [], on: -1, last: -1, cues: [], vtt: {}, shown: '', ai: null, aiReady: false, poll: 0};
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
    drawSubs();
  }

  // ── субтитри: сервер віддає WebVTT, малюємо самі за часом від початку файлу (працює й під час перекодування) ──
  function drawSubs() {
    let h = '';
    if (SB.on >= 0) {
      const t = video.currentTime;
      h = SB.cues.filter(c => c.s <= t && t < c.e).map(c => `<span>${cueHTML(c.t)}</span>`).join('<br>');
    }
    if (h !== SB.shown) { subsEl.innerHTML = h; SB.shown = h; }
  }
  async function pickSub(n, save = true) {
    if (save) LS.set('subs', n < 0 ? {off: true} : {lang: SB.list[n].lang, label: SB.list[n].label});
    SB.on = -1; drawSubs(); ccBtn.classList.toggle('on', n >= 0);
    if (n < 0) return;
    SB.last = n;
    if (!SB.vtt[n]) {
      const slow = setTimeout(() => { if (!dead) vpToast('Готую субтитри…'); }, 600);
      try {
        const r = await fetch(`/subs/${v.id}/${n}.vtt`);
        if (!r.ok) throw new Error(r.status);
        const cues = parseVtt(await r.text());
        if (!cues.length) throw new Error('empty');
        SB.vtt[n] = cues;
      } catch (e) {
        clearTimeout(slow);
        if (!dead) { vpToast('Ці субтитри не вдалося прочитати'); ccBtn.classList.remove('on'); }
        return;
      }
      clearTimeout(slow);
    }
    if (dead || SB.last !== n) return;
    SB.on = n; SB.cues = SB.vtt[n]; drawSubs();
  }
  video.addEventListener('timeupdate', drawSubs);
  video.addEventListener('seeked', drawSubs);
  const aiBusy = () => SB.ai && !['done', 'error'].includes(SB.ai.state);
  async function aiPoll() {            // чекаємо субтитри ШІ, поки відкритий плеєр
    clearTimeout(SB.poll);
    if (dead || !aiBusy()) return;
    SB.poll = setTimeout(async () => {
      const r = await api(`/api/subs/${v.id}`).catch(() => null);
      if (dead || !r) return;
      SB.ai = r.ai;
      if (!aiBusy()) {
        const had = new Set(SB.list.map(t => t.n));
        SB.list = r.subs || [];
        const fresh = SB.list.find(t => t.ai && t.lang === 'uk' && !had.has(t.n)) || SB.list.find(t => t.ai && !had.has(t.n));
        if (fresh) { pickSub(fresh.n); vpToast(`Субтитри ШІ готові: ${subName(fresh)}`); }
        else if (SB.ai && SB.ai.state === 'error') vpToast('Субтитри ШІ: ' + (SB.ai.err || 'не вдалося'));
      }
      if (!menu.hidden && menu.dataset.kind === 'subs') openMenu('subs');
      aiPoll();
    }, 8000);
  }
  api(`/api/subs/${v.id}`).then(r => {
    if (dead || !r) return;
    SB.ai = r.ai; SB.aiReady = r.aiReady;
    if (SB.aiReady) ccBtn.hidden = false;
    aiPoll();
    if (!r.subs || !r.subs.length) return;
    SB.list = r.subs; ccBtn.hidden = false;
    const pref = LS.get('subs', null);
    if (pref && pref.off) return;
    const pick = pref && (SB.list.find(t => t.lang === pref.lang && t.label === pref.label) || pref.lang && SB.list.find(t => t.lang === pref.lang))
      || SB.list.find(t => t.def && !t.forced) || SB.list.find(t => !t.forced) || SB.list[0];
    pickSub(pick.n, false);
  }).catch(() => {});
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
    menu.innerHTML = kind === 'subs'
      ? '<p>Субтитри</p>' + `<button data-sub="-1" class="${SB.on < 0 ? 'on' : ''}">Вимкнено</button>` +
        SB.list.map(t => `<button data-sub="${t.n}" class="${SB.on === t.n ? 'on' : ''}">${esc(subName(t))}${t.forced ? '<small>лише написи</small>' : ''}</button>`).join('') +
        (SB.on >= 0 ? `<a class="vp-mlink" href="/subs/${v.id}/${SB.on}.vtt" download="${esc((v.title || 'subs').replace(/[\\/:*?"<>|]+/g, ' ').trim())}.${SB.list[SB.on] && SB.list[SB.on].lang || 'xx'}.vtt">${I.download || ''}Завантажити ці субтитри</a>` : '') +
        (!SB.aiReady ? '' : aiBusy() ? `<p class="vp-ai">ШІ: ${esc(aiStateText(SB.ai))}</p>`
          : SB.list.some(t => t.ai && t.lang === 'uk') ? `<button data-aidel>${I.trash}Видалити субтитри ШІ</button>`
          : `<button data-aisub>${I.plus}Українські (ШІ)</button>${SB.ai && SB.ai.err ? `<p class="vp-ai">${esc(SB.ai.err)}</p>` : ''}`)
      : kind === 'quality' && o.quality
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
    subs: () => (menu.hidden || menu.dataset.kind !== 'subs' ? openMenu('subs') : closeMenu()),
    pip: togglePip, fs: toggleFs, next: () => { if (o.onNext) { wantFs = !!fsEl(); o.onNext(); } },
  };

  vp.addEventListener('click', async e => {
    const r = e.target.closest('[data-rate]');
    if (r) { setRate(+r.dataset.rate); closeMenu(); return; }
    if (e.target.closest('[data-aidel]')) {
      closeMenu();
      const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify({op: 'delete', ids: [v.id]})}).catch(() => null);
      if (!r || !r.ok) return vpToast('Не вдалося видалити');
      if (SB.on >= 0 && SB.list[SB.on] && SB.list[SB.on].ai) pickSub(-1, false);
      SB.list.filter(t => t.ai).forEach(t => delete SB.vtt[t.n]);
      SB.list = SB.list.filter(t => !t.ai); SB.ai = null;
      vpToast('Субтитри ШІ видалено — можна зробити заново');
      return;
    }
    if (e.target.closest('[data-aisub]')) {
      closeMenu();
      const r = await api('/api/aisubs', {method: 'POST', body: JSON.stringify({op: 'add', ids: [v.id]})}).catch(() => null);
      if (!r || !r.ok) return vpToast('Не вдалося додати в чергу');
      SB.ai = {state: 'queued', p: 0};
      vpToast('Додав у чергу. Субтитри з’являться самі, коли будуть готові — серія займає 15–40 хв');
      aiPoll();
      return;
    }
    const sb = e.target.closest('[data-sub]');
    if (sb) { closeMenu(); pickSub(+sb.dataset.sub); return; }
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
      case 'KeyC': if (SB.list.length) { const n = SB.on >= 0 ? -1 : SB.last >= 0 ? SB.last : SB.list[0].n; pickSub(n); showBadge(n < 0 ? 'Субтитри вимкнено' : `Субтитри: ${esc(subName(SB.list[n]))}`, 1200); } break;
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
      dead = true; clearTimeout(SB.poll);
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
