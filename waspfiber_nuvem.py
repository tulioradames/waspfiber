# -*- coding: utf-8 -*-
"""Conexao do programa com o Servidor WaspFiber (B0.39).

Os diagramas ficam no servidor, nao no computador. Aqui ficam:
- Conexao: login e as chamadas da API (cidades, diagramas, salvar);
- a sessao lembrada (servidor, empresa, usuario e o token - nunca a senha)
  em %APPDATA%\\WaspFiber\\servidor.json;
- a FILA DE ENVIO: se a internet ou o servidor cair na hora de salvar, o
  diagrama fica guardado em %APPDATA%\\WaspFiber\\pendentes\\ so ate
  conseguir enviar; depois o arquivo temporario e apagado.

So biblioteca padrao (urllib).
"""

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

# endereco do servidor: fixo, a pessoa nao escolhe (B0.41). E o publico (Tailscale
# Funnel, HTTPS), que funciona dentro e fora da empresa. WASPFIBER_SERVIDOR troca
# o endereco so pra testes / instalacao propria.
SERVIDOR_PADRAO = os.environ.get("WASPFIBER_SERVIDOR") or "https://servidor.taild43fdd.ts.net"
CAMPOS_INFO = ("usuario", "nome", "empresa", "empresa_nome", "papel")
UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")
TEMPO_LIMITE = 15


class ErroServidor(Exception):
    """sem_conexao=True: nao chegou no servidor (internet, servidor fora).
    status 401: sessao vencida; 409: outra pessoa salvou antes."""

    def __init__(self, mensagem, status=0, extra=None, sem_conexao=False):
        super().__init__(mensagem)
        self.status, self.extra, self.sem_conexao = status, extra or {}, sem_conexao


# ============================================================================
#  ARQUIVOS LOCAIS (so a sessao e a fila temporaria)
# ============================================================================

def _pasta_programa():
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.expanduser("~")
    pasta = os.path.join(base, "WaspFiber")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".novo"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(dados, fp, ensure_ascii=False)
    os.replace(tmp, caminho)


def ler_sessao():
    try:
        with open(os.path.join(_pasta_programa(), "servidor.json"), encoding="utf-8") as fp:
            dados = json.load(fp)
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_sessao(dados):
    _gravar_json(os.path.join(_pasta_programa(), "servidor.json"), dados)


def normalizar_url(url):
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "http://" + url
    partes = urllib.parse.urlparse(url)
    if partes.scheme in ("http", "https") and partes.hostname and not partes.port \
            and partes.scheme == "http":
        url = "%s:8765" % url
    return url


# ============================================================================
#  CONEXAO
# ============================================================================

class Conexao:
    def __init__(self, url, token=None, info=None):
        self.url = normalizar_url(url)
        self.token = token
        self.info = info or {}          # usuario, nome, empresa, empresa_nome

    # ---------------- baixo nivel ----------------
    def pedir(self, metodo, caminho, dados=None):
        corpo = None if dados is None else json.dumps(dados, ensure_ascii=False).encode("utf-8")
        cab = {"Accept": "application/json"}
        if corpo is not None:
            cab["Content-Type"] = "application/json; charset=utf-8"
        if self.token:
            cab["Authorization"] = "Bearer " + self.token
        pedido = urllib.request.Request(self.url + caminho, data=corpo, headers=cab,
                                        method=metodo)
        try:
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as erro:
            try:
                detalhe = json.loads(erro.read().decode("utf-8"))
            except Exception:
                detalhe = {}
            raise ErroServidor(detalhe.get("erro") or "O servidor respondeu %d." % erro.code,
                               erro.code, detalhe)
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as erro:
            motivo = getattr(erro, "reason", erro)
            raise ErroServidor("Sem conexao com o servidor %s (%s)." % (self.url, motivo),
                               sem_conexao=True)

    # ---------------- sessao ----------------
    @classmethod
    def entrar(cls, url, empresa, usuario, senha):
        c = cls(url)
        r = c.pedir("POST", "/api/entrar", {"empresa": empresa, "usuario": usuario, "senha": senha})
        c.token = r["token"]
        c.info = {k: r.get(k, "") for k in CAMPOS_INFO}
        gravar_sessao(dict(ler_sessao(), **dict(c.info, url=c.url, token=c.token)))
        return c

    @classmethod
    def entrar_email(cls, email, senha, url=None):
        """Login do programa (B0.41): e-mail + senha; a empresa sai do dominio."""
        c = cls(url or SERVIDOR_PADRAO)
        r = c.pedir("POST", "/api/entrar", {"email": (email or "").strip(), "senha": senha})
        c.token = r["token"]
        c.info = {k: r.get(k, "") for k in CAMPOS_INFO}
        gravar_sessao(dict(ler_sessao(), **dict(c.info, url=c.url, token=c.token,
                                                 email=(email or "").strip().lower())))
        return c

    @classmethod
    def da_sessao_salva(cls):
        """A conexao da ultima vez (sem conferir no servidor), ou None."""
        s = ler_sessao()
        if not s.get("token"):
            return None
        # o endereco e sempre o padrao (o campo do servidor saiu do login)
        return cls(SERVIDOR_PADRAO, s["token"], {k: s.get(k, "") for k in CAMPOS_INFO})

    def sair(self):
        try:
            if self.token:
                self.pedir("POST", "/api/sair", {})
        except ErroServidor:
            pass
        s = ler_sessao()
        s.pop("token", None)
        gravar_sessao(s)
        self.token = None

    def conferir(self):
        """Confere a sessao no servidor (atualiza nome/empresa)."""
        r = self.pedir("GET", "/api/eu")
        self.info.update({k: r.get(k, "") for k in CAMPOS_INFO})
        return r

    def saude(self):
        return self.pedir("GET", "/api/saude")

    # ---------------- contas (B0.41) ----------------
    @classmethod
    def empresa_do_email(cls, email, url=None):
        """Nome da empresa do dominio do e-mail, ou None se nao cadastrado.
        Lanca ErroServidor se nao houver conexao."""
        email = (email or "").strip()
        if "@" not in email or "." not in email.rsplit("@", 1)[1]:
            return None
        try:
            r = cls(url or SERVIDOR_PADRAO).pedir(
                "GET", "/api/empresa-do-email?" + urllib.parse.urlencode({"email": email}))
            return r.get("empresa_nome")
        except ErroServidor as erro:
            if erro.status == 404:
                return None
            raise

    @classmethod
    def criar_conta(cls, nome, email, senha, url=None):
        return cls(url or SERVIDOR_PADRAO).pedir(
            "POST", "/api/contas", {"nome": nome, "email": email, "senha": senha})

    def pedidos(self):
        return self.pedir("GET", "/api/pedidos")["pedidos"]

    def decidir_pedido(self, email, aprovar):
        return self.pedir("POST", "/api/pedidos/%s" % ("aprovar" if aprovar else "recusar"),
                          {"email": email})

    # ---------------- cidades e diagramas ----------------
    def cidades(self):
        cidades = self.pedir("GET", "/api/cidades")["cidades"]
        for c in cidades:
            c.setdefault("titulo", c.get("nome", c["id"]))
        return cidades

    def criar_cidade(self, nome, uf=""):
        return self.pedir("POST", "/api/cidades", {"nome": nome, "uf": uf})

    def diagramas(self, cidade_id):
        return self.pedir("GET", "/api/cidades/%s/diagramas" % cidade_id)["diagramas"]

    def criar_diagrama(self, cidade_id, nome, conteudo):
        return self.pedir("POST", "/api/cidades/%s/diagramas" % cidade_id,
                          {"nome": nome, "conteudo": conteudo})

    def abrir(self, cidade_id, diagrama_id):
        return self.pedir("GET", "/api/cidades/%s/diagramas/%s" % (cidade_id, diagrama_id))

    def salvar(self, cidade_id, diagrama_id, conteudo, versao_base, forcar=False):
        return self.pedir("PUT", "/api/cidades/%s/diagramas/%s" % (cidade_id, diagrama_id),
                          {"conteudo": conteudo, "versao_base": versao_base, "forcar": forcar})


# ============================================================================
#  FILA DE ENVIO (sem conexao: guarda e envia depois)
# ============================================================================

def _pasta_pendentes():
    return os.path.join(_pasta_programa(), "pendentes")


def _nome_pendente(cidade_id, diagrama_id):
    return "%s__%s.json" % (cidade_id, diagrama_id)


def enfileirar(cidade_id, diagrama_id, conteudo, versao_base, titulo="", cidade_titulo=""):
    _gravar_json(os.path.join(_pasta_pendentes(), _nome_pendente(cidade_id, diagrama_id)),
                 {"cidade": cidade_id, "diagrama": diagrama_id, "conteudo": conteudo,
                  "versao_base": versao_base, "titulo": titulo, "cidade_titulo": cidade_titulo,
                  "quando": time.strftime("%Y-%m-%d %H:%M:%S")})


def pendentes():
    pasta = _pasta_pendentes()
    itens = []
    for nome in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        if not nome.endswith(".json"):
            continue
        try:
            with open(os.path.join(pasta, nome), encoding="utf-8") as fp:
                item = json.load(fp)
            item["_arquivo"] = os.path.join(pasta, nome)
            itens.append(item)
        except (OSError, ValueError):
            pass
    return itens


def pendente_de(cidade_id, diagrama_id):
    for item in pendentes():
        if item.get("cidade") == cidade_id and item.get("diagrama") == diagrama_id:
            return item
    return None


def tirar_da_fila(cidade_id, diagrama_id):
    try:
        os.remove(os.path.join(_pasta_pendentes(), _nome_pendente(cidade_id, diagrama_id)))
    except OSError:
        pass


def enviar_pendentes(conexao):
    """Tenta mandar o que ficou guardado. Se alguem salvou o mesmo diagrama
    enquanto isso, NADA se perde: a versao guardada vira uma copia
    '<nome> (enviado depois)' na mesma cidade.
    Devolve {'enviados': [...], 'copias': [...], 'falhou': bool}."""
    resultado = {"enviados": [], "copias": [], "falhou": False, "detalhes": []}
    for item in pendentes():
        try:
            r = conexao.salvar(item["cidade"], item["diagrama"], item["conteudo"],
                               item["versao_base"])
            resultado["enviados"].append(item.get("titulo") or item["diagrama"])
            resultado["detalhes"].append({"cidade": item["cidade"], "diagrama": item["diagrama"],
                                          "versao": r.get("versao")})
        except ErroServidor as erro:
            if erro.sem_conexao or erro.status == 401:
                resultado["falhou"] = True
                break
            if erro.status in (409, 404):
                nome = "%s (enviado depois %s)" % (item.get("titulo") or item["diagrama"],
                                                   time.strftime("%d-%m %H%M"))
                try:
                    conexao.criar_diagrama(item["cidade"], nome, item["conteudo"])
                    resultado["copias"].append(nome)
                except ErroServidor:
                    resultado["falhou"] = True
                    break
            else:
                resultado["falhou"] = True
                break
        try:
            os.remove(item["_arquivo"])
        except OSError:
            pass
    return resultado
