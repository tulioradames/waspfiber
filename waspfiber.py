# -*- coding: utf-8 -*-
"""
WaspFiber - diagramas de fusao e fibra optica (FTTX)
====================================================
Programa desktop para documentar fusoes de rede FTTX: cadastre DIOs,
Acomodadores (com splitters), OLTs (com placas) e Switches/RBs (com
grupamentos), conecte porta a porta com dois cliques no diagrama e exporte
o diagrama, o relatorio porta a porta e a lista de pendencias.

NAO precisa instalar nada: usa apenas a biblioteca padrao do Python
(tkinter). O diagrama e desenhado no proprio Canvas do tkinter e as
exportacoes (PDF, SVG, PS, CSV) sao escritas direto pelo programa.

Como rodar:      python waspfiber.py
Autoteste:       python waspfiber.py --autoteste
"""

import json
import os
import re
import sys
import textwrap
import time
import unicodedata

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import waspfiber_ui as nix_ui   # icones, botoes, menus e cartoes da interface
import waspfiber_mapa as mapa   # localizacao do diagrama (B0.34)
import waspfiber_nuvem as nuvem   # servidor: login, cidades e diagramas (B0.39)

APP_NOME = "WaspFiber"
VERSAO = "B0.41"
EXTENSAO = ".wasp.json"
EXTENSAO_NIX = ".nix.json"      # redes salvas quando o programa se chamava Nix

# ============================================================================
#  MODELO DE DADOS
# ============================================================================

TIPO_DIO = "DIO"
TIPO_ACOMODADOR = "ACOMODADOR"
TIPO_CABO = "CABO"
TIPOS_ATIVOS = ["OLT", "SWITCH", "RB"]
TIPOS_PASSIVOS = [TIPO_DIO, TIPO_CABO, TIPO_ACOMODADOR]
TODOS_TIPOS = TIPOS_PASSIVOS + TIPOS_ATIVOS

# Equipamentos de "passagem", com dois lados (B0.25): o DIO tem a traseira
# (onde a fibra do cabo e fundida na bandeja) e a frente (onde entra o
# cordao); o cabo tem a ponta A e a ponta B de cada fibra. Cada lado vira um
# "modulo" interno, entao a porta continua sendo (equipamento, lado, numero).
TIPOS_COM_LADOS = (TIPO_DIO, TIPO_CABO)
LADOS = {TIPO_DIO: (("T", "Traseira (fusao)"), ("F", "Frente (conector)")),
         TIPO_CABO: (("A", "Ponta A"), ("B", "Ponta B"))}
LADO_PADRAO = {TIPO_DIO: "F", TIPO_CABO: "A"}
TIPO_MODULO_LADO = "LADO"

# Codigo de cores das fibras e dos tubos - ABNT NBR 14721 (o usado no Brasil)
CORES_ABNT = [("verde", "#2e9e44"), ("amarelo", "#f2d200"), ("branco", "#f0f0f0"),
              ("azul", "#2f6fde"), ("vermelho", "#e03030"), ("violeta", "#8a3fd1"),
              ("marrom", "#8b5a2b"), ("rosa", "#ff5fa8"), ("preto", "#0b0b0b"),
              ("cinza", "#8f8f8f"), ("laranja", "#ff8a1f"), ("aqua", "#33d6e6")]
FIBRAS_POR_TUBO_PADRAO = 12


def cor_fibra(numero, fibras_por_tubo=FIBRAS_POR_TUBO_PADRAO):
    """(nome, cor) da fibra: a sequencia de 12 cores recomeca a cada tubo."""
    fpt = max(1, int(fibras_por_tubo or FIBRAS_POR_TUBO_PADRAO))
    return CORES_ABNT[((numero - 1) % fpt) % 12]


def tubo_da_fibra(numero, fibras_por_tubo=FIBRAS_POR_TUBO_PADRAO):
    """(numero do tubo, nome da cor, cor) - o tubo tambem segue a ABNT."""
    fpt = max(1, int(fibras_por_tubo or FIBRAS_POR_TUBO_PADRAO))
    tubo = (numero - 1) // fpt + 1
    nome, cor = CORES_ABNT[(tubo - 1) % 12]
    return tubo, nome, cor

SIMPLEX = "SIMPLEX"
DUPLEX = "DUPLEX"

# Tipo de conector de cada porta (B0.31). Porta duplex e sempre LC (o SC
# duplex praticamente nao existe em campo). Traseira do DIO e pontas de
# fibra de cabo sao fusao: nao tem conector.
CONECTORES = ("SC", "LC")
POLIMENTOS = ("APC", "UPC")


def conector_padrao(tipo_eq, tipo_mod, lado=None):
    """(conector, polimento) com que a porta nasce - padrao de FTTH:
    DIO e splitter SC/APC (verde), placa GPON SC/UPC, o resto LC/UPC."""
    if tipo_mod == "LADO":
        return ("SC", "APC") if (tipo_eq == "DIO" and lado == "F") else (None, None)
    if tipo_mod in ("1x2", "1x4", "1x8", "1x16"):
        return ("SC", "APC")
    if tipo_mod in ("GPON-8", "GPON-16"):
        return ("SC", "UPC")
    return ("LC", "UPC")


def texto_conector(conector, polimento, duplex=False):
    if not conector:
        return ""
    return "%s/%s%s" % (conector, polimento or "", " duplex" if duplex else "")

# Placas de OLT: nome -> nº de portas + se o GBIC fica travado
TIPOS_PLACA_OLT = {
    "GPON-8": {"portas": 8, "gbic_fixo": SIMPLEX, "rotulo": "Placa GPON (8 portas)"},
    "GPON-16": {"portas": 16, "gbic_fixo": SIMPLEX, "rotulo": "Placa GPON (16 portas)"},
    "CONTROLE": {"portas": 4, "gbic_fixo": None, "rotulo": "Placa de Controle (4 portas)"},
}

# Splitters de acomodador: porta 1 = entrada (ENT), demais = saidas (S1, S2...)
TIPOS_SPLITTER = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
MAX_SPLITTERS_POR_ACOMODADOR = 12

# Grupamentos de SWITCH/RB: quantidade de portas definida pelo usuario
TIPOS_GRUPO_ATIVO = {
    "SFP": "Portas SFP+/SFP28",
    "QSFP": "Portas QSFP (40/100GE)",
}


class Porta:
    """Uma porta dentro de um modulo. Portas de DIO nao usam esta classe."""

    def __init__(self, numero, tipo_gbic=SIMPLEX, conector=None, polimento=None,
                 potencia=None):
        self.numero = numero
        self.tipo_gbic = tipo_gbic
        self.conector = conector
        self.polimento = polimento
        self.potencia = potencia       # dBm de saida (porta de OLT), ou None

    def limite(self):
        return 1 if self.tipo_gbic == SIMPLEX else 2

    def to_dict(self):
        d = {"numero": self.numero, "tipo_gbic": self.tipo_gbic,
             "conector": self.conector, "polimento": self.polimento}
        if self.potencia is not None:
            d["potencia"] = self.potencia
        return d


class Modulo:
    """Placa de OLT, grupamento de SWITCH/RB ou splitter de acomodador."""

    def __init__(self, id_, nome, tipo, num_portas, gbic_fixo=None, conector=None,
                 polimento=None):
        self.id = id_
        self.nome = nome
        self.tipo = tipo
        self.gbic_fixo = gbic_fixo
        inicial = gbic_fixo or SIMPLEX
        if inicial == DUPLEX and conector:
            conector = "LC"
        self.portas = {i: Porta(i, inicial, conector, polimento)
                       for i in range(1, num_portas + 1)}

    @property
    def num_portas(self):
        return len(self.portas)

    def eh_splitter(self):
        return self.tipo in TIPOS_SPLITTER

    def eh_lado(self):
        return self.tipo == TIPO_MODULO_LADO

    def to_dict(self):
        return {"id": self.id, "nome": self.nome, "tipo": self.tipo,
                "gbic_fixo": self.gbic_fixo,
                "portas": {str(k): v.to_dict() for k, v in self.portas.items()}}

    @staticmethod
    def from_dict(d):
        m = Modulo(d["id"], d["nome"], d["tipo"], 0, d.get("gbic_fixo"))
        m.portas = {int(k): Porta(v["numero"], v.get("tipo_gbic", SIMPLEX),
                                  v.get("conector"), v.get("polimento"), v.get("potencia"))
                    for k, v in d.get("portas", {}).items()}
        return m

    def completar_conectores(self, tipo_eq, lado=None, forcar=False):
        """Portas sem tipo (redes antigas, portas novas) recebem o padrao."""
        conector, polimento = conector_padrao(tipo_eq, self.tipo, lado)
        for porta in self.portas.values():
            if forcar or (porta.conector is None and conector):
                porta.conector = "LC" if porta.tipo_gbic == DUPLEX and conector else conector
                porta.polimento = polimento


def orientacao_padrao(tipo):
    """DIO e OLT em pe (uma porta por linha, alinhadas com o vizinho);
    switch/RB deitados (fileiras de gaiolas). Da pra girar qualquer um."""
    return "vertical" if tipo in (TIPO_DIO, "OLT") else "horizontal"


class Equipamento:
    """DIO (portas soltas) ou ACOMODADOR/OLT/SWITCH/RB (portas em modulos).

    pos_x/pos_y = canto superior esquerdo da caixa no diagrama. O eixo Y
    cresce PARA BAIXO (como na tela), pra nao precisar inverter nada.
    """

    def __init__(self, id_, nome, tipo, num_portas=0, ordem=0):
        if tipo not in TODOS_TIPOS:
            raise ValueError("Tipo invalido: %s" % tipo)
        self.id = id_
        self.nome = nome
        self.tipo = tipo
        self.num_portas = num_portas if tipo in TIPOS_COM_LADOS else 0
        self.fibras_por_tubo = FIBRAS_POR_TUBO_PADRAO
        self.modulos = {}
        self._contador_modulo = 0
        self.ordem = ordem
        self.lado = None
        # DIO: "vertical" (uma porta por linha, alinhada com as fibras do
        # cabo - padrao desde a B0.27) ou "horizontal" (o painel visto de frente)
        self.orientacao = orientacao_padrao(tipo)
        self.pos_x = 0.0
        self.pos_y = 0.0
        if self.tem_lados():
            self._montar_lados()

    def is_dio(self):
        return self.tipo == TIPO_DIO

    def is_cabo(self):
        return self.tipo == TIPO_CABO

    def tem_lados(self):
        """DIO e cabo: portas soltas, com dois lados (sem placas/splitters)."""
        return self.tipo in TIPOS_COM_LADOS

    def _montar_lados(self):
        """(Re)cria os dois lados com num_portas cada. As fusoes ficam na
        rede, presas so ao numero - entao refazer os lados nao perde nada."""
        for lado_id, nome in LADOS[self.tipo]:
            antigo = self.modulos.get(lado_id)
            conector, polimento = conector_padrao(self.tipo, TIPO_MODULO_LADO, lado_id)
            # so o cabo e travado em simplex; a porta do DIO pode ser duplex (LC)
            novo = Modulo(lado_id, nome, TIPO_MODULO_LADO, self.num_portas,
                          SIMPLEX if self.is_cabo() else None, conector, polimento)
            if antigo is not None:        # mantem o tipo de cada porta que ja existia
                for n, porta in antigo.portas.items():
                    if n in novo.portas:
                        novo.portas[n] = porta
            self.modulos[lado_id] = novo

    def lado_efetivo(self):
        """Para que lado da caixa saem os conectores das portas."""
        if self.lado in ("esquerda", "direita"):
            return self.lado
        # DIO: frente (conectores) pra direita, traseira (fusao) pra esquerda;
        # cabo: ponta B pra direita, A pra esquerda. Acomodador: saidas pra
        # esquerda e ENT pra direita. Ativos: portas olhando pra esquerda,
        # de frente pro DIO.
        return "direita" if self.tipo in TIPOS_COM_LADOS else "esquerda"

    def _novo_id_modulo(self, prefixo):
        self._contador_modulo += 1
        return "%s-%s-%02d" % (self.id, prefixo, self._contador_modulo)

    def add_placa(self, tipo_placa, nome=None):
        if self.tipo != "OLT":
            raise ValueError("Placas so podem ser adicionadas a uma OLT.")
        if tipo_placa not in TIPOS_PLACA_OLT:
            raise ValueError("Tipo de placa invalido: %s" % tipo_placa)
        info = TIPOS_PLACA_OLT[tipo_placa]
        nome = nome or "Placa %d (%s)" % (len(self.modulos) + 1, info["rotulo"])
        m = Modulo(self._novo_id_modulo("PLACA"), nome, tipo_placa,
                   info["portas"], info["gbic_fixo"], *conector_padrao("OLT", tipo_placa))
        self.modulos[m.id] = m
        return m

    def add_splitter(self, tipo_splitter="1x8", nome=None):
        if self.tipo != TIPO_ACOMODADOR:
            raise ValueError("Splitters so podem ser adicionados a um ACOMODADOR.")
        if tipo_splitter not in TIPOS_SPLITTER:
            raise ValueError("Tipo de splitter invalido: %s" % tipo_splitter)
        if len(self.modulos) >= MAX_SPLITTERS_POR_ACOMODADOR:
            raise ValueError("Um acomodador comporta no maximo %d splitters."
                             % MAX_SPLITTERS_POR_ACOMODADOR)
        nome = nome or "Splitter %d (%s)" % (len(self.modulos) + 1, tipo_splitter)
        m = Modulo(self._novo_id_modulo("SPLIT"), nome, tipo_splitter,
                   1 + TIPOS_SPLITTER[tipo_splitter], SIMPLEX,
                   *conector_padrao(TIPO_ACOMODADOR, tipo_splitter))
        self.modulos[m.id] = m
        return m

    def add_grupamento(self, tipo_grupo, num_portas, nome=None):
        if self.tipo not in ("SWITCH", "RB"):
            raise ValueError("Grupamentos so podem ser adicionados a SWITCH ou RB.")
        if tipo_grupo not in TIPOS_GRUPO_ATIVO:
            raise ValueError("Tipo de grupamento invalido: %s" % tipo_grupo)
        if num_portas < 1:
            raise ValueError("O grupamento precisa de pelo menos 1 porta.")
        nome = nome or "%s (%dp)" % (TIPOS_GRUPO_ATIVO[tipo_grupo], num_portas)
        m = Modulo(self._novo_id_modulo("GRP"), nome, tipo_grupo, num_portas, None,
                   *conector_padrao(self.tipo, tipo_grupo))
        self.modulos[m.id] = m
        return m

    def total_portas(self):
        if self.tem_lados():
            return self.num_portas
        return sum(m.num_portas for m in self.modulos.values())

    def to_dict(self):
        d = {"id": self.id, "nome": self.nome, "tipo": self.tipo, "ordem": self.ordem,
             "lado": self.lado, "pos_x": self.pos_x, "pos_y": self.pos_y,
             "orientacao": self.orientacao}
        if self.tem_lados():
            d["num_portas"] = self.num_portas
            if self.is_cabo():
                d["fibras_por_tubo"] = self.fibras_por_tubo
            else:
                # so o que foge do padrao (duplex, outro conector)
                especiais = {}
                for lado_id, _ in LADOS[self.tipo]:
                    padrao = conector_padrao(self.tipo, TIPO_MODULO_LADO, lado_id)
                    for n, porta in self.modulos[lado_id].portas.items():
                        if porta.tipo_gbic != SIMPLEX or \
                                (porta.conector, porta.polimento) != padrao:
                            especiais.setdefault(lado_id, {})[str(n)] = porta.to_dict()
                if especiais:
                    d["portas_especiais"] = especiais
        else:
            d["modulos"] = [m.to_dict() for m in self.modulos.values()]
            d["_contador_modulo"] = self._contador_modulo
        return d

    @staticmethod
    def from_dict(d):
        eq = Equipamento(d["id"], d["nome"], d["tipo"],
                         d.get("num_portas", 0), d.get("ordem", 0))
        eq.lado = d.get("lado")
        eq.pos_x = d.get("pos_x") or 0.0
        eq.pos_y = d.get("pos_y") or 0.0
        eq.fibras_por_tubo = d.get("fibras_por_tubo") or FIBRAS_POR_TUBO_PADRAO
        eq.orientacao = d.get("orientacao") or orientacao_padrao(eq.tipo)
        for md in ([] if eq.tem_lados() else d.get("modulos", [])):
            m = Modulo.from_dict(md)
            m.completar_conectores(eq.tipo)        # redes antigas: padrao de FTTH
            eq.modulos[m.id] = m
        for lado_id, portas in (d.get("portas_especiais") or {}).items():
            mod = eq.modulos.get(lado_id)
            for n, pd in portas.items():
                if mod is not None and int(n) in mod.portas:
                    mod.portas[int(n)] = Porta(int(n), pd.get("tipo_gbic", SIMPLEX),
                                               pd.get("conector"), pd.get("polimento"))
        eq._contador_modulo = d.get("_contador_modulo", len(eq.modulos))
        return eq


class Fusao:
    """Liga a porta (eq_a, modulo_a, porta_a) a porta (eq_b, modulo_b, porta_b).
    modulo_* e None quando a ponta e um DIO."""

    def __init__(self, id_, eq_a, modulo_a, porta_a, eq_b, modulo_b, porta_b, rotulo=""):
        self.id = id_
        self.eq_a, self.modulo_a, self.porta_a = eq_a, modulo_a, porta_a
        self.eq_b, self.modulo_b, self.porta_b = eq_b, modulo_b, porta_b
        self.rotulo = rotulo

    def pontas(self):
        return ((self.eq_a, self.modulo_a, self.porta_a),
                (self.eq_b, self.modulo_b, self.porta_b))

    def toca(self, eq_id, modulo_id, porta_num):
        return (eq_id, modulo_id, porta_num) in self.pontas()

    def outra_ponta(self, eq_id, modulo_id, porta_num):
        a, b = self.pontas()
        return b if a == (eq_id, modulo_id, porta_num) else a

    def to_dict(self):
        return {"id": self.id, "rotulo": self.rotulo,
                "eq_a": self.eq_a, "modulo_a": self.modulo_a, "porta_a": self.porta_a,
                "eq_b": self.eq_b, "modulo_b": self.modulo_b, "porta_b": self.porta_b}

    @staticmethod
    def from_dict(d):
        return Fusao(d["id"], d["eq_a"], d.get("modulo_a"), d["porta_a"],
                     d["eq_b"], d.get("modulo_b"), d["porta_b"], d.get("rotulo", ""))


class Rede:
    """Todos os equipamentos + fusoes, com as regras de validacao."""

    # colunas do diagrama, da ponta do cliente ate a central:
    # acomodador (CTO) | cabo | DIO | ativos - como o sinal chega no campo
    FAIXA_X = {TIPO_ACOMODADOR: 0.0, TIPO_CABO: 440.0, TIPO_DIO: 800.0}
    FAIXA_X_ATIVO = 1660.0
    GAP_Y = 40.0
    GAP_COLUNA = 160.0

    def __init__(self):
        self.equipamentos = {}
        self.fusoes = {}
        self._contador = 0
        self._contador_fusao = 0
        self._contador_ordem = 0
        # indice (eq_id, modulo_id, porta) -> fusoes, pra nao varrer a lista
        # inteira a cada consulta (o diagrama consulta porta por porta)
        self._indice = {}
        # B0.34: o local do campo a que este diagrama pertence (POP, caixa de
        # emenda ou CTO) - tipo, nome, endereco, cidade, lat/lon, observacao
        self.local = mapa.local_vazio()

    def definir_local(self, dados):
        self.local = mapa.normalizar_local(dados)

    # ---------------- indice de ocupacao ----------------
    def reindexar(self):
        self._indice = {}
        for f in self.fusoes.values():
            for ponta in f.pontas():
                self._indice.setdefault(ponta, []).append(f)

    def lado_padrao(self, eq_id, modulo_id):
        """Compatibilidade: porta de DIO/cabo informada sem lado (None, como
        nas versoes antigas) vale como a frente do DIO / ponta A do cabo."""
        if modulo_id is None:
            eq = self.equipamentos.get(eq_id)
            if eq is not None and eq.tem_lados():
                return LADO_PADRAO[eq.tipo]
        return modulo_id

    def fusoes_na_porta(self, eq_id, modulo_id, porta_num):
        if modulo_id is None:
            modulo_id = self.lado_padrao(eq_id, None)
        return list(self._indice.get((eq_id, modulo_id, porta_num), ()))

    def ocupacao(self, eq):
        """(usadas, total) pra mostrar capacidade. DIO e cabo contam por
        posicao: a porta/fibra esta em uso se qualquer lado tiver fusao."""
        if eq.tem_lados():
            lados = [l for l, _ in LADOS[eq.tipo]]
            usadas = sum(1 for n in range(1, eq.num_portas + 1)
                         if any(self._indice.get((eq.id, l, n)) for l in lados))
            return usadas, eq.num_portas
        portas = self.todas_as_portas(eq)
        return sum(1 for c in portas if self._indice.get(c)), len(portas)

    # ---------------- equipamentos ----------------
    def _faixa_x(self, tipo):
        return self.FAIXA_X.get(tipo, self.FAIXA_X_ATIVO)

    def _posicao_padrao(self, tipo):
        """Espalha equipamentos novos em 3 faixas verticais (DIO / acomodador /
        ativos), empilhando abaixo do ultimo da mesma faixa."""
        fx = self._faixa_x(tipo)
        na_faixa = [e for e in self.equipamentos.values() if self._faixa_x(e.tipo) == fx]
        if not na_faixa:
            return fx, 0.0
        base = max(e.pos_y + layout_equipamento(e)["altura"] + self.altura_extra(e)
                   for e in na_faixa)
        return fx, base + self.GAP_Y

    def add_equipamento(self, nome, tipo, num_portas=0, id_=None, fibras_por_tubo=None):
        if id_ is None:
            self._contador += 1
            id_ = "%s-%03d" % (tipo, self._contador)
            while id_ in self.equipamentos:        # ids ja usados nao colidem
                self._contador += 1
                id_ = "%s-%03d" % (tipo, self._contador)
        if id_ in self.equipamentos:
            raise ValueError("Ja existe equipamento com ID '%s'." % id_)
        self._contador_ordem += 1
        if tipo in TIPOS_COM_LADOS and num_portas < 1:
            raise ValueError("Informe pelo menos 1 %s." % ("fibra" if tipo == TIPO_CABO
                                                           else "porta"))
        eq = Equipamento(id_, nome, tipo, num_portas, self._contador_ordem)
        if fibras_por_tubo:
            eq.fibras_por_tubo = max(1, min(int(fibras_por_tubo), 24))
        eq.pos_x, eq.pos_y = self._posicao_padrao(tipo)
        self.equipamentos[id_] = eq
        return eq

    def remover_equipamento(self, eq_id):
        if eq_id not in self.equipamentos:
            return
        for fid in [f.id for f in self.fusoes.values()
                    if f.eq_a == eq_id or f.eq_b == eq_id]:
            del self.fusoes[fid]
        del self.equipamentos[eq_id]
        self.reindexar()

    def remover_modulo(self, eq_id, modulo_id):
        if self.equipamentos[eq_id].tem_lados():
            raise ValueError("Os lados de um DIO/cabo nao podem ser removidos.")
        for fid in [f.id for f in self.fusoes.values()
                    if (f.eq_a == eq_id and f.modulo_a == modulo_id)
                    or (f.eq_b == eq_id and f.modulo_b == modulo_id)]:
            del self.fusoes[fid]
        self.equipamentos[eq_id].modulos.pop(modulo_id, None)
        self.reindexar()

    def definir_posicao(self, eq_id, x, y):
        eq = self.equipamentos[eq_id]
        eq.pos_x, eq.pos_y = x, y

    def girar_dio(self, eq_id):
        """DIO, OLT, switch ou RB: em pe (vertical) <-> deitado (horizontal)."""
        eq = self.equipamentos[eq_id]
        if not (eq.is_dio() or eq.tipo in TIPOS_ATIVOS):
            raise ValueError("So DIO, OLT, switch e RB podem ser girados.")
        eq.orientacao = "horizontal" if eq.orientacao == "vertical" else "vertical"
        return eq.orientacao

    def inverter_lado(self, eq_id):
        eq = self.equipamentos[eq_id]
        eq.lado = "esquerda" if eq.lado_efetivo() == "direita" else "direita"

    # ---------------- duplicar e criar em lote (v2.2) ----------------
    def duplicar_equipamento(self, eq_id, novo_nome=None):
        """Cria uma copia do equipamento com os mesmos modulos e portas
        (mesmos tipos, mesmas quantidades, mesmo GBIC). NAO copia as fusoes:
        a copia nasce toda livre, que e o que se quer ao repetir um padrao."""
        original = self.equipamentos[eq_id]
        nome = novo_nome or proximo_nome(original.nome,
                                         [e.nome for e in self.equipamentos.values()])
        copia = self.add_equipamento(nome, original.tipo,
                                     original.num_portas if original.tem_lados() else 0,
                                     fibras_por_tubo=original.fibras_por_tubo)
        copia.lado = original.lado
        copia.orientacao = original.orientacao
        for mod in ([] if original.tem_lados() else original.modulos.values()):
            if original.tipo == "OLT":
                copia.add_placa(mod.tipo, mod.nome)
            elif original.tipo == TIPO_ACOMODADOR:
                copia.add_splitter(mod.tipo, mod.nome)
            else:
                novo = copia.add_grupamento(mod.tipo, mod.num_portas, mod.nome)
                for numero, porta in mod.portas.items():
                    if numero in novo.portas:
                        novo.portas[numero].tipo_gbic = porta.tipo_gbic
        return copia

    def criar_em_lote(self, nome_base, tipo, quantidade, inicio=1,
                      num_portas=0, tipo_modulo=None, qtd_modulos=0, fibras_por_tubo=None):
        """Cria varios equipamentos iguais de uma vez, numerados.
        nome_base aceita um marcador de numeracao: use '#' (ex.: 'DIO-##'
        vira DIO-01, DIO-02...). Sem marcador, o numero vai no fim."""
        if quantidade < 1:
            raise ValueError("Informe uma quantidade de pelo menos 1.")
        if quantidade > 200:
            raise ValueError("Maximo de 200 equipamentos por vez.")
        criados = []
        for i in range(quantidade):
            nome = formatar_nome_numerado(nome_base, inicio + i)
            eq = self.add_equipamento(nome, tipo,
                                      num_portas if tipo in TIPOS_COM_LADOS else 0,
                                      fibras_por_tubo=fibras_por_tubo)
            for _ in range(qtd_modulos):
                if tipo == "OLT":
                    eq.add_placa(tipo_modulo or "GPON-16")
                elif tipo == TIPO_ACOMODADOR:
                    eq.add_splitter(tipo_modulo or "1x8")
                elif tipo in ("SWITCH", "RB"):
                    eq.add_grupamento(tipo_modulo or "SFP", num_portas or 24)
            criados.append(eq)
        return criados

    # ---------------- organizar o layout (v2.2) ----------------
    def organizar_layout(self):
        """Arruma as caixas em colunas - acomodadores | cabos | DIOs | ativos,
        o caminho do cliente ate a central - em ordem alfabetica e sem
        sobreposicao. Util depois de cadastrar muita coisa."""
        ordem = ["clientes", TIPO_ACOMODADOR, TIPO_CABO, TIPO_DIO, "ativos"]
        colunas = {c: [] for c in ordem}
        for eq in self.equipamentos.values():
            if eq.is_cabo() and self._cabo_de_cliente(eq):
                colunas["clientes"].append(eq)
            else:
                colunas[eq.tipo if eq.tipo in colunas else "ativos"].append(eq)
        movidos = 0
        x = 0.0
        for chave in ordem:
            lista = colunas[chave]
            if not lista:
                continue
            y = 0.0
            for eq in sorted(lista, key=lambda e: (e.nome or "").lower()):
                if (eq.pos_x, eq.pos_y) != (x, y):
                    movidos += 1
                eq.pos_x, eq.pos_y = x, y
                y += layout_equipamento(eq)["altura"] + self.altura_extra(eq) + self.GAP_Y
            x += max(layout_equipamento(e)["largura"] for e in lista) + self.GAP_COLUNA
        return movidos

    def altura_extra(self, eq):
        """Quanto a regua de conexao passa da caixa quando ha mais fibras
        ligadas num lado do que cabe na altura (DIO e ativos)."""
        if eq.is_cabo() or eq.tipo == TIPO_ACOMODADOR or eq.orientacao == "vertical":
            return 0.0
        if eq.is_dio():
            grupos = [[(eq.id, l, n) for n in range(1, eq.num_portas + 1)] for l in ("T", "F")]
        else:
            grupos = [self.todas_as_portas(eq)]
        ligadas = max([sum(1 for c in g if self._indice.get(c)) for g in grupos] or [0])
        disponivel = layout_equipamento(eq)["altura"] - ALT_TITULO - 10.0
        return max(0.0, (ligadas - 1) * ESPACO_MIN_CONEXAO - disponivel + 12.0)

    def _cabo_de_cliente(self, cabo):
        """Cabo de distribuicao/drop: sai das saidas de splitter e nao chega
        em DIO nenhum. Fica a esquerda da CTO, do lado dos clientes."""
        sai_de_splitter = chega_em_dio = False
        for lado, _ in LADOS[TIPO_CABO]:
            for n in range(1, cabo.num_portas + 1):
                for f in self._indice.get((cabo.id, lado, n), ()):
                    outro = f.outra_ponta(cabo.id, lado, n)
                    eq = self.equipamentos.get(outro[0])
                    if eq is None:
                        continue
                    if eq.is_dio():
                        chega_em_dio = True
                    elif eq.tipo == TIPO_ACOMODADOR and outro[2] != 1:
                        sai_de_splitter = True
        return sai_de_splitter and not chega_em_dio

    # ---------------- edicao ----------------
    def _portas_ocupadas_acima(self, eq_id, modulo_id, limite):
        eq = self.equipamentos[eq_id]
        if modulo_id is None and eq.tem_lados():
            return [n for n in range(limite + 1, eq.num_portas + 1)
                    if any(self._indice.get((eq_id, l, n)) for l, _ in LADOS[eq.tipo])]
        total = eq.modulos[modulo_id].num_portas
        return [n for n in range(limite + 1, total + 1)
                if self.fusoes_na_porta(eq_id, modulo_id, n)]

    def editar_equipamento(self, eq_id, novo_nome=None, novo_id=None, novo_num_portas=None):
        eq = self.equipamentos[eq_id]

        if novo_num_portas is not None and eq.tem_lados() and novo_num_portas != eq.num_portas:
            if novo_num_portas < 1:
                raise ValueError("O %s precisa de pelo menos 1 %s."
                                 % (eq.tipo, "fibra" if eq.is_cabo() else "porta"))
            travando = self._portas_ocupadas_acima(eq_id, None, novo_num_portas)
            if travando:
                raise ValueError(
                    "Nao e possivel reduzir para %d portas: a(s) porta(s) %s tem fusao. "
                    "Remova a(s) fusao(oes) antes."
                    % (novo_num_portas, ", ".join(map(str, travando))))
            eq.num_portas = novo_num_portas
            eq._montar_lados()

        if novo_id and novo_id != eq_id:
            if novo_id in self.equipamentos:
                raise ValueError("Ja existe um equipamento com ID '%s'." % novo_id)
            del self.equipamentos[eq_id]
            eq.id = novo_id
            self.equipamentos[novo_id] = eq
            for f in self.fusoes.values():
                if f.eq_a == eq_id:
                    f.eq_a = novo_id
                if f.eq_b == eq_id:
                    f.eq_b = novo_id
            self.reindexar()

        if novo_nome:
            eq.nome = novo_nome

    def editar_modulo(self, eq_id, modulo_id, novo_tipo=None, novo_num_portas=None,
                      novo_nome=None):
        """Edita nome, tipo e/ou quantidade de portas de um modulo. Reduzir a
        quantidade so e permitido se as portas removidas estiverem livres."""
        eq = self.equipamentos[eq_id]
        if eq.tem_lados():
            raise ValueError("Os lados de um DIO/cabo nao sao editaveis: mude a "
                             "quantidade de portas/fibras no proprio equipamento.")
        mod = eq.modulos[modulo_id]

        alvo_n = None
        alvo_gbic = mod.gbic_fixo
        if novo_tipo and novo_tipo != mod.tipo:
            if eq.tipo == "OLT":
                if novo_tipo not in TIPOS_PLACA_OLT:
                    raise ValueError("Tipo de placa invalido: %s" % novo_tipo)
                alvo_n = TIPOS_PLACA_OLT[novo_tipo]["portas"]
                alvo_gbic = TIPOS_PLACA_OLT[novo_tipo]["gbic_fixo"]
            elif eq.tipo == TIPO_ACOMODADOR:
                if novo_tipo not in TIPOS_SPLITTER:
                    raise ValueError("Tipo de splitter invalido: %s" % novo_tipo)
                alvo_n = 1 + TIPOS_SPLITTER[novo_tipo]
            else:
                if novo_tipo not in TIPOS_GRUPO_ATIVO:
                    raise ValueError("Tipo de grupamento invalido: %s" % novo_tipo)
        if novo_num_portas is not None and eq.tipo in ("SWITCH", "RB"):
            if novo_num_portas < 1:
                raise ValueError("O grupamento precisa de pelo menos 1 porta.")
            alvo_n = novo_num_portas

        if alvo_n is not None and alvo_n != mod.num_portas:
            travando = self._portas_ocupadas_acima(eq_id, modulo_id, alvo_n)
            if travando:
                raise ValueError(
                    "Nao e possivel ficar com %d portas: a(s) porta(s) %s tem fusao. "
                    "Remova a(s) fusao(oes) antes."
                    % (alvo_n, ", ".join(map(str, travando))))

        if alvo_gbic == SIMPLEX and mod.gbic_fixo != SIMPLEX:
            com_duas = [n for n in mod.portas
                        if len(self.fusoes_na_porta(eq_id, modulo_id, n)) > 1]
            if com_duas:
                raise ValueError(
                    "Nao e possivel travar em SIMPLEX: a(s) porta(s) %s tem 2 fusoes. "
                    "Remova uma de cada antes." % ", ".join(map(str, com_duas)))

        if alvo_n is not None and alvo_n != mod.num_portas:
            antigas = mod.portas
            mod.portas = {i: antigas.get(i) or Porta(i, alvo_gbic or SIMPLEX)
                          for i in range(1, alvo_n + 1)}
        if novo_tipo:
            mod.tipo = novo_tipo
        if alvo_gbic:
            mod.gbic_fixo = alvo_gbic
            for p in mod.portas.values():
                p.tipo_gbic = alvo_gbic
        if novo_nome:
            mod.nome = novo_nome
        mudou_tipo = bool(novo_tipo) and (eq.tipo == "OLT" or eq.tipo in ("SWITCH", "RB"))
        mod.completar_conectores(eq.tipo, forcar=mudou_tipo and alvo_n is not None)

    # ---------------- portas ----------------
    def _valida_ponta(self, eq_id, modulo_id, porta_num):
        if eq_id not in self.equipamentos:
            raise ValueError("Equipamento '%s' nao encontrado." % eq_id)
        eq = self.equipamentos[eq_id]
        if eq.tem_lados() and modulo_id in eq.modulos and \
                not 1 <= porta_num <= eq.num_portas:
            raise ValueError("%s %d fora do intervalo de '%s' (1-%d)."
                             % ("Fibra" if eq.is_cabo() else "Porta", porta_num,
                                eq.nome, eq.num_portas))
        else:
            if modulo_id not in eq.modulos:
                raise ValueError("Modulo nao encontrado em '%s'." % eq.nome)
            if porta_num not in eq.modulos[modulo_id].portas:
                raise ValueError("Porta %d nao existe em '%s'."
                                 % (porta_num, eq.modulos[modulo_id].nome))

    def limite_porta(self, eq_id, modulo_id, porta_num):
        eq = self.equipamentos[eq_id]
        modulo_id = self.lado_padrao(eq_id, modulo_id)
        return eq.modulos[modulo_id].portas[porta_num].limite()

    def tipo_gbic_porta(self, eq_id, modulo_id, porta_num):
        eq = self.equipamentos[eq_id]
        if eq.is_cabo():
            return None
        modulo_id = self.lado_padrao(eq_id, modulo_id)
        return eq.modulos[modulo_id].portas[porta_num].tipo_gbic

    def _porta_do_conector(self, eq_id, modulo_id, porta_num):
        """A Porta que guarda o conector: no DIO e sempre a da frente (a
        traseira e a fusao da mesma posicao)."""
        eq = self.equipamentos[eq_id]
        if eq.is_dio():
            return eq.modulos["F"].portas[porta_num]
        return eq.modulos[self.lado_padrao(eq_id, modulo_id)].portas[porta_num]

    def conector_da_porta(self, eq_id, modulo_id, porta_num):
        """(conector, polimento) - (None, None) na fusao (traseira do DIO,
        fibra de cabo)."""
        eq = self.equipamentos.get(eq_id)
        modulo_id = self.lado_padrao(eq_id, modulo_id)
        if eq is None or eq.is_cabo() or (eq.is_dio() and modulo_id == "T"):
            return None, None
        porta = self._porta_do_conector(eq_id, modulo_id, porta_num)
        return porta.conector, porta.polimento

    def definir_conector(self, eq_id, modulo_id, porta_num, conector=None, polimento=None):
        eq = self.equipamentos[eq_id]
        if eq.is_cabo():
            raise ValueError("Fibra de cabo e fundida: nao tem conector.")
        porta = self._porta_do_conector(eq_id, modulo_id, porta_num)
        if conector is not None:
            if conector not in CONECTORES:
                raise ValueError("Conector invalido: %s (use SC ou LC)." % conector)
            if conector == "SC" and porta.tipo_gbic == DUPLEX:
                raise ValueError("Porta duplex e sempre LC. Passe a porta pra simplex "
                                 "antes de trocar pra SC.")
            porta.conector = conector
        if polimento is not None:
            if polimento not in POLIMENTOS:
                raise ValueError("Polimento invalido: %s (use APC ou UPC)." % polimento)
            porta.polimento = polimento

    def definir_conector_em_lote(self, eq_id, modulo_id, conector=None, polimento=None):
        """Mesmo conector em todas as portas do modulo (ou do DIO inteiro).
        Porta duplex continua LC. Devolve quantas portas mudaram."""
        eq = self.equipamentos[eq_id]
        if eq.is_cabo():
            raise ValueError("Fibra de cabo e fundida: nao tem conector.")
        if eq.is_dio():
            modulo_id = "F"
        mudou = 0
        for n, porta in eq.modulos[modulo_id].portas.items():
            antes = (porta.conector, porta.polimento)
            self.definir_conector(eq_id, modulo_id, n,
                                  None if (conector == "SC" and porta.tipo_gbic == DUPLEX)
                                  else conector, polimento)
            mudou += antes != (porta.conector, porta.polimento)
        return mudou

    def potencia_da_porta(self, eq_id, modulo_id, porta_num):
        eq = self.equipamentos.get(eq_id)
        if eq is None or eq.tipo not in TIPOS_ATIVOS:
            return None
        mod = eq.modulos.get(modulo_id)
        porta = mod.portas.get(porta_num) if mod else None
        return porta.potencia if porta else None

    def definir_potencia(self, eq_id, modulo_id, porta_num, dbm):
        """Potencia de saida (dBm) de uma porta de OLT/ativo; None tira."""
        eq = self.equipamentos[eq_id]
        if eq.tipo not in TIPOS_ATIVOS:
            raise ValueError("So porta de OLT, switch ou RB tem potencia de saida.")
        if dbm is not None:
            dbm = float(dbm)
            if not -40.0 <= dbm <= 30.0:
                raise ValueError("Potencia fora da faixa: use de -40 a +30 dBm.")
        eq.modulos[modulo_id].portas[porta_num].potencia = dbm

    def definir_potencia_em_lote(self, eq_id, modulo_id, dbm):
        for n in self.equipamentos[eq_id].modulos[modulo_id].portas:
            self.definir_potencia(eq_id, modulo_id, n, dbm)

    def definir_tipo_porta(self, eq_id, modulo_id, porta_num, tipo_gbic):
        eq = self.equipamentos[eq_id]
        if eq.is_cabo():
            raise ValueError("Fibra de cabo nao tem GBIC nem adaptador duplex.")
        if eq.is_dio():
            # adaptador duplex vale pra posicao inteira: traseira e frente
            if tipo_gbic == SIMPLEX:
                for lado in ("T", "F"):
                    if len(self.fusoes_na_porta(eq_id, lado, porta_num)) > 1:
                        raise ValueError("A porta %d ja tem 2 fibras na %s. Remova uma "
                                         "antes de voltar pra simplex."
                                         % (porta_num, "traseira" if lado == "T" else "frente"))
            for lado in ("T", "F"):
                eq.modulos[lado].portas[porta_num].tipo_gbic = tipo_gbic
            if tipo_gbic == DUPLEX:
                eq.modulos["F"].portas[porta_num].conector = "LC"
            return
        mod = eq.modulos[modulo_id]
        if mod.gbic_fixo and tipo_gbic != mod.gbic_fixo:
            raise ValueError("O modulo '%s' so aceita portas %s (GBIC travado)."
                             % (mod.nome, mod.gbic_fixo))
        if tipo_gbic == SIMPLEX and len(self.fusoes_na_porta(eq_id, modulo_id, porta_num)) > 1:
            raise ValueError("A porta ja tem 2 fusoes. Remova uma antes de voltar "
                             "para SIMPLEX.")
        mod.portas[porta_num].tipo_gbic = tipo_gbic
        if tipo_gbic == DUPLEX and mod.portas[porta_num].conector:
            mod.portas[porta_num].conector = "LC"      # duplex e sempre LC

    def rotulo_porta(self, eq_id, modulo_id, porta_num):
        """Nome curto da porta: ENT/S1/S2... num splitter; na OLT a contagem
        comeca em 0, como no equipamento (0-15); no resto, o numero."""
        eq = self.equipamentos.get(eq_id)
        if eq is None or eq.tem_lados():
            return str(porta_num)
        mod = eq.modulos.get(modulo_id)
        if mod is not None and mod.eh_splitter():
            return "ENT" if porta_num == 1 else "S%d" % (porta_num - 1)
        if eq.tipo == "OLT":
            return str(porta_num - 1)
        return str(porta_num)

    def nome_porta(self, eq_id, modulo_id, porta_num):
        eq = self.equipamentos.get(eq_id)
        if eq is None:
            return "%s:%s" % (eq_id, porta_num)
        modulo_id = self.lado_padrao(eq_id, modulo_id)
        if eq.is_dio():
            return "%s porta %s (%s)" % (eq.nome, porta_num,
                                         "traseira" if modulo_id == "T" else "frente")
        if eq.is_cabo():
            return "%s fibra %s (%s) ponta %s" % (eq.nome, porta_num,
                                                  cor_fibra(porta_num, eq.fibras_por_tubo)[0],
                                                  modulo_id)
        mod = eq.modulos.get(modulo_id)
        return "%s / %s porta %s" % (eq.nome, mod.nome if mod else modulo_id,
                                     self.rotulo_porta(eq_id, modulo_id, porta_num))

    def porta_status(self, eq_id, modulo_id, porta_num):
        modulo_id = self.lado_padrao(eq_id, modulo_id)
        n = len(self.fusoes_na_porta(eq_id, modulo_id, porta_num))
        if n == 0:
            return "livre"
        return "parcial" if n < self.limite_porta(eq_id, modulo_id, porta_num) else "completa"

    def todas_as_portas(self, eq=None):
        """Lista (eq_id, modulo_id, numero) de todas as portas - de um
        equipamento, ou da rede inteira."""
        equipamentos = [eq] if eq is not None else list(self.equipamentos.values())
        saida = []
        for e in equipamentos:
            for m in e.modulos.values():
                saida += [(e.id, m.id, n) for n in sorted(m.portas)]
        return saida

    # ---------------- fusoes ----------------
    def criar_fusao(self, eq_a, modulo_a, porta_a, eq_b, modulo_b, porta_b, rotulo=""):
        modulo_a = self.lado_padrao(eq_a, modulo_a)
        modulo_b = self.lado_padrao(eq_b, modulo_b)
        self._valida_ponta(eq_a, modulo_a, porta_a)
        self._valida_ponta(eq_b, modulo_b, porta_b)
        if (eq_a, modulo_a, porta_a) == (eq_b, modulo_b, porta_b):
            raise ValueError("Nao e possivel conectar uma porta a ela mesma.")
        for eq_id, mod_id, num in ((eq_a, modulo_a, porta_a), (eq_b, modulo_b, porta_b)):
            usadas = len(self.fusoes_na_porta(eq_id, mod_id, num))
            limite = self.limite_porta(eq_id, mod_id, num)
            if usadas >= limite:
                raise ValueError("A porta %s ja atingiu o limite de %d fusao(oes)."
                                 % (self.nome_porta(eq_id, mod_id, num), limite))
        self._contador_fusao += 1
        f = Fusao("FUS-%04d" % self._contador_fusao, eq_a, modulo_a, porta_a,
                  eq_b, modulo_b, porta_b, rotulo)
        self.fusoes[f.id] = f
        for ponta in f.pontas():
            self._indice.setdefault(ponta, []).append(f)
        return f

    def remover_fusao(self, fusao_id):
        if self.fusoes.pop(fusao_id, None) is not None:
            self.reindexar()

    # ---------------- persistencia ----------------
    def to_dict(self):
        return {"versao": VERSAO,
                "local": dict(self.local),
                "equipamentos": [e.to_dict() for e in self.equipamentos.values()],
                "fusoes": [f.to_dict() for f in self.fusoes.values()],
                "_contador": self._contador,
                "_contador_fusao": self._contador_fusao,
                "_contador_ordem": self._contador_ordem}

    @staticmethod
    def from_dict(d):
        r = Rede()
        r.local = mapa.normalizar_local(d.get("local"))
        for ed in d.get("equipamentos", []):
            eq = Equipamento.from_dict(ed)
            r.equipamentos[eq.id] = eq
        for fd in d.get("fusoes", []):
            f = Fusao.from_dict(fd)
            # redes antigas: porta de DIO sem lado -> frente (conector)
            f.modulo_a = r.lado_padrao(f.eq_a, f.modulo_a)
            f.modulo_b = r.lado_padrao(f.eq_b, f.modulo_b)
            r.fusoes[f.id] = f
        r._contador = d.get("_contador", len(r.equipamentos))
        r._contador_fusao = d.get("_contador_fusao", len(r.fusoes))
        r._contador_ordem = d.get("_contador_ordem",
                                  max([e.ordem for e in r.equipamentos.values()], default=0))
        r.reindexar()
        if _versao_num(d.get("versao")) < (0, 28):
            # ate a B0.27 so o DIO girava: os outros voltam pro padrao
            for eq in r.equipamentos.values():
                if not eq.is_dio():
                    eq.orientacao = orientacao_padrao(eq.tipo)
        if _versao_num(d.get("versao")) < (0, 28):
            # B0.27: DIO agora fica em pe (vertical) por padrao
            # as caixas mudaram de tamanho (desenho real): rearruma pra nao
            # ficarem umas por cima das outras
            r.organizar_layout()
        return r

    def salvar(self, caminho):
        with open(caminho, "w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, ensure_ascii=False, indent=2)

    @staticmethod
    def carregar(caminho):
        with open(caminho, "r", encoding="utf-8") as fp:
            return Rede.from_dict(json.load(fp))


def _versao_num(versao):
    """'B0.25' -> (0, 25). Versoes antigas (2.x, sem versao) -> (-1, 0)."""
    achado = re.match(r"B(\d+)\.(\d+)", str(versao or ""))
    return (int(achado.group(1)), int(achado.group(2))) if achado else (-1, 0)


# ---------------------------------------------------------------- nomes
def formatar_nome_numerado(base, numero):
    """'DIO-##' + 7 -> 'DIO-07'. Sem '#', o numero entra no fim: 'DIO' -> 'DIO 7'."""
    base = (base or "").strip() or "Equipamento"
    marcador = re.search(r"#+", base)
    if marcador:
        largura = len(marcador.group(0))
        return base[:marcador.start()] + str(numero).zfill(largura) + base[marcador.end():]
    return "%s %d" % (base, numero)


def proximo_nome(nome, existentes):
    """Sugere um nome livre pra uma copia: 'DIO-01' -> 'DIO-02';
    'CTO Centro' -> 'CTO Centro (2)'."""
    existentes = set(existentes or ())
    numero_final = re.search(r"(\d+)(\D*)$", nome or "")
    candidatos = []
    if numero_final:
        largura = len(numero_final.group(1))
        valor = int(numero_final.group(1))
        for passo in range(1, 500):
            novo = (nome[:numero_final.start(1)] + str(valor + passo).zfill(largura)
                    + numero_final.group(2))
            candidatos.append(novo)
    else:
        candidatos = ["%s (%d)" % (nome, i) for i in range(2, 500)]
    for candidato in candidatos:
        if candidato not in existentes:
            return candidato
    return "%s (copia)" % nome


def sem_acento(texto):
    """Pra busca: 'Jardim Paulista' casa com 'paulista', com ou sem acento."""
    normalizado = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


# ============================================================================
#  BUSCA (v2.2)
# ============================================================================

def buscar(rede, termo, limite=200):
    """Procura o texto em equipamentos, modulos, portas e rotulos de fusao.
    Devolve uma lista de achados: {tipo, titulo, detalhe, chave, eq_id}.
    'chave' e a porta (eq, modulo, numero) quando o achado aponta pra uma
    porta - e o que o diagrama usa pra centralizar e destacar."""
    alvo = sem_acento(termo).strip()
    if not alvo:
        return []
    achados = []

    for eq in sorted(rede.equipamentos.values(), key=lambda e: (e.nome or "").lower()):
        if alvo in sem_acento(eq.nome) or alvo in sem_acento(eq.id):
            usadas, total = rede.ocupacao(eq)
            achados.append({"tipo": "equipamento", "titulo": eq.nome,
                            "detalhe": "%s - %d/%d %s em uso"
                                       % (eq.tipo, usadas, total,
                                          "fibras" if eq.is_cabo() else "portas"),
                            "chave": None, "eq_id": eq.id})
        for mod in ([] if eq.tem_lados() else eq.modulos.values()):
            if alvo in sem_acento(mod.nome):
                achados.append({"tipo": "modulo", "titulo": mod.nome,
                                "detalhe": "%s - %d portas" % (eq.nome, mod.num_portas),
                                "chave": (eq.id, mod.id, min(mod.portas) if mod.portas else 1),
                                "eq_id": eq.id})

    for f in sorted(rede.fusoes.values(), key=lambda x: x.id):
        if alvo in sem_acento(f.rotulo):
            a, b = f.pontas()
            achados.append({"tipo": "fusao", "titulo": f.rotulo or f.id,
                            "detalhe": "%s  <->  %s" % (rede.nome_porta(*a),
                                                        rede.nome_porta(*b)),
                            "chave": a, "eq_id": a[0]})

    # "DIO Centro 15" ou so "15": tambem procura numero de porta
    numero = re.search(r"(\d+)\s*$", alvo)
    if numero:
        procurado = int(numero.group(1))
        prefixo = alvo[:numero.start()].strip()
        for eq in rede.equipamentos.values():
            if prefixo and prefixo not in sem_acento(eq.nome):
                continue
            for chave in rede.todas_as_portas(eq):
                # compara com o numero que aparece na tela (OLT conta de 0,
                # splitter tem S1, S2...)
                rotulo = rede.rotulo_porta(*chave)
                if rotulo != str(procurado) and rotulo != "S%d" % procurado:
                    continue
                achados.append({"tipo": "porta", "titulo": rede.nome_porta(*chave),
                                "detalhe": "porta %s" % rede.porta_status(*chave),
                                "chave": chave, "eq_id": eq.id})
                if len(achados) >= limite:
                    break

    # tira repetidos mantendo a ordem
    vistos, unicos = set(), []
    for achado in achados:
        assinatura = (achado["tipo"], achado["titulo"], achado["detalhe"])
        if assinatura in vistos:
            continue
        vistos.add(assinatura)
        unicos.append(achado)
    return unicos[:limite]


# ============================================================================
#  PENDENCIAS: o que esta faltando ou inconsistente na documentacao (v2.2)
# ============================================================================

def pendencias(rede):
    """Lista o que merece atencao na rede documentada. Cada item:
    {gravidade, tipo, item, detalhe, chave}. gravidade: 'erro' | 'aviso' | 'info'."""
    itens = []

    # 1. nomes repetidos: confundem relatorio e diagrama
    por_nome = {}
    for eq in rede.equipamentos.values():
        por_nome.setdefault(sem_acento(eq.nome), []).append(eq)
    for lista in por_nome.values():
        if len(lista) > 1:
            itens.append({"gravidade": "aviso", "tipo": "Nome repetido",
                          "item": lista[0].nome,
                          "detalhe": "%d equipamentos com o mesmo nome (ids: %s)"
                                     % (len(lista), ", ".join(e.id for e in lista)),
                          "chave": None})

    for eq in sorted(rede.equipamentos.values(), key=lambda e: (e.nome or "").lower()):
        portas = rede.todas_as_portas(eq)
        usadas, total = rede.ocupacao(eq)
        unidade = "fibras" if eq.is_cabo() else "portas"

        # 2. equipamento sem nenhuma fusao: cadastrado e esquecido
        if total and not usadas:
            itens.append({"gravidade": "aviso", "tipo": "Sem conexao",
                          "item": eq.nome,
                          "detalhe": "%s com %d %s e nenhuma fusao cadastrada"
                                     % (eq.tipo, total, unidade),
                          "chave": portas[0]})

        # 3. equipamento lotado: nao cabe mais cliente
        if total and usadas == total:
            itens.append({"gravidade": "info", "tipo": "Lotado",
                          "item": eq.nome,
                          "detalhe": "todas as %d %s estao em uso" % (total, unidade),
                          "chave": portas[0]})

        for mod in eq.modulos.values():
            # 4. splitter sem alimentacao: as saidas nao levam sinal nenhum
            if mod.eh_splitter():
                entrada = (eq.id, mod.id, 1)
                saidas_usadas = [n for n in mod.portas
                                 if n != 1 and rede.fusoes_na_porta(eq.id, mod.id, n)]
                if not rede.fusoes_na_porta(*entrada):
                    gravidade = "erro" if saidas_usadas else "aviso"
                    itens.append({"gravidade": gravidade, "tipo": "Splitter sem entrada",
                                  "item": "%s / %s" % (eq.nome, mod.nome),
                                  "detalhe": ("a ENT nao esta fundida"
                                              + (" e ja tem %d saida(s) ligada(s)"
                                                 % len(saidas_usadas) if saidas_usadas
                                                 else "")),
                                  "chave": entrada})

            # 5. porta duplex com so uma fibra: TX sem RX (ou o contrario)
            for numero, porta in mod.portas.items():
                if porta.tipo_gbic != DUPLEX:
                    continue
                qtd = len(rede.fusoes_na_porta(eq.id, mod.id, numero))
                if qtd == 1:
                    itens.append({"gravidade": "erro", "tipo": "Duplex pela metade",
                                  "item": rede.nome_porta(eq.id, mod.id, numero),
                                  "detalhe": "porta duplex com 1 fibra ligada de 2",
                                  "chave": (eq.id, mod.id, numero)})

    # 6. fusao sem rotulo: dificulta achar o cliente depois
    # (fusao de fibra de cabo e de bandeja do DIO dispensa rotulo: a fibra
    # ja e identificada pelo numero e pela cor)
    def _de_bandeja(f):
        for eq_id, mod_id, _ in f.pontas():
            eq = rede.equipamentos.get(eq_id)
            if eq is not None and (eq.is_cabo() or (eq.is_dio() and mod_id == "T")):
                return True
        return False
    sem_rotulo = [f for f in rede.fusoes.values()
                  if not (f.rotulo or "").strip() and not _de_bandeja(f)]
    if sem_rotulo:
        itens.append({"gravidade": "info", "tipo": "Fusao sem rotulo",
                      "item": "%d fusao(oes)" % len(sem_rotulo),
                      "detalhe": "sem rotulo fica dificil achar o cliente na busca "
                                 "(ex.: %s)" % ", ".join(f.id for f in sem_rotulo[:5]),
                      "chave": sem_rotulo[0].pontas()[0]})

    ordem = {"erro": 0, "aviso": 1, "info": 2}
    itens.sort(key=lambda x: (ordem.get(x["gravidade"], 9), x["tipo"], x["item"]))
    return itens


def resumo_capacidade(rede):
    """Quantas portas livres existem, por equipamento - a pergunta que mais
    aparece no dia a dia ('onde ainda cabe cliente?')."""
    linhas = []
    for eq in sorted(rede.equipamentos.values(), key=lambda e: (e.nome or "").lower()):
        usadas, total = rede.ocupacao(eq)
        if not total:
            continue
        linhas.append({"equipamento": eq.nome, "tipo": eq.tipo,
                       "total": total, "usadas": usadas,
                       "livres": total - usadas,
                       "ocupacao": round(usadas * 100.0 / total, 1)})
    return linhas


# ============================================================================
#  RASTREIO DO CAMINHO DA FIBRA (por onde o sinal passa e quanto perde)
# ============================================================================

# Perdas de referencia de mercado (arredondadas). Se a sua operadora usa
# valores medidos (OTDR), e so trocar aqui.
PERDA_FUSAO_DB = 0.1
PERDA_CONECTOR_DB = 0.5          # par de conectores no adaptador do DIO
PERDA_SPLITTER_DB = {"1x2": 3.5, "1x4": 7.2, "1x8": 10.5, "1x16": 13.7}
SENSIBILIDADE_ONU_DBM = -28.0    # abaixo disso: critico (tipico GPON)
LIMIAR_ALERTA_DBM = -25.0        # entre o limiar e a sensibilidade: alerta

MAX_NOS_RASTREIO = 600           # trava de seguranca contra redes gigantes
MAX_PROFUNDIDADE_RASTREIO = 14


def classificar_potencia(dbm):
    if dbm is None:
        return None
    if dbm < SENSIBILIDADE_ONU_DBM:
        return "critico"
    if dbm < LIMIAR_ALERTA_DBM:
        return "alerta"
    return "ok"


def _saltos_da_porta(rede, chave, via_entrada=None, chegou_por=None, so_fusao=None):
    """Por onde o sinal pode seguir a partir de uma porta. Dois tipos de
    salto: pela FUSAO (vai pra porta da outra ponta) e por DENTRO de um
    splitter (a entrada alimenta as saidas, e cada saida chega na entrada).

    via_entrada diz como chegamos nesta porta, pra respeitar o sentido do
    sinal: se chegamos na ENTRADA vindo de uma saida (subindo em direcao a
    OLT), o sinal NAO volta a descer pelas outras saidas - um splitter
    combina nesse sentido, nao distribui."""
    eq_id, mod_id, num = chave
    saltos = []
    for f in rede.fusoes_na_porta(*chave):
        if so_fusao is not None and f.id != so_fusao:
            continue                 # adaptador duplex: segue so a fibra par
        if via_entrada == "fusao":
            # chegou por uma fibra: numa porta duplex a outra fibra e outro
            # caminho (TX x RX) - o sinal nao pula de uma pra outra
            continue
        saltos.append({"destino": f.outra_ponta(*chave), "via": "fusao",
                       "perda": PERDA_FUSAO_DB, "rotulo": f.rotulo,
                       "fusao_id": f.id})
    eq = rede.equipamentos.get(eq_id)
    if eq is not None and eq.tem_lados():
        # passagem: no DIO o sinal atravessa o adaptador (traseira <-> frente);
        # no cabo, a fibra leva de uma ponta a outra
        for outro, _nome in LADOS[eq.tipo]:
            if outro == mod_id:
                continue
            if eq.is_dio():
                # adaptador duplex: a 1a fibra de tras casa com a 1a da frente
                # e a 2a com a 2a - o TX nao "vaza" pro RX
                par = None
                if rede.tipo_gbic_porta(eq_id, mod_id, num) == DUPLEX and chegou_por:
                    daqui = [f.id for f in sorted(rede.fusoes_na_porta(*chave),
                                                  key=lambda x: x.id)]
                    de_la = [f.id for f in sorted(rede.fusoes_na_porta(eq_id, outro, num),
                                                  key=lambda x: x.id)]
                    if chegou_por in daqui:
                        k = daqui.index(chegou_por)
                        par = de_la[k] if k < len(de_la) else "-"
                c, p = rede.conector_da_porta(eq_id, "F", num)
                saltos.append({"destino": (eq_id, outro, num), "via": "dio",
                               "perda": PERDA_CONECTOR_DB,
                               "rotulo": "conector %s" % texto_conector(c, p) if c else "conector",
                               "fusao_id": None, "so_fusao": par})
            else:
                saltos.append({"destino": (eq_id, outro, num), "via": "cabo",
                               "perda": 0.0, "rotulo": "fibra %d %s"
                               % (num, cor_fibra(num, eq.fibras_por_tubo)[0]),
                               "fusao_id": None})
    elif eq is not None:
        mod = eq.modulos.get(mod_id)
        if mod is not None and mod.eh_splitter():
            perda = PERDA_SPLITTER_DB.get(mod.tipo, 0.0)
            if num == 1:                       # entrada -> todas as saidas
                if via_entrada != "splitter":  # so quando o sinal esta descendo
                    for outra in sorted(mod.portas):
                        if outra != 1:
                            saltos.append({"destino": (eq_id, mod_id, outra),
                                           "via": "splitter", "perda": perda,
                                           "rotulo": mod.tipo, "fusao_id": None})
            else:                              # saida -> sobe pra entrada
                saltos.append({"destino": (eq_id, mod_id, 1), "via": "splitter",
                               "perda": perda, "rotulo": mod.tipo, "fusao_id": None})
    return saltos


def rastrear_caminho(rede, chave, potencia_dbm=5.0):
    """Percorre a rede a partir de uma porta e devolve a arvore do caminho.
    Cada no: {chave, nome, via, rotulo, perda, perda_acum, potencia, filhos}.
    Nao inclui atenuacao de cabo (este programa nao guarda a metragem da
    rota - isso fica no cadastro de cabos/mapa)."""
    contador = {"nos": 1}

    def novo_no(chave_no, via, rotulo, perda, perda_acum):
        return {"chave": chave_no, "nome": rede.nome_porta(*chave_no), "via": via,
                "rotulo": rotulo or "", "perda": perda, "perda_acum": perda_acum,
                "potencia": None if potencia_dbm is None else potencia_dbm - perda_acum,
                "filhos": [], "truncado": False, "fusao_id": None}

    raiz = novo_no(chave, "inicio", "", 0.0, 0.0)

    def expandir(no, visitados, profundidade):
        if profundidade >= MAX_PROFUNDIDADE_RASTREIO or contador["nos"] >= MAX_NOS_RASTREIO:
            no["truncado"] = True
            return
        for salto in _saltos_da_porta(rede, no["chave"], no["via"], no.get("fusao_id"),
                                      no.get("so_fusao")):
            destino = salto["destino"]
            if destino in visitados:
                continue
            if contador["nos"] >= MAX_NOS_RASTREIO:
                no["truncado"] = True
                return
            contador["nos"] += 1
            filho = novo_no(destino, salto["via"], salto["rotulo"], salto["perda"],
                            no["perda_acum"] + salto["perda"])
            filho["fusao_id"] = salto["fusao_id"]
            filho["so_fusao"] = salto.get("so_fusao")
            no["filhos"].append(filho)
            expandir(filho, visitados | {destino}, profundidade + 1)

    expandir(raiz, {chave}, 0)
    return raiz


def calcular_potencias(rede):
    """Pra cada porta de OLT com potencia informada, percorre o caminho e
    anota a potencia que chega em cada porta e em cada fibra. Se dois
    caminhos chegam no mesmo ponto, vale o mais forte.
    Devolve {"portas": {chave: dBm}, "fusoes": {id: dBm}, "fontes": {chave: dBm}}."""
    portas, fusoes, fontes = {}, {}, {}
    for eq in rede.equipamentos.values():
        if eq.tipo not in TIPOS_ATIVOS:
            continue
        for mod in eq.modulos.values():
            for n, porta in mod.portas.items():
                if porta.potencia is None:
                    continue
                chave = (eq.id, mod.id, n)
                fontes[chave] = porta.potencia
                pilha = [rastrear_caminho(rede, chave, porta.potencia)]
                while pilha:
                    no = pilha.pop()
                    dbm = no["potencia"]
                    if dbm is not None:
                        if dbm > portas.get(no["chave"], -999.0):
                            portas[no["chave"]] = dbm
                        fid = no.get("fusao_id")
                        if fid and dbm > fusoes.get(fid, -999.0):
                            fusoes[fid] = dbm
                    pilha.extend(no["filhos"])
    return {"portas": portas, "fusoes": fusoes, "fontes": fontes}


def formatar_dbm(dbm):
    """-6.4 -> '-6,4 dBm' (virgula, como se escreve aqui)."""
    return ("%+.1f dBm" % dbm).replace(".", ",")


def pontas_finais(no, acumulado=None):
    """Lista as pontas onde o caminho termina (as folhas da arvore)."""
    acumulado = [] if acumulado is None else acumulado
    if not no["filhos"]:
        acumulado.append(no)
    else:
        for filho in no["filhos"]:
            pontas_finais(filho, acumulado)
    return acumulado


def fusoes_do_rastreio(no, acumulado=None):
    """Ids das fusoes usadas no caminho - serve pra destacar no diagrama."""
    acumulado = set() if acumulado is None else acumulado
    if no.get("fusao_id"):
        acumulado.add(no["fusao_id"])
    for filho in no["filhos"]:
        fusoes_do_rastreio(filho, acumulado)
    return acumulado


def rastreio_em_texto(no, nivel=0, linhas=None, mostrar_potencia=True):
    """Formata a arvore do rastreio como texto identado."""
    linhas = [] if linhas is None else linhas
    prefixo = "   " * nivel + ("" if nivel == 0 else "|- ")
    via = {"inicio": "", "fusao": "fusao", "splitter": "splitter",
           "dio": "atravessa o DIO", "cabo": "pelo cabo"}.get(no["via"], no["via"])
    detalhe = []
    if via:
        detalhe.append(via)
    if no["rotulo"]:
        detalhe.append(no["rotulo"])
    if no["perda"]:
        detalhe.append("-%.2f dB" % no["perda"])
    texto = prefixo + no["nome"]
    if detalhe:
        texto += "   (" + ", ".join(detalhe) + ")"
    if mostrar_potencia and no["potencia"] is not None:
        texto += "   => %.2f dBm" % no["potencia"]
    elif no["perda_acum"]:
        texto += "   => perda total %.2f dB" % no["perda_acum"]
    linhas.append(texto)
    if no["truncado"]:
        linhas.append("   " * (nivel + 1) + "|- (rastreio interrompido: caminho muito longo)")
    for filho in no["filhos"]:
        rastreio_em_texto(filho, nivel + 1, linhas, mostrar_potencia)
    return linhas


# ============================================================================
#  TEMA VISUAL (a mesma paleta vale pra tela, pro SVG e pro PDF)
# ============================================================================

TEMA_GRAFITE = {
    "nome": "Grafite",
    "escuro": True,
    "fundo": "#0e1115",
    "caixa_fundo": "#191e24", "caixa_borda": "#2b333c", "caixa_lw": 1.0,
    "titulo_cor": "#eef1f4", "titulo_tam": 10.5, "titulo_regua": "#2b333c",
    "tipo_cor": "#76838f", "tipo_tam": 6.8,
    "modulo_fundo": "#1e242b", "modulo_cor": "#8b98a4", "modulo_regua": "#2b333c",
    "porta_cor": "#b0bac2", "porta_tam": 7.8, "zebra": "#161a20",
    "livre": "#39424a", "uso": "#53c08d", "parcial": "#d9a441",
    "fibra": "#64727c", "duplex1": "#e08a4c", "duplex2": "#6aa9e0",
    "rotulo_cor": "#8b98a2",
    "destaque": "#4dd0e1", "halo": "#1f3b42", "selecao": "#4dd0e1",
    "cabecalho_cor": "#eef1f4",
    # equipamentos "de verdade" (B0.25)
    "chassi": "#1f252c", "chassi_borda": "#323b45", "chassi_titulo": "#191e24",
    "bandeja": "#161b20", "adaptador": "#2a3138", "adaptador_borda": "#4a545e",
    "slot": "#0d1115", "vazio": "#3a424a", "led_off": "#2f363d", "numero": "#7fb3ff",
    "sfp": "#4dd0e1", "fusao_ok": "#d7dde2", "cordao": "#e0b300", "ferrolho": "#8a949c",
    # polimento do conector, nas cores de mercado: APC verde, UPC azul
    "apc": "#3fbf6a", "upc": "#4a8fe7",
    # cores da janela (tkinter)
    "ui_fundo": "#161a1f", "ui_painel": "#1e242b", "ui_borda": "#2a323b",
    "ui_texto": "#eef1f4", "ui_texto_fraco": "#8b98a4", "ui_acento": "#4dd0e1",
    "ui_acento_texto": "#0b2529", "ui_campo": "#11151a", "ui_hover": "#262e37",
    "ui_profundo": "#0e1115",
    "ui_erro": "#e5736a", "ui_aviso": "#d9a441", "ui_ok": "#53c08d",
}

TEMA_LINHO = {
    "nome": "Linho",
    "escuro": False,
    "fundo": "#faf9f7",
    "caixa_fundo": "#ffffff", "caixa_borda": "#e4e0d9", "caixa_lw": 1.0,
    "titulo_cor": "#1c1b19", "titulo_tam": 10.5, "titulo_regua": "#ded9d1",
    "tipo_cor": "#a39b8e", "tipo_tam": 6.8,
    "modulo_fundo": None, "modulo_cor": "#8d857a", "modulo_regua": "#eceae5",
    "porta_cor": "#5d574f", "porta_tam": 7.8, "zebra": None,
    "livre": "#d9d4cc", "uso": "#2f6f5e", "parcial": "#b98b2e",
    "fibra": "#9a9287", "duplex1": "#b06c3a", "duplex2": "#5a7f9c",
    "rotulo_cor": "#8d857a",
    "destaque": "#2f6f5e", "halo": "#dbe8e2", "selecao": "#2f6f5e",
    "cabecalho_cor": "#1c1b19",
    "chassi": "#f3f1ed", "chassi_borda": "#d9d4cc", "chassi_titulo": "#ebe7e0",
    "bandeja": "#ffffff", "adaptador": "#ece9e3", "adaptador_borda": "#bdb6ab",
    "slot": "#d6d1c8", "vazio": "#d9d4cc", "led_off": "#e2ddd5", "numero": "#2f5fa8",
    "sfp": "#2f6f5e", "fusao_ok": "#5d574f", "cordao": "#c79a00", "ferrolho": "#8d857a",
    "apc": "#2f8f4e", "upc": "#2f5fa8",
    "ui_fundo": "#faf9f7", "ui_painel": "#ffffff", "ui_borda": "#e4e0d9",
    "ui_texto": "#1c1b19", "ui_texto_fraco": "#8d857a", "ui_acento": "#2f6f5e",
    "ui_acento_texto": "#ffffff", "ui_campo": "#ffffff", "ui_hover": "#f1efea",
    "ui_profundo": "#f3f1ed",
    "ui_erro": "#b4453c", "ui_aviso": "#b98b2e", "ui_ok": "#2f6f5e",
}

TEMAS = {"grafite": TEMA_GRAFITE, "linho": TEMA_LINHO}
TEMA = TEMA_GRAFITE          # tema ativo do programa


def aplicar_tema(nome):
    """Troca o tema ativo ('grafite' ou 'linho'). O diagrama, o SVG e o PDF
    seguem o que estiver ativo."""
    global TEMA
    TEMA = TEMAS.get(str(nome).lower(), TEMA_GRAFITE)
    return TEMA


# ============================================================================
#  GEOMETRIA E CENA (primitivas independentes de quem vai desenhar)
# ============================================================================

ALT_TITULO = 26.0
MARGEM_INTERNA = 12.0
ALT_CABECALHO = 70.0        # faixa reservada pro cabecalho do diagrama

# ---- desenho "como na vida real" (B0.25) ----
PASSO_DIO = 26.0            # distancia entre portas do DIO (adaptador SC)
COLUNAS_DIO = 12            # portas por fileira
PORTAS_POR_BANDEJA = 24     # 2 fileiras de 12 por bandeja
ALT_FILEIRA_DIO = 44.0
LARGURA_CABO = 220.0
ALT_FIBRA = 15.0
LARGURA_ACOMODADOR = 300.0
ALT_SAIDA_SPLITTER = 15.0
LARGURA_ATIVO = {"OLT": 284.0, "SWITCH": 436.0, "RB": 316.0}
CELULA_MODULO = {"GPON-8": 32.0, "GPON-16": 32.0, "CONTROLE": 46.0,
                 "SFP": 34.0, "QSFP": 46.0}
ALT_FILEIRA_ATIVO = 46.0


def espacado(texto):
    """D I O - o espacamento entre letras que o tkinter nao tem, na mao.
    So pra textos curtos sem espaco dentro (o SVG junta espacos repetidos)."""
    return " ".join(str(texto))


def _bandejas_dio(n):
    """Lista com a quantidade de portas de cada bandeja (24, 24, ..., resto)."""
    n = max(1, n)
    return [min(PORTAS_POR_BANDEJA, n - i) for i in range(0, n, PORTAS_POR_BANDEJA)]


LARGURA_DIO_VERTICAL = 240.0
LARGURA_ATIVO_VERTICAL = 230.0
PORTAS_POR_BANDEJA_VERTICAL = 12     # bandeja de 12: casa com o tubo de 12 do cabo


def _bandejas_verticais(n):
    n = max(1, n)
    q = PORTAS_POR_BANDEJA_VERTICAL
    return [min(q, n - i) for i in range(0, n, q)]


def _alt_bandeja(qtd):
    fileiras = 1 if qtd <= COLUNAS_DIO else 2
    return fileiras * ALT_FILEIRA_DIO + 8.0


def _tubos_do_cabo(eq):
    """[(tubo, [fibras...]), ...] seguindo as fibras por tubo do cabo."""
    fpt = max(1, eq.fibras_por_tubo or FIBRAS_POR_TUBO_PADRAO)
    tubos = []
    for inicio in range(1, eq.num_portas + 1, fpt):
        tubos.append(((inicio - 1) // fpt + 1,
                      list(range(inicio, min(inicio + fpt, eq.num_portas + 1)))))
    return tubos


def _grade_ativo(eq, mod):
    """(celula, colunas, fileiras) de um modulo de OLT/SWITCH/RB."""
    largura = LARGURA_ATIVO.get(eq.tipo, 316.0)
    celula = CELULA_MODULO.get(mod.tipo, 34.0)
    colunas = max(1, int((largura - 28.0) // celula))
    fileiras = max(1, -(-mod.num_portas // colunas))
    return celula, colunas, fileiras


def layout_equipamento(eq):
    """Largura e altura da caixa do equipamento no diagrama (as duas medidas
    que o resto do programa usa pra posicionar e organizar)."""
    topo = ALT_TITULO + 8.0
    if eq.is_dio() and eq.orientacao == "vertical":
        bandejas = _bandejas_verticais(eq.num_portas)
        altura = topo + sum(16.0 + q * ALT_FIBRA for q in bandejas) + 8.0
        return {"largura": LARGURA_DIO_VERTICAL, "altura": altura}
    if eq.is_dio():
        colunas = max(1, min(COLUNAS_DIO, eq.num_portas))
        meia = colunas * PASSO_DIO + 18.0
        bandejas = _bandejas_dio(eq.num_portas)
        altura = (ALT_TITULO + 22.0 + sum(_alt_bandeja(q) for q in bandejas)
                  + 10.0 * (len(bandejas) - 1) + 12.0)
        return {"largura": 2 * meia + 44.0, "altura": altura, "meia": meia}
    if eq.is_cabo():
        altura = topo + sum(16.0 + len(f) * ALT_FIBRA for _, f in _tubos_do_cabo(eq)) + 8.0
        return {"largura": LARGURA_CABO, "altura": altura}
    if eq.tipo == TIPO_ACOMODADOR:
        altura = topo
        for mod in eq.modulos.values():
            saidas = mod.num_portas - 1
            altura += 18.0 + max(saidas * ALT_SAIDA_SPLITTER + 10.0, 44.0) + 10.0
        return {"largura": LARGURA_ACOMODADOR, "altura": max(altura + 4.0, ALT_TITULO + 40.0)}
    if eq.orientacao == "vertical":
        altura = topo + sum(16.0 + m.num_portas * ALT_FIBRA for m in eq.modulos.values())
        return {"largura": LARGURA_ATIVO_VERTICAL,
                "altura": max(altura + 8.0, ALT_TITULO + 40.0)}
    altura = topo
    for mod in eq.modulos.values():
        _, _, fileiras = _grade_ativo(eq, mod)
        altura += 18.0 + fileiras * ALT_FILEIRA_ATIVO + 8.0
    return {"largura": LARGURA_ATIVO.get(eq.tipo, 316.0),
            "altura": max(altura + 4.0, ALT_TITULO + 40.0)}


def cor_linha_fibra(cor, tema):
    """A cor da fibra, legivel no fundo: preta no tema escuro e branca no
    claro sumiriam, entao viram um cinza."""
    if tema.get("escuro") and cor == "#0b0b0b":
        return "#6a6a6a"
    if not tema.get("escuro") and cor == "#f0f0f0":
        return "#b8b8b8"
    return cor


def _bezier(p0, c1, c2, p3, passos=22):
    """Amostra uma curva de bezier cubica como uma lista de pontos."""
    pts = []
    for i in range(passos + 1):
        t = i / float(passos)
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0],
                    a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]))
    return pts


class Cena:
    """Lista de primitivas em coordenadas do "mundo" (y cresce pra baixo).
    Quem desenha (Canvas do tkinter, SVG ou PDF) so percorre esta lista."""

    def __init__(self, tema=None):
        self.itens = []        # dicts: ret | linha | texto | oval
        self.potencias = None  # dBm calculados (camada de potencia), se houver
        self.portas = {}       # (eq,mod,num) -> {"x","y","lado"}
        self.titulos = {}      # eq_id -> {"x0","y0","x1","y1"}
        self.tema = tema or TEMA
        self.minx = self.miny = 0.0
        self.maxx = self.maxy = 0.0

    def ret(self, x, y, w, h, fill=None, outline=None, largura=1.0, tags=()):
        self.itens.append({"t": "ret", "x": x, "y": y, "w": w, "h": h,
                           "fill": fill, "outline": outline, "lw": largura,
                           "tags": tuple(tags)})

    def linha(self, pontos, cor="#000000", largura=1.0, tracejado=None, tags=()):
        self.itens.append({"t": "linha", "pts": list(pontos), "cor": cor,
                           "lw": largura, "dash": tracejado, "tags": tuple(tags)})

    def texto(self, x, y, texto, tamanho=9.0, cor=None, ancora="w",
              negrito=False, tags=()):
        self.itens.append({"t": "texto", "x": x, "y": y, "s": texto,
                           "tam": tamanho, "cor": cor or self.tema["porta_cor"],
                           "anc": ancora, "bold": negrito, "tags": tuple(tags)})

    def oval(self, x, y, raio, cor, largura=2.0, tags=()):
        self.itens.append({"t": "oval", "x": x, "y": y, "r": raio, "cor": cor,
                           "lw": largura, "tags": tuple(tags)})

    def calcular_limites(self, margem=30.0):
        xs, ys = [], []
        for it in self.itens:
            if it["t"] == "ret":
                xs += [it["x"], it["x"] + it["w"]]
                ys += [it["y"], it["y"] + it["h"]]
            elif it["t"] == "linha":
                xs += [p[0] for p in it["pts"]]
                ys += [p[1] for p in it["pts"]]
            elif it["t"] in ("texto", "oval"):
                xs.append(it["x"])
                ys.append(it["y"])
        if not xs:
            xs, ys = [0.0, 400.0], [0.0, 300.0]
        self.minx, self.maxx = min(xs) - margem, max(xs) + margem
        self.miny, self.maxy = min(ys) - margem, max(ys) + margem
        return self.minx, self.miny, self.maxx, self.maxy

    def pintar_fundo(self):
        """Fundo do tamanho exato da cena, atras de tudo."""
        self.itens.insert(0, {"t": "ret", "x": self.minx, "y": self.miny,
                              "w": self.largura, "h": self.altura,
                              "fill": self.tema["fundo"], "outline": None,
                              "lw": 0, "tags": ()})

    @property
    def largura(self):
        return self.maxx - self.minx

    @property
    def altura(self):
        return self.maxy - self.miny


def _estilo_fusao(rede, f, tema):
    """Cor e tracejado da linha de uma fusao:
    - as 2 fibras de uma porta duplex: cores quente/fria e tracejado;
    - fibra de cabo: a cor da propria fibra (codigo ABNT);
    - cordao (frente do DIO, porta de ativo): amarelo, como o cordao monomodo;
    - o resto (bandeja, splitter): cinza."""
    for eq_id, mod_id, num in f.pontas():
        eq = rede.equipamentos.get(eq_id)
        if eq is None or eq.tem_lados():
            continue
        if rede.tipo_gbic_porta(eq_id, mod_id, num) == DUPLEX:
            irmas = sorted(rede.fusoes_na_porta(eq_id, mod_id, num), key=lambda x: x.id)
            indice = [x.id for x in irmas].index(f.id) if f in irmas else 0
            return (tema["duplex1"] if indice == 0 else tema["duplex2"]), (5, 4)
    for eq_id, mod_id, num in f.pontas():
        eq = rede.equipamentos.get(eq_id)
        if eq is not None and eq.is_cabo():
            return cor_linha_fibra(cor_fibra(num, eq.fibras_por_tubo)[1], tema), None
    for eq_id, mod_id, num in f.pontas():
        eq = rede.equipamentos.get(eq_id)
        if eq is not None and (eq.tipo in TIPOS_ATIVOS or (eq.is_dio() and mod_id == "F")):
            return tema["cordao"], None
    return tema["fibra"], None


def _distribuir(topo, base, indice, quantidade):
    """Ponto de saida da fibra na borda: espalha as portas de um grupo ao
    longo da altura dele, pra as linhas nao sairem todas do mesmo ponto."""
    if quantidade <= 1:
        return (topo + base) / 2.0
    return topo + 4.0 + indice * (base - topo - 8.0) / float(quantidade - 1)


def _cor_status(t, status):
    return {"livre": t["vazio"], "parcial": t["parcial"], "completa": t["uso"]}[status]


def _desenhar_titulo(cena, eq, x0, y0, largura, subtitulo):
    t = cena.tema
    tag_eq, tag_tit = "eq:%s" % eq.id, "titulo:%s" % eq.id
    cena.ret(x0, y0, largura, ALT_TITULO, fill=t["chassi_titulo"], outline=t["chassi_borda"],
             largura=t["caixa_lw"], tags=(tag_eq, tag_tit))
    maximo = int((largura - 30 - len(subtitulo) * 5.0) / 6.0)
    nome = eq.nome if len(eq.nome) <= maximo else eq.nome[:max(maximo - 1, 4)] + "…"
    cena.texto(x0 + 12, y0 + ALT_TITULO / 2.0, nome, 9.0, t["titulo_cor"], "w", True,
               tags=(tag_eq, tag_tit))
    cena.texto(x0 + largura - 12, y0 + ALT_TITULO / 2.0, subtitulo, t["tipo_tam"],
               t["tipo_cor"], "e", tags=(tag_eq, tag_tit))
    cena.titulos[eq.id] = {"x0": x0, "y0": y0, "x1": x0 + largura, "y1": y0 + ALT_TITULO}


ESPACO_MIN_CONEXAO = 13.0   # distancia minima entre duas saidas de fibra na borda


def _registrar(cena, chave, cx, cy, ax, ay, lado, grupo=None):
    """Guarda onde a porta esta (centro, pra clicar e centralizar) e de onde
    sai a fibra (ancora na borda da caixa). Com 'grupo' (topo, base), a
    altura da saida e decidida depois, so entre as portas que tem fusao."""
    cena.portas[chave] = {"x": cx, "y": cy, "ax": ax, "ay": ay, "lado": lado,
                          "grupo": grupo}


def _espalhar(desejados, topo, base, espaco):
    """Posicoes em ordem, cada uma o mais perto possivel da desejada, com
    'espaco' minimo entre vizinhas e dentro de [topo, base]."""
    n = len(desejados)
    if n == 0:
        return []
    if n > 1 and (base - topo) < espaco * (n - 1):
        # nao cabe na altura da caixa: desce alem dela (vira uma regua de
        # conexao presa na borda) em vez de apertar as saidas
        return [topo + i * espaco for i in range(n)]
    ys = []
    for d in desejados:
        y = max(d, topo) if not ys else max(d, ys[-1] + espaco)
        ys.append(y)
    ys[-1] = min(ys[-1], base)
    for i in range(n - 2, -1, -1):
        ys[i] = min(ys[i], ys[i + 1] - espaco)
    if ys[0] < topo:                       # nao coube encostado: desce tudo
        ys = [topo + i * espaco for i in range(n)]
    return ys


def _resolver_conexoes(cena, rede):
    """Saida das fibras na borda: so as portas com fusao ganham saida, cada
    uma na altura da propria porta (ou o mais perto possivel), com espaco
    pra ver qual linha e de qual porta."""
    grupos = {}
    for chave, p in cena.portas.items():
        if p["grupo"] is not None and rede.fusoes_na_porta(*chave):
            grupos.setdefault(p["grupo"], []).append(chave)
    for (gid, topo, base), chaves in grupos.items():
        # ordem natural (fileira, numero): a porta 1 sai em cima da 2, e as
        # linhas pra outro equipamento em ordem nao se cruzam
        chaves.sort(key=lambda c: (cena.portas[c]["y"], c[2]))
        desejados = [cena.portas[c]["y"] for c in chaves]
        ys = _espalhar(desejados, topo + 4, base - 4, ESPACO_MIN_CONEXAO)
        for c, y in zip(chaves, ys):
            cena.portas[c]["ay"] = y
        if ys[-1] > base - 4:
            ax = cena.portas[chaves[0]]["ax"]
            t = cena.tema
            cena.ret(ax - 5, base - 2, 10, ys[-1] + 9 - base, fill=t["chassi"],
                     outline=t["chassi_borda"], largura=t["caixa_lw"])


def _desenhar_conexoes(cena, rede):
    """Conector bem visivel na borda de cada porta ligada, na cor da linha,
    com o numero da porta do lado (DIO e ativos)."""
    t = cena.tema
    for chave, p in cena.portas.items():
        fusoes = rede.fusoes_na_porta(*chave)
        ax, ay = p["ax"], p["ay"]
        tag = "porta:%s|%s|%d" % (chave[0], chave[1] or "", chave[2])
        if not fusoes:
            if p["grupo"] is None:
                cena.ret(ax - 1.4, ay - 1.4, 2.8, 2.8, fill=t["ferrolho"], outline=None)
            continue
        cor, _ = _estilo_fusao(rede, fusoes[0], t)
        fora = 1.0 if p["lado"] == "direita" else -1.0
        # plugue: corpo fino na cor da fibra pra fora da caixa + ferrolho
        # encostado na borda (em vez do quadrado grande)
        corpo_x = ax if fora > 0 else ax - 7.0
        cena.ret(corpo_x, ay - 2.2, 7.0, 4.4, fill=cor, outline=None, tags=(tag,))
        cena.ret(ax - 1.5 if fora > 0 else ax - 1.5, ay - 1.2, 3.0, 2.4, fill=t["ferrolho"],
                 outline=None, tags=(tag,))
        if p["grupo"] is not None:
            cena.texto(ax + fora * 8.0, ay - 5.0, rede.rotulo_porta(*chave), 6.4,
                       t["numero"], "w" if fora > 0 else "e", True, tags=(tag,))



def _tipo_do_modulo(rede, eq, mod):
    """'  ·  SC/APC' quando todas as portas do modulo tem o mesmo conector."""
    tipos = {rede.conector_da_porta(eq.id, mod.id, n) for n in mod.portas}
    if len(tipos) == 1:
        c, p = tipos.pop()
        if c:
            return "  ·  %s/%s" % (c, p)
    return "  ·  conectores mistos" if len(tipos) > 1 else ""


def _desenhar_potencias(cena, rede, potencias):
    """Valor em dBm do lado de fora de cada porta por onde o sinal passa
    (abaixo da linha, pra nao brigar com o numero da porta)."""
    t = cena.tema
    for chave, dbm in potencias["portas"].items():
        p = cena.portas.get(chave)
        if p is None:
            continue
        fora = 1.0 if p["lado"] == "direita" else -1.0
        fonte = chave in potencias["fontes"]
        texto = ("TX " if fonte else "") + formatar_dbm(dbm)
        cor = t["ui_acento"] if fonte else cor_nivel(t, dbm)
        x = p["ax"] + fora * 9.0
        y = p["ay"] + (6.5 if not fonte else -6.0)
        cena.ret(x - (0 if fora > 0 else 1) * (len(texto) * 3.6) - 1, y - 4, len(texto) * 3.6 + 2,
                 8, fill=t["fundo"], outline=None)
        cena.texto(x, y, texto, 5.8, cor, "w" if fora > 0 else "e", True)


def cor_polimento(t, polimento, padrao=None):
    return {"APC": t["apc"], "UPC": t["upc"]}.get(polimento, padrao or t["adaptador_borda"])


def _adaptador(cena, rede, chave, cx, cy, larg, alt, tags):
    """Adaptador/conector visto de frente: a borda na cor do polimento (APC
    verde, UPC azul); com fibra ligada, o conector aparece encaixado na mesma
    cor. Duplex (sempre LC) tem dois furos, um pra cada fibra."""
    t = cena.tema
    conector, polimento = rede.conector_da_porta(*chave)
    cor = cor_polimento(t, polimento)
    duplex = rede.tipo_gbic_porta(*chave) == DUPLEX
    usadas = len(rede.fusoes_na_porta(*chave))
    cena.ret(cx - larg / 2.0, cy - alt / 2.0, larg, alt, fill=t["adaptador"], outline=cor,
             largura=1.1, tags=tags)
    furos = 2 if duplex else 1
    fw = (larg - 6.0 - 2.0 * (furos - 1)) / furos
    fh = alt - 6.0 if conector != "LC" or duplex else alt - 7.0
    for k in range(furos):
        fx = cx - larg / 2.0 + 3.0 + k * (fw + 2.0)
        ocupado = usadas > k
        cena.ret(fx, cy - fh / 2.0, fw, fh, fill=cor if ocupado else t["slot"], outline=None,
                 tags=tags)
    return conector, polimento, duplex


def _desenhar_dio(cena, rede, eq, x0, y0, info):
    """DIO como o painel real: bandejas de 24 (2 fileiras de 12), traseira
    (fusao) de um lado e frente (conector) do outro."""
    t = cena.tema
    largura, meia = info["largura"], info["meia"]
    tag_eq = "eq:%s" % eq.id
    frente_dir = eq.lado_efetivo() == "direita"
    x_esq, x_dir = x0 + 12.0, x0 + largura - 12.0 - meia
    x_lado = {"T": x_esq if frente_dir else x_dir, "F": x_dir if frente_dir else x_esq}
    sub = {"T": "TRASEIRA  ·  FUSAO", "F": "FRENTE  ·  CONECTOR"}
    for lado in ("T", "F"):
        cena.texto(x_lado[lado] + meia / 2.0, y0 + ALT_TITULO + 11, sub[lado], 6.0,
                   t["tipo_cor"], "center", tags=(tag_eq,))
    y = y0 + ALT_TITULO + 22.0
    inicio = 1
    for qtd in _bandejas_dio(eq.num_portas):
        alt = _alt_bandeja(qtd)
        for lado in ("T", "F"):
            bx = x_lado[lado]
            na_esquerda = bx == x_esq
            cena.ret(bx, y, meia, alt, fill=t["bandeja"], outline=t["chassi_borda"],
                     largura=0.8, tags=(tag_eq,))
            for i in range(qtd):
                num = inicio + i
                fileira, coluna = divmod(i, COLUNAS_DIO)
                px = bx + 9.0 + coluna * PASSO_DIO
                py = y + 4.0 + fileira * ALT_FILEIRA_DIO
                status = rede.porta_status(eq.id, lado, num)
                usado = status != "livre"
                tag = "porta:%s|%s|%d" % (eq.id, lado, num)
                cena.texto(px + 11, py + 7, str(num), 6.4, t["numero"], "center", True,
                           tags=(tag_eq, tag))
                cena.ret(px + 2, py + 12, 18, 18, fill=t["adaptador"],
                         outline=t["adaptador_borda"], largura=0.8, tags=(tag_eq, tag))
                if lado == "T":
                    cena.ret(px + 7, py + 17, 8, 8, fill=t["fusao_ok"] if usado else t["vazio"],
                             outline=None, tags=(tag_eq, tag))
                else:
                    _adaptador(cena, rede, (eq.id, "F", num), px + 11, py + 21, 16, 14,
                               (tag_eq, tag))
                cena.ret(px + 2, py + 32, 18, 2, fill=t["uso"] if usado else t["led_off"],
                         outline=None, tags=(tag_eq, tag))
                ax = x0 if na_esquerda else x0 + largura
                _registrar(cena, (eq.id, lado, num), px + 11, py + 21, ax, py + 21,
                           "esquerda" if na_esquerda else "direita",
                           grupo=((eq.id, lado), y0 + ALT_TITULO + 2.0,
                                  y0 + info["altura"]))
        inicio += qtd
        y += alt + 10.0
    # setinha no meio: o sinal atravessa o adaptador
    cx, cy = x0 + largura / 2.0, y0 + ALT_TITULO + 22.0 + 20.0
    d = 3.0 if frente_dir else -3.0
    cena.linha([(cx - d, cy - 5), (cx + d, cy), (cx - d, cy + 5)], t["tipo_cor"], 1.2,
               tags=(tag_eq,))


def _desenhar_dio_vertical(cena, rede, eq, x0, y0, info):
    """DIO em pe: uma porta por linha, traseira (fusao) de um lado e frente
    (conector) do outro, bandejas de 12. As linhas ficam na mesma altura das
    fibras do cabo ao lado, entao a fibra N chega reto na porta N."""
    t = cena.tema
    largura = info["largura"]
    tag_eq = "eq:%s" % eq.id
    frente_dir = eq.lado_efetivo() == "direita"
    y = y0 + ALT_TITULO + 8.0
    inicio = 1
    for b, qtd in enumerate(_bandejas_verticais(eq.num_portas)):
        cena.texto(x0 + largura / 2.0, y + 8, "BANDEJA %d" % (b + 1), 6.2, t["modulo_cor"],
                   "center", tags=(tag_eq,))
        # rotulo de cada lado centrado em cima da coluna de adaptadores
        cena.texto(x0 + 26, y + 8, "FRENTE" if not frente_dir else "TRASEIRA", 5.4,
                   t["tipo_cor"], "center", tags=(tag_eq,))
        cena.texto(x0 + largura - 26, y + 8, "FRENTE" if frente_dir else "TRASEIRA", 5.4,
                   t["tipo_cor"], "center", tags=(tag_eq,))
        y += 16.0
        cena.ret(x0 + 6, y - 1, largura - 12, qtd * ALT_FIBRA + 2, fill=t["bandeja"],
                 outline=t["chassi_borda"], largura=0.8, tags=(tag_eq,))
        for i in range(qtd):
            num = inicio + i
            cy = y + ALT_FIBRA / 2.0
            # passagem interna (adaptador): fio fino ligando os dois lados
            cena.linha([(x0 + 40, cy), (x0 + largura - 40, cy)], t["led_off"], 1.0,
                       tags=(tag_eq,))
            cena.ret(x0 + largura / 2.0 - 13, cy - 6, 26, 12, fill=t["bandeja"], outline=None,
                     tags=(tag_eq,))
            cena.texto(x0 + largura / 2.0, cy, str(num), 6.6, t["numero"], "center", True,
                       tags=(tag_eq, "porta:%s|%s|%d" % (eq.id, "F", num)))
            for lado in ("T", "F"):
                na_esquerda = (lado == "T") == frente_dir
                tag = "porta:%s|%s|%d" % (eq.id, lado, num)
                usadas = len(rede.fusoes_na_porta(eq.id, lado, num))
                cx = x0 + 26 if na_esquerda else x0 + largura - 26
                if lado == "F":
                    conector, polimento, duplex = _adaptador(
                        cena, rede, (eq.id, "F", num), cx, cy, 22, 12, (tag_eq, tag))
                    tx = cx - 16 if not na_esquerda else cx + 16
                    cena.texto(tx, cy, texto_conector(conector, polimento,
                                                      duplex).replace(" duplex", " dx"),
                               5.2, cor_polimento(t, polimento, t["tipo_cor"]),
                               "e" if not na_esquerda else "w", tags=(tag_eq, tag))
                else:
                    duplex = rede.tipo_gbic_porta(eq.id, "T", num) == DUPLEX
                    cena.ret(cx - 11, cy - 6, 22, 12, fill=t["adaptador"],
                             outline=t["adaptador_borda"], largura=0.8, tags=(tag_eq, tag))
                    for k in range(2 if duplex else 1):
                        largura_f = 12 if not duplex else 6
                        fx = cx - 6 + k * 7 if duplex else cx - 6
                        cena.ret(fx, cy - 3, largura_f - (1 if duplex else 0), 6,
                                 fill=t["fusao_ok"] if usadas > k else t["vazio"],
                                 outline=None, tags=(tag_eq, tag))
                _registrar(cena, (eq.id, lado, num), cx, cy, x0 if na_esquerda else x0 + largura,
                           cy, "esquerda" if na_esquerda else "direita")
            y += ALT_FIBRA
        inicio += qtd


def _desenhar_cabo(cena, rede, eq, x0, y0, info):
    """Cabo com os tubos e as fibras nas cores ABNT; ponta A de um lado e
    ponta B do outro."""
    t = cena.tema
    largura = info["largura"]
    tag_eq = "eq:%s" % eq.id
    b_dir = eq.lado_efetivo() == "direita"
    y = y0 + ALT_TITULO + 8.0
    for tubo, fibras in _tubos_do_cabo(eq):
        nome_t, cor_t = CORES_ABNT[(tubo - 1) % 12]
        cena.ret(x0 + 12, y + 4, 12, 8, fill=cor_t, outline=t["adaptador_borda"], largura=0.6,
                 tags=(tag_eq,))
        cena.texto(x0 + 30, y + 8, "TUBO %d  ·  %s" % (tubo, nome_t.upper()), 6.2,
                   t["modulo_cor"], "w", tags=(tag_eq,))
        y += 16.0
        topo = y
        for num in fibras:
            nome_f, cor_f = cor_fibra(num, eq.fibras_por_tubo)
            cy = y + ALT_FIBRA / 2.0
            cena.linha([(x0 + 34, cy), (x0 + largura - 34, cy)], cor_linha_fibra(cor_f, t),
                       1.2, tags=(tag_eq,))
            cena.ret(x0 + largura / 2.0 - 13, cy - 6, 26, 12, fill=t["chassi"], outline=None,
                     tags=(tag_eq,))
            cena.texto(x0 + largura / 2.0, cy, str(num), 6.4, t["numero"], "center", True,
                       tags=(tag_eq,))
            for lado in ("A", "B"):
                na_esquerda = (lado == "A") == b_dir
                tag = "porta:%s|%s|%d" % (eq.id, lado, num)
                usado = bool(rede.fusoes_na_porta(eq.id, lado, num))
                cx = x0 + 24 if na_esquerda else x0 + largura - 24
                # fibra com a capinha colorida (tubete) e a ponta
                cena.ret(cx - 9, cy - 2.5, 18, 5, fill=cor_f, outline=t["adaptador_borda"],
                         largura=0.5, tags=(tag_eq, tag))
                fx = cx - 13 if na_esquerda else cx + 9
                cena.ret(fx, cy - 1.5, 4, 3, fill=t["uso"] if usado else t["ferrolho"],
                         outline=None, tags=(tag_eq, tag))
                ax = x0 if na_esquerda else x0 + largura
                _registrar(cena, (eq.id, lado, num), cx, cy, ax, cy,
                           "esquerda" if na_esquerda else "direita")
            y += ALT_FIBRA
        cena.ret(x0 + 4, topo, 3, y - topo, fill=cor_t, outline=None, tags=(tag_eq,))


def _desenhar_acomodador(cena, rede, eq, x0, y0, info):
    """CTO/acomodador: cada splitter PLC com a entrada de um lado e as saidas
    conectorizadas do outro."""
    t = cena.tema
    largura = info["largura"]
    tag_eq = "eq:%s" % eq.id
    saidas_esq = eq.lado_efetivo() == "esquerda"
    y = y0 + ALT_TITULO + 8.0
    for mod in eq.modulos.values():
        cena.texto(x0 + 12, y + 8, ("%s  ·  PLC %s%s" % (mod.nome.upper(), mod.tipo,
                                                         _tipo_do_modulo(rede, eq, mod)))[:54],
                   6.2, t["modulo_cor"], "w", tags=(tag_eq,))
        y += 18.0
        saidas = sorted(n for n in mod.portas if n != 1)
        alt = max(len(saidas) * ALT_SAIDA_SPLITTER + 10.0, 44.0)
        bx = x0 + largura / 2.0 - 26
        cena.ret(bx, y, 52, alt, fill=t["adaptador"], outline=t["adaptador_borda"],
                 largura=0.8, tags=(tag_eq,))
        cena.texto(bx + 26, y + alt / 2.0, mod.tipo, 8.0, t["titulo_cor"], "center", True,
                   tags=(tag_eq,))
        # entrada (ENT), no lado oposto das saidas
        meio = y + alt / 2.0
        ent_cx = x0 + largura - 34 if saidas_esq else x0 + 34
        borda_corpo = bx + 52 if saidas_esq else bx
        cena.linha([(borda_corpo, meio), (ent_cx + (-8 if saidas_esq else 8), meio)],
                   t["ferrolho"], 1.6, tags=(tag_eq,))
        tag = "porta:%s|%s|%d" % (eq.id, mod.id, 1)
        status = rede.porta_status(eq.id, mod.id, 1)
        _adaptador(cena, rede, (eq.id, mod.id, 1), ent_cx, meio, 16, 14, (tag_eq, tag))
        cena.texto(ent_cx, meio - 13, "ENT", 6.0, t["tipo_cor"], "center", tags=(tag_eq, tag))
        _registrar(cena, (eq.id, mod.id, 1), ent_cx, meio,
                   x0 + largura if saidas_esq else x0, meio,
                   "direita" if saidas_esq else "esquerda")
        # saidas
        for k, num in enumerate(saidas):
            cy = y + 5.0 + k * ALT_SAIDA_SPLITTER + ALT_SAIDA_SPLITTER / 2.0
            cx = x0 + 30 if saidas_esq else x0 + largura - 30
            corpo = bx if saidas_esq else bx + 52
            cena.linha([(corpo, cy), (cx + (28 if saidas_esq else -28), cy)], t["ferrolho"],
                       0.8, tags=(tag_eq,))
            tag = "porta:%s|%s|%d" % (eq.id, mod.id, num)
            status = rede.porta_status(eq.id, mod.id, num)
            _adaptador(cena, rede, (eq.id, mod.id, num), cx, cy, 16, 12, (tag_eq, tag))
            cena.texto(cx + 11 if saidas_esq else cx - 11, cy, "S%d" % (num - 1), 6.0,
                       t["tipo_cor"], "w" if saidas_esq else "e", tags=(tag_eq, tag))
            _registrar(cena, (eq.id, mod.id, num), cx, cy, x0 if saidas_esq else x0 + largura,
                       cy, "esquerda" if saidas_esq else "direita")
        y += alt + 10.0
    if not eq.modulos:
        cena.texto(x0 + largura / 2.0, y0 + ALT_TITULO + 20, "sem splitter", 6.6,
                   t["tipo_cor"], "center", tags=(tag_eq,))


def _desenhar_ativo(cena, rede, eq, x0, y0, info):
    """OLT/SWITCH/RB: cada placa ou grupamento como uma fileira de gaiolas
    SFP; com fusao, aparece o modulo encaixado e o LED aceso."""
    t = cena.tema
    largura = info["largura"]
    tag_eq = "eq:%s" % eq.id
    portas_esq = eq.lado_efetivo() == "esquerda"
    y = y0 + ALT_TITULO + 8.0
    for mod in eq.modulos.values():
        extra = "  ·  GBIC %s" % mod.gbic_fixo if mod.gbic_fixo else ""
        cena.texto(x0 + 12, y + 8, (mod.nome.upper() + extra)[:52], 6.2, t["modulo_cor"],
                   "w", tags=(tag_eq,))
        y += 18.0
        celula, colunas, fileiras = _grade_ativo(eq, mod)
        gaiola = celula - 6.0
        numeros = sorted(mod.portas)
        alt = fileiras * ALT_FILEIRA_ATIVO
        for i, num in enumerate(numeros):
            fileira, coluna = divmod(i, colunas)
            px = x0 + 14.0 + coluna * celula
            py = y + fileira * ALT_FILEIRA_ATIVO
            tag = "porta:%s|%s|%d" % (eq.id, mod.id, num)
            status = rede.porta_status(eq.id, mod.id, num)
            usadas = len(rede.fusoes_na_porta(eq.id, mod.id, num))
            duplex = rede.tipo_gbic_porta(eq.id, mod.id, num) == DUPLEX
            cena.texto(px + gaiola / 2.0, py + 7, rede.rotulo_porta(eq.id, mod.id, num), 6.4,
                       t["numero"], "center", True, tags=(tag_eq, tag))
            cena.ret(px, py + 12, gaiola, 20, fill=t["adaptador"], outline=t["adaptador_borda"],
                     largura=0.8, tags=(tag_eq, tag))
            cor_mod = cor_polimento(t, rede.conector_da_porta(eq.id, mod.id, num)[1], t["sfp"])
            if duplex:                   # LC duplex: dois furos (TX / RX)
                furo = (gaiola - 14.0) / 2.0
                for k in range(2):
                    fx = px + 5 + k * (furo + 4)
                    cena.ret(fx, py + 16, furo, 12, fill=t["slot"], outline=None,
                             tags=(tag_eq, tag))
                    if usadas > k:
                        cena.ret(fx + 2, py + 18, furo - 4, 8, fill=cor_mod, outline=None,
                                 tags=(tag_eq, tag))
            else:
                cena.ret(px + 5, py + 16, gaiola - 10, 12, fill=t["slot"], outline=None,
                         tags=(tag_eq, tag))
                if usadas:
                    cena.ret(px + 8, py + 18, gaiola - 16, 8, fill=cor_mod, outline=None,
                             tags=(tag_eq, tag))
            led = {"livre": t["led_off"], "parcial": t["parcial"], "completa": t["uso"]}[status]
            cena.ret(px + gaiola / 2.0 - 2, py + 35, 4, 4, fill=led, outline=None,
                     tags=(tag_eq, tag))
            ax = x0 if portas_esq else x0 + largura
            _registrar(cena, (eq.id, mod.id, num), px + gaiola / 2.0, py + 22, ax, py + 22,
                       "esquerda" if portas_esq else "direita",
                       grupo=((eq.id, "lado"), y0 + ALT_TITULO + 2.0, y0 + info["altura"]))
        y += alt + 8.0
    if not eq.modulos:
        cena.texto(x0 + largura / 2.0, y0 + ALT_TITULO + 20,
                   "sem placa" if eq.tipo == "OLT" else "sem grupamento", 6.6,
                   t["tipo_cor"], "center", tags=(tag_eq,))


def _desenhar_ativo_vertical(cena, rede, eq, x0, y0, info):
    """OLT/switch/RB em pe: cada placa (ou grupamento) e uma coluna de portas,
    uma por linha, com a gaiola SFP virada pra borda - igual ao DIO em pe,
    entao a porta 0 da placa fica na altura da porta 1 do DIO ao lado."""
    t = cena.tema
    largura = info["largura"]
    tag_eq = "eq:%s" % eq.id
    portas_esq = eq.lado_efetivo() == "esquerda"
    y = y0 + ALT_TITULO + 8.0
    for mod in eq.modulos.values():
        extra = "  ·  GBIC %s" % mod.gbic_fixo if mod.gbic_fixo else ""
        texto = mod.nome.upper() + extra
        if len(texto) > 34:
            texto = texto[:33] + "…"
        cena.texto(x0 + largura / 2.0, y + 8, texto, 6.0, t["modulo_cor"], "center",
                   tags=(tag_eq,))
        y += 16.0
        cena.ret(x0 + 6, y - 1, largura - 12, mod.num_portas * ALT_FIBRA + 2,
                 fill=t["bandeja"], outline=t["chassi_borda"], largura=0.8, tags=(tag_eq,))
        for num in sorted(mod.portas):
            cy = y + ALT_FIBRA / 2.0
            tag = "porta:%s|%s|%d" % (eq.id, mod.id, num)
            status = rede.porta_status(eq.id, mod.id, num)
            usadas = len(rede.fusoes_na_porta(eq.id, mod.id, num))
            duplex = rede.tipo_gbic_porta(eq.id, mod.id, num) == DUPLEX
            cx = x0 + 28 if portas_esq else x0 + largura - 28
            conector, polimento = rede.conector_da_porta(eq.id, mod.id, num)
            cor_mod = cor_polimento(t, polimento, t["sfp"])
            # gaiola SFP vista de frente, virada pra borda
            cena.ret(cx - 13, cy - 6, 26, 12, fill=t["adaptador"], outline=t["adaptador_borda"],
                     largura=0.8, tags=(tag_eq, tag))
            if duplex:
                for k in range(2):
                    fx = cx - 10 + k * 11
                    cena.ret(fx, cy - 3.5, 9, 7, fill=t["slot"], outline=None, tags=(tag_eq, tag))
                    if usadas > k:
                        cena.ret(fx + 1.5, cy - 2, 6, 4, fill=cor_mod, outline=None,
                                 tags=(tag_eq, tag))
            else:
                cena.ret(cx - 10, cy - 3.5, 20, 7, fill=t["slot"], outline=None, tags=(tag_eq, tag))
                if usadas:
                    cena.ret(cx - 8, cy - 2, 16, 4, fill=cor_mod, outline=None,
                             tags=(tag_eq, tag))
            # numero (OLT conta de 0), o tipo do conector e o LED, por dentro
            nx = cx + 22 if portas_esq else cx - 22
            cena.texto(nx, cy, rede.rotulo_porta(eq.id, mod.id, num), 6.6, t["numero"],
                       "w" if portas_esq else "e", True, tags=(tag_eq, tag))
            cena.texto(nx + (18 if portas_esq else -18), cy,
                       texto_conector(conector, polimento, duplex), 5.4,
                       cor_polimento(t, polimento, t["tipo_cor"]),
                       "w" if portas_esq else "e", tags=(tag_eq, tag))
            led = {"livre": t["led_off"], "parcial": t["parcial"], "completa": t["uso"]}[status]
            lx = x0 + largura - 20 if portas_esq else x0 + 16
            cena.ret(lx, cy - 2, 4, 4, fill=led, outline=None, tags=(tag_eq, tag))
            _registrar(cena, (eq.id, mod.id, num), cx, cy, x0 if portas_esq else x0 + largura,
                       cy, "esquerda" if portas_esq else "direita")
            y += ALT_FIBRA
    if not eq.modulos:
        cena.texto(x0 + largura / 2.0, y0 + ALT_TITULO + 20,
                   "sem placa" if eq.tipo == "OLT" else "sem grupamento", 6.6,
                   t["tipo_cor"], "center", tags=(tag_eq,))


def _subtitulo(rede, eq):
    if eq.is_dio():
        return "%d PORTAS" % eq.num_portas
    if eq.is_cabo():
        return "%dFO" % eq.num_portas
    if eq.tipo == TIPO_ACOMODADOR:
        return "CTO  ·  %d SPLITTER%s" % (len(eq.modulos), "" if len(eq.modulos) == 1 else "S")
    return eq.tipo


def cor_nivel(t, dbm):
    """Verde / laranja / vermelho pela potencia que chega (faixas do GPON)."""
    return {"ok": t["uso"], "alerta": t["ui_aviso"], "critico": t["ui_erro"]}[
        classificar_potencia(dbm)]


def montar_cena(rede, selecionado=None, com_legenda=True, destaque=None, tema=None,
                selecao_lote=None, potencias=None):
    """Constroi a cena completa do diagrama a partir da rede.
    destaque: ids de fusoes pra desenhar realcadas (usado pelo rastreio).
    tema: usa o tema ativo do programa se nao for informado."""
    t = tema or TEMA
    cena = Cena(t)
    destaque = destaque or set()

    for eq in sorted(rede.equipamentos.values(), key=lambda e: e.ordem):
        info = layout_equipamento(eq)
        x0, y0 = eq.pos_x, eq.pos_y
        cena.ret(x0, y0, info["largura"], info["altura"], fill=t["chassi"],
                 outline=t["chassi_borda"], largura=t["caixa_lw"], tags=("eq:%s" % eq.id,))
        _desenhar_titulo(cena, eq, x0, y0, info["largura"], _subtitulo(rede, eq))
        if eq.is_dio() and eq.orientacao == "vertical":
            _desenhar_dio_vertical(cena, rede, eq, x0, y0, info)
        elif eq.is_dio():
            _desenhar_dio(cena, rede, eq, x0, y0, info)
        elif eq.is_cabo():
            _desenhar_cabo(cena, rede, eq, x0, y0, info)
        elif eq.tipo == TIPO_ACOMODADOR:
            _desenhar_acomodador(cena, rede, eq, x0, y0, info)
        elif eq.orientacao == "vertical":
            _desenhar_ativo_vertical(cena, rede, eq, x0, y0, info)
        else:
            _desenhar_ativo(cena, rede, eq, x0, y0, info)

    _resolver_conexoes(cena, rede)
    itens_equipamentos = cena.itens
    cena.itens = []
    por_cima = []          # destaque do rastreio e rotulos ficam acima das caixas

    # ---- fusoes ----
    for f in sorted(rede.fusoes.values(), key=lambda x: x.id):
        pa, pb = f.pontas()
        if pa not in cena.portas or pb not in cena.portas:
            continue
        a, b = cena.portas[pa], cena.portas[pb]
        p0, p3 = (a["ax"], a["ay"]), (b["ax"], b["ay"])
        cor, dash = _estilo_fusao(rede, f, t)
        if a["lado"] == b["lado"]:
            # as duas pontas olham pro mesmo lado: arco pra fora, em vez de
            # atravessar as caixas por dentro
            fora = 60.0 + abs(p0[1] - p3[1]) * 0.18
            bx = (max(p0[0], p3[0]) + fora if a["lado"] == "direita"
                  else min(p0[0], p3[0]) - fora)
            c1, c2 = (bx, p0[1]), (bx, p3[1])
        else:
            dx = max(abs(p3[0] - p0[0]) * 0.5, 40.0)
            s0 = 1.0 if a["lado"] == "direita" else -1.0
            s3 = 1.0 if b["lado"] == "direita" else -1.0
            c1, c2 = (p0[0] + s0 * dx, p0[1]), (p3[0] + s3 * dx, p3[1])
        pts = _bezier(p0, c1, c2, p3)
        if f.id in destaque:
            n = len(cena.itens)
            cena.linha(pts, t["halo"], 7.0, None, tags=("fusao:%s" % f.id,))
            cena.linha(pts, t["destaque"], 1.8, dash, tags=("fusao:%s" % f.id,))
            por_cima += cena.itens[n:]
            del cena.itens[n:]
        else:
            if potencias and f.id in potencias["fusoes"]:
                # fibra com sinal: contorno na cor do nivel, a cor da fibra por cima
                cena.linha(pts, cor_nivel(t, potencias["fusoes"][f.id]), 4.6, None,
                           tags=("fusao:%s" % f.id,))
            cena.linha(pts, cor, 1.7, dash, tags=("fusao:%s" % f.id,))
        if f.rotulo:
            meio = pts[len(pts) // 2]
            n = len(cena.itens)
            cena.texto(meio[0], meio[1] - 7, f.rotulo, 6.6, t["rotulo_cor"],
                       "center", tags=("fusao:%s" % f.id,))
            por_cima += cena.itens[n:]
            del cena.itens[n:]
    # a fibra que so passa por tras de uma caixa some atras dela (como no
    # papel), em vez de riscar por cima das portas
    cena.itens = cena.itens + itens_equipamentos + por_cima

    _desenhar_conexoes(cena, rede)
    cena.potencias = potencias
    if potencias:
        _desenhar_potencias(cena, rede, potencias)

    # portas marcadas com Shift (fusao em lote)
    for chave in (selecao_lote or ()):
        if chave in cena.portas:
            p = cena.portas[chave]
            cena.oval(p["x"], p["y"], 9.0, t["selecao"], 1.6)
    if selecionado:
        chave = (selecionado["eq_id"], selecionado["modulo_id"], selecionado["porta_num"])
        if chave in cena.portas:
            p = cena.portas[chave]
            cena.oval(p["x"], p["y"], 13.0, t["selecao"], 2.0)

    cena.calcular_limites()

    if com_legenda:
        # cabecalho discreto no lugar da legenda cheia de itens
        topo = cena.miny - ALT_CABECALHO
        cena.texto(cena.minx + 40, topo + 20, espacado(APP_NOME.upper()), 14.0,
                   t["cabecalho_cor"], "w", True)
        cena.texto(cena.minx + 40, topo + 40,
                   "DIAGRAMA DE FUSOES   ·   " + VERSAO, 6.8, t["tipo_cor"], "w")
        local = getattr(rede, "local", None)
        if mapa.local_preenchido(local):
            linha_local = mapa.resumo_local(local)
            if local.get("endereco"):
                linha_local += "   ·   " + local["endereco"]
            cena.texto(cena.minx + 40, topo + 55, linha_local.upper(), 6.8,
                       t["cabecalho_cor"], "w")
        conta = lambda cond: len([e for e in rede.equipamentos.values() if cond(e)])
        usadas = sum(rede.ocupacao(e)[0] for e in rede.equipamentos.values() if not e.is_cabo())
        total = sum(rede.ocupacao(e)[1] for e in rede.equipamentos.values() if not e.is_cabo())
        cena.texto(cena.maxx - 40, topo + 30,
                   "%d CABO   ·   %d DIO   ·   %d ACOMODADOR   ·   %d ATIVO   ·   %d FUSOES"
                   "   ·   %d/%d PORTAS"
                   % (conta(lambda e: e.is_cabo()), conta(lambda e: e.is_dio()),
                      conta(lambda e: e.tipo == TIPO_ACOMODADOR),
                      conta(lambda e: e.tipo in TIPOS_ATIVOS), len(rede.fusoes), usadas, total),
                   6.8, t["tipo_cor"], "e")
        # legenda das cores do polimento
        lx = cena.maxx - 40
        for rotulo, cor in (("UPC", t["upc"]), ("APC", t["apc"])):
            cena.texto(lx, topo + 46, rotulo, 6.6, t["tipo_cor"], "e")
            cena.ret(lx - 34, topo + 42, 8, 8, fill=cor, outline=None)
            lx -= 56
        cena.texto(lx, topo + 46, "POLIMENTO", 6.0, t["tipo_cor"], "e")
        if potencias and potencias["fontes"]:
            lx -= 80
            for rotulo, cor in (("< -28 CRITICO", t["ui_erro"]), ("< -25 ALERTA", t["ui_aviso"]),
                                ("OK", t["uso"])):
                cena.texto(lx, topo + 46, rotulo, 6.0, t["tipo_cor"], "e")
                cena.ret(lx - len(rotulo) * 4.8 - 14, topo + 42, 8, 8, fill=cor, outline=None)
                lx -= len(rotulo) * 4.8 + 34
            cena.texto(lx, topo + 46, "SINAL (dBm)", 6.0, t["tipo_cor"], "e")
        cena.calcular_limites()
    cena.pintar_fundo()
    return cena


# ============================================================================
#  EXPORTACAO: SVG
# ============================================================================

def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def exportar_svg(cena, caminho):
    dx, dy = -cena.minx, -cena.miny
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
              'viewBox="0 0 %.0f %.0f">' % (cena.largura, cena.altura,
                                            cena.largura, cena.altura),
              '<rect width="100%%" height="100%%" fill="%s"/>'
              % (cena.tema or TEMA)["fundo"],
              '<g font-family="Helvetica, Arial, sans-serif">']
    ancoras = {"w": "start", "e": "end", "center": "middle"}
    for it in cena.itens:
        if it["t"] == "ret":
            partes.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                          'fill="%s" stroke="%s" stroke-width="%.1f"/>'
                          % (it["x"] + dx, it["y"] + dy, it["w"], it["h"],
                             it["fill"] or "none", it["outline"] or "none", it["lw"]))
        elif it["t"] == "linha":
            pts = " ".join("%.1f,%.1f" % (p[0] + dx, p[1] + dy) for p in it["pts"])
            dash = (' stroke-dasharray="%s"' % ",".join(map(str, it["dash"]))
                    if it["dash"] else "")
            partes.append('<polyline points="%s" fill="none" stroke="%s" '
                          'stroke-width="%.1f"%s/>' % (pts, it["cor"], it["lw"], dash))
        elif it["t"] == "texto":
            partes.append('<text x="%.1f" y="%.1f" font-size="%.1f" fill="%s" '
                          'text-anchor="%s"%s>%s</text>'
                          % (it["x"] + dx, it["y"] + dy + it["tam"] * 0.36, it["tam"],
                             it["cor"], ancoras.get(it["anc"], "start"),
                             ' font-weight="bold"' if it["bold"] else "",
                             _xml_escape(it["s"])))
        elif it["t"] == "oval":
            partes.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" '
                          'stroke="%s" stroke-width="%.1f"/>'
                          % (it["x"] + dx, it["y"] + dy, it["r"], it["cor"], it["lw"]))
    partes.append("</g></svg>")
    with open(caminho, "w", encoding="utf-8") as fp:
        fp.write("\n".join(partes))
    return caminho


# ============================================================================
#  EXPORTACAO: PDF (escrito na mao, sem bibliotecas)
# ============================================================================

# larguras aproximadas da Helvetica (em milesimos de em), so pra alinhar texto
_LARG_PADRAO = 556
_LARGURAS = {" ": 278, "!": 278, '"': 355, "'": 191, "(": 333, ")": 333, ",": 278,
             "-": 333, ".": 278, "/": 278, ":": 278, ";": 278, "[": 278, "]": 278,
             "i": 222, "j": 222, "l": 222, "f": 278, "t": 278, "r": 333, "I": 278,
             "m": 833, "w": 722, "M": 833, "W": 944, "A": 667, "B": 667, "C": 722,
             "D": 722, "E": 667, "F": 611, "G": 778, "H": 722, "J": 500, "K": 667,
             "L": 556, "N": 722, "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667,
             "T": 611, "U": 722, "V": 667, "X": 667, "Y": 667, "Z": 611}


def largura_texto(texto, tamanho, negrito=False):
    total = sum(_LARGURAS.get(c, _LARG_PADRAO) for c in str(texto))
    return total / 1000.0 * tamanho * (1.06 if negrito else 1.0)


def _pdf_txt(s):
    """Texto para dentro de um PDF: latin-1 (WinAnsi) com escapes."""
    try:
        b = str(s).encode("cp1252", "replace")
    except Exception:
        b = str(s).encode("latin-1", "replace")
    out = bytearray()
    for c in b:
        if c in (0x28, 0x29, 0x5C):   # ( ) \
            out += b"\\" + bytes([c])
        elif c < 32 or c > 126:
            out += ("\\%03o" % c).encode("ascii")
        else:
            out.append(c)
    return out.decode("ascii")


class PaginaPDF:
    """Acumula operadores de desenho de uma pagina (origem embaixo-esquerda)."""

    def __init__(self, largura, altura):
        self.largura = largura
        self.altura = altura
        self.ops = []

    def _cor(self, cor_hex, traco=True):
        cor_hex = (cor_hex or "#000000").lstrip("#")
        if len(cor_hex) == 3:
            cor_hex = "".join(c * 2 for c in cor_hex)
        r, g, b = (int(cor_hex[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        self.ops.append("%.3f %.3f %.3f %s" % (r, g, b, "RG" if traco else "rg"))

    def retangulo(self, x, y, w, h, fill=None, stroke=None, lw=1.0):
        if fill:
            self._cor(fill, False)
        if stroke:
            self._cor(stroke, True)
            self.ops.append("%.2f w" % lw)
        self.ops.append("%.2f %.2f %.2f %.2f re" % (x, y, w, h))
        self.ops.append("B" if (fill and stroke) else ("f" if fill else "S"))

    def polilinha(self, pts, cor="#000000", lw=1.0, dash=None):
        if len(pts) < 2:
            return
        self._cor(cor, True)
        self.ops.append("%.2f w" % lw)
        self.ops.append("[%s] 0 d" % (" ".join("%.1f" % d for d in dash) if dash else ""))
        self.ops.append("%.2f %.2f m" % pts[0])
        for p in pts[1:]:
            self.ops.append("%.2f %.2f l" % p)
        self.ops.append("S")
        self.ops.append("[] 0 d")

    def texto(self, x, y, s, tamanho=9.0, cor="#000000", negrito=False):
        self._cor(cor, False)
        self.ops.append("BT /%s %.2f Tf %.2f %.2f Td (%s) Tj ET"
                        % ("F2" if negrito else "F1", tamanho, x, y, _pdf_txt(s)))

    def circulo(self, x, y, r, cor="#000000", lw=1.0):
        k = 0.5523 * r
        self._cor(cor, True)
        self.ops.append("%.2f w" % lw)
        self.ops.append("%.2f %.2f m" % (x + r, y))
        for (c1, c2, p) in (((x + r, y + k), (x + k, y + r), (x, y + r)),
                            ((x - k, y + r), (x - r, y + k), (x - r, y)),
                            ((x - r, y - k), (x - k, y - r), (x, y - r)),
                            ((x + k, y - r), (x + r, y - k), (x + r, y))):
            self.ops.append("%.2f %.2f %.2f %.2f %.2f %.2f c" % (c1 + c2 + p))
        self.ops.append("S")

    def conteudo(self):
        return "\n".join(self.ops).encode("latin-1", "replace")


def escrever_pdf(paginas, caminho):
    """Monta um PDF valido a partir de uma lista de PaginaPDF."""
    objetos = []          # lista de bytes (objeto 1..N)

    def add(corpo):
        objetos.append(corpo)
        return len(objetos)

    fonte_normal = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                       b"/Encoding /WinAnsiEncoding >>")
    fonte_negrito = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                        b"/Encoding /WinAnsiEncoding >>")
    id_paginas = add(b"")          # reservado: preenchido no fim
    ids_pagina = []
    for pag in paginas:
        fluxo = pag.conteudo()
        id_conteudo = add(b"<< /Length %d >>\nstream\n" % len(fluxo) + fluxo
                          + b"\nendstream")
        id_pag = add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                      "/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                      "/Contents %d 0 R >>"
                      % (id_paginas, pag.largura, pag.altura, fonte_normal,
                         fonte_negrito, id_conteudo)).encode("ascii"))
        ids_pagina.append(id_pag)
    objetos[id_paginas - 1] = ("<< /Type /Pages /Count %d /Kids [%s] >>"
                               % (len(ids_pagina),
                                  " ".join("%d 0 R" % i for i in ids_pagina))
                               ).encode("ascii")
    id_catalogo = add(("<< /Type /Catalog /Pages %d 0 R >>" % id_paginas).encode("ascii"))

    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posicoes = []
    for i, corpo in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n" % (len(objetos) + 1)
    saida += b"0000000000 65535 f \n"
    for pos in posicoes:
        saida += b"%010d 00000 n \n" % pos
    saida += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objetos) + 1, id_catalogo, inicio_xref))
    with open(caminho, "wb") as fp:
        fp.write(bytes(saida))
    return caminho


def pagina_do_diagrama(cena, largura_pag=None, altura_pag=None, margem=24.0):
    """Desenha a cena numa pagina de PDF, escolhendo um tamanho proporcional
    ao diagrama (redes grandes viram paginas grandes, texto nunca espremido)."""
    if largura_pag is None:
        largura_pag = min(max(cena.largura + 2 * margem, 420.0), 5000.0)
    if altura_pag is None:
        altura_pag = min(max(cena.altura + 2 * margem, 300.0), 5000.0)
    escala = min((largura_pag - 2 * margem) / cena.largura,
                 (altura_pag - 2 * margem) / cena.altura)
    pag = PaginaPDF(largura_pag, altura_pag)
    tema = cena.tema or TEMA
    pag.retangulo(0, 0, largura_pag, altura_pag, fill=tema["fundo"])

    def conv(x, y):
        return (margem + (x - cena.minx) * escala,
                altura_pag - margem - (y - cena.miny) * escala)

    for it in cena.itens:
        if it["t"] == "ret":
            x, y = conv(it["x"], it["y"] + it["h"])
            pag.retangulo(x, y, it["w"] * escala, it["h"] * escala,
                          it["fill"], it["outline"], max(it["lw"] * escala, 0.3))
        elif it["t"] == "linha":
            pag.polilinha([conv(*p) for p in it["pts"]], it["cor"],
                          max(it["lw"] * escala, 0.3),
                          [d * escala for d in it["dash"]] if it["dash"] else None)
        elif it["t"] == "texto":
            tam = it["tam"] * escala
            larg = largura_texto(it["s"], tam, it["bold"])
            x, y = conv(it["x"], it["y"])
            if it["anc"] == "e":
                x -= larg
            elif it["anc"] == "center":
                x -= larg / 2.0
            pag.texto(x, y - tam * 0.36, it["s"], tam, it["cor"], it["bold"])
        elif it["t"] == "oval":
            x, y = conv(it["x"], it["y"])
            pag.circulo(x, y, it["r"] * escala, it["cor"], max(it["lw"] * escala, 0.4))
    return pag


# ============================================================================
#  RELATORIOS: porta a porta, pendencias e capacidade
# ============================================================================

COLUNAS = [("Equipamento", 34, 26), ("Modulo", 170, 24), ("Porta", 300, 7),
           ("Conector", 336, 11), ("Status", 396, 9), ("Conectado a", 452, 34),
           ("Rotulo", 660, 16)]
LARG_A4 = 842.0   # A4 paisagem
ALT_A4 = 595.0


def linhas_relatorio(rede):
    """Uma linha por porta; portas duplex com 2 fusoes rendem 2 linhas."""
    saida = []
    for eq in sorted(rede.equipamentos.values(), key=lambda e: (e.tipo, e.nome)):
        grupos = [(m.id, m, sorted(m.portas)) for m in eq.modulos.values()]
        for mod_id, mod, numeros in grupos:
            for num in numeros:
                c, pol = rede.conector_da_porta(eq.id, mod_id, num)
                duplex = rede.tipo_gbic_porta(eq.id, mod_id, num) == DUPLEX
                gbic = (texto_conector(c, pol, duplex).replace(" duplex", " dx") if c
                        else "fusao")
                base = [eq.nome + " (%s)" % eq.tipo,
                        mod.nome if mod else "-",
                        rede.rotulo_porta(eq.id, mod_id, num), gbic,
                        rede.porta_status(eq.id, mod_id, num)]
                fusoes = rede.fusoes_na_porta(eq.id, mod_id, num)
                if not fusoes:
                    saida.append(base + ["-", "-"])
                    continue
                for f in sorted(fusoes, key=lambda x: x.id):
                    destino = rede.nome_porta(*f.outra_ponta(eq.id, mod_id, num))
                    saida.append(base + [destino, f.rotulo or "-"])
    return saida


def _pagina_tabela(titulo, colunas, linhas, numero, total, tema=None):
    """Monta uma pagina A4 paisagem com uma tabela simples (altura da linha
    se ajusta ao texto, nomes longos quebram em varias linhas)."""
    t = tema or TEMA
    pag = PaginaPDF(LARG_A4, ALT_A4)
    pag.retangulo(0, 0, LARG_A4, ALT_A4, fill=t["fundo"])
    pag.texto(34, ALT_A4 - 34, titulo, 13.0, t["titulo_cor"], True)
    if total > 1:
        pag.texto(LARG_A4 - 120, ALT_A4 - 34, "pagina %d/%d" % (numero, total),
                  9.0, t["tipo_cor"])
    y = ALT_A4 - 60
    for nome_coluna, x, _ in colunas:
        pag.texto(x, y, nome_coluna, 8.5, t["titulo_cor"], True)
    pag.polilinha([(30, y - 5), (LARG_A4 - 30, y - 5)], t["titulo_regua"], 0.8)
    y -= 18
    usadas = 0
    for dados in linhas:
        blocos = [textwrap.wrap(str(v), larg) or ["-"]
                  for (_, _, larg), v in zip(colunas, dados)]
        alt = max(len(b) for b in blocos) * 9.0 + 3.0
        if y - alt < 30:
            break
        for (_, x, _), bloco in zip(colunas, blocos):
            for i, parte in enumerate(bloco):
                pag.texto(x, y - i * 9.0, parte, 7.5, t["porta_cor"])
        y -= alt
        pag.polilinha([(30, y + 3), (LARG_A4 - 30, y + 3)], t["modulo_regua"], 0.4)
        usadas += 1
    return pag, usadas


def _paginas_de_tabela(titulo, colunas, linhas, tema=None):
    """Quebra a tabela em quantas paginas forem necessarias."""
    t = tema or TEMA
    if not linhas:
        pag, _ = _pagina_tabela(titulo, colunas, [], 1, 1, t)
        pag.texto(34, ALT_A4 - 90, "(nada a listar)", 9.0, t["tipo_cor"])
        return [pag]
    paginas, indice = [], 0
    while indice < len(linhas):
        pag, usadas = _pagina_tabela(titulo, colunas, linhas[indice:],
                                     len(paginas) + 1, 0, t)
        if usadas == 0:              # protecao: linha gigante nao trava o loop
            usadas = 1
        paginas.append(pag)
        indice += usadas
    # agora que sabemos o total, reescreve o "pagina X/Y"
    total = len(paginas)
    if total > 1:
        for i, pag in enumerate(paginas, start=1):
            pag.texto(LARG_A4 - 120, ALT_A4 - 34, "pagina %d/%d" % (i, total),
                      9.0, t["tipo_cor"])
    return paginas


def paginas_do_relatorio(rede, tema=None):
    return _paginas_de_tabela("Relatorio de portas e fusoes", COLUNAS,
                              linhas_relatorio(rede), tema)


COLUNAS_PENDENCIAS = [("Gravidade", 34, 10), ("Tipo", 110, 22), ("Item", 250, 40),
                      ("Detalhe", 500, 55)]
COLUNAS_CAPACIDADE = [("Equipamento", 34, 34), ("Tipo", 260, 12), ("Total", 340, 8),
                      ("Em uso", 400, 8), ("Livres", 460, 8), ("Ocupacao", 520, 10)]


def linhas_pendencias(rede):
    return [[p["gravidade"].upper(), p["tipo"], p["item"], p["detalhe"]]
            for p in pendencias(rede)]


def linhas_capacidade(rede):
    return [[c["equipamento"], c["tipo"], str(c["total"]), str(c["usadas"]),
             str(c["livres"]), "%.1f%%" % c["ocupacao"]] for c in resumo_capacidade(rede)]


def exportar_relatorio_pdf(rede, cena, caminho, incluir_extras=True, tema=None):
    """PDF completo: diagrama + portas/fusoes + pendencias + capacidade."""
    t = tema or (cena.tema if cena is not None else TEMA)
    paginas = [pagina_do_diagrama(cena)] if cena is not None else []
    paginas += paginas_do_relatorio(rede, t)
    if incluir_extras:
        paginas += _paginas_de_tabela("Pendencias (o que merece atencao)",
                                      COLUNAS_PENDENCIAS, linhas_pendencias(rede), t)
        paginas += _paginas_de_tabela("Capacidade: portas livres por equipamento",
                                      COLUNAS_CAPACIDADE, linhas_capacidade(rede), t)
    return escrever_pdf(paginas, caminho)


def _escrever_csv(caminho, cabecalho, linhas):
    """CSV com ';' e BOM (utf-8-sig), do jeito que o Excel em portugues espera."""
    import csv
    with open(caminho, "w", newline="", encoding="utf-8-sig") as fp:
        escritor = csv.writer(fp, delimiter=";")
        escritor.writerow(cabecalho)
        for linha in linhas:
            escritor.writerow(linha)
    return caminho


def exportar_relatorio_csv(rede, caminho):
    """Mesma tabela do PDF, mas em CSV pra abrir no Excel e poder filtrar,
    ordenar e contar."""
    return _escrever_csv(caminho, [t for t, _, _ in COLUNAS], linhas_relatorio(rede))


def exportar_pendencias_csv(rede, caminho):
    return _escrever_csv(caminho, [t for t, _, _ in COLUNAS_PENDENCIAS],
                         linhas_pendencias(rede))


def exportar_capacidade_csv(rede, caminho):
    return _escrever_csv(caminho, [t for t, _, _ in COLUNAS_CAPACIDADE],
                         linhas_capacidade(rede))


# ============================================================================
#  PASTA DE CONFIGURACAO / RECUPERACAO AUTOMATICA
# ============================================================================

def pasta_do_programa():
    """Pasta onde o programa guarda o autosave (nao mistura com os arquivos
    do usuario). No Windows: %APPDATA%\\WaspFiber."""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.expanduser("~")
    pasta = os.path.join(base, "WaspFiber")
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError:
        pasta = os.path.expanduser("~")
    return pasta


def pastas_antigas():
    """Onde as versoes anteriores (Nix, FTTX Diagramador) guardavam as coisas
    - so pra nao perder uma recuperacao pendente de quem ja usava."""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.expanduser("~")
    return [os.path.join(base, "Nix"), os.path.join(base, "FTTX-Diagramador")]


def caminho_autosave():
    return os.path.join(pasta_do_programa(), "recuperacao.json")


def caminhos_autosave_antigos():
    return [os.path.join(p, "recuperacao.json") for p in pastas_antigas()]


def gravar_autosave(rede, caminho_original=None, documento=None):
    """Grava uma copia de seguranca a cada alteracao. Falha em silencio: e
    protecao, nao pode atrapalhar o trabalho."""
    try:
        dados = rede.to_dict()
        dados["_autosave"] = {"quando": time.strftime("%d/%m/%Y %H:%M:%S"),
                              "arquivo": caminho_original or "", "documento": documento}
        with open(caminho_autosave(), "w", encoding="utf-8") as fp:
            json.dump(dados, fp, ensure_ascii=False)
        return True
    except Exception:
        return False


def ler_autosave():
    """Devolve (rede, info) do autosave, ou (None, None) se nao houver.
    Tambem olha a pasta da versao antiga (FTTX Diagramador), pra quem
    atualizou com trabalho pendente."""
    caminho = caminho_autosave()
    for antigo in caminhos_autosave_antigos():
        if not os.path.exists(caminho) and os.path.exists(antigo):
            caminho = antigo
    if not os.path.exists(caminho):
        return None, None
    try:
        with open(caminho, "r", encoding="utf-8") as fp:
            dados = json.load(fp)
        info = dados.pop("_autosave", {})
        rede = Rede.from_dict(dados)
        if not rede.equipamentos:
            return None, None
        return rede, info
    except Exception:
        return None, None


def apagar_autosave():
    for caminho in [caminho_autosave()] + caminhos_autosave_antigos():
        try:
            if os.path.exists(caminho):
                os.remove(caminho)
        except OSError:
            pass


# ============================================================================
#  REDE DE EXEMPLO
# ============================================================================

def rede_exemplo():
    """Rede de demonstracao, do jeito que ela existe no campo: a OLT liga por
    cordao na FRENTE do DIO; na TRASEIRA do DIO as fibras do cabo C1 estao
    fundidas na bandeja; a outra ponta do C1 chega na CTO e alimenta o
    splitter 1x8, cujas saidas descem pelo cabo de distribuicao C2 ate os
    clientes. Tem ainda switch com grupamentos, portas duplex (TX/RX), um
    jumper entre DIOs e um loop interno."""
    r = Rede()
    olt = r.add_equipamento("OLT-Central-01", "OLT", id_="OLT-01")
    gpon = olt.add_placa("GPON-16", "Placa 1 - GPON16")
    ctrl = olt.add_placa("CONTROLE", "Placa 2 - Controle")
    sw = r.add_equipamento("SWITCH-AGREG-01", "SWITCH", id_="SW-01")
    sfp = sw.add_grupamento("SFP", 24, "Grupamento SFP+ (24p)")
    qsfp = sw.add_grupamento("QSFP", 6, "Grupamento QSFP (6p)")
    dio1 = r.add_equipamento("DIO-Centro-01", TIPO_DIO, 24, id_="DIO-01")
    dio2 = r.add_equipamento("DIO-Centro-02", TIPO_DIO, 12, id_="DIO-02")
    c1 = r.add_equipamento("C1 Rua das Flores", TIPO_CABO, 24, id_="CABO-01")
    c2 = r.add_equipamento("C2 Distribuicao", TIPO_CABO, 12, id_="CABO-02")
    cto = r.add_equipamento("CTO-Bairro-01", TIPO_ACOMODADOR, id_="ACOMO-01")
    sp = cto.add_splitter("1x8", "Splitter Rua das Flores")

    # central: OLT -> frente do DIO (cordoes)
    r.criar_fusao(olt.id, gpon.id, 5, dio1.id, "F", 5, "PON 4")
    r.criar_fusao(olt.id, gpon.id, 3, dio1.id, "F", 3, "PON 2")
    r.definir_potencia(olt.id, gpon.id, 5, 5.0)      # SFP GPON classe C+: +5 dBm
    r.definir_potencia(olt.id, gpon.id, 3, 5.0)
    r.criar_fusao(olt.id, ctrl.id, 1, dio1.id, "F", 10, "Uplink mgmt")
    r.definir_tipo_porta(olt.id, ctrl.id, 2, DUPLEX)
    r.criar_fusao(olt.id, ctrl.id, 2, dio1.id, "F", 11, "TX")
    r.criar_fusao(olt.id, ctrl.id, 2, dio2.id, "F", 5, "RX")
    r.criar_fusao(sw.id, sfp.id, 1, dio2.id, "F", 1, "Uplink OLT")
    r.definir_tipo_porta(sw.id, qsfp.id, 1, DUPLEX)
    r.criar_fusao(sw.id, qsfp.id, 1, dio2.id, "F", 2, "TX")
    r.criar_fusao(sw.id, qsfp.id, 1, dio2.id, "F", 3, "RX")
    r.criar_fusao(dio1.id, "F", 1, dio2.id, "F", 8, "Jumper")
    r.criar_fusao(sw.id, sfp.id, 2, sw.id, sfp.id, 3, "Loop")

    # bandeja: as 12 primeiras fibras do C1 fundidas na traseira do DIO-01
    for n in range(1, 13):
        r.criar_fusao(dio1.id, "T", n, c1.id, "B", n)
    # campo: fibra 5 do C1 alimenta o splitter; saidas descem pelo C2
    r.criar_fusao(c1.id, "A", 5, cto.id, sp.id, 1)
    r.criar_fusao(cto.id, sp.id, 2, c2.id, "B", 1, "Cliente A")
    r.criar_fusao(cto.id, sp.id, 3, c2.id, "B", 2, "Cliente B")
    r.organizar_layout()
    r.definir_local({"tipo": "POP", "nome": "POP Centro", "cidade": "Sao Paulo - SP",
                     "endereco": "Praca da Se", "lat": -23.550520, "lon": -46.633308,
                     "obs": "Rede de exemplo"})
    return r


# ============================================================================
#  INTERFACE: DIALOGOS
# ============================================================================

class DialogoBase(simpledialog.Dialog):
    """Base dos dialogos: botoes no tema (o simpledialog usa os botoes
    classicos, brancos no Windows), 'Cancelar' em portugues e a barra de
    titulo escura pedida ANTES da janela aparecer."""

    def protocol(self, nome=None, funcao=None):
        # o simpledialog chama isto logo antes de mostrar a janela: e a hora
        # certa de escurecer a barra de titulo (depois, o Windows ignora)
        if nome == "WM_DELETE_WINDOW":
            nix_ui.barra_de_titulo_escura(self)
        return super().protocol(nome, funcao)

    def buttonbox(self):
        caixa = ttk.Frame(self, padding=(10, 4, 10, 10))
        ttk.Button(caixa, text="OK", width=12, style="Acento.TButton",
                   command=self.ok).pack(side="left", padx=4)
        ttk.Button(caixa, text="Cancelar", width=12,
                   command=self.cancel).pack(side="left", padx=4)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        caixa.pack()


class DialogTexto(DialogoBase):
    """Pergunta de uma linha no tema (no lugar do simpledialog.askstring,
    que vem com botoes classicos e 'Cancel' em ingles)."""

    def __init__(self, parent, titulo, pergunta, inicial=""):
        self.pergunta, self.inicial, self.resultado = pergunta, inicial, None
        super().__init__(parent, titulo)

    def body(self, master):
        ttk.Label(master, text=self.pergunta, wraplength=380, justify="left").pack(
            anchor="w", pady=(4, 6))
        self.e_texto = ttk.Entry(master, width=48)
        self.e_texto.insert(0, self.inicial or "")
        self.e_texto.pack(fill="x")
        self.e_texto.select_range(0, "end")
        return self.e_texto

    def apply(self):
        self.resultado = self.e_texto.get()


def perguntar_texto(titulo, pergunta, parent=None, initialvalue=""):
    """Devolve o texto digitado, ou None se cancelar."""
    return DialogTexto(parent, titulo, pergunta, initialvalue).resultado


class DialogNovoEquipamento(DialogoBase):
    def __init__(self, parent):
        self.resultado = None
        super().__init__(parent, "Novo equipamento")

    def body(self, master):
        ttk.Label(master, text="Tipo:").grid(row=0, column=0, sticky="w", pady=3)
        self.var_tipo = tk.StringVar(value=TIPO_DIO)
        cb = ttk.Combobox(master, textvariable=self.var_tipo, width=22,
                          state="readonly", values=TODOS_TIPOS)
        cb.grid(row=0, column=1, pady=3)
        cb.bind("<<ComboboxSelected>>", self._muda_tipo)

        ttk.Label(master, text="Nome:").grid(row=1, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=25)
        self.e_nome.grid(row=1, column=1, pady=3)

        self.lbl_qtd = ttk.Label(master, text="Portas do DIO:")
        self.lbl_qtd.grid(row=2, column=0, sticky="w", pady=3)
        self.e_qtd = ttk.Entry(master, width=25)
        self.e_qtd.insert(0, "24")
        self.e_qtd.grid(row=2, column=1, pady=3)

        self.lbl_fpt = ttk.Label(master, text="Fibras por tubo:")
        self.lbl_fpt.grid(row=3, column=0, sticky="w", pady=3)
        self.e_fpt = ttk.Entry(master, width=25)
        self.e_fpt.insert(0, str(FIBRAS_POR_TUBO_PADRAO))
        self.e_fpt.grid(row=3, column=1, pady=3)

        self.dica = ttk.Label(master, text="", style="Fraco.TLabel", wraplength=300)
        self.dica.grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="w")
        self._muda_tipo()
        return self.e_nome

    def _muda_tipo(self, _=None):
        tipo = self.var_tipo.get()
        self.e_fpt.config(state="normal" if tipo == TIPO_CABO else "disabled")
        if tipo == TIPO_DIO:
            self.lbl_qtd.config(text="Portas do DIO:")
            self.e_qtd.config(state="normal")
            self.dica.config(text="Cada porta tem dois lados: a traseira (fusao com a "
                                  "fibra do cabo, na bandeja) e a frente (conector do "
                                  "cordao). Bandejas de 24 portas.")
        elif tipo == TIPO_CABO:
            self.lbl_qtd.config(text="Fibras (FO):")
            self.e_qtd.config(state="normal")
            self.dica.config(text="Fibras e tubos no codigo de cores ABNT (verde, "
                                  "amarelo, branco, azul...). Cada fibra tem a ponta A "
                                  "e a ponta B.")
        elif tipo == TIPO_ACOMODADOR:
            self.lbl_qtd.config(text="Splitters 1x8 iniciais:")
            self.e_qtd.config(state="normal")
            self.dica.config(text="Cada splitter nasce com 1 entrada (ENT) e as saidas "
                                  "(S1, S2...). Da pra adicionar/trocar depois.")
        else:
            self.lbl_qtd.config(text="(portas vem dos modulos)")
            self.e_qtd.config(state="disabled")
            self.dica.config(text="As portas de OLT/SWITCH/RB vem das placas e "
                                  "grupamentos, cadastrados depois de criar o equipamento.")

    def validate(self):
        tipo = self.var_tipo.get()
        if not self.e_nome.get().strip():
            messagebox.showwarning("Falta o nome", "Informe um nome para o equipamento.")
            return False
        if tipo == TIPO_CABO:
            try:
                if not 1 <= int(self.e_fpt.get()) <= 24:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Fibras por tubo", "Informe de 1 a 24 fibras por tubo.")
                return False
        if tipo in (TIPO_DIO, TIPO_CABO, TIPO_ACOMODADOR):
            try:
                qtd = int(self.e_qtd.get())
            except ValueError:
                messagebox.showwarning("Quantidade invalida", "Informe um numero inteiro.")
                return False
            if qtd < 1:
                messagebox.showwarning("Quantidade invalida", "Precisa ser pelo menos 1.")
                return False
            if tipo == TIPO_ACOMODADOR and qtd > MAX_SPLITTERS_POR_ACOMODADOR:
                messagebox.showwarning("Muitos splitters",
                                       "Maximo de %d splitters." % MAX_SPLITTERS_POR_ACOMODADOR)
                return False
        return True

    def apply(self):
        tipo = self.var_tipo.get()
        qtd = int(self.e_qtd.get()) if tipo in (TIPO_DIO, TIPO_CABO, TIPO_ACOMODADOR) else 0
        fpt = int(self.e_fpt.get()) if tipo == TIPO_CABO else None
        self.resultado = (self.e_nome.get().strip(), tipo, qtd, fpt)


class DialogLote(DialogoBase):
    """Cria varios equipamentos iguais de uma vez (v2.2)."""

    def __init__(self, parent):
        self.resultado = None
        super().__init__(parent, "Criar varios equipamentos")

    def body(self, master):
        ttk.Label(master, text="Tipo:").grid(row=0, column=0, sticky="w", pady=3)
        self.var_tipo = tk.StringVar(value=TIPO_DIO)
        cb = ttk.Combobox(master, textvariable=self.var_tipo, width=24,
                          state="readonly", values=TODOS_TIPOS)
        cb.grid(row=0, column=1, pady=3, sticky="w")
        cb.bind("<<ComboboxSelected>>", self._atualizar)

        ttk.Label(master, text="Nome base:").grid(row=1, column=0, sticky="w", pady=3)
        self.e_base = ttk.Entry(master, width=27)
        self.e_base.insert(0, "DIO-##")
        self.e_base.grid(row=1, column=1, pady=3, sticky="w")
        self.e_base.bind("<KeyRelease>", self._atualizar)

        ttk.Label(master, text="Quantidade:").grid(row=2, column=0, sticky="w", pady=3)
        self.e_qtd = ttk.Entry(master, width=27)
        self.e_qtd.insert(0, "12")
        self.e_qtd.grid(row=2, column=1, pady=3, sticky="w")
        self.e_qtd.bind("<KeyRelease>", self._atualizar)

        ttk.Label(master, text="Comecar em:").grid(row=3, column=0, sticky="w", pady=3)
        self.e_inicio = ttk.Entry(master, width=27)
        self.e_inicio.insert(0, "1")
        self.e_inicio.grid(row=3, column=1, pady=3, sticky="w")
        self.e_inicio.bind("<KeyRelease>", self._atualizar)

        self.lbl_portas = ttk.Label(master, text="Portas de cada DIO:")
        self.lbl_portas.grid(row=4, column=0, sticky="w", pady=3)
        self.e_portas = ttk.Entry(master, width=27)
        self.e_portas.insert(0, "24")
        self.e_portas.grid(row=4, column=1, pady=3, sticky="w")

        self.lbl_mod = ttk.Label(master, text="Modulos em cada um:")
        self.lbl_mod.grid(row=5, column=0, sticky="w", pady=3)
        quadro_mod = ttk.Frame(master)
        quadro_mod.grid(row=5, column=1, pady=3, sticky="w")
        self.e_qtd_mod = ttk.Entry(quadro_mod, width=5)
        self.e_qtd_mod.insert(0, "1")
        self.e_qtd_mod.pack(side="left")
        self.var_tipo_mod = tk.StringVar()
        self.cb_tipo_mod = ttk.Combobox(quadro_mod, textvariable=self.var_tipo_mod,
                                        width=16, state="readonly")
        self.cb_tipo_mod.pack(side="left", padx=4)

        self.previa = ttk.Label(master, text="", style="Fraco.TLabel", wraplength=330)
        self.previa.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(master, text="Use ## no nome base pra dizer onde entra o numero "
                               "(DIO-## vira DIO-01, DIO-02...).",
                  style="Fraco.TLabel", wraplength=330).grid(row=7, column=0, columnspan=2,
                                                          sticky="w", pady=(4, 0))
        self._atualizar()
        return self.e_base

    def _atualizar(self, _=None):
        tipo = self.var_tipo.get()
        if tipo in TIPOS_COM_LADOS:
            self.lbl_portas.config(text="Portas de cada DIO:" if tipo == TIPO_DIO
                                   else "Fibras de cada cabo:")
            self.e_portas.config(state="normal")
            self.cb_tipo_mod["values"] = []
            self.cb_tipo_mod.set("")
            self.cb_tipo_mod.config(state="disabled")
            self.e_qtd_mod.config(state="disabled")
            self.lbl_mod.config(text="(%s nao tem modulos)" % tipo)
        else:
            self.e_qtd_mod.config(state="normal")
            self.cb_tipo_mod.config(state="readonly")
            self.lbl_mod.config(text="Modulos em cada um:")
            if tipo == "OLT":
                valores = list(TIPOS_PLACA_OLT)
                self.e_portas.config(state="disabled")
                self.lbl_portas.config(text="(portas vem das placas)")
            elif tipo == TIPO_ACOMODADOR:
                valores = list(TIPOS_SPLITTER)
                self.e_portas.config(state="disabled")
                self.lbl_portas.config(text="(portas vem dos splitters)")
            else:
                valores = list(TIPOS_GRUPO_ATIVO)
                self.e_portas.config(state="normal")
                self.lbl_portas.config(text="Portas de cada grupamento:")
            self.cb_tipo_mod["values"] = valores
            if self.var_tipo_mod.get() not in valores:
                self.cb_tipo_mod.current(0)
        try:
            qtd = int(self.e_qtd.get())
            inicio = int(self.e_inicio.get())
            base = self.e_base.get()
            nomes = [formatar_nome_numerado(base, inicio + i) for i in range(min(qtd, 3))]
            texto = ", ".join(nomes)
            if qtd > 3:
                texto += ", ...  ate  " + formatar_nome_numerado(base, inicio + qtd - 1)
            self.previa.config(text="Vai criar %d: %s" % (qtd, texto))
        except ValueError:
            self.previa.config(text="Preencha quantidade e inicio com numeros.")

    def validate(self):
        try:
            qtd = int(self.e_qtd.get())
            int(self.e_inicio.get())
        except ValueError:
            messagebox.showwarning("Numero invalido",
                                   "Quantidade e inicio precisam ser numeros inteiros.")
            return False
        if not 1 <= qtd <= 200:
            messagebox.showwarning("Quantidade invalida", "Informe de 1 a 200.")
            return False
        if not self.e_base.get().strip():
            messagebox.showwarning("Falta o nome", "Informe um nome base.")
            return False
        if str(self.e_portas.cget("state")) == "normal":
            try:
                if int(self.e_portas.get()) < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Portas invalidas", "Informe um numero maior que zero.")
                return False
        if str(self.e_qtd_mod.cget("state")) == "normal":
            try:
                if int(self.e_qtd_mod.get()) < 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Modulos invalidos", "Informe um numero (0 ou mais).")
                return False
        return True

    def apply(self):
        tipo = self.var_tipo.get()
        portas = (int(self.e_portas.get())
                  if str(self.e_portas.cget("state")) == "normal" else 0)
        qtd_mod = (int(self.e_qtd_mod.get())
                   if str(self.e_qtd_mod.cget("state")) == "normal" else 0)
        self.resultado = {"nome_base": self.e_base.get().strip(), "tipo": tipo,
                          "quantidade": int(self.e_qtd.get()),
                          "inicio": int(self.e_inicio.get()), "num_portas": portas,
                          "tipo_modulo": self.var_tipo_mod.get() or None,
                          "qtd_modulos": qtd_mod}


class DialogNovoModulo(DialogoBase):
    def __init__(self, parent, equipamento):
        self.eq = equipamento
        self.resultado = None
        super().__init__(parent, "Nova placa / grupamento / splitter")

    def body(self, master):
        if self.eq.tipo == "OLT":
            valores, rotulo = list(TIPOS_PLACA_OLT), "Tipo de placa:"
        elif self.eq.tipo == TIPO_ACOMODADOR:
            valores, rotulo = list(TIPOS_SPLITTER), "Tipo de splitter:"
        else:
            valores, rotulo = list(TIPOS_GRUPO_ATIVO), "Tipo de grupamento:"
        ttk.Label(master, text=rotulo).grid(row=0, column=0, sticky="w", pady=3)
        self.var_tipo = tk.StringVar(value=valores[0])
        cb = ttk.Combobox(master, textvariable=self.var_tipo, values=valores,
                          state="readonly", width=22)
        cb.grid(row=0, column=1, pady=3)
        cb.bind("<<ComboboxSelected>>", self._atualiza)

        ttk.Label(master, text="Nome (opcional):").grid(row=1, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=25)
        self.e_nome.grid(row=1, column=1, pady=3)

        self.lbl_qtd = ttk.Label(master, text="Portas:")
        self.lbl_qtd.grid(row=2, column=0, sticky="w", pady=3)
        self.e_qtd = ttk.Entry(master, width=25)
        self.e_qtd.insert(0, "24")
        self.e_qtd.grid(row=2, column=1, pady=3)

        self.info = ttk.Label(master, text="", style="Fraco.TLabel", wraplength=300)
        self.info.grid(row=3, column=0, columnspan=2, pady=(8, 0), sticky="w")
        self._atualiza()
        return cb

    def _atualiza(self, _=None):
        tipo = self.var_tipo.get()
        if self.eq.tipo == "OLT":
            info = TIPOS_PLACA_OLT[tipo]
            self.e_qtd.config(state="disabled")
            self.info.config(text="%s - %d portas, GBIC %s."
                             % (info["rotulo"], info["portas"],
                                info["gbic_fixo"] or "livre (simplex ou duplex)"))
        elif self.eq.tipo == TIPO_ACOMODADOR:
            self.e_qtd.config(state="disabled")
            self.info.config(text="Splitter %s: porta 1 = entrada (ENT), %d saidas."
                             % (tipo, TIPOS_SPLITTER[tipo]))
        else:
            self.e_qtd.config(state="normal")
            self.info.config(text="%s - informe quantas portas. GBIC livre por porta."
                             % TIPOS_GRUPO_ATIVO[tipo])

    def validate(self):
        if self.eq.tipo in ("SWITCH", "RB"):
            try:
                if int(self.e_qtd.get()) < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Quantidade invalida",
                                       "Informe um numero inteiro maior que zero.")
                return False
        return True

    def apply(self):
        qtd = int(self.e_qtd.get()) if self.eq.tipo in ("SWITCH", "RB") else 0
        self.resultado = (self.var_tipo.get(), self.e_nome.get().strip() or None, qtd)


OPCOES_CONECTOR = ["(manter como esta)", "SC/APC", "SC/UPC", "LC/APC", "LC/UPC"]


def _campo_conector_lote(master, linha, rotulo="Conector de todas as portas:"):
    """Combobox pra trocar o conector de todas as portas de uma vez."""
    ttk.Label(master, text=rotulo).grid(row=linha, column=0, sticky="w", pady=3)
    var = tk.StringVar(value=OPCOES_CONECTOR[0])
    ttk.Combobox(master, textvariable=var, values=OPCOES_CONECTOR, state="readonly",
                 width=27).grid(row=linha, column=1, pady=3)
    ttk.Label(master, text="Porta duplex continua LC (muda so o polimento).",
              style="Fraco.TLabel").grid(row=linha + 1, column=0, columnspan=2, sticky="w")
    return var


def _ler_conector_lote(var):
    """'SC/APC' -> ('SC', 'APC'); '(manter...)' -> None."""
    valor = var.get() if var is not None else ""
    return tuple(valor.split("/")) if "/" in valor else None


class DialogEditarEquipamento(DialogoBase):
    def __init__(self, parent, equipamento):
        self.eq = equipamento
        self.resultado = None
        super().__init__(parent, "Editar equipamento")

    def body(self, master):
        ttk.Label(master, text="Nome:").grid(row=0, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=30)
        self.e_nome.insert(0, self.eq.nome)
        self.e_nome.grid(row=0, column=1, pady=3)

        ttk.Label(master, text="ID:").grid(row=1, column=0, sticky="w", pady=3)
        self.e_id = ttk.Entry(master, width=30)
        self.e_id.insert(0, self.eq.id)
        self.e_id.grid(row=1, column=1, pady=3)

        if self.eq.tem_lados():
            ttk.Label(master, text="Fibras:" if self.eq.is_cabo() else "Portas:").grid(row=2, column=0, sticky="w", pady=3)
            self.e_qtd = ttk.Entry(master, width=30)
            self.e_qtd.insert(0, str(self.eq.num_portas))
            self.e_qtd.grid(row=2, column=1, pady=3)
        else:
            self.e_qtd = None
            ttk.Label(master, text="(%d modulo(s), %d portas)"
                      % (len(self.eq.modulos), self.eq.total_portas()),
                      style="Fraco.TLabel").grid(row=2, column=0, columnspan=2,
                                              sticky="w", pady=3)
        self.var_conector = (_campo_conector_lote(master, 3, "Conector da frente (todas):")
                             if self.eq.is_dio() else None)
        return self.e_nome

    def validate(self):
        if self.e_qtd is not None:
            try:
                int(self.e_qtd.get())
            except ValueError:
                messagebox.showwarning("Quantidade invalida", "Informe um numero inteiro.")
                return False
        return True

    def apply(self):
        self.resultado = (self.e_nome.get().strip() or None,
                          self.e_id.get().strip() or None,
                          int(self.e_qtd.get()) if self.e_qtd is not None else None)
        self.conector_lote = _ler_conector_lote(self.var_conector)


class DialogEditarModulo(DialogoBase):
    def __init__(self, parent, equipamento, modulo):
        self.eq, self.mod = equipamento, modulo
        self.resultado = None
        super().__init__(parent, "Editar modulo")

    def body(self, master):
        if self.eq.tipo == "OLT":
            valores = list(TIPOS_PLACA_OLT)
        elif self.eq.tipo == TIPO_ACOMODADOR:
            valores = list(TIPOS_SPLITTER)
        else:
            valores = list(TIPOS_GRUPO_ATIVO)
        ttk.Label(master, text="Nome:").grid(row=0, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=30)
        self.e_nome.insert(0, self.mod.nome)
        self.e_nome.grid(row=0, column=1, pady=3)

        ttk.Label(master, text="Tipo:").grid(row=1, column=0, sticky="w", pady=3)
        self.var_tipo = tk.StringVar(value=self.mod.tipo if self.mod.tipo in valores
                                     else valores[0])
        ttk.Combobox(master, textvariable=self.var_tipo, values=valores,
                     state="readonly", width=27).grid(row=1, column=1, pady=3)

        if self.eq.tipo in ("SWITCH", "RB"):
            ttk.Label(master, text="Portas:").grid(row=2, column=0, sticky="w", pady=3)
            self.e_qtd = ttk.Entry(master, width=30)
            self.e_qtd.insert(0, str(self.mod.num_portas))
            self.e_qtd.grid(row=2, column=1, pady=3)
        else:
            self.e_qtd = None
        ttk.Label(master, text="Reduzir portas so funciona se as portas removidas "
                              "estiverem livres.", style="Fraco.TLabel",
                  wraplength=320).grid(row=3, column=0, columnspan=2, pady=(8, 0))
        self.var_conector = _campo_conector_lote(master, 4)
        return self.e_nome

    def validate(self):
        if self.e_qtd is not None:
            try:
                int(self.e_qtd.get())
            except ValueError:
                messagebox.showwarning("Quantidade invalida", "Informe um numero inteiro.")
                return False
        return True

    def apply(self):
        self.resultado = (self.var_tipo.get(),
                          int(self.e_qtd.get()) if self.e_qtd is not None else None,
                          self.e_nome.get().strip() or None)
        self.conector_lote = _ler_conector_lote(self.var_conector)


class DialogPorta(DialogoBase):
    """Edita o GBIC da porta e gerencia as fusoes dela."""

    def __init__(self, parent, rede, eq_id, modulo_id, porta_num, ao_mudar,
                 ao_rastrear=None):
        self.rede = rede
        self.eq_id, self.modulo_id, self.porta_num = eq_id, modulo_id, porta_num
        self.ao_mudar = ao_mudar
        self.ao_rastrear = ao_rastrear
        super().__init__(parent, rede.nome_porta(eq_id, modulo_id, porta_num)[:60])

    def body(self, master):
        eq = self.rede.equipamentos[self.eq_id]
        ttk.Label(master, text=self.rede.nome_porta(self.eq_id, self.modulo_id,
                                                   self.porta_num),
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                           sticky="w", pady=(0, 6))
        linha = 1
        self.var_gbic = None
        if not eq.is_cabo():
            # conector (SC/LC), polimento (APC/UPC) e simplex/duplex
            mod_conector = "F" if eq.is_dio() else self.modulo_id
            mod = eq.modulos[mod_conector]
            porta = mod.portas[self.porta_num]
            titulo = ("Adaptador da porta %d (frente e traseira)" % self.porta_num
                      if eq.is_dio() else "Conector")
            quadro = ttk.LabelFrame(master, text=titulo)
            quadro.grid(row=linha, column=0, columnspan=3, sticky="ew", pady=4)
            self.var_gbic = tk.StringVar(value=porta.tipo_gbic)
            self.var_conector = tk.StringVar(value=porta.conector or "SC")
            self.var_polimento = tk.StringVar(value=porta.polimento or "UPC")
            fixo = mod.gbic_fixo
            ttk.Label(quadro, text="Tipo:").grid(row=0, column=0, sticky="w", padx=(4, 8))
            ttk.Radiobutton(quadro, text="Simplex", value=SIMPLEX, variable=self.var_gbic,
                            state="disabled" if fixo else "normal",
                            command=self._salvar_gbic).grid(row=0, column=1, sticky="w")
            ttk.Radiobutton(quadro, text="Duplex (sempre LC)", value=DUPLEX,
                            variable=self.var_gbic, state="disabled" if fixo else "normal",
                            command=self._salvar_gbic).grid(row=0, column=2, sticky="w")
            ttk.Label(quadro, text="Conector:").grid(row=1, column=0, sticky="w", padx=(4, 8))
            self.rb_sc = ttk.Radiobutton(quadro, text="SC", value="SC",
                                         variable=self.var_conector,
                                         command=self._salvar_conector)
            self.rb_sc.grid(row=1, column=1, sticky="w")
            ttk.Radiobutton(quadro, text="LC", value="LC", variable=self.var_conector,
                            command=self._salvar_conector).grid(row=1, column=2, sticky="w")
            ttk.Label(quadro, text="Polimento:").grid(row=2, column=0, sticky="w", padx=(4, 8))
            ttk.Radiobutton(quadro, text="APC (verde)", value="APC",
                            variable=self.var_polimento,
                            command=self._salvar_conector).grid(row=2, column=1, sticky="w")
            ttk.Radiobutton(quadro, text="UPC (azul)", value="UPC",
                            variable=self.var_polimento,
                            command=self._salvar_conector).grid(row=2, column=2, sticky="w")
            if fixo:
                ttk.Label(quadro, text="Simplex/duplex travado em %s pelo tipo do modulo."
                          % fixo, style="Fraco.TLabel").grid(row=3, column=0, columnspan=3,
                                                          sticky="w", padx=4)
            self._ajustar_sc()
            linha += 1
        if eq.tipo in TIPOS_ATIVOS:
            quadro_p = ttk.LabelFrame(master, text="Potencia de saida (dBm)")
            quadro_p.grid(row=linha, column=0, columnspan=3, sticky="ew", pady=4)
            self.e_pot = ttk.Entry(quadro_p, width=10)
            atual = self.rede.potencia_da_porta(self.eq_id, self.modulo_id, self.porta_num)
            if atual is not None:
                self.e_pot.insert(0, ("%g" % atual).replace(".", ","))
            self.e_pot.pack(side="left", padx=4, pady=4)
            ttk.Button(quadro_p, text="Aplicar", command=self._salvar_potencia).pack(
                side="left", padx=4)
            ttk.Label(quadro_p, text="vazio = sem potencia. O caminho aparece marcado no "
                                     "diagrama.", style="Fraco.TLabel").pack(side="left", padx=6)
            linha += 1

        quadro_f = ttk.LabelFrame(master, text="Fusoes desta porta")
        quadro_f.grid(row=linha, column=0, columnspan=3, sticky="ew", pady=4)
        self.lista = tk.Listbox(quadro_f, height=4, width=60)
        self.lista.pack(side="left", padx=(4, 0), pady=4)
        ttk.Button(quadro_f, text="Remover", command=self._remover).pack(side="left", padx=6)
        linha += 1

        quadro_n = ttk.LabelFrame(master, text="Conectar esta porta a...")
        quadro_n.grid(row=linha, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Label(quadro_n, text="Equipamento:").grid(row=0, column=0, sticky="w")
        self.cb_eq = ttk.Combobox(quadro_n, width=32, state="readonly")
        self.cb_eq.grid(row=0, column=1, pady=2)
        self.cb_eq.bind("<<ComboboxSelected>>", self._muda_eq)
        ttk.Label(quadro_n, text="Modulo:").grid(row=1, column=0, sticky="w")
        self.cb_mod = ttk.Combobox(quadro_n, width=32, state="readonly")
        self.cb_mod.grid(row=1, column=1, pady=2)
        self.cb_mod.bind("<<ComboboxSelected>>", self._muda_mod)
        ttk.Label(quadro_n, text="Porta:").grid(row=2, column=0, sticky="w")
        self.cb_porta = ttk.Combobox(quadro_n, width=32, state="readonly")
        self.cb_porta.grid(row=2, column=1, pady=2)
        ttk.Label(quadro_n, text="Rotulo:").grid(row=3, column=0, sticky="w")
        self.e_rotulo = ttk.Entry(quadro_n, width=35)
        self.e_rotulo.grid(row=3, column=1, pady=2)
        ttk.Button(quadro_n, text="Adicionar fusao",
                   command=self._adicionar).grid(row=4, column=1, sticky="e", pady=4)

        self._eqs = sorted(self.rede.equipamentos.values(), key=lambda e: e.nome)
        self.cb_eq["values"] = ["%s [%s]" % (e.nome, e.id) for e in self._eqs]
        if self._eqs:
            self.cb_eq.current(0)
            self._muda_eq()
        self._atualizar_lista()
        return self.lista

    def _eq_destino(self):
        i = self.cb_eq.current()
        return self._eqs[i] if 0 <= i < len(self._eqs) else None

    def _muda_eq(self, _=None):
        eq = self._eq_destino()
        if eq is None:
            return
        if True:
            self._mods = list(eq.modulos.values())
            self.cb_mod["values"] = [m.nome for m in self._mods]
            if self._mods:
                self.cb_mod.current(0)
            else:
                self.cb_mod.set("")
        self._muda_mod()

    def _muda_mod(self, _=None):
        eq = self._eq_destino()
        if eq is None:
            return
        if True:
            i = self.cb_mod.current()
            if not self._mods or i < 0:
                self.cb_porta["values"] = []
                self._numeros_destino, self._mod_id_destino = [], None
                return
            mod = self._mods[i]
            numeros, mod_id = sorted(mod.portas), mod.id
        opcoes = []
        for n in numeros:
            usadas = len(self.rede.fusoes_na_porta(eq.id, mod_id, n))
            limite = self.rede.limite_porta(eq.id, mod_id, n)
            opcoes.append("%s (%d/%d)%s" % (self.rede.rotulo_porta(eq.id, mod_id, n),
                                            usadas, limite,
                                            "  [cheia]" if usadas >= limite else ""))
        self._numeros_destino, self._mod_id_destino = numeros, mod_id
        self.cb_porta["values"] = opcoes
        if opcoes:
            self.cb_porta.current(0)

    def _atualizar_lista(self):
        self.lista.delete(0, tk.END)
        self._fusoes = self.rede.fusoes_na_porta(self.eq_id, self.modulo_id, self.porta_num)
        limite = self.rede.limite_porta(self.eq_id, self.modulo_id, self.porta_num)
        for f in self._fusoes:
            destino = self.rede.nome_porta(*f.outra_ponta(self.eq_id, self.modulo_id,
                                                          self.porta_num))
            self.lista.insert(tk.END, "%s -> %s%s"
                              % (f.id, destino,
                                 ("  [%s]" % f.rotulo) if f.rotulo else ""))
        if not self._fusoes:
            self.lista.insert(tk.END, "(nenhuma fusao - limite desta porta: %d)" % limite)

    def _salvar_potencia(self):
        texto = self.e_pot.get().strip().replace(",", ".").replace("+", "").replace("dBm", "")
        try:
            self.rede.definir_potencia(self.eq_id, self.modulo_id, self.porta_num,
                                       float(texto) if texto.strip() else None)
        except ValueError as erro:
            messagebox.showerror("Potencia invalida", str(erro) if "faixa" in str(erro)
                                 else "Digite so o numero em dBm, ex.: 5 ou -1,5.")
            return
        self.ao_mudar()

    def _porta_conector(self):
        eq = self.rede.equipamentos[self.eq_id]
        return eq.modulos["F" if eq.is_dio() else self.modulo_id].portas[self.porta_num]

    def _ajustar_sc(self):
        """Duplex e sempre LC: com duplex marcado, SC fica desabilitado."""
        duplex = self.var_gbic.get() == DUPLEX
        self.rb_sc.configure(state="disabled" if duplex else "normal")
        if duplex:
            self.var_conector.set("LC")

    def _salvar_gbic(self):
        try:
            self.rede.definir_tipo_porta(self.eq_id, self.modulo_id, self.porta_num,
                                         self.var_gbic.get())
        except ValueError as erro:
            messagebox.showerror("Nao foi possivel mudar simplex/duplex", str(erro))
            self.var_gbic.set(self._porta_conector().tipo_gbic)
        self._ajustar_sc()
        self._atualizar_lista()
        self.ao_mudar()

    def _salvar_conector(self):
        try:
            self.rede.definir_conector(self.eq_id, self.modulo_id, self.porta_num,
                                       self.var_conector.get(), self.var_polimento.get())
        except ValueError as erro:
            messagebox.showerror("Nao foi possivel mudar o conector", str(erro))
            porta = self._porta_conector()
            self.var_conector.set(porta.conector or "SC")
            self.var_polimento.set(porta.polimento or "UPC")
        self.ao_mudar()

    def _adicionar(self):
        eq = self._eq_destino()
        i = self.cb_porta.current()
        if eq is None or i < 0 or not self._numeros_destino:
            messagebox.showwarning("Escolha a porta",
                                   "Selecione o equipamento, o modulo e a porta.")
            return
        try:
            self.rede.criar_fusao(self.eq_id, self.modulo_id, self.porta_num,
                                  eq.id, self._mod_id_destino,
                                  self._numeros_destino[i], self.e_rotulo.get().strip())
        except ValueError as erro:
            messagebox.showerror("Nao foi possivel conectar", str(erro))
            return
        self.e_rotulo.delete(0, tk.END)
        self._atualizar_lista()
        self._muda_mod()
        self.ao_mudar()

    def _remover(self):
        selecao = self.lista.curselection()
        if not selecao or not self._fusoes or selecao[0] >= len(self._fusoes):
            return
        self.rede.remover_fusao(self._fusoes[selecao[0]].id)
        self._atualizar_lista()
        self._muda_mod()
        self.ao_mudar()

    def buttonbox(self):
        caixa = ttk.Frame(self)
        if self.ao_rastrear is not None:
            ttk.Button(caixa, text="Rastrear caminho da fibra",
                       command=self._rastrear).pack(side="left", padx=4, pady=6)
        ttk.Button(caixa, text="Fechar", command=self.ok).pack(side="left", padx=4, pady=6)
        caixa.pack()
        self.bind("<Return>", lambda _: self.ok())
        self.bind("<Escape>", lambda _: self.ok())

    def _rastrear(self):
        chave = (self.eq_id, self.modulo_id, self.porta_num)
        self.ok()
        self.ao_rastrear(chave)


def em_segundo_plano(janela, funcao, ao_terminar):
    """Roda funcao() numa thread (internet nao pode travar a janela) e chama
    ao_terminar(resultado, erro) de volta na thread da interface."""
    import threading
    caixa = {}

    def rodar():
        try:
            caixa["resultado"] = funcao()
        except Exception as erro:
            caixa["erro"] = erro

    fio = threading.Thread(target=rodar, daemon=True)
    fio.start()

    def conferir():
        if fio.is_alive():
            janela.after(80, conferir)
            return
        try:
            if janela.winfo_exists():
                ao_terminar(caixa.get("resultado"), caixa.get("erro"))
        except tk.TclError:
            pass
    janela.after(80, conferir)


class DialogLocal(DialogoBase):
    """Localizacao do diagrama (B0.34): o diagrama pertence a um local do
    campo - POP, caixa de emenda ou CTO. Ficha do local a esquerda e o mapa a
    direita: clique no mapa marca o ponto; colar a coordenada (ou o link do
    Google Maps) tambem marca. Google Maps / Earth abrem no navegador."""

    def __init__(self, parent, local, baixador=None):
        self.local = mapa.normalizar_local(local)
        self.baixador = baixador
        self.resultado = None
        self._resultados_busca = []
        super().__init__(parent, "Localizacao do diagrama")

    # ---------------- montagem ----------------
    def body(self, master):
        t = TEMA
        ficha = ttk.Frame(master)
        ficha.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        linha = 0

        def rotulo(texto):
            nonlocal linha
            ttk.Label(ficha, text=texto).grid(row=linha, column=0, sticky="w", pady=(6, 1))
            linha += 1

        rotulo("Este diagrama e de um:")
        self.var_tipo = tk.StringVar(value=mapa.ROTULO_TIPO_LOCAL.get(self.local["tipo"], ""))
        ttk.Combobox(ficha, textvariable=self.var_tipo, state="readonly", width=34,
                     values=[r for _, r in mapa.TIPOS_LOCAL]).grid(row=linha, column=0,
                                                                   sticky="we")
        linha += 1

        rotulo("Nome / identificacao do local:")
        self.e_nome = ttk.Entry(ficha, width=36)
        self.e_nome.insert(0, self.local["nome"])
        self.e_nome.grid(row=linha, column=0, sticky="we")
        linha += 1

        rotulo("Endereco (Enter procura no mapa):")
        caixa_end = ttk.Frame(ficha)
        caixa_end.grid(row=linha, column=0, sticky="we")
        self.e_endereco = ttk.Entry(caixa_end, width=27)
        self.e_endereco.insert(0, self.local["endereco"])
        self.e_endereco.pack(side="left", fill="x", expand=True)
        self.e_endereco.bind("<Return>", lambda _e: (self._buscar(), "break")[1])
        ttk.Button(caixa_end, text="Procurar", width=9,
                   command=self._buscar).pack(side="left", padx=(4, 0))
        linha += 1
        # resultados da busca (aparece so quando ha mais de um)
        self.lista_busca = tk.Listbox(ficha, height=4, activestyle="none", bd=0,
                                      highlightthickness=1, bg=t["ui_painel"],
                                      fg=t["ui_texto"], selectbackground=t["ui_acento"],
                                      selectforeground=t["ui_acento_texto"],
                                      highlightbackground=t["ui_borda"])
        self.lista_busca.bind("<<ListboxSelect>>", self._escolher_busca)
        self._linha_lista = linha
        linha += 1

        rotulo("Cidade:")
        self.e_cidade = ttk.Entry(ficha, width=36)
        self.e_cidade.insert(0, self.local["cidade"])
        self.e_cidade.grid(row=linha, column=0, sticky="we")
        linha += 1

        rotulo("Coordenada (cole do Google Maps ou Earth):")
        self.var_coord = tk.StringVar(
            value="" if self.local["lat"] is None
            else mapa.formatar_coordenada(self.local["lat"], self.local["lon"]))
        self.e_coord = ttk.Entry(ficha, width=36, textvariable=self.var_coord)
        self.e_coord.grid(row=linha, column=0, sticky="we")
        self.e_coord.bind("<Return>", lambda _e: (self._ler_coord(centralizar=True), "break")[1])
        self.var_coord.trace_add("write", lambda *_: self._ler_coord())
        linha += 1
        self.lbl_coord = ttk.Label(ficha, text="", style="Fraco.TLabel", wraplength=280)
        self.lbl_coord.grid(row=linha, column=0, sticky="w", pady=(2, 0))
        linha += 1

        rotulo("Observacao:")
        self.t_obs = tk.Text(ficha, width=36, height=3, wrap="word", bd=0,
                             bg=t["ui_painel"], fg=t["ui_texto"], insertbackground=t["ui_texto"],
                             highlightthickness=1, highlightbackground=t["ui_borda"],
                             font=("TkDefaultFont", 9))
        self.t_obs.insert("1.0", self.local["obs"])
        self.t_obs.grid(row=linha, column=0, sticky="we")
        linha += 1

        acoes = ttk.Frame(ficha)
        acoes.grid(row=linha, column=0, sticky="we", pady=(12, 0))
        self.bt_maps = ttk.Button(acoes, text="Abrir no Google Maps",
                                  command=lambda: self._abrir(mapa.link_google_maps))
        self.bt_maps.pack(fill="x", pady=2)
        self.bt_earth = ttk.Button(acoes, text="Abrir no Google Earth",
                                   command=lambda: self._abrir(mapa.link_google_earth))
        self.bt_earth.pack(fill="x", pady=2)
        self.bt_endereco = ttk.Button(acoes, text="Preencher endereco pelo ponto",
                                      command=self._endereco_do_ponto)
        self.bt_endereco.pack(fill="x", pady=2)
        ttk.Button(acoes, text="Limpar coordenada", command=self._limpar).pack(fill="x", pady=2)
        linha += 1
        self.lbl_status = ttk.Label(ficha, text="", style="Fraco.TLabel", wraplength=280)
        self.lbl_status.grid(row=linha, column=0, sticky="w", pady=(8, 0))

        # ----- mapa -----
        lado = ttk.Frame(master)
        lado.grid(row=0, column=1, sticky="nsew")
        topo = ttk.Frame(lado)
        topo.pack(fill="x", pady=(0, 6))
        ttk.Label(topo, text="Clique no mapa para marcar o local. Arraste move, "
                             "roda do mouse da zoom.", style="Fraco.TLabel").pack(side="left")
        self.var_fonte = tk.StringVar(value=mapa.fonte_inicial())
        self.quadro_fontes = ttk.Frame(topo)
        self.quadro_fontes.pack(side="right")
        self._montar_fontes()
        centro = None if self.local["lat"] is None else (self.local["lat"], self.local["lon"])
        self.mapa = mapa.MapaWidget(lado, t, largura=680, altura=500, centro=centro,
                                    ao_marcar=self._marcado_no_mapa, baixador=self.baixador,
                                    fonte=self.var_fonte.get())
        self.mapa.pack(fill="both", expand=True)
        if centro:
            self.mapa.marcar(*centro)
        self._ler_coord()
        return self.e_nome

    # ---------------- fonte do mapa ----------------
    def _montar_fontes(self):
        for chave in mapa.fontes_disponiveis():
            ttk.Radiobutton(self.quadro_fontes, text=mapa.FONTES[chave]["rotulo"], value=chave,
                            variable=self.var_fonte, command=self._escolher_fonte
                            ).pack(side="left", padx=(8, 0))

    def _escolher_fonte(self):
        self.mapa.trocar_fonte(self.var_fonte.get())
        mapa.gravar_config({"fonte": self.var_fonte.get()})

    # ---------------- coordenada ----------------
    def _ponto(self):
        return mapa.ler_coordenada(self.var_coord.get())

    def _ler_coord(self, centralizar=False):
        texto = self.var_coord.get().strip()
        ponto = mapa.ler_coordenada(texto)
        if ponto:
            self.lbl_coord.configure(text=mapa.formatar_dms(*ponto))
            if hasattr(self, "mapa"):
                self.mapa.marcar(ponto[0], ponto[1], centralizar=centralizar
                                 or self.mapa.marcador is None)
        else:
            self.lbl_coord.configure(text="Coordenada nao reconhecida." if texto else
                                     "Sem coordenada: clique no mapa ou cole aqui.")
        estado = "normal" if ponto else "disabled"
        for botao in ("bt_maps", "bt_earth", "bt_endereco"):
            if hasattr(self, botao):
                getattr(self, botao).configure(state=estado)
        return ponto

    def _marcado_no_mapa(self, lat, lon):
        self.var_coord.set(mapa.formatar_coordenada(lat, lon))

    def _limpar(self):
        self.var_coord.set("")
        self.mapa.marcar(None, None)

    # ---------------- google ----------------
    def _abrir(self, gerar_link):
        ponto = self._ponto()
        if not ponto:
            return
        import webbrowser
        webbrowser.open(gerar_link(*ponto))

    # ---------------- busca de endereco ----------------
    def _buscar(self):
        texto = self.e_endereco.get().strip()
        cidade = self.e_cidade.get().strip()
        if not texto:
            self.lbl_status.configure(text="Digite o endereco para procurar.")
            return
        consulta = texto if (not cidade or cidade.lower() in texto.lower()) \
            else "%s, %s" % (texto, cidade)
        self.lbl_status.configure(text="Procurando \"%s\"..." % consulta)
        em_segundo_plano(self, lambda: mapa.buscar_endereco(consulta), self._busca_pronta)

    def _busca_pronta(self, resultados, erro):
        self.lista_busca.grid_forget()
        if erro:
            self.lbl_status.configure(text="Nao consegui procurar (sem internet?). "
                                           "Cole a coordenada ou clique no mapa.")
            return
        self._resultados_busca = resultados or []
        if not self._resultados_busca:
            self.lbl_status.configure(text="Nenhum lugar encontrado com esse endereco.")
            return
        _, lat, lon = self._resultados_busca[0]
        self.mapa.marcar(lat, lon, centralizar=True, avisar=True)
        if len(self._resultados_busca) > 1:
            self.lista_busca.delete(0, "end")
            for descricao, _, _ in self._resultados_busca:
                self.lista_busca.insert("end", descricao)
            self.lista_busca.grid(row=self._linha_lista, column=0, sticky="we", pady=(4, 0))
            self.lista_busca.selection_set(0)
            self.lbl_status.configure(text="%d lugares encontrados - escolha na lista. "
                                           "Confira o ponto no mapa." % len(self._resultados_busca))
        else:
            self.lbl_status.configure(text="Achei. Confira o ponto no mapa (clique pra ajustar).")

    def _escolher_busca(self, _evento=None):
        escolha = self.lista_busca.curselection()
        if escolha and escolha[0] < len(self._resultados_busca):
            _, lat, lon = self._resultados_busca[escolha[0]]
            self.mapa.marcar(lat, lon, centralizar=True, avisar=True)

    def _endereco_do_ponto(self):
        ponto = self._ponto()
        if not ponto:
            return
        self.lbl_status.configure(text="Buscando o endereco do ponto...")

        def pronto(resultado, erro):
            if erro or not resultado:
                self.lbl_status.configure(text="Nao consegui achar o endereco (sem internet?).")
                return
            endereco, cidade = resultado
            if endereco:
                self.e_endereco.delete(0, "end")
                self.e_endereco.insert(0, endereco)
            if cidade:
                self.e_cidade.delete(0, "end")
                self.e_cidade.insert(0, cidade)
            self.lbl_status.configure(text="Endereco preenchido. Confira o numero.")
        em_segundo_plano(self, lambda: mapa.endereco_do_ponto(*ponto), pronto)

    # ---------------- ok ----------------
    def validate(self):
        texto = self.var_coord.get().strip()
        if texto and not self._ponto():
            messagebox.showwarning("Coordenada", "Nao entendi a coordenada.\n\nExemplos que "
                                   "funcionam:\n-23.550520, -46.633308\n"
                                   "23°33'01.9\"S 46°38'00.0\"W\nou o link do Google Maps.",
                                   parent=self)
            return False
        return True

    def apply(self):
        rotulo_para_tipo = {r: k for k, r in mapa.TIPOS_LOCAL}
        ponto = self._ponto()
        self.resultado = mapa.normalizar_local({
            "tipo": rotulo_para_tipo.get(self.var_tipo.get(), ""),
            "nome": self.e_nome.get(),
            "endereco": self.e_endereco.get(),
            "cidade": self.e_cidade.get(),
            "lat": ponto[0] if ponto else None,
            "lon": ponto[1] if ponto else None,
            "obs": self.t_obs.get("1.0", "end"),
        })


class DialogFormato(DialogoBase):
    """Escolhe o formato antes de salvar."""

    def __init__(self, parent, formatos, titulo="Escolher formato"):
        self.formatos = formatos
        self.resultado = None
        super().__init__(parent, titulo)

    def body(self, master):
        ttk.Label(master, text="Formato do arquivo:").pack(anchor="w", pady=(0, 4))
        self.var = tk.StringVar(value=self.formatos[0][0])
        for chave, descricao in self.formatos:
            ttk.Radiobutton(master, text=descricao, value=chave,
                            variable=self.var).pack(anchor="w")

    def apply(self):
        self.resultado = self.var.get()


class DialogRastreio(DialogoBase):
    """Mostra por onde o sinal passa a partir de uma porta, com a perda
    acumulada e a potencia estimada em cada ponta."""

    def __init__(self, parent, rede, chave, ao_destacar=None):
        self.rede = rede
        self.chave = chave
        self.ao_destacar = ao_destacar
        self.arvore = None
        super().__init__(parent, "Rastrear caminho da fibra")

    def body(self, master):
        ttk.Label(master, text=self.rede.nome_porta(*self.chave),
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, columnspan=4,
                                                           sticky="w", pady=(0, 6))
        ttk.Label(master, text="Potencia de saida (dBm):").grid(row=1, column=0, sticky="w")
        self.e_potencia = ttk.Entry(master, width=8)
        # usa a potencia da propria porta da OLT, se tiver; senao 5 dBm
        pot = self.rede.potencia_da_porta(*self.chave)
        self.e_potencia.insert(0, "%.1f" % (pot if pot is not None else 5.0))
        self.e_potencia.grid(row=1, column=1, sticky="w")
        ttk.Button(master, text="Recalcular",
                   command=self._calcular).grid(row=1, column=2, sticky="w", padx=4)
        ttk.Button(master, text="Destacar no diagrama",
                   command=self._destacar).grid(row=1, column=3, sticky="e")

        self.texto = tk.Text(master, width=96, height=22, wrap="none",
                             font=("Courier New", 9), bg=TEMA["ui_campo"],
                             fg=TEMA["ui_texto"], insertbackground=TEMA["ui_texto"],
                             highlightthickness=0, borderwidth=0, padx=8, pady=6)
        self.texto.grid(row=2, column=0, columnspan=4, sticky="nsew", pady=(8, 0))
        barra = ttk.Scrollbar(master, orient="vertical", command=self.texto.yview)
        barra.grid(row=2, column=4, sticky="ns", pady=(8, 0))
        barra_h = ttk.Scrollbar(master, orient="horizontal", command=self.texto.xview)
        barra_h.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.texto.configure(yscrollcommand=barra.set, xscrollcommand=barra_h.set)
        self.texto.tag_configure("ok", foreground=TEMA["ui_ok"])
        self.texto.tag_configure("alerta", foreground=TEMA["ui_aviso"])
        self.texto.tag_configure("critico", foreground=TEMA["ui_erro"])
        self.texto.tag_configure("cabec", font=("Courier New", 9, "bold"))

        self.resumo = ttk.Label(master, text="", style="Fraco.TLabel", wraplength=760)
        self.resumo.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self._calcular()
        return self.e_potencia

    def _potencia_informada(self):
        try:
            return float(self.e_potencia.get().replace(",", "."))
        except ValueError:
            return None

    def _calcular(self):
        potencia = self._potencia_informada()
        self.arvore = rastrear_caminho(self.rede, self.chave, potencia)
        linhas = rastreio_em_texto(self.arvore, mostrar_potencia=potencia is not None)
        self.texto.configure(state="normal")
        self.texto.delete("1.0", tk.END)
        self.texto.insert(tk.END, "CAMINHO DO SINAL\n", "cabec")
        for linha in linhas:
            etiqueta = ()
            if "=> " in linha and "dBm" in linha:
                try:
                    valor = float(linha.rsplit("=> ", 1)[1].split(" dBm")[0])
                    etiqueta = (classificar_potencia(valor),)
                except (ValueError, IndexError):
                    etiqueta = ()
            self.texto.insert(tk.END, linha + "\n", etiqueta)

        pontas = pontas_finais(self.arvore)
        self.texto.insert(tk.END, "\nPONTAS FINAIS (%d)\n" % len(pontas), "cabec")
        for ponta in sorted(pontas, key=lambda n: -n["perda_acum"]):
            situacao = ("%.2f dBm" % ponta["potencia"]) if ponta["potencia"] is not None \
                else "perda %.2f dB" % ponta["perda_acum"]
            self.texto.insert(tk.END, "  %s  ->  %s\n" % (ponta["nome"], situacao),
                              (classificar_potencia(ponta["potencia"]),)
                              if ponta["potencia"] is not None else ())
        self.texto.configure(state="disabled")

        pior = max((p["perda_acum"] for p in pontas), default=0.0)
        aviso = ("Nao inclui a atenuacao do cabo (0,35 dB/km tipico): este cadastro nao "
                 "guarda a metragem da rota. Perdas usadas: fusao %.1f dB, splitter %s."
                 % (PERDA_FUSAO_DB,
                    ", ".join("%s=%.1f" % (k, v) for k, v in PERDA_SPLITTER_DB.items())))
        self.resumo.config(text="%d ponta(s) final(is) | pior perda: %.2f dB\n%s"
                           % (len(pontas), pior, aviso))

    def _destacar(self):
        if self.ao_destacar and self.arvore:
            self.ao_destacar(fusoes_do_rastreio(self.arvore))

    def buttonbox(self):
        caixa = ttk.Frame(self)
        ttk.Button(caixa, text="Copiar texto", command=self._copiar).pack(side="left", padx=4)
        ttk.Button(caixa, text="Fechar", command=self.ok).pack(side="left", padx=4)
        caixa.pack(pady=6)
        self.bind("<Escape>", lambda _: self.ok())

    def _copiar(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.texto.get("1.0", tk.END))
            messagebox.showinfo("Copiado", "Caminho copiado para a area de transferencia.")
        except tk.TclError:
            pass


class DialogBusca(tk.Toplevel):
    """Busca por equipamento, modulo, rotulo de fusao (nome do cliente) ou
    numero de porta - e leva o diagrama ate o achado (v2.2).
    Fica aberta enquanto voce navega pelos resultados."""

    ICONES = {"equipamento": "[EQ]", "modulo": "[MOD]", "fusao": "[FUS]", "porta": "[PORTA]"}

    def __init__(self, parent, rede, ao_escolher):
        super().__init__(parent)
        self.rede = rede
        self.ao_escolher = ao_escolher
        self.achados = []
        self.title("Buscar na rede")
        self.geometry("760x440")
        self.configure(bg=TEMA["ui_fundo"])
        self.transient(parent)

        topo = ttk.Frame(self, padding=8)
        topo.pack(fill="x")
        ttk.Label(topo, text="Procurar:").pack(side="left")
        self.e_termo = ttk.Entry(topo, width=40)
        self.e_termo.pack(side="left", padx=6)
        self.e_termo.bind("<KeyRelease>", lambda _: self._procurar())
        self.e_termo.bind("<Return>", lambda _: self._abrir_primeiro())
        self.e_termo.bind("<Down>", lambda _: self.lista.focus_set())
        ttk.Button(topo, text="Buscar", command=self._procurar).pack(side="left")
        ttk.Button(topo, text="Fechar", command=self.destroy).pack(side="right")

        ttk.Label(self, text="Digite parte do nome do equipamento, do modulo, do rotulo "
                             "da fusao (nome do cliente) ou o numero da porta. "
                             "Clique num resultado pra ir ate ele no diagrama.",
                  style="Fraco.TLabel", wraplength=700).pack(anchor="w", padx=12)

        quadro = ttk.Frame(self, padding=8)
        quadro.pack(fill="both", expand=True)
        self.lista = ttk.Treeview(quadro, columns=("tipo", "item", "detalhe"),
                                  show="headings", height=14)
        self.lista.heading("tipo", text="Tipo")
        self.lista.heading("item", text="Item")
        self.lista.heading("detalhe", text="Detalhe")
        self.lista.column("tipo", width=70, stretch=False)
        self.lista.column("item", width=250)
        self.lista.column("detalhe", width=350)
        self.lista.pack(side="left", fill="both", expand=True)
        barra = ttk.Scrollbar(quadro, orient="vertical", command=self.lista.yview)
        barra.pack(side="right", fill="y")
        self.lista.configure(yscrollcommand=barra.set)
        self.lista.bind("<<TreeviewSelect>>", lambda _: self._abrir_selecionado())
        self.lista.bind("<Return>", lambda _: self._abrir_selecionado())

        self.status = ttk.Label(self, text="", style="Fraco.TLabel",
                                padding=(12, 0, 12, 10))
        self.status.pack(anchor="w")
        self.e_termo.focus_set()
        self.bind("<Escape>", lambda _: self.destroy())

    def _procurar(self):
        termo = self.e_termo.get()
        self.achados = buscar(self.rede, termo)
        self.lista.delete(*self.lista.get_children())
        for i, achado in enumerate(self.achados):
            self.lista.insert("", "end", iid=str(i),
                              values=(self.ICONES.get(achado["tipo"], ""),
                                      achado["titulo"], achado["detalhe"]))
        if not termo.strip():
            self.status.config(text="")
        else:
            self.status.config(text="%d resultado(s) para '%s'."
                               % (len(self.achados), termo.strip()))

    def _abrir_selecionado(self):
        selecao = self.lista.selection()
        if not selecao:
            return
        indice = int(selecao[0])
        if 0 <= indice < len(self.achados):
            self.ao_escolher(self.achados[indice])

    def _abrir_primeiro(self):
        if self.achados:
            self.lista.selection_set("0")
            self.ao_escolher(self.achados[0])


class DialogPendencias(tk.Toplevel):
    """O que merece atencao na rede + quanto ainda cabe de cliente (v2.2)."""

    def __init__(self, parent, rede, ao_escolher, ao_exportar):
        super().__init__(parent)
        self.rede = rede
        self.ao_escolher = ao_escolher
        self.ao_exportar = ao_exportar
        self.itens = []
        self.title("Pendencias e capacidade")
        self.geometry("1000x560")
        self.configure(bg=TEMA["ui_fundo"])
        self.transient(parent)

        abas = ttk.Notebook(self)
        abas.pack(fill="both", expand=True, padx=8, pady=8)

        aba1 = ttk.Frame(abas)
        abas.add(aba1, text="Pendencias")
        ttk.Label(aba1, text="Duplo clique leva ate o item no diagrama.",
                  style="Fraco.TLabel").pack(anchor="w", padx=6, pady=6)
        self.tabela = ttk.Treeview(aba1, columns=("grav", "tipo", "item", "detalhe"),
                                   show="headings")
        for coluna, titulo, largura in (("grav", "Gravidade", 90), ("tipo", "Tipo", 150),
                                        ("item", "Item", 280), ("detalhe", "Detalhe", 400)):
            self.tabela.heading(coluna, text=titulo)
            self.tabela.column(coluna, width=largura)
        self.tabela.pack(fill="both", expand=True, padx=6)
        self.tabela.tag_configure("erro", foreground=TEMA["ui_erro"])
        self.tabela.tag_configure("aviso", foreground=TEMA["ui_aviso"])
        self.tabela.tag_configure("info", foreground=TEMA["ui_texto_fraco"])
        self.tabela.bind("<Double-Button-1>", lambda _: self._abrir())

        aba2 = ttk.Frame(abas)
        abas.add(aba2, text="Capacidade (portas livres)")
        self.tabela_cap = ttk.Treeview(
            aba2, columns=("eq", "tipo", "total", "usadas", "livres", "ocup"),
            show="headings")
        for coluna, titulo, largura in (("eq", "Equipamento", 300), ("tipo", "Tipo", 110),
                                        ("total", "Total", 70), ("usadas", "Em uso", 70),
                                        ("livres", "Livres", 70), ("ocup", "Ocupacao", 90)):
            self.tabela_cap.heading(coluna, text=titulo)
            self.tabela_cap.column(coluna, width=largura)
        self.tabela_cap.pack(fill="both", expand=True, padx=6, pady=6)

        rodape = ttk.Frame(self, padding=(10, 0, 10, 10))
        rodape.pack(fill="x")
        self.resumo = ttk.Label(rodape, text="", style="Fraco.TLabel")
        self.resumo.pack(side="left")
        ttk.Button(rodape, text="Fechar", command=self.destroy).pack(side="right")
        ttk.Button(rodape, text="Exportar CSV",
                   command=self.ao_exportar).pack(side="right", padx=6)
        ttk.Button(rodape, text="Atualizar", command=self.atualizar).pack(side="right")
        self.atualizar()
        self.bind("<Escape>", lambda _: self.destroy())

    def atualizar(self):
        self.itens = pendencias(self.rede)
        self.tabela.delete(*self.tabela.get_children())
        for i, item in enumerate(self.itens):
            self.tabela.insert("", "end", iid=str(i), tags=(item["gravidade"],),
                               values=(item["gravidade"].upper(), item["tipo"],
                                       item["item"], item["detalhe"]))
        self.tabela_cap.delete(*self.tabela_cap.get_children())
        for linha in resumo_capacidade(self.rede):
            self.tabela_cap.insert("", "end",
                                   values=(linha["equipamento"], linha["tipo"],
                                           linha["total"], linha["usadas"],
                                           linha["livres"], "%.1f%%" % linha["ocupacao"]))
        erros = sum(1 for i in self.itens if i["gravidade"] == "erro")
        avisos = sum(1 for i in self.itens if i["gravidade"] == "aviso")
        livres = sum(l["livres"] for l in resumo_capacidade(self.rede))
        self.resumo.config(text="%d erro(s), %d aviso(s), %d item(ns) no total  |  "
                                "%d porta(s) livre(s) na rede"
                           % (erros, avisos, len(self.itens), livres))

    def _abrir(self):
        selecao = self.tabela.selection()
        if not selecao:
            return
        indice = int(selecao[0])
        if 0 <= indice < len(self.itens):
            item = self.itens[indice]
            if item.get("chave"):
                self.ao_escolher({"chave": item["chave"], "eq_id": item["chave"][0]})


# ============================================================================
#  INTERFACE: JANELA PRINCIPAL
# ============================================================================

# ============================================================================
#  TELA INICIAL: CIDADES E DIAGRAMAS (B0.36)
# ============================================================================

ICONE_LOCAL = {"POP": "server", "CEO": "cable", "CTO": "split"}


class DialogNovoDiagrama(DialogoBase):
    """Novo diagrama numa cidade: de qual local ele e (POP, CEO, CTO) e o nome."""

    def __init__(self, parent, cidade):
        self.cidade = cidade
        self.resultado = None
        super().__init__(parent, "Novo diagrama - %s" % cidade["titulo"])

    def body(self, master):
        ttk.Label(master, text="Este diagrama e de um:").grid(row=0, column=0, sticky="w", pady=3)
        self.var_tipo = tk.StringVar(value=mapa.ROTULO_TIPO_LOCAL["CTO"])
        ttk.Combobox(master, textvariable=self.var_tipo, state="readonly", width=28,
                     values=[r for _, r in mapa.TIPOS_LOCAL]).grid(row=0, column=1, pady=3,
                                                                   sticky="w")
        ttk.Label(master, text="Nome / identificacao:").grid(row=1, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=31)
        self.e_nome.grid(row=1, column=1, pady=3, sticky="w")
        self.var_mapa = tk.BooleanVar(value=True)
        ttk.Checkbutton(master, text="Marcar a localizacao no mapa em seguida",
                        variable=self.var_mapa).grid(row=2, column=0, columnspan=2,
                                                     sticky="w", pady=(8, 0))
        ttk.Label(master, text="Ex.: POP Centro, CEO-012, CTO Rua das Flores 03",
                  style="Fraco.TLabel").grid(row=3, column=0, columnspan=2, sticky="w",
                                             pady=(8, 0))
        return self.e_nome

    def validate(self):
        if not self.e_nome.get().strip():
            messagebox.showwarning("Novo diagrama", "Informe o nome do local.", parent=self)
            return False
        return True

    def apply(self):
        tipo = {r: k for k, r in mapa.TIPOS_LOCAL}.get(self.var_tipo.get(), "")
        self.resultado = (tipo, self.e_nome.get().strip(), bool(self.var_mapa.get()))


def misturar(cor_a, cor_b, fracao):
    """Mistura duas cores '#rrggbb' (fracao=0 -> a, 1 -> b)."""
    a = [int(cor_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(cor_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * fracao) for x, y in zip(a, b))


# cor de cada tipo de local (selo na lista e, depois, o pino no mapa)
COR_LOCAL = {"POP": "#b39dfa", "CEO": "#f2b84b", "CTO": "#4dd0e1"}


class Selo(tk.Label):
    """Etiqueta pequena colorida: POP / CEO / CTO."""

    def __init__(self, pai, texto, cor, fundo, fonte):
        super().__init__(pai, text=texto, fg=cor, bg=misturar(fundo, cor, 0.16),
                         font=(fonte, 7, "bold"), padx=6, pady=1)


class LinhaLista(tk.Frame):
    """Linha clicavel das listas da tela inicial. Clique seleciona, duplo
    clique abre.
    estilo 'lista': linha da coluna das cidades (selecionada = barra de cor
    a esquerda); 'cartao': cartao com borda, na area dos diagramas."""

    def __init__(self, pai, tema, icone, titulo, detalhe="", direita="", ao_clicar=None,
                 ao_duplo=None, fonte="TkDefaultFont", estilo="lista", selo=None,
                 fonte_titulo=None):
        self.tema, self.estilo, self.selecionado = tema, estilo, False
        self.nome_icone = icone
        cartao = estilo == "cartao"
        self.cor_base = tema["ui_painel"] if cartao else tema["ui_fundo"]
        super().__init__(pai, bg=self.cor_base, cursor="hand2",
                         highlightthickness=1 if cartao else 0,
                         highlightbackground=tema["ui_borda"], highlightcolor=tema["ui_borda"])
        self.barra = tk.Frame(self, bg=self.cor_base, width=3)
        self.barra.grid(row=0, column=0, rowspan=2, sticky="ns")
        self.img = tk.Label(self, image=nix_ui.icone(icone, "fraco"), bg=self.cor_base)
        self.img.grid(row=0, column=1, rowspan=2, padx=(12 if cartao else 10, 12),
                      pady=12 if cartao else 9, sticky="n")
        linha_titulo = tk.Frame(self, bg=self.cor_base)
        linha_titulo.grid(row=0, column=2, sticky="we", pady=(11 if cartao else 8, 0))
        self.selo = None
        if selo:
            self.selo = Selo(linha_titulo, selo[0], selo[1], self.cor_base, fonte)
            self.selo.pack(side="left", padx=(0, 8))
        self.lbl_titulo = tk.Label(linha_titulo, text=titulo, bg=self.cor_base,
                                   fg=tema["ui_texto"], anchor="w",
                                   font=(fonte_titulo or fonte, 10))
        self.lbl_titulo.pack(side="left")
        self.lbl_detalhe = tk.Label(self, text=detalhe, bg=self.cor_base,
                                    fg=tema["ui_texto_fraco"], anchor="w", font=(fonte, 8))
        self.lbl_detalhe.grid(row=1, column=2, sticky="we", pady=(2, 11 if cartao else 8))
        self.lbl_direita = tk.Label(self, text=direita, bg=self.cor_base,
                                    fg=tema["ui_texto_fraco"], anchor="e", justify="right",
                                    font=(fonte, 8))
        self.lbl_direita.grid(row=0, column=3, rowspan=2, padx=(8, 14))
        self.columnconfigure(2, weight=1)
        self._fundos = (self, self.img, linha_titulo, self.lbl_titulo, self.lbl_detalhe,
                        self.lbl_direita)
        for parte in self._fundos + ((self.selo,) if self.selo else ()):
            parte.bind("<Enter>", lambda _e: self._pintar(True))
            parte.bind("<Leave>", lambda _e: self._pintar(False))
            if ao_clicar:
                parte.bind("<ButtonRelease-1>", lambda _e: ao_clicar())
            if ao_duplo:
                parte.bind("<Double-Button-1>", lambda _e: ao_duplo())

    def _pintar(self, hover=False):
        t = self.tema
        if self.selecionado:
            fundo = misturar(self.cor_base, t["ui_acento"], 0.10)
        elif hover:
            fundo = t["ui_hover"]
        else:
            fundo = self.cor_base
        for parte in self._fundos:
            parte.configure(bg=fundo)
        if self.selo is not None:
            self.selo.configure(bg=misturar(fundo, self.selo.cget("fg"), 0.16))
        self.barra.configure(bg=t["ui_acento"] if self.selecionado else fundo)
        if self.estilo == "cartao":
            self.configure(highlightbackground=t["ui_acento"] if self.selecionado
                           else (t["ui_texto_fraco"] if hover else t["ui_borda"]))
        self.img.configure(image=nix_ui.icone(self.nome_icone,
                                              "acento" if self.selecionado else
                                              ("texto" if hover else "fraco")))

    def marcar(self, sim):
        self.selecionado = sim
        self.lbl_titulo.configure(fg=self.tema["ui_acento"] if sim else self.tema["ui_texto"])
        self._pintar()


class ListaRolavel(tk.Frame):
    """Coluna com rolagem (Canvas + Frame), a roda do mouse funciona em cima
    de qualquer linha."""

    def __init__(self, pai, tema, fundo=None):
        fundo = fundo or tema["ui_fundo"]
        super().__init__(pai, bg=fundo)
        self.tema = tema
        barra = ttk.Scrollbar(self, orient="vertical")
        self.tela = tk.Canvas(self, bg=fundo, highlightthickness=0, bd=0,
                              yscrollcommand=nix_ui.rolagem_automatica(barra))
        barra.configure(command=self.tela.yview)
        self.tela.pack(side="left", fill="both", expand=True)
        self.corpo = tk.Frame(self.tela, bg=fundo)
        janela = self.tela.create_window(0, 0, window=self.corpo, anchor="nw")
        self.corpo.bind("<Configure>", lambda _e: self.tela.configure(
            scrollregion=self.tela.bbox("all")))
        self.tela.bind("<Configure>", lambda e: self.tela.itemconfigure(janela, width=e.width))

    def limpar(self):
        for filho in self.corpo.winfo_children():
            filho.destroy()
        self.tela.yview_moveto(0)

    def ligar_roda(self):
        def rolar(evento):
            if getattr(evento, "num", None) == 4 or getattr(evento, "delta", 0) > 0:
                self.tela.yview_scroll(-2, "units")
            else:
                self.tela.yview_scroll(2, "units")
            return "break"

        def ligar(widget):
            for sequencia in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(sequencia, rolar, add="+")
            for filho in widget.winfo_children():
                ligar(filho)
        ligar(self.tela)
        ligar(self.corpo)


def _quando(segundos):
    try:
        return time.strftime("%d/%m/%Y  %H:%M", time.localtime(segundos))
    except (OverflowError, OSError, ValueError):
        return ""


def marca_wordmark(pai, tema, fonte_titulo, fonte, tamanho_logo=48, subtitulo=True):
    """Marca + 'WaspFiber' (Fiber na cor de destaque) + subtitulo."""
    caixa = tk.Frame(pai, bg=pai.cget("bg"))
    tk.Label(caixa, image=nix_ui.logo(tamanho_logo), bg=pai.cget("bg")).pack(side="left")
    textos = tk.Frame(caixa, bg=pai.cget("bg"))
    textos.pack(side="left", padx=(12, 0))
    nome = tk.Frame(textos, bg=pai.cget("bg"))
    nome.pack(anchor="w")
    tk.Label(nome, text="Wasp", bg=pai.cget("bg"), fg=tema["ui_texto"],
             font=(fonte_titulo, 17), bd=0, padx=0).pack(side="left")
    tk.Label(nome, text="Fiber", bg=pai.cget("bg"), fg=tema["ui_acento"],
             font=(fonte_titulo, 17), bd=0, padx=0).pack(side="left")
    tk.Label(nome, text=VERSAO, bg=misturar(pai.cget("bg"), tema["ui_acento"], 0.14),
             fg=tema["ui_acento"], font=(fonte, 7, "bold"), padx=6).pack(side="left",
                                                                      padx=(10, 0), pady=(4, 0))
    if subtitulo:
        tk.Label(textos, text="Documentacao de redes de fibra optica (FTTH)",
                 bg=pai.cget("bg"), fg=tema["ui_texto_fraco"], font=(fonte, 8)).pack(anchor="w")
    return caixa


class DialogNovaCidade(DialogoBase):
    """Cadastra uma cidade no servidor da empresa."""

    def __init__(self, parent):
        self.resultado = None
        super().__init__(parent, "Nova cidade")

    def body(self, master):
        ttk.Label(master, text="Nome da cidade:").grid(row=0, column=0, sticky="w", pady=3)
        self.e_nome = ttk.Entry(master, width=34)
        self.e_nome.grid(row=0, column=1, sticky="we", pady=3)
        ttk.Label(master, text="UF:").grid(row=1, column=0, sticky="w", pady=3)
        self.var_uf = tk.StringVar(value="")
        ttk.Combobox(master, textvariable=self.var_uf, width=6, state="readonly",
                     values=("",) + nuvem.UFS).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(master, text="A cidade fica no servidor da empresa: todo mundo da equipe "
                               "ve a mesma lista e os mesmos diagramas.",
                  style="Fraco.TLabel", wraplength=340, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        return self.e_nome

    def validate(self):
        if not self.e_nome.get().strip():
            messagebox.showwarning("Nova cidade", "Informe o nome da cidade.", parent=self)
            return False
        return True

    def apply(self):
        self.resultado = (self.e_nome.get().strip(), self.var_uf.get().strip())


class PainelAcesso(tk.Frame):
    """Entrar no WaspFiber (B0.41): e-mail e senha - o servidor e fixo e a
    EMPRESA SAI DO DOMINIO do e-mail (aparece sozinha, sem campo pra errar).
    Tambem 'Criar conta': so com e-mail do dominio da empresa; a conta fica
    aguardando o administrador da empresa aprovar.

    modo_unico=True: so o 'Entrar' (sessao vencida no meio do trabalho)."""

    def __init__(self, pai, tema, fonte, fonte_titulo, ao_entrar, modo_unico=False):
        super().__init__(pai, bg=pai.cget("bg"))
        self.tema, self.fonte, self.fonte_titulo = tema, fonte, fonte_titulo
        self.ao_entrar, self.modo_unico = ao_entrar, modo_unico
        self.modo = "entrar"
        self._consulta = None            # after() da busca da empresa
        self._email_consultado = None
        self.campos = {}
        fundo = self.cget("bg")
        self.lbl_titulo = tk.Label(self, text="", bg=fundo, fg=tema["ui_texto"],
                                   font=(fonte_titulo, 14))
        self.lbl_titulo.pack()
        self.lbl_sub = tk.Label(self, text="", bg=fundo, fg=tema["ui_texto_fraco"],
                                font=(fonte, 9))
        self.lbl_sub.pack(pady=(2, 4))
        self.corpo = tk.Frame(self, bg=fundo)
        self.corpo.pack(fill="x")
        self.msg = tk.Label(self, text="", bg=fundo, fg=tema["ui_erro"], font=(fonte, 8),
                            wraplength=300, justify="left")
        self.msg.pack(anchor="w", pady=(8, 0))
        # nasce com texto: sem texto o BotaoIcone vira botao "so icone" (tamanho fixo)
        self.botao = nix_ui.BotaoIcone(self, tema, None, texto="Entrar", variante="acento",
                                       comando=self.enviar)
        self.botao.pack(fill="x", pady=(10, 0))
        self.troca = tk.Frame(self, bg=fundo)
        if not modo_unico:
            self.troca.pack(pady=(12, 0))
        self.lbl_troca = tk.Label(self.troca, text="", bg=fundo, fg=tema["ui_texto_fraco"],
                                  font=(fonte, 9))
        self.lbl_troca.pack(side="left")
        self.link_troca = tk.Label(self.troca, text="", bg=fundo, fg=tema["ui_acento"],
                                   font=(fonte, 9, "underline"), cursor="hand2")
        self.link_troca.pack(side="left", padx=(4, 0))
        self.link_troca.bind("<ButtonRelease-1>", lambda _e: self.trocar_modo())
        self.montar("entrar")

    # ---------------- montagem ----------------
    def _campo(self, chave, rotulo, valor="", oculto=False):
        t = self.tema
        tk.Label(self.corpo, text=rotulo, bg=self.cget("bg"), fg=t["ui_texto_fraco"],
                 font=(self.fonte, 8)).pack(anchor="w", pady=(8, 2))
        entrada = ttk.Entry(self.corpo, width=38, show="•" if oculto else "")
        entrada.insert(0, valor)
        entrada.pack(fill="x")
        entrada.bind("<Return>", lambda _e: (self.enviar(), "break")[1])
        self.campos[chave] = entrada
        return entrada

    def montar(self, modo):
        t = self.tema
        self.modo = modo
        email_antes = self.campos["email"].get() if "email" in self.campos else \
            nuvem.ler_sessao().get("email", "")
        for filho in self.corpo.winfo_children():
            filho.destroy()
        self.campos = {}
        self._email_consultado = None
        if modo == "entrar":
            self.lbl_titulo.configure(text="Entrar no WaspFiber")
            self.lbl_sub.configure(text="Use o e-mail da sua empresa.")
            self._campo("email", "E-mail", email_antes)
            self._linha_empresa()
            self._campo("senha", "Senha", oculto=True)
            self.botao.configure(text="Entrar")
            self.lbl_troca.configure(text="Ainda nao tem conta?")
            self.link_troca.configure(text="Criar conta")
        else:
            self.lbl_titulo.configure(text="Criar conta")
            self.lbl_sub.configure(text="Com o e-mail da sua empresa (ex.: voce@suaempresa.com.br).")
            self._campo("nome", "Seu nome")
            self._campo("email", "E-mail da empresa", email_antes)
            self._linha_empresa()
            self._campo("senha", "Senha (pelo menos 8 caracteres)", oculto=True)
            self._campo("senha2", "Repita a senha", oculto=True)
            self.botao.configure(text="Criar conta")
            self.lbl_troca.configure(text="Ja tem conta?")
            self.link_troca.configure(text="Entrar")
        self.campos["email"].bind("<KeyRelease>", lambda _e: self._agendar_empresa(), add="+")
        self.campos["email"].bind("<FocusOut>", lambda _e: self._agendar_empresa(0), add="+")
        self.mostrar_msg("")
        self._agendar_empresa(0)
        self.foco = next((e for e in self.campos.values() if not e.get()), self.campos["senha"])

    def _linha_empresa(self):
        """'Empresa: Zaaz NE' - preenchida sozinha pelo dominio do e-mail."""
        fundo = self.cget("bg")
        linha = tk.Frame(self.corpo, bg=fundo)
        linha.pack(fill="x", pady=(6, 0))
        self.img_empresa = tk.Label(linha, image=nix_ui.icone("building-2", "fraco"), bg=fundo)
        self.img_empresa.pack(side="left")
        self.lbl_empresa = tk.Label(linha, text="", bg=fundo, fg=self.tema["ui_texto_fraco"],
                                    font=(self.fonte, 9))
        self.lbl_empresa.pack(side="left", padx=(6, 0))
        self.empresa_nome = None

    def trocar_modo(self):
        self.montar("criar" if self.modo == "entrar" else "entrar")
        self.after(50, lambda: self.foco.focus_set())

    def mostrar_msg(self, texto, tipo="erro"):
        cor = {"erro": self.tema["ui_erro"], "ok": self.tema["ui_ok"],
               "info": self.tema["ui_texto_fraco"]}[tipo]
        self.msg.configure(text=texto, fg=cor)

    # ---------------- empresa pelo dominio ----------------
    def _agendar_empresa(self, atraso=450):
        if self._consulta:
            self.after_cancel(self._consulta)
        self._consulta = self.after(atraso, self._buscar_empresa)

    def _buscar_empresa(self):
        self._consulta = None
        if "email" not in self.campos:
            return
        email = self.campos["email"].get().strip().lower()
        if email == self._email_consultado:
            return
        self._email_consultado = email
        t = self.tema
        if "@" not in email or "." not in email.rsplit("@", 1)[1]:
            self.empresa_nome = None
            self.lbl_empresa.configure(text="A empresa aparece aqui pelo e-mail", fg=t["ui_texto_fraco"])
            self.img_empresa.configure(image=nix_ui.icone("building-2", "fraco"))
            return
        self.lbl_empresa.configure(text="Procurando a empresa...", fg=t["ui_texto_fraco"])

        def pronto(nome, erro):
            if self.campos.get("email") is None or \
                    self.campos["email"].get().strip().lower() != email:
                return
            if erro:
                self.empresa_nome = None
                self.lbl_empresa.configure(text="Sem conexao com o WaspFiber", fg=t["ui_aviso"])
                self._email_consultado = None
            elif nome:
                self.empresa_nome = nome
                self.lbl_empresa.configure(text="Empresa: %s" % nome, fg=t["ui_texto"])
                self.img_empresa.configure(image=nix_ui.icone("building-2", "acento"))
            else:
                self.empresa_nome = None
                self.lbl_empresa.configure(text="@%s nao e de nenhuma empresa cadastrada"
                                                % email.rsplit("@", 1)[1], fg=t["ui_aviso"])
                self.img_empresa.configure(image=nix_ui.icone("building-2", "aviso"))
        em_segundo_plano(self, lambda: nuvem.Conexao.empresa_do_email(email), pronto)

    # ---------------- enviar ----------------
    def enviar(self):
        if self.modo == "entrar":
            self._entrar()
        else:
            self._criar()

    def _entrar(self):
        email = self.campos["email"].get().strip()
        senha = self.campos["senha"].get()
        if not email or not senha:
            self.mostrar_msg("Digite o e-mail e a senha.")
            return
        self.mostrar_msg("Entrando...", "info")
        self.update_idletasks()
        try:
            conexao = nuvem.Conexao.entrar_email(email, senha)
        except nuvem.ErroServidor as falha:
            self.mostrar_msg(str(falha))
            self.campos["senha"].delete(0, "end")
            return
        self.campos["senha"].delete(0, "end")
        self.mostrar_msg("")
        self.ao_entrar(conexao)

    def _criar(self):
        c = {k: e.get() for k, e in self.campos.items()}
        if not c["nome"].strip() or not c["email"].strip() or not c["senha"]:
            self.mostrar_msg("Preencha nome, e-mail e senha.")
            return
        if c["senha"] != c["senha2"]:
            self.mostrar_msg("As duas senhas nao conferem.")
            self.campos["senha2"].delete(0, "end")
            return
        if len(c["senha"]) < 8:
            self.mostrar_msg("A senha precisa ter pelo menos 8 caracteres.")
            return
        self.mostrar_msg("Enviando o pedido...", "info")
        self.update_idletasks()
        try:
            r = nuvem.Conexao.criar_conta(c["nome"].strip(), c["email"].strip(), c["senha"])
        except nuvem.ErroServidor as falha:
            self.mostrar_msg(str(falha))
            return
        self.montar("entrar")
        self.mostrar_msg("Pedido enviado para a %s. Assim que o administrador aprovar, "
                         "entre com o seu e-mail e a senha." % r.get("empresa_nome", "empresa"),
                         "ok")


class DialogEntrar(DialogoBase):
    """Login quando a sessao vence no meio do trabalho."""

    def __init__(self, parent):
        self.conexao = None
        super().__init__(parent, "Entrar no WaspFiber")

    def body(self, master):
        ttk.Label(master, text="A sessao terminou. Entre de novo pra continuar (o diagrama "
                               "aberto nao se perde).", wraplength=320,
                  justify="left").pack(anchor="w", pady=(0, 6))
        self.painel = PainelAcesso(master, TEMA, "TkDefaultFont", "TkDefaultFont",
                                   self._entrou, modo_unico=True)
        self.painel.pack(fill="x")
        return self.painel.foco

    def buttonbox(self):
        self.bind("<Escape>", self.cancel)

    def _entrou(self, conexao):
        self.conexao = conexao
        self.ok()

    def validate(self):
        return self.conexao is not None


class DialogPedidos(tk.Toplevel):
    """Pedidos de acesso da empresa (so o administrador ve): aprovar / recusar."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Pedidos de acesso")
        self.configure(bg=TEMA["ui_fundo"])
        self.transient(app)
        self.geometry("560x420")
        t = TEMA
        tk.Label(self, text="Pedidos de acesso", bg=t["ui_fundo"], fg=t["ui_texto"],
                 font=(app.fonte_titulo, 13)).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(self, text="Contas criadas com o e-mail da empresa, esperando a sua aprovacao.",
                 bg=t["ui_fundo"], fg=t["ui_texto_fraco"], font=(app.fonte_ui, 9)).pack(
            anchor="w", padx=18)
        self.lista = ListaRolavel(self, t)
        self.lista.pack(fill="both", expand=True, padx=12, pady=12)
        self.atualizar()

    def atualizar(self):
        t = TEMA
        self.lista.limpar()
        try:
            pedidos = self.app.conexao.pedidos()
        except nuvem.ErroServidor as erro:
            tk.Label(self.lista.corpo, text=str(erro), bg=t["ui_fundo"], fg=t["ui_erro"],
                     wraplength=480, justify="left").pack(anchor="w", padx=8, pady=8)
            return
        if not pedidos:
            tk.Label(self.lista.corpo, text="Nenhum pedido aguardando.", bg=t["ui_fundo"],
                     fg=t["ui_texto_fraco"], font=(self.app.fonte_ui, 10)).pack(pady=30)
        for p in pedidos:
            linha = tk.Frame(self.lista.corpo, bg=t["ui_painel"], highlightthickness=1,
                             highlightbackground=t["ui_borda"])
            linha.pack(fill="x", pady=3)
            textos = tk.Frame(linha, bg=t["ui_painel"])
            textos.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            tk.Label(textos, text=p["nome"], bg=t["ui_painel"], fg=t["ui_texto"],
                     font=(self.app.fonte_titulo, 10), anchor="w").pack(anchor="w")
            tk.Label(textos, text="%s   ·   pediu em %s" % (p["email"], p["criado_em"]),
                     bg=t["ui_painel"], fg=t["ui_texto_fraco"], font=(self.app.fonte_ui, 8),
                     anchor="w").pack(anchor="w")
            nix_ui.BotaoIcone(linha, t, "x", texto="Recusar",
                              comando=lambda e=p["email"]: self.decidir(e, False)).pack(
                side="right", padx=(0, 8))
            nix_ui.BotaoIcone(linha, t, "check", texto="Aprovar", variante="acento",
                              comando=lambda e=p["email"]: self.decidir(e, True)).pack(
                side="right", padx=4)
        self.lista.ligar_roda()

    def decidir(self, email, aprovar):
        if not aprovar and not messagebox.askyesno(
                "Recusar pedido", "Recusar o acesso de %s? A conta pedida e apagada." % email,
                parent=self):
            return
        try:
            self.app.conexao.decidir_pedido(email, aprovar)
        except nuvem.ErroServidor as erro:
            messagebox.showwarning("Pedidos de acesso", str(erro), parent=self)
        self.atualizar()
        if self.app.tela_inicio.visivel():
            self.app.tela_inicio.atualizar_pedidos()


class TelaInicio(tk.Frame):
    """Primeira tela do programa (B0.39: tudo no SERVIDOR). Sem sessao, mostra
    o login; depois, as cidades da empresa e os diagramas (POP / CEO / CTO)
    de cada uma - ou cadastrar uma cidade / um diagrama novo. Fica por cima
    do editor e some quando um diagrama e aberto."""

    def __init__(self, app):
        t = TEMA
        super().__init__(app, bg=t["ui_fundo"])
        self.app = app
        self.cidade = None
        self.cidades = []
        self.itens = []
        self.linhas_cidade = {}
        self.linhas_diagrama = {}
        self.diagrama_escolhido = None
        BotaoIcone = nix_ui.BotaoIcone
        fonte, titulo = app.fonte_ui, app.fonte_titulo
        profundo = t["ui_profundo"]

        # ----- cabecalho -----
        topo = tk.Frame(self, bg=t["ui_fundo"])
        topo.pack(fill="x", padx=26, pady=(16, 14))
        marca_wordmark(topo, t, titulo, fonte).pack(side="left")
        BotaoIcone(topo, t, "circle-help", texto="Como usar",
                   comando=app.acao_ajuda).pack(side="right")
        tk.Frame(self, bg=t["ui_borda"], height=1).pack(fill="x")

        self.corpo = tk.Frame(self, bg=t["ui_fundo"])
        self.corpo.pack(fill="both", expand=True)

        # ----- coluna das cidades -----
        esquerda = tk.Frame(self.corpo, bg=t["ui_fundo"], width=340)
        esquerda.pack(side="left", fill="y")
        esquerda.pack_propagate(False)
        cab = tk.Frame(esquerda, bg=t["ui_fundo"])
        cab.pack(fill="x", padx=(24, 16), pady=(22, 12))
        tk.Label(cab, text="Cidades", bg=t["ui_fundo"], fg=t["ui_texto"],
                 font=(titulo, 12)).pack(side="left")
        self.lbl_qtd_cidades = tk.Label(cab, text="", bg=t["ui_fundo"], fg=t["ui_texto_fraco"],
                                        font=(fonte, 9))
        self.lbl_qtd_cidades.pack(side="left", padx=(8, 0), pady=(2, 0))
        BotaoIcone(cab, t, "rotate-cw", dica="Atualizar (buscar de novo no servidor)",
                   comando=self.atualizar).pack(side="right")
        botoes = tk.Frame(esquerda, bg=t["ui_fundo"])
        botoes.pack(fill="x", padx=(22, 16), pady=(0, 12))
        BotaoIcone(botoes, t, "plus", texto="Nova cidade", variante="acento",
                   comando=self.nova_cidade).pack(side="left")
        self.lista_cidades = ListaRolavel(esquerda, t)
        self.lista_cidades.pack(fill="both", expand=True, padx=(14, 8))

        # quadro do servidor: onde esta conectado, quem e, envios pendentes
        rodape = tk.Frame(esquerda, bg=t["ui_painel"])
        rodape.pack(fill="x", padx=16, pady=16)
        dentro = tk.Frame(rodape, bg=t["ui_painel"])
        dentro.pack(fill="x", padx=12, pady=10)
        linha = tk.Frame(dentro, bg=t["ui_painel"])
        linha.pack(fill="x")
        self.lbl_servidor_titulo = tk.Label(linha, text="CONECTADO", bg=t["ui_painel"],
                                            fg=t["ui_texto_fraco"], font=(fonte, 7, "bold"))
        self.lbl_servidor_titulo.pack(side="left")
        self.bt_sair = BotaoIcone(linha, t, "x", texto="Sair", comando=self.sair)
        self.bt_sair.pack(side="right")
        self.lbl_empresa = tk.Label(dentro, text="", bg=t["ui_painel"], fg=t["ui_texto"],
                                    font=(titulo, 9), anchor="w", justify="left")
        self.lbl_empresa.pack(anchor="w", pady=(2, 0))
        self.lbl_servidor = tk.Label(dentro, text="", bg=t["ui_painel"], fg=t["ui_texto_fraco"],
                                     font=(fonte, 8), anchor="w", justify="left", wraplength=280)
        self.lbl_servidor.pack(anchor="w")
        self.bt_pedidos = BotaoIcone(dentro, t, "circle-alert", texto="Pedidos de acesso",
                                     variante="normal", comando=lambda: DialogPedidos(self.app))
        self.quadro_pendentes = tk.Frame(dentro, bg=t["ui_painel"])
        self.lbl_pendentes = tk.Label(self.quadro_pendentes, text="", bg=t["ui_painel"],
                                      fg=t["ui_aviso"], font=(fonte, 8), anchor="w",
                                      justify="left", wraplength=200)
        self.lbl_pendentes.pack(side="left")
        BotaoIcone(self.quadro_pendentes, t, "rotate-cw", texto="Enviar",
                   comando=lambda: self.app._sincronizar(avisar=True)).pack(side="right")

        tk.Frame(self.corpo, bg=t["ui_borda"], width=1).pack(side="left", fill="y")

        # ----- area dos diagramas (mais escura) -----
        self.direita = tk.Frame(self.corpo, bg=profundo)
        self.direita.pack(side="left", fill="both", expand=True)
        self.cab_cidade = tk.Frame(self.direita, bg=profundo)
        self.cab_cidade.pack(fill="x", padx=32, pady=(24, 4))
        self.lbl_cidade = tk.Label(self.cab_cidade, text="", bg=profundo, fg=t["ui_texto"],
                                   font=(titulo, 20), anchor="w")
        self.lbl_cidade.pack(anchor="w")
        self.resumo = tk.Frame(self.cab_cidade, bg=profundo)
        self.resumo.pack(anchor="w", pady=(6, 0))
        self.barra_diagramas = tk.Frame(self.direita, bg=profundo)
        self.barra_diagramas.pack(fill="x", padx=30, pady=(16, 10))
        BotaoIcone(self.barra_diagramas, t, "plus", texto="Novo diagrama", variante="acento",
                   comando=self.novo_diagrama).pack(side="left")
        self.bt_abrir = BotaoIcone(self.barra_diagramas, t, "folder-open", texto="Abrir",
                                   variante="normal", comando=self.abrir_escolhido)
        self.bt_abrir.pack(side="left", padx=(6, 0))
        BotaoIcone(self.barra_diagramas, t, "download", texto="Importar arquivo",
                   dica="Envia um .wasp.json deste computador pra esta cidade no servidor",
                   comando=self.importar).pack(side="left", padx=(6, 0))
        self.lista_diagramas = ListaRolavel(self.direita, t, fundo=profundo)
        self.lista_diagramas.pack(fill="both", expand=True, padx=(30, 18), pady=(0, 18))

        # mensagem no lugar da lista (sem cidades / sem conexao)
        self.aviso = tk.Frame(self.direita, bg=profundo)
        self.aviso_img = tk.Label(self.aviso, image=nix_ui.logo_emblema(), bg=profundo)
        self.aviso_img.pack(pady=(0, 18))
        self.aviso_titulo = tk.Label(self.aviso, text="", bg=profundo, fg=t["ui_texto"],
                                     font=(titulo, 15))
        self.aviso_titulo.pack()
        self.aviso_texto = tk.Label(self.aviso, text="", bg=profundo, fg=t["ui_texto_fraco"],
                                    font=(fonte, 9), justify="center")
        self.aviso_texto.pack(pady=(8, 18))
        self.aviso_botoes = tk.Frame(self.aviso, bg=profundo)
        self.aviso_botoes.pack()

        # ----- login (cobre tudo abaixo do cabecalho) -----
        self.login = tk.Frame(self, bg=profundo)
        cartao = tk.Frame(self.login, bg=t["ui_painel"], highlightthickness=1,
                          highlightbackground=t["ui_borda"])
        cartao.place(relx=0.5, rely=0.46, anchor="center")
        caixa = tk.Frame(cartao, bg=t["ui_painel"])
        caixa.pack(padx=34, pady=28)
        tk.Label(caixa, image=nix_ui.logo(64), bg=t["ui_painel"]).pack(pady=(0, 10))
        self.form = PainelAcesso(caixa, t, fonte, titulo, self._entrou)
        self.form.pack(fill="x")

        self.bind_all("<Return>", self._enter, add="+")

    # ---------------- estado ----------------
    @property
    def conexao(self):
        return self.app.conexao

    def mostrar(self):
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.lift()
        self.atualizar()

    def visivel(self):
        return bool(self.place_info())

    def _mostrar_login(self, mensagem=""):
        self.corpo.pack_forget()
        self.login.pack(fill="both", expand=True)
        if self.form.modo != "entrar":
            self.form.montar("entrar")
        self.form.mostrar_msg(mensagem)
        self.after(50, lambda: self.form.foco.focus_set())

    def _entrou(self, conexao):
        self.app.conexao = conexao
        self.app.after(300, self.app._sincronizar)
        self.atualizar()

    def sair(self):
        if self.conexao and nuvem.pendentes():
            if not messagebox.askyesno(
                    "Sair", "Ainda ha diagrama(s) aguardando envio pro servidor. Eles continuam "
                            "guardados neste computador e sao enviados no proximo login.\n\n"
                            "Sair mesmo assim?"):
                return
        if self.conexao:
            self.conexao.sair()
        self.app.conexao = None
        self.cidade = None
        self.atualizar()

    def _chamar(self, funcao, titulo="Servidor"):
        """Chama o servidor; trata sessao vencida e falta de conexao.
        Devolve (ok, resultado)."""
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            return True, funcao()
        except nuvem.ErroServidor as erro:
            if erro.status == 401:
                self.app.conexao = None
                self._mostrar_login(str(erro))
            elif erro.sem_conexao:
                self._mostrar_aviso("Sem conexao com o servidor", str(erro) +
                                    "\nConfira a rede (ou a VPN) e tente de novo.",
                                    [("rotate-cw", "Tentar de novo", self.atualizar)])
            else:
                messagebox.showwarning(titulo, str(erro))
            return False, None
        finally:
            self.configure(cursor="")

    # ---------------- dados ----------------
    def atualizar(self):
        if not self.conexao:
            self._mostrar_login()
            return
        self.login.pack_forget()
        if not self.corpo.winfo_ismapped():
            self.corpo.pack(fill="both", expand=True)
        info = self.conexao.info
        self.lbl_empresa.configure(text="%s  ·  %s" % (info.get("empresa_nome") or info.get("empresa", ""),
                                                       info.get("nome") or info.get("usuario", "")))
        self.lbl_servidor.configure(text=info.get("usuario", ""))
        self.atualizar_pendentes()
        self.atualizar_pedidos()
        ok, lista = self._chamar(self.conexao.cidades)
        if not ok:
            return
        self.cidades = lista
        self.lbl_qtd_cidades.configure(text=str(len(lista)) if lista else "")
        self.lista_cidades.limpar()
        self.linhas_cidade = {}
        for cidade in lista:
            qtd = cidade.get("diagramas", 0)
            linha = LinhaLista(self.lista_cidades.corpo, TEMA, "building-2", cidade["titulo"],
                               "%d diagrama%s" % (qtd, "" if qtd == 1 else "s"),
                               ao_clicar=lambda c=cidade: self.escolher_cidade(c),
                               ao_duplo=lambda c=cidade: self.escolher_cidade(c),
                               fonte=self.app.fonte_ui)
            linha.pack(fill="x", pady=1)
            self.linhas_cidade[cidade["id"]] = linha
        self.lista_cidades.ligar_roda()
        if not lista:
            self.cidade = None
            self._mostrar_aviso("Comece cadastrando uma cidade",
                                "Cada cidade guarda os diagramas dos POPs, caixas de emenda "
                                "e CTOs dela.\nTudo fica no servidor: a equipe toda ve as "
                                "mesmas cidades.",
                                [("plus", "Nova cidade", self.nova_cidade)])
            return
        ultima = nuvem.ler_sessao().get("ultima_cidade")
        escolhida = next((c for c in lista if self.cidade and c["id"] == self.cidade["id"]), None) \
            or next((c for c in lista if c["id"] == ultima), None) or lista[0]
        self.escolher_cidade(escolhida, registrar=False)

    def atualizar_pedidos(self):
        """Administrador da empresa: botao com quantos pedidos de acesso esperam."""
        if not self.conexao or self.conexao.info.get("papel") != "admin":
            self.bt_pedidos.pack_forget()
            return
        try:
            qtd = len(self.conexao.pedidos())
        except nuvem.ErroServidor:
            qtd = 0
        self.bt_pedidos.configure(text="Pedidos de acesso (%d)" % qtd if qtd
                                  else "Pedidos de acesso")
        self.bt_pedidos.variante = "acento" if qtd else "normal"
        self.bt_pedidos._sair()
        self.bt_pedidos.pack(anchor="w", pady=(8, 0))

    def atualizar_pendentes(self):
        qtd = len(nuvem.pendentes())
        if qtd:
            self.lbl_pendentes.configure(text="%d diagrama%s aguardando envio" % (
                qtd, "" if qtd == 1 else "s"))
            self.quadro_pendentes.pack(fill="x", pady=(8, 0))
        else:
            self.quadro_pendentes.pack_forget()

    def _mostrar_aviso(self, titulo, texto, botoes):
        for parte in (self.cab_cidade, self.barra_diagramas, self.lista_diagramas):
            parte.pack_forget()
        self.aviso_titulo.configure(text=titulo)
        self.aviso_texto.configure(text=texto)
        for filho in self.aviso_botoes.winfo_children():
            filho.destroy()
        for i, (icone, texto_bt, comando) in enumerate(botoes):
            nix_ui.BotaoIcone(self.aviso_botoes, TEMA, icone, texto=texto_bt,
                              variante="acento" if i == 0 else "normal",
                              comando=comando).pack(side="left", padx=3)
        self.aviso.place(relx=0.5, rely=0.45, anchor="center")

    def _esconder_aviso(self):
        self.aviso.place_forget()
        if not self.cab_cidade.winfo_ismapped():
            self.cab_cidade.pack(fill="x", padx=32, pady=(24, 4))
            self.barra_diagramas.pack(fill="x", padx=30, pady=(16, 10))
            self.lista_diagramas.pack(fill="both", expand=True, padx=(30, 18), pady=(0, 18))

    def escolher_cidade(self, cidade, registrar=True):
        self.cidade = cidade
        if registrar:
            s = nuvem.ler_sessao()
            s["ultima_cidade"] = cidade["id"]
            nuvem.gravar_sessao(s)
        for chave, linha in self.linhas_cidade.items():
            linha.marcar(chave == cidade["id"])
        self._esconder_aviso()
        self.lbl_cidade.configure(text=cidade["titulo"])
        self.listar_diagramas()

    def _montar_resumo(self, itens):
        t = TEMA
        profundo = t["ui_profundo"]
        for filho in self.resumo.winfo_children():
            filho.destroy()
        if not itens:
            tk.Label(self.resumo, text="Nenhum diagrama ainda", bg=profundo,
                     fg=t["ui_texto_fraco"], font=(self.app.fonte_ui, 9)).pack(side="left")
            return
        for tipo in ("POP", "CEO", "CTO"):
            qtd = len([i for i in itens if i["tipo"] == tipo])
            if qtd:
                Selo(self.resumo, tipo, COR_LOCAL[tipo], profundo,
                     self.app.fonte_ui).pack(side="left")
                tk.Label(self.resumo, text=str(qtd), bg=profundo, fg=t["ui_texto"],
                         font=(self.app.fonte_ui, 9)).pack(side="left", padx=(5, 14))
        outros = len([i for i in itens if i["tipo"] not in COR_LOCAL])
        if outros:
            tk.Label(self.resumo, text="%d sem tipo" % outros, bg=profundo,
                     fg=t["ui_texto_fraco"], font=(self.app.fonte_ui, 9)).pack(side="left",
                                                                               padx=(0, 14))
        sem_local = len([i for i in itens if not i["tem_coordenada"] and not i["erro"]])
        if sem_local:
            tk.Label(self.resumo, text="%d sem localizacao no mapa" % sem_local, bg=profundo,
                     fg=t["ui_aviso"], font=(self.app.fonte_ui, 9)).pack(side="left")

    def listar_diagramas(self):
        t = TEMA
        self.lista_diagramas.limpar()
        self.linhas_diagrama = {}
        self.diagrama_escolhido = None
        ok, itens = self._chamar(lambda: self.conexao.diagramas(self.cidade["id"]))
        if not ok:
            return
        self.itens = itens
        self._montar_resumo(itens)
        if not itens:
            caixa = tk.Frame(self.lista_diagramas.corpo, bg=t["ui_painel"],
                             highlightthickness=1, highlightbackground=t["ui_borda"])
            caixa.pack(fill="x", pady=(4, 0))
            tk.Label(caixa, text="Nenhum diagrama nesta cidade ainda", bg=t["ui_painel"],
                     fg=t["ui_texto"], font=(self.app.fonte_titulo, 11)).pack(pady=(26, 4))
            tk.Label(caixa, text="Crie o primeiro: o POP, uma caixa de emenda ou uma CTO.",
                     bg=t["ui_painel"], fg=t["ui_texto_fraco"],
                     font=(self.app.fonte_ui, 9)).pack(pady=(0, 14))
            nix_ui.BotaoIcone(caixa, t, "plus", texto="Novo diagrama", variante="acento",
                              comando=self.novo_diagrama).pack(pady=(0, 26))
        for item in itens:
            partes = []
            if item["erro"]:
                partes.append(item["erro"])
            else:
                if item["endereco"]:
                    partes.append(item["endereco"])
                partes.append("%d equipamento%s  ·  %d fusoes" % (
                    item["equipamentos"], "" if item["equipamentos"] == 1 else "s",
                    item["fusoes"]))
                if not item["tem_coordenada"]:
                    partes.append("sem localizacao no mapa")
            if nuvem.pendente_de(self.cidade["id"], item["id"]):
                partes.append("alteracoes deste PC aguardando envio")
            direita = "alterado em %s" % _quando(item["modificado"])
            if item.get("alterado_por"):
                direita += "\npor %s" % item["alterado_por"]
            selo = (item["tipo"], COR_LOCAL[item["tipo"]]) if item["tipo"] in COR_LOCAL else None
            linha = LinhaLista(self.lista_diagramas.corpo, t,
                               ICONE_LOCAL.get(item["tipo"], "file-text"), item["titulo"],
                               "   ·   ".join(partes), direita,
                               ao_clicar=lambda i=item: self._escolher_diagrama(i),
                               ao_duplo=lambda i=item: self.app.abrir_diagrama(self.cidade, i["id"]),
                               fonte=self.app.fonte_ui, fonte_titulo=self.app.fonte_titulo,
                               estilo="cartao", selo=selo)
            linha.pack(fill="x", pady=4)
            self.linhas_diagrama[item["id"]] = linha
        self.lista_diagramas.ligar_roda()

    def _escolher_diagrama(self, item):
        self.diagrama_escolhido = item["id"]
        for did, linha in self.linhas_diagrama.items():
            linha.marcar(did == item["id"])

    def _enter(self, evento):
        if self.visivel() and self.conexao and evento.widget.winfo_toplevel() is self.app \
                and self.diagrama_escolhido:
            self.abrir_escolhido()

    # ---------------- acoes ----------------
    def abrir_escolhido(self):
        if self.diagrama_escolhido and self.cidade:
            self.app.abrir_diagrama(self.cidade, self.diagrama_escolhido)
        elif self.cidade:
            self.app.status.config(text="Escolha um diagrama da lista (ou crie um novo).")

    def nova_cidade(self):
        if not self.conexao:
            return
        dialogo = DialogNovaCidade(self.app)
        if not dialogo.resultado:
            return
        nome, uf = dialogo.resultado
        ok, cidade = self._chamar(lambda: self.conexao.criar_cidade(nome, uf), "Nova cidade")
        if ok:
            self.cidade = cidade
            s = nuvem.ler_sessao()
            s["ultima_cidade"] = cidade["id"]
            nuvem.gravar_sessao(s)
            self.atualizar()

    def novo_diagrama(self):
        if self.cidade:
            self.app.novo_diagrama(self.cidade)

    def importar(self):
        if self.cidade:
            self.app.importar_diagrama(self.cidade)


class App(tk.Tk):
    DICA = ("Clique numa porta do diagrama e depois em outra para criar a fusao. "
            "Arraste o equipamento (por qualquer parte) para move-lo. "
            "Roda do mouse = zoom, arrastar no vazio = mover a vista.")

    def __init__(self):
        super().__init__()
        nix_ui.usar_janela(self)
        self.title(APP_NOME)
        self.geometry("1380x850")
        self.minsize(1000, 620)

        self.rede = Rede()
        self.caminho_atual = None
        # B0.39: os diagramas ficam no servidor. documento = o diagrama aberto
        # (cidade, id e versao no servidor); conexao = login lembrado
        self.documento = None
        self.conexao = nuvem.Conexao.da_sessao_salva()
        self._sincronizando = False
        self.porta_selecionada = None
        self.escala = 1.0
        self.cena = None
        self._arraste_eq = None
        self.mostrar_potencia = True   # camada de potencia (dBm) no diagrama
        self.selecao_lote = []         # portas marcadas com Shift+clique
        self._origem_arraste = None
        self._redesenho_pendente = False
        self.destaque = set()          # fusoes realcadas pelo rastreio
        self.alteracoes_pendentes = False
        self._historico = []           # estados anteriores (desfazer)
        self._refazer = []
        self._janela_busca = None
        self._janela_pendencias = None

        self._aplicar_estilo()
        self._montar_menu()
        self._montar_layout()
        self._montar_atalhos()
        self.protocol("WM_DELETE_WINDOW", self.acao_sair)
        nix_ui.barra_de_titulo_escura(self)
        self.atualizar_tudo(centralizar=True)
        # B0.36: o programa abre na tela das cidades, nao direto no diagrama
        self.tela_inicio = TelaInicio(self)
        self.tela_inicio.mostrar()
        self.after(1500, self._sincronizar_periodico)   # envia o que ficou sem conexao
        self.after(400, self._oferecer_recuperacao)

    # ---------------- protecao do trabalho ----------------
    def _snapshot(self):
        """Guarda o estado atual antes de uma alteracao, pra permitir desfazer."""
        try:
            self._historico.append(json.dumps(self.rede.to_dict()))
        except Exception:
            return
        if len(self._historico) > 60:
            self._historico.pop(0)
        self._refazer.clear()

    def _marcar_alterado(self):
        self.alteracoes_pendentes = True
        gravar_autosave(self.rede, self.caminho_atual, getattr(self, "documento", None))
        if hasattr(self, "lbl_alterado"):
            self._atualizar_cabecalho()

    def acao_desfazer(self, _evento=None):
        if not self._historico:
            self.status.config(text="Nada para desfazer.")
            return
        try:
            self._refazer.append(json.dumps(self.rede.to_dict()))
            self.rede = Rede.from_dict(json.loads(self._historico.pop()))
        except Exception as erro:
            messagebox.showerror("Nao foi possivel desfazer", str(erro))
            return
        self._depois_de_trocar_rede()
        self.status.config(text="Desfeito. (%d passo(s) restante(s))" % len(self._historico))

    def acao_refazer(self, _evento=None):
        if not self._refazer:
            self.status.config(text="Nada para refazer.")
            return
        try:
            self._historico.append(json.dumps(self.rede.to_dict()))
            self.rede = Rede.from_dict(json.loads(self._refazer.pop()))
        except Exception as erro:
            messagebox.showerror("Nao foi possivel refazer", str(erro))
            return
        self._depois_de_trocar_rede()

    def _depois_de_trocar_rede(self):
        """Depois de desfazer/refazer/abrir: as janelas auxiliares apontam pra
        rede antiga, entao elas se atualizam ou fecham."""
        self.porta_selecionada = None
        self.destaque = set()
        self._marcar_alterado()
        self.atualizar_tudo()
        for janela in (self._janela_busca, self._janela_pendencias):
            if janela is not None and janela.winfo_exists():
                janela.rede = self.rede
                if hasattr(janela, "atualizar"):
                    janela.atualizar()
                elif hasattr(janela, "_procurar"):
                    janela._procurar()

    def _confirmar_descarte(self, titulo):
        """Pergunta o que fazer com alteracoes nao salvas. True = pode seguir."""
        if not self.alteracoes_pendentes:
            return True
        resposta = messagebox.askyesnocancel(
            titulo, "Voce tem alteracoes que ainda nao foram salvas.\n\n"
                    "Salvar antes de continuar?\n\n"
                    "Sim = salvar    |    Nao = descartar    |    Cancelar = voltar")
        if resposta is None:
            return False
        if resposta:
            self.acao_salvar()
            return not self.alteracoes_pendentes   # se cancelou o Salvar como, aborta
        return True

    def acao_sair(self):
        if not self._confirmar_descarte("Sair"):
            return
        apagar_autosave()
        self.destroy()

    def _oferecer_recuperacao(self):
        """Se o programa foi fechado no meio do trabalho, oferece o que ficou."""
        if self.rede.equipamentos:
            return
        rede, info = ler_autosave()
        if rede is None:
            return
        quando = (info or {}).get("quando", "sessao anterior")
        arquivo = (info or {}).get("arquivo") or ""
        detalhe = ("\nArquivo de origem: %s" % arquivo) if arquivo else ""
        if messagebox.askyesno(
                "Recuperar trabalho",
                "Encontrei um trabalho da sessao anterior que nao foi salvo "
                "(%d equipamentos, %d fusoes), de %s.%s\n\nQuer recuperar?"
                % (len(rede.equipamentos), len(rede.fusoes), quando, detalhe)):
            self.rede = rede
            self.caminho_atual = None
            self.documento = (info or {}).get("documento")
            self.alteracoes_pendentes = True
            self.mostrar_editor()
            self.atualizar_tudo(centralizar=True)
        else:
            apagar_autosave()

    def _montar_atalhos(self):
        self.bind_all("<Control-s>", lambda _: self.acao_salvar())
        self.bind_all("<Control-o>", lambda _: self.acao_abrir())
        self.bind_all("<Control-z>", self.acao_desfazer)
        self.bind_all("<Control-y>", self.acao_refazer)
        self.bind_all("<Control-k>", lambda _: (self.abrir_paleta(), "break")[1])
        self.bind_all("<Control-K>", lambda _: (self.abrir_paleta(), "break")[1])
        self.bind_all("<Control-l>", lambda _: self.acao_buscar())
        self.bind_all("<Control-f>", lambda _: self.acao_rastrear())
        self.bind_all("<Control-d>", lambda _: self.acao_duplicar_equipamento())
        self.bind_all("<F1>", lambda _: self.acao_ajuda())
        self.bind_all("<F5>", lambda _: self.acao_pendencias())
        self.bind_all("<KeyPress-i>", self._tecla_atalho(self.acao_inverter_lado))
        self.bind_all("<KeyPress-I>", self._tecla_atalho(self.acao_inverter_lado))
        self.bind_all("<KeyPress-p>", self._tecla_atalho(self.acao_alternar_potencia))
        self.bind_all("<KeyPress-P>", self._tecla_atalho(self.acao_alternar_potencia))
        self.bind_all("<Escape>", self._tecla_esc)

    # ---------------- janela ----------------
    def _montar_menu(self):
        """Sem barra de menu nativa (no Windows ela e branca e ignora o tema).
        Tudo fica no menu '...' do canto e na paleta de comandos (Ctrl+K)."""
        self.config(menu="")
        try:
            self.iconphoto(True, nix_ui.logo_icone())      # icone desta e das outras janelas
        except tk.TclError:
            pass
        # barra de titulo escura nas janelas de dialogo tambem
        self._janelas_escurecidas = set()
        self.bind_class("Toplevel", "<Map>", self._escurecer_dialogo, add="+")

    def _escurecer_dialogo(self, evento):
        janela = evento.widget
        if str(janela) in self._janelas_escurecidas or getattr(janela, "_titulo_escuro", False):
            return
        self._janelas_escurecidas.add(str(janela))
        try:
            if not janela.overrideredirect():
                nix_ui.barra_de_titulo_escura(janela)
        except Exception:
            pass

    def _comandos(self):
        """Tudo que o programa sabe fazer: alimenta a paleta (Ctrl+K) e o
        menu '...'. (icone, nome, atalho, funcao, palavras extras pra busca)"""
        return [
            ("house", "Inicio (cidades e diagramas)", "", self.mostrar_inicio,
             "voltar cidade cidades pasta inicio diagramas trocar abrir"),
            ("plus", "Novo equipamento", "", self.acao_novo_equipamento,
             "criar cadastrar dio olt switch rb acomodador cto cabo fibra"),
            ("layers", "Criar varios equipamentos", "", self.acao_criar_lote, "lote leva serie"),
            ("copy", "Duplicar equipamento", "Ctrl+D", self.acao_duplicar_equipamento,
             "copiar repetir"),
            ("pencil", "Editar equipamento", "", self.acao_editar_equipamento,
             "renomear nome portas"),
            ("box", "Novo modulo", "", self.acao_novo_modulo,
             "placa gpon controle grupamento sfp qsfp splitter"),
            ("arrow-left-right", "Inverter lado das portas", "", self.acao_inverter_lado,
             "espelhar lado"),
            ("activity", "Mostrar / ocultar potencia (dBm)", "P", self.acao_alternar_potencia,
             "sinal dbm nivel atenuacao camada"),
            ("activity", "Potencia de saida da porta da OLT", "", self.acao_potencia_porta,
             "dbm sinal transmissao tx laser"),
            ("rotate-cw", "Girar (vertical / horizontal)", "", self.acao_girar_dio,
             "virar deitar em pe orientacao"),
            ("trash-2", "Excluir equipamento", "", self.acao_remover_equipamento,
             "remover apagar deletar"),
            ("map-pin", "Localizacao do diagrama (mapa)", "", self.acao_local,
             "mapa local gps coordenada endereco pop cto ceo caixa emenda onde fica"),
            ("map", "Abrir no Google Maps", "", self.acao_google_maps,
             "mapa google maps navegador rota como chegar"),
            ("globe", "Abrir no Google Earth", "", self.acao_google_earth,
             "google earth satelite 3d navegador"),
            ("route", "Rastrear caminho da fibra", "Ctrl+F", self.acao_rastrear,
             "perda potencia db sinal caminho"),
            ("x", "Limpar destaque do rastreio", "", self.acao_limpar_destaque, "tirar"),
            ("triangle-alert", "Pendencias e capacidade", "F5", self.acao_pendencias,
             "erros problemas portas livres ocupacao"),
            ("search", "Busca avancada (tabela)", "", self.acao_busca_avancada,
             "procurar cliente porta"),
            ("layout-grid", "Organizar layout", "", self.acao_organizar,
             "arrumar colunas alinhar"),
            ("maximize-2", "Centralizar o diagrama", "", lambda: self.atualizar_tudo(True),
             "enquadrar ajustar tela zoom"),
            ("zoom-in", "Aproximar", "", lambda: self.aplicar_zoom(1.2), "zoom mais"),
            ("zoom-out", "Afastar", "", lambda: self.aplicar_zoom(1 / 1.2), "zoom menos"),
            ("undo-2", "Desfazer", "Ctrl+Z", self.acao_desfazer, "voltar"),
            ("redo-2", "Refazer", "Ctrl+Y", self.acao_refazer, ""),
            ("file-plus", "Novo diagrama", "", self.acao_nova, "novo criar pop cto ceo caixa"),
            ("download", "Importar diagrama de arquivo", "Ctrl+O", self.acao_abrir,
             "abrir arquivo carregar json importar enviar servidor"),
            ("save", "Salvar", "Ctrl+S", self.acao_salvar, "gravar arquivo"),
            ("save", "Salvar como copia", "", self.acao_salvar_como, "gravar copia duplicar servidor"),
            ("download", "Exportar diagrama", "", self.acao_exportar,
             "pdf svg ps imagem imprimir"),
            ("file-text", "Relatorio PDF completo", "", self.acao_relatorio,
             "exportar imprimir tabela"),
            ("file-down", "Planilha para o Excel (CSV)", "", self.acao_relatorio_csv,
             "exportar csv excel tabela"),
            ("circle-help", "Como usar", "F1", self.acao_ajuda, "ajuda manual"),
            ("activity", "Autoteste", "", self.acao_autoteste, "verificar diagnostico"),
            ("x", "Sair do WaspFiber", "", self.acao_sair, "fechar"),
        ]

    # comandos mostrados quando a paleta abre sem nada digitado
    PALETA_INICIAL = ("Novo equipamento", "Rastrear caminho da fibra",
                      "Pendencias e capacidade", "Salvar", "Inicio (cidades e diagramas)",
                      "Exportar diagrama", "Relatorio PDF completo", "Organizar layout")

    def _itens_menu(self):
        c = {nome: (ic, nome, atalho, fn) for ic, nome, atalho, fn, _ in self._comandos()}
        grupo = lambda *nomes: [c[n] for n in nomes]
        return (grupo("Inicio (cidades e diagramas)") + [None]
                + grupo("Novo diagrama", "Salvar", "Salvar como copia",
                        "Importar diagrama de arquivo") + [None]
                + grupo("Exportar diagrama", "Relatorio PDF completo",
                        "Planilha para o Excel (CSV)") + [None]
                + grupo("Localizacao do diagrama (mapa)", "Abrir no Google Maps",
                        "Abrir no Google Earth") + [None]
                + grupo("Criar varios equipamentos", "Pendencias e capacidade") + [None]
                + grupo("Como usar", "Autoteste", "Sair do WaspFiber"))

    # ---------------- aparencia ----------------
    def _aplicar_estilo(self):
        """Veste a janela inteira com o tema ativo: cores, tipografia e
        bordas. O tkinter so deixa customizar a fundo com o tema 'clam'."""
        t = TEMA
        self.configure(bg=t["ui_fundo"])
        try:
            import tkinter.font as tkfont
            familia = "Segoe UI" if sys.platform.startswith("win") else "DejaVu Sans"
            disponiveis = set(tkfont.families(self))
            if familia not in disponiveis:
                familia = "TkDefaultFont"
            for nome, tamanho in (("TkDefaultFont", 9), ("TkTextFont", 9),
                                  ("TkMenuFont", 9), ("TkHeadingFont", 9)):
                try:
                    fonte = tkfont.nametofont(nome)
                    if familia != "TkDefaultFont":
                        fonte.configure(family=familia, size=tamanho)
                except tk.TclError:
                    pass
            self.fonte_ui = familia if familia != "TkDefaultFont" else "TkDefaultFont"
            self.fonte_titulo = ("Segoe UI Semibold" if "Segoe UI Semibold" in disponiveis
                                 else self.fonte_ui)
        except Exception:
            self.fonte_ui = "TkDefaultFont"
            self.fonte_titulo = "TkDefaultFont"

        estilo = ttk.Style(self)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure(".", background=t["ui_fundo"], foreground=t["ui_texto"],
                         fieldbackground=t["ui_campo"], bordercolor=t["ui_borda"],
                         lightcolor=t["ui_borda"], darkcolor=t["ui_borda"],
                         focuscolor=t["ui_acento"], borderwidth=0)
        estilo.configure("TFrame", background=t["ui_fundo"])
        estilo.configure("Painel.TFrame", background=t["ui_painel"])
        estilo.configure("TLabel", background=t["ui_fundo"], foreground=t["ui_texto"])
        estilo.configure("Fraco.TLabel", foreground=t["ui_texto_fraco"])
        estilo.configure("Secao.TLabel", foreground=t["ui_texto_fraco"],
                         font=(self.fonte_ui, 8))
        estilo.configure("Titulo.TLabel", foreground=t["ui_texto"],
                         font=(self.fonte_ui, 11, "bold"))
        estilo.configure("Status.TLabel", background=t["ui_painel"],
                         foreground=t["ui_texto_fraco"])

        estilo.configure("TButton", background=t["ui_painel"], foreground=t["ui_texto"],
                         borderwidth=0, focusthickness=0, padding=(6, 6),
                         relief="flat", anchor="center")
        estilo.map("TButton",
                   background=[("pressed", t["ui_acento"]), ("active", t["ui_hover"])],
                   foreground=[("pressed", t["ui_acento_texto"])])
        estilo.configure("Acento.TButton", background=t["ui_acento"],
                         foreground=t["ui_acento_texto"])
        estilo.map("Acento.TButton", background=[("active", t["ui_acento"])])
        estilo.configure("Discreto.TButton", background=t["ui_fundo"],
                         foreground=t["ui_texto_fraco"], padding=(2, 5),
                         font=(self.fonte_ui, 8))
        estilo.map("Discreto.TButton", background=[("active", t["ui_hover"])],
                   foreground=[("active", t["ui_texto"])])

        estilo.configure("Treeview", background=t["ui_painel"],
                         fieldbackground=t["ui_painel"], foreground=t["ui_texto"],
                         borderwidth=0, rowheight=22)
        estilo.map("Treeview", background=[("selected", t["ui_acento"])],
                   foreground=[("selected", t["ui_acento_texto"])])
        estilo.configure("Treeview.Heading", background=t["ui_fundo"],
                         foreground=t["ui_texto_fraco"], borderwidth=0,
                         relief="flat", padding=(6, 4))
        estilo.map("Treeview.Heading", background=[("active", t["ui_hover"])])
        estilo.configure("Lateral.Treeview", background=t["ui_fundo"],
                         fieldbackground=t["ui_fundo"], foreground=t["ui_texto"],
                         borderwidth=0, rowheight=24, indent=14)
        estilo.map("Lateral.Treeview", background=[("selected", t["ui_hover"])],
                   foreground=[("selected", t["ui_acento"])])
        estilo.layout("Lateral.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        for classe in ("TEntry", "TCombobox", "TSpinbox"):
            estilo.configure(classe, fieldbackground=t["ui_campo"],
                             background=t["ui_campo"], foreground=t["ui_texto"],
                             bordercolor=t["ui_borda"], arrowcolor=t["ui_texto_fraco"],
                             insertcolor=t["ui_texto"], padding=4)
        estilo.map("TCombobox", fieldbackground=[("readonly", t["ui_campo"])],
                   foreground=[("readonly", t["ui_texto"])])
        self.option_add("*TCombobox*Listbox.background", t["ui_painel"])
        self.option_add("*TCombobox*Listbox.foreground", t["ui_texto"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["ui_acento"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["ui_acento_texto"])

        estilo.configure("TScrollbar", background=t["ui_borda"], troughcolor=t["ui_fundo"],
                         bordercolor=t["ui_fundo"], arrowcolor=t["ui_texto_fraco"],
                         width=10)
        estilo.map("TScrollbar", background=[("active", t["ui_texto_fraco"])])
        # barras de rolagem finas, sem as setinhas
        for orient, eixo in (("Vertical", "ns"), ("Horizontal", "we")):
            estilo.layout("%s.TScrollbar" % orient, [
                ("%s.Scrollbar.trough" % orient, {"sticky": eixo, "children": [
                    ("%s.Scrollbar.thumb" % orient, {"expand": "1", "sticky": "nswe"})]})])
        estilo.configure("TScrollbar", arrowsize=8, gripcount=0)
        estilo.configure("TSeparator", background=t["ui_borda"])
        estilo.configure("TLabelframe", background=t["ui_fundo"],
                         bordercolor=t["ui_borda"], foreground=t["ui_texto_fraco"])
        estilo.configure("TLabelframe.Label", background=t["ui_fundo"],
                         foreground=t["ui_texto_fraco"])
        estilo.configure("TNotebook", background=t["ui_fundo"], borderwidth=0)
        estilo.configure("TNotebook.Tab", background=t["ui_fundo"],
                         foreground=t["ui_texto_fraco"], padding=(14, 7), borderwidth=0)
        estilo.map("TNotebook.Tab", background=[("selected", t["ui_painel"])],
                   foreground=[("selected", t["ui_texto"])])
        estilo.configure("TRadiobutton", background=t["ui_fundo"],
                         foreground=t["ui_texto"], indicatorcolor=t["ui_campo"])
        estilo.map("TRadiobutton", indicatorcolor=[("selected", t["ui_acento"])],
                   background=[("active", t["ui_fundo"])])
        estilo.configure("TCheckbutton", background=t["ui_fundo"],
                         foreground=t["ui_texto"], indicatorcolor=t["ui_campo"])

        # widgets classicos (listbox, text, menu) nao usam ttk
        self.option_add("*Listbox.background", t["ui_painel"])
        self.option_add("*Listbox.foreground", t["ui_texto"])
        self.option_add("*Listbox.selectBackground", t["ui_acento"])
        self.option_add("*Listbox.selectForeground", t["ui_acento_texto"])
        self.option_add("*Listbox.highlightThickness", 0)
        self.option_add("*Listbox.borderWidth", 0)
        self.option_add("*Text.background", t["ui_campo"])
        self.option_add("*Text.foreground", t["ui_texto"])
        self.option_add("*Text.insertBackground", t["ui_texto"])
        self.option_add("*Text.highlightThickness", 0)
        self.option_add("*Menu.background", t["ui_painel"])
        self.option_add("*Menu.foreground", t["ui_texto"])
        self.option_add("*Menu.activeBackground", t["ui_acento"])
        self.option_add("*Menu.activeForeground", t["ui_acento_texto"])
        self.option_add("*Menu.borderWidth", 0)
        self.option_add("*Menu.relief", "flat")
        self.option_add("*Toplevel.background", t["ui_fundo"])
        # widgets classicos que nao vem do ttk: o corpo dos dialogos (Frame),
        # e os campos/botoes da caixinha de pergunta (askstring)
        self.option_add("*Frame.background", t["ui_fundo"])
        self.option_add("*Label.background", t["ui_fundo"])
        self.option_add("*Label.foreground", t["ui_texto"])
        self.option_add("*Entry.background", t["ui_campo"])
        self.option_add("*Entry.foreground", t["ui_texto"])
        self.option_add("*Entry.insertBackground", t["ui_texto"])
        self.option_add("*Entry.selectBackground", t["ui_acento"])
        self.option_add("*Entry.selectForeground", t["ui_acento_texto"])
        self.option_add("*Entry.relief", "flat")
        self.option_add("*Entry.highlightThickness", 1)
        self.option_add("*Entry.highlightBackground", t["ui_borda"])
        self.option_add("*Entry.highlightColor", t["ui_acento"])
        self.option_add("*Button.background", t["ui_painel"])
        self.option_add("*Button.foreground", t["ui_texto"])
        self.option_add("*Button.activeBackground", t["ui_hover"])
        self.option_add("*Button.activeForeground", t["ui_texto"])
        self.option_add("*Button.relief", "flat")
        self.option_add("*Button.borderWidth", 0)
        self.option_add("*Button.highlightThickness", 0)
        self.option_add("*Button.padX", 14)
        self.option_add("*Button.padY", 4)

    def _secao(self, pai, texto):
        """Titulo de secao: maiusculas pequenas e discretas, com uma regua."""
        quadro = ttk.Frame(pai)
        quadro.pack(fill="x", pady=(14, 6))
        ttk.Label(quadro, text=espacado(texto.upper()),
                  style="Secao.TLabel").pack(anchor="w")
        ttk.Separator(quadro, orient="horizontal").pack(fill="x", pady=(5, 0))
        return quadro

    def _montar_layout(self):
        """Layout 'minimo + Ctrl+K' (B0.24): barra fina no topo com o campo de
        comando, equipamentos em cartoes na lateral e o diagrama ocupando o
        resto, com os controles de zoom flutuando no canto."""
        t = TEMA
        BotaoIcone = nix_ui.BotaoIcone
        self._sel_eq_id = None
        self.cartoes = {}
        self.paleta = None

        # ----- rodape -----
        rodape = tk.Frame(self, bg=t["ui_painel"])
        rodape.pack(fill="x", side="bottom")
        self.status = ttk.Label(rodape, text="Pronto.", style="Status.TLabel")
        self.status.pack(side="left", padx=14, pady=5)
        self.status_direita = ttk.Label(rodape, text="Ctrl K  comandos     F1  ajuda",
                                        style="Status.TLabel")
        self.status_direita.pack(side="right", padx=14)

        # ----- barra do topo -----
        barra = tk.Frame(self, bg=t["ui_fundo"])
        barra.pack(fill="x", padx=14, pady=10)
        tk.Frame(self, bg=t["ui_borda"], height=1).pack(fill="x")
        BotaoIcone(barra, t, "house", dica="Inicio: cidades e diagramas",
                   comando=self.mostrar_inicio).pack(side="left", padx=(0, 8))
        marca = tk.Label(barra, image=nix_ui.logo(32), bg=t["ui_fundo"])
        marca.pack(side="left")
        nix_ui.Tooltip(marca, "%s %s" % (APP_NOME, VERSAO), t)
        self.lbl_arquivo = tk.Label(barra, text="", bg=t["ui_fundo"], fg=t["ui_texto"],
                                    font=(self.fonte_titulo, 10))
        self.lbl_arquivo.pack(side="left", padx=(10, 0))
        self.lbl_alterado = tk.Label(barra, text="", bg=t["ui_fundo"], fg=t["ui_acento"],
                                     font=(self.fonte_ui, 10))
        self.lbl_alterado.pack(side="left", padx=(4, 0))
        nix_ui.Tooltip(self.lbl_alterado, "Alteracoes nao salvas (Ctrl+S)", t)
        # B0.34: onde fica este diagrama (POP / caixa de emenda / CTO)
        self.botao_local = BotaoIcone(barra, t, "map-pin", texto="Definir localizacao",
                                      comando=self.acao_local, variante="normal")
        self.botao_local.pack(side="left", padx=(14, 0))
        self.dica_local = nix_ui.Tooltip(self.botao_local, "Localizacao do diagrama no mapa", t)

        self.botao_menu = BotaoIcone(barra, t, "ellipsis", dica="Menu")
        self.botao_menu.pack(side="right")
        self.menu_principal = nix_ui.MenuSuspenso(self.botao_menu, t, self._itens_menu(),
                                                  alinhar="direita")
        self.botao_menu.comando = self.menu_principal.abrir
        BotaoIcone(barra, t, "redo-2", dica="Refazer  (Ctrl+Y)",
                   comando=self.acao_refazer).pack(side="right")
        BotaoIcone(barra, t, "undo-2", dica="Desfazer  (Ctrl+Z)",
                   comando=self.acao_desfazer).pack(side="right")

        # campo de comando no meio: clicar (ou Ctrl+K) abre a paleta
        self.campo_comando = tk.Frame(barra, bg=t["ui_painel"], cursor="xterm",
                                      highlightthickness=1, highlightbackground=t["ui_borda"])
        self.campo_comando.pack(side="left", expand=True, padx=40)
        partes = (tk.Label(self.campo_comando, image=nix_ui.icone("search", "fraco"),
                           bg=t["ui_painel"]),
                  tk.Label(self.campo_comando, text="Buscar ou executar um comando...",
                           bg=t["ui_painel"], fg=t["ui_texto_fraco"], width=46, anchor="w",
                           font=(self.fonte_ui, 9)),
                  tk.Label(self.campo_comando, text="Ctrl K", bg=t["ui_borda"],
                           fg=t["ui_texto_fraco"], font=(self.fonte_ui, 8), padx=6))
        partes[0].pack(side="left", padx=(10, 6), pady=6)
        partes[1].pack(side="left")
        partes[2].pack(side="left", padx=8)
        for parte in (self.campo_comando,) + partes:
            parte.bind("<ButtonRelease-1>", lambda _e: self.abrir_paleta())

        # ----- barra lateral -----
        lateral = tk.Frame(self, bg=t["ui_fundo"], width=280)
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        topo = tk.Frame(lateral, bg=t["ui_fundo"])
        topo.pack(fill="x", padx=(16, 8), pady=(6, 6))
        self.lbl_qtd_eq = tk.Label(topo, text=espacado("EQUIPAMENTOS"), bg=t["ui_fundo"],
                                   fg=t["ui_texto_fraco"], font=(self.fonte_ui, 8))
        self.lbl_qtd_eq.pack(side="left")
        BotaoIcone(topo, t, "plus", dica="Novo equipamento",
                   comando=self.acao_novo_equipamento).pack(side="right")
        BotaoIcone(topo, t, "layers", dica="Criar varios",
                   comando=self.acao_criar_lote).pack(side="right")

        # detalhe do equipamento selecionado (some quando nao ha selecao)
        self.painel_detalhe = tk.Frame(lateral, bg=t["ui_fundo"], height=340)
        self.painel_detalhe.pack_propagate(False)
        self._montar_detalhe(self.painel_detalhe)

        # lista de cartoes com rolagem
        quadro_lista = tk.Frame(lateral, bg=t["ui_fundo"])
        quadro_lista.pack(fill="both", expand=True)
        self._quadro_lista = quadro_lista
        barra_lista = ttk.Scrollbar(quadro_lista, orient="vertical")
        self.tela_cartoes = tk.Canvas(quadro_lista, bg=t["ui_fundo"], highlightthickness=0,
                                      bd=0, yscrollcommand=nix_ui.rolagem_automatica(barra_lista))
        barra_lista.configure(command=self.tela_cartoes.yview)
        self.tela_cartoes.pack(side="left", fill="both", expand=True)
        self.quadro_cartoes = tk.Frame(self.tela_cartoes, bg=t["ui_fundo"])
        janela_id = self.tela_cartoes.create_window(0, 0, window=self.quadro_cartoes,
                                                    anchor="nw")
        self.quadro_cartoes.bind("<Configure>", lambda _e: self.tela_cartoes.configure(
            scrollregion=self.tela_cartoes.bbox("all")))
        self.tela_cartoes.bind("<Configure>", lambda e: self.tela_cartoes.itemconfigure(
            janela_id, width=e.width))
        for alvo in (self.tela_cartoes, self.quadro_cartoes):
            alvo.bind("<MouseWheel>", self._rolar_cartoes)
            alvo.bind("<Button-4>", self._rolar_cartoes)
            alvo.bind("<Button-5>", self._rolar_cartoes)
        self.vazio = tk.Frame(self.quadro_cartoes, bg=t["ui_fundo"])
        tk.Label(self.vazio, text="Nenhum equipamento ainda.", bg=t["ui_fundo"],
                 fg=t["ui_texto_fraco"], font=(self.fonte_ui, 9)).pack(anchor="w", pady=(18, 10))
        BotaoIcone(self.vazio, t, "plus", texto="Novo equipamento", variante="acento",
                   comando=self.acao_novo_equipamento).pack(anchor="w", pady=2)

        tk.Frame(self, bg=t["ui_borda"], width=1).pack(side="left", fill="y")

        # ----- diagrama -----
        direita = tk.Frame(self, bg=t["fundo"])
        direita.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(direita, bg=TEMA["fundo"], highlightthickness=0, borderwidth=0,
                                closeenough=4.0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._fundo_press)
        self.canvas.bind("<B1-Motion>", self._fundo_motion)
        self.canvas.bind("<ButtonRelease-1>", self._fundo_release)
        self.canvas.bind("<Configure>", lambda _e: self.rede.equipamentos or
                         self._desenhar_canvas())        # rede vazia: recentraliza o convite
        self.canvas.bind("<MouseWheel>", self._roda)              # Windows/Mac
        self.canvas.bind("<Button-4>", lambda e: self.aplicar_zoom(1.2, (e.x, e.y)))   # Linux
        self.canvas.bind("<Button-5>", lambda e: self.aplicar_zoom(1 / 1.2, (e.x, e.y)))

        # dica flutuante no alto do diagrama (aparece so quando ha porta escolhida)
        self.lbl_dica = tk.Label(direita, text="", bg=t["ui_painel"], fg=t["ui_texto"],
                                 padx=14, pady=7, font=(self.fonte_ui, 9))

        # controles flutuando no canto do diagrama
        flutuante = tk.Frame(direita, bg=t["ui_painel"])
        flutuante.place(relx=1.0, rely=1.0, x=-18, y=-18, anchor="se")
        BotaoIcone(flutuante, t, "zoom-out", dica="Afastar", variante="normal",
                   comando=lambda: self.aplicar_zoom(1 / 1.2)).pack(side="left")
        self.lbl_zoom = tk.Label(flutuante, text="100%", bg=t["ui_painel"],
                                 fg=t["ui_texto_fraco"], width=5, font=(self.fonte_ui, 8))
        self.lbl_zoom.pack(side="left")
        BotaoIcone(flutuante, t, "zoom-in", dica="Aproximar", variante="normal",
                   comando=lambda: self.aplicar_zoom(1.2)).pack(side="left")
        tk.Frame(flutuante, bg=t["ui_borda"], width=1, height=18).pack(side="left", padx=4)
        BotaoIcone(flutuante, t, "maximize-2", dica="Centralizar", variante="normal",
                   comando=lambda: self.atualizar_tudo(centralizar=True)).pack(side="left")
        self.botao_potencia = BotaoIcone(flutuante, t, "activity", variante="acento",
                                         dica="Mostrar / ocultar a potencia (dBm)  (P)",
                                         comando=self.acao_alternar_potencia)
        self.botao_potencia.pack(side="left")
        BotaoIcone(flutuante, t, "layout-grid", dica="Organizar layout", variante="normal",
                   comando=self.acao_organizar).pack(side="left")

        self.menu_contexto = nix_ui.MenuSuspenso(self.canvas, t, [])
        # Esc fecha o que estiver aberto; clique fora fecha a paleta
        self.bind_all("<ButtonPress-1>", self._clique_fora_da_paleta, add="+")

    def _montar_detalhe(self, pai):
        t = TEMA
        BotaoIcone = nix_ui.BotaoIcone
        tk.Frame(pai, bg=t["ui_borda"], height=1).pack(fill="x")
        cab = tk.Frame(pai, bg=t["ui_fundo"])
        cab.pack(fill="x", padx=(12, 8), pady=(10, 2))
        self.det_icone = tk.Label(cab, bg=t["ui_fundo"])
        self.det_icone.pack(side="left")
        self.det_nome = tk.Label(cab, text="", bg=t["ui_fundo"], fg=t["ui_texto"],
                                 anchor="w", font=(self.fonte_ui, 10))
        self.det_nome.pack(side="left", padx=(8, 0), fill="x", expand=True)
        acoes = tk.Frame(pai, bg=t["ui_fundo"])
        acoes.pack(fill="x", padx=(8, 8), pady=(0, 4))
        for nome, dica, cmd in (("pencil", "Editar equipamento", self.acao_editar_equipamento),
                                ("copy", "Duplicar  (Ctrl+D)", self.acao_duplicar_equipamento),
                                ("arrow-left-right", "Inverter lado das portas",
                                 self.acao_inverter_lado),
                                ("rotate-cw", "Girar (vertical / horizontal)",
                                 self.acao_girar_dio),
                                ("route", "Rastrear a porta escolhida  (Ctrl+F)",
                                 self.acao_rastrear),
                                ("trash-2", "Excluir equipamento",
                                 self.acao_remover_equipamento)):
            BotaoIcone(acoes, t, nome, dica=dica, comando=cmd).pack(side="left")

        sub = tk.Frame(pai, bg=t["ui_fundo"])
        sub.pack(fill="x", padx=(16, 8), pady=(6, 2))
        self.det_titulo_portas = tk.Label(sub, text=espacado("PORTAS"), bg=t["ui_fundo"],
                                          fg=t["ui_texto_fraco"], font=(self.fonte_ui, 8))
        self.det_titulo_portas.pack(side="left")
        self.det_botoes_modulo = tk.Frame(sub, bg=t["ui_fundo"])
        self.det_botoes_modulo.pack(side="right")
        for nome, dica, cmd in (("trash-2", "Excluir o modulo escolhido", self.acao_remover_modulo),
                                ("pencil", "Editar o modulo escolhido", self.acao_editar_modulo),
                                ("plus", "Novo modulo", self.acao_novo_modulo)):
            BotaoIcone(self.det_botoes_modulo, t, nome, dica=dica,
                       comando=cmd).pack(side="right")

        quadro = tk.Frame(pai, bg=t["ui_fundo"])
        quadro.pack(fill="both", expand=True, padx=(8, 4), pady=(0, 6))
        barra = ttk.Scrollbar(quadro, orient="vertical")
        self.arvore = ttk.Treeview(quadro, columns=("info",), show="tree",
                                   style="Lateral.Treeview", selectmode="browse",
                                   yscrollcommand=nix_ui.rolagem_automatica(barra))
        barra.configure(command=self.arvore.yview)
        self.arvore.column("#0", width=150)
        self.arvore.column("info", width=70, anchor="e")
        self.arvore.pack(side="left", fill="both", expand=True)
        self.arvore.bind("<Double-Button-1>", lambda _: self.acao_abrir_item_arvore())
        self.arvore.bind("<Return>", lambda _: self.acao_abrir_item_arvore())
        self.arvore.tag_configure("livre", foreground=t["ui_texto_fraco"])
        self.arvore.tag_configure("uso", foreground=t["ui_ok"])
        self.arvore.tag_configure("modulo", foreground=t["ui_texto"])

    def _rolar_cartoes(self, evento):
        if getattr(evento, "num", None) == 4 or getattr(evento, "delta", 0) > 0:
            passo = -1
        else:
            passo = 1
        if self.tela_cartoes.yview() != (0.0, 1.0):
            self.tela_cartoes.yview_scroll(passo * 2, "units")
        return "break"

    def _mostrar_dica(self, texto):
        """Balao no alto do diagrama; texto vazio esconde."""
        if texto:
            self.lbl_dica.configure(text=texto)
            self.lbl_dica.place(relx=0.5, y=14, anchor="n")
            self.lbl_dica.lift()
        else:
            self.lbl_dica.place_forget()

    def _tecla_esc(self, _evento=None):
        """Esc fecha, nesta ordem: paleta, menu, porta escolhida, destaque."""
        if self.paleta is not None:
            self.fechar_paleta()
        elif self.menu_principal.aberto():
            self.menu_principal.fechar()
        elif self.menu_contexto.aberto():
            self.menu_contexto.fechar()
        elif self.porta_selecionada is not None:
            self._limpar_selecao()
        elif self.destaque:
            self.acao_limpar_destaque()

    # ---------------- paleta de comandos (Ctrl+K) ----------------
    def abrir_paleta(self, texto=""):
        if getattr(self, "tela_inicio", None) is not None and self.tela_inicio.visivel():
            return
        """Campo unico pra achar qualquer comando OU qualquer coisa na rede
        (equipamento, modulo, cliente, porta). Setas escolhem, Enter executa."""
        if self.paleta is not None:
            self.fechar_paleta()
            return
        self.menu_principal.fechar()
        t = TEMA
        self.paleta = tk.Frame(self, bg=t["ui_borda"])
        corpo = tk.Frame(self.paleta, bg=t["ui_painel"])
        corpo.pack(padx=1, pady=1, fill="both")
        linha = tk.Frame(corpo, bg=t["ui_painel"])
        linha.pack(fill="x", padx=12, pady=10)
        tk.Label(linha, image=nix_ui.icone("search", "acento"),
                 bg=t["ui_painel"]).pack(side="left")
        self.var_paleta = tk.StringVar(value=texto)
        self.e_paleta = tk.Entry(linha, textvariable=self.var_paleta, bg=t["ui_painel"],
                                 fg=t["ui_texto"], insertbackground=t["ui_texto"],
                                 relief="flat", bd=0, highlightthickness=0, width=52,
                                 font=(self.fonte_ui, 11))
        self.e_paleta.pack(side="left", padx=8, fill="x", expand=True)
        tk.Frame(corpo, bg=t["ui_borda"], height=1).pack(fill="x")
        self.lista_paleta = tk.Frame(corpo, bg=t["ui_painel"])
        self.lista_paleta.pack(fill="x", pady=4)
        tk.Label(corpo, text="ENTER executa   ·   setas escolhem   ·   ESC fecha",
                 bg=t["ui_painel"], fg=t["ui_texto_fraco"],
                 font=(self.fonte_ui, 8)).pack(anchor="w", padx=12, pady=(2, 8))

        self.e_paleta.bind("<Down>", lambda _e: self._mover_paleta(1))
        self.e_paleta.bind("<Up>", lambda _e: self._mover_paleta(-1))
        self.e_paleta.bind("<Return>", lambda _e: self._executar_paleta())
        self.e_paleta.bind("<KP_Enter>", lambda _e: self._executar_paleta())
        self.e_paleta.bind("<Escape>", lambda _e: (self.fechar_paleta(), "break")[1])
        self.var_paleta.trace_add("write", lambda *_: self._filtrar_paleta())
        self._filtrar_paleta()

        self.update_idletasks()
        y = self.campo_comando.winfo_rooty() - self.winfo_rooty() - 2
        centro = (self.campo_comando.winfo_rootx() - self.winfo_rootx()
                  + self.campo_comando.winfo_width() // 2)
        meia = self.paleta.winfo_reqwidth() // 2
        centro = max(meia + 6, min(centro, self.winfo_width() - meia - 6))
        self.paleta.place(x=centro, y=max(y, 6), anchor="n")
        self.paleta.lift()
        self.e_paleta.focus_set()
        self.e_paleta.icursor("end")

    def fechar_paleta(self):
        if self.paleta is not None:
            self.paleta.destroy()
            self.paleta = None
            try:
                self.canvas.focus_set()
            except tk.TclError:
                pass

    def _clique_fora_da_paleta(self, evento):
        if self.paleta is None:
            return
        if nix_ui.dentro_de(evento.widget, self.paleta) or \
                nix_ui.dentro_de(evento.widget, self.campo_comando):
            return
        self.fechar_paleta()

    def resultados_paleta(self, texto):
        """Lista (icone, titulo, detalhe/atalho, funcao, secao) pro texto
        digitado. Separada da tela pra poder ser testada."""
        termo = sem_acento(texto).strip()
        comandos = self._comandos()
        if not termo:
            por_nome = {c[1]: c for c in comandos}
            return [(por_nome[n][0], n, por_nome[n][2], por_nome[n][3], "SUGESTOES")
                    for n in self.PALETA_INICIAL if n in por_nome]
        palavras = termo.split()
        no_titulo, nas_extras = [], []
        for ic, nome, atalho, funcao, extras in comandos:
            titulo = sem_acento(nome)
            tudo = titulo + " " + sem_acento(extras)
            if all(p in titulo for p in palavras):
                no_titulo.append((ic, nome, atalho, funcao, "COMANDOS"))
            elif all(p in tudo for p in palavras):
                nas_extras.append((ic, nome, atalho, funcao, "COMANDOS"))
        saida = no_titulo[:6]

        icones = {"modulo": "box", "fusao": "cable", "porta": "activity"}
        achados = buscar(self.rede, texto, limite=40)
        primeira_porta = None
        for achado in achados[:8]:
            if achado["tipo"] == "equipamento":
                eq = self.rede.equipamentos.get(achado["eq_id"])
                ic = nix_ui.ICONE_POR_TIPO.get(eq.tipo if eq else "", "box")
            else:
                ic = icones.get(achado["tipo"], "box")
            detalhe = achado["detalhe"]
            if len(detalhe) > 46:
                detalhe = detalhe[:45] + "\u2026"
            saida.append((ic, achado["titulo"], detalhe,
                          lambda a=achado: self.ir_para(a), "NA REDE"))
            if primeira_porta is None and achado.get("chave") and achado["tipo"] in ("porta", "fusao"):
                primeira_porta = achado
        if primeira_porta is not None:
            chave = primeira_porta["chave"]
            saida.append(("route", "Rastrear a partir de %s" % self.rede.nome_porta(*chave),
                          "", lambda c=chave: self._rastrear_chave(c), "NA REDE"))
        # comandos achados so pelas palavras extras vem depois da rede
        return saida + nas_extras[:max(0, 6 - len(no_titulo))]

    def _filtrar_paleta(self):
        if self.paleta is None:
            return
        t = TEMA
        for filho in self.lista_paleta.winfo_children():
            filho.destroy()
        self._itens_paleta = self.resultados_paleta(self.var_paleta.get())
        self._linhas_paleta = []
        self._indice_paleta = 0
        if not self._itens_paleta:
            tk.Label(self.lista_paleta, text="Nada encontrado.", bg=t["ui_painel"],
                     fg=t["ui_texto_fraco"], font=(self.fonte_ui, 9)).pack(
                anchor="w", padx=14, pady=10)
            return
        secao_atual = None
        for i, (ic, titulo, detalhe, _fn, secao) in enumerate(self._itens_paleta):
            if secao != secao_atual:
                secao_atual = secao
                tk.Label(self.lista_paleta, text=espacado(secao), bg=t["ui_painel"],
                         fg=t["ui_texto_fraco"], font=(self.fonte_ui, 7)).pack(
                    anchor="w", padx=14, pady=(6, 2))
            linha = tk.Frame(self.lista_paleta, bg=t["ui_painel"], cursor="hand2")
            linha.pack(fill="x", padx=4)
            img = tk.Label(linha, image=nix_ui.icone(ic, "fraco"), bg=t["ui_painel"])
            img.pack(side="left", padx=(10, 10), pady=6)
            rot = tk.Label(linha, text=titulo, bg=t["ui_painel"], fg=t["ui_texto"],
                           anchor="w", font=(self.fonte_ui, 9))
            rot.pack(side="left")
            det = tk.Label(linha, text=detalhe, bg=t["ui_painel"], fg=t["ui_texto_fraco"],
                           anchor="e", font=(self.fonte_ui, 8))
            det.pack(side="right", padx=12)
            self._linhas_paleta.append((linha, img, rot, det, ic))
            for parte in (linha, img, rot, det):
                parte.bind("<Enter>", lambda _e, k=i: self._marcar_paleta(k))
                parte.bind("<ButtonRelease-1>", lambda _e, k=i: self._executar_paleta(k))
        self._marcar_paleta(0)

    def _marcar_paleta(self, indice):
        t = TEMA
        if not self._linhas_paleta:
            return
        self._indice_paleta = indice % len(self._linhas_paleta)
        for i, (linha, img, rot, det, ic) in enumerate(self._linhas_paleta):
            ativo = i == self._indice_paleta
            fundo = t["ui_hover"] if ativo else t["ui_painel"]
            for parte in (linha, img, rot, det):
                parte.configure(bg=fundo)
            img.configure(image=nix_ui.icone(ic, "acento" if ativo else "fraco"))

    def _mover_paleta(self, passo):
        self._marcar_paleta(self._indice_paleta + passo)
        return "break"

    def _executar_paleta(self, indice=None):
        if not self._itens_paleta:
            return "break"
        if indice is None:
            indice = self._indice_paleta
        funcao = self._itens_paleta[indice][3]
        self.fechar_paleta()
        self.after(10, funcao)          # depois de fechar: pode abrir um dialogo
        return "break"

    # ---------------- desenho ----------------
    def _potencias(self):
        """Potencia calculada pra camada do diagrama (None se desligada ou
        se nenhuma porta de OLT tem potencia informada)."""
        if not self.mostrar_potencia:
            return None
        calc = calcular_potencias(self.rede)
        return calc if calc["fontes"] else None

    def atualizar_tudo(self, centralizar=False):
        self.cena = montar_cena(self.rede, self.porta_selecionada,
                                destaque=self.destaque, selecao_lote=self.selecao_lote,
                                potencias=self._potencias())
        self._desenhar_canvas()
        if centralizar:
            self._ajustar_zoom_para_caber()
        self._atualizar_listas()
        titulo = APP_NOME
        if self._nome_documento():
            titulo += " - " + self._nome_documento()
        if self.alteracoes_pendentes:
            titulo += "  *(nao salvo)"
        self.title(titulo)

    def _desenhar_canvas(self):
        c = self.canvas
        c.configure(bg=TEMA["fundo"])
        c.delete("all")
        if not self.rede.equipamentos:
            self._desenhar_vazio()
            return
        e = self.escala
        dx, dy = -self.cena.minx, -self.cena.miny

        def px(x, y):
            return ((x + dx) * e, (y + dy) * e)

        for it in self.cena.itens:
            tags = it["tags"]
            if it["t"] == "ret":
                x0, y0 = px(it["x"], it["y"])
                x1, y1 = px(it["x"] + it["w"], it["y"] + it["h"])
                c.create_rectangle(x0, y0, x1, y1, fill=it["fill"] or "",
                                   outline=it["outline"] or "",
                                   width=max(it["lw"] * e, 1.0), tags=tags)
            elif it["t"] == "linha":
                pts = [v for p in it["pts"] for v in px(*p)]
                kw = {}
                if it["dash"]:
                    kw["dash"] = tuple(max(int(d * e), 1) for d in it["dash"])
                c.create_line(*pts, fill=it["cor"], width=max(it["lw"] * e, 1.0),
                              tags=tags, **kw)
            elif it["t"] == "texto":
                if it["tam"] * e < 3.2:
                    continue   # zoom muito pequeno: nem desenha o texto
                x, y = px(it["x"], it["y"])
                tam = max(int(round(it["tam"] * e)), 6)
                familia = getattr(self, "fonte_ui", "Helvetica")
                fonte = (familia, tam, "bold") if it["bold"] else (familia, tam)
                c.create_text(x, y, text=it["s"], font=fonte, fill=it["cor"],
                              anchor={"w": "w", "e": "e", "center": "center"}[it["anc"]],
                              tags=tags)
            elif it["t"] == "oval":
                x, y = px(it["x"], it["y"])
                r = it["r"] * e
                c.create_oval(x - r, y - r, x + r, y + r, outline=it["cor"],
                              width=max(it["lw"] * e, 1.0), tags=tags)

        c.configure(scrollregion=(0, 0, self.cena.largura * e, self.cena.altura * e))
        if hasattr(self, "lbl_zoom"):
            self.lbl_zoom.configure(text="%d%%" % round(e * 100))
        # cliques nas portas e arraste pelos titulos
        for chave in self.cena.portas:
            tag = "porta:%s|%s|%d" % (chave[0], chave[1] or "", chave[2])
            c.tag_bind(tag, "<ButtonPress-1>",
                       lambda ev, k=chave: self._clique_porta(k))
            c.tag_bind(tag, "<Shift-ButtonPress-1>",
                       lambda ev, k=chave: self._clique_porta_shift(k))
        # passar o mouse numa fibra (ou numa porta ligada) acende o caminho
        # e marca as duas portas: da pra ver na hora onde ela chega
        for f in self.rede.fusoes.values():
            tag = "fusao:%s" % f.id
            c.tag_bind(tag, "<Enter>", lambda ev, fid=f.id: self._acender_fusoes([fid]))
            c.tag_bind(tag, "<Leave>", lambda ev: self._apagar_fusoes())
        for chave in self.cena.portas:
            fusoes = self.rede.fusoes_na_porta(*chave)
            if not fusoes:
                continue
            tag = "porta:%s|%s|%d" % (chave[0], chave[1] or "", chave[2])
            ids = [f.id for f in fusoes]
            c.tag_bind(tag, "<Enter>", lambda ev, i=ids: self._acender_fusoes(i))
            c.tag_bind(tag, "<Leave>", lambda ev: self._apagar_fusoes())
        # arrastar: pega o equipamento por qualquer parte (menos pelas portas,
        # que continuam sendo clique pra fundir)
        for chave in self.cena.portas:
            tag = "porta:%s|%s|%d" % (chave[0], chave[1] or "", chave[2])
            c.tag_bind(tag, "<Button-3>", lambda ev, k=chave: self._menu_porta(ev, k))
        for eq_id in self.cena.titulos:
            c.tag_bind("eq:%s" % eq_id, "<Button-3>",
                       lambda ev, i=eq_id: self._menu_equipamento(ev, i))
        for eq_id in self.cena.titulos:
            tag = "eq:%s" % eq_id
            # so o "pegar" fica no item; mover e soltar ficam no canvas (o
            # item embaixo do mouse e redesenhado no meio do arraste - preso
            # a ele, o Tk parava de mandar os movimentos)
            c.tag_bind(tag, "<ButtonPress-1>", lambda ev, i=eq_id: self._titulo_press(ev, i))
            c.tag_bind(tag, "<Enter>", lambda ev: self._cursor_canvas())
            c.tag_bind(tag, "<Leave>", lambda ev: self._cursor_canvas())

    def _desenhar_vazio(self):
        """Rede vazia: no lugar do diagrama, o logo e o caminho pra comecar."""
        c, t = self.canvas, TEMA
        self.update_idletasks()
        cx = max(c.winfo_width(), 400) / 2.0
        cy = max(c.winfo_height(), 300) / 2.0 - 30
        c.configure(scrollregion=(0, 0, c.winfo_width(), c.winfo_height()))
        c.xview_moveto(0)
        c.yview_moveto(0)
        c.create_image(cx, cy - 50, image=nix_ui.logo_emblema())
        familia = getattr(self, "fonte_ui", "TkDefaultFont")
        c.create_text(cx, cy + 40, text="Rede vazia", fill=t["ui_texto"],
                      font=(familia, 12))
        c.create_text(cx, cy + 66, fill=t["ui_texto_fraco"], font=(familia, 9),
                      text="Cadastre um equipamento no + da barra lateral, "
                           "ou aperte Ctrl K e digite o que quer fazer.")
        if hasattr(self, "lbl_zoom"):
            self.lbl_zoom.configure(text="%d%%" % round(self.escala * 100))

    def _acender_fusoes(self, ids):
        c, t, e = self.canvas, TEMA, self.escala
        self._apagar_fusoes()
        textos = []
        for fid in ids:
            f = self.rede.fusoes.get(fid)
            if f is None:
                continue
            for item in c.find_withtag("fusao:%s" % fid):
                if c.type(item) == "line":
                    # 'disabled': o realce nao "pega" o mouse (senao sairia da
                    # linha original e apagaria/acenderia sem parar)
                    c.create_line(*c.coords(item), fill=t["destaque"], state="disabled",
                                  width=max(4.0 * e, 2.5), tags=("acesa",))
            for ponta in f.pontas():
                p = self.cena.portas.get(ponta)
                if p is None:
                    continue
                for (x, y, r) in ((p["x"], p["y"], 14.0), (p["ax"], p["ay"], 7.0)):
                    x = (x - self.cena.minx) * e
                    y = (y - self.cena.miny) * e
                    c.create_oval(x - r * e, y - r * e, x + r * e, y + r * e, state="disabled",
                                  outline=t["destaque"], width=2, tags=("acesa",))
            a, b = f.pontas()
            pot = (self.cena.potencias or {}).get("fusoes", {}).get(fid) \
                if self.cena.potencias else None
            textos.append("%s  \u2194  %s%s%s" % (self.rede.nome_porta(*a), self.rede.nome_porta(*b),
                                                ("   [%s]" % f.rotulo) if f.rotulo else "",
                                                ("   \u00b7   %s" % formatar_dbm(pot))
                                                if pot is not None else ""))
        if textos:
            self.status.config(text="   |   ".join(textos))

    def _apagar_fusoes(self):
        self.canvas.delete("acesa")

    def _ajustar_zoom_para_caber(self):
        self.update_idletasks()
        if not self.rede.equipamentos:
            self.escala = 1.0
            self._desenhar_canvas()
            return
        largura = max(self.canvas.winfo_width(), 200)
        altura = max(self.canvas.winfo_height(), 200)
        if self.cena.largura <= 0 or self.cena.altura <= 0:
            return
        self.escala = max(0.08, min(largura / self.cena.largura,
                                    altura / self.cena.altura, 2.0))
        self._desenhar_canvas()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def aplicar_zoom(self, fator, ancora=None):
        antes = self.escala
        self.escala = max(0.08, min(self.escala * fator, 4.0))
        if abs(self.escala - antes) < 1e-6:
            return
        if ancora is None:
            ancora = (self.canvas.winfo_width() / 2.0, self.canvas.winfo_height() / 2.0)
        mundo_x = self.canvas.canvasx(ancora[0]) / antes
        mundo_y = self.canvas.canvasy(ancora[1]) / antes
        self._desenhar_canvas()
        novo_x = mundo_x * self.escala - ancora[0]
        novo_y = mundo_y * self.escala - ancora[1]
        total_x = max(self.cena.largura * self.escala, 1)
        total_y = max(self.cena.altura * self.escala, 1)
        self.canvas.xview_moveto(max(0.0, novo_x / total_x))
        self.canvas.yview_moveto(max(0.0, novo_y / total_y))

    def _roda(self, evento):
        self.aplicar_zoom(1.2 if evento.delta > 0 else 1 / 1.2, (evento.x, evento.y))

    def centralizar_em(self, x_mundo, y_mundo):
        """Rola a vista pra deixar um ponto do diagrama no centro da tela."""
        self.update_idletasks()
        total_x = max(self.cena.largura * self.escala, 1)
        total_y = max(self.cena.altura * self.escala, 1)
        px = (x_mundo - self.cena.minx) * self.escala - self.canvas.winfo_width() / 2.0
        py = (y_mundo - self.cena.miny) * self.escala - self.canvas.winfo_height() / 2.0
        self.canvas.xview_moveto(min(max(px / total_x, 0.0), 1.0))
        self.canvas.yview_moveto(min(max(py / total_y, 0.0), 1.0))

    # ---------------- barra lateral ----------------
    def _atualizar_listas(self):
        t = TEMA
        self._eqs_ordenados = sorted(self.rede.equipamentos.values(), key=lambda e: e.ordem)
        if self._sel_eq_id not in self.rede.equipamentos:
            self._sel_eq_id = None
        ids = [eq.id for eq in self._eqs_ordenados]
        if ids != list(self.cartoes):
            # entrou ou saiu equipamento: refaz os cartoes
            for cartao in self.cartoes.values():
                cartao.destroy()
            self.cartoes = {}
            for eq in self._eqs_ordenados:
                cartao = nix_ui.CartaoEquipamento(
                    self.quadro_cartoes, t, eq, 0, 0,
                    ao_clicar=self._clicar_cartao,
                    ao_duplo=self.acao_editar_equipamento)
                cartao.ao_rodar(self._rolar_cartoes)
                cartao.pack(fill="x", padx=(8, 4))
                self.cartoes[eq.id] = cartao
        for eq in self._eqs_ordenados:
            usadas, total = self.rede.ocupacao(eq)
            cartao = self.cartoes[eq.id]
            cartao.atualizar(eq, usadas, total)
            cartao.marcar(eq.id == self._sel_eq_id)
        if self._eqs_ordenados:
            self.vazio.pack_forget()
        else:
            self.vazio.pack(fill="x", padx=16)
        self.lbl_qtd_eq.configure(text=espacado("EQUIPAMENTOS") + "   %d" % len(ids)
                                  if ids else espacado("EQUIPAMENTOS"))
        self._atualizar_arvore()

        ocup = [self.rede.ocupacao(e) for e in self.rede.equipamentos.values()
                if not e.is_cabo()]
        usadas, total_portas = sum(o[0] for o in ocup), sum(o[1] for o in ocup)
        self.status.config(text="%d equipamentos   ·   %d fusoes   ·   %d/%d portas em uso"
                           % (len(self.rede.equipamentos), len(self.rede.fusoes),
                              usadas, total_portas))
        self._atualizar_cabecalho()

    def _nome_documento(self):
        doc = getattr(self, "documento", None)
        if doc or self.rede.local.get("nome"):
            return self.rede.local.get("nome") or doc["id"]
        if self.caminho_atual:
            return os.path.basename(self.caminho_atual).split(".")[0]
        return ""

    def _atualizar_cabecalho(self):
        arquivo = self._nome_documento() or "Diagrama sem nome"
        doc = getattr(self, "documento", None)
        cidade = (doc or {}).get("cidade")
        self.lbl_arquivo.configure(text=("%s   ›   %s" % (cidade["titulo"], arquivo))
                                   if cidade else arquivo)
        self.title("%s - %s" % (APP_NOME, arquivo) if doc else APP_NOME)
        aguardando = bool(doc and nuvem.pendente_de(cidade["id"], doc["id"]))
        if self.alteracoes_pendentes:
            self.lbl_alterado.configure(text="•", fg=TEMA["ui_acento"])
        elif aguardando:
            self.lbl_alterado.configure(text="aguardando envio ao servidor", fg=TEMA["ui_aviso"])
        else:
            self.lbl_alterado.configure(text="")
        if hasattr(self, "botao_local"):
            local = self.rede.local
            if mapa.local_preenchido(local):
                texto = mapa.resumo_local(local, com_coordenada=False) or "Local sem nome"
                dica = mapa.resumo_local(local) + (
                    "\nClique para ver no mapa" if local["lat"] is not None
                    else "\nSem coordenada - clique para marcar no mapa")
            else:
                texto, dica = "Definir localizacao", "Localizacao do diagrama no mapa"
            self.botao_local.configure(text=texto)
            self.dica_local.texto = dica
        self.lbl_zoom.configure(text="%d%%" % round(self.escala * 100))

    def _clicar_cartao(self, eq_id):
        self._selecionar_equipamento(eq_id)
        self.ir_para({"eq_id": eq_id, "chave": None})

    def _atualizar_arvore(self):
        self.arvore.delete(*self.arvore.get_children())
        eq = self._eq_selecionado()
        if eq is None:
            self.painel_detalhe.pack_forget()
            return
        if not self.painel_detalhe.winfo_ismapped():
            self.painel_detalhe.pack(side="bottom", fill="x", before=self._quadro_lista)
        self.det_icone.configure(image=nix_ui.icone(
            nix_ui.ICONE_POR_TIPO.get(eq.tipo, "box"), "acento"))
        self.det_nome.configure(text=eq.nome)
        if eq.tem_lados():
            self.det_titulo_portas.configure(
                text=espacado("FIBRAS" if eq.is_cabo() else "PORTAS"))
            self.det_botoes_modulo.pack_forget()
        else:
            self.det_titulo_portas.configure(text=espacado("MODULOS"))
            if not self.det_botoes_modulo.winfo_ismapped():
                self.det_botoes_modulo.pack(side="right")
        for mod in eq.modulos.values():
            usadas_mod = sum(1 for n in mod.portas if self.rede.fusoes_na_porta(eq.id, mod.id, n))
            no = self.arvore.insert("", "end", iid="m|%s|%s" % (eq.id, mod.id),
                                    text=mod.nome,
                                    values=("%d/%d" % (usadas_mod, mod.num_portas),),
                                    tags=("modulo",), open=eq.tem_lados() and len(eq.modulos) == 2
                                    and mod.id == LADO_PADRAO.get(eq.tipo))
            for n in sorted(mod.portas):
                usadas = len(self.rede.fusoes_na_porta(eq.id, mod.id, n))
                limite = self.rede.limite_porta(eq.id, mod.id, n)
                if eq.is_cabo():
                    texto = "Fibra %d  ·  %s" % (n, cor_fibra(n, eq.fibras_por_tubo)[0])
                else:
                    texto = "Porta %s" % self.rede.rotulo_porta(eq.id, mod.id, n)
                self.arvore.insert(no, "end", iid="p|%s|%s|%d" % (eq.id, mod.id, n),
                                   text=texto,
                                   values=("%d/%d" % (usadas, limite),),
                                   tags=("livre" if usadas == 0 else "uso",))

    def _eq_selecionado(self):
        return self.rede.equipamentos.get(getattr(self, "_sel_eq_id", None))

    def _selecionar_equipamento(self, eq_id):
        if eq_id not in self.rede.equipamentos:
            return False
        self._sel_eq_id = eq_id
        for outro, cartao in self.cartoes.items():
            cartao.marcar(outro == eq_id)
        cartao = self.cartoes.get(eq_id)
        if cartao is not None and self._eqs_ordenados:
            # rola a lista ate o cartao
            self.update_idletasks()
            total = max(self.quadro_cartoes.winfo_height(), 1)
            topo = cartao.winfo_y() / float(total)
            vista = self.tela_cartoes.yview()
            if not (vista[0] <= topo <= vista[1] - 0.02):
                self.tela_cartoes.yview_moveto(max(0.0, topo - 0.1))
        self._atualizar_arvore()
        return True

    def _item_arvore(self):
        selecao = self.arvore.selection()
        if not selecao:
            return None
        partes = selecao[0].split("|")
        if partes[0] == "m":
            return ("modulo", partes[1], partes[2], None)
        return ("porta", partes[1], partes[2] or None, int(partes[3]))

    # ---------------- inicio / servidor (B0.39) ----------------
    def mostrar_editor(self):
        if getattr(self, "tela_inicio", None) is not None:
            self.tela_inicio.place_forget()

    def _limpar_editor(self):
        self.rede = Rede()
        self.caminho_atual = None
        self.documento = None
        self.porta_selecionada = None
        self.destaque = set()
        self._historico.clear()
        self._refazer.clear()
        self.alteracoes_pendentes = False

    def mostrar_inicio(self):
        """Volta pra tela das cidades (pergunta antes se ha algo nao salvo)."""
        if self.tela_inicio.visivel():
            return
        if not self._confirmar_descarte("Voltar ao inicio"):
            return
        self.fechar_paleta()
        cidade = (self.documento or {}).get("cidade")
        self._limpar_editor()
        apagar_autosave()
        self.atualizar_tudo(centralizar=True)
        if cidade:
            self.tela_inicio.cidade = cidade
        self.tela_inicio.mostrar()

    def _carregar_documento(self, cidade, diagrama_id, conteudo, versao, nao_enviado=False):
        self.rede = Rede.from_dict(conteudo)
        self.caminho_atual = None
        self.documento = {"cidade": cidade, "id": diagrama_id, "versao": versao}
        self.porta_selecionada = None
        self.destaque = set()
        self._historico.clear()
        self._refazer.clear()
        self.alteracoes_pendentes = nao_enviado
        apagar_autosave()
        self.mostrar_editor()
        self.atualizar_tudo(centralizar=True)

    def _erro_servidor(self, erro, titulo):
        """Mensagem de erro do servidor; sessao vencida pede login de novo.
        Devolve True se a pessoa entrou de novo (vale tentar outra vez)."""
        if erro.status == 401:
            dialogo = DialogEntrar(self)
            if dialogo.conexao:
                self.conexao = dialogo.conexao
                return True
            return False
        messagebox.showwarning(titulo, str(erro))
        return False

    def abrir_diagrama(self, cidade, diagrama_id):
        if not self._confirmar_descarte("Abrir diagrama"):
            return False
        guardado = nuvem.pendente_de(cidade["id"], diagrama_id)
        if guardado:
            # o que ficou neste PC sem chegar no servidor vale mais: abre ele
            self._carregar_documento(cidade, diagrama_id, guardado["conteudo"],
                                     guardado["versao_base"], nao_enviado=True)
            self.status.config(text="Este diagrama tem alteracoes deste computador que ainda "
                                    "nao chegaram no servidor (salve pra enviar).")
            return True
        if not self.conexao:
            messagebox.showwarning("Abrir diagrama", "Entre no servidor primeiro.")
            return False
        try:
            dados = self.conexao.abrir(cidade["id"], diagrama_id)
        except nuvem.ErroServidor as erro:
            if self._erro_servidor(erro, "Abrir diagrama"):
                return self.abrir_diagrama(cidade, diagrama_id)
            return False
        try:
            self._carregar_documento(cidade, diagrama_id, dados["conteudo"], dados["versao"])
        except Exception as erro:
            messagebox.showerror("Abrir diagrama", "O diagrama no servidor esta com defeito:\n%s"
                                 % erro)
            return False
        return True

    def _criar_no_servidor(self, cidade, nome, rede, titulo="Novo diagrama"):
        if not self.conexao:
            messagebox.showwarning(titulo, "Entre no servidor primeiro (tela inicial).")
            return None
        try:
            return self.conexao.criar_diagrama(cidade["id"], nome, rede.to_dict())
        except nuvem.ErroServidor as erro:
            if self._erro_servidor(erro, titulo):
                return self._criar_no_servidor(cidade, nome, rede, titulo)
            if erro.sem_conexao:
                messagebox.showwarning(titulo, "Sem conexao com o servidor: o diagrama novo so "
                                               "pode ser criado com o servidor no ar.")
            return None

    def novo_diagrama(self, cidade):
        """Cria o diagrama de um local (POP / CEO / CTO) na cidade, direto no
        servidor, e abre no editor."""
        dialogo = DialogNovoDiagrama(self, cidade)
        if not dialogo.resultado:
            return None
        tipo, nome, marcar = dialogo.resultado
        rede = Rede()
        rede.definir_local({"tipo": tipo, "nome": nome, "cidade": cidade["titulo"]})
        criado = self._criar_no_servidor(cidade, nome, rede)
        if not criado:
            return None
        self._carregar_documento(cidade, criado["id"], rede.to_dict(), criado["versao"])
        self.status.config(text="Diagrama criado no servidor: %s / %s" % (cidade["titulo"], nome))
        if marcar:
            self.after(150, self.acao_local)
        return criado["id"]

    def importar_diagrama(self, cidade):
        """Manda um .wasp.json deste computador pra cidade (no servidor)."""
        caminho = filedialog.askopenfilename(
            title="Importar diagrama para %s" % cidade["titulo"],
            filetypes=[("Rede WaspFiber (*%s)" % EXTENSAO, "*%s" % EXTENSAO),
                       ("Rede da versao Nix (*%s)" % EXTENSAO_NIX, "*%s" % EXTENSAO_NIX),
                       ("Arquivos da versao FTTX (*.json)", "*.json"),
                       ("Todos (*.*)", "*.*")])
        if not caminho:
            return None
        if not self._confirmar_descarte("Importar diagrama"):
            return None
        try:
            rede = Rede.carregar(caminho)
        except Exception as erro:
            messagebox.showerror("Importar diagrama", "%s\n\n%s" % (caminho, erro))
            return None
        nome = rede.local.get("nome") or os.path.basename(caminho).split(".")[0]
        if not rede.local.get("cidade"):
            rede.local["cidade"] = cidade["titulo"]
        criado = self._criar_no_servidor(cidade, nome, rede, "Importar diagrama")
        if not criado:
            return None
        self._carregar_documento(cidade, criado["id"], rede.to_dict(), criado["versao"])
        self.status.config(text="Importado pro servidor: %s / %s" % (cidade["titulo"], nome))
        return criado["id"]

    def _cidade_em_uso(self):
        return (self.documento or {}).get("cidade") or getattr(self.tela_inicio, "cidade", None)

    def acao_nova(self):
        cidade = self._cidade_em_uso()
        if cidade and self.conexao:
            if self._confirmar_descarte("Novo diagrama"):
                self.novo_diagrama(cidade)
        else:
            self.mostrar_inicio()

    def acao_abrir(self):
        cidade = self._cidade_em_uso()
        if cidade and self.conexao:
            self.importar_diagrama(cidade)
        else:
            messagebox.showinfo("Importar diagrama", "Escolha a cidade na tela inicial antes "
                                                    "de importar um arquivo.")

    def acao_salvar(self):
        if not self.documento:
            return self.acao_salvar_como()
        return self._salvar_no_servidor()

    def _salvar_no_servidor(self, forcar=False):
        doc = self.documento
        cidade = doc["cidade"]
        conteudo = self.rede.to_dict()
        titulo = self.rede.local.get("nome") or doc["id"]
        try:
            if not self.conexao:
                raise nuvem.ErroServidor("Sem login no servidor.", sem_conexao=True)
            r = self.conexao.salvar(cidade["id"], doc["id"], conteudo, doc["versao"], forcar)
        except nuvem.ErroServidor as erro:
            if erro.sem_conexao:
                # guarda neste PC so ate o servidor voltar
                nuvem.enfileirar(cidade["id"], doc["id"], conteudo, doc["versao"], titulo,
                                 cidade["titulo"])
                self.alteracoes_pendentes = False
                apagar_autosave()
                self.status.config(text="Sem conexao com o servidor: guardado neste computador "
                                        "e enviado assim que o servidor voltar.")
                self.atualizar_tudo()
                return True
            if erro.status == 409:
                quem = erro.extra.get("alterado_por") or "outra pessoa"
                quando = erro.extra.get("alterado_em") or ""
                resposta = messagebox.askyesnocancel(
                    "Outra pessoa salvou este diagrama",
                    "%s salvou este diagrama no servidor%s, depois que voce abriu.\n\n"
                    "Sim = salvar a sua versao por cima (a dela fica no historico do servidor)\n"
                    "Nao = salvar a sua como uma COPIA\n"
                    "Cancelar = voltar sem salvar" % (quem, (" em " + quando) if quando else ""))
                if resposta is None:
                    return False
                if resposta:
                    return self._salvar_no_servidor(forcar=True)
                return self.acao_salvar_como()
            if self._erro_servidor(erro, "Salvar"):
                return self._salvar_no_servidor(forcar)
            return False
        doc["versao"] = r["versao"]
        nuvem.tirar_da_fila(cidade["id"], doc["id"])
        self.alteracoes_pendentes = False
        apagar_autosave()
        self.status.config(text="Salvo no servidor: %s / %s" % (cidade["titulo"], titulo))
        self.atualizar_tudo()
        return True

    def acao_salvar_como(self):
        """Salva uma COPIA no servidor, com outro nome, na mesma cidade."""
        cidade = self._cidade_em_uso()
        if not cidade or not self.conexao:
            messagebox.showinfo("Salvar", "Escolha a cidade na tela inicial (casinha) e crie o "
                                          "diagrama por la: tudo fica no servidor.")
            return False
        atual = self.rede.local.get("nome") or "Diagrama"
        nome = perguntar_texto("Salvar como copia", "Nome da copia (fica em %s, no servidor):"
                               % cidade["titulo"], self,
                               initialvalue=(atual + " (copia)") if self.documento else atual)
        if not nome or not nome.strip():
            return False
        nome = nome.strip()
        self.rede.local["nome"] = nome
        criado = self._criar_no_servidor(cidade, nome, self.rede, "Salvar como copia")
        if not criado:
            return False
        self.documento = {"cidade": cidade, "id": criado["id"], "versao": criado["versao"]}
        self.alteracoes_pendentes = False
        apagar_autosave()
        self.status.config(text="Copia salva no servidor: %s / %s" % (cidade["titulo"], nome))
        self.atualizar_tudo()
        return True

    def _sincronizar(self, avisar=False):
        """Manda pro servidor o que ficou guardado sem conexao. Roda sozinho
        a cada minuto (em segundo plano: nao trava a tela)."""
        if getattr(self, "_sincronizando", False):
            return
        if not self.conexao or not nuvem.pendentes():
            if avisar:
                self.status.config(text="Nada aguardando envio." if self.conexao else
                                   "Entre no servidor pra enviar.")
            return
        self._sincronizando = True
        conexao = self.conexao

        def pronto(resultado, erro):
            self._sincronizando = False
            if erro or not resultado:
                return
            doc = self.documento
            for item in resultado.get("detalhes", []):
                if doc and item["cidade"] == doc["cidade"]["id"] and \
                        item["diagrama"] == doc["id"] and item.get("versao"):
                    doc["versao"] = item["versao"]
            partes = []
            if resultado["enviados"]:
                partes.append("%d enviado(s) pro servidor" % len(resultado["enviados"]))
            if resultado["copias"]:
                partes.append("%d virou(aram) copia porque alguem salvou antes: %s"
                              % (len(resultado["copias"]), ", ".join(resultado["copias"])))
            if resultado["falhou"] and avisar:
                partes.append("o servidor ainda nao respondeu")
            if partes:
                self.status.config(text="Diagramas guardados neste PC: " + "; ".join(partes) + ".")
            if self.tela_inicio.visivel() and (resultado["enviados"] or resultado["copias"]):
                self.tela_inicio.atualizar()
            else:
                self.tela_inicio.atualizar_pendentes()
            self._atualizar_cabecalho()
        em_segundo_plano(self, lambda: nuvem.enviar_pendentes(conexao), pronto)

    def _sincronizar_periodico(self):
        self._sincronizar()
        self.after(60000, self._sincronizar_periodico)

    def acao_exemplo(self):
        # B0.38: saiu da interface (menu, paleta e telas). Fica so pro
        # autoteste e pros testes automaticos.
        if not self._confirmar_descarte("Carregar rede de exemplo"):
            return
        self.rede = rede_exemplo()
        self.caminho_atual = None
        self.documento = None
        self.porta_selecionada = None
        self.destaque = set()
        self._historico.clear()
        self._refazer.clear()
        self.alteracoes_pendentes = False
        self.mostrar_editor()
        self.atualizar_tudo(centralizar=True)

    def acao_exportar(self):
        dialogo = DialogFormato(self, [
            ("pdf", "PDF - tema da tela (%s)" % TEMA["nome"]),
            ("pdf_claro", "PDF - fundo claro, pra imprimir"),
            ("svg", "SVG - tema da tela (abre no navegador, da pra editar)"),
            ("svg_claro", "SVG - fundo claro"),
            ("ps", "PS / PostScript (impressao direta)")])
        fmt = dialogo.resultado
        if not fmt:
            return
        tema_saida = TEMA_LINHO if fmt.endswith("_claro") else TEMA
        fmt = fmt.replace("_claro", "")
        caminho = filedialog.asksaveasfilename(
            title="Exportar diagrama", defaultextension="." + fmt,
            filetypes=[("%s (*.%s)" % (fmt.upper(), fmt), "*." + fmt)])
        if not caminho:
            return
        if not caminho.lower().endswith("." + fmt):
            caminho += "." + fmt
        try:
            cena = montar_cena(self.rede, destaque=self.destaque, tema=tema_saida,
                               potencias=self._potencias())
            if fmt == "pdf":
                escrever_pdf([pagina_do_diagrama(cena)], caminho)
            elif fmt == "svg":
                exportar_svg(cena, caminho)
            else:
                # o PostScript tem que cobrir o diagrama INTEIRO, nao so o
                # pedaco visivel na tela
                largura = max(self.cena.largura * self.escala, 1)
                altura = max(self.cena.altura * self.escala, 1)
                self.canvas.postscript(file=caminho, colormode="color",
                                       x=0, y=0, width=largura, height=altura,
                                       pagewidth=min(largura, 2000))
        except Exception as erro:
            messagebox.showerror("Erro ao exportar", str(erro))
            return
        messagebox.showinfo("Exportado", "Diagrama salvo em:\n%s" % caminho)

    def acao_relatorio(self):
        escolha = DialogFormato(self, [
            ("claro", "Fundo claro - pra imprimir (recomendado)"),
            ("tema", "Tema da tela (%s)" % TEMA["nome"])],
            titulo="Relatorio PDF")
        if not escolha.resultado:
            return
        tema_saida = TEMA_LINHO if escolha.resultado == "claro" else TEMA
        caminho = filedialog.asksaveasfilename(title="Exportar relatorio",
                                               defaultextension=".pdf",
                                               initialfile="waspfiber-relatorio.pdf",
                                               filetypes=[("PDF (*.pdf)", "*.pdf")])
        if not caminho:
            return
        if not caminho.lower().endswith(".pdf"):
            caminho += ".pdf"
        try:
            exportar_relatorio_pdf(self.rede, montar_cena(self.rede, tema=tema_saida,
                                                          potencias=self._potencias()),
                                   caminho, tema=tema_saida)
        except Exception as erro:
            messagebox.showerror("Erro ao gerar o relatorio", str(erro))
            return
        messagebox.showinfo("Relatorio gerado",
                            "Salvo em:\n%s\n\nTem o diagrama, a tabela porta a porta, "
                            "as pendencias e a capacidade." % caminho)

    def acao_relatorio_csv(self, tipo=None):
        if tipo is None:
            dialogo = DialogFormato(
                self, [("portas", "Portas e fusoes (tabela completa)"),
                       ("pendencias", "Pendencias (o que merece atencao)"),
                       ("capacidade", "Capacidade (portas livres por equipamento)")],
                titulo="Exportar para Excel")
            tipo = dialogo.resultado
            if not tipo:
                return
        nomes = {"portas": "waspfiber-portas.csv", "pendencias": "waspfiber-pendencias.csv",
                 "capacidade": "waspfiber-capacidade.csv"}
        caminho = filedialog.asksaveasfilename(
            title="Exportar para Excel", defaultextension=".csv",
            initialfile=nomes.get(tipo, "waspfiber.csv"),
            filetypes=[("CSV para Excel (*.csv)", "*.csv")])
        if not caminho:
            return
        if not caminho.lower().endswith(".csv"):
            caminho += ".csv"
        try:
            if tipo == "pendencias":
                exportar_pendencias_csv(self.rede, caminho)
            elif tipo == "capacidade":
                exportar_capacidade_csv(self.rede, caminho)
            else:
                exportar_relatorio_csv(self.rede, caminho)
        except Exception as erro:
            messagebox.showerror("Erro ao gerar o CSV", str(erro))
            return
        messagebox.showinfo("CSV gerado", "Salvo em:\n%s\n\nAbra no Excel para filtrar, "
                                          "ordenar e contar." % caminho)

    def acao_ajuda(self):
        messagebox.showinfo("Como usar", (
            "Ctrl+K abre a PALETA: digite o que quer fazer (\"rastrear\", \"exportar\", "
            "\"novo\") ou o que procura na rede (cliente, equipamento, porta) e "
            "aperte Enter. Tudo o que o programa faz esta ali.\n\n"
            "O botao ... no canto de cima tem o menu (abrir, salvar, exportar).\n\n"
            "INICIO (casinha no topo): as CIDADES e os DIAGRAMAS de cada uma. Cada "
            "cidade e uma pasta; cada POP, caixa de emenda ou CTO e um diagrama dentro "
            "dela. Use uma pasta compartilhada no servidor pra equipe toda.\n\n"
            "1. Na tela inicial (casinha), escolha a cidade e abra ou crie o diagrama "
            "do POP, da caixa de emenda ou da CTO.\n\n"
            "2. O + da barra lateral cadastra um equipamento (DIO, CABO, acomodador, "
            "OLT, switch, RB); o icone ao lado cria "
            "varios de uma vez (DIO-01 ... DIO-24).\n\n"
            "3. Clique num cartao pra escolher o equipamento: embaixo aparecem as "
            "acoes (editar, duplicar, inverter, rastrear, excluir) e a lista de "
            "modulos e portas. Duplo clique numa porta abre GBIC e fusoes.\n\n"
            "4. No diagrama, clique numa porta e depois em outra para fundir. "
            "O DIO tem traseira (fusao da fibra do cabo) e frente (cordao). "
            "Pra fundir varias de uma vez: clique na primeira, Shift+clique na ultima "
            "e depois clique na primeira porta de destino.\n\n"
            "Botao direito no equipamento: inverter lado (tecla I), girar, editar, "
            "duplicar, excluir. Botao direito numa porta da OLT: potencia de saida - o "
            "caminho do sinal aparece marcado em dBm (tecla P liga/desliga).\n\n"
            "Duplo clique numa porta da lista lateral troca o conector (SC/LC), o "
            "polimento (APC verde / UPC azul) e simplex/duplex (duplex e sempre LC).\n\n"
            "5. RASTREAR (Ctrl+F): por onde o sinal passa, perda em dB e potencia "
            "em cada ponta. Esc tira o destaque.\n\n"
            "6. PENDENCIAS (F5): splitter sem entrada, duplex pela metade, nomes "
            "repetidos - e quantas portas ainda estao livres.\n\n"
            "7. LOCALIZACAO: o botao com o pino, no topo, diz de qual local e o "
            "diagrama (POP, caixa de emenda ou CTO). Clique no mapa pra marcar, ou "
            "cole a coordenada / o link do Google Maps. Dali abre no Google Maps "
            "e no Google Earth.\n\n"
            "Arraste o equipamento por qualquer parte pra move-lo; o botao de girar "
            "deita/levanta o DIO. Roda do mouse = zoom; arrastar no vazio = mover a vista. "
            "Ctrl+Z desfaz, Ctrl+S salva. Se fechar no meio do trabalho, o programa "
            "oferece recuperar na proxima abertura."))

    # ---------------- localizacao (B0.34) ----------------
    def acao_local(self):
        dialogo = DialogLocal(self, self.rede.local)
        if dialogo.resultado is None or dialogo.resultado == self.rede.local:
            return
        self._snapshot()
        self.rede.definir_local(dialogo.resultado)
        self._marcar_alterado()
        self.atualizar_tudo()
        self.status.config(text="Localizacao do diagrama: %s"
                           % (mapa.resumo_local(self.rede.local) or "removida"))

    def _abrir_no_google(self, gerar_link, nome):
        local = self.rede.local
        if local.get("lat") is None:
            if messagebox.askyesno(nome, "Este diagrama ainda nao tem coordenada.\n\n"
                                         "Marcar o local no mapa agora?"):
                self.acao_local()
            if self.rede.local.get("lat") is None:
                return
            local = self.rede.local
        import webbrowser
        webbrowser.open(gerar_link(local["lat"], local["lon"]))
        self.status.config(text="Abrindo no %s: %s" % (
            nome, mapa.formatar_coordenada(local["lat"], local["lon"])))

    def acao_google_maps(self):
        self._abrir_no_google(mapa.link_google_maps, "Google Maps")

    def acao_google_earth(self):
        self._abrir_no_google(mapa.link_google_earth, "Google Earth")

    def acao_autoteste(self):
        caminho = os.path.join(pasta_do_programa(), "autoteste.txt")
        try:
            ok = autoteste(caminho)
        except Exception as erro:
            messagebox.showerror("Autoteste", "Falhou: %s" % erro)
            return
        messagebox.showinfo("Autoteste",
                            ("Tudo funcionando." if ok else "Alguma coisa falhou.")
                            + "\n\nDetalhes salvos em:\n%s" % caminho)

    # ---------------- cadastro ----------------
    def _nome_livre(self, nome):
        """Avisa se ja existe outro equipamento com o mesmo nome (confunde nos
        relatorios). O usuario decide se continua."""
        iguais = [e for e in self.rede.equipamentos.values()
                  if (e.nome or "").strip().lower() == (nome or "").strip().lower()]
        if not iguais:
            return True
        return messagebox.askyesno(
            "Nome repetido",
            "Ja existe um equipamento chamado '%s' (%s).\n\nNomes iguais ficam "
            "dificeis de distinguir no relatorio e no diagrama.\n\nContinuar assim?"
            % (iguais[0].nome, iguais[0].id))

    def acao_novo_equipamento(self):
        dialogo = DialogNovoEquipamento(self)
        if not dialogo.resultado:
            return
        nome, tipo, qtd, fpt = dialogo.resultado
        if not self._nome_livre(nome):
            return
        self._snapshot()
        try:
            eq = self.rede.add_equipamento(nome, tipo, qtd if tipo in TIPOS_COM_LADOS else 0,
                                           fibras_por_tubo=fpt)
            if tipo == TIPO_ACOMODADOR:
                for _ in range(qtd):
                    eq.add_splitter("1x8")
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Nao foi possivel criar", str(erro))
            return
        self._marcar_alterado()
        self.atualizar_tudo(centralizar=True)
        self._selecionar_equipamento(eq.id)

    def acao_criar_lote(self):
        """Cadastra uma leva numerada de equipamentos de uma vez (v2.2)."""
        dialogo = DialogLote(self)
        if not dialogo.resultado:
            return
        dados = dialogo.resultado
        self._snapshot()
        try:
            criados = self.rede.criar_em_lote(
                dados["nome_base"], dados["tipo"], dados["quantidade"],
                dados["inicio"], dados["num_portas"], dados["tipo_modulo"],
                dados["qtd_modulos"])
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Nao foi possivel criar", str(erro))
            return
        self._marcar_alterado()
        self.atualizar_tudo(centralizar=True)
        self.status.config(text="%d equipamento(s) criado(s): %s ... %s"
                           % (len(criados), criados[0].nome, criados[-1].nome))

    def acao_duplicar_equipamento(self):
        """Repete o equipamento selecionado com os mesmos modulos (v2.2)."""
        eq = self._eq_selecionado()
        if eq is None:
            messagebox.showinfo("Selecione", "Escolha na lista o equipamento a duplicar.")
            return
        sugestao = proximo_nome(eq.nome, [e.nome for e in self.rede.equipamentos.values()])
        nome = perguntar_texto("Duplicar equipamento",
                                      "Nome da copia de '%s':" % eq.nome,
                                      initialvalue=sugestao, parent=self)
        if not nome:
            return
        self._snapshot()
        try:
            copia = self.rede.duplicar_equipamento(eq.id, nome.strip())
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Nao foi possivel duplicar", str(erro))
            return
        self._marcar_alterado()
        self.atualizar_tudo()
        self._selecionar_equipamento(copia.id)
        self.status.config(text="'%s' duplicado como '%s' (%d modulo(s), sem fusoes)."
                           % (eq.nome, copia.nome, len(copia.modulos)))

    def acao_organizar(self):
        """Arruma as caixas em colunas, sem sobreposicao (v2.2)."""
        if not self.rede.equipamentos:
            return
        self._snapshot()
        movidos = self.rede.organizar_layout()
        self._marcar_alterado()
        self.atualizar_tudo(centralizar=True)
        self.status.config(text="Layout organizado (%d caixa(s) movida(s)). "
                                "Ctrl+Z volta como estava." % movidos)

    def acao_editar_equipamento(self):
        eq = self._eq_selecionado()
        if eq is None:
            messagebox.showinfo("Selecione", "Escolha um equipamento na barra lateral.")
            return
        dialogo = DialogEditarEquipamento(self, eq)
        if not dialogo.resultado:
            return
        novo_nome = dialogo.resultado[0]
        if novo_nome and novo_nome != eq.nome and not self._nome_livre(novo_nome):
            return
        self._snapshot()
        try:
            self.rede.editar_equipamento(eq.id, *dialogo.resultado)
            if getattr(dialogo, "conector_lote", None):
                self.rede.definir_conector_em_lote(eq.id, "F", *dialogo.conector_lote)
        except ValueError as erro:
            messagebox.showerror("Nao foi possivel editar", str(erro))
        self._marcar_alterado()
        self.atualizar_tudo()

    def acao_remover_equipamento(self):
        eq = self._eq_selecionado()
        if eq is None:
            return
        if messagebox.askyesno("Remover", "Remover '%s' e todas as fusoes dele?\n\n"
                               "(da pra desfazer com Ctrl+Z)" % eq.nome):
            self._snapshot()
            self.rede.remover_equipamento(eq.id)
            self.porta_selecionada = None
            self.destaque = set()
            self._marcar_alterado()
            self.atualizar_tudo()

    def acao_alternar_potencia(self):
        self.mostrar_potencia = not self.mostrar_potencia
        self.botao_potencia.variante = "acento" if self.mostrar_potencia else "normal"
        self.botao_potencia._sair()
        self.atualizar_tudo()
        if self.mostrar_potencia and not calcular_potencias(self.rede)["fontes"]:
            self.status.config(text="Nenhuma porta de OLT tem potencia: clique com o botao "
                                    "direito numa porta da OLT > Potencia de saida.")
        else:
            self.status.config(text="Potencia no diagrama: %s."
                               % ("ligada" if self.mostrar_potencia else "desligada"))

    def acao_potencia_porta(self, chave=None):
        """Pergunta a potencia de saida (dBm) de uma porta de OLT/ativo."""
        chave = chave or self._porta_para_rastrear()
        if chave is None or self.rede.equipamentos[chave[0]].tipo not in TIPOS_ATIVOS:
            messagebox.showinfo("Potencia", "Escolha uma porta de OLT (clique na porta ou "
                                            "use o botao direito em cima dela).")
            return
        atual = self.rede.potencia_da_porta(*chave)
        texto = perguntar_texto(
            "Potencia de saida",
            "%s\n\nPotencia de saida em dBm (ex.: 3, 5, 7 ou -1,5).\n"
            "Deixe vazio pra tirar." % self.rede.nome_porta(*chave),
            parent=self, initialvalue="" if atual is None else ("%g" % atual).replace(".", ","))
        if texto is None:
            return
        texto = texto.strip().replace(",", ".").replace("+", "").replace("dBm", "").strip()
        try:
            valor = float(texto) if texto else None
        except ValueError:
            messagebox.showerror("Potencia invalida", "Digite so o numero em dBm, ex.: 5 ou -1,5.")
            return
        self._snapshot()
        try:
            self.rede.definir_potencia(*chave, valor)
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Potencia invalida", str(erro))
            return
        self._limpar_selecao()
        self._marcar_alterado()
        if valor is not None and not self.mostrar_potencia:
            self.acao_alternar_potencia()
        self.atualizar_tudo()
        self.status.config(text="%s: %s" % (self.rede.nome_porta(*chave),
                                            formatar_dbm(valor) if valor is not None
                                            else "sem potencia"))

    def acao_girar_dio(self):
        eq = self._eq_selecionado()
        if eq is None or not (eq.is_dio() or eq.tipo in TIPOS_ATIVOS):
            messagebox.showinfo("Girar", "Escolha um DIO, OLT, switch ou RB na barra lateral.")
            return
        self._snapshot()
        nova = self.rede.girar_dio(eq.id)
        self._marcar_alterado()
        self.atualizar_tudo()
        self.ir_para({"eq_id": eq.id, "chave": None})
        self.status.config(text="%s agora esta na %s. Se encostou em outra caixa, use "
                                "Organizar." % (eq.nome, nova))

    def acao_inverter_lado(self):
        eq = self._eq_selecionado()
        if eq is None:
            return
        self._snapshot()
        self.rede.inverter_lado(eq.id)
        self._marcar_alterado()
        self.atualizar_tudo()

    def acao_novo_modulo(self):
        eq = self._eq_selecionado()
        if eq is None:
            messagebox.showinfo("Selecione", "Escolha o equipamento na barra lateral.")
            return
        if eq.tem_lados():
            messagebox.showinfo(eq.tipo, "%s nao tem modulos. Use Editar para mudar a "
                                         "quantidade de %s."
                                % (eq.tipo, "fibras" if eq.is_cabo() else "portas"))
            return
        dialogo = DialogNovoModulo(self, eq)
        if not dialogo.resultado:
            return
        tipo, nome, qtd = dialogo.resultado
        self._snapshot()
        try:
            if eq.tipo == "OLT":
                eq.add_placa(tipo, nome)
            elif eq.tipo == TIPO_ACOMODADOR:
                eq.add_splitter(tipo, nome)
            else:
                eq.add_grupamento(tipo, qtd, nome)
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Nao foi possivel adicionar", str(erro))
            return
        self._marcar_alterado()
        self.atualizar_tudo()

    def acao_editar_modulo(self):
        item = self._item_arvore()
        if item and item[0] == "modulo" and self.rede.equipamentos[item[1]].tem_lados():
            messagebox.showinfo("Lados", "Os dois lados de um DIO/cabo sao fixos. "
                                         "Para mudar a quantidade, edite o equipamento.")
            return
        if item is None or item[0] != "modulo":
            messagebox.showinfo("Selecione", "Escolha um modulo na lista da barra lateral.")
            return
        _, eq_id, mod_id, _ = item
        eq = self.rede.equipamentos[eq_id]
        dialogo = DialogEditarModulo(self, eq, eq.modulos[mod_id])
        if not dialogo.resultado:
            return
        self._snapshot()
        try:
            self.rede.editar_modulo(eq_id, mod_id, *dialogo.resultado)
            if getattr(dialogo, "conector_lote", None):
                self.rede.definir_conector_em_lote(eq_id, mod_id, *dialogo.conector_lote)
        except ValueError as erro:
            messagebox.showerror("Nao foi possivel editar", str(erro))
        self._marcar_alterado()
        self.atualizar_tudo()

    def acao_remover_modulo(self):
        item = self._item_arvore()
        if item and item[0] == "modulo" and self.rede.equipamentos[item[1]].tem_lados():
            messagebox.showinfo("Lados", "Os dois lados de um DIO/cabo sao fixos. "
                                         "Para mudar a quantidade, edite o equipamento.")
            return
        if item is None or item[0] != "modulo":
            messagebox.showinfo("Selecione", "Escolha um modulo na lista da barra lateral.")
            return
        _, eq_id, mod_id, _ = item
        nome = self.rede.equipamentos[eq_id].modulos[mod_id].nome
        if messagebox.askyesno("Remover modulo", "Remover '%s' e as fusoes dele?\n\n"
                               "(da pra desfazer com Ctrl+Z)" % nome):
            self._snapshot()
            self.rede.remover_modulo(eq_id, mod_id)
            self.porta_selecionada = None
            self.destaque = set()
            self._marcar_alterado()
            self.atualizar_tudo()

    def acao_abrir_item_arvore(self):
        item = self._item_arvore()
        if item is None:
            return
        if item[0] == "modulo":
            self.acao_editar_modulo()
            return
        _, eq_id, mod_id, num = item
        self.abrir_porta((eq_id, mod_id, num))

    def abrir_porta(self, chave):
        """Dialogo da porta: conector, simplex/duplex, potencia e fusoes."""
        eq_id, mod_id, num = chave
        self._snapshot()
        antes = json.dumps(self.rede.to_dict())
        DialogPorta(self, self.rede, eq_id, mod_id, num, lambda: None,
                    ao_rastrear=self._rastrear_chave)
        if json.dumps(self.rede.to_dict()) != antes:
            self._marcar_alterado()
        elif self._historico:
            self._historico.pop()          # nada mudou: nao suja o historico
        self.atualizar_tudo()

    # ---------------- menu do botao direito ----------------
    def _no_equipamento(self, eq_id, funcao):
        """Seleciona o equipamento e roda a acao (as acoes usam a selecao)."""
        def rodar():
            if self._selecionar_equipamento(eq_id):
                funcao()
        return rodar

    def _itens_menu_equipamento(self, eq_id):
        eq = self.rede.equipamentos[eq_id]
        em = lambda f: self._no_equipamento(eq_id, f)
        itens = [("arrow-left-right", "Inverter lado", "I", em(self.acao_inverter_lado))]
        if eq.is_dio() or eq.tipo in TIPOS_ATIVOS:
            itens.append(("rotate-cw", "Girar (vertical / horizontal)", "",
                          em(self.acao_girar_dio)))
        itens.append(("pencil", "Editar", "", em(self.acao_editar_equipamento)))
        if not eq.tem_lados():
            itens.append(("box", "Novo modulo", "", em(self.acao_novo_modulo)))
        itens.append(("copy", "Duplicar", "Ctrl+D", em(self.acao_duplicar_equipamento)))
        if eq.tipo == "OLT":
            itens.append(("activity", "Potencia em todas as portas PON...", "",
                          lambda: self.acao_potencia_olt(eq_id)))
        itens += [None, ("trash-2", "Excluir", "", em(self.acao_remover_equipamento))]
        return itens

    def _menu_equipamento(self, evento, eq_id):
        if self._sobre_porta():
            return                       # o menu da porta cuida
        self._selecionar_equipamento(eq_id)
        self.menu_contexto.abrir_em(evento.x_root, evento.y_root,
                                    self._itens_menu_equipamento(eq_id))
        return "break"

    def _menu_porta(self, evento, chave):
        eq = self.rede.equipamentos[chave[0]]
        itens = [("pencil", "Editar porta (conector, duplex, fusoes)", "",
                  lambda: self.abrir_porta(chave))]
        if eq.tipo in TIPOS_ATIVOS:
            atual = self.rede.potencia_da_porta(*chave)
            itens.append(("activity", "Potencia de saida%s..." % (
                "  (%s)" % formatar_dbm(atual) if atual is not None else ""), "",
                lambda: self.acao_potencia_porta(chave)))
        itens.append(("route", "Rastrear a partir daqui", "", lambda: self._rastrear_chave(chave)))
        if self.rede.fusoes_na_porta(*chave):
            itens.append(("x", "Remover a(s) fusao(oes) desta porta", "",
                          lambda: self._remover_fusoes_da_porta(chave)))
        itens += [None] + self._itens_menu_equipamento(chave[0])
        self._selecionar_equipamento(chave[0])
        self.menu_contexto.abrir_em(evento.x_root, evento.y_root, itens)
        return "break"

    def _remover_fusoes_da_porta(self, chave):
        fusoes = self.rede.fusoes_na_porta(*chave)
        if not fusoes:
            return
        self._snapshot()
        for f in fusoes:
            self.rede.remover_fusao(f.id)
        self.destaque = set()
        self._marcar_alterado()
        self.atualizar_tudo()
        self.status.config(text="%d fusao(oes) removida(s) de %s. Ctrl+Z desfaz."
                           % (len(fusoes), self.rede.nome_porta(*chave)))

    def acao_potencia_olt(self, eq_id):
        """Mesma potencia em todas as portas das placas GPON da OLT."""
        eq = self.rede.equipamentos[eq_id]
        placas = [m for m in eq.modulos.values() if m.tipo.startswith("GPON")]
        if not placas:
            messagebox.showinfo("Potencia", "Esta OLT nao tem placa GPON.")
            return
        texto = perguntar_texto(
            "Potencia nas portas PON",
            "%s - %d placa(s) GPON.\n\nPotencia de saida em dBm pra TODAS as portas PON "
            "(ex.: 3, 5, 7).\nDeixe vazio pra tirar." % (eq.nome, len(placas)), parent=self)
        if texto is None:
            return
        texto = texto.strip().replace(",", ".").replace("+", "").replace("dBm", "").strip()
        try:
            valor = float(texto) if texto else None
            if valor is not None and not -40.0 <= valor <= 30.0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Potencia invalida", "Digite so o numero em dBm (-40 a +30).")
            return
        self._snapshot()
        for placa in placas:
            self.rede.definir_potencia_em_lote(eq_id, placa.id, valor)
        self._marcar_alterado()
        if valor is not None and not self.mostrar_potencia:
            self.acao_alternar_potencia()
        self.atualizar_tudo()

    def _tecla_atalho(self, funcao):
        """Atalho de uma letra so: nao dispara enquanto se digita num campo."""
        def tratar(evento):
            classe = evento.widget.winfo_class() if hasattr(evento.widget, "winfo_class") else ""
            if classe in ("Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox"):
                return
            funcao()
        return tratar

    # ---------------- busca, rastreio e pendencias ----------------
    def acao_buscar(self):
        """Ctrl+L: a busca agora mora na paleta de comandos."""
        if self.paleta is None:
            self.abrir_paleta()

    def acao_busca_avancada(self):
        if self._janela_busca is not None and self._janela_busca.winfo_exists():
            self._janela_busca.lift()
            self._janela_busca.e_termo.focus_set()
            return
        self._janela_busca = DialogBusca(self, self.rede, self.ir_para)

    def ir_para(self, achado):
        """Leva a vista ate um achado da busca (ou das pendencias) e o destaca."""
        eq_id = achado.get("eq_id")
        chave = achado.get("chave")
        if eq_id and eq_id in self.rede.equipamentos:
            self._selecionar_equipamento(eq_id)
        if chave and chave in (self.cena.portas if self.cena else {}):
            self.porta_selecionada = {"eq_id": chave[0], "modulo_id": chave[1],
                                      "porta_num": chave[2]}
            self.atualizar_tudo()
            ponto = self.cena.portas[chave]
            self.centralizar_em(ponto["x"], ponto["y"])
            self.status.config(text="Encontrado: %s" % self.rede.nome_porta(*chave))
        elif eq_id and eq_id in self.rede.equipamentos:
            eq = self.rede.equipamentos[eq_id]
            info = layout_equipamento(eq)
            self.centralizar_em(eq.pos_x + info["largura"] / 2.0,
                                eq.pos_y + min(info["altura"], 300) / 2.0)
            self.status.config(text="Encontrado: %s" % eq.nome)

    def _porta_para_rastrear(self):
        """Usa a porta selecionada no diagrama; se nao tiver, a da arvore."""
        if self.porta_selecionada:
            p = self.porta_selecionada
            return (p["eq_id"], p["modulo_id"], p["porta_num"])
        item = self._item_arvore()
        if item and item[0] == "porta":
            return (item[1], item[2], item[3])
        return None

    def acao_rastrear(self):
        chave = self._porta_para_rastrear()
        if chave is None:
            messagebox.showinfo(
                "Escolha uma porta",
                "Selecione uma porta antes de rastrear:\n\n"
                "- clique numa porta livre no diagrama, ou\n"
                "- escolha a porta na lista de portas da barra lateral, ou\n"
                "- ache pela paleta (Ctrl+K) digitando o cliente ou a porta.")
            return
        self._rastrear_chave(chave)

    def _rastrear_chave(self, chave):
        DialogRastreio(self, self.rede, chave, self._aplicar_destaque)

    def _aplicar_destaque(self, fusoes):
        self.destaque = set(fusoes or ())
        self.atualizar_tudo()
        self.status.config(text="Caminho destacado: %d fusao(oes). "
                                "Esc tira o destaque."
                           % len(self.destaque))

    def acao_limpar_destaque(self):
        self.destaque = set()
        self.atualizar_tudo()

    def acao_pendencias(self):
        if self._janela_pendencias is not None and self._janela_pendencias.winfo_exists():
            self._janela_pendencias.atualizar()
            self._janela_pendencias.lift()
            return
        self._janela_pendencias = DialogPendencias(
            self, self.rede, self.ir_para,
            lambda: self.acao_relatorio_csv("pendencias"))

    # ---------------- interacao no diagrama ----------------
    def _limpar_selecao(self):
        self.porta_selecionada = None
        self.selecao_lote = []
        self._mostrar_dica("")
        self.atualizar_tudo()

    def _clique_porta(self, chave):
        fusoes = self.rede.fusoes_na_porta(*chave)
        limite = self.rede.limite_porta(*chave)

        if self.porta_selecionada is None:
            if len(fusoes) >= limite:
                nomes = ", ".join(self.rede.nome_porta(*f.outra_ponta(*chave))
                                  for f in fusoes)
                if messagebox.askyesno(
                        "Porta cheia",
                        "%s\n\nJa conectada a: %s\n\nRemover a(s) fusao(oes) desta "
                        "porta?  (da pra desfazer com Ctrl+Z)"
                        % (self.rede.nome_porta(*chave), nomes)):
                    self._snapshot()
                    for f in fusoes:
                        self.rede.remover_fusao(f.id)
                    self.destaque = set()
                    self._marcar_alterado()
                    self.atualizar_tudo()
                return "break"
            self.porta_selecionada = {"eq_id": chave[0], "modulo_id": chave[1],
                                      "porta_num": chave[2]}
            self._mostrar_dica("%s   \u2192   clique na porta de destino   \u00b7   Esc cancela"
                               % self.rede.nome_porta(*chave))
            self.atualizar_tudo()
            return "break"

        origem = (self.porta_selecionada["eq_id"], self.porta_selecionada["modulo_id"],
                  self.porta_selecionada["porta_num"])
        if self.selecao_lote:
            if chave in self.selecao_lote:
                self._limpar_selecao()
            else:
                self._fundir_lote(chave)
            return "break"
        if origem == chave:
            self._limpar_selecao()
            return "break"
        rotulo = perguntar_texto("Rotulo da fusao",
                                        "Rotulo (opcional, ex.: TX, RX, Cliente 12):",
                                        parent=self)
        if rotulo is None:
            self._limpar_selecao()
            return "break"
        self._snapshot()
        try:
            self.rede.criar_fusao(origem[0], origem[1], origem[2],
                                  chave[0], chave[1], chave[2], rotulo.strip())
            self._marcar_alterado()
        except ValueError as erro:
            self._historico.pop()
            messagebox.showerror("Nao foi possivel conectar", str(erro))
        self._limpar_selecao()
        return "break"

    def _clique_porta_shift(self, chave):
        """Shift+clique: marca da porta escolhida ate esta (mesmo modulo / lado
        do mesmo equipamento). Depois, um clique na porta de destino funde
        todas em sequencia: 1->1, 2->2..."""
        if self.porta_selecionada is None:
            return self._clique_porta(chave)
        origem = (self.porta_selecionada["eq_id"], self.porta_selecionada["modulo_id"],
                  self.porta_selecionada["porta_num"])
        if origem[:2] != chave[:2]:
            # outro equipamento/modulo: recomeca a selecao daqui
            self._limpar_selecao()
            return self._clique_porta(chave)
        eq = self.rede.equipamentos[chave[0]]
        numeros = sorted(eq.modulos[chave[1]].portas)
        a, b = sorted((origem[2], chave[2]))
        self.selecao_lote = [(chave[0], chave[1], n) for n in numeros if a <= n <= b]
        self.porta_selecionada = {"eq_id": chave[0], "modulo_id": chave[1],
                                  "porta_num": self.selecao_lote[0][2]}
        primeiro, ultimo = self.selecao_lote[0], self.selecao_lote[-1]
        self._mostrar_dica("%d portas marcadas (%s a %s)   \u2192   clique na PRIMEIRA porta de "
                           "destino   \u00b7   Esc cancela"
                           % (len(self.selecao_lote), self.rede.rotulo_porta(*primeiro),
                              self.rede.rotulo_porta(*ultimo)))
        self.atualizar_tudo()
        return "break"

    def _plano_lote(self, destino):
        """[(origem, destino), ...] na ordem, ou levanta ValueError dizendo
        o que impede (falta porta, porta ocupada)."""
        eq = self.rede.equipamentos[destino[0]]
        numeros = [n for n in sorted(eq.modulos[destino[1]].portas) if n >= destino[2]]
        if len(numeros) < len(self.selecao_lote):
            raise ValueError("A partir de %s so existem %d porta(s); foram marcadas %d."
                             % (self.rede.nome_porta(*destino), len(numeros),
                                len(self.selecao_lote)))
        pares = [(o, (destino[0], destino[1], n))
                 for o, n in zip(self.selecao_lote, numeros)]
        ocupadas = []
        for o, d in pares:
            if o == d or d in self.selecao_lote:
                raise ValueError("O destino se sobrepoe as portas marcadas.")
            for ponta in (o, d):
                if len(self.rede.fusoes_na_porta(*ponta)) >= self.rede.limite_porta(*ponta):
                    ocupadas.append(self.rede.nome_porta(*ponta))
        if ocupadas:
            raise ValueError("Ja estao ocupadas:\n- " + "\n- ".join(ocupadas[:12])
                             + ("\n... e mais %d" % (len(ocupadas) - 12)
                                if len(ocupadas) > 12 else ""))
        return pares

    def _fundir_lote(self, destino):
        try:
            pares = self._plano_lote(destino)
        except ValueError as erro:
            messagebox.showerror("Nao da pra fundir em lote", str(erro))
            return
        primeiro, ultimo = pares[0][1], pares[-1][1]
        rotulo = perguntar_texto(
            "Fundir %d fibras" % len(pares),
            "%d fusoes: %s ... ate %s.\n\nRotulo (opcional). Use # pra numerar:\n"
            "'Cliente #' vira Cliente 1, Cliente 2..." % (
                len(pares), self.rede.nome_porta(*primeiro), self.rede.nome_porta(*ultimo)),
            parent=self)
        if rotulo is None:
            self._limpar_selecao()
            return
        rotulo = rotulo.strip()
        self._snapshot()
        estado = self._historico[-1]
        try:
            for i, (o, d) in enumerate(pares, 1):
                texto = (formatar_nome_numerado(rotulo, i) if "#" in rotulo else rotulo)
                self.rede.criar_fusao(o[0], o[1], o[2], d[0], d[1], d[2], texto)
        except ValueError as erro:
            # tudo ou nada: volta como estava
            self.rede = Rede.from_dict(json.loads(estado))
            self._historico.pop()
            messagebox.showerror("Nao foi possivel fundir em lote", str(erro))
            self._limpar_selecao()
            return
        self._marcar_alterado()
        self._limpar_selecao()
        self.status.config(text="%d fusoes criadas de uma vez (%s ... %s). Ctrl+Z desfaz todas."
                           % (len(pares), self.rede.rotulo_porta(*pares[0][0]),
                              self.rede.rotulo_porta(*pares[-1][0])))

    def _sobre_porta(self):
        """O item embaixo do mouse e uma porta?"""
        return any(tag.startswith("porta:") for tag in self.canvas.gettags("current"))

    def _cursor_canvas(self):
        """Mao na porta (clicar pra fundir), cruz de mover no resto do
        equipamento, seta comum no vazio."""
        tags = self.canvas.gettags("current")
        if any(t.startswith("porta:") for t in tags):
            cursor = "hand2"
        elif any(t.startswith("eq:") for t in tags):
            cursor = "fleur"
        else:
            cursor = ""
        if self.canvas.cget("cursor") != cursor:
            self.canvas.configure(cursor=cursor)

    def _mundo(self, evento):
        """Coordenada do diagrama sob o mouse."""
        minx, miny = self._origem_arraste or (self.cena.minx, self.cena.miny)
        return (self.canvas.canvasx(evento.x) / self.escala + minx,
                self.canvas.canvasy(evento.y) / self.escala + miny)

    def _titulo_press(self, evento, eq_id):
        eq = self.rede.equipamentos.get(eq_id)
        if eq is None or self._sobre_porta():
            return
        self._origem_arraste = (self.cena.minx, self.cena.miny)
        mx, my = self._mundo(evento)
        self._arraste_eq = (eq_id, mx - eq.pos_x, my - eq.pos_y, eq.pos_x, eq.pos_y)
        self.canvas.configure(cursor="fleur")
        return "break"

    def _titulo_motion(self, evento):
        if self._arraste_eq is None:
            return
        eq_id, offx, offy, _, _ = self._arraste_eq
        mx, my = self._mundo(evento)
        self.rede.definir_posicao(eq_id, mx - offx, my - offy)
        if not self._redesenho_pendente:
            # redesenha no maximo ~60 vezes por segundo, nao a cada pixel
            self._redesenho_pendente = True
            self.after(16, self._redesenhar_arraste)
        return "break"

    def _redesenhar_arraste(self):
        self._redesenho_pendente = False
        if self._origem_arraste is None:
            return
        self.cena = montar_cena(self.rede, self.porta_selecionada, destaque=self.destaque,
                                selecao_lote=self.selecao_lote, potencias=self._potencias())
        # durante o arraste a origem fica parada: senao a vista pularia
        # quando o equipamento passasse da borda do diagrama
        self.cena.minx, self.cena.miny = self._origem_arraste
        self._desenhar_canvas()

    def _titulo_release(self, _evento=None):
        if self._arraste_eq is None:
            return
        eq_id, _, _, x_antes, y_antes = self._arraste_eq
        self._arraste_eq = None
        eq = self.rede.equipamentos.get(eq_id)
        if eq is not None:
            # encaixa numa grade de 10 pra alinhar facil
            eq.pos_x = round(eq.pos_x / 10.0) * 10.0
            eq.pos_y = round(eq.pos_y / 10.0) * 10.0
            moveu = (eq.pos_x, eq.pos_y) != (x_antes, y_antes)
        else:
            moveu = False
        if moveu:
            # guarda o estado de antes do arraste pro Ctrl+Z
            eq.pos_x, eq.pos_y, novo = x_antes, y_antes, (eq.pos_x, eq.pos_y)
            self._snapshot()
            eq.pos_x, eq.pos_y = novo
            self._marcar_alterado()
        # redesenha mantendo a vista no mesmo lugar
        vx = self.canvas.canvasx(0) / self.escala + self._origem_arraste[0]
        vy = self.canvas.canvasy(0) / self.escala + self._origem_arraste[1]
        self._origem_arraste = None
        self.atualizar_tudo()
        total_x = max(self.cena.largura * self.escala, 1)
        total_y = max(self.cena.altura * self.escala, 1)
        self.canvas.xview_moveto(max(0.0, (vx - self.cena.minx) * self.escala / total_x))
        self.canvas.yview_moveto(max(0.0, (vy - self.cena.miny) * self.escala / total_y))
        if moveu:
            self._selecionar_equipamento(eq_id)
        self._cursor_canvas()
        return "break"

    def _fundo_press(self, evento):
        self.canvas.scan_mark(evento.x, evento.y)

    def _fundo_motion(self, evento):
        if self._arraste_eq is not None:
            self._titulo_motion(evento)          # arrastando um equipamento
            return
        self.canvas.scan_dragto(evento.x, evento.y, gain=1)

    def _fundo_release(self, _evento=None):
        if self._arraste_eq is not None:
            self._titulo_release()


# ============================================================================
#  AUTOTESTE (verifica o programa inteiro sem abrir janela)
# ============================================================================

def autoteste(caminho_saida=None):
    """Modo de verificacao: monta a rede de exemplo, exercita as funcoes e
    gera os arquivos, escrevendo um relatorio do que funcionou.

        WaspFiber.exe --autoteste
    """
    import tempfile
    destino = caminho_saida or os.path.join(tempfile.gettempdir(), "waspfiber_autoteste.txt")
    linhas = []
    ok = True
    try:
        rede = rede_exemplo()
        linhas.append("rede de exemplo: %d equipamentos, %d fusoes"
                      % (len(rede.equipamentos), len(rede.fusoes)))
        cena = montar_cena(rede)
        linhas.append("diagrama: %d primitivas, %d portas, area %.0fx%.0f"
                      % (len(cena.itens), len(cena.portas), cena.largura, cena.altura))
        pasta = tempfile.mkdtemp(prefix="waspfiber_teste_")
        # (nome, funcao, tamanho minimo aceitavel) - a rede de exemplo nao tem
        # nenhuma pendencia, entao esse CSV sai so com o cabecalho mesmo
        alvos = [
            ("diagrama.pdf", lambda p: escrever_pdf([pagina_do_diagrama(cena)], p), 2000),
            ("diagrama.svg", lambda p: exportar_svg(cena, p), 2000),
            ("relatorio.pdf", lambda p: exportar_relatorio_pdf(rede, cena, p), 5000),
            ("portas.csv", lambda p: exportar_relatorio_csv(rede, p), 1000),
            ("pendencias.csv", lambda p: exportar_pendencias_csv(rede, p), 25),
            ("capacidade.csv", lambda p: exportar_capacidade_csv(rede, p), 100),
            ("rede.wasp.json", lambda p: rede.salvar(p), 1000),
        ]
        for nome, funcao, minimo in alvos:
            caminho = os.path.join(pasta, nome)
            funcao(caminho)
            tamanho = os.path.getsize(caminho)
            linhas.append("%s: %d bytes %s"
                          % (nome, tamanho, "ok" if tamanho >= minimo else "SUSPEITO"))
            ok = ok and tamanho >= minimo
        recarregada = Rede.carregar(os.path.join(pasta, "rede.wasp.json"))
        linhas.append("reabrir json: %d equipamentos, %d fusoes"
                      % (len(recarregada.equipamentos), len(recarregada.fusoes)))

        # rastreio: da porta 5 da placa GPON o sinal passa pelo splitter 1x8
        arvore = rastrear_caminho(rede, ("OLT-01", "OLT-01-PLACA-01", 5), 5.0)
        pontas = pontas_finais(arvore)
        destacadas = fusoes_do_rastreio(arvore)
        linhas.append("rastreio: %d ponta(s), %d fusao(oes) no caminho, pior perda %.2f dB"
                      % (len(pontas), len(destacadas),
                         max((p["perda_acum"] for p in pontas), default=0.0)))
        ok = ok and len(pontas) >= 2 and len(destacadas) >= 3

        # busca
        achados_cliente = buscar(rede, "cliente a")
        achados_eq = buscar(rede, "centro")
        linhas.append("busca: 'cliente a' -> %d achado(s); 'centro' -> %d achado(s)"
                      % (len(achados_cliente), len(achados_eq)))
        ok = ok and achados_cliente and achados_eq

        # duplicar e criar em lote
        copia = rede.duplicar_equipamento("OLT-01")
        em_lote = rede.criar_em_lote("TESTE-##", TIPO_DIO, 3, 1, 12)
        linhas.append("duplicar: '%s' com %d modulo(s) | lote: %s"
                      % (copia.nome, len(copia.modulos),
                         ", ".join(e.nome for e in em_lote)))
        ok = ok and len(copia.modulos) == 2 and len(em_lote) == 3

        # organizar layout (nao pode deixar caixas sobrepostas)
        rede.organizar_layout()
        caixas = sorted(rede.equipamentos.values(), key=lambda e: (e.pos_x, e.pos_y))
        sobreposicao = False
        for i, a in enumerate(caixas):
            for b in caixas[i + 1:]:
                if a.pos_x != b.pos_x:
                    continue
                alt_a = layout_equipamento(a)["altura"]
                if b.pos_y < a.pos_y + alt_a and a.pos_y < b.pos_y + layout_equipamento(b)["altura"]:
                    sobreposicao = True
        linhas.append("organizar layout: %d caixas, sobreposicao=%s"
                      % (len(caixas), sobreposicao))
        ok = ok and not sobreposicao

        # pendencias (a copia da OLT nasce sem fusao nenhuma: tem que aparecer)
        # a rede de exemplo nasce limpa: so depois da copia e do lote (acima)
        # e que aparecem equipamentos sem nenhuma fusao
        lista = pendencias(rede)
        tipos = sorted(set(p["tipo"] for p in lista))
        linhas.append("pendencias: %d item(ns) - %s" % (len(lista), ", ".join(tipos)))
        ok = ok and any(p["tipo"] == "Sem conexao" for p in lista)
        livres = sum(c["livres"] for c in resumo_capacidade(rede))
        linhas.append("capacidade: %d porta(s) livre(s) na rede de teste" % livres)

        # autosave: gravar, ler de volta e limpar
        salvo = gravar_autosave(rede, "teste")
        lida, info = ler_autosave()
        linhas.append("autosave: gravou=%s releu=%s (%s)"
                      % (salvo, lida is not None and len(lida.fusoes) == len(rede.fusoes),
                         (info or {}).get("quando", "-")))
        ok = ok and salvo and lida is not None
        apagar_autosave()

        linhas.append("tkinter disponivel: %s" % (tk.TkVersion,))
        linhas.append("RESULTADO: %s" % ("TUDO OK" if ok else "FALHOU"))
        linhas.append("arquivos de teste em: %s" % pasta)
    except Exception:
        import traceback
        linhas.append("ERRO:\n" + traceback.format_exc())
        ok = False
    texto = "\n".join(linhas) + "\n"
    with open(destino, "w", encoding="utf-8") as fp:
        fp.write(texto)
    try:
        print(texto)
    except Exception:
        pass          # pythonw.exe nao tem console: o arquivo ja tem o resultado
    return ok


def main():
    if "--autoteste" in sys.argv:
        indice = sys.argv.index("--autoteste")
        saida = sys.argv[indice + 1] if len(sys.argv) > indice + 1 else None
        sys.exit(0 if autoteste(saida) else 1)
    App().mainloop()


if __name__ == "__main__":
    main()
