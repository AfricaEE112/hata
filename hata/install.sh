#!/usr/bin/env bash
# Hata — встановлення на чистий Ubuntu Server 24.04 (або Debian 12/13).
#
#   git clone https://github.com/AfricaEE112/vidbox && sudo vidbox/hata/install.sh
#
# Скрипт можна запускати повторно: він доставить відсутнє й оновить код, нічого не зламавши.
# Після встановлення на екрані ноутбука з'явиться QR-код — далі все в браузері (майстер налаштування).
#
# Змінні (необов'язково):
#   HATA_HOSTNAME=hata   ім'я сервера в мережі (hata.local); keep — не змінювати
#   HATA_REPO=…          звідки оновлюватись (типово — GitHub-репозиторій, з якого запущено)
set -euo pipefail

[ "$(id -u)" = 0 ] || exec sudo -E bash "$0" "$@"

say()  { printf '\n\033[1;36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*"; exit 1; }

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC=/opt/hata/src
DATA=/var/lib/hata
HOST_NEW="${HATA_HOSTNAME:-hata}"
export DEBIAN_FRONTEND=noninteractive

. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) die "Hata розрахована на Ubuntu Server або Debian, а тут $PRETTY_NAME" ;; esac

# ── пакети ──
say "Встановлюю пакети (python3, ffmpeg, avahi, qrencode, драйвери відео)…"
apt-get update -q
apt-get install -y -q --no-install-recommends \
  python3 git ca-certificates curl ffmpeg qrencode avahi-daemon libnss-mdns console-setup kbd \
  exfatprogs smartmontools unattended-upgrades vainfo
if grep -qsi 0x8086 /sys/class/drm/card*/device/vendor; then
  # відеоядро Intel: апаратне декодування HEVC/AV1 для VidBox (VAAPI)
  apt-get install -y -q --no-install-recommends intel-media-va-driver-non-free \
    || apt-get install -y -q --no-install-recommends intel-media-va-driver \
    || warn "Драйвер Intel VAAPI не встановився — VidBox перекодовуватиме процесором"
fi

# ── користувач і теки ──
say "Створюю користувача hata і теки…"
getent group render >/dev/null || groupadd --system render
id hata >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin hata
usermod -aG video,render hata
install -d -o hata -g hata -m 750 "$DATA" "$DATA/vidbox"
install -d -o root -g root -m 755 /srv/disks /opt/hata

# ── код (належить root: панель не може змінити те, що виконує gazda) ──
say "Копіюю код Hata і VidBox у $SRC…"
ORIGIN="${HATA_REPO:-$(git -C "$HERE" remote get-url origin 2>/dev/null || echo https://github.com/AfricaEE112/vidbox.git)}"
BRANCH="$(git -C "$HERE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
[ "$BRANCH" = HEAD ] && BRANCH=main
if [ ! -d "$SRC/.git" ]; then
  if [ -d "$HERE/.git" ]; then
    git clone -q --no-hardlinks "$HERE" "$SRC"
    git -C "$SRC" checkout -q "$(git -C "$HERE" rev-parse HEAD)" -B "$BRANCH"
    git -C "$SRC" remote set-url origin "$ORIGIN"
    git -C "$SRC" fetch -q origin "$BRANCH" 2>/dev/null && git -C "$SRC" branch -q -u "origin/$BRANCH" || true
  else
    git clone -q -b "$BRANCH" "$ORIGIN" "$SRC"
  fi
else
  git -C "$SRC" pull -q --ff-only || warn "Не вдалося оновити код (немає мережі?) — лишаю поточну версію"
fi
chown -R root:root /opt/hata
chmod -R go-w /opt/hata
ln -sf "$SRC/hata/gazda.py" /usr/local/bin/gazda
chmod 755 "$SRC/hata/gazda.py"

# ── ноутбук: працювати з закритою кришкою, гасити екран ──
say "Налаштовую ноутбук: закрита кришка не присипляє сервер…"
install -d /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/hata.conf <<'EOF'
# Hata: сервер працює й із закритою кришкою
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
EOF
systemctl kill -s HUP systemd-logind 2>/dev/null || true
# не засинати взагалі (на сервері ці стани не потрібні)
systemctl mask -q sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true

# шрифт консолі з кирилицею і великими літерами (екран статусу)
if [ -f /etc/default/console-setup ]; then
  sed -i -e 's/^CODESET=.*/CODESET="Uni2"/' -e 's/^FONTFACE=.*/FONTFACE="Terminus"/' -e 's/^FONTSIZE=.*/FONTSIZE="12x24"/' /etc/default/console-setup
  setupcon --force >/dev/null 2>&1 || true
fi

# ── ім'я в мережі: hata.local ──
if [ "$HOST_NEW" != keep ] && [ "$(hostname)" != "$HOST_NEW" ]; then
  say "Ім'я сервера в мережі: $HOST_NEW.local"
  hostnamectl set-hostname "$HOST_NEW" || true
  grep -q "127.0.1.1" /etc/hosts && sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOST_NEW/" /etc/hosts || echo -e "127.0.1.1\t$HOST_NEW" >> /etc/hosts
fi
systemctl enable -q --now avahi-daemon 2>/dev/null || true

# ── автоматичні оновлення безпеки Ubuntu (великі оновлення — лише кнопкою в панелі) ──
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# ── файрвол: лише якщо його вже ввімкнено (за замовчуванням в Ubuntu вимкнений) ──
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  say "Відкриваю порти Hata у файрволі…"
  ufw allow 80/tcp >/dev/null; ufw allow 8800/tcp >/dev/null; ufw allow 48800/udp >/dev/null
fi

# ── служби ──
say "Запускаю служби…"
install -m 644 "$SRC"/hata/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q --now gazda.service
systemctl enable -q hata.service hata-screen.service
systemctl restart hata.service hata-screen.service
if python3 -c "import json,sys; sys.exit(0 if json.load(open('$DATA/hata.json')).get('setup_done') else 1)" 2>/dev/null; then
  systemctl enable -q vidbox.service && systemctl restart vidbox.service
fi

# ── перевірка й адреса ──
for i in $(seq 1 30); do curl -fs http://127.0.0.1/api/ping >/dev/null && break; sleep 1; done
curl -fs http://127.0.0.1/api/ping >/dev/null || die "Панель Hata не запустилась. Подивись: journalctl -u hata -n 50"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
URL="http://${IP:-$(hostname).local}/"
say "Готово! Відкрий на телефоні чи ПК:"
printf '\n    \033[1;36m%s\033[0m   або  http://%s.local/\n\n' "$URL" "$(hostname)"
qrencode -t ANSIUTF8 -m 2 "$URL" 2>/dev/null || true
echo "Той самий QR-код тепер і на екрані ноутбука. Далі — майстер у браузері."
