'use strict';
// Hata: майстер першого налаштування і панель сервера. Без бібліотек і збирачів.

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const app = $('#app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const size = b => { if (!b) return '0'; const u = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']; let i = 0; while (b >= 1024 && i < 4) { b /= 1024; i++; } return (b >= 100 || i < 3 ? Math.round(b) : b.toFixed(1)).toString().replace('.', ',') + ' ' + u[i]; };
const uptime = s => { const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60); return d ? `${d} д ${h} год` : h ? `${h} год ${m} хв` : `${m} хв`; };
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

const prompt = (path, cmd) => `<p class="prompt"><span class="u">[hata@${esc(HOST)} ${esc(path)}]$</span> <span class="c">${esc(cmd)}</span><span class="cur"></span></p>`;
const win = (path, body, bold = '') => `<section class="win"><div class="wbar"><i></i><i></i><i></i><span>${esc(path)}<b>${esc(bold)}</b></span></div><div class="wbody">${body}</div></section>`;
const meter = (used, total) => { const p = total ? Math.round(used / total * 100) : 0; return `<div class="meter"><i class="${p > 90 ? 'bad' : p > 75 ? 'warn' : ''}" style="width:${p}%"></i></div>`; };

// ───────────────────────── старт ─────────────────────────
let STATE = null;
async function start() {
  STATE = await api('/api/state');
  if (STATE.ok === false && !STATE.setup) { app.innerHTML = win('~/', `<p>Сервер Hata не відповідає. Спробуй оновити сторінку за хвилину.</p>`); return; }
  HOST = STATE.host || 'hata';
  $('#hostTag').textContent = HOST + (STATE.demo ? ' · демо' : '');
  document.title = STATE.setup ? `Hata — ${HOST}` : 'Hata — налаштування';
  if (STATE.hasPassword && !STATE.authed) return login();
  if (!STATE.setup) return wizard(STATE.hasPassword ? Math.max(W.step, 2) : W.step);
  return panel();
}

function login() {
  app.innerHTML = prompt('~', 'login') + `<h1 class="title">Вхід</h1><p class="lead">Пароль, який ти задав під час налаштування Hata.</p>` +
    win('~/', `<form id="lf"><label class="f" for="pw">пароль</label><input id="pw" type="password" autocomplete="current-password" autofocus>
      <div class="err" id="le"></div><div class="acts"><button class="btn primary">Увійти</button></div></form>`, 'login');
  $('#lf').onsubmit = async e => {
    e.preventDefault();
    const r = await api('/api/login', {password: $('#pw').value});
    if (r.ok) start(); else $('#le').textContent = r.error || 'Не вдалося увійти';
  };
}

// ───────────────────────── майстер ─────────────────────────
const STEPS = ['вітання', 'пароль', 'диски', 'папки', 'tailscale', 'ноутбук', 'готово'];
const W = Object.assign({step: 0, folders: [], anime: ''}, JSON.parse(sessionStorage.getItem('hata_wiz') || '{}'));
const saveW = () => sessionStorage.setItem('hata_wiz', JSON.stringify(W));

function frame(i, title, lead, body) {
  const steps = STEPS.map((s, k) => `<span class="${k === i ? 'on' : k < i ? 'done' : ''}">${k < i ? '✓ ' : ''}${s}</span>`).join('');
  return prompt('~/setup', `hata-setup --step ${i + 1}/${STEPS.length}`) + `<div class="steps">${steps}</div>` +
    `<h1 class="title">${title}</h1><p class="lead">${lead}</p>` + body;
}

function wizard(i) {
  W.step = i; saveW();
  ({0: stepHello, 1: stepPassword, 2: stepDisks, 3: stepFolders, 4: stepTailscale, 5: stepLaptop, 6: stepDone})[i]();
  window.scrollTo(0, 0);
}
const next = () => wizard(W.step + 1);
const back = () => wizard(Math.max(STATE.hasPassword ? 2 : 0, W.step - 1));
const nav = (nextLabel = 'Далі', extra = '') => `<div class="acts">${W.step > (STATE.hasPassword ? 2 : 0) ? '<button class="btn ghost" id="back">Назад</button>' : ''}<span class="sp"></span>${extra}<button class="btn primary" id="next">${nextLabel}</button></div>`;
function bindNav(onNext) {
  if ($('#back')) $('#back').onclick = back;
  $('#next').onclick = onNext || next;
}

function stepHello() {
  app.innerHTML = frame(0, 'Привіт, це Hata', 'Твій домашній сервер майже готовий. Кілька кроків — і він сам підключить диски, запустить VidBox і, якщо захочеш, буде доступний звідусіль через Tailscale.',
    win('~/setup/', `<dl class="kv"><dt>сервер</dt><dd>${esc(HOST)}</dd><dt>адреса</dt><dd>${esc(location.host)}</dd><dt>кроки</dt><dd>пароль → диски → папки → Tailscale → ноутбук</dd></dl>
      <p class="note">Будь-який крок можна змінити пізніше в панелі.</p>`, 'readme') + nav('Почати'));
  bindNav();
}

function stepPassword() {
  app.innerHTML = frame(1, 'Пароль', 'Один пароль на все: панель Hata, VidBox і Android-апку. Кожен пристрій вводить його один раз.',
    win('~/setup/', `<form id="pf"><label class="f" for="p1">новий пароль</label><input id="p1" type="password" autocomplete="new-password" autofocus>
      <label class="f" for="p2">ще раз</label><input id="p2" type="password" autocomplete="new-password">
      <div class="err" id="pe"></div></form>`, 'password') + nav('Зберегти'));
  bindNav(async () => {
    const a = $('#p1').value, b = $('#p2').value;
    if (a.length < 6) return $('#pe').textContent = 'Щонайменше 6 символів';
    if (a !== b) return $('#pe').textContent = 'Паролі не збігаються';
    const r = await api('/api/setup/password', {password: a});
    if (!r.ok) return $('#pe').textContent = r.error;
    STATE.hasPassword = true; STATE.authed = true;
    next();
  });
  $('#pf').onsubmit = e => { e.preventDefault(); $('#next').click(); };
}

async function stepDisks() {
  app.innerHTML = frame(2, 'Диски', 'Обери диски з фільмами й аніме. Hata підключатиме їх сама після кожного вмикання — за назвою, тож шляхи не зміняться, навіть якщо переставиш кабелі.',
    win('~/setup/', '<p class="note"><span class="spin"></span> Шукаю диски…</p>', 'disks') + nav());
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
  }).join('') : '<p class="note">Дисків з даними не знайдено. Підключи диск і натисни «Оновити».</p>';
  $('.win .wbody').innerHTML = body + `<div class="err" id="de"></div><div class="acts"><button class="btn ghost" id="rescan">Оновити список</button></div>`;
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
    win('~/setup/', chosen ? chosen : '<p class="note">Поки нічого не вибрано.</p>', 'library') +
    win('~/setup/', `<div class="crumbs">${esc(r.path || 'диски')}</div>${dirs}${here}<div class="err" id="fe"></div>`, 'browse') + nav());
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

let tsTimer, tsFromPanel = false;
async function stepTailscale() {
  clearTimeout(tsTimer);
  const st = await api('/api/tailscale');
  const running = st.state === 'Running';
  const body = running
    ? `<p><span class="okdot"></span>Підключено як <b class="link">${esc(st.name)}</b></p><p class="note">Тепер VidBox і панель доступні звідусіль, де на пристрої ввімкнено Tailscale.</p>`
    : st.url
      ? `<p>Відкрий посилання й увійди у свій акаунт Tailscale — і сервер з'явиться у твоїй мережі:</p><p><a class="btn primary" href="${esc(st.url)}" target="_blank" rel="noopener">Увійти в Tailscale</a></p><p class="note link">${esc(st.url)}</p><p class="note"><span class="spin"></span> Чекаю на вхід…</p>`
      : `<p>Tailscale — приватна мережа між твоїми пристроями. З ним VidBox працює не лише вдома, а й з мобільного інтернету, без відкритих портів на роутері.</p><div class="acts"><button class="btn" id="tsUp">Підключити Tailscale</button></div><div class="err" id="te"></div>`;
  app.innerHTML = frame(4, 'Доступ звідусіль', 'Необов’язково — можна пропустити й увімкнути пізніше в панелі.', win('~/setup/', body, 'tailscale') + nav(running ? 'Далі' : 'Пропустити'));
  bindNav(() => { clearTimeout(tsTimer); next(); });
  if (tsFromPanel) {   // відкрили з панелі: без кроків майстра, «Далі» веде назад у панель
    $('.steps').remove(); if ($('#back')) $('#back').remove();
    $('#next').textContent = 'До панелі';
    $('#next').onclick = () => { clearTimeout(tsTimer); tsFromPanel = false; panel(); };
  }
  if ($('#tsUp')) $('#tsUp').onclick = async () => {
    $('#tsUp').disabled = true; $('#tsUp').innerHTML = '<span class="spin"></span> Встановлюю й запускаю…';
    const r = await api('/api/tailscale', {op: 'up'});
    if (r.ok === false) { $('#te').textContent = r.error; $('#tsUp').disabled = false; $('#tsUp').textContent = 'Спробувати ще'; return; }
    stepTailscale();
  };
  if (!running && st.url) tsTimer = setTimeout(() => { if (W.step === 4 || tsFromPanel) stepTailscale(); }, 3000);
}

async function stepLaptop() {
  const st = await api('/api/status');
  const b = st.battery;
  const lim = b && b.limitSupported ? `<div class="row"><div class="l"><b>Межа заряду батареї</b><small>Ноутбук весь час на зарядці — з межею 60–80% батарея живе в рази довше.</small></div>
     <div class="r"><div class="seg" id="lim">${[60, 80, 100].map(v => `<button data-v="${v}" class="${(b.limit || 100) === v ? 'on' : ''}">${v}%</button>`).join('')}</div></div></div>` : '';
  app.innerHTML = frame(5, 'Ноутбук', 'Сервер працює й із закритою кришкою — Hata вже це налаштувала.',
    win('~/setup/', `<div class="row"><div class="l"><b>Закрита кришка</b><small>Ноутбук не засинає, екран гасне.</small></div><div class="r"><span class="tag ok">увімкнено</span></div></div>` +
      (b ? lim + `<div class="row"><div class="l"><b>Батарея</b><small>${b.ac ? 'від мережі' : 'від батареї'}</small></div><div class="r"><span class="tag">${b.pct}%</span></div></div>`
         : `<div class="row"><div class="l"><b>Батарея</b><small>Не знайдено — схоже, це стаціонарний ПК.</small></div></div>`), 'laptop') + nav());
  bindNav();
  $$('#lim button').forEach(x => x.onclick = async () => {
    const r = await api('/api/battery', {value: +x.dataset.v});
    if (!r.ok) return toast(r.error);
    $$('#lim button').forEach(y => y.classList.toggle('on', y === x)); toast(`Межа заряду: ${x.dataset.v}%`);
  });
}

function stepDone() {
  app.innerHTML = frame(6, 'Готово', 'Перевір і натисни «Завершити» — Hata запустить VidBox з твоїми папками.',
    win('~/setup/', `<dl class="kv"><dt>відео</dt><dd>${W.folders.map(esc).join('<br>') || '—'}</dd><dt>аніме</dt><dd>${esc(W.anime) || 'не вибрано'}</dd><dt>пароль</dt><dd>встановлено</dd></dl><div class="err" id="ce"></div>`, 'summary') + nav('Завершити'));
  bindNav(async () => {
    $('#next').disabled = true; $('#next').innerHTML = '<span class="spin"></span> Запускаю…';
    const r = await api('/api/finish', {folders: W.folders, anime: W.anime});
    if (!r.ok) { $('#ce').textContent = r.error || 'Не вдалося'; $('#next').disabled = false; $('#next').textContent = 'Завершити'; return; }
    sessionStorage.removeItem('hata_wiz');
    STATE.setup = true; toast('Hata налаштована');
    panel();
  });
}

// ───────────────────────── панель ─────────────────────────
let panelTimer;
async function panel() {
  clearTimeout(panelTimer);
  const s = await api('/api/status');
  if (s.ok === false) { app.innerHTML = prompt('~', 'gazda status') + win('~/', `<p class="err">${esc(s.error)}</p>`, 'error'); return; }
  const vb = `${location.protocol}//${location.hostname}:${s.vidbox.port}`;
  const svc = (n, t) => { const on = s.services[n] === 'active'; return `<div class="row"><div class="l"><b><span class="okdot ${on ? '' : 'off'}"></span>${t}</b><small>${esc(s.services[n] || '—')}</small></div><div class="r"><button class="btn ghost" data-svc="${n}">Перезапустити</button></div></div>`; };
  const ts = s.tailscale || {};
  const bat = s.battery ? `${s.battery.pct}% · ${s.battery.ac ? 'від мережі' : 'від батареї'}${s.battery.limit && s.battery.limit < 100 ? ` · межа ${s.battery.limit}%` : ''}` : '—';
  const used = s.mem.total - s.mem.avail;
  app.innerHTML = prompt('~', 'gazda status') + `<h1 class="title">${esc(s.host)}</h1><p class="lead">${esc(s.os)} · працює ${uptime(s.uptime)}</p>` +
    `<div class="acts" style="margin:-8px 0 18px"><a class="btn primary" href="${vb}">Відкрити VidBox</a></div>` +
    '<div class="grid">' +
    win('~/', `<dl class="kv"><dt>процесор</dt><dd>${s.cpus} ядер · навантаження ${s.load.toFixed(2).replace('.', ',')}</dd>
      <dt>температура</dt><dd>${s.temp != null ? s.temp.toString().replace('.', ',') + ' °C' : '—'}</dd>
      <dt>пам’ять</dt><dd>${size(used)} з ${size(s.mem.total)}${meter(used, s.mem.total)}</dd>
      <dt>батарея</dt><dd>${bat}</dd><dt>версія</dt><dd>${esc(s.version || '—')}</dd></dl>`, 'system') +
    win('~/', ([{name: 'система', path: '/', mounted: true, ...(s.root || {})}].concat(s.disks)).map(d => `<div class="row"><div class="l"><b>${esc(d.name)}</b>
      <small>${d.mounted ? `${size(d.total - d.free)} з ${size(d.total)} · вільно ${size(d.free)}` : 'не підключено'}</small>${d.mounted ? meter(d.total - d.free, d.total) : ''}</div>
      ${d.mounted ? '' : '<div class="r"><span class="tag bad">відключено</span></div>'}</div>`).join(''), 'disks') +
    win('~/', svc('vidbox', 'VidBox') + svc('hata-screen', 'Екран ноутбука'), 'services') +
    win('~/', `<dl class="kv"><dt>вдома</dt><dd>${(s.ips || []).map(esc).join(', ') || '—'}</dd>
      <dt>tailscale</dt><dd>${ts.state === 'Running' ? `<span class="okdot"></span>${esc(ts.name)}` : ts.installed ? 'не підключено' : 'не встановлено'}</dd></dl>
      ${ts.state === 'Running' ? '' : '<div class="acts"><button class="btn" id="tsOn">Підключити Tailscale</button></div>'}`, 'network') +
    '</div>' +
    win('~/', `<div class="acts" style="margin-top:0"><button class="btn" id="upd">Оновити Hata і VidBox</button><span class="sp"></span>
      <button class="btn danger" data-power="reboot">Перезавантажити</button><button class="btn danger" data-power="poweroff">Вимкнути</button></div>
      <p class="note">Оновлення беруть нову версію з GitHub; якщо вона не запуститься, Hata сама повернеться на попередню.</p>`, 'actions');
  $$('[data-svc]').forEach(b => b.onclick = async () => { b.disabled = true; const r = await api('/api/service', {name: b.dataset.svc, op: 'restart'}); toast(r.ok ? 'Перезапущено' : r.error); panel(); });
  $$('[data-power]').forEach(b => b.onclick = async () => {
    const off = b.dataset.power === 'poweroff';
    if (!confirm(off ? 'Вимкнути сервер? Увімкнути знову можна лише кнопкою на ноутбуці.' : 'Перезавантажити сервер? Він повернеться за хвилину-дві.')) return;
    const r = await api('/api/power', {op: b.dataset.power});
    toast(r.ok ? (off ? 'Вимикаю…' : 'Перезавантажую…') : r.error);
  });
  $('#upd').onclick = async () => {
    $('#upd').disabled = true; $('#upd').innerHTML = '<span class="spin"></span> Оновлюю…';
    const r = await api('/api/update', {});
    toast(!r.ok ? r.error : r.changed ? `Оновлено до ${r.version}` : 'Уже встановлено останню версію');
    setTimeout(panel, r.changed ? 4000 : 0);
  };
  if ($('#tsOn')) $('#tsOn').onclick = () => { W.step = 4; stepTailscaleFromPanel(); };
  panelTimer = setTimeout(() => { if (STATE.setup && !document.hidden) panel(); }, 15000);
}

async function stepTailscaleFromPanel() {
  clearTimeout(panelTimer);
  tsFromPanel = true;
  await stepTailscale();
}

start();
