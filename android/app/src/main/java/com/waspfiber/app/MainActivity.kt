package com.waspfiber.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import org.osmdroid.config.Configuration
import org.osmdroid.util.GeoPoint
import java.io.File

/** As telas do app, em pilha (voltar = tirar a de cima). */
sealed interface Tela {
    data object Login : Tela
    data object Cidades : Tela
    data class Mapa(val cidade: Cidade) : Tela
    /** item == null: equipamento novo (no ponto sugerido) */
    data class Equipamento(val cidade: Cidade, val item: ItemDiagrama?, val ponto: GeoPoint?) : Tela
    /** o diagrama de fusao do POP / CEO / CTO */
    data class Fusoes(val cidade: Cidade, val item: ItemDiagrama) : Tela
}

val Cores = darkColorScheme(
    primary = Color(0xFF4DD0E1), onPrimary = Color(0xFF0B2529),
    primaryContainer = Color(0xFF4DD0E1), onPrimaryContainer = Color(0xFF0B2529),
    secondaryContainer = Color(0xFF262E37), onSecondaryContainer = Color(0xFFEEF1F4),
    tertiaryContainer = Color(0xFF262E37), onTertiaryContainer = Color(0xFFEEF1F4),
    secondary = Color(0xFF5AD18A), onSecondary = Color(0xFF06210F),
    background = Color(0xFF0E1115), onBackground = Color(0xFFEEF1F4),
    surface = Color(0xFF161A1F), onSurface = Color(0xFFEEF1F4),
    surfaceVariant = Color(0xFF1E242B), onSurfaceVariant = Color(0xFF8B98A4),
    surfaceContainer = Color(0xFF1E242B), surfaceContainerHigh = Color(0xFF262E37),
    outline = Color(0xFF2A323B), error = Color(0xFFE5736A),
)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // mapa: identifica o app pro servidor de tiles e guarda o cache dentro do app
        Configuration.getInstance().apply {
            userAgentValue = "WaspFiber-Android/" + packageName
            osmdroidBasePath = File(filesDir, "osmdroid")
            osmdroidTileCache = File(cacheDir, "tiles")
        }
        setContent { MaterialTheme(colorScheme = Cores) { App() } }
    }
}

@Composable
fun App() {
    val ctx = LocalContext.current
    var sessao by remember { mutableStateOf(Preferencias.sessao(ctx)) }
    Api.token = sessao?.token
    val pilha = remember {
        mutableStateListOf<Tela>(if (sessao == null) Tela.Login else Tela.Cidades)
    }
    var aviso by remember { mutableStateOf("") }

    fun ir(tela: Tela) = pilha.add(tela)
    fun voltar() { if (pilha.size > 1) pilha.removeAt(pilha.lastIndex) }
    fun sair(mensagem: String = "") {
        Preferencias.esquecerToken(ctx)
        Api.token = null
        sessao = null
        aviso = mensagem
        pilha.clear()
        pilha.add(Tela.Login)
    }
    /** erro do servidor: sessao vencida volta pro login */
    fun tratar(erro: ErroServidor): String {
        if (erro.status == 401) sair("Sua sessao terminou. Entre de novo.")
        return erro.message ?: "Erro"
    }

    BackHandler(enabled = pilha.size > 1) { voltar() }

    when (val tela = pilha.last()) {
        Tela.Login -> TelaLogin(aviso) { nova ->
            Preferencias.guardar(ctx, nova)
            sessao = nova
            aviso = ""
            pilha.clear()
            pilha.add(Tela.Cidades)
        }
        Tela.Cidades -> TelaCidades(sessao, aoAbrir = { ir(Tela.Mapa(it)) },
                                    aoSair = { sair() }, tratar = ::tratar)
        is Tela.Mapa -> TelaMapa(tela.cidade, aoVoltar = ::voltar,
                                 aoEquipamento = { item, ponto -> ir(Tela.Equipamento(tela.cidade, item, ponto)) },
                                 aoFusoes = { ir(Tela.Fusoes(tela.cidade, it)) },
                                 tratar = ::tratar)
        is Tela.Equipamento -> TelaEquipamento(tela.cidade, tela.item, tela.ponto,
                                               aoVoltar = ::voltar,
                                               aoFusoes = { ir(Tela.Fusoes(tela.cidade, it)) },
                                               tratar = ::tratar)
        is Tela.Fusoes -> TelaFusoes(tela.cidade, tela.item, aoVoltar = ::voltar, tratar = ::tratar)
    }
}
