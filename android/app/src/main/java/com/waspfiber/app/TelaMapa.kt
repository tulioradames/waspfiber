package com.waspfiber.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.drawable.BitmapDrawable
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Satellite
import androidx.compose.material.icons.filled.WrongLocation
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SmallFloatingActionButton
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
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.launch
import org.osmdroid.events.MapEventsReceiver
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.CustomZoomButtonsController
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.mylocation.GpsMyLocationProvider
import org.osmdroid.views.overlay.mylocation.MyLocationNewOverlay

/** Mapa da cidade: os POPs, CEOs e CTOs nos pinos, a posicao do tecnico
 *  (GPS) e o "Equipamento aqui". */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaMapa(cidade: Cidade, aoVoltar: () -> Unit,
             aoEquipamento: (ItemDiagrama?, GeoPoint?) -> Unit,
             tratar: (ErroServidor) -> String) {
    val ctx = LocalContext.current
    val escopo = rememberCoroutineScope()
    var itens by remember { mutableStateOf<List<ItemDiagrama>?>(null) }
    var erro by remember { mutableStateOf("") }
    var escolhido by remember { mutableStateOf<ItemDiagrama?>(null) }
    var fonte by remember { mutableStateOf(Preferencias.fonteMapa(ctx)) }
    var recarregar by remember { mutableStateOf(0) }
    var semLocalAberto by remember { mutableStateOf(false) }
    var corrigir by remember { mutableStateOf<ItemDiagrama?>(null) }
    var aviso by remember { mutableStateOf("") }
    var permitido by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION)
                       == PackageManager.PERMISSION_GRANTED)
    }
    val pedirPermissao = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { r -> permitido = r.values.any { it } }

    // ---------------- mapa (osmdroid) ----------------
    val mapa = remember {
        MapView(ctx).apply {
            setMultiTouchControls(true)
            zoomController.setVisibility(CustomZoomButtonsController.Visibility.NEVER)
            setTileSource(fonteDeTiles(fonte))
            minZoomLevel = 3.0
            maxZoomLevel = if (fonte == "satelite") 18.0 else 19.0
            controller.setZoom(5.0)
            controller.setCenter(GeoPoint(-7.2, -36.5))
            overlays.add(MapEventsOverlay(object : MapEventsReceiver {
                override fun singleTapConfirmedHelper(p: GeoPoint?): Boolean { escolhido = null; return true }
                override fun longPressHelper(p: GeoPoint?): Boolean = false
            }))
        }
    }
    val eu = remember { MyLocationNewOverlay(GpsMyLocationProvider(ctx), mapa) }
    var enquadrado by remember { mutableStateOf(false) }
    val ciclo = LocalLifecycleOwner.current
    DisposableEffect(ciclo) {
        val obs = LifecycleEventObserver { _, ev ->
            when (ev) {
                Lifecycle.Event.ON_RESUME -> { mapa.onResume(); if (permitido) eu.enableMyLocation() }
                Lifecycle.Event.ON_PAUSE -> { mapa.onPause(); eu.disableMyLocation() }
                else -> {}
            }
        }
        ciclo.lifecycle.addObserver(obs)
        mapa.onResume()
        onDispose { ciclo.lifecycle.removeObserver(obs); eu.disableMyLocation(); mapa.onDetach() }
    }
    LaunchedEffect(Unit) {
        if (!permitido) pedirPermissao.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
                                                      Manifest.permission.ACCESS_COARSE_LOCATION))
    }
    LaunchedEffect(permitido) {
        if (permitido) {
            eu.enableMyLocation()
            if (!mapa.overlays.contains(eu)) mapa.overlays.add(eu)
            eu.runOnFirstFix {
                // cidade sem nenhum ponto: comeca onde o tecnico esta
                if (itens.orEmpty().none { it.lat != null }) mapa.post {
                    eu.myLocation?.let { mapa.controller.animateTo(it, 17.0, 800L) }
                }
            }
        }
    }
    LaunchedEffect(recarregar) {
        erro = ""
        try { itens = Api.diagramas(cidade.id) } catch (e: ErroServidor) { erro = tratar(e) }
    }

    // pinos: refaz quando muda a lista ou o escolhido
    LaunchedEffect(itens, escolhido) {
        mapa.overlays.removeAll { it is Marker }
        val pontos = mutableListOf<GeoPoint>()
        itens.orEmpty().filter { it.lat != null && it.lon != null }
            .sortedBy { it.id == escolhido?.id }
            .forEach { item ->
                val ponto = GeoPoint(item.lat!!, item.lon!!)
                pontos += ponto
                mapa.overlays.add(Marker(mapa).apply {
                    position = ponto
                    setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                    icon = BitmapDrawable(ctx.resources, Tipos.pino(ctx, item.tipo, item.id == escolhido?.id))
                    title = item.titulo
                    setOnMarkerClickListener { _, _ -> escolhido = item; true }
                })
            }
        mapa.invalidate()
        if (!enquadrado && itens != null) {
            enquadrado = true
            mapa.post {
                when {
                    pontos.size > 1 -> mapa.zoomToBoundingBox(
                        BoundingBox.fromGeoPoints(pontos).increaseByScale(1.4f), false, 60)
                    pontos.size == 1 -> { mapa.controller.setZoom(17.0); mapa.controller.setCenter(pontos[0]) }
                }
            }
        }
    }

    fun trocarFonte() {
        fonte = if (fonte == "mapa") "satelite" else "mapa"
        Preferencias.guardarFonteMapa(ctx, fonte)
        mapa.setTileSource(fonteDeTiles(fonte))
        mapa.maxZoomLevel = if (fonte == "satelite") 18.0 else 19.0
        if (mapa.zoomLevelDouble > mapa.maxZoomLevel) mapa.controller.setZoom(mapa.maxZoomLevel)
    }

    fun minhaPosicao(): GeoPoint? = if (permitido) eu.myLocation else null

    val semLocal = itens.orEmpty().filter { it.lat == null }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                navigationIcon = { IconButton(onClick = aoVoltar) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Voltar") } },
                title = {
                    Column {
                        Text(cidade.titulo, fontSize = 19.sp)
                        val n = itens?.size ?: 0
                        Text("$n equipamento${if (n == 1) "" else "s"}", fontSize = 12.sp,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = {
                    IconButton(onClick = { trocarFonte() }) {
                        Icon(if (fonte == "mapa") Icons.Default.Satellite else Icons.Default.Map,
                             if (fonte == "mapa") "Satelite" else "Mapa")
                    }
                    IconButton(onClick = { enquadrado = false; recarregar++ }) {
                        Icon(Icons.Default.Refresh, "Atualizar")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
        floatingActionButton = {
            if (escolhido == null) Column(horizontalAlignment = Alignment.End,
                                          verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SmallFloatingActionButton(onClick = {
                    val p = minhaPosicao()
                    if (p != null) mapa.controller.animateTo(p, maxOf(mapa.zoomLevelDouble, 17.0), 600L)
                    else if (!permitido) pedirPermissao.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
                                                                       Manifest.permission.ACCESS_COARSE_LOCATION))
                    else aviso = "Procurando o GPS... (ligue a localizacao do celular)"
                }) { Icon(Icons.Default.MyLocation, "Minha posicao") }
                ExtendedFloatingActionButton(
                    onClick = { aoEquipamento(null, minhaPosicao() ?: mapa.mapCenter as GeoPoint) },
                    icon = { Icon(Icons.Default.Add, null) },
                    text = { Text("Equipamento aqui") })
            }
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            AndroidView(factory = { mapa }, modifier = Modifier.fillMaxSize())
            Column(Modifier.align(Alignment.TopStart).padding(10.dp)) {
                if (semLocal.isNotEmpty()) {
                    AssistChip(onClick = { semLocalAberto = true },
                               label = { Text("${semLocal.size} sem localizacao") },
                               colors = AssistChipDefaults.assistChipColors(
                                   containerColor = MaterialTheme.colorScheme.surface,
                                   labelColor = MaterialTheme.colorScheme.onSurface),
                               leadingIcon = { Icon(Icons.Default.WrongLocation, null,
                                                    tint = Color(0xFFD9A441)) })
                }
                if (erro.isNotEmpty()) Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                    Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(erro, color = MaterialTheme.colorScheme.error, fontSize = 13.sp,
                             modifier = Modifier.weight(1f, fill = false))
                        TextButton(onClick = { recarregar++ }) { Text("Tentar de novo") }
                    }
                }
                if (aviso.isNotEmpty()) Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                    Text(aviso, fontSize = 13.sp, modifier = Modifier.padding(10.dp))
                }
            }
            Text(if (fonte == "satelite") "Imagens © Esri, Maxar" else "© OpenStreetMap",
                 fontSize = 9.sp, color = Color(0xFF202020),
                 modifier = Modifier.align(Alignment.BottomStart).padding(4.dp))
            escolhido?.let { item ->
                CartaoEquipamento(item, Modifier.align(Alignment.BottomCenter).padding(10.dp),
                                  aoDetalhes = { aoEquipamento(item, null) },
                                  aoCorrigir = { corrigir = item })
            }
        }
    }

    if (semLocalAberto) {
        AlertDialog(
            onDismissRequest = { semLocalAberto = false },
            title = { Text("Sem localizacao no mapa") },
            text = {
                LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    items(semLocal, key = { it.id }) { item ->
                        TextButton(onClick = { semLocalAberto = false; aoEquipamento(item, minhaPosicao()) },
                                   modifier = Modifier.fillMaxWidth()) {
                            IconeTipo(item.tipo)
                            Spacer(Modifier.width(10.dp))
                            Text(item.titulo, modifier = Modifier.weight(1f))
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { semLocalAberto = false }) { Text("Fechar") } },
        )
    }
    corrigir?.let { item ->
        val p = minhaPosicao()
        val precisao = eu.myLocationProvider?.lastKnownLocation?.accuracy
        AlertDialog(
            onDismissRequest = { corrigir = null },
            title = { Text("Corrigir a localizacao") },
            text = {
                Text(if (p == null) "Ainda sem sinal de GPS. Espere uns segundos (ligue a localizacao do celular)."
                     else "Colocar ${item.titulo} na sua posicao atual?\n\n" +
                         "%.6f, %.6f".format(p.latitude, p.longitude) +
                         (precisao?.let { "\nPrecisao do GPS: ±%.0f m".format(it) } ?: ""))
            },
            confirmButton = {
                TextButton(enabled = p != null, onClick = {
                    corrigir = null
                    escopo.launch {
                        try {
                            val d = Api.abrir(cidade.id, item.id)
                            Local.atualizar(d.conteudo, item.tipo,
                                            item.titulo, item.endereco, p!!.latitude, p.longitude)
                            Api.salvar(cidade.id, item.id, d.conteudo, d.versao)
                            aviso = "Localizacao de ${item.titulo} corrigida."
                            escolhido = null
                            recarregar++
                        } catch (e: ErroServidor) { aviso = tratar(e) }
                    }
                }) { Text("Corrigir") }
            },
            dismissButton = { TextButton(onClick = { corrigir = null }) { Text("Cancelar") } },
        )
    }
}

@Composable
fun IconeTipo(tipo: String, tamanho: Int = 22) {
    val id = Tipos.icones[tipo]
    val cor = Color(Tipos.cores[tipo] ?: Tipos.COR_SEM_TIPO)
    if (id != null) Icon(painterResource(id), tipo, tint = cor, modifier = Modifier.size(tamanho.dp))
    else Icon(Icons.Default.Edit, null, tint = cor, modifier = Modifier.size(tamanho.dp))
}

@Composable
fun Selo(tipo: String) {
    val cor = Color(Tipos.cores[tipo] ?: Tipos.COR_SEM_TIPO)
    if (tipo.isNotEmpty()) Box(Modifier.padding(end = 8.dp)) {
        androidx.compose.material3.Surface(color = cor.copy(alpha = 0.18f), shape = RoundedCornerShape(4.dp)) {
            Text(tipo, color = cor, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp))
        }
    }
}

@Composable
private fun CartaoEquipamento(item: ItemDiagrama, modifier: Modifier,
                              aoDetalhes: () -> Unit, aoCorrigir: () -> Unit) {
    Card(modifier = modifier.fillMaxWidth(),
         colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconeTipo(item.tipo, 26)
                Spacer(Modifier.width(10.dp))
                Selo(item.tipo)
                Text(item.titulo, fontSize = 18.sp)
            }
            if (item.endereco.isNotEmpty()) Text(item.endereco, fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
            Text("${item.equipamentos} equipamento${if (item.equipamentos == 1) "" else "s"}  ·  ${item.fusoes} fusoes" +
                 (if (item.alteradoPor.isNotEmpty()) "  ·  por ${item.alteradoPor}" else ""),
                 fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = aoCorrigir, modifier = Modifier.weight(1f)) {
                    Icon(Icons.Default.MyLocation, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp)); Text("Minha posicao")
                }
                Button(onClick = aoDetalhes, modifier = Modifier.weight(1f)) { Text("Detalhes") }
            }
        }
    }
}
