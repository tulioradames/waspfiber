"""Testa a interface de verdade num display virtual: cliques, arraste, zoom,
desfazer, busca, lote, duplicar, organizar, pendencias e exportacoes.
Rodar:  xvfb-run -a python teste_gui.py"""
import os
import types
import tkinter.messagebox as mb
import tkinter.simpledialog as sd

import waspfiber as fttx
from waspfiber import App

PASTA = __import__("tempfile").gettempdir()
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

app = App()
app.update()
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
app.caminho_atual = PASTA + "/gui_rede.json"
app.acao_salvar()
app.update()
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
fttx.gravar_autosave(app.rede, "/tmp/perdido.json")
app2 = App()
mb.askyesno = lambda *a, **k: True
_recuperar_original(app2)
app2.update()
checar(len(app2.rede.equipamentos) == len(app.rede.equipamentos)
       and app2.caminho_atual == "/tmp/perdido.json",
       "recupera o trabalho e lembra o arquivo")
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

print()
if FALHAS:
    print("!! %d FALHA(S): %s" % (len(FALHAS), "; ".join(FALHAS)))
    raise SystemExit(1)
print("TODOS OS TESTES DE INTERFACE PASSARAM")
