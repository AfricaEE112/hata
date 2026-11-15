package app.vidbox

import android.app.Application
import app.vidbox.data.Api
import app.vidbox.data.Prefs
import coil.ImageLoader
import coil.ImageLoaderFactory

class VidBoxApp : Application(), ImageLoaderFactory {
    lateinit var prefs: Prefs
        private set
    lateinit var api: Api
        private set

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        api = Api(prefs)
    }

    // Обкладинки, нарізки й кадри йдуть тим самим клієнтом, що й API (з токеном входу).
    // Адреси містять ?v=…, тож кешуємо назавжди, не дивлячись на заголовки.
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .okHttpClient(api.client)
        .respectCacheHeaders(false)
        .crossfade(180)
        .build()
}
