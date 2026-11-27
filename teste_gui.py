"""Testa a interface de verdade num display virtual: cliques, arraste, zoom,
desfazer, busca, lote, duplicar, organizar, pendencias e exportacoes.
Rodar:  xvfb-run -a python teste_gui.py"""
import os
import sys
import types
import tkinter.messagebox as mb
import tkinter.simpledialog as sd

import tempfile
import webbrowser

# configuracao do programa (autosave, cache do mapa) numa
# pasta descartavel: o teste nao mexe no que a pessoa usa de verdade
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="waspfiber_appdata_")

import waspfiber as fttx
from waspfiber import App

PASTA = tempfile.mkdtemp(prefix="waspfiber_teste_").replace("\\", "/")
FALHAS = []


def checar(condicao, descricao, detalhe=""):
    print("  %s %s%s" % ("[ok]  " if condicao else "[FALHOU]", descricao,
                         ("  -> " + str(detalhe)) if detalhe else ""))
    if not condicao:
        FALHAS.append(descricao)


# nada pode abrir um dialogo modal esperando resposta humana
fttx.apagar_autosave()
_recuperar_original = App._oferecer_recuperacao
App._oferecer_recuperacao = lambda self: None
mb.askyesnocancel = lambda *a, **k: False      # "descartar" nos avisos de nao salvo
mb.askyesno = lambda *a, **k: True
mb.showinfo = lambda *a, **k: None
mb.showwarning = lambda *a, **k: None
mb.showerror = lambda *a, **k: None
fttx.perguntar_texto = lambda *a, **k: "TESTE"

# servidor WaspFiber de teste, aqui mesmo (sem internet)
import threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "servidor"))
import waspfiber_servidor as ws
_dados_srv = tempfile.mkdtemp(prefix="waspfiber_dados_")
srv = ws.criar_servidor(_dados_srv, "127.0.0.1", 0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL_SRV = "http://127.0.0.1:%d" % srv.server_address[1]
srv.RequestHandlerClass.armazem.criar_empresa("junior", "Junior Telecom")
srv.RequestHandlerClass.armazem.definir_dominio("junior", "junior.com.br")
srv.RequestHandlerClass.armazem.criar_empresa("beta", "Beta Fibra")
srv.RequestHandlerClass.armazem.definir_dominio("beta", "betafibra.com.br")
srv.RequestHandlerClass.armazem.definir_dominio("beta", "beta.net")
srv.RequestHandlerClass.armazem.definir_usuario("junior", "tulio@junior.com.br", "Tulio",
                                                "senha-teste-123", "admin")
srv.RequestHandlerClass.armazem.definir_usuario("junior", "ana@junior.com.br", "Ana",
                                                "senha-teste-456")
fttx.nuvem.SERVIDOR_PADRAO = URL_SRV      # o endereco e fixo no programa; no teste, o local

app = App()
app.update()
inicio_ao_abrir = app.tela_inicio.visivel()
login_ao_abrir = app.tela_inicio.login.winfo_ismapped()
app.acao_exemplo()
app.update()

print("== janela ==")
checar(len(app.rede.equipamentos) == 7 and len(app.canvas.find_all()) > 300,
       "exemplo desenhado", "%d itens no canvas" % len(app.canvas.find_all()))
primeiro = "DIO-01"
app._clicar_cartao(primeiro)
app.update()
lados = app.arvore.get_children()
checar(len(lados) == 2 and all(len(app.arvore.get_children(l)) == 24 for l in lados),
       "lista lateral mostra traseira e frente do DIO, 24 portas cada")

print("== fusao por clique ==")
livres = [k for k in app.cena.portas if not app.rede.fusoes_na_porta(*k)]
a, b = livres[0], livres[-1]
app._clique_porta(a)
app.update()
checar(app.porta_selecionada is not None, "1o clique seleciona a porta")
antes = len(app.rede.fusoes)
app._clique_porta(b)
app.update()
checar(len(app.rede.fusoes) == antes + 1 and app.porta_selecionada is None,
       "2o clique cria a fusao e limpa a selecao")
cheia = [k for k in app.cena.portas
         if len(app.rede.fusoes_na_porta(*k)) >= app.rede.limite_porta(*k)][0]
antes = len(app.rede.fusoes)
app._clique_porta(cheia)
app.update()
checar(len(app.rede.fusoes) < antes, "clicar em porta cheia oferece remover")

print("== desfazer / refazer ==")
antes = len(app.rede.equipamentos)
app._selecionar_equipamento(primeiro)
app.acao_remover_equipamento()
app.update()
removido = len(app.rede.equipamentos)
app.acao_desfazer()
app.update()
checar(removido == antes - 1 and len(app.rede.equipamentos) == antes,
       "remove e Ctrl+Z devolve")
app.acao_refazer()
app.update()
checar(len(app.rede.equipamentos) == removido, "Ctrl+Y refaz")
app.acao_desfazer()
app.update()

print("== aviso de nao salvo e autosave ==")
checar(app.alteracoes_pendentes and "(nao salvo)" in app.title(), "titulo avisa")
rec, _ = fttx.ler_autosave()
checar(rec is not None, "autosave gravado a cada alteracao")
mb.askyesnocancel = lambda *a, **k: None
checar(app._confirmar_descarte("teste") is False, "cancelar bloqueia a acao")
mb.askyesnocancel = lambda *a, **k: False
# salvar agora vai pro servidor (B0.39): empresa de teste so pra isto
import waspfiber_nuvem as _nv
srv.RequestHandlerClass.armazem.criar_empresa("testes", "Testes")
srv.RequestHandlerClass.armazem.definir_usuario("testes", "gui", "GUI", "senha-teste-789")
app.conexao = _nv.Conexao.entrar(URL_SRV, "testes", "gui", "senha-teste-789")
_cid = app.conexao.criar_cidade("Teste", "SP")
_d = app.conexao.criar_diagrama(_cid["id"], "Rede GUI", app.rede.to_dict())
app.documento = {"cidade": _cid, "id": _d["id"], "versao": _d["versao"]}
app.acao_salvar()
app.update()
app.conexao.sair()
app.conexao = None
checar(not app.alteracoes_pendentes and fttx.ler_autosave()[0] is None,
       "salvar limpa o aviso e o autosave")

print("== criar em lote (novo) ==")
antes = len(app.rede.equipamentos)
dados = {"nome_base": "DIO-LOTE-##", "tipo": fttx.TIPO_DIO, "quantidade": 6,
         "inicio": 1, "num_portas": 24, "tipo_modulo": None, "qtd_modulos": 0}
fttx.DialogLote = type("FalsoDialogLote", (), {"__init__": lambda self, parent: None,
                                               "resultado": dados})
app.acao_criar_lote()
app.update()
criados = [e for e in app.rede.equipamentos.values() if e.nome.startswith("DIO-LOTE-")]
checar(len(app.rede.equipamentos) == antes + 6 and len(criados) == 6,
       "criou 6 de uma vez pela interface", sorted(e.nome for e in criados)[:3])
checar(all(e.num_portas == 24 for e in criados), "todos com 24 portas")
app.acao_desfazer()
app.update()
checar(len(app.rede.equipamentos) == antes, "lote inteiro desfeito com um Ctrl+Z")

print("== duplicar (novo) ==")
alvo = [e for e in app.rede.equipamentos.values() if e.tipo == "OLT"][0]
app._selecionar_equipamento(alvo.id)
fttx.perguntar_texto = lambda *a, **k: "OLT-COPIA"
antes = len(app.rede.equipamentos)
app.acao_duplicar_equipamento()
app.update()
copia = [e for e in app.rede.equipamentos.values() if e.nome == "OLT-COPIA"]
checar(len(app.rede.equipamentos) == antes + 1 and copia, "duplicou pela interface")
checar(copia and len(copia[0].modulos) == len(alvo.modulos), "copia trouxe os modulos")
fttx.perguntar_texto = lambda *a, **k: "TESTE"

print("== organizar layout (novo) ==")
for eq in app.rede.equipamentos.values():
    eq.pos_x, eq.pos_y = 0.0, 0.0
app.acao_organizar()
app.update()
posicoes = {(e.pos_x, e.pos_y) for e in app.rede.equipamentos.values()}
checar(len(posicoes) == len(app.rede.equipamentos), "cada caixa num lugar diferente")
app.acao_desfazer()
app.update()

print("== busca (novo) ==")
janela = fttx.DialogBusca(app, app.rede, app.ir_para)
janela.e_termo.insert(0, "cliente a")
janela._procurar()
janela.update()
checar(len(janela.achados) >= 1, "janela de busca lista o resultado", len(janela.achados))
checar(len(janela.lista.get_children()) == len(janela.achados), "tabela preenchida")
antes_scroll = app.canvas.xview()
janela._abrir_primeiro()
app.update()
checar(app.porta_selecionada is not None, "escolher o resultado seleciona a porta")
chave = (app.porta_selecionada["eq_id"], app.porta_selecionada["modulo_id"],
         app.porta_selecionada["porta_num"])
checar(chave in app.cena.portas, "porta existe no diagrama", chave)
janela.e_termo.delete(0, "end")
janela.e_termo.insert(0, "zzzz")
janela._procurar()
checar(janela.achados == [], "termo inexistente limpa a lista")
janela.destroy()

print("== centralizar no achado ==")
app.escala = 1.5
app.atualizar_tudo()
longe = sorted(app.cena.portas.items(), key=lambda kv: -kv[1]["y"])[0]
app.ir_para({"chave": longe[0], "eq_id": longe[0][0]})
app.update()
visivel_y = app.canvas.yview()
alvo_rel = ((longe[1]["y"] - app.cena.miny) * app.escala) / (app.cena.altura * app.escala)
checar(visivel_y[0] <= alvo_rel <= visivel_y[1] + 0.01,
       "a vista rolou ate a porta encontrada",
       "alvo %.2f, janela %.2f-%.2f" % (alvo_rel, visivel_y[0], visivel_y[1]))
app.atualizar_tudo(centralizar=True)

print("== pendencias (novo) ==")
quebrada = fttx.Rede()
dio = quebrada.add_equipamento("DIO P", fttx.TIPO_DIO, 4)
ac = quebrada.add_equipamento("CTO P", fttx.TIPO_ACOMODADOR)
sp = ac.add_splitter("1x2")
quebrada.criar_fusao(ac.id, sp.id, 2, dio.id, None, 1, "Cliente Y")
app.rede = quebrada
app.atualizar_tudo(centralizar=True)
painel = fttx.DialogPendencias(app, app.rede, app.ir_para, lambda: None)
painel.update()
checar(len(painel.tabela.get_children()) >= 1, "painel lista as pendencias",
       len(painel.tabela.get_children()))
checar(len(painel.tabela_cap.get_children()) == 2, "aba de capacidade preenchida")
painel.tabela.selection_set("0")
painel._abrir()
app.update()
checar(app.porta_selecionada is not None, "duplo clique leva ate a porta do problema")
painel.destroy()

print("== exportacoes pela interface ==")
app.rede = fttx.rede_exemplo()
app.atualizar_tudo(centralizar=True)
cena = fttx.montar_cena(app.rede)
fttx.escrever_pdf([fttx.pagina_do_diagrama(cena)], PASTA + "/gui_diagrama.pdf")
fttx.exportar_svg(cena, PASTA + "/gui_diagrama.svg")
fttx.exportar_relatorio_pdf(app.rede, cena, PASTA + "/gui_relatorio.pdf")
fttx.exportar_relatorio_csv(app.rede, PASTA + "/gui_portas.csv")
app.rede.salvar(PASTA + "/gui_rede.json")
larg = app.cena.largura * app.escala
alt = app.cena.altura * app.escala
app.canvas.postscript(file=PASTA + "/gui_diagrama.ps", colormode="color",
                      x=0, y=0, width=larg, height=alt)
checar(all(os.path.getsize(PASTA + "/" + n) > 1000 for n in
           ("gui_diagrama.pdf", "gui_diagrama.svg", "gui_relatorio.pdf",
            "gui_portas.csv", "gui_rede.json", "gui_diagrama.ps")),
       "gerou PDF, SVG, relatorio, CSV, JSON e PS")
bbox = [l for l in open(PASTA + "/gui_diagrama.ps").read().splitlines()
        if "BoundingBox" in l][0]
x0, y0, x1, y1 = [float(v) for v in bbox.split(":")[1].split()]
checar(abs((x1 - x0) / (y1 - y0) - larg / alt) < 0.05,
       "PS cobre o diagrama inteiro (proporcao bate)")

print("== rastreio pela interface ==")
chave = ("OLT-01", "OLT-01-PLACA-01", 5)
app.porta_selecionada = {"eq_id": chave[0], "modulo_id": chave[1], "porta_num": chave[2]}
checar(app._porta_para_rastrear() == chave, "pega a porta selecionada")
arv = fttx.rastrear_caminho(app.rede, chave, 5.0)
app._aplicar_destaque(fttx.fusoes_do_rastreio(arv))
app.update()
checar(len(app.destaque) == 5, "caminho destacado no diagrama")
app.acao_limpar_destaque()
app.update()
checar(len(app.destaque) == 0, "destaque limpo")

print("== recuperacao ==")
fttx.gravar_autosave(app.rede, "", {"cidade": {"id": "x-sp", "titulo": "X - SP"},
                                    "id": "perdido", "versao": "v1"})
app2 = App()
mb.askyesno = lambda *a, **k: True
_recuperar_original(app2)
app2.update()
checar(len(app2.rede.equipamentos) == len(app.rede.equipamentos)
       and (app2.documento or {}).get("id") == "perdido",
       "recupera o trabalho e lembra de qual diagrama do servidor era")
app2.destroy()
fttx.nix_ui.usar_janela(app)          # (so no teste existem duas janelas principais)
fttx.apagar_autosave()


print("== interface (B0.24/B0.25): sem menu nativo, cartoes, paleta, menu ... ==")
app.acao_exemplo()
app.update()
checar(str(app["menu"]) == "", "sem barra de menu nativa (a branca do Windows)")
checar(len(app.cartoes) == len(app.rede.equipamentos), "um cartao por equipamento")
app._clicar_cartao("OLT-01")
app.update()
checar(app._eq_selecionado().id == "OLT-01" and app.cartoes["OLT-01"].selecionado,
       "clicar no cartao seleciona o equipamento")
checar(app.painel_detalhe.winfo_ismapped() and len(app.arvore.get_children()) == 2,
       "painel de detalhe mostra os modulos da OLT")
ids_antes = {id(c) for c in app.cartoes.values()}
livres = [k for k in app.cena.portas if not app.rede.fusoes_na_porta(*k)]
app._clique_porta(livres[0])
app.update()
checar(app.lbl_dica.winfo_ismapped(), "dica flutuante aparece com a porta escolhida")
app._clique_porta(livres[1])
app.update()
checar({id(c) for c in app.cartoes.values()} == ids_antes,
       "nova fusao atualiza os cartoes sem recriar (sem piscar)")
checar(not app.lbl_dica.winfo_ismapped(), "dica some depois da fusao")
checar(app.lbl_alterado.cget("text") != "", "ponto de 'nao salvo' aceso")
app.acao_desfazer()
app.update()

app.abrir_paleta()
app.update()
checar(app.paleta is not None and app.paleta.winfo_ismapped(), "Ctrl+K abre a paleta")
checar(len(app._itens_paleta) == len(App.PALETA_INICIAL), "paleta vazia mostra sugestoes")
app.var_paleta.set("pend")
app.update()
checar(app._itens_paleta and app._itens_paleta[0][1] == "Pendencias e capacidade",
       "digitar filtra os comandos", app._itens_paleta[0][1] if app._itens_paleta else None)
app.var_paleta.set("excel")
app.update()
checar(any("Excel" in i[1] for i in app._itens_paleta), "acha comando por palavra extra")
app.var_paleta.set("cliente a")
app.update()
nomes = [i[1] for i in app._itens_paleta]
checar("Cliente A" in nomes and any(n.startswith("Rastrear a partir") for n in nomes),
       "paleta tambem busca na rede e oferece rastrear", nomes)
indice = nomes.index("Cliente A")
app._mover_paleta(indice - app._indice_paleta)
app._executar_paleta()
import time
for _ in range(10):
    time.sleep(0.01)
    app.update()
checar(app.paleta is None, "Enter fecha a paleta")
checar(app.porta_selecionada is not None, "e leva ate a porta do cliente")
app._limpar_selecao()
app.var_paleta = None
app.abrir_paleta("zzzz")
app.update()
checar(app._itens_paleta == [], "nada encontrado nao quebra")
app._tecla_esc()
app.update()
checar(app.paleta is None, "Esc fecha a paleta")
chamado = []
app.abrir_paleta("organizar")
app.update()
app._itens_paleta[0] = app._itens_paleta[0][:3] + (lambda: chamado.append(1),) + app._itens_paleta[0][4:]
app._executar_paleta(0)
for _ in range(10):
    time.sleep(0.01)
    app.update()
checar(chamado == [1], "Enter executa o comando escolhido")

app.menu_principal.abrir()
app.update()
checar(app.menu_principal.aberto() and len(app.menu_principal.linhas) >= 12,
       "menu ... abre com os comandos do arquivo")
app._tecla_esc()
checar(not app.menu_principal.aberto(), "Esc fecha o menu")
todos = app._comandos()
checar(all(callable(c[3]) for c in todos) and
       all(fttx.nix_ui.icone(c[0]) is not None for c in todos),
       "todo comando tem funcao e icone", len(todos))

print("== conexoes visiveis (B0.25) ==")
app.acao_exemplo()
app.update()
f = [f for f in app.rede.fusoes.values() if f.rotulo == "PON 4"][0]
app._acender_fusoes([f.id])
acesas = app.canvas.find_withtag("acesa")
checar(len(acesas) >= 5 and all(app.canvas.itemcget(i, "state") == "disabled" for i in acesas),
       "passar o mouse acende a fibra e as duas portas (sem roubar o mouse)", len(acesas))
checar("DIO-Centro-01" in app.status.cget("text") and "\u2194" in app.status.cget("text"),
       "rodape mostra de qual porta pra qual porta", app.status.cget("text")[:60])
app._apagar_fusoes()
checar(not app.canvas.find_withtag("acesa"), "tirar o mouse apaga o realce")
saidas = [p["ay"] for k, p in app.cena.portas.items()
          if k[0] == "DIO-01" and k[1] == "F" and app.rede.fusoes_na_porta(*k)]
saidas.sort()
checar(all(b - a >= fttx.ESPACO_MIN_CONEXAO - 0.01 for a, b in zip(saidas, saidas[1:])),
       "saidas das fibras no DIO com espaco entre si", len(saidas))

print("== arrastar e girar (B0.27) ==")
import types as _t
app.acao_exemplo()
app.update()
eq = app.rede.equipamentos["DIO-02"]
antes = (eq.pos_x, eq.pos_y)
cv = app.canvas
meio = app.cena.portas[("DIO-02", "F", 6)]       # um ponto no meio da caixa (fora da porta)
px = int((meio["x"] - 60 - app.cena.minx) * app.escala - cv.canvasx(0))
py = int((meio["y"] - app.cena.miny) * app.escala - cv.canvasy(0))
# eventos de verdade (como o mouse manda): o arraste tem que acompanhar o
# mouse o caminho todo, mesmo com o diagrama sendo redesenhado no meio
cv.event_generate("<Motion>", x=px, y=py)
app.update()
cv.event_generate("<ButtonPress-1>", x=px, y=py)
app.update()
for k in range(1, 21):
    cv.event_generate("<Motion>", x=px + k * 8, y=py + k * 5, state=0x100)
    time.sleep(0.02)
    app.update()
cv.event_generate("<ButtonRelease-1>", x=px + 160, y=py + 100, state=0x100)
app.update()
esperado = (round((antes[0] + 160 / app.escala) / 10) * 10.0,
            round((antes[1] + 100 / app.escala) / 10) * 10.0)
checar(abs(eq.pos_x - esperado[0]) <= 10 and abs(eq.pos_y - esperado[1]) <= 10
       and eq.pos_x % 10 == 0 and eq.pos_y % 10 == 0,
       "arrasta o equipamento junto com o mouse ate o fim e encaixa na grade",
       ((eq.pos_x, eq.pos_y), esperado))
checar(app._arraste_eq is None, "soltar o botao termina o arraste")
antes_eqs = {e.id: (e.pos_x, e.pos_y) for e in app.rede.equipamentos.values()}
porta = app.cena.portas[("DIO-02", "F", 10)]
qx = int((porta["x"] - app.cena.minx) * app.escala - cv.canvasx(0))
qy = int((porta["y"] - app.cena.miny) * app.escala - cv.canvasy(0))
cv.event_generate("<Motion>", x=qx, y=qy)
app.update()
cv.event_generate("<ButtonPress-1>", x=qx, y=qy)
cv.event_generate("<ButtonRelease-1>", x=qx, y=qy)
app.update()
checar(app.porta_selecionada is not None and
       {e.id: (e.pos_x, e.pos_y) for e in app.rede.equipamentos.values()} == antes_eqs,
       "clicar na porta seleciona a porta e nao arrasta nada")
app._limpar_selecao()
checar(app.alteracoes_pendentes and app._eq_selecionado().id == "DIO-02",
       "arrastar marca alteracao e seleciona o equipamento")
app.acao_desfazer()
app.update()
eq = app.rede.equipamentos["DIO-02"]
checar((eq.pos_x, eq.pos_y) == antes, "Ctrl+Z volta pra onde estava")
app._selecionar_equipamento("DIO-01")
app.acao_girar_dio()
app.update()
checar(app.rede.equipamentos["DIO-01"].orientacao == "horizontal", "girar DIO pela interface")
app.acao_desfazer()
app.update()

print("== fundir varias fibras com Shift (B0.31) ==")
app.acao_exemplo()
app.update()
antes = len(app.rede.fusoes)
app._clique_porta(("CABO-01", "A", 13))
app._clique_porta_shift(("CABO-01", "A", 16))
app.update()
checar(len(app.selecao_lote) == 4 and app.lbl_dica.winfo_ismapped(),
       "Shift+clique marca as fibras 13 a 16", len(app.selecao_lote))
fttx.perguntar_texto = lambda *a, **k: "Cliente #"
app._clique_porta(("DIO-02", "T", 1))
app.update()
novas = [f for f in app.rede.fusoes.values() if f.rotulo.startswith("Cliente ") and
         f.eq_a == "CABO-01"]
checar(len(app.rede.fusoes) == antes + 4 and
       sorted((f.porta_a, f.porta_b, f.rotulo) for f in novas) ==
       [(13, 1, "Cliente 1"), (14, 2, "Cliente 2"), (15, 3, "Cliente 3"), (16, 4, "Cliente 4")],
       "um clique no destino funde 13->1, 14->2, 15->3, 16->4 com rotulo numerado",
       sorted((f.porta_a, f.porta_b) for f in novas))
checar(app.selecao_lote == [] and app.porta_selecionada is None, "selecao limpa depois")
app.acao_desfazer()
app.update()
checar(len(app.rede.fusoes) == antes, "um Ctrl+Z desfaz o lote inteiro")
erros = []
mb.showerror = lambda *a, **k: erros.append(a)
app._clique_porta(("CABO-01", "A", 13))
app._clique_porta_shift(("CABO-01", "A", 24))
app._clique_porta(("DIO-02", "T", 6))            # so sobram 7 portas no DIO-02
app.update()
checar(erros and len(app.rede.fusoes) == antes, "falta porta no destino: avisa e nao cria nada",
       erros[0][1][:50] if erros else None)
app._limpar_selecao()
app._clique_porta(("CABO-01", "A", 1))
app._clique_porta_shift(("CABO-02", "A", 3))      # outro equipamento: recomeca
checar(app.selecao_lote == [] and app.porta_selecionada["eq_id"] == "CABO-02",
       "Shift em outro equipamento recomeca a selecao")
app._limpar_selecao()
mb.showerror = lambda *a, **k: None
fttx.perguntar_texto = lambda *a, **k: "TESTE"

print("== botao direito, inverter e potencia (B0.33) ==")
import types as _t2
app.acao_exemplo()
app.update()
ev3 = _t2.SimpleNamespace(x_root=300, y_root=300)
app._menu_equipamento(ev3, "DIO-01")
app.update()
nomes = [i[1] for i in app.menu_contexto.itens if i]
checar(app.menu_contexto.aberto() and "Inverter lado" in nomes and "Girar (vertical / horizontal)" in nomes,
       "botao direito no equipamento abre o menu", nomes[:4])
lado_antes = app.rede.equipamentos["DIO-01"].lado_efetivo()
[i for i in app.menu_contexto.itens if i and i[1] == "Inverter lado"][0][3]()
app.update()
checar(app.rede.equipamentos["DIO-01"].lado_efetivo() != lado_antes, "Inverter lado pelo menu")
app.menu_contexto.fechar()
app._tecla_atalho(app.acao_inverter_lado)(_t2.SimpleNamespace(widget=app.canvas))
checar(app.rede.equipamentos["DIO-01"].lado_efetivo() == lado_antes, "tecla I inverte de novo")
app._menu_porta(ev3, ("OLT-01", "OLT-01-PLACA-01", 1))
nomes = [i[1] for i in app.menu_contexto.itens if i]
checar(any(n.startswith("Potencia de saida") for n in nomes), "botao direito na porta da OLT oferece potencia")
app.menu_contexto.fechar()
fttx.perguntar_texto = lambda *a, **k: "+3,5"
app.acao_potencia_porta(("OLT-01", "OLT-01-PLACA-01", 1))
app.update()
checar(app.rede.potencia_da_porta("OLT-01", "OLT-01-PLACA-01", 1) == 3.5, "define a potencia digitando +3,5")
fttx.perguntar_texto = lambda *a, **k: "TESTE"
checar(app.cena.potencias and app.cena.potencias["fontes"], "diagrama recalcula a potencia")
app.acao_alternar_potencia()
checar(app.cena.potencias is None, "botao P desliga a camada de potencia")
app.acao_alternar_potencia()
checar(app.cena.potencias is not None, "e liga de novo")
app.acao_desfazer()
app.update()
checar(app.rede.potencia_da_porta("OLT-01", "OLT-01-PLACA-01", 1) is None, "Ctrl+Z desfaz a potencia")

print("== localizacao no mapa (B0.34) ==")
# mapa sem internet nos testes: todo tile vira um quadrado PNG gerado aqui
_png = fttx.tk.PhotoImage(master=app, width=256, height=256)
_png.put("#3a6b4a", to=(0, 0, 256, 256))
_bytes_png = _png.data(format="png")
_bytes_png = _bytes_png if isinstance(_bytes_png, bytes) else __import__("base64").b64decode(_bytes_png)
tiles_pedidos = []
fttx.mapa.baixar_tile = lambda f, z, x, y, pasta=None: (tiles_pedidos.append((f, z, x, y)), _bytes_png)[1]
fttx.mapa.gravar_ultima_vista = lambda *a, **k: None
abertos = []
webbrowser.open = lambda url, *a, **k: abertos.append(url)
checar("POP Centro" in app.botao_local.cget("text"), "topo mostra o local da rede de exemplo",
       app.botao_local.cget("text"))
_body = fttx.DialogLocal.body
dialogos = []
fttx.DialogLocal.body = lambda self, master: (dialogos.append(self), _body(self, master))[1]
resultado = {}


def mexer_no_dialogo():
    d = dialogos[-1]
    for _ in range(40):          # deixa as threads entregarem os tiles
        d.update()
        __import__("time").sleep(0.02)
    resultado["tiles"] = len(d.mapa._imagens)
    resultado["pino_inicial"] = d.mapa.marcador
    d.var_coord.set("https://www.google.com/maps/place/x/@-22.9,-43.2,17z/data=!3d-22.9068!4d-43.1729")
    d.update()
    resultado["pino_link"] = d.mapa.marcador
    resultado["dms"] = d.lbl_coord.cget("text")
    d.var_coord.set("isso nao e coordenada")
    d.update()
    resultado["botao_desligado"] = str(d.bt_maps.cget("state"))
    ev = __import__("types").SimpleNamespace(x=320, y=235, delta=0)
    d.mapa._press(ev)
    d.mapa._release(ev)
    d.update()
    resultado["coord_clique"] = d.var_coord.get()
    resultado["ponto_clique"] = d.mapa.marcador
    zoom = d.mapa.zoom
    d.mapa._roda(__import__("types").SimpleNamespace(x=100, y=100, delta=120))
    resultado["zoom"] = (zoom, d.mapa.zoom)
    d.var_fonte.set("satelite")
    d.mapa.trocar_fonte("satelite")
    d.update()
    d.bt_maps.invoke()
    d.var_tipo.set("CTO")
    d.e_nome.delete(0, "end")
    d.e_nome.insert(0, "CTO-Bairro-01")
    d.ok()


app.after(50, mexer_no_dialogo)
app.acao_local()
app.update()
checar(resultado.get("tiles", 0) > 0, "mapa desenha os tiles", resultado.get("tiles"))
checar(resultado.get("pino_inicial") == (-23.55052, -46.633308), "mapa abre no local salvo")
checar(resultado.get("pino_link") == (-22.9068, -43.1729), "colar link do Google Maps move o pino")
checar("S" in resultado.get("dms", "") and "W" in resultado.get("dms", ""), "mostra em graus/min/seg",
       resultado.get("dms"))
checar(resultado.get("botao_desligado") == "disabled", "coordenada invalida desliga o Google Maps")
checar(resultado.get("coord_clique") and fttx.mapa.ler_coordenada(resultado["coord_clique"])
       == resultado.get("ponto_clique"), "clique no mapa marca o ponto", resultado.get("coord_clique"))
checar(resultado.get("zoom", (0, 0))[1] == resultado.get("zoom", (0, 0))[0] + 1, "roda do mouse da zoom")
checar(any(t[0] == "satelite" for t in tiles_pedidos), "troca pra satelite pede tiles de satelite")
checar(abertos and "google.com/maps" in abertos[-1], "botao abre o Google Maps no navegador")
checar(app.rede.local["tipo"] == "CTO" and app.rede.local["nome"] == "CTO-Bairro-01"
       and app.rede.local["lat"] == resultado.get("ponto_clique", (None,))[0],
       "OK grava o local na rede", app.rede.local)
checar("CTO" in app.botao_local.cget("text") and app.alteracoes_pendentes,
       "topo atualiza e marca alteracao", app.botao_local.cget("text"))
app.acao_google_earth()
checar(abertos[-1].startswith("https://earth.google.com/web/@"), "abre no Google Earth", abertos[-1])
app.acao_desfazer()
app.update()
checar(app.rede.local["tipo"] == "POP", "Ctrl+Z desfaz a localizacao")
nomes = [r[1] for r in app.resultados_paleta("google")]
checar("Abrir no Google Maps" in nomes and "Abrir no Google Earth" in nomes, "paleta acha 'google'", nomes)
checar(any("Localizacao" in r[1] for r in app.resultados_paleta("cto")), "paleta acha o local por 'cto'")
app.rede = fttx.Rede()
app.atualizar_tudo()
abertos.clear()
fttx.mb_askyesno_original = mb.askyesno
mb.askyesno = lambda *a, **k: False
app.acao_google_maps()
mb.askyesno = lambda *a, **k: True
checar(not abertos, "sem coordenada nao abre o navegador")
checar(app.botao_local.cget("text") == "Definir localizacao", "rede nova pede pra definir o local")

print("== mapa mais rapido (B0.35) ==")
res2 = {}


def dialogo_rapido():
    d = dialogos[-1]
    res2["radios"] = [w.cget("text") for w in d.quadro_fontes.winfo_children()]
    for _ in range(30):
        d.update()
        __import__("time").sleep(0.02)
    d.mapa._roda(__import__("types").SimpleNamespace(x=340, y=250, delta=120))
    chave = next(k for k in list(d.mapa._imagens) if k[1] == d.mapa.zoom - 1)
    filho = (chave[0], chave[1] + 1, chave[2] * 2, chave[3] * 2)
    d.mapa._imagens.pop(filho, None)
    previa = d.mapa._previa(filho)
    res2["previa"] = previa is not None and previa.width() == 256
    d.var_fonte.set("satelite")
    d._escolher_fonte()
    res2["config_fonte"] = fttx.mapa.ler_config().get("fonte")
    d.cancel()


app.after(50, dialogo_rapido)
app.acao_local()
app.update()
checar(res2.get("radios") == ["Mapa", "Satelite"], "opcoes do mapa: Mapa e Satelite", res2.get("radios"))
checar(res2.get("previa"), "mostra a previa ampliada enquanto o tile carrega")
checar(res2.get("config_fonte") == "satelite", "lembra a escolha de fonte")
checar(not any("Chave do Google" in r[1] for r in app.resultados_paleta("chave")),
       "paleta sem chave do Google")

print("== tela inicial e servidor (B0.39) ==")
import waspfiber_nuvem as nuvem
checar(inicio_ao_abrir and login_ao_abrir, "programa abre na tela de login do servidor")
checar(not app.tela_inicio.visivel(), "abrir um diagrama sai da tela inicial")
app.mostrar_inicio()
app.update()
tela = app.tela_inicio
checar(tela.visivel() and tela.login.winfo_ismapped(), "sem login: mostra o login")
form = tela.form


def esperar_empresas(limite=5.0):
    fim = __import__("time").time() + limite
    while __import__("time").time() < fim:
        app.update()
        if form.empresas is not None:
            return True
        __import__("time").sleep(0.03)
    return False


checar(form.modo == "entrar" and set(form.campos) == {"empresa", "email", "senha"}
       and "Entrar no WaspFiber" in form.lbl_titulo.cget("text"),
       "tela 'Entrar no WaspFiber': empresa, e-mail e senha (sem servidor)")
checar(esperar_empresas(), "carrega a lista de empresas do servidor")
nomes = list(form.campos["empresa"].cget("values"))
checar(nomes == ["Beta Fibra", "Junior Telecom"], "lista so as empresas com dominio", nomes)
checar(form.empresa is None and form.var_empresa.get() == form.ESCOLHA,
       "mais de uma empresa: pede pra escolher")
form.var_empresa.set("Junior Telecom")
form._escolheu_empresa()
app.update()
checar(form.var_dominio.get() == "@junior.com.br" and form.lbl_dominio.winfo_ismapped(),
       "escolheu a empresa: o e-mail ja vem com @junior.com.br", form.var_dominio.get())
form.var_empresa.set("Beta Fibra")
form._escolheu_empresa()
app.update()
checar(form.cb_dominio.winfo_ismapped() and list(form.cb_dominio.cget("values")) ==
       ["@beta.net", "@betafibra.com.br"], "empresa com 2 dominios: escolhe o dominio na lista")
form.preencher("tulio@junior.com.br")
checar(form.empresa["nome"] == "Junior Telecom" and form.campos["email"].get() == "tulio"
       and form.email_completo() == "tulio@junior.com.br",
       "colar o e-mail inteiro escolhe a empresa e deixa so a parte antes do @")
form.campos["email"].delete(0, "end")
form.enviar()
checar("antes do @" in form.msg.cget("text"), "sem e-mail: avisa", form.msg.cget("text"))
form.campos["email"].insert(0, "tulio")
form.campos["senha"].insert(0, "errada")
form.enviar()
app.update()
checar(app.conexao is None and "incorretos" in form.msg.cget("text"),
       "senha errada: mensagem no login", form.msg.cget("text"))
form.campos["senha"].insert(0, "senha-teste-123")
form.enviar()
app.update()
checar(app.conexao is not None and not tela.login.winfo_ismapped() and form.campos["senha"].get() == "",
       "login certo: entra e limpa a senha")
checar(nuvem.ler_sessao().get("email") == "tulio@junior.com.br", "lembra o e-mail pro proximo login")
checar("Junior Telecom" in tela.lbl_empresa.cget("text"), "mostra a empresa e o usuario",
       tela.lbl_empresa.cget("text"))
checar(tela.aviso.winfo_ismapped() and "cidade" in tela.aviso_titulo.cget("text"),
       "empresa sem cidades: convite pra cadastrar")
app.abrir_paleta()
checar(app.paleta is None or not app.paleta.winfo_exists(), "Ctrl+K nao abre por cima do inicio")


class CidadeFalsa:
    def __init__(self, parent):
        self.resultado = ("Santos", "SP")


_orig_cidade = fttx.DialogNovaCidade
fttx.DialogNovaCidade = CidadeFalsa
tela.nova_cidade()
fttx.DialogNovaCidade = _orig_cidade
app.update()
checar(list(tela.linhas_cidade) == ["santos-sp"] and tela.cidade["titulo"] == "Santos - SP",
       "nova cidade criada no servidor e escolhida")


class DiagramaFalso:
    def __init__(self, parent, cidade):
        self.resultado = ("CTO", "CTO Rua A 01", False)


_orig_diag = fttx.DialogNovoDiagrama
fttx.DialogNovoDiagrama = DiagramaFalso
did = app.novo_diagrama(tela.cidade)
fttx.DialogNovoDiagrama = _orig_diag
app.update()
checar(did == "cto-rua-a-01" and not tela.visivel() and app.documento["id"] == did,
       "novo diagrama criado no servidor e aberto", app.documento)
checar(not os.listdir(os.environ["APPDATA"] + "/WaspFiber") or
       not any(n.endswith(".wasp.json") for n in os.listdir(os.environ["APPDATA"] + "/WaspFiber")),
       "nada de .wasp.json salvo no computador")
checar("Santos - SP" in app.lbl_arquivo.cget("text") and "CTO Rua A 01" in app.lbl_arquivo.cget("text"),
       "topo mostra cidade > diagrama", app.lbl_arquivo.cget("text"))
app.rede.add_equipamento("DIO X", fttx.TIPO_DIO, 12)
app._marcar_alterado()
checar(app.acao_salvar() and not app.alteracoes_pendentes, "salvar grava no servidor")
outra = nuvem.Conexao.entrar_email("ana@junior.com.br", "senha-teste-456")
nuvem.gravar_sessao(dict(app.conexao.info, url=app.conexao.url, token=app.conexao.token))
checar(len(outra.abrir("santos-sp", did)["conteudo"]["equipamentos"]) == 1,
       "outra pessoa ve o que foi salvo")
dados_ana = outra.abrir("santos-sp", did)
from waspfiber import Rede
r_ana = Rede.from_dict(dados_ana["conteudo"])
r_ana.add_equipamento("DIO da Ana", fttx.TIPO_DIO, 12)
outra.salvar("santos-sp", did, r_ana.to_dict(), dados_ana["versao"])
app.rede.add_equipamento("DIO Y", fttx.TIPO_DIO, 12)
app._marcar_alterado()
perguntas = []
mb.askyesnocancel = lambda *a, **k: (perguntas.append(a), True)[1]   # salvar por cima
checar(app.acao_salvar() and perguntas and "Ana" in perguntas[0][1],
       "conflito: avisa que a Ana salvou e deixa salvar por cima", perguntas[:1])
mb.askyesnocancel = lambda *a, **k: False

print("== sem conexao: guarda e envia depois ==")
url_boa = app.conexao.url
app.conexao.url = "http://127.0.0.1:9"
app.rede.add_equipamento("DIO offline", fttx.TIPO_DIO, 12)
app._marcar_alterado()
checar(app.acao_salvar() and not app.alteracoes_pendentes and len(nuvem.pendentes()) == 1,
       "servidor fora: guarda na fila e nao perde nada")
app.update()
checar("aguardando envio" in app.lbl_alterado.cget("text"), "topo avisa 'aguardando envio'",
       app.lbl_alterado.cget("text"))
app.conexao.url = url_boa
for _ in range(200):
    if not app._sincronizando and nuvem.pendentes():
        app._sincronizar()          # (a automatica pode estar rodando: espera e tenta)
    app.update()
    if not app._sincronizando and not nuvem.pendentes():
        break
    __import__("time").sleep(0.05)
checar(nuvem.pendentes() == [] and
       len(outra.abrir("santos-sp", did)["conteudo"]["equipamentos"]) == 3,
       "servidor voltou: envia sozinho e apaga a copia temporaria",
       (len(nuvem.pendentes()), len(outra.abrir("santos-sp", did)["conteudo"]["equipamentos"]),
        app._sincronizando))
app.rede.add_equipamento("DIO depois", fttx.TIPO_DIO, 12)
app._marcar_alterado()
perguntas.clear()
mb.askyesnocancel = lambda *a, **k: (perguntas.append(a), None)[1]
checar(app.acao_salvar() and not perguntas, "depois do envio, salvar de novo nao da conflito")
mb.askyesnocancel = lambda *a, **k: False

app.mostrar_inicio()
app.update()
linhas = tela.linhas_diagrama
checar(list(linhas) == [did] and "4 equipamentos" in linhas[did].lbl_detalhe.cget("text"),
       "volta pro inicio e a lista mostra o que esta no servidor", linhas[did].lbl_detalhe.cget("text"))
checar("por Tulio" in linhas[did].lbl_detalhe.cget("text"), "lista mostra quem alterou",
       linhas[did].lbl_detalhe.cget("text"))
tela._escolher_diagrama({"id": did})
tela.abrir_escolhido()
app.update()
checar(not tela.visivel() and len(app.rede.equipamentos) == 4, "abre o diagrama do servidor")
mb.askyesnocancel = lambda *a, **k: None
app.rede.add_equipamento("DIO Z", fttx.TIPO_DIO, 12)
app._marcar_alterado()
app.mostrar_inicio()
checar(not tela.visivel(), "alteracao nao salva: cancelar fica no editor")
mb.askyesnocancel = lambda *a, **k: False
app.mostrar_inicio()
checar(tela.visivel(), "descartar volta pro inicio")

print("== mapa da cidade (B0.44) ==")
checar(tela.mapa_cidade.marcadores == [] and "Nenhum equipamento" in tela.mapa_cidade.aviso,
       "cidade sem coordenadas: mapa avisa", tela.mapa_cidade.aviso)
from waspfiber import Rede as _Rede
for _tipo, _nome, _lat, _lon in (("POP", "POP Centro", -23.9350, -46.3280),
                                 ("CEO", "CEO-012", -23.9600, -46.3300)):
    _r = _Rede()
    _r.definir_local({"tipo": _tipo, "nome": _nome, "lat": _lat, "lon": _lon})
    outra.criar_diagrama("santos-sp", _nome, _r.to_dict())
tela.listar_diagramas()
app.update()
_ms = tela.mapa_cidade.marcadores
checar(sorted(m["tipo"] for m in _ms) == ["CEO", "POP"] and not tela.mapa_cidade.aviso,
       "mapa da cidade mostra os equipamentos com coordenada", [m["titulo"] for m in _ms])
_w, _h = tela.mapa_cidade._tamanho()
_xs = [tela.mapa_cidade.tela_do_ponto(m["lat"], m["lon"]) for m in _ms]
checar(all(0 < x < _w and 0 < y < _h for x, y in _xs), "o mapa se enquadra nos equipamentos", _xs)
_pop = next(m for m in _ms if m["tipo"] == "POP")
_x, _y = tela.mapa_cidade.tela_do_ponto(_pop["lat"], _pop["lon"])
checar(tela.mapa_cidade.marcador_em(_x, _y - 22)["id"] == _pop["id"], "achar o pino debaixo do mouse")
_ev = __import__("types").SimpleNamespace(x=_x, y=_y - 22, delta=0)
tela.mapa_cidade._press(_ev)
tela.mapa_cidade._release(_ev)
app.update()
checar(tela.diagrama_escolhido == _pop["id"] and tela.linhas_diagrama[_pop["id"]].selecionado,
       "clicar no pino escolhe o equipamento na lista")
_ceo = next(i for i in tela.itens if i["tipo"] == "CEO")
tela._escolher_diagrama(_ceo, no_mapa=True)
checar(tela.mapa_cidade.escolhido == _ceo["id"], "clicar na lista destaca o pino no mapa")
checar(tela.linhas_diagrama[_ceo["id"]].cor_icone == "ceo", "icone do tipo na cor do tipo (CEO)")
abriu = []
_orig_abrir = app.abrir_diagrama
app.abrir_diagrama = lambda c, d: abriu.append(d)
tela.mapa_cidade._duplo(_ev)
app.abrir_diagrama = _orig_abrir
checar(abriu == [_pop["id"]], "duplo clique no pino abre o diagrama")
_f = tela.mapa_cidade.fonte
tela._trocar_fonte_mapa()
checar(tela.mapa_cidade.fonte != _f and tela.bt_fonte_mapa.cget("text") in ("Mapa", "Satelite"),
       "botao troca mapa / satelite")
tela._trocar_fonte_mapa()
checar(fttx.mapa.TIPOS_LOCAL[1] == ("CEO", "CEO"), "tipo 'CEO' (sem 'Caixa de emenda')")
print("== criar conta e pedidos de acesso (B0.41) ==")
checar(tela.bt_pedidos.winfo_ismapped() and tela.bt_pedidos.cget("text") == "Pedidos de acesso",
       "administrador ve o botao de pedidos de acesso")
tela.sair()
app.update()
checar(app.conexao is None and tela.login.winfo_ismapped() and "token" not in nuvem.ler_sessao(),
       "sair volta pro login e esquece a sessao")
app.update()
checar(form.empresa and form.empresa["nome"] == "Junior Telecom" and form.campos["email"].get() == "tulio",
       "proximo login: empresa e e-mail ja vem preenchidos")
form.trocar_modo()
checar(form.modo == "criar" and set(form.campos) == {"empresa", "nome", "email", "senha", "senha2"}
       and form.var_dominio.get() == "@junior.com.br",
       "criar conta: empresa, nome, e-mail (com o dominio) e senha 2x")
for k, v in (("nome", "Bruno"), ("email", "bruno"), ("senha", "senha-bruno-1"),
             ("senha2", "outra-coisa")):
    form.campos[k].delete(0, "end")
    form.campos[k].insert(0, v)
form.enviar()
checar("nao conferem" in form.msg.cget("text"), "senhas diferentes: avisa")
form.campos["senha2"].insert(0, "senha-bruno-1")
form.enviar()
app.update()
checar(form.modo == "entrar" and "Pedido enviado" in form.msg.cget("text")
       and "Junior Telecom" in form.msg.cget("text"), "pedido enviado e volta pro Entrar",
       form.msg.cget("text"))
form.campos["email"].delete(0, "end")
form.campos["email"].insert(0, "bruno")
form.campos["senha"].insert(0, "senha-bruno-1")
form.enviar()
checar(app.conexao is None and "aguarda a aprovacao" in form.msg.cget("text"),
       "conta pendente nao entra ate aprovar", form.msg.cget("text"))
form.campos["senha"].insert(0, "senha-teste-123")
form.campos["email"].delete(0, "end")
form.campos["email"].insert(0, "tulio")
form.enviar()
app.update()
checar(tela.bt_pedidos.cget("text") == "Pedidos de acesso (1)", "admin ve 1 pedido aguardando",
       tela.bt_pedidos.cget("text"))
janela = fttx.DialogPedidos(app)
app.update()
janela.decidir("bruno@junior.com.br", True)
app.update()
janela.destroy()
checar(tela.bt_pedidos.cget("text") == "Pedidos de acesso", "aprovado: some da lista")
checar(nuvem.Conexao.entrar_email("bruno@junior.com.br", "senha-bruno-1").info["nome"] == "Bruno",
       "depois de aprovado, entra")
nuvem.gravar_sessao(dict(app.conexao.info, url=app.conexao.url, token=app.conexao.token))
tela.sair()
app.update()
app.acao_exemplo()
app.update()

print("== satelite ate o zoom 18 (B0.43) ==")
_t = fttx.tk.Toplevel(app)
_m = fttx.mapa.MapaWidget(_t, fttx.TEMA, fonte="satelite", centro=(-7.23, -35.88), zoom=19,
                          baixador=lambda f, z, x, y: (_ for _ in ()).throw(
                              fttx.mapa.ErroMapa("sem imagem neste zoom (500)", sem_imagem=True)))
_m.pack()
checar(_m.zoom == 18, "satelite abre no maximo no zoom 18", _m.zoom)
_m._roda(__import__("types").SimpleNamespace(x=100, y=100, delta=120))
checar(_m.zoom == 18, "roda do mouse nao passa do 18 no satelite")
for _ in range(30):
    _t.update()
    __import__("time").sleep(0.02)
checar(_m._falhas and _m.erro_rede is None, "falta de foto nao vira aviso de 'sem conexao'")
_m.trocar_fonte("mapa")
_m.aplicar_zoom(+1)
checar(_m.zoom == 19, "no mapa de ruas da pra ir ate o 19")
_m.trocar_fonte("satelite")
checar(_m.zoom == 18, "voltando pro satelite, o zoom desce pro 18")
_t.destroy()

print("== rede vazia ==")
app.rede = fttx.Rede()
app.atualizar_tudo(centralizar=True)
app.update()
checar(app.vazio.winfo_ismapped() and not app.painel_detalhe.winfo_ismapped(),
       "rede vazia mostra o convite pra comecar")

app.acao_exemplo()
app.update()
app.update_idletasks()
os.system("import -window root %s/gui_b024.png 2>/dev/null" % PASTA)
app.destroy()
srv.shutdown()

print()
if FALHAS:
    print("!! %d FALHA(S): %s" % (len(FALHAS), "; ".join(FALHAS)))
    raise SystemExit(1)
print("TODOS OS TESTES DE INTERFACE PASSARAM")
