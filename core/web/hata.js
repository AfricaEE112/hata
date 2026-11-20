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

async function api(url, body, ms = 120000) {
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), ms);   // не крутимо спінер вічно
  const opt = body === undefined ? {signal: ctl.signal} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal: ctl.signal};
  try {
    const r = await fetch(url, opt);
    const j = await r.json().catch(() => ({}));
    if (r.status === 401 && j.error === 'auth') { start(); return {ok: false, error: 'Потрібно увійти'}; }
    return j;
  } catch (e) {
    return {ok: false, error: e.name === 'AbortError' ? 'Сервер довго не відповідає — схоже, повільний інтернет. Спробуй ще раз пізніше.'
      : `Немає зв’язку з сервером. Якщо Хата перезавантажилась, її адреса могла змінитись — глянь на екран ноутбука або відкрий http://${HOST}.local`};
  } finally { clearTimeout(t); }
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
  '9': '01110100011000101111000010001001100', ':': '0010100', ' ': '0000000',
  '.': '0000001', '-': '000000000111000000000'};
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
  // Назва для нового диска: з мітки латиницею, інакше з виробника (wdc, toshiba…); без повторів.
  const taken = new Set(list.map(d => d.name).filter(Boolean));
  const slug = t => (t || '').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24);
  const suggest = d => {
    let base = slug(d.label) || slug((d.model || '').split(/\s+/)[0]) || 'disk', n = base, k = 2;
    while (taken.has(n)) n = base + k++;
    taken.add(n); return n;
  };
  const body = list.length ? list.map(d => {
    const name = d.name || (d.system ? '' : suggest(d));
    const meta = [size(d.size), d.fs, d.model, d.usb ? 'USB' : ''].filter(Boolean).join(' · ');
    return `<div class="row"><div class="l"><b>${esc(d.label || d.dev)}</b><small>${esc(meta)}</small></div><div class="r">` +
      (d.system ? '<span class="tag">системний</span>' :
       d.name ? `<span class="tag ok">/srv/disks/${esc(d.name)}</span><button class="btn ghost" data-unmount="${esc(d.name)}" aria-label="Відключити ${esc(d.name)}">Відключити</button>` :
       `<input type="text" value="${esc(name)}" aria-label="Назва диска" data-name="${esc(d.uuid)}"><button class="btn" data-mount="${esc(d.uuid)}">Підключити</button>`) +
      '</div></div>';
  }).join('') : '<p class="note">Дисків з даними не знайдено. Підключи диск і натисни «Оновити список».</p>';
  $('.win .wbody').innerHTML = body + `<div class="err" id="de" role="alert"></div><div class="acts"><button class="btn ghost" id="rescan">Оновити список</button></div>`;
  $('#rescan').onclick = stepDisks;
  $$('[data-unmount]').forEach(b => b.onclick = async () => {
    if (!confirm(`Відключити диск «${b.dataset.unmount}» від Хати? Файли на ньому лишаться, просто VidBox перестане його бачити, поки не підключиш знову.`)) return;
    b.disabled = true;
    const res = await api('/api/unmount', {name: b.dataset.unmount});
    if (!res.ok) { $('#de').textContent = res.error; b.disabled = false; return; }
    toast(`Відключено: ${b.dataset.unmount}`);
    stepDisks();
  });
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
    ? `<p><span class="okdot"></span>Підключено як <b class="link">${esc(st.name)}</b></p>
       <dl class="kv" style="margin-top:12px"><dt>панель</dt><dd class="link">http://${esc(st.name)}/</dd><dt>vidbox</dt><dd class="link">http://${esc(st.name)}:8800/</dd></dl>
       <p class="note">Працює звідусіль, де на телефоні чи ноутбуці ввімкнено Tailscale з тим самим акаунтом. В Android-апці VidBox введи адресу <b>${esc(st.name)}</b> у «Адреса ПК» — вона працює і вдома, і поза домом.</p>`
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

function stopPanel() { clearTimeout(panelTimer); clearTimeout(liveTimer); clearTimeout(houseTimer); clearTimeout(disksTimer); }

function panelTop(s) {
  bar.hidden = false;
  const b = s.battery;
  bar.innerHTML = `${who()}<nav aria-label="Розділи">${SECTIONS.map(([k, l, id]) => `<a href="#${id}" data-k="${k}"><span>${k}</span>${l}</a>`).join('')}` +
    `<a href="#files" data-k="7" data-files><span>7</span>файли</a><a href="#house" data-k="8" data-house><span>8</span>будинок</a>` +
    `<a class="ext" href="${esc(vidboxUrl(s))}">VidBox ↗</a></nav><span class="sp"></span>
    <dl class="stats"><div><dt>cpu</dt><dd id="tCpu">—</dd></div><div><dt>ram</dt><dd id="tRam">—</dd></div><div><dt>t°</dt><dd id="tTemp">—</dd></div>` +
    (b ? `<div><dt>бат</dt><dd style="display:flex;gap:6px;align-items:center">${segs(b.pct, 10).replace('class="segs ', 'style="width:52px;flex:none" class="segs ')}${b.pct}%</dd></div>` : '') +
    `<div><dt class="sr">час</dt><dd class="clock">${hhmm()}</dd></div></dl>${schemePicker()}`;
  bindSchemes(true);
  $$('.top nav a[data-k]').forEach(a => a.onclick = e => { e.preventDefault(); goSection(a.dataset.k); });
}

// Перехід до розділу: 1–6 — блоки панелі (якщо ми на іншій сторінці — спершу назад на панель), 7 — файли.
async function goSection(k) {
  $$('.top nav a').forEach(x => x.classList.toggle('on', x.dataset.k === k));
  if (k === '2') return disksPage();
  if (k === '7') return filesPage();
  if (k === '8') return housePage();
  const s = SECTIONS.find(x => x[0] === k);
  if (!s) return;
  if (!$('#sys')) await panel();
  $$('.top nav a').forEach(x => x.classList.toggle('on', x.dataset.k === k));
  $('#' + s[2]).scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
}
const vidboxUrl = s => location.protocol === 'https:' ? `https://${location.hostname}:8443` : `http://${location.hostname}:${s.vidbox.port}`;

// Панель. soft = тихе оновлення раз на 30 с: міняємо лише блоки, де щось змінилось, без перемальовування сторінки.
async function panel(soft) {
  stopPanel();
  fromPanel = false;
  const s = await api('/api/status');
  if (soft && !$('#sys')) return;                    // поки чекали, користувач пішов на іншу сторінку
  if (s.ok === false) {
    if (soft) { panelTimer = setTimeout(() => panel(true), 30000); return; }   // сервер на мить зайнятий — не лякаємо
    app.innerHTML = `<div class="wrap">${prompt('~', 'gazda status')}${win('помилка', `<p class="err">${esc(s.error)}</p>`, {c: 'red'})}</div>`; return;
  }
  LAST = s;
  if (!soft) panelTop(s);
  // Сервер ще в UTC (так ставить Ubuntu) — беремо часовий пояс з браузера, щоб годинник на ноутбуці й журнал були місцеві.
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (tz && ['UTC', 'Etc/UTC', 'Universal', ''].includes(s.tz || '') && tz !== s.tz)
    api('/api/timezone', {tz}).then(r => { if (r.ok) toast(`Часовий пояс сервера: ${r.tz}`); });
  const ts = s.tailscale || {};
  const ver = (s.version || '').split(' ')[0] || '—';

  const sys = `<div class="when"><div data-clock="small">${dots(hhmm())}</div><p><span class="wd">${weekday()}</span><span class="dt">${today()}</span></p></div>
    <dl class="kv"><dt>хост</dt><dd>${esc(s.host)}${(s.ips || []).length ? ' · ' + s.ips.map(esc).join(', ') : ''}</dd>
      <dt>працює</dt><dd>${uptime(s.uptime)}</dd><dt>система</dt><dd>${esc(s.os)} · Хата ${esc(ver)}</dd></dl>
    <div class="gh"><span>${esc(((s.cpu_model || '').match(/i[3579]-\w+|Ryzen \d+ \w+|Celeron \w+|Pentium \w+|N\d{3,4}/) || ['cpu'])[0])} · ${s.cpus} потоків</span><b id="cpuNow">—</b></div><div class="graph" id="cpuG" aria-hidden="true"></div>
    <div class="meters" style="margin-top:14px" id="mem"></div>`;

  const disks = [{name: 'система', path: '/', mounted: true, ...(s.root || {})}].concat(s.disks || []);
  const dsk = `<div class="disks"><div class="drow h"><span>диск</span><span>заповнено</span><span style="text-align:right">зайнято</span></div>` +
    disks.map(d => {
      const used = (d.total || 0) - (d.free || 0), p = d.total ? used / d.total * 100 : 0;
      return `<div class="drow"><span class="n"><b>${esc(d.name)}</b><small>${esc(d.path || '')}</small></span>` +
        (d.mounted ? `${segs(p, 30)}<span class="v">${size(used)} <span>/ ${size(d.total)}</span></span>`
                   : `<span class="note" style="margin:0">диск не знайдено — він вимкнений або від'єднаний</span><span class="v"><span class="tag bad">відключено</span></span>`) + '</div>';
    }).join('') + `</div><div class="dock"><span>Новий диск у доці чи USB? Його можна підключити тут.</span><span style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="openDisks">Здоров’я й копії</button><button class="btn" id="openFiles">Файли</button><button class="btn" id="findDisks">Знайти диски</button></span></div>`;

  const svcRow = (name, desc, state, btns) => `<div class="row svc ${state === 'active' ? '' : 'off'}"><div class="l"><b><span class="okdot ${state === 'active' ? '' : 'off'}"></span>${esc(name)}</b><small>${esc(desc)}</small></div>` +
    `<div class="r"><span class="st">${state === 'active' ? 'працює' : esc(state || 'зупинена')}</span>${btns}</div></div>`;
  const svc = Object.entries(s.services || {}).map(([n, st]) => svcRow(n, SVC[n] || '', st, n === 'hata' ? '' :
      `<button class="btn" data-op="${st === 'active' ? 'stop' : 'start'}" data-name="${n}" aria-label="${st === 'active' ? 'Зупинити' : 'Запустити'} ${n}">${st === 'active' ? '■' : '▶'}</button>` +
      `<button class="btn" data-svc="${n}" aria-label="Перезапустити ${n}">↻</button>`)).join('') +
    svcRow('tailscale', ts.state === 'Running' ? 'доступ звідусіль' : ts.installed ? 'не підключено' : 'не встановлено', ts.state === 'Running' ? 'active' : 'вимкнено', '') +
    `<div class="row svc"><div class="l"><b><span class="okdot always"></span>gazda</b><small>керує системою, не зупиняється</small></div><div class="r"><span class="st" style="color:var(--yel)">завжди</span></div></div>`;

  const net = `<div id="ifaces"><p class="note" style="margin:0"><span class="spin"></span></p></div><div id="pinBox"></div>
    <dl class="kv" style="margin-top:12px"><dt>ім'я</dt><dd>${esc(s.host)}.local</dd>
      <dt>tailscale</dt><dd>${ts.state === 'Running' ? `<span class="okdot"></span>${esc(ts.name)}` : ts.installed ? 'не підключено' : 'не встановлено'}</dd>
      ${ts.state === 'Running' ? `<dt>ззовні</dt><dd class="link">${ts.https ? `<a href="https://${esc(ts.name)}:8443/">vidbox</a> · <a href="https://${esc(ts.name)}/">панель</a>`
        : `<a href="http://${esc(ts.name)}:8800/">vidbox</a> · <a href="http://${esc(ts.name)}/">панель</a>`}</dd>` : ''}</dl>
      ${ts.state === 'Running' && !ts.https ? `<p class="note" id="tsHttpsNote">Щоб поставити Хату й VidBox на головний екран як апки (телефон, Mac, Windows), потрібні HTTPS-адреси.</p>` : ''}
      ${ts.https ? `<p class="note">Апка: відкрий https-адресу → «Поділитися → На початковий екран» (iPhone), «Встановити» в меню (Android, Chrome, Edge) або «Файл → Додати в Dock» (Safari на Mac).</p>` : ''}
    <div class="gh"><span>трафік</span><b id="netNow">—</b></div><div class="graph net" id="netG" aria-hidden="true"></div>
    <p class="note" id="speedRes" aria-live="polite"></p>
    <div class="acts"><button class="btn" id="speed">Перевірити швидкість</button><button class="btn" id="wifiBtn">Wi-Fi</button>${ts.state === 'Running' ? (ts.https ? '' : '<button class="btn" id="tsHttps">Увімкнути HTTPS</button>') : '<button class="btn" id="tsOn">Tailscale</button>'}</div>`;

  const b = s.battery;
  const pwr = (b ? `<div class="gh" style="margin-top:0"><span>батарея · ${b.ac ? 'від мережі' : 'від батареї'}</span><b>${b.pct}%</b></div>${segs(b.pct, 20, 'tall')}` +
      (b.limitSupported ? `<p class="note" style="margin-top:16px">заряджати до</p><div class="seg" id="lim" role="group" aria-label="Межа заряду" style="margin-top:6px">${[60, 80, 100].map(v => `<button data-v="${v}" class="${(b.limit || 100) === v ? 'on' : ''}">${v}%</button>`).join('')}</div>` : '')
      : '<p class="note" style="margin-top:0">Батареї немає — живлення від мережі.</p>') +
    `<p class="note" style="margin-top:16px">кришка закрита — <span style="color:var(--fg)">не засинає</span></p>
    <div class="acts"><button class="btn" data-power="reboot">Перезавантажити</button><button class="btn danger" data-power="poweroff">Вимкнути</button></div>`;

  if (soft) {
    const swap = (id, html) => { const b = $(`#${id} .wbody`); if (b && b.dataset.html !== html) { b.innerHTML = html; b.dataset.html = html; } };
    swap('disks', dsk); swap('svc', svc); swap('pwr', pwr);
    bindPanel(); netInfo(); journal(); live();
    panelTimer = setTimeout(nextPanel, 30000);
    return;
  }
  app.innerHTML = `<div class="wrap wide">
    <div class="cols">${win('система', sys, {n: '¹', id: 'sys'})}${win('диски', dsk, {n: '²', c: 'yel', id: 'disks', cls: 'w2'})}</div>
    <div class="cols">${win('служби', svc, {n: '³', c: 'red', id: 'svc'})}${win('мережа', net, {n: '⁴', c: 'vio', id: 'net'})}${win('живлення', pwr, {n: '⁵', c: 'yel', id: 'pwr'})}</div>
    <div class="cols">${win('журнал', '<p class="note" style="margin:0"><span class="spin"></span></p>', {n: '⁶', c: 'dim', id: 'log', cls: 'w9'})}<div id="updBox" style="flex:1 1 340px;min-width:0">${updBox()}</div></div>
  </div>`;

  for (const [id, html] of [['disks', dsk], ['svc', svc], ['pwr', pwr]]) $(`#${id} .wbody`).dataset.html = html;
  bindPanel();
  $('#wifiBtn').onclick = () => wifiPage();
  $('#ifaces').onclick = e => {           // рядки мережі перемальовуються — тож слухаємо на контейнері
    const b = e.target.closest('[data-pin],[data-unpin]');
    if (b) b.dataset.pin !== undefined ? pinForm(b.dataset.pin, b.dataset.ip) : unpin();
  };
  $('#speed').onclick = speedTest;
  if ($('#tsOn')) $('#tsOn').onclick = () => openFromPanel(4);
  if ($('#tsHttps')) $('#tsHttps').onclick = async e => {
    const b = e.currentTarget; b.disabled = true; b.textContent = 'Вмикаю…';
    const r = await api('/api/tailscale', {op: 'https'});
    if (r.https) { toast('Готово: адреси тепер https://'); return setTimeout(() => location.reload(), 800); }
    b.disabled = false; b.textContent = 'Увімкнути HTTPS';
    const n = $('#tsHttpsNote'), m = (r.error || '').match(/https:\/\/\S+/);
    if (n) n.innerHTML = m ? `${esc(r.error.split(m[0])[0])}<a href="${esc(m[0])}" target="_blank" rel="noopener">${esc(m[0])}</a>${esc(r.error.split(m[0])[1] || '')}` : esc(r.error || 'Не вдалося');
  };
  if (SPEED) $('#speedRes').innerHTML = SPEED;
  netInfo();
  bindUpd();
  live();
  journal();
  diskWarn();
  if (!UPD) checkUpdates();
  panelTimer = setTimeout(nextPanel, 30000);
}
const nextPanel = () => { if (STATE.setup && !document.hidden && !typing() && !$('details.schemes[open]')) panel(true); else panelTimer = setTimeout(nextPanel, 30000); };

// На огляді: якщо з якимось диском біда — рядок-попередження над списком дисків.
async function diskWarn() {
  const h = await api('/api/disks/health');
  const box = $('#disks .wbody');
  if (!box || !h.disks) return;
  const bad = h.disks.map(d => [d, diskVerdict(d)]).filter(([, v]) => v[0] === 'red' || v[0] === 'yel');
  $('#dkWarn')?.remove();
  if (bad.length) box.insertAdjacentHTML('afterbegin', `<p class="dk-warn" id="dkWarn">${bad.map(([d, v]) => `<span style="color:var(--${v[0]})">▲ ${esc(d.names.join(' · '))}: ${esc(v[1])}</span>`).join('<br>')} <button class="linkbtn" data-dk>детальніше</button></p>`);
  $('#dkWarn [data-dk]')?.addEventListener('click', disksPage);
}

function bindPanel() {
  $$('[data-svc]').forEach(x => x.onclick = () => service(x, x.dataset.svc, 'restart'));
  $$('[data-op]').forEach(x => x.onclick = () => service(x, x.dataset.name, x.dataset.op));
  $$('[data-power]').forEach(x => x.onclick = async () => {
    const off = x.dataset.power === 'poweroff';
    if (!confirm(off ? 'Вимкнути сервер? Увімкнути знову можна лише кнопкою на ноутбуці.' : 'Перезавантажити сервер? Він повернеться за хвилину-дві.')) return;
    const r = await api('/api/power', {op: x.dataset.power});
    toast(r.ok ? (off ? 'Вимикаю…' : 'Перезавантажую…') : r.error);
  });
  $('#findDisks').onclick = () => openFromPanel(2);
  $('#openFiles').onclick = () => filesPage();
  $('#openDisks').onclick = () => disksPage();
  bindLimit();
}

async function service(btn, name, op) {
  btn.disabled = true;
  const r = await api('/api/service', {name, op});
  toast(r.ok ? ({restart: 'Перезапущено', stop: 'Зупинено', start: 'Запущено'})[op] + ': ' + name : r.error);
  panel(true);
}

// ───────────────────────── мережа ─────────────────────────
const KIND = {cable: 'кабель', wifi: 'wi-fi', phone: 'телефон', tailscale: 'tailscale'};
const mbit = v => v >= 1000 ? (v / 1000).toString().replace('.', ',') + ' Гбіт/с' : v + ' Мбіт/с';
const sigPct = dbm => Math.max(0, Math.min(100, 2 * (dbm + 100)));
let SPEED = '';

async function netInfo() {
  const r = await api('/api/net');
  if (!$('#ifaces') || (r.ok === false && $('#ifaces').dataset.html)) return;
  const w = r.wifi || {};
  const rows = (r.ifaces || []).filter(i => i.kind !== 'tailscale').map(i => {
    const bits = [esc(i.name), ...(i.ips || []).map(esc)];
    if (i.kind === 'wifi' && w.ssid) bits.splice(1, 0, `«${esc(w.ssid)}» ${sigPct(w.signal)}%`);
    if (i.speed) bits.push(mbit(i.speed));
    if (i.usb) bits.push(i.usb >= 5000 ? 'USB 3' : i.usb >= 480 ? 'USB 2.0' : 'USB 1.1');
    const warn = i.kind === 'wifi' && w.ssid && w.signal <= -72 ? `Слабкий сигнал (${w.signal} дБм) — Wi-Fi буде повільним. Постав ноутбук ближче до роутера або спробуй мережу 2,4 ГГц: вона пробиває стіни краще.`
      : i.speed && i.speed <= 10 ? 'Лінк лише 10 Мбіт/с — заміни кабель або спробуй інший порт роутера/доку.'
      : i.usb && i.usb < 480 ? 'Пристрій працює як USB 1.1 (12 Мбіт/с) — переткни в інший порт або заміни кабель.' : '';
    const pinned = (r.static || {}).iface === i.name;
    const pin = i.kind === 'cable' && i.up ? (pinned ? `<button class="btn ghost" data-unpin aria-label="Прибрати постійну адресу">Скасувати</button>`
      : `<button class="btn ghost" data-pin="${esc(i.name)}" data-ip="${esc((i.ips || [])[0] || '')}">Закріпити адресу</button>`) : '';
    return `<div class="row"><div class="l"><b><span class="okdot ${i.up ? '' : 'off'}"></span>${KIND[i.kind]}</b><small>${bits.join(' · ')}</small>` +
      (pinned ? `<small style="display:block;color:var(--acc)">постійна адреса — не зміниться після перезавантаження</small>` : '') +
      (warn ? `<small style="display:block;color:var(--yel)">${warn}</small>` : '') + `</div><div class="r">` +
      (i.name === r.route ? '<span class="tag ok">інтернет</span>' : i.up ? '' : '<span class="tag">вимкнено</span>') + pin + '</div></div>';
  }).join('');
  const html = rows || '<p class="note" style="margin:0">Мережевих адаптерів не знайдено.</p>';
  if ($('#ifaces').dataset.html !== html) { $('#ifaces').innerHTML = html; $('#ifaces').dataset.html = html; }
}

// Постійна адреса вдома: кабель отримує фіксовану IP замість щоразу нової від роутера.
let iface_ip = () => '';
function pinForm(iface, ip) {
  iface_ip = () => ip;
  const base = ip.split('.').slice(0, 3).join('.');
  $('#pinBox').innerHTML = `<form class="row" id="pinF" style="flex-wrap:wrap;border-bottom:0">
    <div class="l" style="flex-basis:100%"><b>Постійна адреса для кабелю</b>
      <small>Візьми адресу, яку роутер сам нікому не роздає (часто це .200–.250), або закріпи її ще й у роутері — тоді конфліктів точно не буде.</small></div>
    <label class="field" style="flex:1 1 200px"><span aria-hidden="true">❯</span><input id="pinIp" value="${esc(base)}.200" aria-label="Постійна адреса" inputmode="decimal"></label>
    <button class="btn primary" id="pinGo">Закріпити</button><button class="btn ghost" type="button" id="pinX">Скасувати</button>
    <div class="err" id="pinErr" role="alert" style="flex-basis:100%"></div></form>`;
  $('#pinX').onclick = () => $('#pinBox').innerHTML = '';
  $('#pinF').onsubmit = async e => {
    e.preventDefault();
    const want = $('#pinIp').value.trim(), b = $('#pinGo');
    b.disabled = true; b.innerHTML = '<span class="spin"></span> Перевіряю й застосовую…';
    const r = await api('/api/static', {op: 'set', iface, ip: want}, 60000);
    if (r.ok === false) {
      // зайшли через стару IP: вона зникла разом з відповіддю — переходимо на нову
      if (/Немає зв’язку|довго не відповідає/.test(r.error) && location.hostname === iface_ip()) { location.href = `http://${want}/`; return; }
      $('#pinErr').textContent = r.error; b.disabled = false; b.textContent = 'Закріпити'; return;
    }
    $('#pinBox').innerHTML = '';
    toast(`Тепер Хата завжди за адресою ${want}`);
    if (location.hostname !== want && /^\d+\.\d+\.\d+\.\d+$/.test(location.hostname)) setTimeout(() => location.href = `http://${want}/`, 1500);
    else netInfo();
  };
}
async function unpin() {
  if (!confirm('Прибрати постійну адресу? Роутер знову видаватиме кабелю адресу сам, і вона може змінюватися.')) return;
  const r = await api('/api/static', {op: 'clear'}, 200000);
  toast(r.ok === false ? r.error : 'Адресу знову видає роутер');
  netInfo();
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
    const r = await api('/api/wifi', {op: 'scan'}, 700000);
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
      const r = await api('/api/wifi', {op: 'connect', ssid: n.ssid, password: $('#wfPw') ? $('#wfPw').value : ''}, 700000);
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
  const box = $('#log .wbody');
  const html = lines.length ? `<ol class="log">${lines.map(l => `<li><span class="t">${new Date(l.t * 1000).toLocaleTimeString('uk-UA')}</span>` +
    `<span class="u" style="color:var(--${col(l.unit)})">${esc(l.unit)}</span><span>${esc(l.msg)}</span></li>`).join('')}</ol>`
    : `<p class="note" style="margin:0">${esc(r.error || 'Журнал порожній.')}</p>`;
  if (r.ok === false && box.dataset.html) return;    // на мить не відповів — лишаємо, що було
  if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
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
    const r = await api('/api/update', {}, 600000);
    toast(!r.ok ? r.error : r.changed ? `Оновлено до ${r.version.split(' ')[0]}` : 'Уже встановлено останню версію');
    UPD = null;
    setTimeout(panel, r.changed ? 4000 : 0);
  };
}
async function checkUpdates(force) {
  UPD = await api('/api/updates' + (force ? '?force' : ''), undefined, 700000);
  if ($('#updBox')) { $('#updBox').innerHTML = updBox(); bindUpd(); }
}

// ───────────────────────── файли ─────────────────────────
// Менеджер файлів на дисках Хати: перегляд, завантаження з браузера (файли й цілі теки, перетягуванням),
// нова тека, перейменування, перенесення (вирізати → вставити), видалення. Плюс спільні папки (Samba).
const FS = {path: '', data: null, sel: new Set(), clip: null, ren: null, uploads: [], active: 0, jobs: [], share: null};
const ICON = {dir: '▸', video: '▶', subs: '¶', image: '▣', audio: '♪', archive: '▤', file: '·'};
const fdate = t => new Date(t * 1000).toLocaleDateString('uk-UA', {day: '2-digit', month: '2-digit', year: '2-digit'});

async function filesPage(path = FS.path) {
  stopPanel(); fromPanel = false;
  if (!$('.top nav a[data-files]')) { bar.hidden = false; if (LAST) panelTop(LAST); }
  $$('.top nav a').forEach(x => x.classList.toggle('on', x.dataset.k === '7'));
  const r = await api('/api/files' + (path ? '?path=' + encodeURIComponent(path) : ''));
  if (r.ok === false && path) return filesPage('');     // теки вже немає — на початок
  FS.data = r; FS.path = r.path || ''; FS.sel.clear(); FS.ren = null;
  if (!FS.share) api('/api/share').then(x => { FS.share = x; drawShare(); });
  drawFiles(); drawUploads(); drawShare();
  window.scrollTo(0, 0);
}

function drawFiles() {
  const r = FS.data || {}, items = r.items || [], atRoot = !r.up;
  if (!$('#fm')) {
    app.innerHTML = `<div class="wrap wide"><div id="fmPrompt"></div><div class="cols">
      ${win('файли', '', {n: '⁷', id: 'fm', cls: 'w9'})}
      <div style="flex:1 1 340px;min-width:0">${win('завантаження', '', {c: 'yel', id: 'up'})}${win('спільні папки', '', {c: 'vio', id: 'smb'})}</div>
    </div></div><div class="drop" id="drop" hidden><div><b>Відпусти, щоб завантажити</b><span id="dropTo"></span></div></div>
    <input type="file" id="fPick" multiple hidden><input type="file" id="dPick" webkitdirectory hidden>`;
    bindDrop();
    $('#fPick').onchange = e => { queueFiles([...e.target.files].map(f => ({file: f, rel: f.name}))); e.target.value = ''; };
    $('#dPick').onchange = e => { queueFiles([...e.target.files].map(f => ({file: f, rel: f.webkitRelativePath || f.name}))); e.target.value = ''; };
  }
  const rel = (r.path || '').slice((r.root || '').length).split('/').filter(Boolean);
  $('#fmPrompt').innerHTML = prompt(r.path || '/srv/disks', 'ls');
  const crumbs = `<nav class="crumbs fm-crumbs" aria-label="Шлях"><button class="lnk" data-cd="${esc(r.root || '')}">диски</button>` +
    rel.map((n, k) => `<span>/</span><button class="lnk" data-cd="${esc((r.root || '') + '/' + rel.slice(0, k + 1).join('/'))}">${esc(n)}</button>`).join('') + '</nav>';
  const tools = atRoot ? '' : `<div class="fm-tools">
      <button class="btn primary" id="upBtn">Завантажити файли</button><button class="btn" id="upDir">Цілу теку</button>
      <button class="btn" id="mk">Нова тека</button><span class="sp"></span>
      <span class="note" style="margin:0">вільно ${size(r.free)} з ${size(r.total)}</span></div>`;
  const clip = FS.clip ? `<div class="fm-bar"><span>Переносимо: <b>${FS.clip.paths.length === 1 ? esc(FS.clip.paths[0].split('/').pop()) : FS.clip.paths.length + ' шт.'}</b></span><span class="sp"></span>
      ${atRoot ? '<span class="note" style="margin:0">відкрий теку, куди перенести</span>' : '<button class="btn primary" id="paste">Вставити сюди</button>'}<button class="btn ghost" id="unclip">Скасувати</button></div>` : '';
  const sel = FS.sel.size ? `<div class="fm-bar"><span>Вибрано: <b>${FS.sel.size}</b></span><span class="sp"></span>
      <button class="btn" id="cut">Вирізати</button><button class="btn danger" id="del">Видалити</button><button class="btn ghost" id="unsel">Зняти</button></div>` : '';
  const rows = items.map((it, k) => {
    const path = (r.path || '') + '/' + it.name, on = FS.sel.has(path);
    const name = FS.ren === path
      ? `<form class="fm-ren" data-ren="${k}"><input value="${esc(it.name)}" aria-label="Нова назва" autofocus><button class="btn primary">OK</button></form>`
      : it.dir ? `<button class="lnk fm-name" data-cd="${esc(path)}">${esc(it.name)}</button>`
               : `<a class="fm-name" href="/api/files/dl?path=${encodeURIComponent(path)}" download>${esc(it.name)}</a>`;
    return `<div class="fm-row${on ? ' on' : ''}">` +
      (atRoot ? '<span></span>' : `<input type="checkbox" data-sel="${k}" ${on ? 'checked' : ''} aria-label="Вибрати ${esc(it.name)}">`) +
      `<span class="fm-ic k-${it.kind}" aria-hidden="true">${ICON[it.kind] || '·'}</span>${name}` +
      `<span class="fm-sz">${it.dir ? '' : size(it.size)}</span><span class="fm-dt">${fdate(it.mtime)}</span>` +
      (atRoot ? '<span></span>' : `<span class="fm-act"><button class="btn ghost" data-rn="${k}" aria-label="Перейменувати ${esc(it.name)}" title="Перейменувати">✎</button></span>`) + '</div>';
  }).join('');
  const empty = atRoot ? '<p class="note">Дисків ще немає — підключи їх у панелі, блок «диски».</p>'
    : '<div class="fm-empty">Тека порожня. Перетягни сюди файли чи теки з комп’ютера або натисни «Завантажити файли».</div>';
  $('#fm .wbody').innerHTML = crumbs + tools + clip + sel +
    (r.ok === false ? `<p class="err">${esc(r.error)}</p>` : '') +
    (items.length ? `<div class="fm-list">${rows}</div>` : empty) +
    (r.writable === false && !atRoot ? '<p class="note" style="color:var(--yel)">У цю теку Хата не має права писати.</p>' : '');
  bindFiles();
}

function bindFiles() {
  const r = FS.data || {}, items = r.items || [];
  const pathOf = k => (r.path || '') + '/' + items[k].name;
  $$('[data-cd]').forEach(b => b.onclick = () => filesPage(b.dataset.cd));
  $$('[data-sel]').forEach(c => c.onchange = () => { const p = pathOf(+c.dataset.sel); c.checked ? FS.sel.add(p) : FS.sel.delete(p); drawFiles(); });
  $$('[data-rn]').forEach(b => b.onclick = () => { FS.ren = pathOf(+b.dataset.rn); drawFiles(); const i = $('.fm-ren input'); if (i) { i.focus(); i.setSelectionRange(0, i.value.replace(/\.[^.]+$/, '').length); } });
  $$('[data-ren]').forEach(f => f.onsubmit = async e => {
    e.preventDefault();
    const x = await api('/api/files', {op: 'rename', path: pathOf(+f.dataset.ren), name: f.querySelector('input').value});
    if (x.ok === false) return toast(x.error);
    FS.ren = null; filesPage(FS.path);
  });
  if ($('#upBtn')) $('#upBtn').onclick = () => $('#fPick').click();
  if ($('#upDir')) $('#upDir').onclick = () => $('#dPick').click();
  if ($('#mk')) $('#mk').onclick = async () => {
    const n = window.prompt('Назва нової теки:');
    if (!n) return;
    const x = await api('/api/files', {op: 'mkdir', dir: FS.path, name: n});
    x.ok === false ? toast(x.error) : filesPage(FS.path);
  };
  if ($('#unsel')) $('#unsel').onclick = () => { FS.sel.clear(); drawFiles(); };
  if ($('#cut')) $('#cut').onclick = () => { FS.clip = {paths: [...FS.sel]}; FS.sel.clear(); drawFiles(); toast('Відкрий теку, куди перенести, і натисни «Вставити сюди»'); };
  if ($('#unclip')) $('#unclip').onclick = () => { FS.clip = null; drawFiles(); };
  if ($('#paste')) $('#paste').onclick = async () => {
    const b = $('#paste'); b.disabled = true; b.innerHTML = '<span class="spin"></span> Переношу…';
    const x = await api('/api/files', {op: 'move', paths: FS.clip.paths, dir: FS.path}, 300000);
    if (x.ok === false) { toast(x.error); b.disabled = false; b.textContent = 'Вставити сюди'; return; }
    FS.clip = null;
    if (x.job) { toast('Між дисками — копіюю у фоні, прогрес праворуч'); pollJobs(); } else { toast('Перенесено'); api('/api/files', {op: 'rescan'}); }
    filesPage(FS.path);
  };
  if ($('#del')) $('#del').onclick = async () => {
    const n = FS.sel.size;
    if (!confirm(`Видалити ${n === 1 ? '«' + [...FS.sel][0].split('/').pop() + '»' : n + ' шт.'} назавжди? Кошика немає — повернути не вийде.`)) return;
    const x = await api('/api/files', {op: 'delete', paths: [...FS.sel]}, 300000);
    x.ok === false ? toast(x.error) : toast(`Видалено: ${x.deleted}`);
    filesPage(FS.path);
  };
}

// ── завантаження: черга, по два файли одночасно, прогрес і швидкість ──
function queueFiles(list) {
  if (!FS.data || !FS.data.up) return toast('Спершу відкрий теку на диску, куди завантажувати');
  if (FS.data.writable === false) return toast('У цю теку Хата не може писати — онови Хату або перевір права на диск');
  for (const {file, rel} of list) FS.uploads.push({file, rel, dir: FS.path, sent: 0, state: 'wait', t0: 0, xhr: null});
  drawUploads(); pumpUploads();
}

function pumpUploads() {
  while (FS.active < 2) {
    const u = FS.uploads.find(x => x.state === 'wait');
    if (!u) break;
    FS.active++; u.state = 'go'; u.t0 = performance.now();
    const x = u.xhr = new XMLHttpRequest();
    x.open('PUT', `/api/files/upload?dir=${encodeURIComponent(u.dir)}&name=${encodeURIComponent(u.rel)}`);
    x.upload.onprogress = e => { u.sent = e.loaded; drawUploads(); };
    x.onload = () => { let j = {}; try { j = JSON.parse(x.responseText); } catch (e) {} finish(u, j.ok ? 'done' : 'err', j.error || 'Помилка ' + x.status); };
    x.onerror = () => finish(u, 'err', x.upload && u.sent < u.file.size ? 'Сервер обірвав завантаження — глянь журнал Хати' : 'З’єднання обірвалось');
    x.onabort = () => finish(u, 'cancel', '');
    x.send(u.file);
  }
}
function finish(u, state, err) {
  u.state = state; u.err = err; u.sent = state === 'done' ? u.file.size : u.sent; FS.active--;
  drawUploads(); pumpUploads();
  if (!FS.uploads.some(x => x.state === 'wait' || x.state === 'go')) {
    api('/api/files', {op: 'rescan'});                 // VidBox підхопить нове одразу
    if ($('#fm')) filesPage(FS.path);
  }
}

function drawUploads() {
  if (!$('#up')) return;
  const live = FS.uploads.filter(u => u.state !== 'done' || performance.now() - u.t0 < 600000).slice(-30);
  const rows = live.map((u, k) => {
    const pct = u.file.size ? u.sent / u.file.size * 100 : 100;
    const sec = (performance.now() - u.t0) / 1000, sp = u.state === 'go' && sec > .5 ? u.sent / sec : 0;
    const st = u.state === 'done' ? '<span class="st">готово</span>' : u.state === 'err' ? `<span class="st" style="color:var(--red)">${esc(u.err)}</span>`
      : u.state === 'cancel' ? '<span class="st" style="color:var(--dim)">скасовано</span>'
      : u.state === 'wait' ? '<span class="st" style="color:var(--dim)">у черзі</span>' : `<span class="st">${short(sp)}/с</span>`;
    return `<div class="up-row"><div class="up-n"><b title="${esc(u.rel)}">${esc(u.rel)}</b>${st}</div>
      <div class="up-p">${segs(pct, 24, u.state === 'err' ? '' : 'mono')}<span class="note" style="margin:0">${size(u.sent)} / ${size(u.file.size)}</span>
      ${u.state === 'go' || u.state === 'wait' ? `<button class="btn ghost" data-cancel="${FS.uploads.indexOf(u)}" aria-label="Скасувати">×</button>` : ''}</div></div>`;
  }).join('');
  const jobs = FS.jobs.filter(j => j.state === 'working' || Date.now() / 1000 - (j.finished || 0) < 60).map(j =>
    `<div class="up-row"><div class="up-n"><b>⇢ ${esc(j.name)}${j.count > 1 ? ` (+${j.count - 1})` : ''}</b><span class="st"${j.state === 'error' ? ' style="color:var(--red)"' : ''}>${j.state === 'done' ? 'перенесено' : j.state === 'error' ? esc(j.error) : 'переношу між дисками'}</span></div>
     <div class="up-p">${segs(j.total ? j.done / j.total * 100 : 0, 24, 'mono')}<span class="note" style="margin:0">${size(j.done)} / ${size(j.total)}</span></div></div>`).join('');
  $('#up .wbody').innerHTML = (jobs + rows) ||
    `<p class="note" style="margin:0">Перетягни файли чи цілі теки з комп’ютера будь-куди на цю сторінку — вони завантажаться у відкриту теку. З телефона — кнопка «Завантажити файли».</p>`;
  $$('[data-cancel]').forEach(b => b.onclick = () => { const u = FS.uploads[+b.dataset.cancel]; if (u.xhr && u.state === 'go') u.xhr.abort(); else { u.state = 'cancel'; drawUploads(); } });
}

let jobsT;
async function pollJobs() {
  clearTimeout(jobsT);
  const r = await api('/api/files/jobs');
  FS.jobs = r.jobs || [];
  drawUploads();
  if (FS.jobs.some(j => j.state === 'working')) jobsT = setTimeout(pollJobs, 1000);
  else { api('/api/files', {op: 'rescan'}); if ($('#fm')) filesPage(FS.path); }
}

// ── перетягування: файли й цілі теки (через webkitGetAsEntry) ──
function bindDrop() {
  let depth = 0;
  const show = on => { $('#drop').hidden = !on; if (on) $('#dropTo').textContent = FS.data && FS.data.up ? FS.path : 'спершу відкрий теку на диску'; };
  document.ondragenter = e => { if ($('#fm') && [...(e.dataTransfer?.types || [])].includes('Files')) { depth++; show(true); } };
  document.ondragleave = () => { if (--depth <= 0) { depth = 0; show(false); } };
  document.ondragover = e => { if ($('#fm')) e.preventDefault(); };
  document.ondrop = async e => {
    if (!$('#fm')) return;
    e.preventDefault(); depth = 0; show(false);
    const entries = [...e.dataTransfer.items].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    const out = [];
    const walk = (en, pre) => new Promise(res => {
      if (en.isFile) return en.file(f => { out.push({file: f, rel: pre + f.name}); res(); }, () => res());
      const rd = en.createReader(), all = [];
      const more = () => rd.readEntries(async batch => {
        if (batch.length) { all.push(...batch); return more(); }
        for (const c of all) await walk(c, pre + en.name + '/');
        res();
      }, () => res());
      more();
    });
    if (entries.length) { for (const en of entries) await walk(en, ''); }
    else out.push(...[...e.dataTransfer.files].map(f => ({file: f, rel: f.name})));
    if (out.length) queueFiles(out);
  };
}

// ── спільні папки (Samba): \\hata у Windows, smb://hata.local на Mac ──
function drawShare() {
  if (!$('#smb')) return;
  const s = FS.share, ip = (LAST && (LAST.ips || [])[0]) || location.hostname, host = (LAST && LAST.host) || HOST;
  if (!s) { $('#smb .wbody').innerHTML = '<p class="note" style="margin:0"><span class="spin"></span></p>'; return; }
  if (s.enabled) {
    $('#smb .wbody').innerHTML = `<p style="margin:0 0 10px"><span class="okdot"></span>Увімкнено — диски Хати видно як мережеві папки.</p>
      <dl class="kv"><dt>Windows</dt><dd class="link">\\\\${esc(ip)}</dd><dt>Mac</dt><dd class="link">smb://${esc(host)}.local</dd>
      <dt>вхід</dt><dd>hata · пароль панелі</dd><dt>папки</dt><dd>${(s.shares || []).map(x => esc(x.name)).join(', ') || '—'}</dd></dl>
      <p class="note">Windows: «Провідник» → у рядок адреси <b>\\\\${esc(ip)}</b> → правою кнопкою на диску → «Підключити мережевий диск». Mac: Finder → Cmd+K → <b>smb://${esc(host)}.local</b>.</p>
      <div class="acts"><button class="btn ghost" id="smbOff">Вимкнути</button></div>`;
    $('#smbOff').onclick = async () => {
      if (!confirm('Вимкнути спільні папки? Мережеві диски на ПК і Mac перестануть відкриватись.')) return;
      FS.share = await api('/api/share', {op: 'disable'}); drawShare();
    };
  } else {
    $('#smb .wbody').innerHTML = `<p class="note" style="margin-top:0">Диски Хати стануть звичайними мережевими папками у Windows («Провідник») і на Mac (Finder) — копіюй фільми просто туди, як на флешку. Працює вдома й через Tailscale.</p>
      <form id="smbF" style="display:flex;flex-wrap:wrap;gap:10px"><label class="field" style="flex:1 1 200px"><span aria-hidden="true">❯</span><input id="smbPw" type="password" placeholder="пароль панелі" aria-label="Пароль панелі" autocomplete="current-password"></label>
      <button class="btn primary" id="smbOn">Увімкнути</button></form><div class="err" id="smbErr" role="alert"></div>`;
    $('#smbF').onsubmit = async e => {
      e.preventDefault();
      const b = $('#smbOn'); b.disabled = true; b.innerHTML = '<span class="spin"></span> Встановлюю…';
      const r = await api('/api/share', {op: 'enable', password: $('#smbPw').value}, 700000);
      if (r.ok === false) { $('#smbErr').textContent = r.error; b.disabled = false; b.textContent = 'Увімкнути'; return; }
      FS.share = r; drawShare(); toast('Спільні папки увімкнено');
    };
  }
}

// ───────────────────────── диски: здоров'я, сон, копії ─────────────────────────
// SMART читає gazda (root) раз на 5 хв, не будячи сплячих дисків. Копії робить сама панель (core/backup.py).
const DK = {health: null, bk: null, pick: null, picking: false};
let disksTimer;
const hoursText = h => h == null ? '—' : `${h.toLocaleString('uk-UA')} год` + (h >= 8760 ? ` ≈ ${(h / 8760).toFixed(1).replace('.', ',')} р.` : '');
const agoText = t => { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 90 ? 'щойно' : s < 3600 ? `${Math.round(s / 60)} хв тому` : s < 86400 ? `${Math.round(s / 3600)} год тому` : new Date(t * 1000).toLocaleDateString('uk-UA', {day: 'numeric', month: 'short'}); };
const pl = (n, one, few, many) => { n = Math.abs(n) % 100; const d = n % 10; return n > 10 && n < 20 ? many : d === 1 ? one : d > 1 && d < 5 ? few : many; };
const razy = n => pl(n, 'раз', 'рази', 'разів');
const minsText = m => m < 0 ? 'як є' : !m ? 'ніколи' : m < 60 ? `${m} хв` : `${m / 60} год`;

// Висновок про диск звичайними словами: [рівень, текст]
function diskVerdict(d) {
  const s = d.smart || {};
  if (s.state === 'none' || (!s.state && !s.at)) return ['dim', s.why ? `SMART недоступний: ${s.why}` : 'SMART ще не прочитано'];
  const out = [];
  if (s.passed === false) out.push(['red', 'SMART каже, що диск відмовляє. Скопіюй важливе якнайшвидше й заміни диск.']);
  if (s.failing && s.failing.length) out.push(['red', `Показники нижче межі: ${s.failing.join(', ')}.`]);
  if (s.pending > 0 || s.uncorrect > 0) out.push(['red', `${(s.pending || 0) + (s.uncorrect || 0)} ${pl((s.pending || 0) + (s.uncorrect || 0), 'нестабільний чи нечитабельний сектор', 'нестабільні чи нечитабельні сектори', 'нестабільних чи нечитабельних секторів')} — диск може втрачати дані. Зроби копію важливого.`]);
  if (s.realloc > 0) out.push(['yel', `${s.realloc} ${pl(s.realloc, 'перепризначений сектор', 'перепризначені сектори', 'перепризначених секторів')}: диск почав зношуватись. Поки працює, але стеж, чи число не росте.`]);
  if (s.media_errors > 0) out.push(['red', `${s.media_errors} ${pl(s.media_errors, 'помилка', 'помилки', 'помилок')} носія — SSD може втрачати дані.`]);
  if (s.life != null && s.life <= 10) out.push(['yel', `Ресурс SSD майже вичерпано (лишилось ${s.life}%).`]);
  if (s.temp >= 55) out.push(['red', `Гарячий: ${s.temp} °C. Дай йому повітря або перестав з-під ноутбука.`]);
  else if (s.temp >= 50) out.push(['yel', `Теплий: ${s.temp} °C — вище за комфортні для HDD 50 °C.`]);
  // Ресурс паркувань: 2,5" (WD Blue, Toshiba MQ04 …) — 600 тис., звичайні 3,5" — 300 тис.
  const lim = /^2\.5/.test(s.form || '') || !s.form && d.usb && d.size < 2.2e12 ? 600000 : 300000;
  const lc = s.load_cycles, rate = lc && s.hours > 0 ? Math.round(lc / s.hours) : 0;
  const nice = n => n.toLocaleString('uk-UA');
  if (lc >= lim) out.push(['yel', `Головки запаркувались ${nice(lc)} ${razy(lc)} — більше за ресурс від виробника (${nice(lim / 1000)} тис.). Диск ще може довго працювати, але копії тримай свіжими.`]);
  else if (lc >= lim * .8) out.push(['yel', `Головки запаркувались ${nice(lc)} ${razy(lc)} — майже весь ресурс від виробника (${nice(lim / 1000)} тис.). Копії тримай свіжими.`]);
  if (d.sleep >= 0 && s.lc_rate > 20) out.push(['yel', `Головки й далі паркуються ~${s.lc_rate} ${razy(s.lc_rate)} на годину. Схоже, диск не слухає команду про паркування, а щохвилинне читання, яке не дає доку приспати диск, будить головки знову. Вибери «як є» — так паркувань буде менше.`]);
  if (d.sleep < 0 && lc > 1000 && (s.lc_rate ?? rate) > 20) out.push(['yel', `Головки паркуються ~${s.lc_rate ?? rate} ${razy(s.lc_rate ?? rate)} на годину. Вибери нижче «ніколи» або час сну — Хата вимкне це паркування.`]);
  if (s.crc > 0) out.push(['yel', `${s.crc} ${pl(s.crc, 'помилка', 'помилки', 'помилок')} передачі — зазвичай винен кабель чи USB-адаптер, а не сам диск.${s.crc < 10 ? ' Кілька штук за роки — не страшно, якщо число не росте.' : ''}`]);
  if (!out.length) return ['acc', s.state === 'standby' ? 'Здоровий, зараз спить.' : 'Диск здоровий.'];
  return out.sort((a, b) => (a[0] === 'red' ? 0 : 1) - (b[0] === 'red' ? 0 : 1))[0].concat([out.slice(1).map(x => x[1])]);
}

function sleepNote(d) {
  const s = d.smart || {};
  const now = s.state === 'standby' ? 'Зараз спить — прокинеться сам, щойно щось знадобиться (кілька секунд розкрутки).'
    : d.idle != null && d.sleep !== 0 ? `Без роботи ${d.idle < 60 ? 'менше хвилини' : Math.round(d.idle / 60) + ' хв'}.` : '';
  const own = d.tuned === false ? ' Диск не прийняв команду вимкнути власний таймер — тримаю лише читанням.' : '';
  if (d.sleep < 0) return `${now} Хата не втручається: диск чи док засинають за своїм таймером (деякі доки — вже за 2–3 хв).`;
  if (d.sleep === 0) return `Тримаю розкрученим: власний таймер диска вимкнено, і раз на хвилину читаю 4 КБ, щоб док не приспав.${own} Відео стартує без затримки; ціна — кілька ват, тепло й шум.`;
  return `${now} До ${minsText(d.sleep)} без роботи не дам заснути ні диску, ні доку, далі приспить Хата.${own} Часте засинання–прокидання теж зношує — 20–30 хв зазвичай оптимально.`;
}

function diskCard(d, choices) {
  const s = d.smart || {}, [lvl, text, more] = diskVerdict(d);
  const kind = (d.rot ? 'HDD' : d.loop ? 'файл-диск' : 'SSD') + (d.usb ? ' · USB' : d.system ? ' · внутрішній' : '');
  const state = d.loop ? '' : s.state === 'standby' ? '<span class="okdot off"></span>спить' : s.state === 'active' ? '<span class="okdot"></span>працює' : '';
  const t = s.temp;
  const rows = [
    ['робота', hoursText(s.hours)], ['увімкнень', s.cycles != null ? s.cycles.toLocaleString('uk-UA') : null],
    ['паркувань головок', s.load_cycles != null ? s.load_cycles.toLocaleString('uk-UA') + (s.lc_rate != null ? ` (зараз ${s.lc_rate}/год)` : s.hours > 0 ? ` (у сер. ${Math.round(s.load_cycles / s.hours)}/год)` : '') : null],
    ['перепризначені', s.realloc], ['нестабільні', s.pending], ['невиправні', s.uncorrect], ['помилки кабелю', s.crc],
    ['ресурс', s.life != null ? `${s.life}%` : null], ['резерв', s.spare != null ? `${s.spare}%` : null], ['помилки носія', s.media_errors],
  ].filter(r => r[1] != null && r[1] !== '—' || r[0] === 'робота' && s.hours != null);
  const bad = k => ({перепризначені: s.realloc > 0, нестабільні: s.pending > 0, невиправні: s.uncorrect > 0, 'помилки кабелю': s.crc > 0, 'помилки носія': s.media_errors > 0})[k];
  const usage = Object.entries(d.usage || {}).map(([n, u]) => u ? `<span>${esc(n)}</span>${segs((u.total - u.free) / u.total * 100, 30)}<span class="v">${size(u.total - u.free)} / ${size(u.total)}</span>` : '').join('');
  return win(d.names.join(' · '), `
    <p class="dk-sub">${esc(d.model || s.model || 'диск')}${d.size ? ' · ' + size(d.size) : ''} · ${kind}${state ? ` · ${state}` : ''}</p>
    <div class="dk-top">
      ${t != null ? `<div class="dk-temp" style="--c:var(--${t >= 55 ? 'red' : t >= 50 ? 'yel' : 'acc'})"><b>${t}°</b><small>${s.state === 'standby' ? 'до сну' : 'зараз'}</small></div>` : ''}
      <div class="dk-verdict ${lvl}"><b>${esc(text)}</b>${(more || []).map(m => `<small>${esc(m)}</small>`).join('')}</div>
    </div>
    ${usage ? `<div class="meters" style="margin-top:14px">${usage}</div>` : ''}
    ${rows.length ? `<dl class="kv dk-kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd class="${bad(k) ? 'bad' : ''}">${esc(v)}</dd>`).join('')}</dl>` : ''}
    ${d.sleepable ? `<p class="note" style="margin-top:16px">засинати без роботи через</p>
      <div class="seg dk-sleep" role="group" aria-label="Засинати без роботи">${choices.map(m => `<button data-sleep="${m}" data-dev="${esc(d.dev)}" class="${d.sleep === m ? 'on' : ''}">${minsText(m)}</button>`).join('')}</div>
      <p class="note">${sleepNote(d)}</p>` : ''}
    <div class="acts">${d.loop ? '' : `<button class="btn" data-smart="${esc(d.dev)}">Оновити SMART</button>`}
      ${d.names.filter(n => n !== 'система').map(n => `<button class="btn ghost" data-fopen="${esc(n)}">Файли: ${esc(n)}</button>`).join('')}
      <span class="sp"></span><span class="note" style="margin:0">${s.at ? 'перевірено ' + agoText(s.at) : ''}</span></div>`,
    {c: lvl === 'red' ? 'red' : lvl === 'yel' ? 'yel' : 'acc', cls: 'dk', badge: lvl === 'red' ? 'увага' : ''});
}

function backupHTML() {
  const b = DK.bk || {}, c = b.conf || {}, j = b.job || {}, last = c.last;
  const disks = b.disks || [];
  const same = f => c.target && (f === b.root + '/' + c.target || f.startsWith(b.root + '/' + c.target + '/'));
  const folders = (c.folders || []).map(f => `<div class="row"><div class="l"><b>${esc(f)}</b>${same(f) ? '<small style="color:var(--yel)">на тому самому диску, що й копії — від поломки диска не врятує</small>' : ''}</div>
    <div class="r"><button class="btn ghost" data-bkrm="${esc(f)}" aria-label="Прибрати ${esc(f)}">✕</button></div></div>`).join('');
  const lastText = !last ? 'Копій ще не було.' : last.error ? `<span style="color:var(--red)">Остання спроба ${agoText(last.at)} не вдалася: ${esc(last.error)}</span>`
    : `Остання копія ${agoText(last.at)} ${last.ok ? '<span style="color:var(--acc)">✓</span>' : `<span style="color:var(--yel)">з помилками (${last.errors})</span>`}: ${(last.files || 0).toLocaleString('uk-UA')} файлів, ${size(last.bytes)} — нового скопійовано ${size(last.copied)}${last.took != null ? `, ${last.took} с` : ''}.`;
  const picker = DK.picking ? `<div class="dk-pick"><div class="crumbs">${esc(DK.pick && DK.pick.path || 'диски')}</div>
      ${DK.pick && DK.pick.path ? `<div class="row"><div class="l"><b><a href="#" data-bkgo="${esc(DK.pick.up || '')}">..</a></b></div><div class="r">${DK.pick.up ? `<button class="btn primary" data-bkadd="${esc(DK.pick.path)}">Копіювати цю теку</button>` : ''}</div></div>` : ''}
      ${(DK.pick && DK.pick.dirs || []).map(x => `<div class="row"><div class="l"><b><a href="#" data-bkgo="${esc(x.path)}">${esc(x.name)}/</a></b></div></div>`).join('') || '<p class="note">Тут порожньо.</p>'}
      <div class="acts"><button class="btn ghost" id="bkPickClose">Готово</button></div></div>` : '';
  return `<p class="lead" style="margin-bottom:12px">Щодня в заданий час: налаштування й бази Хати (прогрес у VidBox і манзі, «Будинок», Хата) і вибрані теки — на інший диск. Незмінене не копіюється вдруге, тож копій можна тримати багато.</p>
    <div class="dk-form">
      <div><label class="f" for="bkTarget">диск для копій</label>
      <select id="bkTarget"><option value="">— не копіювати —</option>${disks.map(n => `<option value="${esc(n)}"${n === c.target ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
      <div><label class="f" for="bkTime">щодня о</label><input id="bkTime" type="time" value="${esc(c.time || '03:30')}"></div>
      <div><label class="f" for="bkKeep">тримати копій</label><input id="bkKeep" type="number" min="1" max="90" value="${c.keep || 14}"></div>
    </div>
    ${b.free != null ? `<p class="note">На диску «${esc(c.target)}» вільно ${size(b.free)} з ${size(b.total)}.</p>` : ''}
    <p class="note" style="margin-top:16px">що копіювати</p>
    <div class="row"><div class="l"><b>Хата і VidBox</b><small>налаштування, бази, прогрес — завжди (без кешів кадрів і обкладинок)</small></div><div class="r"><span class="tag ok">завжди</span></div></div>
    ${folders}
    ${picker || `<div class="acts" style="margin-top:8px"><button class="btn" id="bkPick">Додати теку</button></div>`}
    <p class="note" style="margin-top:16px">${j.running ? `<span class="spin"></span> Копіюю${j.step ? ': ' + esc(j.step) : ''}…` : lastText}</p>
    <div class="acts"><button class="btn primary" id="bkRun"${!c.target || j.running ? ' disabled' : ''}>Зробити копію зараз</button></div>
    ${(b.snapshots || []).length ? `<p class="note" style="margin-top:18px">копії на диску «${esc(c.target)}»</p><ol class="dk-snaps">${b.snapshots.map(s => `<li><button class="linkbtn" data-fpath="${esc(s.path)}">${esc(s.name)}</button>
      <span>${s.files != null ? `${s.files.toLocaleString('uk-UA')} файлів · ${size(s.bytes)}` : ''}${s.errors ? ` · <span style="color:var(--yel)">помилок ${s.errors}</span>` : ''}</span></li>`).join('')}</ol>
      <p class="note">Відновити: відкрий копію у «Файлах» і перенеси потрібне назад.</p>` : ''}`;
}

async function disksPage() {
  stopPanel(); fromPanel = false;
  if (!$('.top nav a[data-house]')) { bar.hidden = false; if (LAST) panelTop(LAST); }
  $$('.top nav a').forEach(x => x.classList.toggle('on', x.dataset.k === '2'));
  if (!$('#dkBody')) {
    app.innerHTML = `<div class="wrap wide">${prompt('~/диски', 'smartctl -a /dev/sd*')}<div id="dkBody"><p class="note"><span class="spin"></span></p></div></div>`;
    window.scrollTo(0, 0);
  }
  const [h, b] = await Promise.all([api('/api/disks/health'), api('/api/backup')]);
  if (!$('#dkBody')) return;
  DK.health = h; DK.bk = b;
  drawDisks();
  clearTimeout(disksTimer);
  disksTimer = setTimeout(() => { if ($('#dkBody') && !typing() && !DK.picking) disksPage(); else if ($('#dkBody')) disksTimer = setTimeout(disksPage, 30000); },
    (DK.bk.job || {}).running ? 3000 : 30000);
}

function drawDisks() {
  const h = DK.health || {}, list = h.disks || [];
  const cards = h.ok === false ? win('диски', `<p class="err">${esc(h.error)}</p>`, {c: 'red'}) : list.map(d => diskCard(d, h.choices || [0, 10, 20, 30, 60])).join('');
  const html = `<div class="dk-grid">${cards}</div>
    <div class="cols">${win('копії', backupHTML(), {c: 'vio', id: 'bk', cls: 'w2'})}
      ${win('ще диск?', `<p class="note" style="margin-top:0">Новий диск у доці чи USB підключається тут — так само, як у майстрі.</p><div class="acts"><button class="btn" id="dkFind">Знайти диски</button></div>`, {c: 'dim'})}</div>`;
  const box = $('#dkBody');
  if (box.dataset.html === html) return;
  box.innerHTML = html; box.dataset.html = html;
  bindDisks();
}

function bindDisks() {
  $$('[data-sleep]').forEach(btn => btn.onclick = async () => {
    const r = await api('/api/disks/health', {op: 'sleep', dev: btn.dataset.dev, minutes: +btn.dataset.sleep});
    const m = +btn.dataset.sleep;
    toast(r.ok ? (m < 0 ? 'Сон — як вирішить диск чи док' : m ? `Засинатиме через ${minsText(m)} без роботи` : 'Не засинатиме') : r.error);
    disksPage();
  });
  $$('[data-smart]').forEach(btn => btn.onclick = async () => {
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Читаю…';
    const r = await api('/api/disks/health', {op: 'refresh', dev: btn.dataset.smart}, 130000);
    if (r.ok === false) toast(r.error);
    disksPage();
  });
  $$('[data-fopen]').forEach(b => b.onclick = () => filesPage((DK.bk && DK.bk.root || '/srv/disks') + '/' + b.dataset.fopen));
  $$('[data-fpath]').forEach(b => b.onclick = () => filesPage(b.dataset.fpath));
  $('#dkFind').onclick = () => openFromPanel(2);
  const save = async d => { const r = await api('/api/backup', {op: 'save', ...d}); if (r.ok === false) toast(r.error); await disksPage(); return r; };
  $('#bkTarget').onchange = e => save({target: e.target.value}).then(r => r.ok && toast(e.target.value ? `Копії йтимуть на «${e.target.value}»` : 'Копії вимкнено'));
  $('#bkTime').onchange = e => save({time: e.target.value}).then(r => r.ok && toast(`Щодня о ${e.target.value}`));
  $('#bkKeep').onchange = e => save({keep: +e.target.value});
  $$('[data-bkrm]').forEach(b => b.onclick = () => save({folders: DK.bk.conf.folders.filter(f => f !== b.dataset.bkrm)}));
  const browse = async p => { DK.pick = await api('/api/dirs' + (p ? '?path=' + encodeURIComponent(p) : '')); DK.picking = true; drawDisks(); };
  if ($('#bkPick')) $('#bkPick').onclick = () => browse(DK.bk.root);
  $$('[data-bkgo]').forEach(a => a.onclick = e => { e.preventDefault(); browse(a.dataset.bkgo); });
  $$('[data-bkadd]').forEach(b => b.onclick = () => { DK.picking = false; save({folders: (DK.bk.conf.folders || []).concat(b.dataset.bkadd)}); });
  if ($('#bkPickClose')) $('#bkPickClose').onclick = () => { DK.picking = false; drawDisks(); };
  $('#bkRun').onclick = async () => {
    const r = await api('/api/backup', {op: 'run'});
    toast(r.ok ? 'Копіюю у фоні' : r.error);
    disksPage();
  };
}

// ───────────────────────── будинок (заміри від ESP) ─────────────────────────
// Плати RoomMonitor надсилають заміри раз на 15 с. Тут: що зараз, графік з проміжками без світла
// й інтернету, події та ключ, який треба вписати в скетч.
const HS = {dev: null, key: 'temp', range: localStorage.getItem('hata_hrange') || '24h', now: null, series: {}, ev: null, keyInfo: null, at: 0};
const HRANGES = [['1h', 'година'], ['24h', 'доба'], ['7d', 'тиждень'], ['30d', 'місяць']];
const HNAMES = {'temp.room': 'кімната', 'temp.outside': 'вулиця', 'temp.radiator': 'батарея', 'humidity.room': 'вологість',
  'pressure_hpa': 'тиск', 'lux': 'світло', 'co2_ppm': 'CO₂', 'ping_ms': 'пінг', 'rssi': 'сигнал wi-fi', 'devices': 'пристрої в мережі',
  'battery_v': 'батарея плати', 'chip_temp': 'чип плати', 'internet': 'інтернет', 'power': 'світло є', 'free_heap': 'пам’ять плати'};
const HUNIT = {'humidity.room': '%', pressure_hpa: 'гПа', lux: 'лк', co2_ppm: 'ppm', ping_ms: 'мс', rssi: 'дБм', battery_v: 'В', chip_temp: '°C', free_heap: 'Б'};
const hname = k => HNAMES[k] || (k.startsWith('temp.') ? k.slice(5) : k);
const hunit = k => k.startsWith('temp.') ? '°C' : (HUNIT[k] || '');
const HCOL = ['acc', 'vio', 'red', 'yel'];
const hfix = (v, k) => v == null ? '—' : (Math.abs(v) >= 100 || /devices|lux|free_heap|ping|rssi|co2/.test(k) ? Math.round(v) : v.toFixed(1)).toString().replace('.', ',');
const hclock = t => new Date(t * 1000).toLocaleTimeString('uk-UA', {hour: '2-digit', minute: '2-digit'});
const hago = s => s < 60 ? `${s} с тому` : s < 3600 ? `${Math.round(s / 60)} хв тому` : `з ${hclock(Math.floor(Date.now() / 1000) - s)}`;
const hdur = s => s == null ? '' : s < 60 ? `${s} с` : s < 3600 ? `${Math.round(s / 60)} хв` : s < 86400 ? `${Math.floor(s / 3600)} год ${Math.round(s % 3600 / 60)} хв` : `${Math.floor(s / 86400)} дн ${Math.round(s % 86400 / 3600)} год`;
let houseTimer, houseSeriesAt = 0;

async function housePage() {
  stopPanel(); fromPanel = false;
  if (!$('.top nav a[data-house]')) { bar.hidden = false; if (LAST) panelTop(LAST); }
  $$('.top nav a').forEach(x => x.classList.toggle('on', x.dataset.k === '8'));
  app.innerHTML = `<div class="wrap wide">${prompt('~/будинок', 'tail -f room')}<div id="hBody"><p class="note"><span class="spin"></span></p></div></div>`;
  window.scrollTo(0, 0);
  houseSeriesAt = 0;
  await houseTick();
}

async function houseTick() {
  clearTimeout(houseTimer);
  if (!$('#hBody')) return;
  if (!document.hidden) {
    const [now, key] = await Promise.all([api('/api/house/now'), HS.keyInfo ? null : api('/api/house/key')]);
    if (!$('#hBody')) return;
    if (key) HS.keyInfo = key;
    HS.now = now;
    const devs = now.devices || [];
    if (!HS.dev || !devs.find(d => d.device === HS.dev)) HS.dev = (devs.find(d => d.device === 'room') || devs[0] || {}).device || null;
    const fresh = Date.now() - houseSeriesAt > (HS.range === '1h' ? 15000 : 60000);
    if (HS.dev && fresh) await houseLoadSeries();
    drawHouse();
  }
  houseTimer = setTimeout(houseTick, 5000);
}

const hdev = () => (HS.now && HS.now.devices || []).find(d => d.device === HS.dev);
const hkeys = d => Object.keys(d ? d.values : {}).sort();
const htemps = d => hkeys(d).filter(k => k.startsWith('temp.')).sort((a, b) => (a !== 'temp.room') - (b !== 'temp.room') || a.localeCompare(b));

async function houseLoadSeries() {
  const d = hdev();
  if (!d) return;
  const keys = HS.key === 'temp' ? htemps(d) : [HS.key];
  const q = k => api(`/api/house/series?device=${encodeURIComponent(HS.dev)}&key=${encodeURIComponent(k)}&range=${HS.range}`);
  const [ev, ...ser] = await Promise.all([api(`/api/house/events?range=${HS.range}&device=${encodeURIComponent(HS.dev)}`), ...keys.map(q)]);
  HS.series = Object.fromEntries(keys.map((k, i) => [k, ser[i]]));
  HS.ev = ev;
  houseSeriesAt = Date.now();
}

function drawHouse() {
  const box = $('#hBody'), devs = HS.now.devices || [], d = hdev();
  if (!d) {
    const html = `<div class="cols">${win('будинок', `<p class="lead" style="margin-bottom:10px">Тут з’являться температура в кімнаті, графік і відключення світла від плати RoomMonitor (ESP32).</p>
      <p class="note">Плата ще нічого не надсилала. Впиши ключ нижче в скетч і прошей плату — перші заміри прийдуть за 15 с.</p>`, {n: '⁸', id: 'hempty'})}
      ${win('ключ плати', houseKeyHTML(), {c: 'yel', id: 'hkey'})}</div>`;
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; bindHouseKey(); }
    return;
  }
  const v = k => d.values[k] ? d.values[k].v : null;
  const tkeys = htemps(d), main = tkeys[0];
  const t = main ? v(main) : null, tt = main ? d.temps[main] || {} : {};
  const tr = tt.trend, arrow = tr == null ? '' : tr > 0.15 ? '↑' : tr < -0.15 ? '↓' : '→';
  const since = HS.now.now - (d.lastSeen || 0);
  const src = {ntc: 'терморезистор', sensor: 'датчик', estimate: 'оцінка ±2 °C', none: 'нема датчика'}[d.tempSrc] || d.tempSrc || '';
  const big = t == null ? '' : (Math.round(t * 10) / 10).toFixed(1);
  const pw = v('power'), inet = v('internet'), rssi = v('rssi');
  const nowHTML = `<div class="hnow">
      <div class="htemp">${t == null ? '<p class="note" style="margin:0">температури ще немає</p>' : `${dots(big, true)}<span class="hdeg">°C</span>`}</div>
      <div class="hside"><p class="hstate"><span class="okdot ${d.online ? '' : 'off'}"></span>${d.online ? `на зв’язку · ${hago(since)}` : `офлайн ${hago(since)}`}</p>
        ${t == null ? '' : `<p>${arrow ? `<b class="harrow">${arrow}</b> ${tr > 0 ? '+' : ''}${hfix(tr)}° за 30 хв` : 'тренд з’явиться за пів години'}</p>
        <p class="note" style="margin:4px 0 0">сьогодні ${hfix(tt.min)}…${hfix(tt.max)} °C${src ? ` · <span class="tag${d.tempSrc === 'estimate' ? ' warn' : ''}">${esc(src)}</span>` : ''}</p>`}
        ${tkeys.slice(1).map(k => `<p class="note" style="margin:4px 0 0">${esc(hname(k))}: <b style="color:var(--fg)">${hfix(v(k))} °C</b></p>`).join('')}</div></div>
    <dl class="kv" style="margin-top:16px">
      ${pw != null ? `<dt>світло</dt><dd>${pw ? '<span class="okdot"></span>є' : '<span class="okdot off"></span>немає'}</dd>` : ''}
      ${inet != null ? `<dt>інтернет</dt><dd>${inet ? `<span class="okdot"></span>є${v('ping_ms') != null && v('ping_ms') >= 0 ? ` · пінг ${hfix(v('ping_ms'), 'ping')} мс` : ''}` : '<span class="okdot off"></span>немає'}</dd>` : ''}
      ${v('humidity.room') != null ? `<dt>вологість</dt><dd>${hfix(v('humidity.room'))} %</dd>` : ''}
      ${v('co2_ppm') != null ? `<dt>CO₂</dt><dd>${hfix(v('co2_ppm'), 'co2')} ppm</dd>` : ''}
      ${v('devices') != null ? `<dt>у мережі</dt><dd>${hfix(v('devices'), 'devices')} пристр.</dd>` : ''}
      ${rssi != null ? `<dt>wi-fi плати</dt><dd style="display:flex;gap:8px;align-items:center">${segs(sigPct(rssi), 10).replace('class="segs ', 'style="width:70px;flex:none" class="segs ')}${hfix(rssi, 'rssi')} дБм</dd>` : ''}
      ${v('battery_v') != null ? `<dt>батарея плати</dt><dd>${hfix(v('battery_v'))} В</dd>` : ''}
      <dt>плата</dt><dd>${esc(d.device)}${d.fw ? ' · ' + esc(d.fw) : ''}${d.uptime ? ' · працює ' + uptime(d.uptime) : ''}${v('chip_temp') != null ? ` · чип ${hfix(v('chip_temp'))}°` : ''}</dd>
    </dl>`;
  const chips = [['temp', 'температура']].concat(hkeys(d).filter(k => !k.startsWith('temp.') && k !== 'free_heap').map(k => [k, hname(k)]));
  const ctlHTML = `<div class="hbar">${devs.length > 1 ? `<div class="seg hdevs">${devs.map(x => `<button data-hdev="${esc(x.device)}" class="${x.device === HS.dev ? 'on' : ''}">${esc(x.device)}</button>`).join('')}</div>` : ''}
      <div class="hchips">${chips.map(([k, l]) => `<button class="chip${HS.key === k ? ' on' : ''}" data-hkey="${esc(k)}">${esc(l)}</button>`).join('')}</div>
      <div class="seg hrange">${HRANGES.map(([k, l]) => `<button data-hr="${k}" class="${HS.range === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>`;
  const title = d.device === 'room' ? 'кімната' : d.device;
  if (!$('#hnow')) {
    box.innerHTML = `<div class="cols">${win(title, '', {n: '⁸', id: 'hnow'})}${win('графік', '<div id="hctl"></div><div class="hchart" id="hchart"></div><div class="hlegend" id="hlegend"></div>', {c: 'vio', id: 'hgraph', cls: 'w2'})}</div>
      <div class="cols">${win('події', '', {c: 'yel', id: 'hev', cls: 'w2'})}${win('ключ плати', houseKeyHTML(), {c: 'dim', id: 'hkey'})}</div>`;
    bindHouseKey();
  }
  const set = (sel, html) => { const b = $(sel); if (b && b.dataset.html !== html) { b.innerHTML = html; b.dataset.html = html; return true; } return false; };
  set('#hnow .wbody', nowHTML);
  if (set('#hctl', ctlHTML)) bindHouseGraph();
  drawChart();
  set('#hev .wbody', houseEventsHTML());
}

function bindHouseGraph() {
  $$('[data-hr]').forEach(b => b.onclick = async () => {
    HS.range = b.dataset.hr; localStorage.setItem('hata_hrange', HS.range);
    $$('[data-hr]').forEach(x => x.classList.toggle('on', x === b));
    await houseLoadSeries(); drawHouse();
  });
  $$('[data-hkey]').forEach(b => b.onclick = async () => {
    HS.key = b.dataset.hkey;
    $$('[data-hkey]').forEach(x => x.classList.toggle('on', x === b));
    await houseLoadSeries(); drawHouse();
  });
  $$('[data-hdev]').forEach(b => b.onclick = async () => { HS.dev = b.dataset.hdev; HS.key = 'temp'; $('#hBody').innerHTML = ''; delete $('#hBody').dataset.html; await houseLoadSeries(); drawHouse(); });
}

// Графік: SVG-лінії без бібліотек. Підписи осей — звичайним HTML поверх, щоб не розтягувались разом із SVG.
function drawChart() {
  const el = $('#hchart');
  if (!el) return;
  const keys = Object.keys(HS.series), any = keys.find(k => (HS.series[k].points || []).length);
  const s0 = HS.series[keys[0]] || {};
  const from = s0.from || 0, to = s0.to || 1, W = 1000, H = 300;
  const sig = JSON.stringify([HS.range, HS.key, keys.map(k => (HS.series[k].points || []).length), to - to % 15, HS.ev && HS.ev.events.length]);
  if (el.dataset.sig === sig) return;
  el.dataset.sig = sig;
  if (!any) { el.innerHTML = `<p class="note" style="margin:0;padding:40px 0;text-align:center">За ${HRANGES.find(r => r[0] === HS.range)[1]} замірів немає.</p>`; $('#hlegend').innerHTML = ''; return; }
  let lo = Infinity, hi = -Infinity;
  for (const k of keys) for (const p of HS.series[k].points) { lo = Math.min(lo, p[2] ?? p[1]); hi = Math.max(hi, p[3] ?? p[1]); }
  const temp = HS.key === 'temp';
  const span0 = hi - lo, padY = Math.max(temp ? 0.5 : Math.abs(hi) * 0.05 || 1, span0 * 0.12);
  lo -= padY; hi += padY;
  const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(x => x >= raw);
  lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
  const X = t => (t - from) / (to - from) * W, Y = v => H - (v - lo) / (hi - lo) * H;
  const gapMax = Math.max(90, (s0.step || 15) * 3);
  const path = pts => { let d = '', prev = null; for (const p of pts) { d += (prev && p[0] - prev > gapMax ? ' M' : d ? ' L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); prev = p[0]; } return d; };
  const band = pts => pts.length && pts[0].length > 2 ? 'M' + pts.map(p => `${X(p[0]).toFixed(1)} ${Y(p[3]).toFixed(1)}`).join(' L') + ' L' + pts.slice().reverse().map(p => `${X(p[0]).toFixed(1)} ${Y(p[2]).toFixed(1)}`).join(' L') + ' Z' : '';
  const gaps = (HS.ev ? HS.ev.gaps : []).filter(g => g.to > from).map(g => {
    const a = X(Math.max(from, g.from)), b = X(Math.min(to, g.to));
    return `<rect x="${a.toFixed(1)}" y="0" width="${Math.max(2, b - a).toFixed(1)}" height="${H}" fill="url(#h-${g.kind})" class="hgap ${g.kind}"><title>${g.kind === 'power' ? (g.source === 'wifi_up' ? 'роутер був недоступний (схоже, світло)' : 'не було світла') : 'не було інтернету'}: ${hclock(g.from)}–${g.open ? 'зараз' : hclock(g.to)} (${hdur(g.to - g.from)})</title></rect>`;
  }).join('');
  const boots = (HS.ev ? HS.ev.events : []).filter(e => e.type === 'boot' && e.ts > from).map(e => `<line x1="${X(e.ts).toFixed(1)}" x2="${X(e.ts).toFixed(1)}" y1="0" y2="${H}" class="hboot"><title>плата запустилась ${hclock(e.ts)}</title></line>`).join('');
  const yt = []; for (let v = lo; v <= hi + step / 2; v += step) yt.push(v);
  const tstep = {'1h': 600, '24h': 3 * 3600, '7d': 86400, '30d': 5 * 86400}[HS.range] * (el.clientWidth < 560 ? 2 : 1);
  const tz = new Date().getTimezoneOffset() * 60, xt = [];
  for (let t = Math.ceil((from - tz) / tstep) * tstep + tz; t <= to; t += tstep) xt.push(t);
  const xl = t => HS.range === '7d' ? new Date(t * 1000).toLocaleDateString('uk-UA', {weekday: 'short', day: 'numeric'}) : HS.range === '30d' ? new Date(t * 1000).toLocaleDateString('uk-UA', {day: 'numeric', month: 'numeric'}) : hclock(t);
  const lines = keys.map((k, i) => { const pts = HS.series[k].points || []; return `<path d="${band(pts)}" class="hband" style="--c:var(--${HCOL[i % 4]})"/><path d="${path(pts)}" class="hline" style="--c:var(--${HCOL[i % 4]})"/>`; }).join('');
  el.innerHTML = `<div class="hplot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <defs><pattern id="h-power" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" class="hp-bg power"/><line x1="0" y1="0" x2="0" y2="8" class="hp power"/></pattern>
        <pattern id="h-inet" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="8" height="8" class="hp-bg inet"/><line x1="0" y1="0" x2="0" y2="8" class="hp inet"/></pattern></defs>
      ${yt.map(v => `<line x1="0" x2="${W}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" class="hgrid"/>`).join('')}${gaps}${boots}${lines}
      <line class="hcur" id="hcur" x1="0" x2="0" y1="0" y2="${H}" visibility="hidden"/></svg>
    ${yt.map(v => `<span class="hy" style="top:${(Y(v) / H * 100).toFixed(2)}%">${hfix(v, HS.key)}</span>`).join('')}
    ${xt.map(t => `<span class="hx" style="left:${(X(t) / W * 100).toFixed(2)}%">${esc(xl(t))}</span>`).join('')}
    <div class="htip" id="htip" hidden></div></div>`;
  const leg = keys.map((k, i) => `<span><i style="background:var(--${HCOL[i % 4]})"></i>${esc(hname(k))}${hunit(k) ? ', ' + hunit(k) : ''}</span>`);
  const kinds = new Set((HS.ev ? HS.ev.gaps : []).filter(g => g.to > from).map(g => g.kind));
  if (kinds.has('power')) leg.push('<span><i class="hsw power"></i>без світла</span>');
  if (kinds.has('inet')) leg.push('<span><i class="hsw inet"></i>без інтернету</span>');
  $('#hlegend').innerHTML = leg.join('');
  // підказка під курсором / пальцем
  const plot = $('.hplot', el), tip = $('#htip'), cur = $('#hcur');
  const show = e => {
    const r = plot.getBoundingClientRect(), x = Math.min(Math.max(0, (e.clientX - r.left) / r.width), 1), t = from + x * (to - from);
    const rows = keys.map((k, i) => { const pts = HS.series[k].points || []; let best = null; for (const p of pts) if (!best || Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      return best && Math.abs(best[0] - t) < gapMax ? `<span style="color:var(--${HCOL[i % 4]})">${esc(hname(k))}</span> ${hfix(best[1], k)}${hunit(k).startsWith('°') ? '°' : ' ' + hunit(k)}` : ''; }).filter(Boolean);
    if (!rows.length) { tip.hidden = true; cur.setAttribute('visibility', 'hidden'); return; }
    cur.setAttribute('x1', x * W); cur.setAttribute('x2', x * W); cur.setAttribute('visibility', 'visible');
    tip.hidden = false;
    tip.innerHTML = `<b>${HS.range === '1h' || HS.range === '24h' ? hclock(t) : new Date(t * 1000).toLocaleString('uk-UA', {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'})}</b>${rows.join('<br>')}`;
    tip.style.left = Math.min(r.width - tip.offsetWidth - 4, Math.max(4, x * r.width + 12)) + 'px';
  };
  plot.onpointermove = show;
  plot.onpointerdown = show;
  plot.onpointerleave = () => { tip.hidden = true; cur.setAttribute('visibility', 'hidden'); };
}

function houseEventsHTML() {
  const ev = (HS.ev ? HS.ev.events : []).slice().reverse().slice(0, 12);
  if (!ev.length) return `<p class="note" style="margin:0">За ${HRANGES.find(r => r[0] === HS.range)[1]} без пригод: світло й інтернет були весь час.</p>`;
  const text = e => ({
    power_off: ['red', 'зникло світло'], power_on: ['acc', `світло повернулось${e.duration ? ` · не було ${hdur(e.duration)}` : ''}`],
    inet_down: ['red', 'зник інтернет'], inet_up: ['acc', `інтернет повернувся${e.duration ? ` · не було ${hdur(e.duration)}` : ''}`],
    wifi_up: ['yel', `роутер знову на зв’язку${e.duration ? ` · не було ${hdur(e.duration)} (схоже, вимикали світло)` : ''}`],
    wifi_down: ['red', 'роутер недоступний'], boot: ['dim', `плата запустилась${e.duration ? ` · була вимкнена ${hdur(e.duration)}` : ''}`]})[e.type] || ['dim', e.type];
  const day = t => new Date(t * 1000).toLocaleDateString('uk-UA', {day: 'numeric', month: 'short'});
  return `<ol class="log hlog">${ev.map(e => { const [c, s] = text(e); return `<li><span class="t">${HS.range === '1h' || HS.range === '24h' ? '' : day(e.ts) + ' '}${hclock(e.ts)}</span><span class="u" style="color:var(--${c})">●</span><span>${esc(s)}</span></li>`; }).join('')}</ol>`;
}

function houseKeyHTML() {
  const k = HS.keyInfo || {};
  return `<p class="note" style="margin:0 0 10px">Плата надсилає заміри з цим ключем. Впиши його в скетч RoomMonitor і прошей плату.</p>
    <pre class="hcode" id="hcode">const char* HATA_URL = "${esc(k.url || '')}";
const char* HATA_KEY = "${esc(k.key || '')}";</pre>
    <div class="acts" style="margin-top:12px"><button class="btn" id="hcopy">Скопіювати</button><span class="sp"></span><button class="btn danger" id="hnew">Новий ключ</button></div>`;
}

function bindHouseKey() {
  if ($('#hcopy')) $('#hcopy').onclick = async () => {
    try { await navigator.clipboard.writeText($('#hcode').textContent); toast('Скопійовано'); }
    catch (e) { const r = document.createRange(); r.selectNodeContents($('#hcode')); getSelection().removeAllRanges(); getSelection().addRange(r); toast('Виділено — натисни Ctrl+C'); }
  };
  if ($('#hnew')) $('#hnew').onclick = async () => {
    if (!confirm('Створити новий ключ? Плата перестане надсилати заміри, поки не впишеш новий ключ і не прошиєш її.')) return;
    const r = await api('/api/house/key', {op: 'new'});
    if (r.ok) { HS.keyInfo = {...HS.keyInfo, key: r.key}; const b = $('#hkey .wbody'); b.innerHTML = houseKeyHTML(); delete b.dataset.html; bindHouseKey(); toast('Новий ключ готовий'); }
  };
}

// Клавіші 1–6 — до розділу панелі, як у btop.
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey || typing() || !$('.top nav a[data-k]')) return;
  if (/^[1-8]$/.test(e.key)) goSection(e.key);
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && $('#cpuG')) live(); });

start();
