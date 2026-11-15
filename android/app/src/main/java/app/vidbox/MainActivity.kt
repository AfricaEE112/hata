package app.vidbox

import android.app.PictureInPictureParams
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.util.Rational
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.lifecycle.Lifecycle
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.vidbox.player.PlaybackService
import app.vidbox.player.PlayerHolder
import app.vidbox.ui.App
import com.google.common.util.concurrent.ListenableFuture

class MainActivity : ComponentActivity() {
    private val vm: AppVM by viewModels()
    private var controller: ListenableFuture<MediaController>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        addOnPictureInPictureModeChangedListener { info ->
            vm.pip = info.isInPictureInPictureMode
            // вікно «картинка в картинці» закрили хрестиком → зупиняємо
            if (!info.isInPictureInPictureMode && !lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) PlayerHolder.peek()?.pause()
        }
        handle(intent)
        setContent { App(vm, this) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** Відкрити екран з ярлика чи команди: route = lib, pl, pl/short, top, settings, i/<id>, v/<id>. */
    private fun handle(i: Intent?) {
        val r = i?.getStringExtra("route") ?: return
        if (!vm.connected) return
        val parts = r.trim('/').split('/')
        when (parts[0]) {
            "lib" -> vm.nav.go(Lib)
            "pl" -> if (parts.size > 1) {
                vm.nav.go(Playlists)
                vm.nav.go(Playlist(parts[1]))
            } else vm.nav.go(Playlists)
            "top" -> vm.nav.go(Top)
            "settings" -> vm.nav.go(Settings)
            "i" -> if (parts.size > 1) vm.nav.go(Info(parts[1]))
            "v" -> if (parts.size > 1) vm.nav.go(Player(parts[1]))
            "random" -> vm.openRandom()
            else -> vm.nav.go(Home)
        }
    }

    override fun onStart() {
        super.onStart()
        vm.foreground = true
    }

    override fun onStop() {
        super.onStop()
        vm.foreground = false
        val p = PlayerHolder.peek() ?: return
        if (vm.pip || !vm.prefs.bgAudio) p.pause()
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        // на Android 12+ вікно PiP вмикається само (setAutoEnterEnabled), на старших — тут
        if (Build.VERSION.SDK_INT < 31 && vm.nav.top is Player && PlayerHolder.peek()?.isPlaying == true) enterPip()
    }

    fun pipParams(auto: Boolean): PictureInPictureParams {
        val p = PlayerHolder.peek()
        val vs = p?.videoSize
        val w = vs?.width?.takeIf { it > 0 } ?: 16
        val h = vs?.height?.takeIf { it > 0 } ?: 9
        val r = (w.toFloat() / h).coerceIn(0.42f, 2.38f)
        val b = PictureInPictureParams.Builder().setAspectRatio(Rational((r * 1000).toInt(), 1000))
        if (Build.VERSION.SDK_INT >= 31) b.setAutoEnterEnabled(auto).setSeamlessResizeEnabled(true)
        return b.build()
    }

    fun enterPip() {
        runCatching { enterPictureInPictureMode(pipParams(true)) }
    }

    fun setPipAuto(auto: Boolean) {
        runCatching { setPictureInPictureParams(pipParams(auto)) }
    }

    /** Під'єднуємось до сервісу відтворення: так з'являються кнопки в шторці й звук у фоні. */
    fun bindPlayback() {
        if (controller != null) return
        controller = MediaController.Builder(this, SessionToken(this, ComponentName(this, PlaybackService::class.java))).buildAsync()
    }

    override fun onDestroy() {
        controller?.let { MediaController.releaseFuture(it) }
        controller = null
        super.onDestroy()
    }
}
