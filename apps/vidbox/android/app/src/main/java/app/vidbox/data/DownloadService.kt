package app.vidbox.data

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.vidbox.MainActivity
import app.vidbox.VidBoxApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Тримає процес живим, поки качаються відео (екран вимкнено, апку згорнуто), і показує прогрес у шторці. */
class DownloadService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var loop: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(
            NotificationChannel(CH, "Завантаження відео", NotificationManager.IMPORTANCE_LOW))
        ServiceCompat.startForeground(this, ID, build("Завантажую відео…", 0),
            if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
        if (loop?.isActive != true) loop = scope.launch {
            val dl = (application as VidBoxApp).dl
            while (true) {
                val run = dl.items.values.filter { dl.running(it.v.id) }
                if (run.isEmpty()) break
                val d = run.first()
                val text = d.note ?: "${(d.progress * 100).toInt()}% · ${Fmt.size(d.bytes)} з ${Fmt.size(d.total)}"
                nm.notify(ID, build((if (run.size > 1) "${run.size} відео · " else "") + d.v.title + "\n" + text,
                    if (d.note == null) (d.progress * 100).toInt() else -1))
                delay(1500)
            }
            ServiceCompat.stopForeground(this@DownloadService, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun build(text: String, pct: Int) = NotificationCompat.Builder(this, CH)
        .setSmallIcon(android.R.drawable.stat_sys_download)
        .setContentTitle(text.substringBefore('\n'))
        .setContentText(text.substringAfter('\n', ""))
        .setOngoing(true).setOnlyAlertOnce(true).setSilent(true)
        .setProgress(100, pct.coerceAtLeast(0), pct < 0)
        .setContentIntent(PendingIntent.getActivity(this, 0,
            Intent(this, MainActivity::class.java).putExtra("route", "downloads").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        .build()

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val CH = "downloads"
        private const val ID = 4207
        fun start(ctx: Context) = runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, DownloadService::class.java)) }
    }
}

private fun CoroutineScope.cancel() = coroutineContext[Job]?.cancel()
