package com.waspfiber.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.LocationCity
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaCidades(sessao: Sessao?, aoAbrir: (Cidade) -> Unit, aoSair: () -> Unit,
                tratar: (ErroServidor) -> String) {
    val escopo = rememberCoroutineScope()
    var cidades by remember { mutableStateOf<List<Cidade>?>(null) }
    var erro by remember { mutableStateOf("") }
    var recarregar by remember { mutableStateOf(0) }
    var novaCidade by remember { mutableStateOf(false) }
    var confirmarSair by remember { mutableStateOf(false) }

    LaunchedEffect(recarregar) {
        erro = ""
        try { cidades = Api.cidades() } catch (e: ErroServidor) { erro = tratar(e) }
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("Cidades", fontSize = 20.sp)
                        Text("${sessao?.empresaNome ?: ""}  ·  ${sessao?.nome ?: ""}",
                             fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                actions = {
                    IconButton(onClick = { cidades = null; recarregar++ }) {
                        Icon(Icons.Default.Refresh, "Atualizar")
                    }
                    IconButton(onClick = { confirmarSair = true }) {
                        Icon(Icons.AutoMirrored.Filled.Logout, "Sair")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(onClick = { novaCidade = true },
                                         icon = { Icon(Icons.Default.Add, null) },
                                         text = { Text("Nova cidade") })
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            when {
                erro.isNotEmpty() -> Column(Modifier.align(Alignment.Center).padding(24.dp),
                                            horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(erro, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = { recarregar++ }) { Text("Tentar de novo") }
                }
                cidades == null -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                cidades!!.isEmpty() -> Column(Modifier.align(Alignment.Center).padding(32.dp),
                                              horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Nenhuma cidade ainda", fontSize = 18.sp)
                    Text("Toque em Nova cidade pra comecar.",
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                else -> LazyColumn(Modifier.fillMaxSize(), contentPadding =
                    androidx.compose.foundation.layout.PaddingValues(12.dp, 8.dp, 12.dp, 96.dp)) {
                    items(cidades!!, key = { it.id }) { cidade ->
                        Card(onClick = { aoAbrir(cidade) },
                             colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant,
                                                              contentColor = MaterialTheme.colorScheme.onSurface),
                             modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.LocationCity, null, tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(14.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(cidade.titulo, fontSize = 17.sp)
                                    Text("${cidade.diagramas} equipamento${if (cidade.diagramas == 1) "" else "s"}",
                                         color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
                                }
                                Icon(Icons.Default.ChevronRight, null,
                                     tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
    }

    if (novaCidade) {
        var nome by remember { mutableStateOf("") }
        var uf by remember { mutableStateOf("") }
        var erroDialogo by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { novaCidade = false },
            title = { Text("Nova cidade") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(nome, { nome = it }, label = { Text("Nome da cidade") }, singleLine = true)
                    OutlinedTextField(uf, { uf = it.take(2).uppercase() }, label = { Text("UF") },
                                      singleLine = true, modifier = Modifier.width(100.dp))
                    if (erroDialogo.isNotEmpty()) Text(erroDialogo, color = MaterialTheme.colorScheme.error)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    escopo.launch {
                        try {
                            val c = Api.criarCidade(nome.trim(), uf.trim())
                            novaCidade = false
                            aoAbrir(c)
                        } catch (e: ErroServidor) { erroDialogo = tratar(e) }
                    }
                }) { Text("Criar") }
            },
            dismissButton = { TextButton(onClick = { novaCidade = false }) { Text("Cancelar") } },
        )
    }
    if (confirmarSair) {
        AlertDialog(
            onDismissRequest = { confirmarSair = false },
            title = { Text("Sair") },
            text = { Text("Sair da conta ${sessao?.email ?: ""}?") },
            confirmButton = {
                TextButton(onClick = {
                    confirmarSair = false
                    escopo.launch { Api.sair(); aoSair() }
                }) { Text("Sair") }
            },
            dismissButton = { TextButton(onClick = { confirmarSair = false }) { Text("Cancelar") } },
        )
    }
}

@Composable
internal fun Carregando() = Box(Modifier.fillMaxSize()) {
    CircularProgressIndicator(Modifier.align(Alignment.Center).size(36.dp))
}

internal fun Modifier.tocavel(acao: () -> Unit) = this.clickable(onClick = acao)
