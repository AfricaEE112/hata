package app.vidbox.player

import android.content.Context
import android.content.pm.ActivityInfo
import android.media.AudioManager
import android.net.Uri
import android.provider.Settings
import android.view.WindowManager
import androidx.annotation.OptIn
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.viewModelScope
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Tracks
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import app.vidbox.AppVM
import app.vidbox.Info
import app.vidbox.MainActivity
import app.vidbox.Player
import app.vidbox.data.Fmt
import app.vidbox.data.Prep
import app.vidbox.data.Video
import app.vidbox.ui.Btn
import app.vidbox.ui.Cover
import app.vidbox.ui.Empty
import app.vidbox.ui.Ic
import app.vidbox.ui.Kind
import app.vidbox.ui.LocalPal
import app.vidbox.ui.Meter
import app.vidbox.ui.SpriteFrame
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.mono
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.IOException
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToInt
import androidx.media3.common.Player as MPlayer

/** Облік перегляду для рейтингу й «продовжити» — так само, як на сайті. */
private class Watch {
    var watched = 0.0
    var start: Double? = null
    var last: Double? = null
    var lastPing = 0L
}

private val SPEEDS = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 2f)

private fun speedLabel(s: Float) = (if (s == s.toInt().toFloat()) s.toInt().toString() else s.toString().replace('.', ',')) + "×"

@OptIn(UnstableApi::class)
@Composable
fun PlayerScreen(vm: AppVM, route: Player, activity: MainActivity) {
    val v = vm.byId[route.id]
    if (v == null) {
        Box(Modifier.fillMaxSize().background(Color.Black), contentAlignment = Alignment.Center) {
            if (vm.lib == null) CircularProgressIndicator(color = LocalPal.current.acc)
            else Empty("Відео не знайдено", "Можливо, файл перемістили або видалили з папки на ПК.") { Btn("Назад", { vm.nav.back() }, icon = Ic.back) }
        }
        return
    }
    PlayerBody(vm, route, activity, v)
}

@OptIn(UnstableApi::class)
@Composable
private fun PlayerBody(vm: AppVM, route: Player, activity: MainActivity, v: Video) {
    val p = LocalPal.current
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val player = remember { PlayerHolder.get(ctx) }
    val cfg = vm.lib?.cfg
    val n = vm.spriteN
    val next = remember(route.id) { vm.nextOf(v) }
    val q = remember(route.id) { vm.queueFor(v) }
    val step = vm.prefs.seekStep

    // джерело: raw — оригінал файлу, copy — MP4-копія з ПК, live — перекодування на льоту
    var source by remember { mutableStateOf("raw") }
    var liveH by remember { mutableIntStateOf(0) }
    var offset by remember { mutableLongStateOf(0L) }     // з якої мілісекунди почався потік live
    var extSubs by remember { mutableStateOf<List<app.vidbox.data.ExtSub>?>(null) }   // субтитри-файли з ПК
    var lastUrl by remember { mutableStateOf("") }
    var quality by remember { mutableStateOf(vm.prefs.quality) }
    var picker by remember { mutableStateOf(false) }
    // субтитри з файла (MKV тощо): кнопка «CC» з'являється, лише коли вони є
    var subs by remember { mutableStateOf<List<SubTrack>>(emptyList()) }
    var subsPicker by remember { mutableStateOf(false) }
    fun applySubs(choice: SubTrack?) {      // null — вимкнути
        val b = player.trackSelectionParameters.buildUpon().clearOverridesOfType(C.TRACK_TYPE_TEXT)
        if (choice == null) b.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true)
        else b.setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false).setOverrideForType(TrackSelectionOverride(choice.group, choice.index))
        player.trackSelectionParameters = b.build()
        vm.prefs.subsOff = choice == null
    }
    LaunchedEffect(Unit) {
        player.trackSelectionParameters = player.trackSelectionParameters.buildUpon()
            .clearOverridesOfType(C.TRACK_TYPE_TEXT).setTrackTypeDisabled(C.TRACK_TYPE_TEXT, vm.prefs.subsOff).build()
    }
    var prep by remember { mutableStateOf<Prep?>(null) }
    var failed by remember { mutableStateOf<String?>(null) }
    var playing by remember { mutableStateOf(false) }
    var buffering by remember { mutableStateOf(true) }
    var ended by remember { mutableStateOf(false) }
    var pos by remember { mutableLongStateOf(0L) }
    var dur by remember { mutableLongStateOf((v.dur * 1000).toLong()) }
    var buffered by remember { mutableLongStateOf(0L) }
    var controls by remember { mutableStateOf(true) }
    var touched by remember { mutableLongStateOf(0L) }
    var speed by remember { mutableFloatStateOf(1f) }
    var holding by remember { mutableStateOf(false) }
    var resize by remember { mutableIntStateOf(AspectRatioFrameLayout.RESIZE_MODE_FIT) }
    var bubble by remember { mutableStateOf<Pair<Int, Long>?>(null) }      // (сек, коли) для «+10 с»
    var hud by remember { mutableStateOf<Pair<ImageVector, Float>?>(null) } // гучність / яскравість
    var notice by remember { mutableStateOf<Triple<String, String?, (() -> Unit)?>?>(null) }
    var landscape by remember { mutableStateOf(v.landscape && vm.prefs.autoLandscape) }
    var countdown by remember { mutableIntStateOf(-1) }
    var scrubbing by remember { mutableStateOf(false) }
    val sid = remember { UUID.randomUUID().toString().replace("-", "").take(20) }
    val watch = remember { Watch() }
    val ffmpeg = vm.lib?.ffmpeg == true

    fun poke() {
        controls = true
        touched = System.currentTimeMillis()
    }

    /** Позиція у відео (для live — від початку файлу, а не потоку). */
    fun absPos(): Long = (if (source == "live") offset else 0L) + player.currentPosition

    fun durSec(): Double = if (source != "live" && player.duration > 0) player.duration / 1000.0 else v.dur

    fun ping(isEnd: Boolean) {
        val st = watch.start ?: return
        if (watch.watched < 1 && !isEnd) return
        val d = durSec()
        val at = if (isEnd) d else absPos() / 1000.0
        val o = JSONObject().put("sid", sid).put("id", v.id).put("pos", at).put("dur", d)
            .put("watched", (watch.watched * 10).roundToInt() / 10.0).put("start", st).put("ended", isEnd)
        vm.localPos(v.id, if (isEnd || (d > 0 && at >= d * 0.95)) 0.0 else at)
        watch.lastPing = System.currentTimeMillis()
        vm.viewModelScope.launch { runCatching { vm.api.ping(o) } }
    }

    fun load(url: String, startMs: Long) {
        lastUrl = url
        // live починається не з нуля файлу — там окремі субтитри розійшлися б у часі; з файлу на телефоні — без ПК
        val ext = if (source == "raw" || source == "copy") extSubs.orEmpty() else emptyList()
        val item = MediaItem.Builder().setUri(url).setMediaId(v.id)
            .setSubtitleConfigurations(ext.map { s ->
                MediaItem.SubtitleConfiguration.Builder(Uri.parse(vm.api.url("/subs/${v.id}/${s.n}.vtt")))
                    .setMimeType(MimeTypes.TEXT_VTT).setId("ext${s.n}")
                    .setLanguage(s.lang.ifEmpty { null }).setLabel(if (s.ai) "ШІ" else s.label.ifEmpty { null }).build()
            })
            .setMediaMetadata(
                MediaMetadata.Builder().setTitle(v.title).setArtist(q?.name ?: Fmt.shortFolder(v.folder))
                    .apply { if (v.thumb > 0) setArtworkUri(Uri.parse(vm.api.thumbUrl(v))) }.build(),
            ).build()
        player.setMediaItem(item, startMs.coerceAtLeast(0))
        player.prepare()
        player.playWhenReady = true
    }

    fun playRaw(atMs: Long) {
        source = "raw"
        load(vm.api.streamUrl(v, raw = true), atMs)
    }

    fun playCopy(atMs: Long) {
        source = "copy"
        load(vm.api.streamUrl(v, raw = false), atMs)
    }

    LaunchedEffect(v.id) {
        val got = runCatching { vm.api.extSubs(v.id) }.getOrDefault(emptyList())
        extSubs = got
        // відео вже почало грати без них — перезавантажуємо з тієї ж позиції
        if (got.isNotEmpty() && lastUrl.isNotEmpty() && (source == "raw" || source == "copy")) load(lastUrl, player.currentPosition)
    }

    /** Потік з потрібною висотою кадру; перемотка = новий потік з іншого місця. */
    fun playLive(h: Int, atMs: Long) {
        source = "live"
        liveH = h
        val at = atMs.coerceIn(0L, maxOf(0L, (v.dur * 1000).toLong() - 1000))
        offset = at
        load(vm.api.liveUrl(v, h, at / 1000.0), 0)
    }

    /** Висота для live: не більша за висоту самого відео. */
    fun fitH(want: Int): Int {
        val src = v.resKey
        if (src <= 0) return want
        return listOf(1080, 720, 480).firstOrNull { it <= want && it <= maxOf(src, 480) } ?: 480
    }

    /** Що грати: оригінал чи перекодований потік — за вибором якості й можливостями телефона. */
    fun open(atMs: Long) {
        vm.dl.ready(v.id)?.let { f ->   // завантажене на телефон — граємо з файлу, ПК не потрібен
            source = "file"
            load(Uri.fromFile(f).toString(), atMs)
            return
        }
        val src = v.resKey
        val pick = when (quality) {
            "orig" -> 0
            "1080", "720", "480" -> quality.toInt().takeIf { ffmpeg && (src == 0 || src > it) } ?: 0
            else -> when {   // авто
                !ffmpeg -> 0
                Caps.metered(ctx) && src > 720 -> 720
                !Caps.hwDecode(v) && src > 1080 -> 1080
                else -> 0
            }
        }
        if (pick > 0) playLive(fitH(pick), atMs) else playRaw(atMs)
    }

    fun seekAbs(ms: Long) {
        val target = ms.coerceIn(0L, maxOf(0L, dur))
        if (source == "live") playLive(liveH, target) else player.seekTo(target)
        pos = target
        ended = false
    }

    /** Телефон не тягне файл → копія з ПК, якщо вона вже є, інакше потік на льоту, а в крайньому разі — готуємо копію. */
    fun fallback(reason: String) {
        val at = absPos()
        if (source == "raw" && (v.ready || ffmpeg)) {
            player.stop()
            if (v.ready) playCopy(at) else playLive(fitH(1080), at)
            return
        }
        if (source == "copy" || prep != null) {
            failed = reason
            return
        }
        player.stop()
        scope.launch {
            try {
                var st = vm.api.prepare(v.id, force = !v.prep)
                prep = st
                while (st.state != "ready") {
                    if (st.state == "error") throw IOException(st.error.ifEmpty { "ffmpeg не зміг перекодувати файл" })
                    delay(1500)
                    st = vm.api.prepareStatus(v.id)
                    prep = st
                }
                prep = null
                playCopy(at)
            } catch (e: Exception) {
                prep = null
                failed = e.message ?: "Не вдалося підготувати відео"
            }
        }
    }

    fun start() {
        failed = null
        ended = false
        val resumeAt = when {
            route.startAt != null -> route.startAt
            v.resumable(cfg?.resume ?: true) -> v.pos
            else -> 0.0
        }
        if (route.startAt == null && resumeAt > 0) {
            notice = Triple("Продовжую з ${Fmt.dur(resumeAt)}", "З початку") {
                seekAbs(0)
                if (watch.watched < 30) watch.start = 0.0
            }
        }
        open((resumeAt * 1000).toLong())
    }

    fun setQuality(qv: String) {
        quality = qv
        vm.prefs.quality = qv
        val at = absPos()
        player.stop()
        failed = null
        open(at)
        notice = Triple("Якість: " + qualityName(qv), null, null)
    }

    fun goNext() {
        val nx = next ?: return
        countdown = -1
        ping(true)
        vm.nav.replace(Player(nx.id))
    }

    fun seekBy(sec: Int) {
        seekAbs(absPos() + sec * 1000L)
        val b = bubble
        val now = System.currentTimeMillis()
        bubble = if (b != null && now - b.second < 900 && (b.first > 0) == (sec > 0)) Pair(b.first + sec, now) else Pair(sec, now)
        ended = false
    }

    fun togglePlay() {
        if (ended) {
            seekAbs(0)
            countdown = -1
        }
        if (player.isPlaying) player.pause() else player.play()
        poke()
    }

    LaunchedEffect(Unit) {
        vm.keys.collect { k ->
            when (k) {
                android.view.KeyEvent.KEYCODE_DPAD_LEFT, android.view.KeyEvent.KEYCODE_BUTTON_L1,
                android.view.KeyEvent.KEYCODE_MEDIA_REWIND -> { seekBy(-step); poke() }
                android.view.KeyEvent.KEYCODE_DPAD_RIGHT, android.view.KeyEvent.KEYCODE_BUTTON_R1,
                android.view.KeyEvent.KEYCODE_MEDIA_FAST_FORWARD -> { seekBy(step); poke() }
                else -> togglePlay()
            }
        }
    }

    // ── підключення плеєра ──
    DisposableEffect(route.id) {
        activity.bindPlayback()
        val l = object : MPlayer.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
                if (isPlaying && watch.start == null) watch.start = absPos() / 1000.0
                if (!isPlaying) ping(false)
            }

            override fun onPlaybackStateChanged(state: Int) {
                buffering = state == MPlayer.STATE_BUFFERING
                if (state == MPlayer.STATE_READY && source != "live" && player.duration > 0) dur = player.duration
                if (state == MPlayer.STATE_ENDED) {
                    ended = true
                    ping(true)
                    controls = true
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                val badStatus = error.errorCode == PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS
                val network = error.errorCode in 2000..2999 && !(badStatus && source == "live")
                if (network) failed = "Зв'язок з ПК обірвався (${error.errorCodeName})" else fallback(error.errorCodeName)
            }

            override fun onTracksChanged(tracks: Tracks) {
                subs = subTracks(tracks)
                if (source != "raw" || tracks.groups.isEmpty()) return
                val g = tracks.groups
                val badVideo = g.any { it.type == C.TRACK_TYPE_VIDEO } && g.none { it.type == C.TRACK_TYPE_VIDEO && it.isSupported }
                val badAudio = g.any { it.type == C.TRACK_TYPE_AUDIO } && g.none { it.type == C.TRACK_TYPE_AUDIO && it.isSupported }
                if (badVideo || badAudio) fallback(if (badVideo) "відео" else "звук")
            }
        }
        player.addListener(l)
        start()
        onDispose {
            player.removeListener(l)
            if (!ended) ping(false)
            player.stop()
            player.clearMediaItems()
            player.setPlaybackSpeed(1f)
        }
    }

    // повноекранний режим, орієнтація, яскравість
    DisposableEffect(Unit) {
        val w = activity.window
        val c = WindowCompat.getInsetsController(w, w.decorView)
        c.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        c.hide(WindowInsetsCompat.Type.systemBars())
        onDispose {
            c.show(WindowInsetsCompat.Type.systemBars())
            w.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            w.attributes = w.attributes.apply { screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE }
            activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            activity.setPipAuto(false)
        }
    }
    LaunchedEffect(landscape) {
        activity.requestedOrientation = if (landscape) ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE else ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
    }
    LaunchedEffect(playing) {
        val w = activity.window
        if (playing) w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) else w.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        activity.setPipAuto(playing)
    }

    // позиція, буфер, облік перегляду
    LaunchedEffect(route.id) {
        while (true) {
            val cur = absPos()
            if (!scrubbing) pos = cur
            buffered = (if (source == "live") offset else 0L) + player.bufferedPosition
            if (source != "live" && player.duration > 0) dur = player.duration
            val c = cur / 1000.0
            if (player.isPlaying) {
                val last = watch.last
                if (last != null) {
                    val dt = c - last
                    if (dt > 0 && dt < 3 * player.playbackParameters.speed) watch.watched += dt
                }
                if (System.currentTimeMillis() - watch.lastPing > 10_000) ping(false)
            }
            watch.last = c
            delay(250)
        }
    }

    // ховаємо керування під час перегляду
    LaunchedEffect(controls, touched, playing, scrubbing) {
        if (controls && playing && !scrubbing) {
            delay(3500)
            controls = false
        }
    }
    LaunchedEffect(notice) {
        if (notice != null) {
            delay(6000)
            notice = null
        }
    }
    LaunchedEffect(bubble) {
        val b = bubble ?: return@LaunchedEffect
        delay(800)
        if (bubble == b) bubble = null
    }
    // кінець: «Далі» з відліком
    LaunchedEffect(ended) {
        if (!ended) return@LaunchedEffect
        if (next != null && cfg?.autoplayNext != false) {
            countdown = cfg?.nextDelay ?: 8
            while (countdown > 0) {
                delay(1000)
                if (countdown > 0) countdown--
            }
            if (countdown == 0) goNext()
        } else if (q != null && next == null) {
            vm.queue = null
            vm.say(if (q.anime != null) "Остання серія «${q.name}»" else "Плейлист «${q.name}» завершено")
        }
    }

    val audio = remember { ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager }
    val maxVol = remember { audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1) }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        AndroidView(
            factory = { c ->
                PlayerView(c).apply {
                    useController = false
                    setShutterBackgroundColor(android.graphics.Color.BLACK)
                    setKeepContentOnPlayerReset(true)
                    this.player = player
                }
            },
            update = {
                it.resizeMode = resize
                if (it.player !== player) it.player = player
            },
            onRelease = { it.player = null },
            modifier = Modifier.fillMaxSize(),
        )

        if (!vm.pip) {
            // жести: тап — меню, подвійний тап — перемотка, утримання — 2×, свайп — яскравість/гучність
            Box(
                Modifier.fillMaxSize()
                    .pointerInput(Unit) {
                        detectTapGestures(
                            onPress = {
                                val job = scope.launch {
                                    delay(450)
                                    holding = true
                                    player.setPlaybackSpeed(2f)
                                }
                                tryAwaitRelease()
                                job.cancel()
                                if (holding) {
                                    holding = false
                                    player.setPlaybackSpeed(speed)
                                }
                            },
                            onLongPress = { },
                            onTap = { if (controls) controls = false else poke() },
                            onDoubleTap = { o ->
                                val third = size.width / 3f
                                when {
                                    o.x < third -> seekBy(-step)
                                    o.x > third * 2 -> seekBy(step)
                                    else -> togglePlay()
                                }
                            },
                        )
                    }
                    .pointerInput(vm.prefs.gestures) {
                        if (!vm.prefs.gestures) return@pointerInput
                        var left = false
                        var base = 0f
                        var acc = 0f
                        detectVerticalDragGestures(
                            onDragStart = { o ->
                                left = o.x < size.width / 2f
                                acc = 0f
                                base = if (left) {
                                    val b = activity.window.attributes.screenBrightness
                                    if (b >= 0) b else runCatching { Settings.System.getInt(ctx.contentResolver, Settings.System.SCREEN_BRIGHTNESS) / 255f }.getOrDefault(.5f)
                                } else audio.getStreamVolume(AudioManager.STREAM_MUSIC).toFloat() / maxVol
                            },
                            onDragEnd = { hud = null },
                            onDragCancel = { hud = null },
                        ) { change, dy ->
                            change.consume()
                            acc += -dy / (size.height * 0.7f)
                            val x = (base + acc).coerceIn(0f, 1f)
                            if (left) {
                                val w = activity.window
                                w.attributes = w.attributes.apply { screenBrightness = x.coerceAtLeast(0.01f) }
                                hud = Ic.sun to x
                            } else {
                                audio.setStreamVolume(AudioManager.STREAM_MUSIC, (x * maxVol).roundToInt(), 0)
                                hud = Ic.volume to x
                            }
                        }
                    },
            )

            // підказки поверх відео
            if (buffering && failed == null && prep == null && !ended) {
                CircularProgressIndicator(color = p.acc, strokeWidth = 3.dp, modifier = Modifier.align(Alignment.Center).size(46.dp))
            }
            if (holding) Pill("2× ▶▶", Modifier.align(Alignment.TopCenter).padding(top = 28.dp))
            bubble?.let { (s, _) ->
                Pill(
                    (if (s > 0) "+" else "−") + "${abs(s)} с",
                    Modifier.align(if (s > 0) Alignment.CenterEnd else Alignment.CenterStart).padding(horizontal = 48.dp),
                )
            }
            hud?.let { (icon, x) ->
                Row(
                    Modifier.align(Alignment.Center).clip(RoundedCornerShape(12.dp)).background(Color.Black.copy(alpha = .7f)).padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(icon, null, tint = Color.White, modifier = Modifier.size(22.dp))
                    Spacer(Modifier.width(12.dp))
                    Meter(x, Modifier.width(140.dp), track = Color.White.copy(alpha = .2f))
                    Spacer(Modifier.width(12.dp))
                    Text("${(x * 100).roundToInt()}%", style = mono(12.sp, FontWeight.Bold), color = Color.White)
                }
            }

            AnimatedVisibility(controls || ended || failed != null || prep != null, enter = fadeIn(), exit = fadeOut()) {
                Controls(
                    vm = vm, v = v, n = n, playing = playing, pos = pos, dur = dur, buffered = buffered, speed = speed,
                    queueText = q?.let { (if (it.anime != null) "Аніме «" else "Плейлист «") + "${it.name}», ${it.ids.indexOf(v.id) + 1} з ${it.ids.size}" },
                    hasNext = next != null, landscape = landscape, center = failed == null && prep == null,
                    onBack = { vm.nav.back() },
                    onPlay = { togglePlay() },
                    onSeekBy = { seekBy(it); poke() },
                    onSeek = { ms ->
                        seekAbs(ms)
                        countdown = -1
                        poke()
                    },
                    qualityLabel = when (source) {
                        "live" -> "${liveH}p"
                        "copy" -> "MP4"
                        else -> if (quality == "auto") "Авто" else "Ориг."
                    },
                    onQuality = { picker = true; poke() },
                    subs = subs,
                    onSubs = {
                        if (subs.size > 1) subsPicker = true
                        else {
                            val off = subs.none { it.selected }
                            applySubs(if (off) subs[0] else null)
                            notice = Triple(if (off) "Субтитри увімкнено" else "Субтитри вимкнено", null, null)
                        }
                        poke()
                    },
                    onScrub = { scrubbing = it; poke() },
                    onSpeed = {
                        speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.size]
                        player.setPlaybackSpeed(speed)
                        poke()
                    },
                    onResize = {
                        resize = if (resize == AspectRatioFrameLayout.RESIZE_MODE_FIT) AspectRatioFrameLayout.RESIZE_MODE_ZOOM else AspectRatioFrameLayout.RESIZE_MODE_FIT
                        notice = Triple(if (resize == AspectRatioFrameLayout.RESIZE_MODE_ZOOM) "Заповнити екран" else "Вписати в екран", null, null)
                        poke()
                    },
                    onRotate = { landscape = !landscape; poke() },
                    onPip = { activity.enterPip() },
                    onNext = { goNext() },
                    onVote = { vm.vote(vm.byId[v.id] ?: v, it); poke() },
                )
            }

            notice?.let { (text, action, run) ->
                Row(
                    Modifier.align(Alignment.TopCenter).windowInsetsPadding(WindowInsets.safeDrawing).padding(top = 64.dp)
                        .clip(RoundedCornerShape(10.dp)).background(p.bg2.copy(alpha = .94f)).border(1.dp, p.acc.copy(alpha = .7f), RoundedCornerShape(10.dp))
                        .padding(start = 14.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(text, style = mono(12.5.sp), color = p.fg, modifier = Modifier.padding(vertical = 6.dp))
                    if (action != null) {
                        Text(
                            action, style = mono(12.5.sp, FontWeight.Bold), color = p.acc,
                            modifier = Modifier.padding(start = 8.dp).clip(RoundedCornerShape(6.dp)).clickable { run?.invoke(); notice = null }.padding(8.dp),
                        )
                    } else Spacer(Modifier.width(8.dp))
                }
            }

            prep?.let { st -> Preparing(st, Modifier.align(Alignment.Center)) }

            failed?.let { msg ->
                Win("mpv — ", Modifier.align(Alignment.Center).padding(24.dp).widthIn(max = 460.dp), bold = "error") {
                    Column(Modifier.padding(16.dp)) {
                        Text("Не вдалося відтворити", style = body(17.sp, FontWeight.SemiBold), color = p.fg)
                        Spacer(Modifier.height(6.dp))
                        Text(msg, style = mono(12.sp), color = p.mute)
                        Spacer(Modifier.height(14.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Btn("Ще раз", { start() }, icon = Ic.refresh, kind = Kind.Primary)
                            Btn("Назад", { vm.nav.back() }, icon = Ic.back)
                        }
                    }
                }
            }

            if (subsPicker) {
                SubsPicker(subs, onPick = { t ->
                    subsPicker = false
                    applySubs(t)
                    notice = Triple(if (t == null) "Субтитри вимкнено" else "Субтитри: ${t.label}", null, null)
                }, onClose = { subsPicker = false })
            }
            if (picker) {
                QualityPicker(v, quality, if (source == "live") liveH else 0, ffmpeg, onPick = { picker = false; setQuality(it) }, onClose = { picker = false })
            }

            if (ended && failed == null) {
                EndCard(
                    vm, next, countdown, cfg?.autoplayNext != false,
                    Modifier.align(Alignment.BottomEnd).windowInsetsPadding(WindowInsets.safeDrawing).padding(end = 16.dp, bottom = 96.dp),
                    onGo = { goNext() },
                    onCancel = { countdown = -1 },
                    onAgain = {
                        seekAbs(0)
                        player.play()
                    },
                )
            }
        }
    }
}

/** Доріжка субтитрів у файлі. */
data class SubTrack(val group: androidx.media3.common.TrackGroup, val index: Int, val label: String, val selected: Boolean)

private val UK = java.util.Locale("uk")

private fun subTracks(tracks: Tracks): List<SubTrack> = tracks.groups.filter { it.type == C.TRACK_TYPE_TEXT }.flatMap { g ->
    (0 until g.length).filter { g.isTrackSupported(it) }.map { i ->
        val f = g.getTrackFormat(i)
        val lang = f.language?.takeIf { it.isNotBlank() && it != "und" }?.let { java.util.Locale.forLanguageTag(it).getDisplayLanguage(UK) }
        val name = listOfNotNull(f.label?.takeIf { it.isNotBlank() }, lang).distinct().joinToString(" · ").ifEmpty { "Доріжка ${i + 1}" }
        val forced = f.selectionFlags and C.SELECTION_FLAG_FORCED != 0
        SubTrack(g.mediaTrackGroup, i, name + if (forced) " (лише написи)" else "", g.isTrackSelected(i))
    }
}

@Composable
private fun SubsPicker(subs: List<SubTrack>, onPick: (SubTrack?) -> Unit, onClose: () -> Unit) {
    val p = LocalPal.current
    val off = subs.none { it.selected }
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose) {
        Win("mpv — ", Modifier.widthIn(max = 420.dp), bold = "subtitles") {
            Column(Modifier.padding(vertical = 6.dp)) {
                (listOf<SubTrack?>(null) + subs).forEach { t ->
                    val on = if (t == null) off else t.selected
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(t) }.padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(t?.label ?: "Вимкнено", style = body(15.sp, if (on) FontWeight.SemiBold else FontWeight.Normal),
                            color = if (on) p.acc else p.fg, modifier = Modifier.weight(1f))
                        if (on) Icon(Ic.check, null, tint = p.acc, modifier = Modifier.size(20.dp))
                    }
                }
            }
        }
    }
}

private fun qualityName(q: String) = when (q) {
    "orig" -> "оригінал"
    "auto" -> "авто"
    else -> q + "p"
}

@Composable
private fun QualityPicker(v: Video, current: String, live: Int, ffmpeg: Boolean, onPick: (String) -> Unit, onClose: () -> Unit) {
    val p = LocalPal.current
    val opts = listOf(
        Triple("auto", "Авто", "Вдома — оригінал, через мобільний інтернет — 720p"),
        Triple("orig", "Оригінал", listOf(v.res, v.vc.uppercase()).filter { it.isNotEmpty() }.joinToString(", ") + " без перекодування"),
        Triple("1080", "1080p", "≈ 6 Мбіт/с, перекодовує ПК"),
        Triple("720", "720p", "≈ 3 Мбіт/с, для мобільного інтернету"),
        Triple("480", "480p", "≈ 1,5 Мбіт/с, коли зв'язок слабкий"),
    )
    androidx.compose.ui.window.Dialog(onDismissRequest = onClose) {
        Win("mpv — ", Modifier.widthIn(max = 420.dp), bold = "quality") {
            Column(Modifier.padding(vertical = 6.dp)) {
                opts.forEach { (id, name, hint) ->
                    val on = id == current
                    val enabled = ffmpeg || id == "auto" || id == "orig"
                    Row(
                        Modifier.fillMaxWidth().clickable(enabled = enabled) { onPick(id) }.padding(horizontal = 16.dp, vertical = 11.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(name, style = body(15.sp, if (on) FontWeight.SemiBold else FontWeight.Normal), color = if (on) p.acc else if (enabled) p.fg else p.mute)
                            Text(if (enabled) hint else "Потрібен ffmpeg на ПК", style = body(12.sp), color = p.mute)
                        }
                        if (on) Icon(Ic.check, null, tint = p.acc, modifier = Modifier.size(20.dp))
                    }
                }
                if (live > 0) Text("Зараз ПК перекодовує в ${live}p", style = mono(11.5.sp), color = p.mute, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            }
        }
    }
}

@Composable
private fun Pill(text: String, modifier: Modifier = Modifier) {
    Text(
        text, style = mono(14.sp, FontWeight.Bold), color = Color.White,
        modifier = modifier.clip(RoundedCornerShape(20.dp)).background(Color.Black.copy(alpha = .62f)).padding(horizontal = 16.dp, vertical = 9.dp),
    )
}

@Composable
private fun Preparing(st: Prep, modifier: Modifier) {
    val p = LocalPal.current
    Win("ffmpeg — ", modifier.padding(24.dp).widthIn(max = 460.dp), bold = "prepare") {
        Column(Modifier.padding(16.dp)) {
            Text("Готую копію для телефона", style = body(17.sp, FontWeight.SemiBold), color = p.fg)
            Spacer(Modifier.height(6.dp))
            Text(
                "Телефон не відтворює цей файл напряму, тому ПК перекодовує його в MP4" + (if (st.enc.isNotEmpty()) " (${st.enc})" else "") +
                    ". Наступного разу відео відкриється одразу.",
                style = body(13.5.sp), color = p.mute,
            )
            Spacer(Modifier.height(14.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Meter(st.progress.toFloat(), Modifier.weight(1f))
                Spacer(Modifier.width(10.dp))
                Text(if (st.state == "queued") "у черзі" else "${(st.progress * 100).roundToInt()}%", style = mono(12.sp, FontWeight.Bold), color = p.fg)
            }
        }
    }
}

@Composable
private fun EndCard(
    vm: AppVM,
    next: Video?,
    countdown: Int,
    auto: Boolean,
    modifier: Modifier,
    onGo: () -> Unit,
    onCancel: () -> Unit,
    onAgain: () -> Unit,
) {
    val p = LocalPal.current
    Column(
        modifier.width(300.dp).clip(RoundedCornerShape(12.dp)).background(p.bg2.copy(alpha = .95f))
            .border(1.dp, p.line, RoundedCornerShape(12.dp)).padding(12.dp),
    ) {
        if (next != null) {
            Text(if (auto && countdown > 0) "Далі через $countdown с" else "Далі", style = mono(12.sp), color = p.acc)
            Spacer(Modifier.height(8.dp))
            Row(Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onGo), verticalAlignment = Alignment.CenterVertically) {
                Cover(next, Modifier.width(112.dp).aspectRatio(16f / 9f).clip(RoundedCornerShape(6.dp)))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(next.title, style = body(14.sp, FontWeight.Medium), color = p.fg, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(Fmt.dur(next.dur), style = mono(11.5.sp), color = p.mute)
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Btn("Дивитися", onGo, Modifier.weight(1f), icon = Ic.play, kind = Kind.Primary)
                if (auto && countdown > 0) Btn("Скасувати", onCancel, Modifier.weight(1f))
            }
        } else {
            Text("Це було останнє", style = mono(12.sp), color = p.acc)
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Btn("Ще раз", onAgain, Modifier.weight(1f), icon = Ic.restart)
                Btn("Випадкове", { vm.openRandom(replace = true) }, Modifier.weight(1f), icon = Ic.dice)
            }
        }
    }
}

@Composable
private fun Controls(
    vm: AppVM,
    v: Video,
    n: Int,
    playing: Boolean,
    pos: Long,
    dur: Long,
    buffered: Long,
    speed: Float,
    qualityLabel: String,
    onQuality: () -> Unit,
    subs: List<SubTrack>,
    onSubs: () -> Unit,
    queueText: String?,
    hasNext: Boolean,
    landscape: Boolean,
    center: Boolean,
    onBack: () -> Unit,
    onPlay: () -> Unit,
    onSeekBy: (Int) -> Unit,
    onSeek: (Long) -> Unit,
    onScrub: (Boolean) -> Unit,
    onSpeed: () -> Unit,
    onResize: () -> Unit,
    onRotate: () -> Unit,
    onPip: () -> Unit,
    onNext: () -> Unit,
    onVote: (Int) -> Unit,
) {
    val p = LocalPal.current
    val cur = vm.byId[v.id] ?: v
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxWidth().height(150.dp).background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = .75f), Color.Transparent))))
        Box(Modifier.fillMaxWidth().height(200.dp).align(Alignment.BottomCenter).background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = .85f)))))

        // верх: назад, назва, оцінка
        Row(
            Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.safeDrawing).padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CtlBtn(Ic.back, "Назад", onBack)
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f).clickable { vm.nav.replace(Info(v.id)) }) {
                Text(v.title, style = body(16.sp, FontWeight.SemiBold), color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(queueText ?: Fmt.shortFolder(v.folder), style = mono(11.5.sp), color = if (queueText != null) p.acc else Color.White.copy(alpha = .7f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            CtlBtn(Ic.up, "Подобається", { onVote(1) }, on = cur.vote > 0)
            CtlBtn(Ic.down, "Не подобається", { onVote(-1) }, on = cur.vote < 0)
        }

        // центр: −10, пауза, +10 (ховаємо, коли поверх вікно з помилкою чи підготовкою копії)
        if (center) Row(Modifier.align(Alignment.Center), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(34.dp)) {
            SkipBtn(Ic.back10, "−${vm.prefs.seekStep}") { onSeekBy(-vm.prefs.seekStep) }
            Box(
                Modifier.size(74.dp).clip(CircleShape).background(Color.Black.copy(alpha = .45f)).border(1.5.dp, Color.White.copy(alpha = .35f), CircleShape)
                    .clickable(onClick = onPlay),
                contentAlignment = Alignment.Center,
            ) {
                Icon(if (playing) Ic.pause else Ic.play, if (playing) "Пауза" else "Відтворити", tint = Color.White, modifier = Modifier.size(34.dp))
            }
            SkipBtn(Ic.fwd10, "+${vm.prefs.seekStep}") { onSeekBy(vm.prefs.seekStep) }
        }

        // низ: час, кнопки, смуга перемотки з кадром-підказкою
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().windowInsetsPadding(WindowInsets.safeDrawing).padding(horizontal = 14.dp, vertical = 6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${Fmt.dur(pos / 1000.0)} / ${Fmt.dur(dur / 1000.0)}", style = mono(12.5.sp, FontWeight.Bold), color = Color.White)
                Spacer(Modifier.weight(1f))
                Text(
                    speedLabel(speed), style = mono(13.sp, FontWeight.Bold), color = if (speed != 1f) p.acc else Color.White,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onSpeed).padding(horizontal = 10.dp, vertical = 9.dp),
                )
                Text(
                    qualityLabel, style = mono(13.sp, FontWeight.Bold), color = Color.White,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onQuality).padding(horizontal = 10.dp, vertical = 9.dp),
                )
                if (subs.isNotEmpty()) {
                    val on = subs.any { it.selected }
                    CtlBtn(Ic.cc, if (on) "Субтитри: вимкнути" else "Субтитри: увімкнути", onSubs, on = on)
                }
                CtlBtn(Ic.fit, "Масштаб", onResize)
                CtlBtn(Ic.rotate, if (landscape) "Вертикально" else "Горизонтально", onRotate, on = landscape)
                CtlBtn(Ic.pip, "Картинка в картинці", onPip)
                if (hasNext) CtlBtn(Ic.next, "Наступне", onNext)
            }
            SeekBar(v, n, pos, dur, buffered, onSeek, onScrub)
        }
    }
}

@Composable
private fun CtlBtn(icon: ImageVector, desc: String, onClick: () -> Unit, on: Boolean = false) {
    val p = LocalPal.current
    Box(Modifier.size(44.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, desc, tint = if (on) p.acc else Color.White, modifier = Modifier.size(23.dp))
    }
}

@Composable
private fun SkipBtn(icon: ImageVector, label: String, onClick: () -> Unit) {
    Box(Modifier.size(56.dp).clip(CircleShape).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Icon(icon, null, tint = Color.White, modifier = Modifier.size(38.dp))
        Text(label.trimStart('+', '−'), style = mono(10.sp, FontWeight.Bold), color = Color.White, modifier = Modifier.padding(top = 4.dp))
    }
}

/** Смуга перемотки: веди пальцем — над нею з'являється кадр з цього місця (з нарізки). */
@Composable
private fun SeekBar(v: Video, n: Int, pos: Long, dur: Long, buffered: Long, onSeek: (Long) -> Unit, onScrub: (Boolean) -> Unit) {
    val p = LocalPal.current
    var drag by remember { mutableStateOf<Float?>(null) }
    val total = dur.coerceAtLeast(1)
    val frac = drag ?: (pos.toFloat() / total)
    val density = LocalDensity.current
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val wPx = with(density) { maxWidth.toPx() }
        val d = drag
        if (d != null) {
            val t = d * total / 1000.0
            val pw = 168.dp
            val pwPx = with(density) { pw.toPx() }
            val x = (d * wPx - pwPx / 2).coerceIn(0f, (wPx - pwPx).coerceAtLeast(0f))
            Column(Modifier.offset { IntOffset(x.roundToInt(), 0) }.width(pw), horizontalAlignment = Alignment.CenterHorizontally) {
                if (v.hasSprite && v.dur > 0) {
                    val i = (((t / v.dur) - 0.03) / 0.94 * (n - 1)).roundToInt().coerceIn(0, n - 1)
                    SpriteFrame(
                        v, i,
                        Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).background(Color.Black)
                            .border(1.5.dp, p.acc, RoundedCornerShape(8.dp)),
                    )
                }
                Text(
                    Fmt.dur(t), style = mono(12.sp, FontWeight.Bold), color = Color.White,
                    modifier = Modifier.padding(top = 4.dp).clip(RoundedCornerShape(5.dp)).background(Color.Black.copy(alpha = .7f)).padding(horizontal = 6.dp, vertical = 2.dp),
                )
            }
        }
        Box(
            Modifier.fillMaxWidth().padding(top = if (d != null) (if (v.hasSprite) 124.dp else 30.dp) else 0.dp).height(34.dp)
                .pointerInput(total) {
                    detectTapGestures(onTap = { o -> onSeek((o.x / size.width * total).toLong().coerceIn(0, total)) })
                }
                .pointerInput(total) {
                    detectHorizontalDragGestures(
                        onDragStart = { o ->
                            drag = (o.x / size.width).coerceIn(0f, 1f)
                            onScrub(true)
                        },
                        onDragEnd = {
                            drag?.let { onSeek((it * total).toLong()) }
                            drag = null
                            onScrub(false)
                        },
                        onDragCancel = {
                            drag = null
                            onScrub(false)
                        },
                    ) { change, _ ->
                        change.consume()
                        drag = (change.position.x / size.width).coerceIn(0f, 1f)
                    }
                },
        ) {
            Canvas(Modifier.fillMaxSize()) {
                val y = size.height / 2
                val h = 4.dp.toPx()
                drawLine(Color.White.copy(alpha = .22f), Offset(0f, y), Offset(size.width, y), h, StrokeCap.Round)
                drawLine(Color.White.copy(alpha = .38f), Offset(0f, y), Offset(size.width * (buffered.toFloat() / total).coerceIn(0f, 1f), y), h, StrokeCap.Round)
                val x = size.width * frac.coerceIn(0f, 1f)
                drawLine(p.acc, Offset(0f, y), Offset(x, y), h, StrokeCap.Round)
                drawCircle(p.acc, (if (d != null) 9.dp else 7.dp).toPx(), Offset(x, y))
            }
        }
    }
}

@Suppress("unused")
private fun Modifier.fullHeight() = this.fillMaxHeight()
