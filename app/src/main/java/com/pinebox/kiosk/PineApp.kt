package com.pinebox.kiosk

import android.app.Application
import android.webkit.WebView
import com.pinebox.kiosk.config.ConfigStore
import com.pinebox.kiosk.feed.StationFeed
import com.pinebox.kiosk.net.StationClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.Dispatchers

/**
 * The application object, and the whole of the app's dependency wiring.
 *
 * No DI framework: there are four singletons and one of them is a poller.
 * Hilt would add a build-time processor and a compile step to a project
 * that has to be buildable from a cold checkout on a box that is still
 * having its toolchain installed.
 *
 * Everything here is process-scoped ON PURPOSE. [StationFeed] in particular
 * must outlive the activity: it is the one poller, and standing it up per
 * activity would mean two of them for the duration of any recreate.
 */
class PineApp : Application() {

    /* THE ROLLING RECORD OF THE SCREEN.
     *
     * On the APPLICATION rather than the activity, because it records the
     * tablet and not this app's window - it must keep running while the
     * operator is in DGX Terminal, in the Tailscale app, or on the launcher.
     * MainActivity only tells it when the screen goes dark; it does not own
     * it. See replay/ScreenReplay.kt. */
    val replay: com.pinebox.kiosk.replay.ScreenReplay by lazy {
        com.pinebox.kiosk.replay.ScreenReplay(this)
    }

    /* THE MIX, CAPTURED OFF THE PAGE. On the APPLICATION for the same reason
     * the screen recorder is: it captures the tablet, not this activity, and
     * must outlive any one of them. Not started here - see audio/AirTap.kt
     * on why it is asked for rather than assumed. */
    val airTap: com.pinebox.kiosk.audio.AirTap by lazy {
        com.pinebox.kiosk.audio.AirTap(this)
    }

    /** SupervisorJob: one failed bridge call must not cancel the feed. */
    val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val configStore: ConfigStore by lazy { ConfigStore(this) }
    val client: StationClient by lazy { StationClient(configStore) }
    val feed: StationFeed by lazy { StationFeed(client, scope) }

    /** The gallery on the home screen and the keyguard, every five minutes. */
    val wallpaper: com.pinebox.kiosk.gallery.WallpaperWatch by lazy {
        com.pinebox.kiosk.gallery.WallpaperWatch(this, client, feed, scope)
    }

    override fun onCreate() {
        super.onCreate()

        /* HERE, NOT IN THE ACTIVITY. The wallpaper's whole point is to be
         * right when the app is NOT the thing on screen - a locked tablet
         * showing the piece on the block. Started from the activity it would
         * stop at the moment it starts mattering. */
        wallpaper.start()

        /* Remote debugging over `adb forward` + chrome://inspect. The
         * tablet is a userdebug LineageOS build on a private LAN with no
         * Play Services and no user accounts; the ability to open the
         * panel's console from the desk is worth more here than the
         * theoretical exposure, and it is how the >=900px CSS branch was
         * confirmed on the real screen. */
        if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true)
    }

    override fun onTerminate() {
        /* Only ever called by the test runtime, but leaving a poller
         * running against a dead process is the kind of thing that turns
         * into a starved station later. */
        scope.cancel()
        super.onTerminate()
    }

    companion object {
        fun of(context: android.content.Context): PineApp =
            context.applicationContext as PineApp
    }
}
