# -*- coding: utf-8 -*-
"""Componentes de interface do WaspFiber: icones, botoes com hover, tooltips,
menus suspensos proprios e cartoes de equipamento.

Existe porque no Windows o tkinter usa a barra de menu NATIVA (branca, que
ignora o tema escuro) e os menus suspensos nativos. Aqui tudo e desenhado
pelo proprio programa, no tema."""

import base64
import sys
import tkinter as tk

import waspfiber_icones as nix_icones

_CACHE_ICONES = {}
_MESTRE = [None]


_CACHES = {}


def usar_janela(raiz):
    """As imagens do tkinter pertencem a UMA janela principal. Cada janela
    principal tem o seu cache (apagar as imagens de uma janela que ainda as
    usa quebra os botoes dela)."""
    global _CACHE_ICONES
    _MESTRE[0] = raiz
    _CACHE_ICONES = _CACHES.setdefault(id(raiz), {})


def icone(nome, cor="fraco", tamanho=18):
    """PhotoImage de um icone Lucide na cor do tema (guardado em cache: o
    tkinter apaga a imagem se ninguem segurar a referencia)."""
    chave = (nome, cor, tamanho)
    if chave not in _CACHE_ICONES:
        dados = nix_icones.ICONES.get(chave) or nix_icones.ICONES.get((nome, cor, 18))
        if dados is None:
            return None
        _CACHE_ICONES[chave] = tk.PhotoImage(data=dados, master=_MESTRE[0])
    return _CACHE_ICONES[chave]


def logo(tamanho=32):
    chave = ("__logo", tamanho)
    if chave not in _CACHE_ICONES:
        dados = nix_icones.LOGO_64 if tamanho > 32 else nix_icones.LOGO_32
        _CACHE_ICONES[chave] = tk.PhotoImage(data=dados, master=_MESTRE[0])
    return _CACHE_ICONES[chave]


def logo_emblema():
    """A vespa inteira, com o rastro de fibras (tela de rede vazia)."""
    chave = ("__emblema",)
    if chave not in _CACHE_ICONES:
        _CACHE_ICONES[chave] = tk.PhotoImage(data=nix_icones.LOGO_EMBLEMA, master=_MESTRE[0])
    return _CACHE_ICONES[chave]


def barra_de_titulo_escura(janela):
    """Windows 10/11: pede ao sistema a barra de titulo escura (senao ela
    fica branca em cima de um programa escuro). Nos outros sistemas, nada."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        janela.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(janela.winfo_id())
        valor = ctypes.c_int(1)
        for atributo in (20, 19):      # DWMWA_USE_IMMERSIVE_DARK_MODE (novo e antigo)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, atributo, ctypes.byref(valor), ctypes.sizeof(valor)) == 0:
                # janela ja visivel: forca o Windows a repintar a moldura agora
                # (SWP_NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED)
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)
                janela._titulo_escuro = True
                return True
    except Exception:
        pass
    return False


class Tooltip:
    """Balaozinho com o nome e o atalho, ao parar o mouse num botao de icone."""

    def __init__(self, widget, texto, tema):
        self.widget, self.texto, self.tema = widget, texto, tema
        self.janela = None
        self._agendado = None
        widget.bind("<Enter>", self._agendar, add="+")
        widget.bind("<Leave>", self._esconder, add="+")
        widget.bind("<ButtonPress>", self._esconder, add="+")

    def _agendar(self, _=None):
        self._agendado = self.widget.after(450, self._mostrar)

    def _mostrar(self):
        if self.janela or not self.texto:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.janela = tk.Toplevel(self.widget)
        self.janela.overrideredirect(True)
        self.janela.configure(bg=self.tema["ui_borda"])
        rotulo = tk.Label(self.janela, text=self.texto, bg=self.tema["ui_painel"],
                          fg=self.tema["ui_texto"], padx=8, pady=4,
                          font=("TkDefaultFont", 8))
        rotulo.pack(padx=1, pady=1)
        self.janela.update_idletasks()
        self.janela.geometry("+%d+%d" % (x - self.janela.winfo_width() // 2, y))

    def _esconder(self, _=None):
        if self._agendado:
            self.widget.after_cancel(self._agendado)
            self._agendado = None
        if self.janela:
            self.janela.destroy()
            self.janela = None


class BotaoIcone(tk.Label):
    """Botao plano: icone (e texto opcional), fundo muda ao passar o mouse.
    variante: 'normal' | 'acento' | 'fantasma' (sem fundo ate o hover)."""

    def __init__(self, pai, tema, nome_icone=None, texto="", comando=None, dica=None,
                 variante="fantasma", fonte=None, largura=None):
        self.tema, self.comando, self.variante = tema, comando, variante
        self.nome_icone = nome_icone
        self._pai = pai                      # o fundo "fantasma" e o do pai
        cores = self._cores()
        super().__init__(pai, text=texto, compound="left" if texto else "center",
                         bg=cores["fundo"], fg=cores["texto"], cursor="hand2",
                         padx=10 if texto else 7, pady=6,
                         font=fonte or ("TkDefaultFont", 9), bd=0)
        if largura:
            self.configure(width=largura)
        elif not texto:
            # so icone: area de clique fixa (em pixels), pra nao grudar no vizinho
            self.configure(width=32, height=30, padx=0, pady=0)
        self._trocar_icone(cores["icone"])
        self.bind("<Enter>", self._entrar)
        self.bind("<Leave>", self._sair)
        self.bind("<ButtonRelease-1>", self._clicar)
        if dica:
            Tooltip(self, dica, tema)

    def _cores(self, hover=False):
        t = self.tema
        if self.variante == "acento":
            return {"fundo": t["ui_acento"], "texto": t["ui_acento_texto"], "icone": "escuro"}
        if self.variante == "normal":
            return {"fundo": t["ui_hover"] if hover else t["ui_painel"],
                    "texto": t["ui_texto"], "icone": "texto"}
        return {"fundo": t["ui_hover"] if hover else self._pai.cget("bg"),
                "texto": t["ui_texto"] if hover else t["ui_texto_fraco"],
                "icone": "texto" if hover else "fraco"}

    def _trocar_icone(self, cor):
        if self.nome_icone:
            imagem = icone(self.nome_icone, cor)
            if imagem is not None:
                self.configure(image=imagem)

    def _entrar(self, _=None):
        cores = self._cores(hover=True)
        self.configure(bg=cores["fundo"], fg=cores["texto"])
        self._trocar_icone(cores["icone"])

    def _sair(self, _=None):
        cores = self._cores()
        self.configure(bg=cores["fundo"], fg=cores["texto"])
        self._trocar_icone(cores["icone"])

    def _clicar(self, _=None):
        if self.comando:
            self.comando()


def dentro_de(widget, container):
    """True se o widget e o proprio container ou um filho dele."""
    if container is None or not hasattr(widget, "winfo_toplevel"):
        return False
    caminho, base = str(widget), str(container)
    return caminho == base or caminho.startswith(base + ".")


class MenuSuspenso:
    """Menu suspenso desenhado pelo programa (o nativo do Windows e branco).
    Fica DENTRO da janela (place), nao numa janela separada: assim nao briga
    com foco nem com o gerenciador de janelas. Fecha com clique fora ou Esc.
    itens: lista de (icone, texto, atalho, comando) ou None pra separador."""

    def __init__(self, ancora, tema, itens, alinhar="esquerda"):
        self.ancora, self.tema, self.itens, self.alinhar = ancora, tema, itens, alinhar
        self.janela = None
        self._posicao = None
        self.raiz = ancora.winfo_toplevel()
        self.raiz.bind_all("<ButtonPress-1>", self._clique_fora, add="+")

    def aberto(self):
        return self.janela is not None

    def _clique_fora(self, evento):
        if self.janela is None:
            return
        if dentro_de(evento.widget, self.janela):
            return                      # clique no proprio menu
        if self._posicao is None and dentro_de(evento.widget, self.ancora):
            return                      # clique no botao que abre (ele mesmo alterna)
        self.fechar()

    def abrir_em(self, x_raiz, y_raiz, itens=None):
        """Menu de contexto: abre onde o mouse esta (botao direito)."""
        self.fechar()
        if itens is not None:
            self.itens = itens
        self._posicao = (x_raiz, y_raiz)
        self.abrir()

    def abrir(self):
        if self.janela is not None:
            self.fechar()
            return
        t = self.tema
        self.janela = tk.Frame(self.raiz, bg=t["ui_borda"])
        corpo = tk.Frame(self.janela, bg=t["ui_painel"], padx=4, pady=4)
        corpo.pack(padx=1, pady=1)
        self.linhas = []
        for item in self.itens:
            if item is None:
                tk.Frame(corpo, bg=t["ui_borda"], height=1).pack(fill="x", pady=4, padx=6)
                continue
            nome_icone, texto, atalho, comando = item
            linha = tk.Frame(corpo, bg=t["ui_painel"], cursor="hand2")
            linha.pack(fill="x")
            img = tk.Label(linha, image=icone(nome_icone, "fraco") if nome_icone else "",
                           bg=t["ui_painel"], width=26)
            img.pack(side="left", padx=(4, 2), pady=5)
            rot = tk.Label(linha, text=texto, bg=t["ui_painel"], fg=t["ui_texto"],
                           anchor="w", width=34, font=("TkDefaultFont", 9))
            rot.pack(side="left")
            ata = tk.Label(linha, text=atalho or "", bg=t["ui_painel"],
                           fg=t["ui_texto_fraco"], font=("TkDefaultFont", 8), width=8,
                           anchor="e")
            ata.pack(side="left", padx=(8, 8))
            self.linhas.append((texto, comando))

            def entrar(_e, partes=(linha, img, rot, ata), nome=nome_icone):
                for p in partes:
                    p.configure(bg=t["ui_hover"])
                if nome:
                    partes[1].configure(image=icone(nome, "texto"))

            def sair(_e, partes=(linha, img, rot, ata), nome=nome_icone):
                for p in partes:
                    p.configure(bg=t["ui_painel"])
                if nome:
                    partes[1].configure(image=icone(nome, "fraco"))

            def clicar(_e, cmd=comando):
                self.executar(cmd)
            for parte in (linha, img, rot, ata):
                parte.bind("<Enter>", entrar)
                parte.bind("<Leave>", sair)
                parte.bind("<ButtonRelease-1>", clicar)
        self.janela.update_idletasks()
        if self._posicao is not None:
            x = self._posicao[0] - self.raiz.winfo_rootx() + 2
            y = self._posicao[1] - self.raiz.winfo_rooty() + 2
            y = max(4, min(y, self.raiz.winfo_height() - self.janela.winfo_reqheight() - 4))
        else:
            x = self.ancora.winfo_rootx() - self.raiz.winfo_rootx()
            y = self.ancora.winfo_rooty() - self.raiz.winfo_rooty() + self.ancora.winfo_height() + 4
        if self.alinhar == "direita" and self._posicao is None:
            x = x + self.ancora.winfo_width() - self.janela.winfo_reqwidth()
        x = max(4, min(x, self.raiz.winfo_width() - self.janela.winfo_reqwidth() - 4))
        self.janela.place(x=x, y=y)
        self.janela.lift()

    def executar(self, comando):
        """Fecha o menu e so depois roda o comando (que pode abrir um dialogo)."""
        self.fechar()
        if comando:
            self.raiz.after(10, comando)

    def fechar(self):
        if self.janela is not None:
            self.janela.destroy()
            self.janela = None
        self._posicao = None


def rolagem_automatica(barra):
    """Funcao pra yscrollcommand que esconde a barra quando tudo cabe."""
    def ajustar(primeiro, ultimo):
        if float(primeiro) <= 0.0 and float(ultimo) >= 1.0:
            barra.pack_forget()
        elif not barra.winfo_ismapped():
            barra.pack(side="right", fill="y")
        barra.set(primeiro, ultimo)
    return ajustar


ICONE_POR_TIPO = {"CABO": "cable", "DIO": "panel-top", "ACOMODADOR": "split", "OLT": "server",
                  "SWITCH": "network", "RB": "router"}


class CartaoEquipamento(tk.Frame):
    """Um equipamento na lista lateral: icone do tipo, nome, ocupacao em
    numero e uma barrinha fina de ocupacao."""

    def __init__(self, pai, tema, eq, usadas, total, ao_clicar, ao_duplo=None):
        super().__init__(pai, bg=tema["ui_fundo"], cursor="hand2")
        self.tema, self.eq_id = tema, eq.id
        self.selecionado = False
        self.ao_clicar, self.ao_duplo = ao_clicar, ao_duplo
        self.img = tk.Label(self, image=icone(ICONE_POR_TIPO.get(eq.tipo, "box"), "fraco"),
                            bg=tema["ui_fundo"])
        self.img.grid(row=0, column=0, rowspan=2, padx=(8, 10), pady=7, sticky="n")
        self.nome = tk.Label(self, text=eq.nome, bg=tema["ui_fundo"], fg=tema["ui_texto"],
                             anchor="w", font=("TkDefaultFont", 9))
        self.nome.grid(row=0, column=1, sticky="we", pady=(6, 0))
        self.info = tk.Label(self, text="%s   ·   %d/%d" % (eq.tipo, usadas, total),
                             bg=tema["ui_fundo"], fg=tema["ui_texto_fraco"], anchor="w",
                             font=("TkDefaultFont", 8))
        self.info.grid(row=1, column=1, sticky="we")
        self.barra = tk.Canvas(self, height=2, bg=tema["ui_borda"], highlightthickness=0, bd=0)
        self.barra.grid(row=2, column=1, sticky="we", pady=(4, 8), padx=(0, 10))
        self.columnconfigure(1, weight=1)
        self.fracao = (usadas / float(total)) if total else 0.0
        self.barra.bind("<Configure>", self._desenhar_barra)
        for parte in (self, self.img, self.nome, self.info, self.barra):
            parte.bind("<Enter>", lambda _e: self._fundo(hover=True))
            parte.bind("<Leave>", lambda _e: self._fundo())
            parte.bind("<ButtonRelease-1>", lambda _e: self.ao_clicar(self.eq_id))
            if ao_duplo:
                parte.bind("<Double-Button-1>", lambda _e: self.ao_duplo())

    def atualizar(self, eq, usadas, total):
        """Troca os numeros sem recriar o cartao (a lista e redesenhada a
        cada fusao - recriar tudo piscaria a barra lateral)."""
        self.nome.configure(text=eq.nome)
        self.info.configure(text="%s   ·   %d/%d" % (eq.tipo, usadas, total))
        self.img.configure(image=icone(ICONE_POR_TIPO.get(eq.tipo, "box"), "fraco"))
        self.fracao = (usadas / float(total)) if total else 0.0
        self._desenhar_barra()

    def ao_rodar(self, funcao):
        for parte in (self, self.img, self.nome, self.info, self.barra):
            parte.bind("<MouseWheel>", funcao)
            parte.bind("<Button-4>", funcao)
            parte.bind("<Button-5>", funcao)

    def _desenhar_barra(self, _=None):
        self.barra.delete("all")
        largura = self.barra.winfo_width()
        cor = self.tema["ui_aviso"] if self.fracao >= 0.9 else self.tema["ui_ok"]
        if self.fracao > 0:
            self.barra.create_rectangle(0, 0, max(2, largura * self.fracao), 2,
                                        fill=cor, outline="")

    def _fundo(self, hover=False):
        t = self.tema
        cor = t["ui_painel"] if (self.selecionado or hover) else t["ui_fundo"]
        for parte in (self, self.img, self.nome, self.info):
            parte.configure(bg=cor)

    def marcar(self, sim):
        self.selecionado = sim
        t = self.tema
        self.nome.configure(fg=t["ui_acento"] if sim else t["ui_texto"])
        self._fundo()
