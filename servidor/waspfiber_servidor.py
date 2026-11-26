# -*- coding: utf-8 -*-
"""Servidor WaspFiber (B0.39).

Guarda as cidades e os diagramas de cada empresa (provedor) e entrega pro
programa pela rede, com login. So biblioteca padrao do Python 3.8+.

Organizacao em disco (pasta de dados):

    dados/
        sessoes.json
        empresas/<empresa>/
            empresa.json                 nome da empresa
            usuarios.json                usuarios (senha guardada com PBKDF2)
            cidades/<cidade>/
                cidade.json
                diagramas/<diagrama>.wasp.json
                historico/<diagrama>/<data>.wasp.json   (ultimas 30 versoes)

Uso:
    python3 waspfiber_servidor.py servir --dados ~/waspfiber-dados --porta 8765
    python3 waspfiber_servidor.py criar-empresa --dados ... <id> "<Nome da empresa>"
    python3 waspfiber_servidor.py criar-usuario --dados ... <empresa> <login> "<Nome>"
                                                 (a senha e pedida no terminal)
    python3 waspfiber_servidor.py listar --dados ...

API (JSON; depois do login: cabecalho  Authorization: Bearer <token>):
    GET  /api/saude
    POST /api/entrar                         {empresa, usuario, senha}
    POST /api/sair
    GET  /api/cidades
    POST /api/cidades                        {nome, uf}
    GET  /api/cidades/<c>/diagramas
    POST /api/cidades/<c>/diagramas          {nome, conteudo}
    GET  /api/cidades/<c>/diagramas/<d>
    PUT  /api/cidades/<c>/diagramas/<d>      {conteudo, versao_base, forcar?}
"""

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tarfile
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSAO_SERVIDOR = "B0.40"
EXTENSAO = ".wasp.json"
MAX_CORPO = 25 * 1024 * 1024
DIAS_SESSAO = 30
MAX_HISTORICO = 30
# bloqueio de senha errada (B0.40): 5 erros em 15 min travam aquele login por 15 min
MAX_ERROS_LOGIN = 5
JANELA_ERROS_S = 15 * 60
BLOQUEIO_S = 15 * 60
# backup automatico (B0.40): um .tar.gz por dia, guarda os ultimos 14
INTERVALO_BACKUP_S = 24 * 3600
MAX_BACKUPS = 14
UFS = ("AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
       "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO")


class ErroApi(Exception):
    def __init__(self, status, mensagem, extra=None):
        super().__init__(mensagem)
        self.status, self.mensagem, self.extra = status, mensagem, extra or {}


# ============================================================================
#  ARMAZENAMENTO
# ============================================================================

def slug(texto):
    """'Sao Jose - SP' -> 'sao-jose-sp' (id seguro pra pasta e url)."""
    s = unicodedata.normalize("NFD", str(texto or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60]


def _ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return padrao


def _gravar_json(caminho, dados):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = "%s.%s.tmp" % (caminho, secrets.token_hex(4))
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(dados, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def hash_senha(senha, sal=None):
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), 200000)
    return sal, h.hex()


def versao_de(conteudo_bytes):
    return hashlib.sha256(conteudo_bytes).hexdigest()[:16]


class Armazem:
    """Tudo o que o servidor guarda. Uma trava por armazem: as gravacoes sao
    rapidas e assim duas pessoas salvando ao mesmo tempo nunca se misturam."""

    def __init__(self, pasta):
        self.pasta = os.path.abspath(os.path.expanduser(pasta))
        os.makedirs(os.path.join(self.pasta, "empresas"), exist_ok=True)
        self.trava = threading.RLock()
        self.sessoes = _ler_json(os.path.join(self.pasta, "sessoes.json"), {}) or {}
        self.erros_login = {}        # (empresa, login) -> [instantes dos erros]

    # ---------------- empresas e usuarios ----------------
    def _p_empresa(self, empresa):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", empresa or ""):
            raise ErroApi(404, "Empresa nao encontrada.")
        return os.path.join(self.pasta, "empresas", empresa)

    def criar_empresa(self, empresa_id, nome):
        empresa_id = slug(empresa_id)
        if not empresa_id:
            raise ValueError("Id da empresa invalido.")
        p = self._p_empresa(empresa_id)
        if os.path.exists(os.path.join(p, "empresa.json")):
            raise ValueError("A empresa '%s' ja existe." % empresa_id)
        _gravar_json(os.path.join(p, "empresa.json"),
                     {"id": empresa_id, "nome": nome, "criada_em": time.strftime("%Y-%m-%d %H:%M:%S")})
        _gravar_json(os.path.join(p, "usuarios.json"), {})
        os.makedirs(os.path.join(p, "cidades"), exist_ok=True)
        return empresa_id

    def empresa(self, empresa_id):
        dados = _ler_json(os.path.join(self._p_empresa(empresa_id), "empresa.json"))
        if not dados:
            raise ErroApi(404, "Empresa nao encontrada.")
        return dados

    def definir_usuario(self, empresa_id, login, nome, senha, papel="usuario"):
        self.empresa(empresa_id)
        login = (login or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{2,40}", login):
            raise ValueError("Login invalido (use letras, numeros, ponto, - ou _).")
        if len(senha or "") < 8:
            raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
        caminho = os.path.join(self._p_empresa(empresa_id), "usuarios.json")
        with self.trava:
            usuarios = _ler_json(caminho, {}) or {}
            sal, h = hash_senha(senha)
            usuarios[login] = {"nome": nome or login, "sal": sal, "hash": h, "papel": papel}
            _gravar_json(caminho, usuarios)

    def _bloqueado(self, chave):
        """Minutos que faltam pra liberar o login (0 = liberado)."""
        agora = time.time()
        erros = [t for t in self.erros_login.get(chave, []) if agora - t < JANELA_ERROS_S]
        self.erros_login[chave] = erros
        if len(erros) >= MAX_ERROS_LOGIN and agora - erros[-1] < BLOQUEIO_S:
            return int((BLOQUEIO_S - (agora - erros[-1])) // 60) + 1
        return 0

    def entrar(self, empresa_id, login, senha):
        empresa_id = slug(empresa_id)
        login = (login or "").strip().lower()
        chave = (empresa_id, login)
        with self.trava:
            minutos = self._bloqueado(chave)
        if minutos:
            raise ErroApi(429, "Muitas tentativas com senha errada. Tente de novo em %d minuto%s."
                          % (minutos, "" if minutos == 1 else "s"))
        try:
            empresa = self.empresa(empresa_id)
            usuarios = _ler_json(os.path.join(self._p_empresa(empresa_id), "usuarios.json"), {})
        except ErroApi:
            empresa, usuarios = None, {}
        conta = (usuarios or {}).get(login)
        ok = False
        if conta:
            _, h = hash_senha(senha or "", conta["sal"])
            ok = hmac.compare_digest(h, conta["hash"])
        if not (empresa and ok):
            with self.trava:
                self.erros_login.setdefault(chave, []).append(time.time())
            time.sleep(1.0)          # freia tentativa de adivinhar senha
            raise ErroApi(401, "Empresa, usuario ou senha incorretos.")
        with self.trava:
            self.erros_login.pop(chave, None)
        token = secrets.token_urlsafe(32)
        with self.trava:
            self._limpar_sessoes()
            self.sessoes[token] = {"empresa": empresa_id, "usuario": login,
                                   "nome": conta["nome"], "expira": time.time() + DIAS_SESSAO * 86400}
            _gravar_json(os.path.join(self.pasta, "sessoes.json"), self.sessoes)
        return {"token": token, "usuario": login, "nome": conta["nome"],
                "empresa": empresa_id, "empresa_nome": empresa["nome"]}

    def sair(self, token):
        with self.trava:
            if self.sessoes.pop(token, None) is not None:
                _gravar_json(os.path.join(self.pasta, "sessoes.json"), self.sessoes)

    def _limpar_sessoes(self):
        agora = time.time()
        for token in [t for t, s in self.sessoes.items() if s.get("expira", 0) < agora]:
            del self.sessoes[token]

    def sessao(self, token):
        s = self.sessoes.get(token or "")
        if not s or s.get("expira", 0) < time.time():
            raise ErroApi(401, "Sessao expirada. Entre de novo.")
        return s

    # ---------------- cidades ----------------
    def _p_cidade(self, empresa_id, cidade_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", cidade_id or ""):
            raise ErroApi(404, "Cidade nao encontrada.")
        p = os.path.join(self._p_empresa(empresa_id), "cidades", cidade_id)
        if not os.path.isfile(os.path.join(p, "cidade.json")):
            raise ErroApi(404, "Cidade nao encontrada.")
        return p

    def listar_cidades(self, empresa_id):
        base = os.path.join(self._p_empresa(empresa_id), "cidades")
        cidades = []
        for cid in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            dados = _ler_json(os.path.join(base, cid, "cidade.json"))
            if not dados:
                continue
            pasta_d = os.path.join(base, cid, "diagramas")
            qtd = len([n for n in os.listdir(pasta_d) if n.endswith(EXTENSAO)]) \
                if os.path.isdir(pasta_d) else 0
            cidades.append(dict(dados, id=cid, diagramas=qtd))
        return sorted(cidades, key=lambda c: slug(c.get("titulo", c["id"])))

    def criar_cidade(self, empresa_id, nome, uf, por):
        nome, uf = (nome or "").strip(), (uf or "").strip().upper()
        if not nome:
            raise ErroApi(400, "Informe o nome da cidade.")
        if uf and uf not in UFS:
            raise ErroApi(400, "UF invalida.")
        titulo = "%s - %s" % (nome, uf) if uf else nome
        cid = slug(titulo)
        if not cid:
            raise ErroApi(400, "Nome de cidade invalido.")
        p = os.path.join(self._p_empresa(empresa_id), "cidades", cid)
        with self.trava:
            if os.path.exists(os.path.join(p, "cidade.json")):
                raise ErroApi(409, "Ja existe a cidade \"%s\"." % titulo)
            dados = {"nome": nome, "uf": uf, "titulo": titulo, "criada_por": por,
                     "criada_em": time.strftime("%Y-%m-%d %H:%M:%S")}
            _gravar_json(os.path.join(p, "cidade.json"), dados)
            os.makedirs(os.path.join(p, "diagramas"), exist_ok=True)
        return dict(dados, id=cid, diagramas=0)

    # ---------------- diagramas ----------------
    def _p_diagrama(self, empresa_id, cidade_id, diagrama_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", diagrama_id or ""):
            raise ErroApi(404, "Diagrama nao encontrado.")
        return os.path.join(self._p_cidade(empresa_id, cidade_id), "diagramas",
                            diagrama_id + EXTENSAO)

    @staticmethod
    def _resumo(caminho, did):
        bruto = open(caminho, "rb").read()
        item = {"id": did, "titulo": did, "tipo": "", "endereco": "", "equipamentos": 0,
                "fusoes": 0, "tem_coordenada": False, "modificado": os.path.getmtime(caminho),
                "versao": versao_de(bruto), "alterado_por": "", "erro": ""}
        try:
            dados = json.loads(bruto.decode("utf-8"))
            local = dados.get("local") or {}
            meta = dados.get("_servidor") or {}
            item.update(tipo=str(local.get("tipo") or ""),
                        titulo=str(local.get("nome") or "").strip() or did,
                        endereco=str(local.get("endereco") or ""),
                        tem_coordenada=local.get("lat") not in (None, ""),
                        equipamentos=len(dados.get("equipamentos") or []),
                        fusoes=len(dados.get("fusoes") or []),
                        alterado_por=meta.get("alterado_por", ""))
        except Exception as erro:
            item["erro"] = "arquivo com defeito (%s)" % erro.__class__.__name__
        return item

    def listar_diagramas(self, empresa_id, cidade_id):
        pasta = os.path.join(self._p_cidade(empresa_id, cidade_id), "diagramas")
        itens = []
        for nome in os.listdir(pasta) if os.path.isdir(pasta) else []:
            if nome.endswith(EXTENSAO):
                itens.append(self._resumo(os.path.join(pasta, nome), nome[:-len(EXTENSAO)]))
        ordem = {"POP": 0, "CEO": 1, "CTO": 2}
        return sorted(itens, key=lambda i: (ordem.get(i["tipo"], 3), slug(i["titulo"])))

    def ler_diagrama(self, empresa_id, cidade_id, diagrama_id):
        caminho = self._p_diagrama(empresa_id, cidade_id, diagrama_id)
        if not os.path.isfile(caminho):
            raise ErroApi(404, "Diagrama nao encontrado.")
        bruto = open(caminho, "rb").read()
        return {"id": diagrama_id, "conteudo": json.loads(bruto.decode("utf-8")),
                "versao": versao_de(bruto)}

    def _gravar_diagrama(self, caminho, conteudo, por):
        if not isinstance(conteudo, dict) or "equipamentos" not in conteudo:
            raise ErroApi(400, "Conteudo invalido: nao parece um diagrama do WaspFiber.")
        conteudo = dict(conteudo)
        conteudo["_servidor"] = {"alterado_por": por, "alterado_em": time.strftime("%Y-%m-%d %H:%M:%S")}
        bruto = json.dumps(conteudo, ensure_ascii=False, indent=1).encode("utf-8")
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        tmp = "%s.%s.tmp" % (caminho, secrets.token_hex(4))
        with open(tmp, "wb") as fp:
            fp.write(bruto)
        os.replace(tmp, caminho)
        return versao_de(bruto)

    def _guardar_historico(self, caminho, cidade_pasta, diagrama_id):
        if not os.path.isfile(caminho):
            return
        pasta = os.path.join(cidade_pasta, "historico", diagrama_id)
        os.makedirs(pasta, exist_ok=True)
        destino = os.path.join(pasta, time.strftime("%Y%m%d-%H%M%S") + EXTENSAO)
        with open(caminho, "rb") as a, open(destino, "wb") as b:
            b.write(a.read())
        antigos = sorted(os.listdir(pasta))
        for velho in antigos[:-MAX_HISTORICO]:
            try:
                os.remove(os.path.join(pasta, velho))
            except OSError:
                pass

    def criar_diagrama(self, empresa_id, cidade_id, nome, conteudo, por):
        base = slug(nome) or "diagrama"
        pasta = os.path.join(self._p_cidade(empresa_id, cidade_id), "diagramas")
        with self.trava:
            did, n = base, 2
            while os.path.exists(os.path.join(pasta, did + EXTENSAO)):
                did, n = "%s-%d" % (base, n), n + 1
            versao = self._gravar_diagrama(os.path.join(pasta, did + EXTENSAO), conteudo, por)
        return {"id": did, "versao": versao}

    def salvar_diagrama(self, empresa_id, cidade_id, diagrama_id, conteudo, versao_base,
                        por, forcar=False):
        caminho = self._p_diagrama(empresa_id, cidade_id, diagrama_id)
        with self.trava:
            if not os.path.isfile(caminho):
                raise ErroApi(404, "Diagrama nao encontrado (pode ter sido apagado).")
            atual = versao_de(open(caminho, "rb").read())
            if atual != versao_base and not forcar:
                meta = (_ler_json(caminho, {}) or {}).get("_servidor") or {}
                raise ErroApi(409, "Outra pessoa salvou este diagrama depois que voce abriu.",
                              {"versao_atual": atual, "alterado_por": meta.get("alterado_por", ""),
                               "alterado_em": meta.get("alterado_em", "")})
            self._guardar_historico(caminho, self._p_cidade(empresa_id, cidade_id), diagrama_id)
            versao = self._gravar_diagrama(caminho, conteudo, por)
        return {"id": diagrama_id, "versao": versao}


# ============================================================================
#  BACKUP
# ============================================================================

def fazer_backup(pasta_dados, pasta_backups):
    """Copia a pasta de dados inteira num .tar.gz com a data; guarda os
    ultimos MAX_BACKUPS. Devolve o caminho do arquivo criado."""
    os.makedirs(pasta_backups, exist_ok=True)
    destino = os.path.join(pasta_backups,
                           "waspfiber-dados-%s.tar.gz" % time.strftime("%Y%m%d-%H%M%S"))
    tmp = destino + ".tmp"
    with tarfile.open(tmp, "w:gz") as tar:
        tar.add(pasta_dados, arcname="waspfiber-dados",
                filter=lambda info: None if info.name.endswith(".tmp") else info)
    os.replace(tmp, destino)
    antigos = sorted(n for n in os.listdir(pasta_backups)
                     if n.startswith("waspfiber-dados-") and n.endswith(".tar.gz"))
    for velho in antigos[:-MAX_BACKUPS]:
        try:
            os.remove(os.path.join(pasta_backups, velho))
        except OSError:
            pass
    return destino


def backup_periodico(pasta_dados, pasta_backups):
    """Thread: faz backup quando o ultimo tem mais de um dia (confere de
    hora em hora - entao tambem logo depois de ligar)."""
    while True:
        try:
            existentes = sorted(n for n in os.listdir(pasta_backups)
                                if n.endswith(".tar.gz")) if os.path.isdir(pasta_backups) else []
            ultimo = os.path.getmtime(os.path.join(pasta_backups, existentes[-1])) \
                if existentes else 0
            if time.time() - ultimo >= INTERVALO_BACKUP_S - 60:
                print("backup:", fazer_backup(pasta_dados, pasta_backups), flush=True)
        except Exception as erro:
            print("backup falhou:", erro, flush=True)
        time.sleep(3600)


# ============================================================================
#  HTTP
# ============================================================================

class Manipulador(BaseHTTPRequestHandler):
    armazem = None
    server_version = "WaspFiber/" + VERSAO_SERVIDOR
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), formato % args))

    def _responder(self, status, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho > MAX_CORPO:
            raise ErroApi(413, "Arquivo grande demais.")
        if not tamanho:
            return {}
        try:
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except ValueError:
            raise ErroApi(400, "JSON invalido.")

    def _sessao(self):
        cab = self.headers.get("Authorization") or ""
        token = cab[7:] if cab.startswith("Bearer ") else ""
        return token, self.armazem.sessao(token)

    def _tratar(self, metodo):
        try:
            partes = [p for p in self.path.split("?")[0].split("/") if p]
            if partes[:1] != ["api"]:
                raise ErroApi(404, "Nada aqui.")
            rota = partes[1:]
            a = self.armazem
            if rota == ["saude"] and metodo == "GET":
                return self._responder(200, {"ok": True, "servidor": "WaspFiber",
                                             "versao": VERSAO_SERVIDOR})
            if rota == ["entrar"] and metodo == "POST":
                d = self._corpo()
                return self._responder(200, a.entrar(d.get("empresa"), d.get("usuario"),
                                                     d.get("senha")))
            token, s = self._sessao()
            emp, por = s["empresa"], s["nome"]
            if rota == ["sair"] and metodo == "POST":
                a.sair(token)
                return self._responder(200, {"ok": True})
            if rota == ["eu"] and metodo == "GET":
                return self._responder(200, {"usuario": s["usuario"], "nome": s["nome"],
                                             "empresa": emp,
                                             "empresa_nome": a.empresa(emp)["nome"]})
            if rota == ["cidades"]:
                if metodo == "GET":
                    return self._responder(200, {"cidades": a.listar_cidades(emp)})
                if metodo == "POST":
                    d = self._corpo()
                    return self._responder(201, a.criar_cidade(emp, d.get("nome"), d.get("uf"), por))
            if len(rota) == 3 and rota[0] == "cidades" and rota[2] == "diagramas":
                if metodo == "GET":
                    return self._responder(200, {"diagramas": a.listar_diagramas(emp, rota[1])})
                if metodo == "POST":
                    d = self._corpo()
                    return self._responder(201, a.criar_diagrama(emp, rota[1], d.get("nome"),
                                                                 d.get("conteudo"), por))
            if len(rota) == 4 and rota[0] == "cidades" and rota[2] == "diagramas":
                if metodo == "GET":
                    return self._responder(200, a.ler_diagrama(emp, rota[1], rota[3]))
                if metodo == "PUT":
                    d = self._corpo()
                    return self._responder(200, a.salvar_diagrama(
                        emp, rota[1], rota[3], d.get("conteudo"), d.get("versao_base"), por,
                        bool(d.get("forcar"))))
            raise ErroApi(404, "Nada aqui.")
        except ErroApi as erro:
            self._responder(erro.status, dict(erro.extra, erro=erro.mensagem))
        except Exception as erro:   # nunca derruba o servidor
            self.log_message("ERRO %r", erro)
            self._responder(500, {"erro": "Erro interno do servidor."})

    def do_GET(self):
        self._tratar("GET")

    def do_POST(self):
        self._tratar("POST")

    def do_PUT(self):
        self._tratar("PUT")


def criar_servidor(pasta_dados, endereco="0.0.0.0", porta=8765):
    armazem = Armazem(pasta_dados)
    classe = type("ManipuladorWasp", (Manipulador,), {"armazem": armazem})
    return ThreadingHTTPServer((endereco, porta), classe)


# ============================================================================
#  LINHA DE COMANDO
# ============================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="Servidor WaspFiber")
    sub = ap.add_subparsers(dest="comando", required=True)
    for nome in ("servir", "criar-empresa", "criar-usuario", "listar", "backup"):
        p = sub.add_parser(nome)
        p.add_argument("--dados", default="~/waspfiber-dados")
        if nome in ("servir", "backup"):
            p.add_argument("--backups", default="~/waspfiber-backups")
        if nome == "servir":
            p.add_argument("--endereco", default="0.0.0.0")
            p.add_argument("--porta", type=int, default=8765)
        if nome == "criar-empresa":
            p.add_argument("id")
            p.add_argument("nome")
        if nome == "criar-usuario":
            p.add_argument("empresa")
            p.add_argument("login")
            p.add_argument("nome")
            p.add_argument("--admin", action="store_true")
    args = ap.parse_args(argv)
    armazem = Armazem(args.dados)
    if args.comando == "servir":
        srv = criar_servidor(args.dados, args.endereco, args.porta)
        threading.Thread(target=backup_periodico, daemon=True, args=(
            armazem.pasta, os.path.abspath(os.path.expanduser(args.backups)))).start()
        print("WaspFiber %s servindo em %s:%d (dados em %s)"
              % (VERSAO_SERVIDOR, args.endereco, args.porta, armazem.pasta), flush=True)
        srv.serve_forever()
    elif args.comando == "backup":
        print("Backup:", fazer_backup(armazem.pasta,
                                      os.path.abspath(os.path.expanduser(args.backups))))
    elif args.comando == "criar-empresa":
        print("Empresa criada:", armazem.criar_empresa(args.id, args.nome))
    elif args.comando == "criar-usuario":
        senha = getpass.getpass("Senha para %s: " % args.login)
        if senha != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas nao conferem.")
        armazem.definir_usuario(args.empresa, args.login, args.nome, senha,
                                "admin" if args.admin else "usuario")
        print("Usuario '%s' pronto na empresa '%s'." % (args.login, args.empresa))
    elif args.comando == "listar":
        base = os.path.join(armazem.pasta, "empresas")
        for emp in sorted(os.listdir(base)):
            dados = _ler_json(os.path.join(base, emp, "empresa.json"), {})
            usuarios = _ler_json(os.path.join(base, emp, "usuarios.json"), {}) or {}
            print("%s  (%s)  usuarios: %s  cidades: %d" % (
                emp, dados.get("nome", ""), ", ".join(sorted(usuarios)) or "-",
                len(armazem.listar_cidades(emp))))


if __name__ == "__main__":
    main()
