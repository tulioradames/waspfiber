package com.waspfiber.app

import android.Manifest
import android.content.pm.PackageManager
import android.location.Location
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.GpsFixed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.osmdroid.util.GeoPoint

/** Criar (item == null) ou corrigir um POP / CEO / CTO: tipo, nome, endereco
 *  e a localizacao pelo GPS do celular. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaEquipamento(cidade: Cidade, item: ItemDiagrama?, ponto: GeoPoint?, aoVoltar: () -> Unit,
                    aoFusoes: (ItemDiagrama) -> Unit, tratar: (ErroServidor) -> String) {
    val ctx = LocalContext.current
    val escopo = rememberCoroutineScope()
    var tipo by remember { mutableStateOf(item?.tipo?.ifEmpty { "CTO" } ?: "CTO") }
    var nome by remember { mutableStateOf(item?.titulo ?: "") }
    var endereco by remember { mutableStateOf(item?.endereco ?: "") }
    var lat by remember { mutableStateOf(item?.lat ?: ponto?.latitude) }
    var lon by remember { mutableStateOf(item?.lon ?: ponto?.longitude) }
    var origem by remember { mutableStateOf(if (item?.lat != null) "salva" else if (ponto != null) "mapa" else "") }
    var diagrama by remember { mutableStateOf<Diagrama?>(null) }
    var carregando by remember { mutableStateOf(item != null) }
    var salvando by remember { mutableStateOf(false) }
    var mensagem by remember { mutableStateOf("") }
    var conflito by remember { mutableStateOf("") }
    var gpsLigado by remember { mutableStateOf(false) }
    var ultimaLeitura by remember { mutableStateOf<Location?>(null) }
    var permitido by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION)
                       == PackageManager.PERMISSION_GRANTED)
    }
    val pedirPermissao = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { r ->
        permitido = r.values.any { it }
        gpsLigado = permitido
    }

    // equipamento existente: busca o diagrama inteiro (o servidor precisa dele pra salvar)
    LaunchedEffect(item?.id) {
        if (item != null) {
            try { diagrama = Api.abrir(cidade.id, item.id) } catch (e: ErroServidor) { mensagem = tratar(e) }
            carregando = false
        }
    }
    // GPS: so fica ligado enquanto a pessoa esta "usando minha posicao"
    DisposableEffect(gpsLigado, permitido) {
        val gps = if (gpsLigado && permitido) Gps(ctx) { leitura ->
            // fica com a leitura mais precisa
            val atual = ultimaLeitura
            if (atual == null || leitura.accuracy <= atual.accuracy ||
                leitura.time - atual.time > 15000) ultimaLeitura = leitura
        } else null
        if (gps != null && !gps.comecar()) mensagem = "Ligue a localizacao (GPS) do celular."
        onDispose { gps?.parar() }
    }

    fun usarLeitura() {
        ultimaLeitura?.let {
            lat = it.latitude; lon = it.longitude; origem = "gps"
            gpsLigado = false
        }
    }

    fun salvar(forcar: Boolean = false) {
        if (nome.isBlank()) { mensagem = "Informe o nome."; return }
        salvando = true
        mensagem = ""
        escopo.launch {
            try {
                if (item == null) {
                    val conteudo = Local.novoDiagrama(tipo, nome.trim(), cidade.titulo, endereco.trim(), lat, lon)
                    Api.criarDiagrama(cidade.id, nome.trim(), conteudo)
                } else {
                    val d = diagrama ?: Api.abrir(cidade.id, item.id)
                    val conteudo = Local.atualizar(JSONObject(d.conteudo.toString()), tipo, nome.trim(),
                                                   endereco.trim(), lat, lon)
                    Api.salvar(cidade.id, item.id, conteudo, d.versao, forcar)
                }
                aoVoltar()
            } catch (e: ErroServidor) {
                if (e.status == 409) conflito = e.extra?.optString("alterado_por").orEmpty().ifEmpty { "Outra pessoa" }
                else mensagem = tratar(e)
            } finally {
                salvando = false
            }
        }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                navigationIcon = { IconButton(onClick = aoVoltar) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Voltar") } },
                title = { Text(if (item == null) "Novo equipamento" else item.titulo, fontSize = 19.sp) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
    ) { pad ->
        if (carregando) Box(Modifier.fillMaxSize().padding(pad)) {
            CircularProgressIndicator(Modifier.align(Alignment.Center))
        } else Column(
            Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("Tipo", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (t in listOf("POP", "CEO", "CTO")) {
                    FilterChip(selected = tipo == t, onClick = { tipo = t },
                               label = { Text(t) }, leadingIcon = { IconeTipo(t, 18) })
                }
            }
            OutlinedTextField(nome, { nome = it }, label = { Text("Nome / identificacao") },
                              placeholder = { Text("Ex.: CTO Prata 03") }, singleLine = true,
                              modifier = Modifier.fillMaxWidth())
            OutlinedTextField(endereco, { endereco = it }, label = { Text("Endereco") },
                              modifier = Modifier.fillMaxWidth())

            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant,
                                                  contentColor = MaterialTheme.colorScheme.onSurface)) {
                Column(Modifier.padding(16.dp)) {
                    Text("Localizacao", fontSize = 15.sp)
                    Spacer(Modifier.height(6.dp))
                    Text(if (lat != null && lon != null) "%.6f, %.6f".format(lat, lon) else "Sem localizacao",
                         fontSize = 18.sp)
                    Text(when (origem) {
                        "gps" -> "Da sua posicao (GPS)"
                        "mapa" -> "Ponto do mapa / da sua posicao ao abrir"
                        "salva" -> "A que ja estava salva"
                        else -> "Use o GPS na frente da caixa"
                    }, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
                    Spacer(Modifier.height(12.dp))
                    if (gpsLigado) {
                        val l = ultimaLeitura
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(10.dp))
                            Text(if (l == null) "Procurando o GPS..."
                                 else "Precisao: ±%.0f m%s".format(l.accuracy,
                                     if (l.accuracy <= 10) " (boa)" else " (espere melhorar)"),
                                 color = if (l != null && l.accuracy <= 10) Color(0xFF5AD18A)
                                         else MaterialTheme.colorScheme.onSurface)
                        }
                        Spacer(Modifier.height(10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Button(onClick = { usarLeitura() }, enabled = ultimaLeitura != null,
                                   modifier = Modifier.weight(1f)) { Text("Usar esta posicao") }
                            OutlinedButton(onClick = { gpsLigado = false }) { Text("Cancelar") }
                        }
                    } else {
                        OutlinedButton(onClick = {
                            ultimaLeitura = null
                            if (permitido) gpsLigado = true
                            else pedirPermissao.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
                                                               Manifest.permission.ACCESS_COARSE_LOCATION))
                        }, modifier = Modifier.fillMaxWidth()) {
                            Icon(Icons.Default.GpsFixed, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("Usar minha posicao (GPS)")
                        }
                    }
                }
            }
            if (item != null && diagrama != null) {
                val d = diagrama!!.conteudo
                Text("${d.optJSONArray("equipamentos")?.length() ?: 0} equipamento(s) e " +
                     "${d.optJSONArray("fusoes")?.length() ?: 0} fusao(oes) neste diagrama",
                     color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
                OutlinedButton(onClick = { aoFusoes(item) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Abrir diagrama de fusao")
                }
            }
            if (mensagem.isNotEmpty()) Text(mensagem, color = MaterialTheme.colorScheme.error)
            Button(onClick = { salvar() }, enabled = !salvando,
                   modifier = Modifier.fillMaxWidth().height(50.dp)) {
                if (salvando) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp,
                                                        color = MaterialTheme.colorScheme.onPrimary)
                else Text(if (item == null) "Criar equipamento" else "Salvar", fontSize = 16.sp)
            }
        }
    }

    if (conflito.isNotEmpty()) {
        AlertDialog(
            onDismissRequest = { conflito = "" },
            title = { Text("Outra pessoa salvou") },
            text = { Text("$conflito salvou este equipamento depois que voce abriu. Salvar o seu por cima? " +
                          "(a versao anterior fica no historico do servidor)") },
            confirmButton = { TextButton(onClick = { conflito = ""; salvar(forcar = true) }) { Text("Salvar por cima") } },
            dismissButton = { TextButton(onClick = { conflito = "" }) { Text("Cancelar") } },
        )
    }
}
