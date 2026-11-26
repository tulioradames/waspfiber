# -*- coding: utf-8 -*-
"""Cidades e diagramas (B0.36).

Organizacao em disco - pensada pra uma pasta compartilhada no servidor:

    Pasta do provedor/
        Sao Paulo - SP/
            cidade.json              <- marca a pasta como cidade
            POP Centro.wasp.json     <- um diagrama por local (POP, CEO, CTO)
            CTO-Bairro-01.wasp.json
        Santos - SP/
            ...

Qualquer pasta pode ser aberta como cidade: se ela nao tiver o cidade.json,
o programa cria (com o nome da pasta). As cidades usadas por ultimo e a
pasta do provedor ficam guardadas em %APPDATA%\\WaspFiber\\inicio.json.

So biblioteca padrao. Nada de interface aqui (a tela fica no waspfiber.py).
"""

import json
import os
import re
import time
import unicodedata

ARQUIVO_CIDADE = "cidade.json"
EXTENSAO = ".wasp.json"
MAX_RECENTES = 12

UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")


# ============================================================================
#  NOMES
# ============================================================================

def nome_de_pasta(texto):
    """Nome valido de arquivo/pasta no Windows, mantendo acentos."""
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(texto or ""))
    texto = re.sub(r"\s+", " ", texto).strip().strip(".")
    if texto.upper() in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(?i)(COM|LPT)\d", texto):
        texto = "_" + texto
    return texto[:80]


def titulo_cidade(nome, uf=""):
    nome, uf = (nome or "").strip(), (uf or "").strip().upper()
    return "%s - %s" % (nome, uf) if (nome and uf) else nome


def sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", str(texto or ""))
                   if unicodedata.category(c) != "Mn").lower()


def _mesmo_caminho(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# ============================================================================
#  CIDADE
# ============================================================================

def _gravar_json(caminho, dados):
    tmp = caminho + ".novo"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(dados, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def eh_cidade(pasta):
    return os.path.isfile(os.path.join(pasta, ARQUIVO_CIDADE))


def ler_cidade(pasta):
    """{'nome', 'uf', 'titulo', 'pasta', 'criada_em'} ou None se a pasta nao
    e uma cidade."""
    if not pasta or not os.path.isdir(pasta) or not eh_cidade(pasta):
        return None
    try:
        with open(os.path.join(pasta, ARQUIVO_CIDADE), encoding="utf-8") as fp:
            dados = json.load(fp)
        if not isinstance(dados, dict):
            dados = {}
    except Exception:
        dados = {}
    nome = str(dados.get("nome") or os.path.basename(os.path.normpath(pasta))).strip()
    uf = str(dados.get("uf") or "").strip().upper()
    return {"nome": nome, "uf": uf, "titulo": titulo_cidade(nome, uf),
            "pasta": os.path.abspath(pasta), "criada_em": dados.get("criada_em", "")}


def criar_cidade(pasta_pai, nome, uf=""):
    """Cria a pasta 'Nome - UF' dentro da pasta do provedor, com o
    cidade.json. Devolve a cidade (dict). ValueError se ja existir."""
    nome = (nome or "").strip()
    uf = (uf or "").strip().upper()
    if not nome:
        raise ValueError("Informe o nome da cidade.")
    if uf and uf not in UFS:
        raise ValueError("UF invalida: %s" % uf)
    if not pasta_pai or not os.path.isdir(pasta_pai):
        raise ValueError("A pasta escolhida para guardar as cidades nao existe.")
    pasta = os.path.join(pasta_pai, nome_de_pasta(titulo_cidade(nome, uf)))
    if os.path.exists(os.path.join(pasta, ARQUIVO_CIDADE)):
        raise ValueError("Ja existe a cidade \"%s\" nessa pasta." % titulo_cidade(nome, uf))
    os.makedirs(pasta, exist_ok=True)
    _gravar_json(os.path.join(pasta, ARQUIVO_CIDADE),
                 {"tipo": "waspfiber-cidade", "nome": nome, "uf": uf,
                  "criada_em": time.strftime("%Y-%m-%d %H:%M:%S")})
    return ler_cidade(pasta)


def abrir_pasta_como_cidade(pasta):
    """Abre qualquer pasta como cidade; se ainda nao for, cria o cidade.json
    com o nome da pasta ('Santos - SP' vira nome Santos, UF SP)."""
    if not pasta or not os.path.isdir(pasta):
        raise ValueError("Pasta nao encontrada: %s" % pasta)
    if not eh_cidade(pasta):
        base = os.path.basename(os.path.normpath(pasta))
        achado = re.fullmatch(r"(.+?)\s*-\s*([A-Za-z]{2})", base)
        nome, uf = (achado.group(1), achado.group(2).upper()) if achado else (base, "")
        if uf not in UFS:
            nome, uf = base, ""
        _gravar_json(os.path.join(pasta, ARQUIVO_CIDADE),
                     {"tipo": "waspfiber-cidade", "nome": nome, "uf": uf,
                      "criada_em": time.strftime("%Y-%m-%d %H:%M:%S")})
    return ler_cidade(pasta)


def listar_cidades(pasta_provedor):
    """Cidades (subpastas com cidade.json) da pasta do provedor, por nome."""
    if not pasta_provedor or not os.path.isdir(pasta_provedor):
        return []
    cidades = []
    try:
        nomes = os.listdir(pasta_provedor)
    except OSError:
        return []
    for nome in nomes:
        pasta = os.path.join(pasta_provedor, nome)
        if os.path.isdir(pasta):
            cidade = ler_cidade(pasta)
            if cidade:
                cidades.append(cidade)
    return sorted(cidades, key=lambda c: sem_acento(c["titulo"]))


# ============================================================================
#  DIAGRAMAS DA CIDADE
# ============================================================================

def listar_diagramas(pasta_cidade):
    """Diagramas (.wasp.json) da cidade, com o resumo pra tela inicial:
    caminho, arquivo, local (tipo/nome/endereco), numeros e data. Arquivo
    com defeito aparece com 'erro' (pra pessoa saber que ele esta la)."""
    itens = []
    try:
        nomes = os.listdir(pasta_cidade)
    except OSError:
        return []
    for nome in nomes:
        if not nome.lower().endswith(EXTENSAO) or nome.startswith("~"):
            continue
        caminho = os.path.join(pasta_cidade, nome)
        if not os.path.isfile(caminho):
            continue
        item = {"caminho": caminho, "arquivo": nome, "titulo": nome[:-len(EXTENSAO)],
                "tipo": "", "endereco": "", "equipamentos": 0, "fusoes": 0,
                "tem_coordenada": False, "modificado": os.path.getmtime(caminho), "erro": ""}
        try:
            with open(caminho, encoding="utf-8") as fp:
                dados = json.load(fp)
            local = dados.get("local") or {}
            item["tipo"] = str(local.get("tipo") or "")
            item["titulo"] = str(local.get("nome") or "").strip() or item["titulo"]
            item["endereco"] = str(local.get("endereco") or "")
            item["tem_coordenada"] = local.get("lat") not in (None, "")
            item["equipamentos"] = len(dados.get("equipamentos") or [])
            item["fusoes"] = len(dados.get("fusoes") or [])
        except Exception as erro:
            item["erro"] = "arquivo com defeito (%s)" % erro.__class__.__name__
        itens.append(item)
    ordem = {"POP": 0, "CEO": 1, "CTO": 2}
    return sorted(itens, key=lambda i: (ordem.get(i["tipo"], 3), sem_acento(i["titulo"])))


def caminho_novo_diagrama(pasta_cidade, nome):
    """'CTO Bairro 01' -> <cidade>/CTO Bairro 01.wasp.json (sem sobrescrever:
    se ja existir, acrescenta (2), (3)...)."""
    base = nome_de_pasta(nome) or "Diagrama"
    caminho = os.path.join(pasta_cidade, base + EXTENSAO)
    n = 2
    while os.path.exists(caminho):
        caminho = os.path.join(pasta_cidade, "%s (%d)%s" % (base, n, EXTENSAO))
        n += 1
    return caminho


def cidade_do_arquivo(caminho):
    """A cidade a que um diagrama pertence (a pasta dele), ou None."""
    if not caminho:
        return None
    return ler_cidade(os.path.dirname(os.path.abspath(caminho)))


# ============================================================================
#  PREFERENCIAS DA TELA INICIAL (cidades recentes, pasta do provedor)
# ============================================================================

def _caminho_prefs():
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.expanduser("~")
    return os.path.join(base, "WaspFiber", "inicio.json")


def ler_prefs():
    try:
        with open(_caminho_prefs(), encoding="utf-8") as fp:
            dados = json.load(fp)
        return dados if isinstance(dados, dict) else {}
    except Exception:
        return {}


def gravar_prefs(mudancas):
    dados = ler_prefs()
    dados.update(mudancas)
    try:
        os.makedirs(os.path.dirname(_caminho_prefs()), exist_ok=True)
        _gravar_json(_caminho_prefs(), dados)
    except OSError:
        pass


def pasta_provedor():
    pasta = ler_prefs().get("pasta_provedor") or ""
    return pasta if pasta and os.path.isdir(pasta) else ""


def pasta_provedor_sugerida():
    """Primeira vez: Documentos\\WaspFiber (criada so quando a pessoa
    cadastrar a primeira cidade)."""
    return os.path.join(os.path.expanduser("~"), "Documents", "WaspFiber")


def definir_pasta_provedor(pasta):
    gravar_prefs({"pasta_provedor": os.path.abspath(pasta) if pasta else ""})


def registrar_recente(pasta_cidade):
    recentes = [p for p in ler_prefs().get("recentes", [])
                if not _mesmo_caminho(p, pasta_cidade)]
    gravar_prefs({"recentes": [os.path.abspath(pasta_cidade)] + recentes[:MAX_RECENTES - 1],
                  "ultima_cidade": os.path.abspath(pasta_cidade)})


def ultima_cidade():
    pasta = ler_prefs().get("ultima_cidade") or ""
    return pasta if ler_cidade(pasta) else ""


def cidades_conhecidas():
    """As cidades da pasta do provedor + as abertas recentemente em outros
    lugares (outra pasta da rede, por exemplo), sem repetir."""
    cidades = listar_cidades(pasta_provedor())
    for pasta in ler_prefs().get("recentes", []):
        cidade = ler_cidade(pasta)
        if cidade and not any(_mesmo_caminho(c["pasta"], pasta) for c in cidades):
            cidade["fora_da_pasta"] = True
            cidades.append(cidade)
    return cidades


def esquecer_cidade(pasta_cidade):
    """Tira das recentes (nao apaga nada do disco)."""
    gravar_prefs({"recentes": [p for p in ler_prefs().get("recentes", [])
                               if not _mesmo_caminho(p, pasta_cidade)]})
