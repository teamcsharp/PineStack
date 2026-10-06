package fm.pinebox.dualwifi;

/** Run by root app_process on the existing userdebug GSI. The system package
 * owns the overlay, satisfying the resource's system policy and surviving
 * boot's shell-overlay cleanup. Reflection avoids a hidden-SDK build. */
public final class OverlayConfig {
    public static void main(String[] args) throws Exception {
        Class<?> fab = Class.forName("android.content.om.FabricatedOverlay");
        Class<?> builder = Class.forName("android.content.om.FabricatedOverlay$Builder");
        Object b = builder.getConstructor(String.class, String.class, String.class)
            .newInstance("android", "PineCamDualWifi", "com.android.wifi.resources");
        builder.getMethod("setTargetOverlayable", String.class).invoke(b, "WifiCustomization");
        builder.getMethod("setResourceValue", String.class, int.class, int.class).invoke(b,
            "com.android.wifi.resources:bool/config_wifiMultiStaLocalOnlyConcurrencyEnabled", 0x12, 1);
        Object overlay = builder.getMethod("build").invoke(b);
        Class<?> tx = Class.forName("android.content.om.OverlayManagerTransaction");
        Class<?> tb = Class.forName("android.content.om.OverlayManagerTransaction$Builder");
        Object t = tb.getConstructor().newInstance();
        tb.getMethod("registerFabricatedOverlay", fab).invoke(t, overlay);
        Class<?> id = Class.forName("android.content.om.OverlayIdentifier");
        Object identifier = id.getConstructor(String.class, String.class)
            .newInstance("android", "PineCamDualWifi");
        tb.getMethod("setEnabled", id, boolean.class, int.class).invoke(t, identifier, true, 0);
        Object transaction = tb.getMethod("build").invoke(t);
        Class<?> binder = Class.forName("android.os.IBinder");
        Object service = Class.forName("android.os.ServiceManager").getMethod("getService", String.class)
            .invoke(null, "overlay");
        Object manager = Class.forName("android.content.om.IOverlayManager$Stub")
            .getMethod("asInterface", binder).invoke(null, service);
        Class.forName("android.content.om.IOverlayManager").getMethod("commit", tx)
            .invoke(manager, transaction);
        System.out.println("Enabled android:PineCamDualWifi");
    }
}
