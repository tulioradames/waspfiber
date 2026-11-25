"""Testa modelo, rastreio, busca, lote, layout, pendencias e exportacoes
sem abrir janela nenhuma.  Rodar:  python teste_core.py"""
import os
import time
from waspfiber import *

FALHAS = []


def checar(condicao, descricao, detalhe=""):
    print("  %s %s%s" % ("[ok]  " if condicao else "[FALHOU]", descricao,
                         ("  -> " + str(detalhe)) if detalhe else ""))
    if not condicao:
        FALHAS.append(descricao)


print("== modelo ==")
r = rede_exemplo()
checar(len(r.equipamentos) == 7 and len(r.fusoes) == 25, "rede de exemplo",
       "%d eqs, %d fusoes" % (len(r.equipamentos), len(r.fusoes)))
cena = montar_cena(r)
checar(len(cena.portas) == len(r.todas_as_portas()), "cena com todas as portas",
       len(cena.portas))

print("== validacoes ==")


def bloqueia(fn, descricao):
    try:
        fn()
        checar(False, descricao + " (deixou passar!)")
    except ValueError as e:
        checar(True, descricao, str(e)[:52])


bloqueia(lambda: r.criar_fusao("DIO-01", None, 3, "DIO-02", None, 4), "porta de DIO ja usada")
bloqueia(lambda: r.criar_fusao("DIO-01", None, 2, "DIO-01", None, 2), "porta nela mesma")
bloqueia(lambda: r.definir_tipo_porta("OLT-01", "OLT-01-PLACA-01", 3, DUPLEX), "duplex em GPON")
bloqueia(lambda: r.editar_equipamento("DIO-01", novo_num_portas=2), "reduzir DIO ocupado")
bloqueia(lambda: r.editar_modulo("SW-01", "SW-01-GRP-01", novo_num_portas=1), "reduzir grupamento")
bloqueia(lambda: r.editar_equipamento("DIO-01", novo_id="DIO-02"), "ID duplicado")

print("== rastreio ==")
a = rastrear_caminho(r, ("OLT-01", "OLT-01-PLACA-01", 5), 5.0)
pontas = pontas_finais(a)
checar(len(pontas) == 8, "da OLT o 1x8 abre em 8 pontas", len(pontas))
# cordao 0,1 + conector do DIO 0,5 + 3 fusoes 0,3 + splitter 10,5 = 11,4
checar(abs(max(p["perda_acum"] for p in pontas) - 11.40) < 0.01,
       "pior perda 11,40 dB (com o conector do DIO)",
       max(p["perda_acum"] for p in pontas))
checar(len(fusoes_do_rastreio(a)) == 5, "5 fusoes no caminho destacado",
       len(fusoes_do_rastreio(a)))
b = rastrear_caminho(r, ("CABO-02", "A", 1), None)
pb = pontas_finais(b)
checar(len(pb) == 1 and "OLT" in pb[0]["nome"],
       "do cliente (ponta do C2) sobe ate a OLT sem espalhar", pb[0]["nome"])
texto = "\n".join(rastreio_em_texto(b))
checar("atravessa o DIO" in texto and "pelo cabo" in texto,
       "o caminho passa pelo cabo e atravessa o DIO")
d = rastrear_caminho(r, ("OLT-01", "OLT-01-PLACA-02", 2), 3.0)
checar(len(d["filhos"]) == 2, "porta duplex abre em TX e RX")
loop = rastrear_caminho(r, ("SW-01", "SW-01-GRP-01", 2), 5.0)
checar(len(pontas_finais(loop)) == 1, "loop interno nao trava o rastreio")
checar((classificar_potencia(2.0), classificar_potencia(-26.0),
        classificar_potencia(-30.0)) == ("ok", "alerta", "critico"), "faixas de potencia")

print("== busca (novo) ==")
checar(len(buscar(r, "cliente a")) == 1, "acha o cliente pelo rotulo da fusao")
checar(len(buscar(r, "CLIENTE A")) == 1, "busca sem diferenciar maiuscula")
checar(any("DIO-Centro" in x["titulo"] for x in buscar(r, "centro")),
       "acha equipamento por parte do nome")
checar(any(x["tipo"] == "modulo" for x in buscar(r, "splitter rua")), "acha modulo")
porta15 = [x["chave"] for x in buscar(r, "dio-centro-01 15") if x["tipo"] == "porta"]
checar(sorted(porta15) == [("DIO-01", "F", 15), ("DIO-01", "T", 15)],
       "acha porta por 'equipamento numero' (os dois lados do DIO)", porta15)
olt0 = [x["chave"] for x in buscar(r, "olt-central-01 0") if x["tipo"] == "porta"]
checar(("OLT-01", "OLT-01-PLACA-01", 1) in olt0, "OLT: 'porta 0' acha a primeira porta", olt0)
checar(buscar(r, "") == [], "busca vazia nao devolve nada")
checar(buscar(r, "zzzz") == [], "termo inexistente nao devolve nada")
r_acento = Rede()
r_acento.add_equipamento("CTO Jardim Paulista", TIPO_DIO, 8)
checar(len(buscar(r_acento, "jardim")) == 1, "busca ignora acento/caixa")

print("== duplicar e criar em lote (novo) ==")
antes = len(r.equipamentos)
copia = r.duplicar_equipamento("OLT-01")
checar(copia.nome == "OLT-Central-02", "copia recebe o proximo numero", copia.nome)
checar(len(copia.modulos) == 2, "copia leva os modulos junto")
checar(all(not r.fusoes_na_porta(*c) for c in r.todas_as_portas(copia)),
       "copia nasce sem fusao nenhuma")
checar(copia.total_portas() == r.equipamentos["OLT-01"].total_portas(),
       "copia com as mesmas portas")
lote = r.criar_em_lote("DIO-##", TIPO_DIO, 5, 1, 24)
checar([e.nome for e in lote] == ["DIO-01", "DIO-02", "DIO-03", "DIO-04", "DIO-05"],
       "lote numerado com ##", [e.nome for e in lote][:3])
lote2 = r.criar_em_lote("CTO Bairro", TIPO_ACOMODADOR, 2, 10, 0, "1x8", 2)
checar([e.nome for e in lote2] == ["CTO Bairro 10", "CTO Bairro 11"],
       "sem ## o numero vai no fim", [e.nome for e in lote2])
checar(all(len(e.modulos) == 2 for e in lote2), "lote ja vem com os modulos pedidos")
checar(len(r.equipamentos) == antes + 1 + 5 + 2, "total de equipamentos bate")
try:
    r.criar_em_lote("X", TIPO_DIO, 500)
    checar(False, "limite de 200 por lote (deixou passar!)")
except ValueError as e:
    checar(True, "limite de 200 por lote", str(e)[:40])

print("== organizar layout (novo) ==")
for eq in r.equipamentos.values():          # bagunca tudo de proposito
    eq.pos_x, eq.pos_y = 0.0, 0.0
r.organizar_layout()
caixas = list(r.equipamentos.values())
sobrepostas = 0
for i, p in enumerate(caixas):
    for q in caixas[i + 1:]:
        if p.pos_x == q.pos_x and \
           q.pos_y < p.pos_y + layout_equipamento(p)["altura"] and \
           p.pos_y < q.pos_y + layout_equipamento(q)["altura"]:
            sobrepostas += 1
checar(sobrepostas == 0, "nenhuma caixa sobreposta depois de organizar")
colunas = sorted(set(e.pos_x for e in caixas))
checar(len(colunas) == 5, "cinco colunas (cabos de cliente | CTO | cabos | DIO | ativos)", colunas)
x_de = lambda cond: {e.pos_x for e in caixas if cond(e)}
checar(max(x_de(lambda e: e.tipo == TIPO_ACOMODADOR)) < min(x_de(lambda e: e.is_dio()))
       < min(x_de(lambda e: e.tipo in TIPOS_ATIVOS)),
       "ordem do campo pra central: CTO, DIO, ativos")

print("== equipamentos reais: DIO com dois lados, cabo, OLT a partir de 0 (B0.25) ==")
x = Rede()
dio = x.add_equipamento("DIO X", TIPO_DIO, 48)
cabo = x.add_equipamento("Cabo X", TIPO_CABO, 36, fibras_por_tubo=12)
olt = x.add_equipamento("OLT X", "OLT")
placa = olt.add_placa("GPON-16")
checar(sorted(dio.modulos) == ["F", "T"] and dio.modulos["T"].num_portas == 48,
       "DIO nasce com traseira e frente de 48 portas")
x.criar_fusao(dio.id, "T", 1, cabo.id, "B", 1)
x.criar_fusao(dio.id, "F", 1, olt.id, placa.id, 1)
checar(x.porta_status(dio.id, "T", 1) == "completa" and x.porta_status(dio.id, "F", 1) == "completa",
       "a mesma porta aceita fusao atras e cordao na frente")
bloqueia(lambda: x.criar_fusao(dio.id, "T", 1, cabo.id, "B", 2), "traseira ja fundida")
checar(x.ocupacao(dio) == (1, 48), "ocupacao do DIO conta por posicao", x.ocupacao(dio))
checar(cor_fibra(1) == ("verde", "#2e9e44") and cor_fibra(12)[0] == "aqua"
       and cor_fibra(13)[0] == "verde", "cores ABNT recomecam a cada tubo")
checar(tubo_da_fibra(25)[:2] == (3, "branco"), "fibra 25 fica no tubo 3 (branco)")
checar(x.rotulo_porta(olt.id, placa.id, 1) == "0" and x.rotulo_porta(olt.id, placa.id, 16) == "15",
       "OLT numerada de 0 a 15")
checar("vermelho" in x.nome_porta(cabo.id, "A", 5) and "ponta A" in x.nome_porta(cabo.id, "A", 5),
       "fibra do cabo tem nome com a cor e a ponta", x.nome_porta(cabo.id, "A", 5))
bloqueia(lambda: x.remover_modulo(dio.id, "T"), "lado do DIO nao pode ser removido")
bloqueia(lambda: x.editar_equipamento(dio.id, novo_num_portas=0), "DIO sem porta")
x.editar_equipamento(dio.id, novo_num_portas=24)
checar(dio.modulos["F"].num_portas == 24 and x.porta_status(dio.id, "F", 1) == "completa",
       "reduzir o DIO refaz os lados e mantem as fusoes")
checar(dio.orientacao == "vertical", "DIO nasce em pe (vertical)")
checar(x.girar_dio(dio.id) == "horizontal", "girar o DIO deita ele")
info = layout_equipamento(dio)
checar(info["largura"] > 600 and 140 < info["altura"] < 170, "DIO 24 desenhado como painel 1U",
       (info["largura"], info["altura"]))
c = montar_cena(x)
checar((dio.id, "T", 1) in c.portas and (cabo.id, "B", 36) in c.portas,
       "cena tem os dois lados do DIO e as duas pontas do cabo")
checar(c.portas[(dio.id, "T", 1)]["ax"] < c.portas[(dio.id, "F", 1)]["ax"],
       "traseira a esquerda, frente a direita")
cores_linhas = {it["cor"] for it in c.itens if it["t"] == "linha" and
                any(tag.startswith("fusao:") for tag in it["tags"])}
checar("#2e9e44" in cores_linhas and TEMA["cordao"] in cores_linhas,
       "fibra do cabo na cor ABNT e cordao amarelo", cores_linhas)
antiga = {"versao": "B0.24", "equipamentos": [
    {"id": "D1", "nome": "DIO velho", "tipo": "DIO", "num_portas": 12, "pos_x": 0, "pos_y": 0},
    {"id": "D2", "nome": "DIO velho 2", "tipo": "DIO", "num_portas": 12, "pos_x": 0, "pos_y": 0}],
    "fusoes": [{"id": "FUS-0001", "eq_a": "D1", "modulo_a": None, "porta_a": 3,
                "eq_b": "D2", "modulo_b": None, "porta_b": 4, "rotulo": "x"}]}
velha = Rede.from_dict(antiga)
checar(velha.fusoes_na_porta("D1", "F", 3) and velha.fusoes_na_porta("D2", "F", 4),
       "rede antiga abre com as fusoes do DIO na frente")
checar(velha.equipamentos["D1"].pos_y != velha.equipamentos["D2"].pos_y,
       "rede antiga e reorganizada (caixas mudaram de tamanho)")
x.girar_dio(dio.id)
dio.pos_x, dio.pos_y = 400.0, 0.0
cabo.pos_x, cabo.pos_y = 0.0, 0.0
c = montar_cena(x)
checar(abs(c.portas[(dio.id, "T", 1)]["ay"] - c.portas[(cabo.id, "B", 1)]["ay"]) < 0.01 and
       abs(c.portas[(dio.id, "T", 13)]["ay"] - c.portas[(cabo.id, "B", 13)]["ay"]) < 0.01,
       "DIO vertical: a porta N fica na altura da fibra N do cabo (linha reta)")
checar(c.portas[(dio.id, "T", 1)]["ax"] < c.portas[(dio.id, "F", 1)]["ax"],
       "DIO vertical: traseira a esquerda, frente a direita")
ordem = [it.get("tags", ()) for it in c.itens]
i_linha = next(i for i, tg in enumerate(ordem) if any(t.startswith("fusao:") for t in tg))
i_caixa = next(i for i, tg in enumerate(ordem) if any(t.startswith("eq:") for t in tg))
checar(i_linha < i_caixa, "as fibras passam por baixo das caixas")
checar(olt.orientacao == "vertical" and orientacao_padrao("SWITCH") == "horizontal",
       "OLT nasce em pe; switch/RB deitados")
olt.pos_x, olt.pos_y = 800.0, 0.0
c = montar_cena(x)
checar(abs(c.portas[(olt.id, placa.id, 1)]["ay"] - c.portas[(dio.id, "F", 1)]["ay"]) < 0.01,
       "OLT em pe: a porta 0 da placa fica na altura da porta 1 do DIO")
checar(layout_equipamento(olt)["altura"] > 16 * ALT_FIBRA, "placa em pe: uma porta por linha")
sw = x.add_equipamento("SW X", "SWITCH")
sw.add_grupamento("SFP", 8)
checar(x.girar_dio(sw.id) == "vertical", "switch tambem gira")
c = montar_cena(x)
checar(all((sw.id, m, n) in c.portas for m in sw.modulos for n in range(1, 9)),
       "switch em pe desenha todas as portas")
velha2 = Rede.from_dict({"versao": "B0.27", "equipamentos": [
    {"id": "O1", "nome": "OLT", "tipo": "OLT", "orientacao": "vertical", "modulos": []},
    {"id": "S1", "nome": "SW", "tipo": "SWITCH", "orientacao": "vertical", "modulos": []},
    {"id": "D1", "nome": "DIO", "tipo": "DIO", "num_portas": 12, "orientacao": "horizontal"}],
    "fusoes": []})
checar((velha2.equipamentos["O1"].orientacao, velha2.equipamentos["S1"].orientacao,
        velha2.equipamentos["D1"].orientacao) == ("vertical", "horizontal", "horizontal"),
       "rede da B0.27: OLT em pe, switch deitado, DIO como o usuario deixou")
copia_cabo = x.duplicar_equipamento(cabo.id)
checar(copia_cabo.num_portas == 36 and copia_cabo.is_cabo(), "duplicar cabo")
r_ex = rede_exemplo()
c2 = r_ex.equipamentos["CABO-02"]
checar(c2.pos_x < r_ex.equipamentos["ACOMO-01"].pos_x,
       "cabo de cliente fica do lado dos clientes (antes da CTO)")
r_ex.salvar(__import__("tempfile").gettempdir() + "/t_real.json")
volta = Rede.carregar(__import__("tempfile").gettempdir() + "/t_real.json")
checar(volta.equipamentos["CABO-01"].fibras_por_tubo == 12 and len(volta.fusoes) == 25
       and volta.equipamentos["CABO-02"].pos_x == c2.pos_x,
       "salvar/abrir guarda cabo, lados e posicoes")

print("== nome novo: WaspFiber (B0.30) ==")
checar(APP_NOME == "WaspFiber" and EXTENSAO == ".wasp.json", "nome e extensao novos")
import json as _json
caminho_nix = __import__("tempfile").gettempdir() + "/rede_velha.nix.json"
rede_exemplo().salvar(caminho_nix)
checar(len(Rede.carregar(caminho_nix).equipamentos) == 7, "rede .nix.json da versao Nix continua abrindo")
checar(pasta_do_programa().endswith("WaspFiber") and
       any(p.endswith("Nix") for p in pastas_antigas()),
       "recuperacao nova em WaspFiber, procurando tambem na pasta do Nix")
import waspfiber_icones as _ic
checar(all(hasattr(_ic, n) for n in ("LOGO_64", "LOGO_32", "LOGO_EMBLEMA")), "logos da vespa embutidas")

print("== tipos de porta: SC/LC, APC/UPC, duplex (B0.31) ==")
y = Rede()
d = y.add_equipamento("DIO Y", TIPO_DIO, 12)
o = y.add_equipamento("OLT Y", "OLT")
gp = o.add_placa("GPON-16")
ct = o.add_placa("CONTROLE")
a2 = y.add_equipamento("CTO Y", TIPO_ACOMODADOR)
sp = a2.add_splitter("1x8")
sw = y.add_equipamento("SW Y", "SWITCH")
gr = sw.add_grupamento("SFP", 4)
cb = y.add_equipamento("C Y", TIPO_CABO, 12)
checar(y.conector_da_porta(d.id, "F", 1) == ("SC", "APC"), "DIO nasce SC/APC na frente")
checar(y.conector_da_porta(d.id, "T", 1) == (None, None), "traseira do DIO e fusao (sem conector)")
checar(y.conector_da_porta(cb.id, "A", 1) == (None, None), "fibra de cabo e fusao (sem conector)")
checar(y.conector_da_porta(a2.id, sp.id, 2) == ("SC", "APC"), "saida de splitter SC/APC")
checar(y.conector_da_porta(o.id, gp.id, 1) == ("SC", "UPC"), "placa GPON SC/UPC")
checar(y.conector_da_porta(o.id, ct.id, 1) == ("LC", "UPC") and
       y.conector_da_porta(sw.id, gr.id, 1) == ("LC", "UPC"), "controle e switch LC/UPC")
y.definir_conector(d.id, "F", 2, "LC", "UPC")
checar(y.conector_da_porta(d.id, "F", 2) == ("LC", "UPC"), "troca o conector de uma porta")
y.definir_tipo_porta(d.id, "F", 3, DUPLEX)
checar(y.conector_da_porta(d.id, "F", 3)[0] == "LC" and y.limite_porta(d.id, "T", 3) == 2
       and y.limite_porta(d.id, "F", 3) == 2, "DIO duplex: vira LC e aceita 2 fibras dos dois lados")
bloqueia(lambda: y.definir_conector(d.id, "F", 3, "SC"), "duplex nao aceita SC")
y.definir_tipo_porta(o.id, ct.id, 2, DUPLEX)
checar(y.conector_da_porta(o.id, ct.id, 2)[0] == "LC", "porta de ativo duplex vira LC")
bloqueia(lambda: y.definir_tipo_porta(o.id, gp.id, 1, DUPLEX), "GPON continua travada em simplex")
bloqueia(lambda: y.definir_conector(cb.id, "A", 1, "SC"), "fibra de cabo nao tem conector")
mudou = y.definir_conector_em_lote(d.id, None, "SC", "UPC")
checar(y.conector_da_porta(d.id, "F", 1) == ("SC", "UPC") and
       y.conector_da_porta(d.id, "F", 3) == ("LC", "UPC") and mudou >= 11,
       "conector em lote: todas viram SC/UPC, a duplex continua LC", mudou)
# rastreio no DIO duplex: TX de tras so segue pro TX da frente
c2 = y.add_equipamento("C2 Y", TIPO_CABO, 12)
y.criar_fusao(c2.id, "B", 1, d.id, "T", 3, "TX")
y.criar_fusao(c2.id, "B", 2, d.id, "T", 3, "RX")
y.criar_fusao(d.id, "F", 3, o.id, ct.id, 2, "TX")
y.criar_fusao(d.id, "F", 3, sw.id, gr.id, 1, "RX")
arv = rastrear_caminho(y, (c2.id, "A", 1), None)
nomes = [n["nome"] for n in pontas_finais(arv)]
checar(len(nomes) == 1 and "OLT" in nomes[0], "duplex no DIO: a fibra TX nao vaza pro RX", nomes)
z = Rede.from_dict(json.loads(json.dumps(y.to_dict())))
checar(z.conector_da_porta(d.id, "F", 3) == ("LC", "UPC") and
       z.tipo_gbic_porta(d.id, "T", 3) == DUPLEX and
       z.conector_da_porta(d.id, "F", 2) == ("SC", "UPC"),
       "salvar/abrir guarda conector, polimento e duplex do DIO")
velha3 = Rede.from_dict({"versao": "B0.30", "equipamentos": [
    {"id": "O", "nome": "O", "tipo": "OLT", "modulos": [{"id": "P", "nome": "P", "tipo": "GPON-8",
     "gbic_fixo": "SIMPLEX", "portas": {"1": {"numero": 1, "tipo_gbic": "SIMPLEX"}}}]}],
    "fusoes": []})
checar(velha3.conector_da_porta("O", "P", 1) == ("SC", "UPC"),
       "rede antiga ganha o tipo padrao nas portas")
linhas = linhas_relatorio(y)
checar(any(l[3] == "LC/UPC dx" for l in linhas) and any(l[3] == "fusao" for l in linhas),
       "relatorio mostra o conector de cada porta")

print("== pendencias (novo) ==")
p = Rede()
dio = p.add_equipamento("DIO Teste", TIPO_DIO, 4)
ac = p.add_equipamento("CTO Teste", TIPO_ACOMODADOR)
sp = ac.add_splitter("1x2")
olt = p.add_equipamento("OLT Teste", "OLT")
placa = olt.add_placa("CONTROLE")
p.criar_fusao(ac.id, sp.id, 2, dio.id, None, 1, "Cliente X")   # saida ligada, ENT solta
p.definir_tipo_porta(olt.id, placa.id, 1, DUPLEX)
p.criar_fusao(olt.id, placa.id, 1, dio.id, None, 2, "")        # duplex com 1 fibra so
p.add_equipamento("DIO Teste", TIPO_DIO, 2)                    # nome repetido
tipos = {x["tipo"] for x in pendencias(p)}
checar("Splitter sem entrada" in tipos, "aponta splitter sem alimentacao")
checar("Duplex pela metade" in tipos, "aponta duplex com 1 fibra so")
checar("Nome repetido" in tipos, "aponta nomes repetidos")
checar("Sem conexao" in tipos, "aponta equipamento sem nenhuma fusao")
checar("Fusao sem rotulo" in tipos, "aponta fusao sem rotulo")
erros = [x for x in pendencias(p) if x["gravidade"] == "erro"]
checar(len(erros) >= 2 and pendencias(p)[0]["gravidade"] == "erro",
       "erros vem primeiro na lista", "%d erro(s)" % len(erros))
checar(all(x["chave"] is None or len(x["chave"]) == 3 for x in pendencias(p)),
       "cada pendencia aponta pra uma porta (pra busca levar ate la)")
checar(pendencias(rede_exemplo()) == [], "rede de exemplo nao tem pendencia")

cap = resumo_capacidade(p)
checar(len(cap) == 4 and all("livres" in c for c in cap), "resumo de capacidade")
total_livres = sum(c["livres"] for c in cap)
checar(total_livres == sum(c["total"] - c["usadas"] for c in cap), "contas de capacidade batem")

print("== exportacoes ==")
pasta = __import__("tempfile").gettempdir() + ""
r2 = rede_exemplo()
cena2 = montar_cena(r2)
exportar_svg(cena2, pasta + "/t_diagrama.svg")
escrever_pdf([pagina_do_diagrama(cena2)], pasta + "/t_diagrama.pdf")
exportar_relatorio_pdf(r2, cena2, pasta + "/t_relatorio.pdf")
exportar_relatorio_csv(r2, pasta + "/t_portas.csv")
exportar_pendencias_csv(p, pasta + "/t_pendencias.csv")
exportar_capacidade_csv(r2, pasta + "/t_capacidade.csv")
for nome, minimo in (("t_diagrama.svg", 2000), ("t_diagrama.pdf", 2000),
                     ("t_relatorio.pdf", 5000), ("t_portas.csv", 1000),
                     ("t_pendencias.csv", 100), ("t_capacidade.csv", 100)):
    tam = os.path.getsize(os.path.join(pasta, nome))
    checar(tam >= minimo, "gerou %s" % nome, "%d bytes" % tam)
linhas_csv = open(pasta + "/t_portas.csv", encoding="utf-8-sig").read().splitlines()
checar(len(linhas_csv) == len(linhas_relatorio(r2)) + 1, "CSV com cabecalho + todas as linhas")
pdf = open(pasta + "/t_relatorio.pdf", "rb").read()
checar(pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"), "PDF bem formado")
checar(b"/Type /Pages" in pdf and b"startxref" in pdf, "PDF com catalogo e xref")

print("== persistencia ==")
r2.salvar(pasta + "/t_rede.json")
r3 = Rede.carregar(pasta + "/t_rede.json")
checar(len(r3.equipamentos) == len(r2.equipamentos) and len(r3.fusoes) == len(r2.fusoes),
       "roundtrip do json")
checar(len(r3.fusoes_na_porta("DIO-01", None, 3)) == 1, "indice reconstruido ao abrir")
checar(gravar_autosave(r2, "x.json") and ler_autosave()[0] is not None, "autosave")
apagar_autosave()
checar(ler_autosave()[0] is None, "autosave apagado")

print("== limites ==")
montar_cena(Rede())
checar(True, "rede vazia nao quebra o desenho")
grande = Rede()
for i in range(12):
    grande.add_equipamento("DIO %d" % i, TIPO_DIO, 48)
t0 = time.time()
cg = montar_cena(grande)
t1 = time.time()
checar(t1 - t0 < 2.0, "rede grande (576 portas) desenha rapido", "%.2fs" % (t1 - t0))
t0 = time.time()
buscar(grande, "10")
checar(time.time() - t0 < 2.0, "busca rapida em rede grande")

print()
if FALHAS:
    print("!! %d FALHA(S): %s" % (len(FALHAS), "; ".join(FALHAS)))
    raise SystemExit(1)
print("TODOS OS TESTES PASSARAM")
