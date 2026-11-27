package com.waspfiber.app

import org.json.JSONArray
import org.json.JSONObject

/**
 * O diagrama de fusao, editado direto no MESMO JSON do programa de PC
 * (waspfiber.py: Rede / Equipamento / Modulo / Fusao). Tudo o que o app nao
 * conhece (posicao no desenho, potencia, conectores...) fica como esta.
 * As regras sao as mesmas do PC:
 *  - DIO: cada porta tem traseira (T, fusao) e frente (F, cordao);
 *  - cabo: cada fibra tem ponta A e ponta B, sempre 1 fusao por ponta;
 *  - porta simplex aceita 1 fusao, duplex 2;
 *  - splitter: porta 1 = ENT, as outras S1, S2...; OLT conta a partir de 0;
 *  - nao liga uma porta nela mesma.
 */

data class Ponta(val eq: String, val modulo: String, val porta: Int)

data class InfoPorta(val ponta: Ponta, val rotulo: String, val corFibra: Int?, val nomeCor: String?)

data class InfoModulo(val id: String, val nome: String, val tipo: String, val portas: List<InfoPorta>)

data class InfoEquipamento(val id: String, val nome: String, val tipo: String,
                           val modulos: List<InfoModulo>) {
    val totalPortas get() = modulos.sumOf { it.portas.size }
}

data class InfoFusao(val id: String, val a: Ponta, val b: Ponta, val rotulo: String)

class ErroModelo(mensagem: String) : Exception(mensagem)

class Modelo(val json: JSONObject) {

    companion object {
        const val DIO = "DIO"
        const val CABO = "CABO"
        const val ACOMODADOR = "ACOMODADOR"
        val ATIVOS = listOf("OLT", "SWITCH", "RB")
        val TODOS = listOf(CABO, DIO, ACOMODADOR) + ATIVOS
        val LADOS = mapOf(DIO to listOf("T" to "Traseira (fusao)", "F" to "Frente (conector)"),
                          CABO to listOf("A" to "Ponta A", "B" to "Ponta B"))
        val LADO_PADRAO = mapOf(DIO to "F", CABO to "A")
        val SPLITTERS = linkedMapOf("1x2" to 2, "1x4" to 4, "1x8" to 8, "1x16" to 16)
        val PLACAS_OLT = linkedMapOf("GPON-8" to 8, "GPON-16" to 16, "CONTROLE" to 4)
        val GRUPAMENTOS = linkedMapOf("SFP" to "Portas SFP+/SFP28", "QSFP" to "Portas QSFP (40/100GE)")
        const val MAX_SPLITTERS = 12

        /** codigo de cores ABNT NBR 14721 (o mesmo do PC) */
        val CORES_ABNT = listOf(
            "verde" to 0xFF2E9E44.toInt(), "amarelo" to 0xFFF2D200.toInt(),
            "branco" to 0xFFF0F0F0.toInt(), "azul" to 0xFF2F6FDE.toInt(),
            "vermelho" to 0xFFE03030.toInt(), "violeta" to 0xFF8A3FD1.toInt(),
            "marrom" to 0xFF8B5A2B.toInt(), "rosa" to 0xFFFF5FA8.toInt(),
            "preto" to 0xFF0B0B0B.toInt(), "cinza" to 0xFF8F8F8F.toInt(),
            "laranja" to 0xFFFF8A1F.toInt(), "aqua" to 0xFF33D6E6.toInt())

        fun corFibra(numero: Int, fibrasPorTubo: Int): Pair<String, Int> {
            val fpt = fibrasPorTubo.coerceAtLeast(1)
            return CORES_ABNT[((numero - 1) % fpt) % 12]
        }

        fun nomeTipo(tipo: String) = when (tipo) {
            ACOMODADOR -> "CTO / acomodador"; CABO -> "Cabo"; else -> tipo
        }
    }

    init {
        if (!json.has("equipamentos")) json.put("equipamentos", JSONArray())
        if (!json.has("fusoes")) json.put("fusoes", JSONArray())
        normalizarFusoes()
    }

    private val eqs get() = json.getJSONArray("equipamentos")
    private val fus get() = json.getJSONArray("fusoes")

    private fun eqJson(id: String): JSONObject? {
        for (i in 0 until eqs.length()) if (eqs.getJSONObject(i).getString("id") == id) return eqs.getJSONObject(i)
        return null
    }

    private fun temLados(tipo: String) = tipo == DIO || tipo == CABO

    /** fusao antiga com porta de DIO/cabo sem lado = frente do DIO / ponta A */
    private fun normalizarFusoes() {
        for (i in 0 until fus.length()) {
            val f = fus.getJSONObject(i)
            for (lado in listOf("a", "b")) {
                if (f.isNull("modulo_$lado") || !f.has("modulo_$lado")) {
                    val eq = eqJson(f.getString("eq_$lado"))
                    val tipo = eq?.optString("tipo") ?: ""
                    LADO_PADRAO[tipo]?.let { f.put("modulo_$lado", it) }
                }
            }
        }
    }

    // ---------------- leitura ----------------
    fun equipamentos(): List<InfoEquipamento> = (0 until eqs.length())
        .map { eqs.getJSONObject(it) }
        .sortedBy { it.optInt("ordem") }
        .map { info(it) }

    fun equipamento(id: String): InfoEquipamento? = eqJson(id)?.let { info(it) }

    private fun info(e: JSONObject): InfoEquipamento {
        val id = e.getString("id")
        val tipo = e.getString("tipo")
        val modulos = mutableListOf<InfoModulo>()
        if (temLados(tipo)) {
            val n = e.optInt("num_portas")
            val fpt = e.optInt("fibras_por_tubo", 12)
            for ((lado, nome) in LADOS[tipo]!!) {
                modulos += InfoModulo(lado, nome, "LADO", (1..n).map { p ->
                    if (tipo == CABO) {
                        val (cor, rgb) = corFibra(p, fpt)
                        InfoPorta(Ponta(id, lado, p), "Fibra $p", rgb, cor)
                    } else InfoPorta(Ponta(id, lado, p), "Porta $p", null, null)
                })
            }
        } else {
            val ms = e.optJSONArray("modulos") ?: JSONArray()
            for (i in 0 until ms.length()) {
                val m = ms.getJSONObject(i)
                val mid = m.getString("id")
                val mtipo = m.optString("tipo")
                val numeros = m.optJSONObject("portas")?.keys()?.asSequence()?.map { it.toInt() }?.sorted()?.toList().orEmpty()
                modulos += InfoModulo(mid, m.optString("nome"), mtipo, numeros.map { p ->
                    InfoPorta(Ponta(id, mid, p), rotuloPorta(tipo, mtipo, p), null, null)
                })
            }
        }
        return InfoEquipamento(id, e.optString("nome"), tipo, modulos)
    }

    fun rotuloPorta(tipoEq: String, tipoModulo: String, porta: Int): String = when {
        tipoModulo in SPLITTERS -> if (porta == 1) "ENT" else "S${porta - 1}"
        tipoEq == "OLT" -> "PON ${porta - 1}"
        else -> "Porta $porta"
    }

    /** "DIO-01 porta 5 (traseira)" / "C1 fibra 5 (azul) ponta A" / "CTO / Splitter 1 S3" */
    fun nomePonta(p: Ponta): String {
        val e = eqJson(p.eq) ?: return "${p.eq}:${p.porta}"
        val nome = e.optString("nome")
        return when (e.optString("tipo")) {
            DIO -> "$nome porta ${p.porta} (${if (p.modulo == "T") "traseira" else "frente"})"
            CABO -> "$nome fibra ${p.porta} (${corFibra(p.porta, e.optInt("fibras_por_tubo", 12)).first}) ponta ${p.modulo}"
            else -> {
                val m = modulo(e, p.modulo)
                "$nome / ${m?.optString("nome") ?: p.modulo} ${rotuloPorta(e.optString("tipo"), m?.optString("tipo") ?: "", p.porta)}"
            }
        }
    }

    private fun modulo(e: JSONObject, id: String): JSONObject? {
        val ms = e.optJSONArray("modulos") ?: return null
        for (i in 0 until ms.length()) if (ms.getJSONObject(i).getString("id") == id) return ms.getJSONObject(i)
        return null
    }

    fun fusoes(): List<InfoFusao> = (0 until fus.length()).map { i ->
        val f = fus.getJSONObject(i)
        InfoFusao(f.getString("id"),
                  Ponta(f.getString("eq_a"), f.optString("modulo_a"), f.getInt("porta_a")),
                  Ponta(f.getString("eq_b"), f.optString("modulo_b"), f.getInt("porta_b")),
                  f.optString("rotulo"))
    }

    fun fusoesNa(p: Ponta): List<InfoFusao> = fusoes().filter { it.a == p || it.b == p }

    fun outraPonta(f: InfoFusao, p: Ponta) = if (f.a == p) f.b else f.a

    /** quantas fusoes a porta aceita (simplex 1, duplex 2; cabo sempre 1) */
    fun limite(p: Ponta): Int {
        val e = eqJson(p.eq) ?: return 0
        val tipo = e.optString("tipo")
        if (tipo == CABO) return 1
        if (tipo == DIO) {
            val esp = e.optJSONObject("portas_especiais")?.optJSONObject(p.modulo)?.optJSONObject(p.porta.toString())
            return if (esp?.optString("tipo_gbic") == "DUPLEX") 2 else 1
        }
        val porta = modulo(e, p.modulo)?.optJSONObject("portas")?.optJSONObject(p.porta.toString()) ?: return 0
        return if (porta.optString("tipo_gbic", "SIMPLEX") == "DUPLEX") 2 else 1
    }

    fun livre(p: Ponta) = fusoesNa(p).size < limite(p)

    fun ocupacao(eq: InfoEquipamento): Pair<Int, Int> {
        val usadas = fusoes().flatMap { listOf(it.a, it.b) }.filter { it.eq == eq.id }.toSet()
        return if (eq.tipo == DIO || eq.tipo == CABO) {
            val n = eq.modulos.firstOrNull()?.portas?.size ?: 0
            (1..n).count { num -> usadas.any { it.porta == num } } to n
        } else usadas.size to eq.totalPortas
    }

    private fun existe(p: Ponta): Boolean {
        val e = eqJson(p.eq) ?: return false
        return if (temLados(e.optString("tipo")))
            LADOS[e.optString("tipo")]!!.any { it.first == p.modulo } && p.porta in 1..e.optInt("num_portas")
        else modulo(e, p.modulo)?.optJSONObject("portas")?.has(p.porta.toString()) == true
    }

    // ---------------- fusoes ----------------
    fun criarFusao(a: Ponta, b: Ponta, rotulo: String = ""): InfoFusao {
        if (!existe(a)) throw ErroModelo("A porta ${nomePonta(a)} nao existe.")
        if (!existe(b)) throw ErroModelo("A porta ${nomePonta(b)} nao existe.")
        if (a == b) throw ErroModelo("Nao e possivel ligar uma porta a ela mesma.")
        for (p in listOf(a, b)) {
            if (fusoesNa(p).size >= limite(p))
                throw ErroModelo("A porta ${nomePonta(p)} ja esta ocupada.")
        }
        val n = json.optInt("_contador_fusao", fus.length()) + 1
        json.put("_contador_fusao", n)
        var id = "FUS-%04d".format(n)
        val ids = fusoes().map { it.id }.toSet()
        var extra = n
        while (id in ids) { extra++; id = "FUS-%04d".format(extra); json.put("_contador_fusao", extra) }
        fus.put(JSONObject().put("id", id).put("rotulo", rotulo)
                    .put("eq_a", a.eq).put("modulo_a", a.modulo).put("porta_a", a.porta)
                    .put("eq_b", b.eq).put("modulo_b", b.modulo).put("porta_b", b.porta))
        return InfoFusao(id, a, b, rotulo)
    }

    /** fusao em sequencia: a..a+n-1 com b..b+n-1 (igual ao Shift do PC). Se
     *  faltar porta ou alguma estiver ocupada, nao cria nenhuma. */
    fun criarEmSequencia(a: Ponta, b: Ponta, quantidade: Int, rotulo: String = ""): Int {
        val pares = (0 until quantidade).map {
            Ponta(a.eq, a.modulo, a.porta + it) to Ponta(b.eq, b.modulo, b.porta + it)
        }
        for ((pa, pb) in pares) {
            if (!existe(pa)) throw ErroModelo("Nao ha ${quantidade} portas a partir de ${nomePonta(a)}.")
            if (!existe(pb)) throw ErroModelo("Nao ha ${quantidade} portas a partir de ${nomePonta(b)}.")
            if (!livre(pa)) throw ErroModelo("${nomePonta(pa)} ja esta ocupada.")
            if (!livre(pb)) throw ErroModelo("${nomePonta(pb)} ja esta ocupada.")
        }
        pares.forEachIndexed { i, (pa, pb) ->
            criarFusao(pa, pb, if ("#" in rotulo) rotulo.replace("#", (i + 1).toString()) else rotulo)
        }
        return pares.size
    }

    fun removerFusao(id: String) {
        for (i in 0 until fus.length()) if (fus.getJSONObject(i).getString("id") == id) { fus.remove(i); return }
    }

    fun definirRotulo(id: String, rotulo: String) {
        for (i in 0 until fus.length()) if (fus.getJSONObject(i).getString("id") == id) {
            fus.getJSONObject(i).put("rotulo", rotulo); return
        }
    }

    // ---------------- equipamentos ----------------
    private fun faixaX(tipo: String) = when (tipo) {
        ACOMODADOR -> 0.0; CABO -> 440.0; DIO -> 800.0; else -> 1660.0
    }

    /** altura aproximada da caixa no desenho do PC (so pra nao empilhar uma
     *  em cima da outra; no PC, "Organizar" arruma de vez) */
    private fun alturaAprox(e: JSONObject): Double {
        val tipo = e.optString("tipo")
        if (temLados(tipo)) return 70.0 + e.optInt("num_portas") * 26.0
        val ms = e.optJSONArray("modulos") ?: JSONArray()
        var portas = 0
        for (i in 0 until ms.length()) portas += ms.getJSONObject(i).optJSONObject("portas")?.length() ?: 0
        return 90.0 + ms.length() * 30.0 + portas * 22.0
    }

    fun adicionarEquipamento(tipo: String, nome: String, quantidade: Int = 0,
                             fibrasPorTubo: Int = 12): InfoEquipamento {
        if (tipo !in TODOS) throw ErroModelo("Tipo invalido.")
        if (nome.isBlank()) throw ErroModelo("Informe o nome.")
        if (temLados(tipo) && quantidade < 1)
            throw ErroModelo("Informe pelo menos 1 ${if (tipo == CABO) "fibra" else "porta"}.")
        val ids = (0 until eqs.length()).map { eqs.getJSONObject(it).getString("id") }.toSet()
        var cont = json.optInt("_contador", eqs.length())
        var id: String
        do { cont++; id = "%s-%03d".format(tipo, cont) } while (id in ids)
        json.put("_contador", cont)
        val ordem = json.optInt("_contador_ordem", eqs.length()) + 1
        json.put("_contador_ordem", ordem)
        val fx = faixaX(tipo)
        var y = 0.0
        for (i in 0 until eqs.length()) {
            val e = eqs.getJSONObject(i)
            if (faixaX(e.optString("tipo")) == fx)
                y = maxOf(y, e.optDouble("pos_y", 0.0) + alturaAprox(e) + 40.0)
        }
        val e = JSONObject().put("id", id).put("nome", nome.trim()).put("tipo", tipo)
            .put("ordem", ordem).put("lado", JSONObject.NULL).put("pos_x", fx).put("pos_y", y)
            .put("orientacao", if (tipo == DIO || tipo == "OLT") "vertical" else "horizontal")
        if (temLados(tipo)) {
            e.put("num_portas", quantidade)
            if (tipo == CABO) e.put("fibras_por_tubo", fibrasPorTubo.coerceIn(1, 24))
        } else {
            e.put("modulos", JSONArray()).put("_contador_modulo", 0)
        }
        eqs.put(e)
        if (tipo == ACOMODADOR) repeat(quantidade.coerceIn(0, MAX_SPLITTERS)) { adicionarSplitter(id, "1x8") }
        return info(e)
    }

    fun renomearEquipamento(id: String, nome: String) {
        if (nome.isBlank()) throw ErroModelo("Informe o nome.")
        eqJson(id)?.put("nome", nome.trim())
    }

    fun removerEquipamento(id: String) {
        for (i in fus.length() - 1 downTo 0) {
            val f = fus.getJSONObject(i)
            if (f.getString("eq_a") == id || f.getString("eq_b") == id) fus.remove(i)
        }
        for (i in 0 until eqs.length()) if (eqs.getJSONObject(i).getString("id") == id) { eqs.remove(i); return }
    }

    private fun novoModulo(eqId: String, prefixo: String, nome: String, tipo: String, portas: Int,
                           gbicFixo: String?, conector: String?, polimento: String?): InfoModulo {
        val e = eqJson(eqId) ?: throw ErroModelo("Equipamento nao encontrado.")
        val ms = e.optJSONArray("modulos") ?: JSONArray().also { e.put("modulos", it) }
        val cont = e.optInt("_contador_modulo", ms.length()) + 1
        e.put("_contador_modulo", cont)
        val id = "%s-%s-%02d".format(eqId, prefixo, cont)
        val ps = JSONObject()
        for (n in 1..portas) {
            ps.put(n.toString(), JSONObject().put("numero", n).put("tipo_gbic", gbicFixo ?: "SIMPLEX")
                .put("conector", conector ?: JSONObject.NULL).put("polimento", polimento ?: JSONObject.NULL))
        }
        ms.put(JSONObject().put("id", id).put("nome", nome).put("tipo", tipo)
                   .put("gbic_fixo", gbicFixo ?: JSONObject.NULL).put("portas", ps))
        return info(e).modulos.first { it.id == id }
    }

    fun adicionarSplitter(eqId: String, tipo: String): InfoModulo {
        val e = eqJson(eqId) ?: throw ErroModelo("Equipamento nao encontrado.")
        if (e.optString("tipo") != ACOMODADOR) throw ErroModelo("Splitter so em CTO / acomodador.")
        val n = e.optJSONArray("modulos")?.length() ?: 0
        if (n >= MAX_SPLITTERS) throw ErroModelo("No maximo $MAX_SPLITTERS splitters.")
        val saidas = SPLITTERS[tipo] ?: throw ErroModelo("Splitter invalido.")
        return novoModulo(eqId, "SPLIT", "Splitter ${n + 1} ($tipo)", tipo, 1 + saidas, "SIMPLEX", "SC", "APC")
    }

    fun adicionarPlaca(eqId: String, tipo: String): InfoModulo {
        val e = eqJson(eqId) ?: throw ErroModelo("Equipamento nao encontrado.")
        if (e.optString("tipo") != "OLT") throw ErroModelo("Placa so em OLT.")
        val portas = PLACAS_OLT[tipo] ?: throw ErroModelo("Placa invalida.")
        val n = e.optJSONArray("modulos")?.length() ?: 0
        val rotulo = when (tipo) {
            "CONTROLE" -> "Placa de Controle (4 portas)"; else -> "Placa GPON ($portas portas)"
        }
        return if (tipo == "CONTROLE") novoModulo(eqId, "PLACA", "Placa ${n + 1} ($rotulo)", tipo, portas, null, "LC", "UPC")
        else novoModulo(eqId, "PLACA", "Placa ${n + 1} ($rotulo)", tipo, portas, "SIMPLEX", "SC", "UPC")
    }

    fun adicionarGrupamento(eqId: String, tipo: String, portas: Int): InfoModulo {
        val e = eqJson(eqId) ?: throw ErroModelo("Equipamento nao encontrado.")
        if (e.optString("tipo") !in listOf("SWITCH", "RB")) throw ErroModelo("Grupamento so em switch ou RB.")
        if (portas < 1) throw ErroModelo("Pelo menos 1 porta.")
        val nome = "${GRUPAMENTOS[tipo] ?: throw ErroModelo("Grupamento invalido.")} (${portas}p)"
        return novoModulo(eqId, "GRP", nome, tipo, portas, null, "LC", "UPC")
    }

    fun removerModulo(eqId: String, moduloId: String) {
        val e = eqJson(eqId) ?: return
        for (i in fus.length() - 1 downTo 0) {
            val f = fus.getJSONObject(i)
            if ((f.getString("eq_a") == eqId && f.optString("modulo_a") == moduloId) ||
                (f.getString("eq_b") == eqId && f.optString("modulo_b") == moduloId)) fus.remove(i)
        }
        val ms = e.optJSONArray("modulos") ?: return
        for (i in 0 until ms.length()) if (ms.getJSONObject(i).getString("id") == moduloId) { ms.remove(i); return }
    }

    fun copia(): Modelo = Modelo(JSONObject(json.toString()))
}
