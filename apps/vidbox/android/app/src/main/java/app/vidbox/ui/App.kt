package app.vidbox.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.Anime
import app.vidbox.Downloads
import app.vidbox.AnimeShow
import app.vidbox.AppVM
import app.vidbox.Connect
import app.vidbox.Home
import app.vidbox.Info
import app.vidbox.Lib
import app.vidbox.MainActivity
import app.vidbox.Player
import app.vidbox.Playlist
import app.vidbox.Playlists
import app.vidbox.Route
import app.vidbox.Settings
import app.vidbox.Top
import app.vidbox.player.PlayerScreen
import app.vidbox.ui.screens.ConnectScreen
import app.vidbox.ui.screens.HomeScreen
import app.vidbox.ui.screens.InfoScreen
import app.vidbox.ui.screens.LibraryScreen
import app.vidbox.ui.screens.PlaylistScreen
import app.vidbox.ui.screens.PlaylistsScreen
import app.vidbox.ui.screens.SettingsScreen
import app.vidbox.ui.screens.TopScreen
import app.vidbox.ui.screens.AnimeScreen
import app.vidbox.ui.screens.DownloadsScreen
import app.vidbox.ui.screens.AnimeShowScreen
import app.vidbox.ui.screens.MangaScreen
import app.vidbox.ui.screens.MangaShowScreen
import app.vidbox.ui.screens.ReaderScreen
import app.vidbox.Manga
import app.vidbox.MangaShow
import app.vidbox.Reader

@Composable
fun App(vm: AppVM, activity: MainActivity) {
    val theme = pal(vm.themeId, vm.hataTheme)
    androidx.compose.runtime.LaunchedEffect(theme.light) {    // світла тема — темні значки в рядку стану
        androidx.core.view.WindowCompat.getInsetsController(activity.window, activity.window.decorView).apply {
            isAppearanceLightStatusBars = theme.light
            isAppearanceLightNavigationBars = theme.light
        }
    }
    VidBoxTheme(theme) {
        CompositionLocalProvider(LocalVM provides vm) {
            val p = LocalPal.current
            val top = vm.nav.top
            BackHandler(enabled = vm.nav.stack.size > 1) { vm.nav.back() }
            Box(Modifier.fillMaxSize().background(p.bg)) {
                when (top) {
                    is Connect -> ConnectScreen(vm)
                    is Player -> key(top.key) { PlayerScreen(vm, top, activity) }
                    is Reader -> key(top.key) { ReaderScreen(vm, top, activity) }
                    else -> Shell(vm, top)
                }
                if (!vm.pip) ToastHost(vm)
            }
        }
    }
}

@Composable
private fun Shell(vm: AppVM, top: Route) {
    val p = LocalPal.current
    val ime = WindowInsets.ime.getBottom(LocalDensity.current) > 0
    Column(Modifier.fillMaxSize().backdrop(p)) {
        TopBar(vm)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            AnimatedContent(
                targetState = top,
                transitionSpec = { fadeIn(tween(170)) togetherWith fadeOut(tween(110)) },
                contentKey = { it.key },
                label = "screen",
            ) { r ->
                when (r) {
                    is Home -> HomeScreen(vm)
                    is Lib -> LibraryScreen(vm)
                    is Playlists -> PlaylistsScreen(vm)
                    is Playlist -> PlaylistScreen(vm, r.id)
                    is Top -> TopScreen(vm)
                    is Anime -> AnimeScreen(vm)
                    is Downloads -> DownloadsScreen(vm)
                    is AnimeShow -> AnimeShowScreen(vm, r.sid)
                    is Manga -> MangaScreen(vm)
                    is MangaShow -> MangaShowScreen(vm, r.tid)
                    is Settings -> SettingsScreen(vm)
                    is Info -> InfoScreen(vm, r)
                    else -> {}
                }
            }
        }
        if (!ime) Dock(vm)
    }
}

@Composable
private fun TopBar(vm: AppVM) {
    val p = LocalPal.current
    Column(Modifier.fillMaxWidth().background(p.bg.copy(alpha = .86f))) {
        Row(
            Modifier.statusBarsPadding().fillMaxWidth().height(58.dp).padding(horizontal = PAD),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.clip(RoundedCornerShape(8.dp)).clickable { vm.nav.go(Home) }) { Brand() }
            Spacer(Modifier.weight(1f))
            if (vm.offline != null) {
                Text(
                    "offline", style = mono(11.5.sp, FontWeight.Bold), color = Color(0xFFFF8A7A),
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).border(1.dp, Color(0x66FF8A7A), RoundedCornerShape(6.dp))
                        .clickable { vm.refresh() }.padding(horizontal = 8.dp, vertical = 4.dp),
                )
                Spacer(Modifier.width(8.dp))
            }
            if (vm.dl.items.isNotEmpty()) {
                IconBtn(Ic.arrDown, { vm.nav.go(Downloads) }, on = vm.nav.top == Downloads, size = 40.dp, desc = "Завантажені")
                Spacer(Modifier.width(8.dp))
            }
            IconBtn(Ic.search, { vm.focusSearch = true; vm.nav.go(Lib) }, size = 40.dp, desc = "Пошук")
            Spacer(Modifier.width(8.dp))
            IconBtn(Ic.sliders, { vm.nav.go(Settings) }, on = vm.nav.tab == Settings, size = 40.dp, desc = "Налаштування")
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.line.copy(alpha = .7f)))
    }
}

@Composable
private fun Dock(vm: AppVM) {
    val p = LocalPal.current
    val tab = vm.nav.tab
    Box(Modifier.fillMaxWidth().navigationBarsPadding().padding(start = 12.dp, end = 12.dp, bottom = 8.dp, top = 4.dp)) {
        Row(
            Modifier.fillMaxWidth().shadow(20.dp, RoundedCornerShape(18.dp)).clip(RoundedCornerShape(18.dp))
                .background(p.bg2.copy(alpha = .96f)).border(1.dp, p.line, RoundedCornerShape(18.dp))
                .padding(horizontal = 4.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceAround,
        ) {
            DockItem("Головна", Ic.home, tab == Home) { vm.nav.go(Home) }
            DockItem("Бібліотека", Ic.film, tab == Lib) { vm.nav.go(Lib) }
            Box(
                Modifier.size(54.dp).shadow(16.dp, RoundedCornerShape(15.dp), ambientColor = p.acc, spotColor = p.acc)
                    .clip(RoundedCornerShape(15.dp)).background(Brush.linearGradient(listOf(p.acc, p.acc2)))
                    .clickable { vm.openRandom() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Ic.dice, "Випадкове відео", tint = p.on, modifier = Modifier.size(27.dp))
            }
            DockItem("Аніме", Ic.anime, tab == Anime) { vm.nav.go(Anime) }
            DockItem("Манга", Ic.book, tab == Manga) { vm.nav.go(Manga) }
            DockItem("Плейлисти", Ic.list, tab == Playlists) { vm.nav.go(Playlists) }
        }
    }
}

@Composable
private fun DockItem(label: String, icon: ImageVector, on: Boolean, onClick: () -> Unit) {
    val p = LocalPal.current
    Column(
        Modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(horizontal = 3.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(icon, null, tint = if (on) p.acc else p.mute, modifier = Modifier.size(24.dp))
        Spacer(Modifier.height(3.dp))
        Text(label, style = body(11.sp, if (on) FontWeight.SemiBold else FontWeight.Normal), color = if (on) p.fg else p.mute, maxLines = 1)
        Spacer(Modifier.height(3.dp))
        Box(Modifier.size(4.dp).clip(CircleShape).background(if (on) p.acc else Color.Transparent))
    }
}
