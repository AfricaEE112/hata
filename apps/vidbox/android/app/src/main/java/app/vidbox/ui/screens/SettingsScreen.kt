package app.vidbox.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.BuildConfig
import app.vidbox.data.Fmt
import app.vidbox.ui.Btn
import app.vidbox.ui.Meter
import app.vidbox.ui.Ic
import app.vidbox.ui.Kind
import app.vidbox.ui.LocalPal
import app.vidbox.ui.PALS
import app.vidbox.ui.PAD
import app.vidbox.ui.PageTitle
import app.vidbox.ui.PromptLine
import app.vidbox.ui.Win
import app.vidbox.ui.body
import app.vidbox.ui.mono
import org.json.JSONObject

@Composable
fun SettingsScreen(vm: AppVM) {
    val p = LocalPal.current
    val ctx = LocalContext.current
    var info by remember { mutableStateOf<JSONObject?>(null) }
    var gen by remember { mutableIntStateOf(0) }    // перемальовуємо після зміни локальних налаштувань
    LaunchedEffect(Unit) { info = runCatching { vm.api.settings() }.getOrNull() }
    val cfg = vm.lib?.cfg
    val w = Modifier.padding(start = PAD, end = PAD, top = 16.dp).widthIn(max = 640.dp).fillMaxWidth()

    LazyColumn(state = vm.nav.list("settings"), contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp), modifier = Modifier.fillMaxSize()) {
        item { PromptLine("~/.config/vidbox", "vim vidbox.conf", Modifier.padding(horizontal = PAD)) }
        item { PageTitle("Налаштування", modifier = Modifier.padding(top = 6.dp)) }

        item {
            Win("~/.config/vidbox/", w, bold = "server") {
                Column(Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(9.dp).clip(CircleShape).background(if (vm.offline == null) Color(0xFF4ADE80) else Color(0xFFFF8A7A)))
                        Spacer(Modifier.width(9.dp))
                        Text(vm.host, style = mono(16.sp, FontWeight.Bold), color = p.fg)
                    }
                    Text(vm.prefs.server, style = mono(12.5.sp), color = p.mute, modifier = Modifier.padding(top = 4.dp))
                    Text(
                        if (vm.offline == null) "Підключено" + (info?.optString("version")?.let { ", VidBox $it на ПК" } ?: "") else "Немає зв'язку: ${vm.offline}",
                        style = body(13.5.sp), color = p.mute, modifier = Modifier.padding(top = 2.dp),
                    )
                    Spacer(Modifier.height(14.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Btn("Інший ПК", { vm.disconnect() }, icon = Ic.monitor)
                        Btn("Пересканувати", { vm.rescan() }, icon = Ic.refresh)
                    }
                }
            }
        }

        item {
            Win("~/.config/vidbox/", w, bold = "theme") {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Спільна з сайтом: зміниш тут — зміниться і в браузері.", style = body(13.sp), color = p.mute, modifier = Modifier.padding(horizontal = 4.dp))
                    PALS.chunked(2).forEach { row ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            row.forEach { t ->
                                val on = t.id == vm.themeId
                                Row(
                                    Modifier.weight(1f).clip(RoundedCornerShape(9.dp)).background(t.bg2)
                                        .border(if (on) 2.dp else 1.dp, if (on) t.acc else p.line, RoundedCornerShape(9.dp))
                                        .clickable { vm.setTheme(t.id) }.padding(10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Box(Modifier.size(14.dp).clip(CircleShape).background(t.acc))
                                    Box(Modifier.padding(start = 4.dp).size(14.dp).clip(CircleShape).background(t.acc2))
                                    Spacer(Modifier.width(9.dp))
                                    Text(t.name, style = mono(12.5.sp, if (on) FontWeight.Bold else FontWeight.Normal), color = t.fg, maxLines = 1)
                                }
                            }
                            if (row.size < 2) Spacer(Modifier.weight(1f))
                        }
                    }
                }
            }
        }

        item {
            Win("~/.config/vidbox/", w, bold = "player") {
                Column(Modifier.padding(vertical = 6.dp)) {
                    key(gen) {
                        Toggle("Вмикати наступне відео", "Після кінця відео — наступне з папки чи плейлиста (через ${cfg?.nextDelay ?: 8} с)", cfg?.autoplayNext ?: true) {
                            vm.saveServer(JSONObject().put("autoplay_next", it))
                        }
                        Toggle("Продовжувати з місця зупинки", "Відео відкривається там, де ти зупинився", cfg?.resume ?: true) {
                            vm.saveServer(JSONObject().put("resume", it))
                        }
                        Toggle("Звук у фоні", "Якщо вийти з апки, звук грає далі, а керування — у шторці", vm.prefs.bgAudio) {
                            vm.prefs.bgAudio = it
                            gen++
                        }
                        Toggle("Горизонтальні відео — одразу на весь екран", "Телефон сам повертається в альбомний режим", vm.prefs.autoLandscape) {
                            vm.prefs.autoLandscape = it
                            gen++
                        }
                        Toggle("Жести яскравості й гучності", "Свайп угору-вниз зліва — яскравість, справа — гучність", vm.prefs.gestures) {
                            vm.prefs.gestures = it
                            gen++
                        }
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("Подвійний тап перемотує на", style = body(15.sp, FontWeight.Medium), color = p.fg)
                                Text("Зліва — назад, справа — вперед", style = body(12.5.sp), color = p.mute)
                            }
                            listOf(5, 10, 15, 30).forEach { s ->
                                val on = vm.prefs.seekStep == s
                                Text(
                                    "$s", style = mono(13.sp, FontWeight.Bold), color = if (on) p.on else p.fg,
                                    modifier = Modifier.padding(start = 5.dp).clip(RoundedCornerShape(6.dp)).background(if (on) p.acc else Color.Black.copy(alpha = .25f))
                                        .border(1.dp, if (on) p.acc else p.line, RoundedCornerShape(6.dp))
                                        .clickable { vm.prefs.seekStep = s; gen++ }.padding(horizontal = 9.dp, vertical = 6.dp),
                                )
                            }
                        }
                    }
                }
            }
        }

        item {
            Win("~/.local/bin/", w, bold = "update") {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 14.dp)) {
                    val u = vm.update
                    val st = vm.updateState
                    Text(if (u != null) "Доступна версія ${u.name}" else "Оновлення апки", style = body(15.sp, FontWeight.Medium), color = p.fg)
                    Spacer(Modifier.height(3.dp))
                    Text(
                        when {
                            st == "checking" -> "Перевіряю GitHub…"
                            st == "downloading" -> "Завантажую ${(vm.updateProgress * 100).toInt()}%" + if (u != null && u.size > 0) " з ${Fmt.size(u.size)}" else ""
                            st.startsWith("error") -> "Не вдалося: " + st.removePrefix("error: ")
                            u != null -> "Зараз ${BuildConfig.VERSION_NAME}. Апка завантажиться з GitHub і запропонує встановити оновлення, налаштування збережуться."
                            st == "latest" -> "Встановлено найновішу версію ${BuildConfig.VERSION_NAME}"
                            else -> "Зараз ${BuildConfig.VERSION_NAME}. Нову версію апка перевіряє сама при запуску."
                        },
                        style = body(12.5.sp), color = p.mute,
                    )
                    if (st == "downloading") Meter(vm.updateProgress, Modifier.padding(top = 10.dp).fillMaxWidth())
                    Spacer(Modifier.height(12.dp))
                    if (u != null) Btn("Оновити", { vm.installUpdate() }, icon = Ic.arrDown, kind = Kind.Primary, enabled = st != "downloading")
                    else Btn("Перевірити оновлення", { vm.checkUpdate() }, icon = Ic.refresh, enabled = st != "checking")
                }
            }
        }

        item {
            Win("~/", w, bold = "neofetch") { Neofetch(vm, info) }
        }

        item {
            Column(w) {
                Text(
                    "Папки з відео, відеокарта, пароль і кеш налаштовуються на сайті: там є всі параметри сервера.",
                    style = body(13.5.sp), color = p.mute,
                )
                Spacer(Modifier.height(10.dp))
                Btn(
                    "Відкрити налаштування на сайті",
                    { runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(vm.prefs.server.trimEnd('/') + "/#/settings"))) } },
                    icon = Ic.external, kind = Kind.Ghost,
                )
                Spacer(Modifier.height(18.dp))
                Text("VidBox для Android ${BuildConfig.VERSION_NAME}", style = mono(11.5.sp), color = p.mute)
            }
        }
    }
}

@Composable
private fun Toggle(title: String, sub: String, value: Boolean, onChange: (Boolean) -> Unit) {
    val p = LocalPal.current
    var on by remember(value) { mutableStateOf(value) }
    Row(
        Modifier.fillMaxWidth().clickable { on = !on; onChange(on) }.padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = body(15.sp, FontWeight.Medium), color = p.fg)
            Text(sub, style = body(12.5.sp), color = p.mute)
        }
        Spacer(Modifier.width(10.dp))
        Switch(
            checked = on, onCheckedChange = { on = it; onChange(it) },
            colors = SwitchDefaults.colors(
                checkedTrackColor = p.acc, checkedThumbColor = p.on, uncheckedTrackColor = p.bg3,
                uncheckedThumbColor = p.mute, uncheckedBorderColor = p.line,
            ),
        )
    }
}

@Composable
private fun Neofetch(vm: AppVM, info: JSONObject?) {
    val p = LocalPal.current
    val logo = listOf("███", "██████", "█████████", "████████████", "███████████████", "████████████", "█████████", "██████", "███    ████████")
    val tot = info?.optJSONObject("totals")
    val hw = info?.optJSONObject("hw")
    val lines = listOf(
        "OS" to (info?.optString("os") ?: "…"),
        "Host" to (info?.optString("host") ?: vm.host),
        "Uptime" to (info?.optLong("uptime")?.let { Fmt.uptime(it) } ?: "…"),
        "Videos" to (tot?.let { "${it.optInt("videos")}, ${Fmt.size(it.optLong("size"))}, ${Fmt.len(it.optDouble("dur", 0.0))}" } ?: "${vm.videos.size}"),
        "GPU" to (hw?.optString("gpu")?.ifEmpty { null } ?: "не визначено"),
        "Encoder" to (hw?.optString("current") ?: "…"),
        "ffmpeg" to (info?.optString("ffmpegVersion")?.ifEmpty { null } ?: if (vm.lib?.ffmpeg == true) "є" else "немає"),
        "Server" to "VidBox ${info?.optString("version") ?: "…"}",
        "Client" to "Android ${android.os.Build.VERSION.RELEASE}, апка ${BuildConfig.VERSION_NAME}",
    )
    Row(Modifier.padding(14.dp)) {
        Text(logo.joinToString("\n"), style = mono(7.5.sp).copy(lineHeight = 8.5.sp), color = p.acc, modifier = Modifier.padding(end = 12.dp, top = 4.dp))
        Column {
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = p.acc, fontWeight = FontWeight.Bold)) { append("vidbox") }
                    withStyle(SpanStyle(color = p.fg)) { append("@") }
                    withStyle(SpanStyle(color = p.acc, fontWeight = FontWeight.Bold)) { append(info?.optString("host") ?: vm.host) }
                },
                style = mono(12.5.sp),
            )
            Text("─".repeat(18), style = mono(12.5.sp), color = p.line)
            lines.forEach { (k, v) ->
                Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(color = p.acc2, fontWeight = FontWeight.Bold)) { append(k) }
                        withStyle(SpanStyle(color = p.fg)) { append(": $v") }
                    },
                    style = mono(11.5.sp),
                )
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                listOf(p.bg3, p.acc, p.acc2, p.fg, p.mute, p.line).forEach { Box(Modifier.size(width = 18.dp, height = 10.dp).background(it)) }
            }
        }
    }
}
