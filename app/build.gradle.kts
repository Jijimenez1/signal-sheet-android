plugins {
    id("com.android.application")
}

val buildNumber = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()

android {
    namespace = "com.javi.signalsheet"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.javi.signalsheet"
        minSdk = 26
        targetSdk = 34
        versionCode = buildNumber
        versionName = "1.$buildNumber"
    }

    signingConfigs {
        create("share") {
            storeFile = file("signalsheet.jks")
            storePassword = "signalsheet"
            keyAlias = "signalsheet"
            keyPassword = "signalsheet"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("share")
        }
        debug {
            signingConfig = signingConfigs.getByName("share")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}


