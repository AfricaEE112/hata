package app.vidbox.player

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import app.vidbox.VidBoxApp

/**
 * Один плеєр на всю апку. ExoPlayer сам грає MKV, MP4, WebM, AVI; H.264, HEVC, VP9 і AV1 —
 * апаратно, якщо телефон уміє. Відео тягнеться з ПК тим самим клієнтом, що й API (з токеном).
 */
@OptIn(UnstableApi::class)
object PlayerHolder {
    private var player: ExoPlayer? = null

    fun peek(): ExoPlayer? = player

    fun get(ctx: Context): ExoPlayer = player ?: build(ctx.applicationContext).also { player = it }

    private fun build(ctx: Context): ExoPlayer {
        val app = ctx as VidBoxApp
        val data = DefaultDataSource.Factory(ctx, OkHttpDataSource.Factory(app.api.client))
        val renderers = DefaultRenderersFactory(ctx).setEnableDecoderFallback(true)
        val buffer = DefaultLoadControl.Builder().setBufferDurationsMs(20_000, 60_000, 1_500, 3_000).build()
        return ExoPlayer.Builder(ctx, renderers)
            .setMediaSourceFactory(DefaultMediaSourceFactory(data))
            .setLoadControl(buffer)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .setSeekBackIncrementMs(10_000)
            .setSeekForwardIncrementMs(10_000)
            .build()
    }

    fun release() {
        player?.release()
        player = null
    }
}

/** Сервіс відтворення: кнопки в шторці, на локскріні й навушниках, звук у фоні. */
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        val open = Intent(this, app.vidbox.MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_SINGLE_TOP }
        val pi = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaSession.Builder(this, PlayerHolder.get(this)).setSessionActivity(pi).build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        session?.player?.let {
            it.pause()
            it.stop()
        }
        stopSelf()
    }

    override fun onDestroy() {
        session?.release()
        session = null
        PlayerHolder.release()
        super.onDestroy()
    }
}
