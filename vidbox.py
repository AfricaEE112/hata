# Сумісність: VidBox тепер — застосунок Hata і живе в apps/vidbox/.
# Цей файл лише запускає його, щоб старі ярлики, start.bat і кнопка «Оновити» продовжили працювати.
# Python і ffmpeg, завантажені раніше в цю теку, теж підхоплюються.
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, 'apps', 'vidbox', 'vidbox.py')
os.environ['PATH'] = os.pathsep.join([ROOT, os.path.join(ROOT, 'ffmpeg'), os.path.join(ROOT, 'ffmpeg', 'bin'),
                                      os.environ.get('PATH', '')])
sys.argv[0] = APP
runpy.run_path(APP, run_name='__main__')
