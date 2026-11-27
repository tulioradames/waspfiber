package com.waspfiber.app

import androidx.compose.foundation.Image
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
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

/** Entrar no WaspFiber / Criar conta - igual ao programa de PC: escolhe a
 *  empresa e o e-mail ja vem com o @dominio dela. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TelaLogin(avisoInicial: String, aoEntrar: (Sessao) -> Unit) {
    val ctx = LocalContext.current
    val escopo = rememberCoroutineScope()
    var empresas by remember { mutableStateOf<List<Empresa>?>(null) }
    var empresa by remember { mutableStateOf<Empresa?>(null) }
    var dominio by remember { mutableStateOf("") }
    var abertoEmpresa by remember { mutableStateOf(false) }
    var criar by remember { mutableStateOf(false) }
    var nome by remember { mutableStateOf("") }
    val lembrado = remember { Preferencias.ultimoEmail(ctx) }
    var local by remember { mutableStateOf(lembrado.substringBefore("@")) }
    var senha by remember { mutableStateOf("") }
    var senha2 by remember { mutableStateOf("") }
    var mensagem by remember { mutableStateOf(avisoInicial) }
    var mensagemOk by remember { mutableStateOf(false) }
    var ocupado by remember { mutableStateOf(false) }
    var tentativa by remember { mutableStateOf(0) }

    LaunchedEffect(tentativa) {
        try {
            val lista = Api.empresas()
            empresas = lista
            val dom = lembrado.substringAfter("@", "")
            empresa = lista.firstOrNull { dom in it.dominios } ?: lista.singleOrNull()
            dominio = empresa?.dominios?.firstOrNull() ?: ""
            if (mensagem.startsWith("Sem conexao")) mensagem = ""
        } catch (e: ErroServidor) {
            mensagem = "Sem conexao com o WaspFiber. Confira a internet e toque em Tentar de novo."
        }
    }

    fun emailCompleto(): String? {
        val l = local.trim().lowercase()
        if (empresa == null || l.isEmpty() || "@" in l || " " in l) return null
        return "$l@$dominio"
    }

    fun enviar() {
        mensagemOk = false
        val email = emailCompleto()
        when {
            empresas == null -> { tentativa++; mensagem = "Buscando as empresas..."; return }
            empresa == null -> { mensagem = "Escolha a sua empresa."; return }
            email == null -> { mensagem = "Digite o seu e-mail (so a parte antes do @)."; return }
            senha.isEmpty() -> { mensagem = "Digite a senha."; return }
            criar && nome.isBlank() -> { mensagem = "Informe o seu nome."; return }
            criar && senha != senha2 -> { mensagem = "As duas senhas nao conferem."; return }
            criar && senha.length < 8 -> { mensagem = "A senha precisa ter pelo menos 8 caracteres."; return }
        }
        ocupado = true
        mensagem = ""
        escopo.launch {
            try {
                if (criar) {
                    val nomeEmpresa = Api.criarConta(nome.trim(), email!!, senha)
                    criar = false
                    senha = ""; senha2 = ""
                    mensagemOk = true
                    mensagem = "Pedido enviado para a $nomeEmpresa. Assim que o administrador " +
                        "aprovar, entre com o seu e-mail e a senha."
                } else {
                    val s = Api.entrar(email!!, senha)
                    senha = ""
                    aoEntrar(s)
                }
            } catch (e: ErroServidor) {
                mensagem = e.message ?: "Erro"
                senha = ""; senha2 = ""
            } finally {
                ocupado = false
            }
        }
    }

    Surface(color = MaterialTheme.colorScheme.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().systemBarsPadding().imePadding()
                .verticalScroll(rememberScrollState()).padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(24.dp))
            Image(painterResource(R.mipmap.ic_launcher), contentDescription = null,
                  modifier = Modifier.size(84.dp))
            Spacer(Modifier.height(10.dp))
            Row {
                Text("Wasp", fontSize = 26.sp, fontWeight = FontWeight.SemiBold)
                Text("Fiber", fontSize = 26.sp, fontWeight = FontWeight.SemiBold,
                     color = MaterialTheme.colorScheme.primary)
            }
            Text(if (criar) "Criar conta" else "Entrar no WaspFiber",
                 style = MaterialTheme.typography.titleMedium,
                 modifier = Modifier.padding(top = 18.dp))
            Text(if (criar) "Com o e-mail da sua empresa." else "Escolha a sua empresa e entre com o seu e-mail.",
                 color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 13.sp)
            Spacer(Modifier.height(18.dp))

            ExposedDropdownMenuBox(expanded = abertoEmpresa,
                                   onExpandedChange = { abertoEmpresa = it && empresas != null }) {
                OutlinedTextField(
                    value = empresa?.nome ?: if (empresas == null) "Carregando as empresas..." else "Escolha a sua empresa",
                    onValueChange = {}, readOnly = true, label = { Text("Empresa") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = abertoEmpresa) },
                    modifier = Modifier.fillMaxWidth().menuAnchor(MenuAnchorType.PrimaryNotEditable, true),
                )
                ExposedDropdownMenu(expanded = abertoEmpresa, onDismissRequest = { abertoEmpresa = false }) {
                    empresas.orEmpty().forEach { e ->
                        DropdownMenuItem(text = { Text(e.nome) }, onClick = {
                            empresa = e
                            dominio = e.dominios.firstOrNull() ?: ""
                            abertoEmpresa = false
                        })
                    }
                }
            }
            if (criar) {
                OutlinedTextField(value = nome, onValueChange = { nome = it }, singleLine = true,
                                  label = { Text("Seu nome") },
                                  modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            }
            OutlinedTextField(
                value = local, onValueChange = { novo ->
                    // colou o e-mail inteiro? escolhe a empresa pelo dominio
                    if ("@" in novo && empresas != null) {
                        val dom = novo.substringAfter("@").trim().lowercase()
                        empresas!!.firstOrNull { dom in it.dominios }?.let {
                            empresa = it; dominio = dom
                        }
                        local = novo.substringBefore("@")
                    } else local = novo
                },
                singleLine = true, label = { Text(if (criar) "E-mail da empresa" else "E-mail") },
                suffix = {
                    Text(if (dominio.isNotEmpty()) "@$dominio" else "@ ...",
                         color = MaterialTheme.colorScheme.primary,
                         modifier = Modifier.padding(start = 2.dp))
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            if ((empresa?.dominios?.size ?: 0) > 1) {
                // mais de um dominio: troca tocando
                TextButton(onClick = {
                    val d = empresa!!.dominios
                    dominio = d[(d.indexOf(dominio) + 1) % d.size]
                }) { Text("Trocar o final do e-mail (@$dominio)") }
            }
            OutlinedTextField(value = senha, onValueChange = { senha = it }, singleLine = true,
                              label = { Text(if (criar) "Senha (pelo menos 8 caracteres)" else "Senha") },
                              visualTransformation = PasswordVisualTransformation(),
                              keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                              modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            if (criar) {
                OutlinedTextField(value = senha2, onValueChange = { senha2 = it }, singleLine = true,
                                  label = { Text("Repita a senha") },
                                  visualTransformation = PasswordVisualTransformation(),
                                  keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                                  modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            }
            if (mensagem.isNotEmpty()) {
                Text(mensagem, fontSize = 13.sp,
                     color = if (mensagemOk) MaterialTheme.colorScheme.secondary else MaterialTheme.colorScheme.error,
                     modifier = Modifier.fillMaxWidth().padding(top = 10.dp))
            }
            Spacer(Modifier.height(16.dp))
            Button(onClick = { enviar() }, enabled = !ocupado,
                   modifier = Modifier.fillMaxWidth().height(50.dp)) {
                if (ocupado) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp,
                                                       color = MaterialTheme.colorScheme.onPrimary)
                else Text(if (criar) "Criar conta" else "Entrar", fontSize = 16.sp)
            }
            if (empresas == null && mensagem.startsWith("Sem conexao")) {
                TextButton(onClick = { tentativa++ }) { Text("Tentar de novo") }
            }
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center, modifier = Modifier.padding(top = 8.dp)) {
                Text(if (criar) "Ja tem conta?" else "Ainda nao tem conta?",
                     color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
                TextButton(onClick = { criar = !criar; mensagem = ""; mensagemOk = false }) {
                    Text(if (criar) "Entrar" else "Criar conta")
                }
            }
            Box(Modifier.height(24.dp)) {}
        }
    }
}
