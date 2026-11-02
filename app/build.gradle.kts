plugins {
    id("com.android.application")
}

android {
    namespace = "com.javi.signalsheet"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.javi.signalsheet"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release { isMinifyEnabled = false }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // Opens the Signal Sheet page full-screen in Chrome, so your existing Claude sign-in works
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.5.0")
}
