# The bridge is called from JavaScript BY NAME. R8 cannot see those calls,
# so without this the whole of window.pineDesktop becomes undefined in a
# minified build - silently, at runtime, on the tablet.
-keepclassmembers class com.pinebox.kiosk.bridge.PineDesktopBridge {
    public *;
}
-keepattributes JavascriptInterface, *Annotation*

# OkHttp's optional platform hooks.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
