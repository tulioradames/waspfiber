import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Assinatura do APK: lida de android/assinatura.properties (fora do git) ou das
// variaveis de ambiente do GitHub Actions. Sem nada disso, sai assinado com a
// chave de debug (serve pra testar, nao pra distribuir).
val assinatura = Properties().apply {
    val arquivo = rootProject.file("assinatura.properties")
    if (arquivo.exists()) arquivo.inputStream().use { load(it) }
}
fun valorAssinatura(chave: String, ambiente: String): String? =
    assinatura.getProperty(chave) ?: System.getenv(ambiente)

android {
    namespace = "com.waspfiber.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.waspfiber.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "M0.1"
    }

    signingConfigs {
        val caminho = valorAssinatura("arquivo", "WASP_KEYSTORE")
        if (caminho != null && file(caminho).exists()) {
            create("release") {
                storeFile = file(caminho)
                storePassword = valorAssinatura("senha", "WASP_KEYSTORE_SENHA")
                keyAlias = valorAssinatura("alias", "WASP_KEY_ALIAS") ?: "waspfiber"
                keyPassword = valorAssinatura("senha", "WASP_KEYSTORE_SENHA")
                storeType = "pkcs12"
            }
        }
    }

    buildTypes {
        // o APK de release fala com o servidor de verdade; o de teste (debug), com um
        // servidor de teste no computador do desenvolvedor (10.0.2.2 = o PC, no emulador)
        debug {
            applicationIdSuffix = ".teste"       // instala junto com o app de verdade
            buildConfigField("String", "SERVIDOR", "\"http://10.0.2.2:8799\"")
            manifestPlaceholders["textoAberto"] = "true"
        }
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
            buildConfigField("String", "SERVIDOR", "\"https://servidor.taild43fdd.ts.net\"")
            manifestPlaceholders["textoAberto"] = "false"
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
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // mapa (OpenStreetMap / satelite Esri), sem chave e sem Google
    implementation("org.osmdroid:osmdroid-android:6.1.20")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
