/* PineBoxKiosk - the Lenovo Tab M9 (TB310FU, LineageOS 21 / SDK 34) as a
 * Pine Box terminal.
 *
 * The tablet has NO Google Play Services, so nothing here may depend on
 * play-services-* or firebase-*; every dependency below is plain AndroidX
 * or OkHttp, which do not need them.
 */
pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "PineBoxKiosk"
include(":app")
