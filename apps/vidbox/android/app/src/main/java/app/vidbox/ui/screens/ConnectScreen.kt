package app.vidbox.ui.screens

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.vidbox.AppVM
import app.vidbox.data.Discovery
import app.vidbox.data.Hello
import app.vidbox.ui.Blink
import app.vidbox.ui.Brand
import app.vidbox.ui.Btn
import app.vidbox.ui.Ic
import app.vidbox.ui.Kind
import app.vidbox.ui.LocalPal
import app.vidbox.ui.Win
import app.vidbox.ui.backdrop
import app.vidbox.ui.body
import app.vidbox.ui.display
import app.vidbox.ui.mono
import kotlinx.coroutines.launch
import java.io.IOException

/** Перший запуск: апка сама шукає VidBox у Wi-Fi. Можна ввести адресу вручну. */
@Composable
fun ConnectScreen(vm: AppVM) {
    val p = LocalPal.current
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val found = remember { mutableStateListOf<Discovery.Found>() }
    var scanning by remember { mutableStateOf(true) }
    var round by remember { mutableIntStateOf(0) }
    var manual by remember { mutableStateOf(vm.prefs.server.removePrefix("http://")) }
    var login by remember { mutableStateOf<Discovery.Found?>(null) }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun connect(base: String, known: Hello?, pw: String?) {
        scope.launch {
            busy = true
            error = null
            try {
                val h = known ?: vm.api.hello(base, fast = false) ?: throw IOException("За адресою $base не відповідає VidBox. Перевір, що він запущений на ПК.")
                if (h.auth && pw == null) {
                    login = Discovery.Found(base, h)
                    return@launch
                }
                val token = if (h.auth) vm.api.login(base, pw ?: "") else ""
                vm.onConnected(base, token, h.host)
            } catch (e: Exception) {
                error = e.message ?: "Не вдалося підключитись"
            } finally {
                busy = false
            }
        }
    }

    // сервер уже відомий, але попросив пароль (його змінили на ПК)
    LaunchedEffect(Unit) {
        val s = vm.prefs.server
        if (s.isNotEmpty()) vm.api.hello(s, fast = false)?.let { if (it.auth) login = Discovery.Found(s, it) }
    }
    LaunchedEffect(round) {
        found.clear()
        scanning = true
        Discovery(ctx, vm.api).find().collect { found.add(it) }
        scanning = false
        // знайшовся рівно один ПК — підключаємось самі (з паролем — одразу показуємо поле входу)
        if (found.size == 1 && login == null && !busy && vm.prefs.server.isEmpty()) {
            val f = found[0]
            if (f.hello.auth) login = f else connect(f.base, f.hello, null)
        }
    }

    Column(
        Modifier.fillMaxSize().backdrop(p).statusBarsPadding().navigationBarsPadding().imePadding()
            .verticalScroll(rememberScrollState()).padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.Start,
    ) {
        Spacer(Modifier.height(36.dp))
        Brand(24)
        Spacer(Modifier.height(30.dp))
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(color = p.acc)) { append("[phone ~]$ ") }
                withStyle(SpanStyle(color = p.fg)) { append(if (scanning) "vidbox --discover" else "vidbox --discover  # готово") }
            },
            style = mono(12.5.sp),
        )
        Spacer(Modifier.height(8.dp))
        Text("Знайди свій ПК", style = display(36.sp), color = p.fg)
        Spacer(Modifier.height(8.dp))
        Text(
            "Запусти VidBox на комп'ютері (start.bat). Якщо телефон у тій самій Wi-Fi мережі, ПК з'явиться тут сам.",
            style = body(15.sp), color = p.mute, modifier = Modifier.widthIn(max = 520.dp),
        )
        Spacer(Modifier.height(20.dp))

        Win("~/", Modifier.fillMaxWidth().widthIn(max = 560.dp), bold = "network") {
            Column(Modifier.padding(vertical = 6.dp)) {
                found.forEach { f ->
                    val sel = login?.base == f.base
                    Row(
                        Modifier.fillMaxWidth().background(if (sel) p.acc.copy(alpha = .1f) else Color.Transparent)
                            .clickable(enabled = !busy) { connect(f.base, f.hello, null) }.padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Ic.monitor, null, tint = p.acc, modifier = Modifier.size(26.dp))
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(f.hello.host, style = mono(15.sp, FontWeight.Bold), color = p.fg)
                            Text(f.base.removePrefix("http://") + "  ·  VidBox " + f.hello.version, style = mono(11.5.sp), color = p.mute)
                        }
                        if (f.hello.auth) Icon(Ic.lock, "Потрібен пароль", tint = p.mute, modifier = Modifier.size(19.dp))
                        Icon(Ic.right, null, tint = p.mute, modifier = Modifier.size(20.dp))
                    }
                }
                if (scanning) {
                    val t = rememberInfiniteTransition(label = "scan")
                    val a = t.animateFloat(1f, 0f, infiniteRepeatable(tween(900, easing = Blink), RepeatMode.Restart), label = "a").value
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Ic.wifi, null, tint = p.acc.copy(alpha = .4f + .6f * a), modifier = Modifier.size(22.dp))
                        Spacer(Modifier.width(12.dp))
                        Text("Шукаю VidBox у мережі…", style = mono(13.sp), color = p.mute)
                    }
                } else if (found.isEmpty()) {
                    Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                        Text("Нічого не знайшлося", style = mono(13.5.sp, FontWeight.Bold), color = p.fg)
                        Text(
                            "Перевір, що VidBox запущений, а телефон у тому ж Wi-Fi. Можна ввести адресу вручну: вона є у вікні VidBox на ПК, рядок «На телефоні».",
                            style = body(13.5.sp), color = p.mute,
                        )
                    }
                }
                if (!scanning) {
                    Text(
                        "Шукати ще раз", style = mono(12.5.sp, FontWeight.Bold), color = p.acc,
                        modifier = Modifier.padding(horizontal = 8.dp).clip(RoundedCornerShape(6.dp)).clickable { round++ }.padding(6.dp),
                    )
                }
            }
        }

        val lg = login
        if (lg != null) {
            Spacer(Modifier.height(14.dp))
            Win("~/", Modifier.fillMaxWidth().widthIn(max = 560.dp), bold = "login@" + lg.hello.host) {
                Column(Modifier.padding(14.dp)) {
                    Text("На цьому ПК увімкнено пароль.", style = body(14.sp), color = p.mute)
                    Spacer(Modifier.height(10.dp))
                    Field(password, { password = it }, "пароль", secret = true, onGo = { connect(lg.base, lg.hello, password) })
                    Spacer(Modifier.height(10.dp))
                    Btn("Увійти", { connect(lg.base, lg.hello, password) }, Modifier.fillMaxWidth(), icon = Ic.lock, kind = Kind.Primary, enabled = !busy)
                }
            }
        }

        Spacer(Modifier.height(14.dp))
        Win("~/", Modifier.fillMaxWidth().widthIn(max = 560.dp), bold = "manual") {
            Column(Modifier.padding(14.dp)) {
                Text("Адреса ПК", style = body(14.sp), color = p.mute)
                Spacer(Modifier.height(8.dp))
                Field(manual, { manual = it }, "192.168.1.10:8800", onGo = { connect(normalize(manual), null, null) })
                Spacer(Modifier.height(10.dp))
                Btn("Підключитись", { connect(normalize(manual), null, null) }, Modifier.fillMaxWidth(), icon = Ic.right, enabled = !busy && manual.isNotBlank())
            }
        }

        error?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, style = mono(12.5.sp), color = Color(0xFFFF8A7A))
        }
        if (busy) {
            Spacer(Modifier.height(12.dp))
            Text("Підключаюсь…", style = mono(12.5.sp), color = p.mute)
        }
        Spacer(Modifier.height(40.dp))
    }
}

private fun normalize(s: String): String {
    var a = s.trim().trimEnd('/')
    if (!a.startsWith("http://") && !a.startsWith("https://")) a = "http://$a"
    val hostPart = a.substringAfter("://")
    if (!hostPart.contains(':')) a += ":8800"
    return a
}

@Composable
private fun Field(value: String, onChange: (String) -> Unit, hint: String, secret: Boolean = false, onGo: () -> Unit) {
    val p = LocalPal.current
    Box(
        Modifier.fillMaxWidth().height(46.dp).clip(RoundedCornerShape(9.dp)).background(Color.Black.copy(alpha = .25f))
            .border(1.dp, p.line, RoundedCornerShape(9.dp)).padding(horizontal = 12.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        if (value.isEmpty()) Text(hint, style = mono(14.sp), color = p.mute)
        BasicTextField(
            value = value, onValueChange = onChange, singleLine = true,
            textStyle = mono(14.sp).copy(color = p.fg), cursorBrush = SolidColor(p.acc),
            visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (secret) KeyboardType.Password else KeyboardType.Uri, imeAction = ImeAction.Go),
            keyboardActions = KeyboardActions(onGo = { onGo() }),
            modifier = Modifier.fillMaxWidth(),
        )
    }
}
