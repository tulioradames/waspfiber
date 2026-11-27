package com.waspfiber.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

private val VERDE = Color(0xFF5AD18A)

private fun corDoTipo(tipo: String) = Color(when (tipo) {
    Modelo.CABO -> 0xFF4DD0E1; Modelo.DIO -> 0xFFB39DFA; Modelo.ACOMODADOR -> 0xFF5AD18A
    "OLT" -> 0xFFE5736A; else -> 0xFFF2B84B
})

@Composable
private fun SeloEq(tipo: String) {
    val cor = corDoTipo(tipo)
    Surface(color = cor.copy(alpha = 0.18f), shape = RoundedCornerShape(4.dp)) {
        Text(if (tipo == Modelo.ACOMODADOR) "CTO" else tipo, color = cor, fontSize = 11.sp,
             fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp))
    }
}

@Composable
private fun Bolinha(cor: Int?, tamanho: Int = 14) {
    Box(Modifier.size(tamanho.dp).background(if (cor != null) Color(cor) else Color(0xFF3A444F), CircleShape)
            .border(1.dp, Color(0x55FFFFFF), CircleShape))
}

/** O diagrama de fusao de um POP / CEO / CTO pelo celular: os equipamentos
 *  (cabos, DIOs, CTO com splitters, OLT...), as portas de cada um e as
 *  fusoes. Grava no mesmo diagrama que o programa de PC abre. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaFusoes(cidade: Cidade, item: ItemDiagrama, aoVoltar: () -> Unit, tratar: (ErroServidor) -> String) {
    val escopo = rememberCoroutineScope()
    val avisos = remember { SnackbarHostState() }
    var modelo by remember { mutableStateOf<Modelo?>(null) }
    var versao by remember { mutableStateOf("") }
    var rev by remember { mutableIntStateOf(0) }          // muda a cada edicao: redesenha
    var alterado by remember { mutableStateOf(false) }
    var carregando by remember { mutableStateOf(true) }
    var salvando by remember { mutableStateOf(false) }
    var erro by remember { mutableStateOf("") }
    var conflito by remember { mutableStateOf("") }
    var perguntarSair by remember { mutableStateOf(false) }

    val abertos = remember { mutableStateListOf<String>() }   // equipamentos abertos (pilha)
    var origem by remember { mutableStateOf<Ponta?>(null) }    // escolhendo com quem fundir
    var portaAberta by remember { mutableStateOf<Ponta?>(null) }
    var novoEquipamento by remember { mutableStateOf(false) }
    var novoModulo by remember { mutableStateOf(false) }
    var renomear by remember { mutableStateOf(false) }
    var excluir by remember { mutableStateOf(false) }

    fun avisar(t: String) { escopo.launch { avisos.showSnackbar(t) } }
    fun mudou() { rev++; alterado = true }

    fun carregar() {
        carregando = true; erro = ""
        escopo.launch {
            try {
                val d = Api.abrir(cidade.id, item.id)
                modelo = Modelo(d.conteudo); versao = d.versao; alterado = false; rev++
                abertos.removeAll { modelo?.equipamento(it) == null }
            } catch (e: ErroServidor) { erro = tratar(e) }
            carregando = false
        }
    }
    LaunchedEffect(item.id) { carregar() }

    fun salvar(forcar: Boolean = false, depois: () -> Unit = {}) {
        val m = modelo ?: return
        salvando = true
        escopo.launch {
            try {
                versao = Api.salvar(cidade.id, item.id, m.json, versao, forcar)
                alterado = false
                avisar("Salvo no servidor")
                depois()
            } catch (e: ErroServidor) {
                if (e.status == 409) conflito = e.extra?.optString("alterado_por").orEmpty().ifEmpty { "Outra pessoa" }
                else avisar(tratar(e))
            } finally { salvando = false }
        }
    }

    BackHandler(enabled = origem != null || abertos.isNotEmpty() || alterado) {
        when {
            origem != null -> origem = null
            abertos.isNotEmpty() -> abertos.removeAt(abertos.lastIndex)
            else -> perguntarSair = true
        }
    }

    val m = modelo
    val eqAberto = abertos.lastOrNull()?.let { id -> rev.let { m?.equipamento(id) } }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(avisos) },
        topBar = {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = {
                        when {
                            origem != null -> origem = null
                            abertos.isNotEmpty() -> abertos.removeAt(abertos.lastIndex)
                            alterado -> perguntarSair = true
                            else -> aoVoltar()
                        }
                    }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Voltar") }
                },
                title = {
                    Column {
                        Text(when {
                            origem != null -> "Fundir com..."
                            eqAberto != null -> eqAberto.nome
                            else -> "Fusoes"
                        }, fontSize = 18.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(item.titulo + if (alterado) "  •  nao salvo" else "", fontSize = 12.sp,
                             color = if (alterado) Color(0xFFF2B84B) else MaterialTheme.colorScheme.onSurfaceVariant,
                             maxLines = 1)
                    }
                },
                actions = {
                    if (origem == null && eqAberto != null) {
                        if (eqAberto.tipo !in listOf(Modelo.DIO, Modelo.CABO))
                            IconButton(onClick = { novoModulo = true }) { Icon(Icons.Default.Add, "Adicionar") }
                        IconButton(onClick = { renomear = true }) { Icon(Icons.Default.Edit, "Renomear") }
                        IconButton(onClick = { excluir = true }) { Icon(Icons.Default.Delete, "Excluir") }
                    }
                    IconButton(onClick = { salvar() }, enabled = alterado && !salvando) {
                        if (salvando) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        else Icon(Icons.Default.Save, "Salvar",
                                  tint = if (alterado) MaterialTheme.colorScheme.primary
                                         else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
        floatingActionButton = {
            if (m != null && origem == null && eqAberto == null) ExtendedFloatingActionButton(
                onClick = { novoEquipamento = true },
                icon = { Icon(Icons.Default.Add, null) }, text = { Text("Equipamento") })
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            when {
                carregando -> CircularProgressIndicator(Modifier.align(Alignment.Center))
                m == null -> Column(Modifier.align(Alignment.Center).padding(24.dp),
                                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(erro.ifEmpty { "Nao foi possivel abrir." }, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = { carregar() }) { Text("Tentar de novo") }
                }
                origem != null -> EscolherDestino(m, origem!!, rev) { destino, qtd, rotulo ->
                    try {
                        val n = if (qtd <= 1) { m.criarFusao(origem!!, destino, rotulo); 1 }
                                else m.criarEmSequencia(origem!!, destino, qtd, rotulo)
                        origem = null
                        mudou()
                        avisar(if (n == 1) "Fusao criada" else "$n fusoes criadas")
                    } catch (e: ErroModelo) { avisar(e.message ?: "Nao foi possivel") }
                }
                eqAberto != null -> PortasDoEquipamento(m, eqAberto, rev) { p ->
                    if (m.fusoesNa(p).isEmpty()) origem = p else portaAberta = p
                }
                else -> ListaEquipamentos(m, rev) { abertos.add(it) }
            }
        }
    }

    // ---------- dialogos ----------
    portaAberta?.let { p ->
        if (m != null) DialogoPorta(m, p, rev,
            aoFechar = { portaAberta = null },
            aoRotulo = { id, r -> m.definirRotulo(id, r); mudou() },
            aoRemover = { id -> m.removerFusao(id); mudou(); avisar("Fusao removida") },
            aoFundir = { portaAberta = null; origem = p },
            aoIr = { outra -> portaAberta = null; abertos.add(outra.eq) })
    }
    if (novoEquipamento && m != null) DialogoNovoEquipamento(
        aoFechar = { novoEquipamento = false },
        aoCriar = { tipo, nome, qtd, fpt ->
            try {
                val e = m.adicionarEquipamento(tipo, nome, qtd, fpt)
                novoEquipamento = false; mudou(); abertos.add(e.id)
                null
            } catch (x: ErroModelo) { x.message }
        })
    if (novoModulo && m != null && eqAberto != null) DialogoNovoModulo(eqAberto.tipo,
        aoFechar = { novoModulo = false },
        aoCriar = { tipo, portas ->
            try {
                when (eqAberto.tipo) {
                    Modelo.ACOMODADOR -> m.adicionarSplitter(eqAberto.id, tipo)
                    "OLT" -> m.adicionarPlaca(eqAberto.id, tipo)
                    else -> m.adicionarGrupamento(eqAberto.id, tipo, portas)
                }
                novoModulo = false; mudou(); null
            } catch (x: ErroModelo) { x.message }
        })
    if (renomear && m != null && eqAberto != null) {
        var nome by remember { mutableStateOf(eqAberto.nome) }
        AlertDialog(onDismissRequest = { renomear = false },
            title = { Text("Renomear") },
            text = { OutlinedTextField(nome, { nome = it }, singleLine = true, label = { Text("Nome") }) },
            confirmButton = { TextButton(onClick = {
                try { m.renomearEquipamento(eqAberto.id, nome); mudou(); renomear = false }
                catch (x: ErroModelo) { avisar(x.message ?: "") }
            }) { Text("OK") } },
            dismissButton = { TextButton(onClick = { renomear = false }) { Text("Cancelar") } })
    }
    if (excluir && m != null && eqAberto != null) {
        val n = m.fusoes().count { it.a.eq == eqAberto.id || it.b.eq == eqAberto.id }
        AlertDialog(onDismissRequest = { excluir = false },
            title = { Text("Excluir ${eqAberto.nome}?") },
            text = { Text(if (n > 0) "As $n fusao(oes) dele tambem saem do diagrama." else "Ele nao tem fusoes.") },
            confirmButton = { TextButton(onClick = {
                m.removerEquipamento(eqAberto.id); abertos.remove(eqAberto.id)
                excluir = false; mudou()
            }) { Text("Excluir", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton(onClick = { excluir = false }) { Text("Cancelar") } })
    }
    if (perguntarSair) AlertDialog(onDismissRequest = { perguntarSair = false },
        title = { Text("Salvar as alteracoes?") },
        text = { Text("As fusoes feitas aqui ainda nao foram para o servidor.") },
        confirmButton = { TextButton(onClick = { perguntarSair = false; salvar { aoVoltar() } }) { Text("Salvar") } },
        dismissButton = { TextButton(onClick = { perguntarSair = false; aoVoltar() }) {
            Text("Descartar", color = MaterialTheme.colorScheme.error) } })
    if (conflito.isNotEmpty()) AlertDialog(onDismissRequest = { conflito = "" },
        title = { Text("Outra pessoa salvou") },
        text = { Text("$conflito salvou este diagrama depois que voce abriu. Salvar o seu por cima " +
                      "(o dele fica no historico do servidor) ou recarregar e perder o que fez aqui?") },
        confirmButton = { TextButton(onClick = { conflito = ""; salvar(forcar = true) }) { Text("Salvar por cima") } },
        dismissButton = { TextButton(onClick = { conflito = ""; carregar() }) { Text("Recarregar") } })
}

// ---------------- lista de equipamentos ----------------
@Composable
private fun ListaEquipamentos(m: Modelo, rev: Int, aoAbrir: (String) -> Unit) {
    val eqs = remember(rev) { m.equipamentos() }
    val nFus = remember(rev) { m.fusoes().size }
    LazyColumn(contentPadding = PaddingValues(12.dp, 12.dp, 12.dp, 96.dp),
               verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            Text("${eqs.size} equipamento(s)  •  $nFus fusao(oes)",
                 color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp,
                 modifier = Modifier.padding(4.dp))
        }
        if (eqs.isEmpty()) item {
            Text("Nenhum equipamento ainda. Toque em \"Equipamento\" para adicionar o cabo que chega, " +
                 "o DIO, a CTO com os splitters...", color = MaterialTheme.colorScheme.onSurfaceVariant,
                 modifier = Modifier.padding(16.dp))
        }
        items(eqs, key = { it.id }) { e ->
            val (usadas, total) = m.ocupacao(e)
            Card(onClick = { aoAbrir(e.id) }, modifier = Modifier.fillMaxWidth(),
                 colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    SeloEq(e.tipo)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(e.nome, fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(when (e.tipo) {
                            Modelo.CABO -> "$total fibras"
                            Modelo.DIO -> "$total portas"
                            Modelo.ACOMODADOR -> "${e.modulos.size} splitter(s)"
                            else -> "${e.modulos.size} modulo(s), $total portas"
                        }, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text("$usadas/$total", fontSize = 14.sp,
                         color = if (total > 0 && usadas >= total) Color(0xFFF2B84B) else VERDE)
                }
            }
        }
    }
}

// ---------------- portas de um equipamento ----------------
@Composable
private fun PortasDoEquipamento(m: Modelo, e: InfoEquipamento, rev: Int, aoTocar: (Ponta) -> Unit) {
    val fusoes = remember(rev) { m.fusoes() }
    LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
        if (e.modulos.isEmpty()) item {
            Text(when (e.tipo) {
                Modelo.ACOMODADOR -> "Sem splitters. Toque em + para adicionar."
                "OLT" -> "Sem placas. Toque em + para adicionar."
                else -> "Sem portas. Toque em + para adicionar um grupamento."
            }, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(20.dp))
        }
        for (mod in e.modulos) {
            item(key = "h-" + mod.id) {
                Text(mod.nome, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                     color = MaterialTheme.colorScheme.primary,
                     modifier = Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface)
                         .padding(horizontal = 16.dp, vertical = 8.dp))
            }
            items(mod.portas, key = { "p-" + mod.id + "-" + it.ponta.porta }) { p ->
                val minhas = fusoes.filter { it.a == p.ponta || it.b == p.ponta }
                val limite = m.limite(p.ponta)
                Row(Modifier.fillMaxWidth().clickable { aoTocar(p.ponta) }
                        .padding(horizontal = 16.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Bolinha(p.corFibra)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.width(78.dp)) {
                        Text(p.rotulo, fontSize = 15.sp)
                        p.nomeCor?.let { Text(it, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                    Column(Modifier.weight(1f)) {
                        if (minhas.isEmpty()) Text("livre", color = VERDE, fontSize = 14.sp)
                        for (f in minhas) {
                            Text("→ " + m.nomePonta(m.outraPonta(f, p.ponta)), fontSize = 14.sp,
                                 maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (f.rotulo.isNotEmpty())
                                Text(f.rotulo, fontSize = 12.sp, color = Color(0xFFF2B84B))
                        }
                        if (limite > 1 && minhas.size < limite && minhas.isNotEmpty())
                            Text("duplex: cabe mais ${limite - minhas.size}", fontSize = 11.sp, color = VERDE)
                    }
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outline, thickness = 0.5.dp)
            }
        }
    }
}

// ---------------- escolher a outra ponta ----------------
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EscolherDestino(m: Modelo, origem: Ponta, rev: Int, aoEscolher: (Ponta, Int, String) -> Unit) {
    val eqs = remember(rev) { m.equipamentos() }
    var eqId by remember { mutableStateOf<String?>(null) }
    var modId by remember { mutableStateOf<String?>(null) }
    var qtd by remember { mutableStateOf("1") }
    var rotulo by remember { mutableStateOf("") }
    val eq = eqId?.let { id -> eqs.firstOrNull { it.id == id } }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp),
           verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
            Column(Modifier.padding(14.dp)) {
                Text("De", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(m.nomePonta(origem), fontSize = 16.sp, color = MaterialTheme.colorScheme.onSurface)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(qtd, { qtd = it.filter(Char::isDigit).take(3) }, singleLine = true,
                              label = { Text("Em sequencia") },
                              keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                              modifier = Modifier.width(130.dp))
            OutlinedTextField(rotulo, { rotulo = it }, singleLine = true,
                              label = { Text("Rotulo (opcional)") }, modifier = Modifier.weight(1f))
        }
        if ((qtd.toIntOrNull() ?: 1) > 1)
            Text("Liga ${qtd} portas seguidas: esta e as proximas com a escolhida e as proximas. " +
                 "Use # no rotulo para numerar (ex.: Cliente #).", fontSize = 12.sp,
                 color = MaterialTheme.colorScheme.onSurfaceVariant)

        Text("Para", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (e in eqs) FilterChip(selected = e.id == eqId, onClick = {
                eqId = e.id
                // primeiro lado/modulo que tem porta livre
                modId = e.modulos.firstOrNull { md -> md.portas.any { m.livre(it.ponta) && it.ponta != origem } }?.id
                    ?: e.modulos.firstOrNull()?.id
            }, label = { Text(e.nome, maxLines = 1) }, leadingIcon = { SeloEq(e.tipo) })
        }
        if (eq != null) {
            if (eq.modulos.size > 1) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (md in eq.modulos) FilterChip(selected = md.id == modId, onClick = { modId = md.id },
                                                  label = { Text(md.nome, maxLines = 1) })
            }
            val mod = eq.modulos.firstOrNull { it.id == modId }
            if (mod == null) Text("Este equipamento nao tem portas.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            else FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
                         verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (p in mod.portas) {
                    val pode = p.ponta != origem && m.livre(p.ponta)
                    Surface(onClick = { aoEscolher(p.ponta, qtd.toIntOrNull() ?: 1, rotulo.trim()) },
                            enabled = pode, shape = RoundedCornerShape(8.dp),
                            color = if (pode) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.background,
                            border = androidx.compose.foundation.BorderStroke(1.dp,
                                if (pode) VERDE.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outline),
                            modifier = Modifier.heightIn(min = 46.dp)) {
                        Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            if (p.corFibra != null) { Bolinha(p.corFibra, 12); Spacer(Modifier.width(6.dp)) }
                            Text(p.rotulo.removePrefix("Porta ").removePrefix("Fibra "), fontSize = 15.sp,
                                 color = if (pode) MaterialTheme.colorScheme.onSurface
                                         else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f))
                        }
                    }
                }
            }
            Text("Verde = livre. Toque na porta para fundir.", fontSize = 12.sp,
                 color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

// ---------------- porta ocupada ----------------
@Composable
private fun DialogoPorta(m: Modelo, p: Ponta, rev: Int, aoFechar: () -> Unit,
                         aoRotulo: (String, String) -> Unit, aoRemover: (String) -> Unit,
                         aoFundir: () -> Unit, aoIr: (Ponta) -> Unit) {
    val fusoes = remember(rev) { m.fusoesNa(p) }
    val rotulos = remember(rev) { mutableStateListOf(*fusoes.map { it.rotulo }.toTypedArray()) }
    AlertDialog(onDismissRequest = aoFechar,
        title = { Text(m.nomePonta(p), fontSize = 18.sp) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (fusoes.isEmpty()) Text("Porta livre.")
                fusoes.forEachIndexed { i, f ->
                    val outra = m.outraPonta(f, p)
                    Text("Fundida com", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(m.nomePonta(outra), fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurface)
                    OutlinedTextField(rotulos.getOrElse(i) { "" }, { if (i < rotulos.size) rotulos[i] = it },
                                      singleLine = true, label = { Text("Rotulo") }, modifier = Modifier.fillMaxWidth())
                    Row {
                        TextButton(onClick = { aoIr(outra) }) { Text("Ver a outra ponta") }
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { aoRemover(f.id) }) {
                            Text("Desfazer fusao", color = MaterialTheme.colorScheme.error)
                        }
                    }
                    if (i < fusoes.lastIndex) HorizontalDivider()
                }
                if (m.livre(p)) TextButton(onClick = aoFundir) { Text("Fundir com outra porta") }
            }
        },
        confirmButton = { TextButton(onClick = {
            fusoes.forEachIndexed { i, f ->
                val r = rotulos.getOrElse(i) { f.rotulo }.trim()
                if (r != f.rotulo) aoRotulo(f.id, r)
            }
            aoFechar()
        }) { Text("OK") } })
}

// ---------------- novo equipamento ----------------
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DialogoNovoEquipamento(aoFechar: () -> Unit, aoCriar: (String, String, Int, Int) -> String?) {
    var tipo by remember { mutableStateOf(Modelo.CABO) }
    var nome by remember { mutableStateOf("") }
    var qtd by remember { mutableStateOf("12") }
    var fpt by remember { mutableStateOf("12") }
    var erro by remember { mutableStateOf("") }
    val rotuloQtd = when (tipo) {
        Modelo.CABO -> "Fibras"; Modelo.DIO -> "Portas"; Modelo.ACOMODADOR -> "Splitters 1x8"; else -> null
    }
    AlertDialog(onDismissRequest = aoFechar,
        title = { Text("Novo equipamento") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (t in Modelo.TODOS) FilterChip(selected = t == tipo, onClick = {
                        tipo = t
                        qtd = when (t) { Modelo.CABO -> "12"; Modelo.DIO -> "24"; Modelo.ACOMODADOR -> "1"; else -> "0" }
                    }, label = { Text(Modelo.nomeTipo(t)) })
                }
                OutlinedTextField(nome, { nome = it }, singleLine = true, label = { Text("Nome") },
                                  placeholder = { Text(when (tipo) {
                                      Modelo.CABO -> "Ex.: Cabo 12FO Rua A"; Modelo.DIO -> "Ex.: DIO 01"
                                      Modelo.ACOMODADOR -> "Ex.: CTO 03"; else -> "Ex.: $tipo 01"
                                  }) }, modifier = Modifier.fillMaxWidth())
                if (rotuloQtd != null) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(qtd, { qtd = it.filter(Char::isDigit).take(3) }, singleLine = true,
                                      label = { Text(rotuloQtd) },
                                      keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                      modifier = Modifier.weight(1f))
                    if (tipo == Modelo.CABO)
                        OutlinedTextField(fpt, { fpt = it.filter(Char::isDigit).take(2) }, singleLine = true,
                                          label = { Text("Fibras/tubo") },
                                          keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                          modifier = Modifier.weight(1f))
                }
                if (tipo == "OLT") Text("Depois de criar, toque em + para colocar as placas.", fontSize = 12.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (tipo == "SWITCH" || tipo == "RB") Text("Depois de criar, toque em + para colocar as portas.",
                                        fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (erro.isNotEmpty()) Text(erro, color = MaterialTheme.colorScheme.error)
            }
        },
        confirmButton = { TextButton(onClick = {
            erro = aoCriar(tipo, nome, qtd.toIntOrNull() ?: 0, fpt.toIntOrNull() ?: 12) ?: ""
        }) { Text("Criar") } },
        dismissButton = { TextButton(onClick = aoFechar) { Text("Cancelar") } })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DialogoNovoModulo(tipoEq: String, aoFechar: () -> Unit, aoCriar: (String, Int) -> String?) {
    val opcoes: List<Pair<String, String>> = when (tipoEq) {
        Modelo.ACOMODADOR -> Modelo.SPLITTERS.keys.map { it to "Splitter $it" }
        "OLT" -> Modelo.PLACAS_OLT.keys.map { it to it }
        else -> Modelo.GRUPAMENTOS.map { (k, v) -> k to v }
    }
    var escolha by remember { mutableStateOf(opcoes.first().first.let { if (tipoEq == Modelo.ACOMODADOR) "1x8" else it }) }
    var portas by remember { mutableStateOf("4") }
    var erro by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = aoFechar,
        title = { Text(when (tipoEq) { Modelo.ACOMODADOR -> "Novo splitter"; "OLT" -> "Nova placa"; else -> "Novas portas" }) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((k, rot) in opcoes) FilterChip(selected = k == escolha, onClick = { escolha = k },
                                                        label = { Text(rot) })
                }
                if (tipoEq == "SWITCH" || tipoEq == "RB")
                    OutlinedTextField(portas, { portas = it.filter(Char::isDigit).take(3) }, singleLine = true,
                                      label = { Text("Quantidade de portas") },
                                      keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                if (erro.isNotEmpty()) Text(erro, color = MaterialTheme.colorScheme.error)
            }
        },
        confirmButton = { TextButton(onClick = { erro = aoCriar(escolha, portas.toIntOrNull() ?: 0) ?: "" }) { Text("Adicionar") } },
        dismissButton = { TextButton(onClick = aoFechar) { Text("Cancelar") } })
}
