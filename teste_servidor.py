"""Testa o Servidor WaspFiber junto com o cliente (waspfiber_nuvem), sem
internet: sobe o servidor aqui mesmo numa porta livre.
Rodar:  python teste_servidor.py"""
import os
import sys
import tempfile
import threading
import time

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="waspfiber_appdata_")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "servidor"))
import waspfiber_servidor as ws
import waspfiber_nuvem as nuvem
from waspfiber import Rede, TIPO_DIO

FALHAS = []


def checar(condicao, descricao, detalhe=""):
    print("  %s %s%s" % ("[ok]  " if condicao else "[FALHOU]", descricao,
                         ("  -> " + str(detalhe)) if detalhe else ""))
    if not condicao:
        FALHAS.append(descricao)


def erro_de(funcao):
    try:
        funcao()
    except nuvem.ErroServidor as erro:
        return erro
    return None


dados = tempfile.mkdtemp(prefix="waspfiber_dados_")
srv = ws.criar_servidor(dados, "127.0.0.1", 0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = "http://127.0.0.1:%d" % srv.server_address[1]
nuvem.SERVIDOR_PADRAO = url          # o endereco e fixo no programa; no teste, o local
arm = srv.RequestHandlerClass.armazem

print("== contas ==")
arm.criar_empresa("Junior Telecom", "Junior Telecom LTDA")
arm.definir_usuario("junior-telecom", "Tulio", "Tulio R.", "senha-forte-123", "admin")
arm.criar_empresa("outro-provedor", "Outro Provedor")
arm.definir_usuario("outro-provedor", "ana", "Ana", "outra-senha-456")
try:
    arm.definir_usuario("junior-telecom", "x", "X", "curta")
    checar(False, "senha curta recusada")
except ValueError:
    checar(True, "senha curta recusada")
usuarios = ws._ler_json(os.path.join(dados, "empresas", "junior-telecom", "usuarios.json"))
checar("senha-forte-123" not in str(usuarios) and usuarios["tulio"]["hash"],
       "senha guardada so como hash (PBKDF2)")
checar(nuvem.Conexao(url).saude()["servidor"] == "WaspFiber", "servidor responde /api/saude")
t0 = time.time()
e = erro_de(lambda: nuvem.Conexao.entrar(url, "junior-telecom", "tulio", "errada"))
checar(e and e.status == 401 and time.time() - t0 >= 0.9, "senha errada: 401 e espera 1 s")
c = nuvem.Conexao.entrar(url, "Junior Telecom", "TULIO", "senha-forte-123")
checar(c.token and c.info["empresa_nome"] == "Junior Telecom LTDA", "login (empresa e usuario sem diferenciar maiuscula)")
salvo = nuvem.ler_sessao()
checar(salvo.get("token") == c.token and "senha" not in str(salvo),
       "sessao lembrada no PC sem a senha")
checar(nuvem.Conexao.da_sessao_salva().conferir()["nome"] == "Tulio R.", "sessao salva continua valendo")
e = erro_de(lambda: nuvem.Conexao(url, "token-falso").cidades())
checar(e and e.status == 401, "sem login nao lista nada")

print("== cidades e diagramas ==")
checar(c.cidades() == [], "empresa nova sem cidades")
cid = c.criar_cidade("Santos", "sp")
checar(cid["id"] == "santos-sp" and cid["titulo"] == "Santos - SP", "cria cidade", cid)
e = erro_de(lambda: c.criar_cidade("Santos", "SP"))
checar(e and e.status == 409, "cidade repetida: 409")
e = erro_de(lambda: c.criar_cidade("X", "ZZ"))
checar(e and e.status == 400, "UF invalida: 400")
r = Rede()
r.definir_local({"tipo": "CTO", "nome": "CTO Gonzaga 03", "cidade": "Santos - SP"})
r.add_equipamento("DIO", TIPO_DIO, 12)
novo = c.criar_diagrama("santos-sp", "CTO Gonzaga 03", r.to_dict())
checar(novo["id"] == "cto-gonzaga-03" and novo["versao"], "cria diagrama", novo)
novo2 = c.criar_diagrama("santos-sp", "CTO Gonzaga 03", r.to_dict())
checar(novo2["id"] == "cto-gonzaga-03-2", "nome repetido ganha -2")
lista = c.diagramas("santos-sp")
r_coord = Rede()
r_coord.definir_local({"tipo": "POP", "nome": "POP com ponto", "lat": -23.93, "lon": -46.33})
c.criar_diagrama("santos-sp", "POP com ponto", r_coord.to_dict())
pop = next(i for i in c.diagramas("santos-sp") if i["tipo"] == "POP")
checar(pop["lat"] == -23.93 and pop["lon"] == -46.33 and pop["tem_coordenada"],
       "lista de diagramas traz a coordenada (pro mapa da cidade)")
lista = [i for i in c.diagramas("santos-sp") if i["tipo"] == "CTO"]
checar("lat" not in lista[0], "sem coordenada: nao manda lat/lon")
checar(len(lista) == 2 and lista[0]["tipo"] == "CTO" and lista[0]["equipamentos"] == 1
       and lista[0]["alterado_por"] == "Tulio R.", "lista diagramas com resumo", lista[0])
aberto = c.abrir("santos-sp", "cto-gonzaga-03")
checar(Rede.from_dict(aberto["conteudo"]).local["nome"] == "CTO Gonzaga 03", "abre o diagrama")
c2 = nuvem.Conexao.entrar(url, "outro-provedor", "ana", "outra-senha-456")
checar(c2.cidades() == [] and erro_de(lambda: c2.diagramas("santos-sp")).status == 404,
       "outra empresa nao ve as cidades da Junior")

print("== salvar e conflito ==")
r2 = Rede.from_dict(aberto["conteudo"])
r2.add_equipamento("DIO 2", TIPO_DIO, 24)
s1 = c.salvar("santos-sp", "cto-gonzaga-03", r2.to_dict(), aberto["versao"])
checar(s1["versao"] != aberto["versao"], "salva e ganha versao nova")
e = erro_de(lambda: c.salvar("santos-sp", "cto-gonzaga-03", r2.to_dict(), aberto["versao"]))
checar(e and e.status == 409 and e.extra.get("alterado_por") == "Tulio R.",
       "salvar em cima de versao velha: 409 com quem alterou", e and e.extra)
forcado = c.salvar("santos-sp", "cto-gonzaga-03", r2.to_dict(), aberto["versao"], forcar=True)
checar(forcado["versao"], "forcar salva mesmo assim")
hist = os.path.join(dados, "empresas", "junior-telecom", "cidades", "santos-sp", "historico",
                    "cto-gonzaga-03")
checar(os.path.isdir(hist) and len(os.listdir(hist)) >= 1, "guarda as versoes anteriores (historico)")
e = erro_de(lambda: c.salvar("santos-sp", "cto-gonzaga-03", {"nada": 1}, forcado["versao"]))
checar(e and e.status == 400, "recusa conteudo que nao e diagrama")
e = erro_de(lambda: c.abrir("santos-sp", "../../etc"))
checar(e and e.status in (404,), "nao deixa sair da pasta (..)")

print("== sem conexao: guarda e envia depois ==")
fora = nuvem.Conexao("http://127.0.0.1:9", c.token)
e = erro_de(lambda: fora.salvar("santos-sp", "cto-gonzaga-03", r2.to_dict(), forcado["versao"]))
checar(e and e.sem_conexao, "servidor fora: erro sem_conexao")
r2.add_equipamento("DIO 3", TIPO_DIO, 12)
nuvem.enfileirar("santos-sp", "cto-gonzaga-03", r2.to_dict(), forcado["versao"], "CTO Gonzaga 03")
checar(len(nuvem.pendentes()) == 1 and nuvem.pendente_de("santos-sp", "cto-gonzaga-03"),
       "fica na fila de envio")
res = nuvem.enviar_pendentes(fora)
checar(res["falhou"] and len(nuvem.pendentes()) == 1, "sem servidor: continua na fila")
res = nuvem.enviar_pendentes(c)
checar(res["enviados"] == ["CTO Gonzaga 03"] and nuvem.pendentes() == [],
       "servidor voltou: envia e apaga a copia temporaria", res)
checar(len(c.abrir("santos-sp", "cto-gonzaga-03")["conteudo"]["equipamentos"]) == 3,
       "o que estava na fila chegou no servidor")
velho = c.abrir("santos-sp", "cto-gonzaga-03")["versao"]
nuvem.enfileirar("santos-sp", "cto-gonzaga-03", r.to_dict(), "versao-velha", "CTO Gonzaga 03")
res = nuvem.enviar_pendentes(c)
checar(len(res["copias"]) == 1 and c.abrir("santos-sp", "cto-gonzaga-03")["versao"] == velho
       and len(c.diagramas("santos-sp")) == 4,
       "conflito na fila: vira copia, nao apaga o trabalho de ninguem", res)
print("== e-mail, dominio e criar conta (B0.41) ==")
arm.definir_dominio("junior-telecom", "@JuniorTelecom.com.br")
try:
    arm.definir_dominio("outro-provedor", "juniortelecom.com.br")
    checar(False, "dominio de outra empresa recusado")
except ValueError:
    checar(True, "dominio de outra empresa recusado")
checar(nuvem.Conexao.empresa_do_email("x@juniortelecom.com.br", url) == "Junior Telecom LTDA",
       "empresa pelo dominio do e-mail")
checar(nuvem.Conexao.empresa_do_email("x@gmail.com", url) is None, "dominio sem empresa: None")
emps = nuvem.Conexao.empresas(url)
checar(emps == [{"id": "junior-telecom", "nome": "Junior Telecom LTDA", "dominios": ["juniortelecom.com.br"]}],
       "lista publica de empresas: so as com dominio, so nome e dominio", emps)
e = erro_de(lambda: nuvem.Conexao.criar_conta("Zé", "ze@gmail.com", "senha-do-ze-1", url))
checar(e and e.status == 400 and "dominio" in str(e), "criar conta com dominio de fora: recusa")
r = nuvem.Conexao.criar_conta("Zé Técnico", "Ze@JuniorTelecom.com.br", "senha-do-ze-1", url)
checar(r["status"] == "pendente" and r["empresa_nome"] == "Junior Telecom LTDA", "conta criada pendente")
e = erro_de(lambda: nuvem.Conexao.criar_conta("Zé", "ze@juniortelecom.com.br", "senha-do-ze-1", url))
checar(e and e.status == 409, "e-mail repetido: 409")
e = erro_de(lambda: nuvem.Conexao.entrar_email("ze@juniortelecom.com.br", "senha-do-ze-1", url))
checar(e and e.status == 403 and "aprovacao" in str(e), "pendente nao entra (403)")
arm.renomear_usuario("junior-telecom", "tulio", "tulio@juniortelecom.com.br")
adm = nuvem.Conexao.entrar_email("TULIO@juniortelecom.com.br", "senha-forte-123", url)
checar(adm.info["papel"] == "admin" and adm.info["empresa"] == "junior-telecom",
       "login por e-mail (renomeado, mantem a senha e o papel)")
checar([p["email"] for p in adm.pedidos()] == ["ze@juniortelecom.com.br"], "admin ve o pedido")
comum = nuvem.Conexao.entrar(url, "outro-provedor", "ana", "outra-senha-456")
e = erro_de(lambda: comum.pedidos())
checar(e and e.status == 403, "quem nao e admin nao ve pedidos")
adm.decidir_pedido("ze@juniortelecom.com.br", True)
ze = nuvem.Conexao.entrar_email("ze@juniortelecom.com.br", "senha-do-ze-1", url)
checar(ze.info["papel"] == "usuario" and ze.cidades()[0]["id"] == "santos-sp",
       "aprovado: entra e ve as cidades da empresa")
nuvem.Conexao.criar_conta("Intruso", "intruso@juniortelecom.com.br", "senha-intruso-1", url)
adm.decidir_pedido("intruso@juniortelecom.com.br", False)
e = erro_de(lambda: nuvem.Conexao.entrar_email("intruso@juniortelecom.com.br", "senha-intruso-1", url))
checar(e and e.status == 401 and adm.pedidos() == [], "recusado: conta apagada")
c = nuvem.Conexao.entrar(url, "junior-telecom", "tulio@juniortelecom.com.br", "senha-forte-123")

print("== bloqueio e backup (B0.40) ==")
ws.BLOQUEIO_S = 2
for _ in range(5):
    erro_de(lambda: nuvem.Conexao.entrar(url, "outro-provedor", "ana", "errada"))
e = erro_de(lambda: nuvem.Conexao.entrar(url, "outro-provedor", "ana", "outra-senha-456"))
checar(e and e.status == 429 and "Muitas tentativas" in str(e),
       "5 senhas erradas: bloqueia ate a senha certa", e and str(e))
checar(nuvem.Conexao.entrar_email("tulio@juniortelecom.com.br", "senha-forte-123", url).token,
       "o bloqueio e so daquele login (os outros entram)")
time.sleep(2.1)
checar(nuvem.Conexao.entrar(url, "outro-provedor", "ana", "outra-senha-456").token,
       "passado o tempo, entra de novo")
import tarfile
pasta_bk = tempfile.mkdtemp(prefix="waspfiber_bk_")
bk = ws.fazer_backup(dados, pasta_bk)
with tarfile.open(bk) as tar:
    nomes = tar.getnames()
checar(any(n.endswith("cto-gonzaga-03.wasp.json") for n in nomes) and
       any(n.endswith("usuarios.json") for n in nomes), "backup leva diagramas e contas")
ws.MAX_BACKUPS = 2
for _ in range(3):
    time.sleep(1.1)
    ws.fazer_backup(dados, pasta_bk)
checar(len(os.listdir(pasta_bk)) == 2, "guarda so os ultimos backups", os.listdir(pasta_bk))
c.sair()
checar(erro_de(lambda: c.cidades()) is not None and "token" not in nuvem.ler_sessao(),
       "sair encerra a sessao")
srv.shutdown()

print()
if FALHAS:
    print("!! %d FALHA(S): %s" % (len(FALHAS), "; ".join(FALHAS)))
    raise SystemExit(1)
print("TODOS OS TESTES DO SERVIDOR PASSARAM")
