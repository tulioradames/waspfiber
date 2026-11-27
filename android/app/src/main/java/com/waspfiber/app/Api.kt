package com.waspfiber.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Erro do servidor, ja com a mensagem pra pessoa.
 *  semConexao = nao chegou no servidor (internet, servidor fora). */
class ErroServidor(
    mensagem: String,
    val status: Int = 0,
    val semConexao: Boolean = false,
    val extra: JSONObject? = null,
) : Exception(mensagem)

data class Empresa(val id: String, val nome: String, val dominios: List<String>)

data class Cidade(val id: String, val nome: String, val uf: String, val titulo: String,
                  val diagramas: Int)

data class ItemDiagrama(
    val id: String, val titulo: String, val tipo: String, val endereco: String,
    val lat: Double?, val lon: Double?, val equipamentos: Int, val fusoes: Int,
    val alteradoPor: String, val modificado: Double, val versao: String,
)

data class Diagrama(val id: String, val conteudo: JSONObject, val versao: String)

data class Sessao(val token: String, val email: String, val nome: String, val papel: String,
                  val empresa: String, val empresaNome: String) {
    val admin get() = papel == "admin"
}

/** A mesma API do programa de PC (servidor/waspfiber_servidor.py). */
object Api {
    /** endereco do servidor: fixo (o mesmo do programa de PC); vem do build -
     *  o APK de teste usa um servidor de teste */
    var servidor: String = BuildConfig.SERVIDOR
    var token: String? = null

    private suspend fun pedir(metodo: String, caminho: String, corpo: JSONObject? = null,
                              tempo: Int = 20000): JSONObject = withContext(Dispatchers.IO) {
        val conexao = try {
            URL(servidor + caminho).openConnection() as HttpURLConnection
        } catch (e: IOException) {
            throw ErroServidor("Sem conexao com o WaspFiber.", semConexao = true)
        }
        try {
            conexao.requestMethod = metodo
            conexao.connectTimeout = tempo
            conexao.readTimeout = tempo
            conexao.setRequestProperty("Accept", "application/json")
            token?.let { conexao.setRequestProperty("Authorization", "Bearer $it") }
            if (corpo != null) {
                conexao.doOutput = true
                conexao.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conexao.outputStream.use { it.write(corpo.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = conexao.responseCode
            val fluxo = if (status in 200..299) conexao.inputStream else conexao.errorStream
            val texto = fluxo?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
            val json = try { JSONObject(if (texto.isBlank()) "{}" else texto) } catch (e: Exception) { JSONObject() }
            if (status !in 200..299) {
                throw ErroServidor(json.optString("erro").ifBlank { "O servidor respondeu $status." },
                                   status, extra = json)
            }
            json
        } catch (e: ErroServidor) {
            throw e
        } catch (e: IOException) {
            throw ErroServidor("Sem conexao com o WaspFiber. Confira a internet.", semConexao = true)
        } finally {
            conexao.disconnect()
        }
    }

    private fun q(valor: String) = URLEncoder.encode(valor, "UTF-8")

    // ---------------- contas ----------------
    suspend fun empresas(): List<Empresa> {
        val lista = pedir("GET", "/api/empresas").getJSONArray("empresas")
        return (0 until lista.length()).map { i ->
            val e = lista.getJSONObject(i)
            val d = e.getJSONArray("dominios")
            Empresa(e.getString("id"), e.getString("nome"), (0 until d.length()).map { d.getString(it) })
        }
    }

    suspend fun entrar(email: String, senha: String): Sessao {
        val r = pedir("POST", "/api/entrar", JSONObject().put("email", email).put("senha", senha))
        token = r.getString("token")
        return Sessao(r.getString("token"), r.optString("usuario", email), r.optString("nome"),
                      r.optString("papel", "usuario"), r.optString("empresa"),
                      r.optString("empresa_nome"))
    }

    suspend fun criarConta(nome: String, email: String, senha: String): String =
        pedir("POST", "/api/contas", JSONObject().put("nome", nome).put("email", email)
            .put("senha", senha)).optString("empresa_nome")

    suspend fun conferir(): JSONObject = pedir("GET", "/api/eu")

    suspend fun sair() {
        try { pedir("POST", "/api/sair", JSONObject()) } catch (_: ErroServidor) { }
        token = null
    }

    // ---------------- cidades ----------------
    suspend fun cidades(): List<Cidade> {
        val lista = pedir("GET", "/api/cidades").getJSONArray("cidades")
        return (0 until lista.length()).map { i -> cidadeDe(lista.getJSONObject(i)) }
    }

    private fun cidadeDe(c: JSONObject) = Cidade(
        c.getString("id"), c.optString("nome"), c.optString("uf"),
        c.optString("titulo").ifBlank { c.optString("nome") }, c.optInt("diagramas"))

    suspend fun criarCidade(nome: String, uf: String): Cidade =
        cidadeDe(pedir("POST", "/api/cidades", JSONObject().put("nome", nome).put("uf", uf)))

    // ---------------- diagramas ----------------
    suspend fun diagramas(cidadeId: String): List<ItemDiagrama> {
        val lista = pedir("GET", "/api/cidades/${q(cidadeId)}/diagramas").getJSONArray("diagramas")
        return (0 until lista.length()).map { i ->
            val d = lista.getJSONObject(i)
            ItemDiagrama(
                d.getString("id"), d.optString("titulo"), d.optString("tipo"),
                d.optString("endereco"),
                if (d.has("lat")) d.getDouble("lat") else null,
                if (d.has("lon")) d.getDouble("lon") else null,
                d.optInt("equipamentos"), d.optInt("fusoes"), d.optString("alterado_por"),
                d.optDouble("modificado", 0.0), d.optString("versao"))
        }
    }

    suspend fun abrir(cidadeId: String, diagramaId: String): Diagrama {
        val r = pedir("GET", "/api/cidades/${q(cidadeId)}/diagramas/${q(diagramaId)}")
        return Diagrama(diagramaId, r.getJSONObject("conteudo"), r.getString("versao"))
    }

    suspend fun criarDiagrama(cidadeId: String, nome: String, conteudo: JSONObject): Diagrama {
        val r = pedir("POST", "/api/cidades/${q(cidadeId)}/diagramas",
                      JSONObject().put("nome", nome).put("conteudo", conteudo))
        return Diagrama(r.getString("id"), conteudo, r.getString("versao"))
    }

    suspend fun salvar(cidadeId: String, diagramaId: String, conteudo: JSONObject,
                       versaoBase: String, forcar: Boolean = false): String =
        pedir("PUT", "/api/cidades/${q(cidadeId)}/diagramas/${q(diagramaId)}",
              JSONObject().put("conteudo", conteudo).put("versao_base", versaoBase)
                  .put("forcar", forcar)).getString("versao")
}

/** O "local" dentro do diagrama (o mesmo do programa de PC). */
object Local {
    fun novoDiagrama(tipo: String, nome: String, cidade: String, endereco: String,
                     lat: Double?, lon: Double?): JSONObject {
        val local = JSONObject().put("tipo", tipo).put("nome", nome).put("cidade", cidade)
            .put("endereco", endereco).put("obs", "")
            .put("lat", lat ?: JSONObject.NULL).put("lon", lon ?: JSONObject.NULL)
        return JSONObject().put("versao", "M0.1").put("local", local)
            .put("equipamentos", JSONArray()).put("fusoes", JSONArray())
            .put("_contador", 0).put("_contador_fusao", 0).put("_contador_ordem", 0)
    }

    fun atualizar(conteudo: JSONObject, tipo: String, nome: String, endereco: String,
                  lat: Double?, lon: Double?): JSONObject {
        val local = conteudo.optJSONObject("local") ?: JSONObject()
        local.put("tipo", tipo).put("nome", nome).put("endereco", endereco)
            .put("lat", lat ?: JSONObject.NULL).put("lon", lon ?: JSONObject.NULL)
        conteudo.put("local", local)
        return conteudo
    }
}
