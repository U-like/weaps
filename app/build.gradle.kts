plugins {
    id("com.android.application")
}

android {
    namespace = "dev.videomosaic.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.videomosaic.app.v050"
        minSdk = 26
        targetSdk = 36
        versionCode = 50
        versionName = "0.5.0-mosaic"
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

dependencies {
    val media3Version = "1.11.0"
    implementation("androidx.media3:media3-exoplayer:$media3Version")
    implementation("androidx.media3:media3-ui:$media3Version")
    implementation("androidx.media3:media3-transformer:$media3Version")
    implementation("androidx.media3:media3-effect:$media3Version")
}
