package app.vidbox.data

import android.content.Context
import android.net.ConnectivityManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.SocketTimeoutException

/**
 * Шукає VidBox у домашній мережі двома способами:
 * 1) UDP-пакет «VIDBOX?» на весь Wi-Fi — сервер одразу відповідає;
 * 2) якщо роутер такі пакети ріже — перебирає адреси підмережі на порту 8800.
 */
class Discovery(private val ctx: Context, private val api: Api) {
    data class Found(val base: String, val hello: Hello)

    private data class Net(val ip: Inet4Address, val prefix: Int)

    private fun localNet(): Net? {
        val cm = ctx.getSystemService(ConnectivityManager::class.java) ?: return null
        val lp = cm.getLinkProperties(cm.activeNetwork) ?: return null
        return lp.linkAddresses.firstNotNullOfOrNull { la ->
            (la.address as? Inet4Address)?.takeIf { !it.isLoopbackAddress }?.let { Net(it, la.prefixLength) }
        }
    }

    private fun broadcastOf(n: Net): InetAddress {
        val ip = n.ip.address
        val mask = if (n.prefix == 0) 0 else -1 shl (32 - n.prefix)
        val v = ((ip[0].toInt() and 255) shl 24) or ((ip[1].toInt() and 255) shl 16) or ((ip[2].toInt() and 255) shl 8) or (ip[3].toInt() and 255)
        val b = v or mask.inv()
        return InetAddress.getByAddress(byteArrayOf((b ushr 24).toByte(), (b ushr 16).toByte(), (b ushr 8).toByte(), b.toByte()))
    }

    fun find(): Flow<Found> = channelFlow {
        val seen = HashSet<String>()
        suspend fun emit(f: Found) {
            val ok = synchronized(seen) { seen.add(f.base) }
            if (ok) send(f)
        }
        val net = localNet()

        launch(Dispatchers.IO) {
            try {
                DatagramSocket().use { s ->
                    s.broadcast = true
                    s.soTimeout = 400
                    val msg = "VIDBOX?".toByteArray()
                    val targets = listOfNotNull(InetAddress.getByName("255.255.255.255"), net?.let { broadcastOf(it) })
                    val until = System.currentTimeMillis() + 2500
                    var nextSend = 0L
                    val buf = ByteArray(1024)
                    while (System.currentTimeMillis() < until) {
                        if (System.currentTimeMillis() >= nextSend) {
                            for (t in targets) runCatching { s.send(DatagramPacket(msg, msg.size, t, DISCOVERY_PORT)) }
                            nextSend = System.currentTimeMillis() + 800
                        }
                        try {
                            val p = DatagramPacket(buf, buf.size)
                            s.receive(p)
                            val h = parseHello(JSONObject(String(p.data, 0, p.length, Charsets.UTF_8)))
                            if (h.app == "VidBox") emit(Found("http://${p.address.hostAddress}:${h.port}", h))
                        } catch (e: SocketTimeoutException) {
                            // чекаємо далі
                        } catch (e: Exception) {
                            // чужий пакет
                        }
                    }
                }
            } catch (e: Exception) {
                // широкомовні пакети заборонені — лишається перебір
            }
        }

        launch(Dispatchers.IO) {
            delay(600)
            val n = net ?: return@launch
            if (n.prefix < 20) return@launch          // занадто велика мережа для перебору
            val own = n.ip.address
            val prefix = "${own[0].toInt() and 255}.${own[1].toInt() and 255}.${own[2].toInt() and 255}."
            val gate = Semaphore(48)
            val jobs = (1..254).map { last ->
                launch {
                    gate.withPermit {
                        val base = "http://$prefix$last:8800"
                        api.hello(base)?.let { emit(Found(base, it)) }
                    }
                }
            }
            jobs.forEach { it.join() }
        }
    }.flowOn(Dispatchers.IO)

    companion object {
        const val DISCOVERY_PORT = 48800
    }
}
