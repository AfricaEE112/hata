'use strict';
// Hata: вхід, майстер першого налаштування і панель сервера. Без бібліотек і збирачів.

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const app = $('#app');
const bar = $('#top');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const size = b => { if (!b) return '0'; const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return (b >= 100 || i < 3 ? Math.round(b) : b.toFixed(1)).toString().replace('.', ',') + ' ' + u[i]; };
const short = b => { if (!b) return '0'; const u = ['B', 'K', 'M', 'G', 'T']; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return (b >= 10 || i === 0 ? Math.round(b) : b.toFixed(1)) + u[i]; };
const uptime = s => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d} д ${h} год` : h ? `${h} год ${m} хв` : `${m} хв`; };
const typing = () => /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '');
let HOST = 'hata';

async function api(url, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  try {
    const r = await fetch(url, opt);
    const j = await r.json().catch(() => ({}));
    if (r.status === 401 && j.error === 'auth') { start(); return {ok: false, error: 'Потрібно увійти'}; }
    return j;
  } catch (e) {
    return {ok: false, error: 'Немає зв’язку з сервером'};
  }
}

let toastT;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 4000);
}

// ───────────────────────── кольорові схеми ─────────────────────────
// [фон, акцент] — лише для кружечків-перемикачів; самі кольори в hata.css.
const SCHEMES = {'чай': ['#191713', '#7cc6b1'], 'ніч': ['#1e1e2e', '#89b4fa'], 'lain': ['#1c1e25', '#b4c3f0'],
  'ягода': ['#2a1022', '#f4a6d7'], 'nothing': ['#000', '#f2f2f2'], 'папір': ['#e9e1cf', '#2f7d6d']};
const scheme = () => document.documentElement.dataset.scheme || 'чай';
function setScheme(name, save) {
  if (!SCHEMES[name]) return;
  document.documentElement.dataset.scheme = name;
  try { localStorage.setItem('hata_scheme', name); } catch (e) {}
  $$('.schemes button').forEach(b => { b.classList.toggle('on', b.dataset.scheme === name); b.setAttribute('aria-pressed', b.dataset.scheme === name); });
  $$('.schemes summary i').forEach(i => { i.style.setProperty('--b', SCHEMES[name][0]); i.style.setProperty('--a', SCHEMES[name][1]); });
  $$('details.schemes').forEach(d => d.open = false);
  if (save) api('/api/scheme', {scheme: name});
}
// Ряд кружечків (на вході) або компактне меню «колір» (у верхньому рядку).
const schemeBtns = names => Object.entries(SCHEMES).map(([n, [b, a]]) =>
  `<button type="button" data-scheme="${n}" title="${n}" aria-label="Схема ${n}" aria-pressed="${n === scheme()}" class="${n === scheme() ? 'on' : ''}" style="--b:${b};--a:${a}"><i></i>${names ? n : ''}</button>`).join('');
const schemePicker = inline => inline
  ? `<div class="schemes" role="group" aria-label="Кольорова схема">${schemeBtns(false)}</div>`
  : `<details class="schemes"><summary title="Кольорова схема" aria-label="Кольорова схема"><i style="--b:${SCHEMES[scheme()][0]};--a:${SCHEMES[scheme()][1]}"></i></summary>` +
    `<div class="pop" role="group" aria-label="Кольорова схема">${schemeBtns(true)}</div></details>`;
function bindSchemes(save) { $$('.schemes button').forEach(b => b.onclick = () => setScheme(b.dataset.scheme, save)); }

// ───────────────────────── дрібні будівельні блоки ─────────────────────────
const who = () => `<span class="who"><b>хата</b><i>@</i>${esc(HOST)}<span class="cur" aria-hidden="true">▌</span></span>`;
const prompt = (path, cmd) => `<p class="prompt"><span class="u">хата@${esc(HOST)}:${esc(path)}$</span> <span class="c">${esc(cmd)}</span></p>`;
// Рамка з назвою в лінії: win('диски', тіло, {n: '²', c: 'yel', id: 'disks', cls: 'w2'})
const win = (label, body, o = {}) => `<section class="win ${o.cls || ''}"${o.id ? ` id="${o.id}"` : ''}${o.c ? ` style="--c:var(--${o.c})"` : ''} aria-label="${esc(label)}">` +
  `<div class="lbl">${o.n ? `<sup>${o.n}</sup>` : ''}${esc(label)}${o.badge ? `<span class="badge">${esc(o.badge)}</span>` : ''}</div><div class="wbody">${body}</div></section>`;
// Сегментована смужка: до 60% — акцент, до 85% — жовтий, далі — червоний.
const segs = (pct, n = 24, cls = '') => `<span class="segs ${cls}" aria-hidden="true">${Array.from({length: n}, (_, i) => {
  const f = (i + .5) / n; return `<i class="${f > pct / 100 ? '' : f < .6 ? 'a' : f < .85 ? 'y' : 'r'}"></i>`; }).join('')}</span>`;
const heat = v => v < 35 ? 'acc' : v < 60 ? 'yel' : 'red';

// Точковий годинник 5×7.
const FONT = {'0': '01110100011001110101110011000101110', '1': '00100011000010000100001000010001110', '2': '01110100010000100010001000100011111',
  '3': '11110000010000101110000010000111110', '4': '00010001100101010010111110001000010', '5': '11111100001111000001000011000101110',
  '6': '00110010001000011110100011000101110', '7': '11111000010001000100010000100001000', '8': '01110100011000101110100011000101110',
  '9': '01110100011000101111000010001001100', ':': '0010100', ' ': '0000000'};
const dots = (text, big) => `<div class="dots${big ? ' big' : ''}" role="img" aria-label="${esc(text.replace(' ', ':'))}">${[...text].map(ch => {
  const bits = FONT[ch] || FONT[' ']; const cols = bits.length / 7;
  return `<div style="grid-template-columns:repeat(${cols},var(--d,7px))">${[...bits].map(b => `<i${b === '1' ? ' class="on"' : ''}></i>`).join('')}</div>`; }).join('')}</div>`;
const hhmm = (sep = ':') => { const d = new Date(); return String(d.getHours()).padStart(2, '0') + sep + String(d.getMinutes()).padStart(2, '0'); };
const weekday = () => new Date().toLocaleDateString('uk-UA', {weekday: 'long'}).toUpperCase();
const today = () => new Date().toLocaleDateString('uk-UA', {day: 'numeric', month: 'long', year: 'numeric'});
setInterval(() => {   // годинники на сторінці; двокрапка блимає
  const blink = new Date().getSeconds() % 2 ? ' ' : ':';
  $$('[data-clock]').forEach(el => el.innerHTML = dots(hhmm(blink), el.dataset.clock === 'big'));
  $$('.clock').forEach(el => el.textContent = hhmm());
}, 1000);

// ───────────────────────── старт ─────────────────────────
let STATE = null;
async function start() {
  stopPanel();
  STATE = await api('/api/state');
  if (STATE.ok === false && !STATE.setup) { app.innerHTML = `<div class="wrap">${win('помилка', '<p>Сервер Hata не відповідає. Спробуй оновити сторінку за хвилину.</p>', {c: 'red'})}</div>`; return; }
  HOST = STATE.host || 'hata';
  if (STATE.scheme) setScheme(STATE.scheme);
  document.title = STATE.setup ? `Хата — ${HOST}` : 'Хата — налаштування';
  if (STATE.hasPassword && !STATE.authed) return login();
  if (!STATE.setup) return wizard(STATE.hasPassword ? Math.max(W.step, 2) : W.step);
  return panel();
}

// ───────────────────────── вхід ─────────────────────────
function login() {
  bar.hidden = true;
  app.innerHTML = `<div class="login">
    <div data-clock="big">${dots(hhmm(), true)}</div>
    <p class="day">${weekday()}</p><p class="date">${today()}</p>
    ${win('вхід', `<h1>${who()}</h1><div class="dash"></div>
      <dl class="kv"><dt>хост</dt><dd>${esc(HOST)}</dd><dt>адреса</dt><dd>${esc(location.host)}</dd><dt>пароль</dt><dd>той, що задав у майстрі</dd></dl>
      <form id="lf"><label class="field"><span aria-hidden="true">❯</span><input id="pw" type="password" autocomplete="current-password" placeholder="пароль" aria-label="Пароль" autofocus></label>
      <button class="btn primary">Увійти</button></form><div class="err" id="le" role="alert"></div>`)}
    <div class="foot">${schemePicker(true)}<span>забув пароль — <code>sudo gazda password</code> на самій Хаті</span></div>
  </div>`;
  let picked = false;     // вибрав колір до входу — збережемо його після входу
  $$('.schemes button').forEach(x => x.onclick = () => { picked = true; setScheme(x.dataset.scheme, false); });
  $('#lf').onsubmit = async e => {
    e.preventDefault();
    $('#le').textContent = '';
    const r = await api('/api/login', {password: $('#pw').value});
    if (r.ok) { if (picked) await api('/api/scheme', {scheme: scheme()}); start(); }
    else $('#le').textContent = r.error || 'Не вдалося увійти';
  };
}

// ───────────────────────── майстер ─────────────────────────
const STEPS = ['вітання', 'пароль', 'диски', 'папки', 'tailscale', 'ноутбук', 'готово'];
const W = Object.assign({step: 0, folders: [], anime: ''}, JSON.parse(sessionStorage.getItem('hata_wiz') || '{}'));
const saveW = () => sessionStorage.setItem('hata_wiz', JSON.stringify(W));
let fromPanel = false;    // крок майстра відкрито з панелі (диски, Tailscale): без кроків, «До панелі»

function wizTop() {
  bar.hidden = false;
  bar.innerHTML = `${who()}<span class="tag">${fromPanel ? 'панель' : 'налаштування'}</span><span class="sp"></span>${schemePicker()}`;
  bindSchemes(!!STATE.hasPassword);
}

function frame(i, title, lead, body) {
  wizTop();
  const steps = fromPanel ? '' : `<div class="steps">${STEPS.map((s, k) => `<span class="${k === i ? 'on' : k < i ? 'done' : ''}">${k < i ? '✓ ' : ''}${s}</span>`).join('')}</div>`;
  return `<div class="wrap">${prompt('~/setup', fromPanel ? `hata ${STEPS[i]}` : `hata-setup --step ${i + 1}/${STEPS.length}`)}${steps}` +
    `<h1 class="title">${title}</h1><p class="lead">${lead}</p>${body}</div>`;
}

function wizard(i) {
  W.step = i; saveW();
  ({0: stepHello, 1: stepPassword, 2: stepDisks, 3: stepFolders, 4: stepTailscale, 5: stepLaptop, 6: stepDone})[i]();
  window.scrollTo(0, 0);
}
const next = () => wizard(W.step + 1);
const back = () => wizard(Math.max(STATE.hasPassword ? 2 : 0, W.step - 1));
const nav = (nextLabel = 'Далі', extra = '') => fromPanel
  ? `<div class="acts"><span class="sp"></span>${extra}<button class="btn primary" id="next">До панелі</button></div>`
  : `<div class="acts">${W.step > (STATE.hasPassword ? 2 : 0) ? '<button class="btn ghost" id="back">Назад</button>' : ''}<span class="sp"></span>${extra}<button class="btn primary" id="next">${nextLabel}</button></div>`;
function bindNav(onNext) {
  if ($('#back')) $('#back').onclick = back;
  $('#next').onclick = fromPanel ? () => { clearTimeout(tsTimer); fromPanel = false; panel(); } : (onNext || next);
}
function openFromPanel(step) { stopPanel(); fromPanel = true; W.step = step; ({2: stepDisks, 4: stepTailscale})[step](); window.scrollTo(0, 0); }

function stepHello() {
  app.innerHTML = frame(0, 'Привіт, це Хата', 'Твій домашній сервер майже готовий. Кілька кроків — і він сам підключить диски, запустить VidBox і, якщо захочеш, буде доступний звідусіль через Tailscale.',
    win('про хату', `<dl class="kv"><dt>сервер</dt><dd>${esc(HOST)}</dd><dt>адреса</dt><dd>${esc(location.host)}</dd><dt>кроки</dt><dd>пароль → диски → папки → Tailscale → ноутбук</dd></dl>
      <p class="note">Будь-який крок можна змінити пізніше в панелі. Колір — кружечки вгорі праворуч.</p>`) + nav('Почати'));
  bindNav();
}

function stepPassword() {
  app.innerHTML = frame(1, 'Пароль', 'Один пароль на все: панель Хати, VidBox і Android-апку. Кожен пристрій вводить його один раз.',
    win('пароль', `<form id="pf"><label class="f" for="p1">новий пароль</label><input id="p1" type="password" autocomplete="new-password" autofocus>
      <label class="f" for="p2">ще раз</label><input id="p2" type="password" autocomplete="new-password">
      <div class="err" id="pe" role="alert"></div></form>`) + nav('Зберегти'));
  bindNav(async () => {
    const a = $('#p1').value, b = $('#p2').value;
    if (a.length < 6) return $('#pe').textContent = 'Щонайменше 6 символів';
    if (a !== b) return $('#pe').textContent = 'Паролі не збігаються';
    const r = await api('/api/setup/password', {password: a});
    if (!r.ok) return $('#pe').textContent = r.error;
    STATE.hasPassword = true; STATE.authed = true;
    api('/api/scheme', {scheme: scheme()});
    next();
  });
  $('#pf').onsubmit = e => { e.preventDefault(); $('#next').click(); };
}

async function stepDisks() {
  app.innerHTML = frame(2, 'Диски', 'Обери диски з фільмами й аніме. Хата підключатиме їх сама після кожного вмикання — за назвою, тож шляхи не зміняться, навіть якщо переставиш кабелі.',
    win('диски', '<p class="note"><span class="spin"></span> Шукаю диски…</p>', {c: 'yel'}) + nav());
  bindNav();
  const r = await api('/api/disks');
  const list = (r.disks || []);
  const body = list.length ? list.map(d => {
    const name = d.name || (d.label || d.dev.split('/').pop()).toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32) || 'disk';
    const meta = [size(d.size), d.fs, d.model, d.usb ? 'USB' : ''].filter(Boolean).join(' · ');
    return `<div class="row"><div class="l"><b>${esc(d.label || d.dev)}</b><small>${esc(meta)}</small></div><div class="r">` +
      (d.system ? '<span class="tag">системний</span>' :
       d.name ? `<span class="tag ok">/srv/disks/${esc(d.name)}</span>` :
       `<input type="text" value="${esc(name)}" aria-label="Назва диска" data-name="${esc(d.uuid)}"><button class="btn" data-mount="${esc(d.uuid)}">Підключити</button>`) +
      '</div></div>';
  }).join('') : '<p class="note">Дисків з даними не знайдено. Підключи диск і натисни «Оновити список».</p>';
  $('.win .wbody').innerHTML = body + `<div class="err" id="de" role="alert"></div><div class="acts"><button class="btn ghost" id="rescan">Оновити список</button></div>`;
  $('#rescan').onclick = stepDisks;
  $$('[data-mount]').forEach(b => b.onclick = async () => {
    const uuid = b.dataset.mount, name = $(`[data-name="${uuid}"]`).value.trim().toLowerCase();
    b.disabled = true; b.innerHTML = '<span class="spin"></span>';
    const res = await api('/api/mount', {uuid, name});
    if (!res.ok) { $('#de').textContent = res.error; b.disabled = false; b.textContent = 'Підключити'; return; }
    toast(`Підключено: ${res.path}`);
    stepDisks();
  });
}

let foldersSeq = 0;
async function stepFolders(path) {
  const my = ++foldersSeq;    // швидкі кліки: застаріла відповідь не перемальовує новіший екран
  const r = await api('/api/dirs' + (path ? '?path=' + encodeURIComponent(path) : ''));
  if (my !== foldersSeq) return;
  const chosen = W.folders.map(f => `<div class="row"><div class="l"><b class="link">${esc(f)}</b><small>відео</small></div><div class="r"><button class="btn ghost" data-rm="${esc(f)}">Прибрати</button></div></div>`).join('') +
    (W.anime ? `<div class="row"><div class="l"><b class="link">${esc(W.anime)}</b><small>аніме — окремий розділ</small></div><div class="r"><button class="btn ghost" data-rma>Прибрати</button></div></div>` : '');
  const here = r.path ? `<div class="acts" style="margin-top:6px"><button class="btn" id="asVideo">Тут відео</button><button class="btn" id="asAnime">Тут аніме</button></div>` : '';
  const dirs = (r.up !== undefined && r.path ? `<div class="row"><div class="l"><b><a href="#" data-go="${esc(r.up)}">..</a></b></div></div>` : '') +
    (r.dirs || []).map(d => `<div class="row"><div class="l"><b><a href="#" data-go="${esc(d.path)}">${esc(d.name)}/</a></b></div></div>`).join('') ||
    '<p class="note">Тут порожньо. Спершу підключи диск на попередньому кроці.</p>';
  app.innerHTML = frame(3, 'Папки', 'Покажи, де лежать відео, а де аніме. Аніме буде окремим розділом з постерами: кожна підпапка — тайтл, файли в ній — серії.',
    win('вибрано', chosen ? chosen : '<p class="note">Поки нічого не вибрано.</p>') +
    win('огляд', `<div class="crumbs">${esc(r.path || 'диски')}</div>${dirs}${here}<div class="err" id="fe" role="alert"></div>`, {c: 'yel'}) + nav());
  bindNav(() => { if (!W.folders.length) return $('#fe').textContent = 'Обери хоча б одну папку з відео'; next(); });
  $$('[data-go]').forEach(a => a.onclick = e => { e.preventDefault(); stepFolders(a.dataset.go); });
  $$('[data-rm]').forEach(b => b.onclick = () => { W.folders = W.folders.filter(f => f !== b.dataset.rm); saveW(); stepFolders(r.path); });
  if ($('[data-rma]')) $('[data-rma]').onclick = () => { W.anime = ''; saveW(); stepFolders(r.path); };
  if ($('#asVideo')) $('#asVideo').onclick = () => {
    if (r.path === W.anime) return $('#fe').textContent = 'Ця папка вже вибрана для аніме';
    if (!W.folders.includes(r.path)) W.folders.push(r.path); saveW(); stepFolders(r.path);
  };
  if ($('#asAnime')) $('#asAnime').onclick = () => {
    if (W.folders.some(f => r.path === f || r.path.startsWith(f + '/') || f.startsWith(r.path + '/')))
      return $('#fe').textContent = 'Аніме має бути окремою папкою, не всередині папки з відео (і навпаки)';
    W.anime = r.path; saveW(); stepFolders(r.path);
  };
}

let tsTimer;
async function stepTailscale() {
  clearTimeout(tsTimer);
  const st = await api('/api/tailscale');
  const running = st.state === 'Running';
  const body = running
    ? `<p><span class="okdot"></span>Підключено як <b class="link">${esc(st.name)}</b></p><p class="note">Тепер VidBox і панель доступні звідусіль, де на пристрої ввімкнено Tailscale.</p>`
    : st.url
      ? `<p>Відкрий посилання й увійди у свій акаунт Tailscale — і сервер з'явиться у твоїй мережі:</p><p><a class="btn primary" href="${esc(st.url)}" target="_blank" rel="noopener">Увійти в Tailscale</a></p><p class="note link">${esc(st.url)}</p><p class="note"><span class="spin"></span> Чекаю на вхід…</p>`
      : `<p>Tailscale — приватна мережа між твоїми пристроями. З ним VidBox працює не лише вдома, а й з мобільного інтернету, без відкритих портів на роутері.</p><div class="acts"><button class="btn" id="tsUp">Підключити Tailscale</button></div><div class="err" id="te" role="alert"></div>`;
  app.innerHTML = frame(4, 'Доступ звідусіль', 'Необов’язково — можна пропустити й увімкнути пізніше в панелі.', win('tailscale', body, {c: 'vio'}) + nav(running ? 'Далі' : 'Пропустити'));
  bindNav(() => { clearTimeout(tsTimer); next(); });
  if ($('#tsUp')) $('#tsUp').onclick = async () => {
    $('#tsUp').disabled = true; $('#tsUp').innerHTML = '<span class="spin"></span> Встановлюю й запускаю…';
    const r = await api('/api/tailscale', {op: 'up'});
    if (r.ok === false) { $('#te').textContent = r.error; $('#tsUp').disabled = false; $('#tsUp').textContent = 'Спробувати ще'; return; }
    stepTailscale();
  };
  if (!running && st.url) tsTimer = setTimeout(() => { if (W.step === 4) stepTailscale(); }, 3000);
}

async function stepLaptop() {
  const st = await api('/api/status');
  const b = st.battery;
  const lim = b && b.limitSupported ? `<div class="row"><div class="l"><b>Межа заряду батареї</b><small>Ноутбук весь час на зарядці — з межею 60–80% батарея живе в рази довше.</small></div>
     <div class="r"><div class="seg" id="lim" role="group" aria-label="Межа заряду">${[60, 80, 100].map(v => `<button data-v="${v}" class="${(b.limit || 100) === v ? 'on' : ''}">${v}%</button>`).join('')}</div></div></div>` : '';
  app.innerHTML = frame(5, 'Ноутбук', 'Сервер працює й із закритою кришкою — Хата вже це налаштувала.',
    win('ноутбук', `<div class="row"><div class="l"><b>Закрита кришка</b><small>Ноутбук не засинає, екран гасне.</small></div><div class="r"><span class="tag ok">увімкнено</span></div></div>` +
      (b ? lim + `<div class="row"><div class="l"><b>Батарея</b><small>${b.ac ? 'від мережі' : 'від батареї'}</small></div><div class="r"><span class="tag">${b.pct}%</span></div></div>`
         : `<div class="row"><div class="l"><b>Батарея</b><small>Не знайдено — схоже, це стаціонарний ПК.</small></div></div>`), {c: 'yel'}) + nav());
  bindNav();
  bindLimit();
}

function bindLimit() {
  $$('#lim button').forEach(x => x.onclick = async () => {
    const r = await api('/api/battery', {value: +x.dataset.v});
    if (!r.ok) return toast(r.error);
    $$('#lim button').forEach(y => y.classList.toggle('on', y === x)); toast(`Межа заряду: ${x.dataset.v}%`);
  });
}

function stepDone() {
  app.innerHTML = frame(6, 'Готово', 'Перевір і натисни «Завершити» — Хата запустить VidBox з твоїми папками.',
    win('підсумок', `<dl class="kv"><dt>відео</dt><dd>${W.folders.map(esc).join('<br>') || '—'}</dd><dt>аніме</dt><dd>${esc(W.anime) || 'не вибрано'}</dd><dt>пароль</dt><dd>встановлено</dd><dt>колір</dt><dd>${esc(scheme())}</dd></dl><div class="err" id="ce" role="alert"></div>`) + nav('Завершити'));
  bindNav(async () => {
    $('#next').disabled = true; $('#next').innerHTML = '<span class="spin"></span> Запускаю…';
    const r = await api('/api/finish', {folders: W.folders, anime: W.anime});
    if (!r.ok) { $('#ce').textContent = r.error || 'Не вдалося'; $('#next').disabled = false; $('#next').textContent = 'Завершити'; return; }
    sessionStorage.removeItem('hata_wiz');
    STATE.setup = true; toast('Хата налаштована');
    panel();
  });
}

// ───────────────────────── панель ─────────────────────────
const SECTIONS = [['1', 'огляд', 'sys'], ['2', 'диски', 'disks'], ['3', 'служби', 'svc'], ['4', 'мережа', 'net'], ['5', 'живлення', 'pwr'], ['6', 'журнал', 'log']];
const SVC = {vidbox: 'відео й аніме', hata: 'ця панель', 'hata-screen': 'екран на ноутбуці'};
const HIST = {cpu: [], net: [], lastNet: null};
let panelTimer, liveTimer, LAST = null, UPD = null;

function stopPanel() { clearTimeout(panelTimer); clearTimeout(liveTimer); }

function panelTop(s) {
  bar.hidden = false;
  const b = s.battery;
  bar.innerHTML = `${who()}<nav aria-label="Розділи">${SECTIONS.map(([k, l, id]) => `<a href="#${id}" data-k="${k}"><span>${k}</span>${l}</a>`).join('')}` +
    `<a class="ext" href="${esc(vidboxUrl(s))}">VidBox ↗</a></nav><span class="sp"></span>
    <dl class="stats"><div><dt>cpu</dt><dd id="tCpu">—</dd></div><div><dt>ram</dt><dd id="tRam">—</dd></div><div><dt>t°</dt><dd id="tTemp">—</dd></div>` +
    (b ? `<div><dt>бат</dt><dd style="display:flex;gap:6px;align-items:center">${segs(b.pct, 10).replace('class="segs ', 'style="width:52px;flex:none" class="segs ')}${b.pct}%</dd></div>` : '') +
    `<div><dt class="sr">час</dt><dd class="clock">${hhmm()}</dd></div></dl>${schemePicker()}`;
  bindSchemes(true);
  $$('.top nav a[data-k]').forEach(a => a.onclick = () => { $$('.top nav a').forEach(x => x.classList.toggle('on', x === a)); });
}
const vidboxUrl = s => `${location.protocol}//${location.hostname}:${s.vidbox.port}`;

async function panel() {
  stopPanel();
  fromPanel = false;
  const s = await api('/api/status');
  if (s.ok === false) { app.innerHTML = `<div class="wrap">${prompt('~', 'gazda status')}${win('помилка', `<p class="err">${esc(s.error)}</p>`, {c: 'red'})}</div>`; return; }
  LAST = s;
  panelTop(s);
  const ts = s.tailscale || {};
  const ver = (s.version || '').split(' ')[0] || '—';

  const sys = `<div class="when"><div data-clock="small">${dots(hhmm())}</div><p><span class="wd">${weekday()}</span><span class="dt">${today()}</span></p></div>
    <dl class="kv"><dt>хост</dt><dd>${esc(s.host)}${(s.ips || []).length ? ' · ' + s.ips.map(esc).join(', ') : ''}</dd>
      <dt>працює</dt><dd>${uptime(s.uptime)}</dd><dt>система</dt><dd>${esc(s.os)} · Хата ${esc(ver)}</dd></dl>
    <div class="gh"><span>cpu · ${s.cpus} ядер</span><b id="cpuNow">—</b></div><div class="graph" id="cpuG" aria-hidden="true"></div>
    <div class="meters" style="margin-top:14px" id="mem"></div>`;

  const disks = [{name: 'система', path: '/', mounted: true, ...(s.root || {})}].concat(s.disks || []);
  const dsk = `<div class="disks"><div class="drow h"><span>диск</span><span>заповнено</span><span style="text-align:right">зайнято</span></div>` +
    disks.map(d => {
      const used = (d.total || 0) - (d.free || 0), p = d.total ? used / d.total * 100 : 0;
      return `<div class="drow"><span class="n"><b>${esc(d.name)}</b><small>${esc(d.path || '')}</small></span>` +
        (d.mounted ? `${segs(p, 30)}<span class="v">${size(used)} <span>/ ${size(d.total)}</span></span>`
                   : `<span class="note" style="margin:0">диск не знайдено — він вимкнений або від'єднаний</span><span class="v"><span class="tag bad">відключено</span></span>`) + '</div>';
    }).join('') + `</div><div class="dock"><span>Новий диск у доці чи USB? Його можна підключити тут.</span><button class="btn" id="findDisks">Знайти диски</button></div>`;

  const svcRow = (name, desc, state, btns) => `<div class="row svc ${state === 'active' ? '' : 'off'}"><div class="l"><b><span class="okdot ${state === 'active' ? '' : 'off'}"></span>${esc(name)}</b><small>${esc(desc)}</small></div>` +
    `<div class="r"><span class="st">${state === 'active' ? 'працює' : esc(state || 'зупинена')}</span>${btns}</div></div>`;
  const svc = Object.entries(s.services || {}).map(([n, st]) => svcRow(n, SVC[n] || '', st, n === 'hata' ? '' :
      `<button class="btn" data-op="${st === 'active' ? 'stop' : 'start'}" data-name="${n}" aria-label="${st === 'active' ? 'Зупинити' : 'Запустити'} ${n}">${st === 'active' ? '■' : '▶'}</button>` +
      `<button class="btn" data-svc="${n}" aria-label="Перезапустити ${n}">↻</button>`)).join('') +
    svcRow('tailscale', ts.state === 'Running' ? 'доступ звідусіль' : ts.installed ? 'не підключено' : 'не встановлено', ts.state === 'Running' ? 'active' : 'вимкнено', '') +
    `<div class="row svc"><div class="l"><b><span class="okdot always"></span>gazda</b><small>керує системою, не зупиняється</small></div><div class="r"><span class="st" style="color:var(--yel)">завжди</span></div></div>`;

  const net = `<div id="ifaces"><p class="note" style="margin:0"><span class="spin"></span></p></div>
    <dl class="kv" style="margin-top:12px"><dt>ім'я</dt><dd>${esc(s.host)}.local</dd>
      <dt>tailscale</dt><dd>${ts.state === 'Running' ? `<span class="okdot"></span>${esc(ts.name)}` : ts.installed ? 'не підключено' : 'не встановлено'}</dd></dl>
    <div class="gh"><span>трафік</span><b id="netNow">—</b></div><div class="graph net" id="netG" aria-hidden="true"></div>
    <p class="note" id="speedRes" aria-live="polite"></p>
    <div class="acts"><button class="btn" id="speed">Перевірити швидкість</button><button class="btn" id="wifiBtn">Wi-Fi</button>${ts.state === 'Running' ? '' : '<button class="btn" id="tsOn">Tailscale</button>'}</div>`;

  const b = s.battery;
  const pwr = (b ? `<div class="gh" style="margin-top:0"><span>батарея · ${b.ac ? 'від мережі' : 'від батареї'}</span><b>${b.pct}%</b></div>${segs(b.pct, 20, 'tall')}` +
      (b.limitSupported ? `<p class="note" style="margin-top:16px">заряджати до</p><div class="seg" id="lim" role="group" aria-label="Межа заряду" style="margin-top:6px">${[60, 80, 100].map(v => `<button data-v="${v}" class="${(b.limit || 100) === v ? 'on' : ''}">${v}%</button>`).join('')}</div>` : '')
      : '<p class="note" style="margin-top:0">Батареї немає — живлення від мережі.</p>') +
    `<p class="note" style="margin-top:16px">кришка закрита — <span style="color:var(--fg)">не засинає</span></p>
    <div class="acts"><button class="btn" data-power="reboot">Перезавантажити</button><button class="btn danger" data-power="poweroff">Вимкнути</button></div>`;

  app.innerHTML = `<div class="wrap wide">
    <div class="cols">${win('система', sys, {n: '¹', id: 'sys'})}${win('диски', dsk, {n: '²', c: 'yel', id: 'disks', cls: 'w2'})}</div>
    <div class="cols">${win('служби', svc, {n: '³', c: 'red', id: 'svc'})}${win('мережа', net, {n: '⁴', c: 'vio', id: 'net'})}${win('живлення', pwr, {n: '⁵', c: 'yel', id: 'pwr'})}</div>
    <div class="cols">${win('журнал', '<p class="note" style="margin:0"><span class="spin"></span></p>', {n: '⁶', c: 'dim', id: 'log', cls: 'w9'})}<div id="updBox" style="flex:1 1 340px;min-width:0">${updBox()}</div></div>
  </div>`;

  $$('[data-svc]').forEach(x => x.onclick = () => service(x, x.dataset.svc, 'restart'));
  $$('[data-op]').forEach(x => x.onclick = () => service(x, x.dataset.name, x.dataset.op));
  $$('[data-power]').forEach(x => x.onclick = async () => {
    const off = x.dataset.power === 'poweroff';
    if (!confirm(off ? 'Вимкнути сервер? Увімкнути знову можна лише кнопкою на ноутбуці.' : 'Перезавантажити сервер? Він повернеться за хвилину-дві.')) return;
    const r = await api('/api/power', {op: x.dataset.power});
    toast(r.ok ? (off ? 'Вимикаю…' : 'Перезавантажую…') : r.error);
  });
  $('#findDisks').onclick = () => openFromPanel(2);
  if ($('#tsOn')) $('#tsOn').onclick = () => openFromPanel(4);
  $('#wifiBtn').onclick = () => wifiPage();
  $('#speed').onclick = speedTest;
  if (SPEED) $('#speedRes').innerHTML = SPEED;
  netInfo();
  bindLimit();
  bindUpd();
  live();
  journal();
  if (!UPD) checkUpdates();
  panelTimer = setTimeout(() => { if (STATE.setup && !document.hidden && !typing()) panel(); else panelTimer = setTimeout(panel, 30000); }, 30000);
}

async function service(btn, name, op) {
  btn.disabled = true;
  const r = await api('/api/service', {name, op});
  toast(r.ok ? ({restart: 'Перезапущено', stop: 'Зупинено', start: 'Запущено'})[op] + ': ' + name : r.error);
  panel();
}

// ───────────────────────── мережа ─────────────────────────
const KIND = {cable: 'кабель', wifi: 'wi-fi', phone: 'телефон', tailscale: 'tailscale'};
const mbit = v => v >= 1000 ? (v / 1000).toString().replace('.', ',') + ' Гбіт/с' : v + ' Мбіт/с';
const sigPct = dbm => Math.max(0, Math.min(100, 2 * (dbm + 100)));
let SPEED = '';

async function netInfo() {
  const r = await api('/api/net');
  if (!$('#ifaces')) return;
  const w = r.wifi || {};
  const rows = (r.ifaces || []).filter(i => i.kind !== 'tailscale').map(i => {
    const bits = [esc(i.name), ...(i.ips || []).map(esc)];
    if (i.kind === 'wifi' && w.ssid) bits.splice(1, 0, `«${esc(w.ssid)}» ${sigPct(w.signal)}%`);
    if (i.speed) bits.push(mbit(i.speed));
    if (i.usb) bits.push(i.usb >= 5000 ? 'USB 3' : i.usb >= 480 ? 'USB 2.0' : 'USB 1.1');
    const warn = i.speed && i.speed <= 10 ? 'Лінк лише 10 Мбіт/с — заміни кабель або спробуй інший порт роутера/доку.'
      : i.usb && i.usb < 480 ? 'Пристрій працює як USB 1.1 (12 Мбіт/с) — переткни в інший порт або заміни кабель.' : '';
    return `<div class="row"><div class="l"><b><span class="okdot ${i.up ? '' : 'off'}"></span>${KIND[i.kind]}</b><small>${bits.join(' · ')}</small>` +
      (warn ? `<small style="display:block;color:var(--yel)">${warn}</small>` : '') + `</div><div class="r">` +
      (i.name === r.route ? '<span class="tag ok">інтернет</span>' : i.up ? '' : '<span class="tag">вимкнено</span>') + '</div></div>';
  }).join('');
  $('#ifaces').innerHTML = rows || '<p class="note" style="margin:0">Мережевих адаптерів не знайдено.</p>';
}

async function speedTest() {
  const b = $('#speed');
  b.disabled = true; b.innerHTML = '<span class="spin"></span> Міряю ~15 с…';
  const r = await api('/api/speedtest', {});
  SPEED = r.ok
    ? `↓ <b style="color:var(--fg)">${String(r.mbit).replace('.', ',')} Мбіт/с</b> · затримка ${r.ms} мс · через ${esc(r.dev || '?')}` +
      (r.mbit < 20 ? '<br><span style="color:var(--yel)">Повільно. Глянь, яке підключення позначене «інтернет», і його швидкість лінку вище.</span>' : '')
    : `<span style="color:var(--red)">${esc(r.error)}</span>`;
  if ($('#speedRes')) $('#speedRes').innerHTML = SPEED;
  if ($('#speed')) { $('#speed').disabled = false; $('#speed').textContent = 'Перевірити швидкість'; }
}

// Сторінка Wi-Fi: поточне підключення, мережі поруч, пароль.
const WF = {nets: null, sel: null, status: null, err: ''};
async function wifiPage(rescan = true) {
  stopPanel(); fromPanel = true; wizTop();
  if (rescan) { WF.nets = null; WF.err = ''; }
  render();
  if (!WF.status || rescan) WF.status = await api('/api/wifi', {op: 'status'});
  render();
  if (rescan && WF.status.iface) {
    const r = await api('/api/wifi', {op: 'scan'});
    WF.nets = r.networks || [];
    if (r.ok === false) WF.err = r.error;
    render();
  }
  function render() {
    const st = WF.status;
    const cur = !st ? '<p class="note" style="margin:0"><span class="spin"></span></p>'
      : !st.iface ? '<p class="note" style="margin:0">Wi-Fi адаптера не знайдено.</p>'
      : st.ssid ? `<div class="row"><div class="l"><b><span class="okdot"></span>${esc(st.ssid)}</b><small>${esc(st.iface)} · сигнал ${sigPct(st.signal)}%</small></div>` +
          `<div class="r">${segs(sigPct(st.signal), 5, 'mono').replace('class="segs mono', 'style="width:60px;flex:none" class="segs mono')}${st.saved ? '<button class="btn ghost" id="wfForget">Забути</button>' : ''}</div></div>`
      : `<p class="note" style="margin:0">Не підключено${st.saved ? ` — збережена мережа «${esc(st.saved)}» не ловиться` : ''}.</p>` +
          (st.saved ? '<div class="acts"><button class="btn ghost" id="wfForget">Забути</button></div>' : '');
    const list = WF.nets === null ? '<p class="note" style="margin:0"><span class="spin"></span> Шукаю мережі…</p>'
      : !WF.nets.length ? `<p class="note" style="margin:0">${esc(WF.err || 'Мереж не знайдено.')}</p>`
      : WF.nets.map((n, k) => `<div class="row"><div class="l"><b>${esc(n.ssid)}</b><small>${esc(n.band)} · ${sigPct(n.signal)}% · ${n.secure ? 'з паролем' : 'відкрита'}</small></div>` +
          `<div class="r">${segs(sigPct(n.signal), 5, 'mono').replace('class="segs mono', 'style="width:60px;flex:none" class="segs mono')}<button class="btn" data-pick="${k}">${st && st.ssid === n.ssid ? 'Підключено' : 'Обрати'}</button></div></div>` +
          (WF.sel === k ? `<form class="row" id="wfForm" style="flex-wrap:wrap">${n.secure ? `<label class="field"><span aria-hidden="true">❯</span><input id="wfPw" type="password" autocomplete="off" placeholder="пароль від «${esc(n.ssid)}»" aria-label="Пароль Wi-Fi" autofocus></label>` : '<span class="note" style="margin:0;flex:1">Відкрита мережа, без пароля.</span>'}` +
            `<button class="btn primary" id="wfGo">Підключити</button></form>` : '')).join('');
    app.innerHTML = `<div class="wrap">${prompt('~/net', 'hata wifi')}<h1 class="title">Wi-Fi</h1>
      <p class="lead">Обери мережу й введи пароль. Якщо підключений і кабель, інтернет іде кабелем — Wi-Fi лишається запасним.</p>
      ${win('підключення', cur, {c: 'vio'})}${win('мережі поруч', list + `<div class="err" id="wfErr" role="alert">${esc(WF.formErr || '')}</div>`, {c: 'yel'})}
      <div class="acts"><button class="btn ghost" id="wfScan">Оновити список</button><span class="sp"></span><button class="btn primary" id="next">До панелі</button></div></div>`;
    $('#next').onclick = () => { fromPanel = false; panel(); };
    $('#wfScan').onclick = () => wifiPage(true);
    $$('[data-pick]').forEach(b => b.onclick = () => { WF.sel = +b.dataset.pick; WF.formErr = ''; render(); if ($('#wfPw')) $('#wfPw').focus(); });
    if ($('#wfForget')) $('#wfForget').onclick = async () => {
      if (!confirm('Забути цю мережу? Хата перестане до неї підключатися.')) return;
      WF.status = await api('/api/wifi', {op: 'forget'}); toast('Мережу забуто'); render();
    };
    if ($('#wfForm')) $('#wfForm').onsubmit = async e => {
      e.preventDefault();
      const n = WF.nets[WF.sel], b = $('#wfGo');
      b.disabled = true; b.innerHTML = '<span class="spin"></span> Підключаю (до 30 с)…';
      const r = await api('/api/wifi', {op: 'connect', ssid: n.ssid, password: $('#wfPw') ? $('#wfPw').value : ''});
      if (r.ok === false) { WF.formErr = r.error; render(); return; }
      WF.status = r; WF.sel = null; WF.formErr = ''; toast(`Підключено до «${n.ssid}»`); render();
    };
  }
}

// Живі цифри: процесор, пам'ять, температура, трафік — раз на 2 секунди, поки сторінку видно.
async function live() {
  clearTimeout(liveTimer);
  if (!document.hidden && $('#cpuG')) {
    const l = await api('/api/live');
    if (l.cpu != null) { HIST.cpu.push(l.cpu); HIST.cpu = HIST.cpu.slice(-48); }
    if (l.net && HIST.lastNet) {
      const dt = Math.max(1, l.time - HIST.lastNet.time) || 2;
      HIST.net.push(Math.max(0, (l.net.rx - HIST.lastNet.rx) / dt)); HIST.net = HIST.net.slice(-40);
    }
    if (l.net) HIST.lastNet = {...l.net, time: l.time};
    drawLive(l);
  }
  liveTimer = setTimeout(live, 2000);
}

function drawLive(l) {
  if (!$('#cpuG')) return;
  const pad = (a, n) => Array(Math.max(0, n - a.length)).fill(0).concat(a);
  $('#cpuG').innerHTML = pad(HIST.cpu, 48).map(v => `<i style="height:${v}%;--c:var(--${heat(v)})"></i>`).join('');
  const nmax = Math.max(64 * 1024, ...HIST.net);
  $('#netG').innerHTML = pad(HIST.net, 40).map(v => `<i style="height:${Math.round(v / nmax * 100)}%"></i>`).join('');
  const cur = HIST.net[HIST.net.length - 1] || 0;
  $('#netNow').textContent = `↓ ${short(cur)}/с`;
  if (l.cpu != null) { $('#cpuNow').textContent = l.cpu + '%'; $('#tCpu').textContent = l.cpu + '%'; }
  const m = l.mem || {}, used = (m.total || 0) - (m.avail || 0);
  const sw = l.swap || {}, swUsed = (sw.total || 0) - (sw.free || 0);
  $('#tRam').textContent = `${short(used)}/${short(m.total)}`;
  $('#tTemp').textContent = l.temp != null ? Math.round(l.temp) + '°C' : '—';
  $('#mem').innerHTML = `<span>ram</span>${segs(m.total ? used / m.total * 100 : 0)}<span class="v">${size(used)} / ${size(m.total)}</span>` +
    (sw.total ? `<span>swap</span>${segs(swUsed / sw.total * 100)}<span class="v">${size(swUsed)} / ${size(sw.total)}</span>` : '') +
    (l.temp != null ? `<span>t°</span>${segs(Math.min(100, l.temp))}<span class="v">${Math.round(l.temp)} °C</span>` : '');
}

async function journal() {
  const r = await api('/api/journal');
  if (!$('#log')) return;
  const lines = (r.lines || []).slice().reverse();
  const col = u => u === 'gazda' ? 'yel' : u === 'hata' ? 'vio' : u === 'vidbox' ? 'acc' : 'dim';
  $('#log .wbody').innerHTML = lines.length ? `<ol class="log">${lines.map(l => `<li><span class="t">${new Date(l.t * 1000).toLocaleTimeString('uk-UA')}</span>` +
    `<span class="u" style="color:var(--${col(l.unit)})">${esc(l.unit)}</span><span>${esc(l.msg)}</span></li>`).join('')}</ol>`
    : `<p class="note" style="margin:0">${esc(r.error || 'Журнал порожній.')}</p>`;
}

// Оновлення: що нового на GitHub, і кнопка, яка оновлює з відкатом.
function updBox() {
  const u = UPD;
  if (!u) return win('оновлення', `<p class="note" style="margin:0"><span class="spin"></span> Дивлюсь, що нового на GitHub…</p><div class="acts"><button class="btn" id="upd" disabled>Оновити</button></div>`, {n: '⁷'});
  if (u.ok === false) return win('оновлення', `<p class="note" style="margin:0">${esc(u.error)}</p><div class="acts"><button class="btn" id="upd" data-check>Перевірити ще раз</button></div>`, {n: '⁷'});
  const ver = (u.version || '').split(' ')[0];
  const c = u.commits || [];
  if (!c.length) return win('оновлення', `<dl class="kv"><dt>хата</dt><dd>${esc(ver)} · остання версія</dd></dl><div class="acts"><button class="btn" id="upd" data-check>Перевірити</button></div>`, {n: '⁷'});
  return win('оновлення', `<dl class="kv"><dt>зараз</dt><dd>${esc(ver)}</dd><dt>нових змін</dt><dd>${c.length}</dd></dl>
    <ul class="commits">${c.slice(0, 6).map(x => `<li><b>${esc(x.hash)}</b><span>${esc(x.msg)}</span></li>`).join('')}${c.length > 6 ? `<li><span style="color:var(--dim)">і ще ${c.length - 6}</span></li>` : ''}</ul>
    <p class="note">Якщо після оновлення щось не запуститься, Хата сама повернеться до ${esc(ver)}.</p>
    <div class="acts"><button class="btn primary" id="upd">Оновити</button></div>`, {n: '⁷', cls: 'hot', badge: String(c.length)});
}
function bindUpd() {
  const b = $('#upd'); if (!b) return;
  b.onclick = async () => {
    if (b.dataset.check !== undefined) { b.disabled = true; b.innerHTML = '<span class="spin"></span> Перевіряю…'; return checkUpdates(true); }
    b.disabled = true; b.innerHTML = '<span class="spin"></span> Оновлюю…';
    const r = await api('/api/update', {});
    toast(!r.ok ? r.error : r.changed ? `Оновлено до ${r.version.split(' ')[0]}` : 'Уже встановлено останню версію');
    UPD = null;
    setTimeout(panel, r.changed ? 4000 : 0);
  };
}
async function checkUpdates(force) {
  UPD = await api('/api/updates' + (force ? '?force' : ''));
  if ($('#updBox')) { $('#updBox').innerHTML = updBox(); bindUpd(); }
}

// Клавіші 1–6 — до розділу панелі, як у btop.
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey || typing() || !$('#sys')) return;
  const s = SECTIONS.find(x => x[0] === e.key);
  if (!s) return;
  $('#' + s[2]).scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
  $$('.top nav a').forEach(a => a.classList.toggle('on', a.dataset.k === s[0]));
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && $('#cpuG')) live(); });

start();
