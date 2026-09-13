package com.pinebox.kiosk.net

import com.pinebox.kiosk.BuildConfig
import com.pinebox.kiosk.config.Config

/**
 * WHICH ADDRESS THE STATION IS ON TODAY.
 *
 * "I want to be able to connect the tablet up to my phone through 3G or the
 *  localized network and be able to connect and interact with the radio...
 *  through Tailscale."
 *
 * The terminal has one station and two roads to it, and which one works
 * depends on where the tablet is standing:
 *
 *   http://10.89.1.246:8096              the LAN, at home
 *   http://100.74.95.59:8096             the tailnet, from anywhere
 *   http://lilspark.tail1fec29.ts.net    the same, by MagicDNS name
 *
 * THE OPERATOR SHOULD NEVER PICK. Carrying the tablet out of the house and
 * having to change a setting to keep listening is the kind of thing that
 * means you stop carrying the tablet out of the house. So the terminal tries
 * them in order and uses the first that answers, and tries again whenever a
 * load fails - which is exactly when the road has changed underneath it.
 *
 * THE LAN GOES FIRST, and not arbitrarily. Tailscale will happily carry
 * traffic between two machines sitting on the same switch, but it is a longer
 * path through a userspace TUN, and on this tablet the panel is one very
 * large document. When the LAN is there it is the right road; the tailnet is
 * the one that still works when it is not.
 *
 * THE ADDRESS BEFORE THE NAME. 100.74.95.59 needs no resolver at all, while
 * the MagicDNS name needs the tablet to be accepting Tailscale's DNS - which
 * is a setting inside the Tailscale app and therefore not something this
 * terminal can promise. The name is kept last so it still rescues the case
 * where the tailnet address has changed and DNS is working.
 *
 * NOTE THE NETWORK POLICY. Every host named here must also appear in
 * res/xml/network_security_config.xml, because cleartext HTTP is permitted
 * per host by name and the base config fails closed. A road added here and
 * not there is a road that is silently refused before a packet is sent.
 */
object Reach {

    /** The one that answered, or null before the first probe. */
    @Volatile
    private var chosen: String? = null

    /** For the diagnostics report and the offline banner. */
    @Volatile
    var said: String = "not yet probed"
        private set

    /**
     * In the order they should be tried. Blank entries are dropped so a
     * terminal with no tailnet configured simply has one road, and
     * duplicates are dropped so a tailnet-only setup does not probe the same
     * address twice.
     */
    fun candidates(cfg: Config): List<String> = listOf(
        cfg.base,
        cfg.tailnetUrl.trimEnd('/'),
        cfg.tailnetName.trimEnd('/'),
    ).filter { it.isNotBlank() }.distinct()

    /**
     * The base to use right now. Before any probe, and after a probe that
     * found nothing, this is the configured one - so the terminal behaves
     * exactly as it did before any of this existed rather than refusing to
     * load.
     */
    fun base(cfg: Config): String = chosen ?: cfg.base

    /**
     * DID ANY ROAD ACTUALLY ANSWER?
     *
     * settle() returns cfg.base when nothing did - deliberately, so the
     * terminal fails against the address the operator expects - which means
     * its RETURN VALUE cannot be used to tell success from failure. Anything
     * reporting on readiness has to ask this instead.
     */
    val answered: Boolean get() = chosen != null

    /** Whether the tailnet is carrying us, which the report wants to say. */
    fun onTailnet(cfg: Config): Boolean {
        val now = chosen ?: return false
        return now != cfg.base
    }

    /** Forget the choice, so the next settle() probes again from the top. */
    fun forget() {
        chosen = null
        said = "forgotten - will probe again"
    }

    /**
     * Try each road and keep the first that answers.
     *
     * `answers` is handed in rather than reached for, so this holds no
     * opinion about HTTP and can be exercised without a station.
     *
     * @return the base that will be used, which is the configured one when
     *   nothing answered - a terminal that cannot reach the station should
     *   fail against the address the operator expects, not against a
     *   tailnet address they have never seen.
     */
    fun settle(cfg: Config, answers: (String) -> Boolean): String {
        val roads = candidates(cfg)
        for (road in roads) {
            val ok = try { answers(road) } catch (err: Exception) { false }
            if (ok) {
                chosen = road
                said = if (road == cfg.base) "on the LAN" else "over the tailnet - $road"
                return road
            }
        }
        chosen = null
        said = "nothing answered on " + roads.size + " road(s)"
        return cfg.base
    }

    /** What the build shipped, for the first run before anything is stored. */
    val defaultTailnetUrl: String get() = BuildConfig.DEFAULT_TAILNET_URL
    val defaultTailnetName: String get() = BuildConfig.DEFAULT_TAILNET_NAME
}
