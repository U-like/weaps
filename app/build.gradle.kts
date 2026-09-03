plugins {
    id("com.android.application")
}

android {
    namespace = "dev.videomosaic.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.videomosaic.app.v041"
        minSdk = 26
        targetSdk = 36
        versionCode = 41
        versionName = "0.4.1-control"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
