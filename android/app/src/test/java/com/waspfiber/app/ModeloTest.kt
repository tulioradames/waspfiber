package com.waspfiber.app

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.File

class ModeloTest {
    private fun novo() = Modelo(JSONObject().put("versao", "M0.2").put("equipamentos", org.json.JSONArray())
        .put("fusoes", org.json.JSONArray()).put("_contador", 0).put("_contador_fusao", 0).put("_contador_ordem", 0))

    @Test
    fun redeCompleta() {
        val m = novo()
        val cabo = m.adicionarEquipamento(Modelo.CABO, "Cabo 12FO", 12)
        val dio = m.adicionarEquipamento(Modelo.DIO, "DIO 01", 24)
        val cto = m.adicionarEquipamento(Modelo.ACOMODADOR, "CTO 03", 2)
        val olt = m.adicionarEquipamento("OLT", "OLT", 0)
        val placa = m.adicionarPlaca(olt.id, "GPON-16")
        val sw = m.adicionarEquipamento("SWITCH", "SW", 0)
        m.adicionarGrupamento(sw.id, "SFP", 4)
        assertEquals("CABO-001", cabo.id)
        assertEquals("ACOMODADOR-003", cto.id)
        val split = m.equipamento(cto.id)!!.modulos
        assertEquals(listOf("ACOMODADOR-003-SPLIT-01", "ACOMODADOR-003-SPLIT-02"), split.map { it.id })
        assertEquals("ENT", split[0].portas[0].rotulo)
        assertEquals("S8", split[0].portas[8].rotulo)

        // fibras 1..4 do cabo (ponta A) na traseira do DIO 1..4
        assertEquals(4, m.criarEmSequencia(Ponta(cabo.id, "A", 1), Ponta(dio.id, "T", 1), 4, "Cliente #"))
        assertEquals("Cliente 3", m.fusoes()[2].rotulo)
        m.criarFusao(Ponta(dio.id, "F", 1), Ponta(olt.id, placa.id, 1), "PON 0")
        m.criarFusao(Ponta(cabo.id, "B", 1), Ponta(cto.id, split[0].id, 1))
        assertEquals("FUS-0006", m.fusoes().last().id)

        // ocupada / ela mesma / fora do intervalo
        assertThrows(ErroModelo::class.java) { m.criarFusao(Ponta(cabo.id, "A", 1), Ponta(dio.id, "T", 9)) }
        assertThrows(ErroModelo::class.java) { m.criarFusao(Ponta(dio.id, "T", 9), Ponta(dio.id, "T", 9)) }
        assertThrows(ErroModelo::class.java) { m.criarFusao(Ponta(dio.id, "T", 25), Ponta(dio.id, "T", 9)) }
        // sequencia que bate numa ocupada nao cria nada
        val antes = m.fusoes().size
        assertThrows(ErroModelo::class.java) { m.criarEmSequencia(Ponta(cabo.id, "A", 3), Ponta(dio.id, "T", 10), 3) }
        assertEquals(antes, m.fusoes().size)

        assertEquals("Cabo 12FO fibra 4 (azul) ponta A", m.nomePonta(Ponta(cabo.id, "A", 4)))
        assertEquals("DIO 01 porta 1 (frente)", m.nomePonta(Ponta(dio.id, "F", 1)))
        assertEquals(4 to 12, m.ocupacao(m.equipamento(cabo.id)!!))

        // remove fusao e equipamento
        m.removerFusao("FUS-0002")
        assertEquals(5, m.fusoes().size)
        m.removerEquipamento(sw.id)
        assertEquals(4, m.equipamentos().size)

        // vai pro PC conferir (teste_modelo_android.py)
        File(System.getProperty("java.io.tmpdir"), "waspfiber_android_modelo.json").writeText(m.json.toString(1))
    }
}
