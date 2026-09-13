plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

/* The C++ sampler in app/src/main/cpp/ is written by a separate agent and
 * has its own CMakeLists.txt. The stanza below turns itself on only when
 * that file exists: wiring externalNativeBuild unconditionally would fail
 * the build of an app that is otherwise complete and installable, and the
 * two halves land at different times.
 *
 * NOTE FOR AN OFFLINE BUILD BOX: cpp/CMakeLists.txt fetches Oboe 1.9.0 with
 * FetchContent on the first configure. Clone it to
 * app/src/main/cpp/third_party/oboe beforehand and the vendored copy is
 * used with no flags - see the header of that file. */
val nativeCmake = file("src/main/cpp/CMakeLists.txt")
val hasNative = nativeCmake.exists()

android {
    namespace = "com.pinebox.kiosk"
    compileSdk = 34

    /* r26b. Chosen because it is the NDK bundled with the AGP 8.5 line and
     * is the last release with full arm64 LTO support that the audio engine
     * is expected to want. Change here AND in the build box's SDK manager. */
    ndkVersion = "26.1.10909125"

    defaultConfig {
        applicationId = "com.pinebox.kiosk"
        /* minSdk 30: the device runs SDK 34 and nothing older will ever see
         * this build, so we are free to use the SDK 30 window-inset APIs
         * (WindowInsetsController) with no compat branch. */
        minSdk = 30
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            /* Lenovo TB310FU / MediaTek MT6768 is arm64-v8a. One ABI. */
            abiFilters += "arm64-v8a"
        }

        if (hasNative) {
            externalNativeBuild {
                cmake {
                    /* -fno-finite-math-only matches the engine's own
                     * reasoning (cpp/CMakeLists.txt): its envelope compares
                     * against exact zero to decide when a voice is
                     * finished, and a compiler told to assume no denormals
                     * and no exact zero leaves voices ringing.
                     *
                     * c++_shared because the core links std::map and
                     * std::vector and a bad_alloc has to be able to unwind
                     * through the JNI bridge rather than terminate. */
                    cppFlags += listOf("-std=c++17", "-fno-finite-math-only")
                    arguments += listOf("-DANDROID_STL=c++_shared")
                }
            }
        }

        /* The station's address is compiled in as the DEFAULT only; the
         * bridge's writeConfig can move it at runtime. Note that moving it
         * off this host also needs res/xml/network_security_config.xml
         * edited, because cleartext is permitted per-host by name. */
        buildConfigField("String", "DEFAULT_BASE_URL", "\"http://10.89.1.246:8096\"")

        /* THE WAY HOME FROM OUTSIDE THE HOUSE. Tried after the LAN by
         * net/Reach.kt, which uses the first road that answers. Both of
         * these must also be named in network_security_config.xml or the
         * request is refused before a packet leaves. */
        buildConfigField("String", "DEFAULT_TAILNET_URL", "\"http://100.74.95.59:8096\"")
        buildConfigField("String", "DEFAULT_TAILNET_NAME",
            "\"http://lilspark.tail1fec29.ts.net:8096\"")
    }

    if (hasNative) {
        externalNativeBuild {
            cmake {
                path = nativeCmake
                version = "3.22.1"
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ""
        }
        release {
            /* R8 off. The @JavascriptInterface surface is reached only by
             * name from JavaScript, and a kiosk that mysteriously loses
             * window.pineDesktop in release is worse than an APK 400 kB
             * bigger. The keep rules in proguard-rules.pro are kept correct
             * anyway so this can be flipped on with one line. */
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            /* Signed with the debug key on purpose: the tablet is userdebug
             * LineageOS on a private LAN and there is no Play listing. Swap
             * in a real signingConfig if that ever changes. */
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf("META-INF/*.kotlin_module", "META-INF/AL2.0", "META-INF/LGPL2.1")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = false
    }

    lint {
        // A kiosk that stops building because a lint rule turned into an
        // error is a kiosk nobody can patch at 3am.
        abortOnError = false
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.webkit)
    implementation(libs.androidx.drawerlayout)
    implementation(libs.androidx.documentfile)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    /* DGX Terminal. See terminal/DgxSsh.kt. */
    implementation(libs.jsch)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    /* See gradle/libs.versions.toml: android.jar's org.json is a throwing
     * stub under JVM unit tests. This puts the real one first on the
     * classpath so StationRows can be tested without a device. */
    testImplementation(libs.org.json)
}
