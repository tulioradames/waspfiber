# -*- coding: utf-8 -*-
"""Localizacao do diagrama no mapa (B0.34).

Cada rede (.wasp.json) e um LOCAL do campo - um POP, uma caixa de emenda
(CEO) ou uma CTO - com coordenada. Este modulo tem:

- ler_coordenada(): entende o que a pessoa cola - "-23.55, -46.63", o link
  do Google Maps, ou o formato do Google Earth (23°33'01.8"S 46°38'00.0"W);
- os links pra abrir o ponto no Google Maps e no Google Earth (navegador,
  sem chave de API);
- MapaWidget: um mapa de verdade dentro do programa (ruas do OpenStreetMap
  ou satelite da Esri), com arrastar, zoom na roda e clique pra marcar o
  ponto. Os tiles sao baixados em segundo plano e guardados em disco; sem
  internet o mapa avisa e a coordenada continua podendo ser digitada;
- buscar_endereco() / endereco_do_ponto(): busca de endereco (Nominatim,
  do OpenStreetMap).

Os tiles do proprio Google nao podem ser usados fora da API paga dele; por
isso o mapa interno usa OpenStreetMap/Esri e o Google abre no navegador.

So biblioteca padrao (tkinter + urllib): o PNG e lido pelo proprio Tk.
"""

import base64
import json
import math
import os
import queue
import re
import threading
import urllib.parse
import urllib.request

import tkinter as tk

AGENTE = "WaspFiber/B0.34 (diagramas FTTX; desktop)"

# tipos de local que um diagrama pode ser
TIPOS_LOCAL = (("POP", "POP"), ("CEO", "Caixa de emenda (CEO)"), ("CTO", "CTO"))
ROTULO_TIPO_LOCAL = dict(TIPOS_LOCAL)

ZOOM_MIN, ZOOM_MAX = 3, 19
TAM_TILE = 256
_RAIO_TERRA_M = 6378137.0
_LIMITE_MERC = math.pi * _RAIO_TERRA_M      # 20037508.34 m

FONTES = {
    "mapa": {"rotulo": "Mapa",
             "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
             "credito": "© colaboradores do OpenStreetMap"},
    "satelite": {"rotulo": "Satelite",
                 # o servico de tiles da Esri entrega JPEG (o Tk nao le sem
                 # PIL); o "export" da mesma camada entrega PNG do mesmo recorte
                 "url": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                         "World_Imagery/MapServer/export?bbox={bbox}&bboxSR=3857"
                         "&imageSR=3857&size=256,256&format=png&f=image"),
                 "credito": "Imagens © Esri, Maxar, Earthstar Geographics"},
}


# ============================================================================
#  COORDENADAS
# ============================================================================

def _valida(lat, lon):
    if lat is None or lon is None:
        return None
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        return (round(lat, 7), round(lon, 7))
    return None


_NUM = r"[-+]?\d{1,3}(?:\.\d+)?"


def _dms_para_graus(graus, minutos, segundos, hemisferio):
    valor = abs(float(graus)) + float(minutos or 0) / 60.0 + float(segundos or 0) / 3600.0
    if hemisferio.upper() in ("S", "W", "O") or str(graus).strip().startswith("-"):
        valor = -valor
    return valor


def ler_coordenada(texto):
    """(lat, lon) a partir do que a pessoa colar, ou None se nao entender.

    Aceita: "-23.5505, -46.6333" | "-23,5505 -46,6333" (virgula decimal) |
    links do Google Maps (@lat,lon,17z  /  !3dlat!4dlon  /  ?q=lat,lon) |
    graus-minutos-segundos do Google Earth: 23°33'01.8"S 46°38'00.0"W
    (tambem com O de oeste e sem os simbolos: 23 33 1.8 S 46 38 0 W)."""
    if not texto:
        return None
    s = urllib.parse.unquote(str(texto)).strip()

    # link do Google Maps: o ponto marcado (!3d!4d) vale mais que o centro (@)
    achado = re.search(r"!3d(" + _NUM + r")!4d(" + _NUM + r")", s)
    if achado:
        return _valida(float(achado.group(1)), float(achado.group(2)))
    achado = re.search(r"[?&](?:q|query|ll|center|destination)=(" + _NUM + r")\s*,\s*(" + _NUM + r")", s)
    if achado:
        return _valida(float(achado.group(1)), float(achado.group(2)))
    achado = re.search(r"@(" + _NUM + r"),(" + _NUM + r")", s)
    if achado:
        return _valida(float(achado.group(1)), float(achado.group(2)))

    # graus, minutos, segundos + hemisferio
    dms = (r"(\d{1,3})\s*[°º:\s]\s*(\d{1,2})\s*['′:\s]\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:\"|″|'')?"
           r"\s*([NSEWLO])")
    partes = re.findall(dms, s, flags=re.IGNORECASE)
    if len(partes) == 2:
        valores = {}
        for g, m, seg, hem in partes:
            v = _dms_para_graus(g, m, seg.replace(",", "."), hem)
            valores["lat" if hem.upper() in "NS" else "lon"] = v
        if "lat" in valores and "lon" in valores:
            return _valida(valores["lat"], valores["lon"])

    # graus decimais com hemisferio: 23.55 S 46.63 W
    partes = re.findall(r"(\d{1,3}(?:[.,]\d+)?)\s*°?\s*([NSEWLO])\b", s, flags=re.IGNORECASE)
    if len(partes) == 2:
        valores = {}
        for g, hem in partes:
            v = _dms_para_graus(g.replace(",", "."), 0, 0, hem)
            valores["lat" if hem.upper() in "NS" else "lon"] = v
        if "lat" in valores and "lon" in valores:
            return _valida(valores["lat"], valores["lon"])

    # dois numeros decimais com ponto: "-23.55, -46.63" / "-23.55 -46.63"
    achado = re.fullmatch(r"\(?\s*(" + _NUM + r")\s*[,;\s]\s*(" + _NUM + r")\s*\)?", s)
    if achado:
        return _valida(float(achado.group(1)), float(achado.group(2)))
    # virgula decimal (jeito brasileiro): "-23,55 -46,63" / "-23,55; -46,63"
    achado = re.fullmatch(r"([-+]?\d{1,3},\d+)\s*[;\s]\s*([-+]?\d{1,3},\d+)", s)
    if achado:
        return _valida(float(achado.group(1).replace(",", ".")),
                       float(achado.group(2).replace(",", ".")))
    return None


def formatar_coordenada(lat, lon):
    """'-23.550520, -46.633308' - o formato que o Google Maps aceita colado."""
    return "%.6f, %.6f" % (lat, lon)


def formatar_dms(lat, lon):
    """23°33'01.9"S  46°38'00.0"W - como o Google Earth mostra."""
    def um(valor, pos, neg):
        hem = pos if valor >= 0 else neg
        valor = abs(valor)
        g = int(valor)
        m = int((valor - g) * 60)
        s = (valor - g - m / 60.0) * 3600
        if s >= 59.95:
            s, m = 0.0, m + 1
        if m >= 60:
            m, g = 0, g + 1
        return "%d°%02d'%04.1f\"%s" % (g, m, s, hem)
    return "%s  %s" % (um(lat, "N", "S"), um(lon, "E", "W"))


def link_google_maps(lat, lon):
    return "https://www.google.com/maps/search/?api=1&query=%.7f,%.7f" % (lat, lon)


def link_google_earth(lat, lon, altitude_m=600):
    # @lat,lon,altitude do terreno(a),distancia da camera(d),fov(y),rumo(h),inclinacao(t)
    return ("https://earth.google.com/web/@%.7f,%.7f,0a,%dd,35y,0h,0t,0r"
            % (lat, lon, altitude_m))


def local_vazio():
    return {"tipo": "", "nome": "", "endereco": "", "cidade": "", "lat": None,
            "lon": None, "obs": ""}


def normalizar_local(dados):
    """Dicionario do local sempre com todas as chaves (redes antigas nao tem)."""
    base = local_vazio()
    if isinstance(dados, dict):
        for chave in base:
            if chave in dados and dados[chave] is not None:
                base[chave] = dados[chave]
    for chave in ("lat", "lon"):
        try:
            base[chave] = None if base[chave] in ("", None) else float(base[chave])
        except (TypeError, ValueError):
            base[chave] = None
    if _valida(base["lat"], base["lon"]) is None:
        base["lat"] = base["lon"] = None
    if base["tipo"] not in ROTULO_TIPO_LOCAL:
        base["tipo"] = ""
    for chave in ("nome", "endereco", "cidade", "obs"):
        base[chave] = str(base[chave] or "").strip()
    return base


def local_preenchido(local):
    local = normalizar_local(local)
    return bool(local["tipo"] or local["nome"] or local["endereco"] or local["cidade"]
                or local["lat"] is not None)


def resumo_local(local, com_coordenada=True):
    """'CTO · CTO-Bairro-01 · -23.550520, -46.633308' (vazio se nada definido)."""
    local = normalizar_local(local)
    partes = []
    if local["tipo"]:
        partes.append(local["tipo"])
    if local["nome"]:
        partes.append(local["nome"])
    if local["cidade"]:
        partes.append(local["cidade"])
    if com_coordenada and local["lat"] is not None:
        partes.append(formatar_coordenada(local["lat"], local["lon"]))
    return "  ·  ".join(partes)


# ============================================================================
#  PROJECAO (Web Mercator, a mesma do Google/OSM)
# ============================================================================

def latlon_para_pixel(lat, lon, zoom):
    """Pixel 'do mundo' no zoom dado (o mundo inteiro tem 256 * 2^zoom px)."""
    lat = max(-85.05112878, min(85.05112878, lat))
    n = TAM_TILE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * n
    return x, y


def pixel_para_latlon(x, y, zoom):
    n = TAM_TILE * (2 ** zoom)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def bbox_do_tile(x, y, zoom):
    """Recorte do tile em metros (EPSG:3857): minx,miny,maxx,maxy."""
    lado = 2 * _LIMITE_MERC / (2 ** zoom)
    minx = -_LIMITE_MERC + x * lado
    maxy = _LIMITE_MERC - y * lado
    return "%.3f,%.3f,%.3f,%.3f" % (minx, maxy - lado, minx + lado, maxy)


def url_do_tile(fonte, zoom, x, y):
    modelo = FONTES[fonte]["url"]
    return modelo.format(z=zoom, x=x, y=y, bbox=bbox_do_tile(x, y, zoom))


# ============================================================================
#  REDE (tiles, busca de endereco) - sempre fora da thread da interface
# ============================================================================

def pasta_cache(base=None):
    base = base or os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") \
        or os.path.expanduser("~")
    return os.path.join(base, "WaspFiber", "mapa")


def _baixar(url, tempo=15):
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE,
                                                  "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(pedido, timeout=tempo) as resposta:
        return resposta.read()


def baixar_tile(fonte, zoom, x, y, pasta=None):
    """Bytes PNG do tile (do cache em disco, ou da internet). Lanca excecao
    se nao conseguir."""
    caminho = os.path.join(pasta or pasta_cache(), fonte, str(zoom), str(x), "%d.png" % y)
    if os.path.exists(caminho):
        with open(caminho, "rb") as fp:
            dados = fp.read()
        if dados[:4] == b"\x89PNG":
            return dados
    dados = _baixar(url_do_tile(fonte, zoom, x, y))
    if dados[:4] != b"\x89PNG":
        raise ValueError("o servidor do mapa nao devolveu uma imagem PNG")
    try:
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with open(caminho, "wb") as fp:
            fp.write(dados)
    except OSError:
        pass
    return dados


def buscar_endereco(texto, limite=6):
    """[(descricao, lat, lon), ...] para um endereco (OpenStreetMap/Nominatim).
    Prioriza o Brasil. Lanca excecao se nao houver conexao."""
    consulta = urllib.parse.urlencode({"q": texto, "format": "jsonv2", "limit": limite,
                                       "countrycodes": "br", "addressdetails": 0})
    dados = json.loads(_baixar("https://nominatim.openstreetmap.org/search?" + consulta)
                       .decode("utf-8"))
    return [(d.get("display_name", ""), float(d["lat"]), float(d["lon"])) for d in dados]


def endereco_do_ponto(lat, lon):
    """(endereco, cidade) do ponto - geocodificacao reversa do Nominatim."""
    consulta = urllib.parse.urlencode({"lat": "%.7f" % lat, "lon": "%.7f" % lon,
                                       "format": "jsonv2", "zoom": 18, "addressdetails": 1})
    d = json.loads(_baixar("https://nominatim.openstreetmap.org/reverse?" + consulta)
                   .decode("utf-8"))
    a = d.get("address") or {}
    rua = a.get("road") or a.get("pedestrian") or a.get("highway") or ""
    numero = a.get("house_number") or ""
    bairro = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
    cidade = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    uf = a.get("ISO3166-2-lvl4", "").replace("BR-", "") or a.get("state", "")
    endereco = ", ".join(p for p in ((rua + (", " + numero if numero else "")), bairro) if p)
    cidade_uf = cidade + ((" - " + uf) if (cidade and uf) else "")
    return endereco or d.get("display_name", ""), cidade_uf


# ============================================================================
#  ULTIMA VISTA (o mapa abre onde a pessoa estava trabalhando)
# ============================================================================

VISTA_PADRAO = (-15.78, -47.93, 4)    # Brasil inteiro


def ler_ultima_vista(pasta=None):
    try:
        with open(os.path.join(pasta or pasta_cache(), "ultima_vista.json"), encoding="utf-8") as fp:
            d = json.load(fp)
        vista = (float(d["lat"]), float(d["lon"]), int(d["zoom"]))
        if _valida(vista[0], vista[1]) and ZOOM_MIN <= vista[2] <= ZOOM_MAX:
            return vista
    except Exception:
        pass
    return VISTA_PADRAO


def gravar_ultima_vista(lat, lon, zoom, pasta=None):
    try:
        pasta = pasta or pasta_cache()
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, "ultima_vista.json"), "w", encoding="utf-8") as fp:
            json.dump({"lat": lat, "lon": lon, "zoom": zoom}, fp)
    except OSError:
        pass


# ============================================================================
#  WIDGET DO MAPA
# ============================================================================

class MapaWidget(tk.Canvas):
    """Mapa navegavel: arrastar move, roda do mouse da zoom no cursor e um
    clique (sem arrastar) marca o ponto e chama ao_marcar(lat, lon).

    baixador(fonte, z, x, y) -> bytes PNG roda nas threads de fundo; nos
    testes da pra trocar por um que nao usa a internet."""

    MAX_IMAGENS = 400

    def __init__(self, pai, tema, largura=620, altura=440, ao_marcar=None,
                 baixador=None, fonte="mapa", centro=None, zoom=None, **kw):
        self.tema = tema
        super().__init__(pai, width=largura, height=altura, bg=tema.get("fundo", "#1c1b19"),
                         highlightthickness=1, highlightbackground=tema.get("ui_borda", "#333"),
                         cursor="fleur", **kw)
        vista = ler_ultima_vista()
        self.lat, self.lon = centro if centro else vista[:2]
        self.zoom = zoom if zoom is not None else (17 if centro else vista[2])
        self.fonte = fonte
        self.marcador = None                  # (lat, lon)
        self.ao_marcar = ao_marcar
        self.baixador = baixador or baixar_tile
        self._imagens = {}                    # (fonte, z, x, y) -> PhotoImage
        self._ordem = []                      # LRU simples das imagens
        self._pedidos = set()                 # tiles ja pedidos (em andamento)
        self._falhas = set()
        self._fila_saida = queue.Queue()      # (chave, bytes ou excecao)
        self._fila_entrada = queue.Queue()
        self._inicio_arraste = None
        self._arrastou = False
        self._redesenho = None
        self.erro_rede = None
        self._vivo = True
        for _ in range(4):
            threading.Thread(target=self._trabalhador, daemon=True).start()
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<MouseWheel>", self._roda)
        self.bind("<Button-4>", lambda e: self.aplicar_zoom(+1, (e.x, e.y)))
        self.bind("<Button-5>", lambda e: self.aplicar_zoom(-1, (e.x, e.y)))
        self.bind("<Configure>", lambda _e: self.redesenhar())
        self.bind("<Destroy>", self._destruir, add="+")
        self.after(60, self._receber)

    # ---------------- threads de download ----------------
    def _trabalhador(self):
        while True:
            chave = self._fila_entrada.get()
            if chave is None:
                return
            fonte, z, x, y = chave
            try:
                resultado = self.baixador(fonte, z, x, y)
            except Exception as erro:          # sem internet, servidor fora...
                resultado = erro
            self._fila_saida.put((chave, resultado))

    def _receber(self):
        if not self._vivo:
            return
        chegou = False
        try:
            while True:
                chave, resultado = self._fila_saida.get_nowait()
                self._pedidos.discard(chave)
                if isinstance(resultado, Exception):
                    self._falhas.add(chave)
                    self.erro_rede = str(resultado)
                    chegou = True
                    continue
                try:
                    imagem = tk.PhotoImage(master=self,
                                           data=base64.b64encode(resultado).decode("ascii"))
                except tk.TclError:
                    self._falhas.add(chave)
                    continue
                self._guardar_imagem(chave, imagem)
                self.erro_rede = None
                chegou = True
        except queue.Empty:
            pass
        if chegou:
            self.redesenhar()
        self.after(60, self._receber)

    def _guardar_imagem(self, chave, imagem):
        self._imagens[chave] = imagem
        self._ordem.append(chave)
        while len(self._ordem) > self.MAX_IMAGENS:
            velha = self._ordem.pop(0)
            if velha in self._imagens and velha not in self._ordem:
                del self._imagens[velha]

    def _destruir(self, evento):
        if evento.widget is not self:
            return
        self._vivo = False
        gravar_ultima_vista(self.lat, self.lon, self.zoom)
        for _ in range(4):
            self._fila_entrada.put(None)

    # ---------------- navegacao ----------------
    def centralizar(self, lat, lon, zoom=None):
        self.lat, self.lon = lat, lon
        if zoom is not None:
            self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, int(zoom)))
        self.redesenhar()

    def marcar(self, lat, lon, centralizar=False, avisar=False):
        self.marcador = (lat, lon) if lat is not None else None
        if centralizar and lat is not None:
            self.lat, self.lon = lat, lon
            self.zoom = max(self.zoom, 16)
        self.redesenhar()
        if avisar and self.ao_marcar and lat is not None:
            self.ao_marcar(lat, lon)

    def trocar_fonte(self, fonte):
        if fonte in FONTES and fonte != self.fonte:
            self.fonte = fonte
            self._falhas = set()
            self.redesenhar()

    def aplicar_zoom(self, passo, ancora=None):
        novo = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom + passo))
        if novo == self.zoom:
            return
        w, h = self._tamanho()
        if ancora is None:
            ancora = (w / 2.0, h / 2.0)
        # mantem o ponto debaixo do cursor no mesmo lugar
        cx, cy = latlon_para_pixel(self.lat, self.lon, self.zoom)
        mx, my = cx + ancora[0] - w / 2.0, cy + ancora[1] - h / 2.0
        lat_m, lon_m = pixel_para_latlon(mx, my, self.zoom)
        self.zoom = novo
        nmx, nmy = latlon_para_pixel(lat_m, lon_m, novo)
        self.lat, self.lon = pixel_para_latlon(nmx - (ancora[0] - w / 2.0),
                                               nmy - (ancora[1] - h / 2.0), novo)
        self.redesenhar()

    def _roda(self, evento):
        self.aplicar_zoom(+1 if evento.delta > 0 else -1, (evento.x, evento.y))

    def _press(self, evento):
        self._inicio_arraste = (evento.x, evento.y, self.lat, self.lon)
        self._arrastou = False

    def _motion(self, evento):
        if not self._inicio_arraste:
            return
        x0, y0, lat0, lon0 = self._inicio_arraste
        dx, dy = evento.x - x0, evento.y - y0
        if abs(dx) + abs(dy) > 4:
            self._arrastou = True
        if self._arrastou:
            cx, cy = latlon_para_pixel(lat0, lon0, self.zoom)
            self.lat, self.lon = pixel_para_latlon(cx - dx, cy - dy, self.zoom)
            self.lat = max(-85.0, min(85.0, self.lat))
            self.lon = ((self.lon + 180.0) % 360.0) - 180.0
            self.redesenhar()

    def _release(self, evento):
        if self._inicio_arraste and not self._arrastou:
            lat, lon = self.ponto_da_tela(evento.x, evento.y)
            self.marcar(round(lat, 7), round(lon, 7), avisar=True)
        self._inicio_arraste = None

    def ponto_da_tela(self, x, y):
        w, h = self._tamanho()
        cx, cy = latlon_para_pixel(self.lat, self.lon, self.zoom)
        return pixel_para_latlon(cx + x - w / 2.0, cy + y - h / 2.0, self.zoom)

    def tela_do_ponto(self, lat, lon):
        w, h = self._tamanho()
        cx, cy = latlon_para_pixel(self.lat, self.lon, self.zoom)
        px, py = latlon_para_pixel(lat, lon, self.zoom)
        return px - cx + w / 2.0, py - cy + h / 2.0

    def _tamanho(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            w, h = int(self.cget("width")), int(self.cget("height"))
        return w, h

    # ---------------- desenho ----------------
    def redesenhar(self):
        if self._redesenho is None and self._vivo:
            self._redesenho = self.after_idle(self._desenhar)

    def _desenhar(self):
        self._redesenho = None
        if not self._vivo:
            return
        t = self.tema
        self.delete("all")
        w, h = self._tamanho()
        cx, cy = latlon_para_pixel(self.lat, self.lon, self.zoom)
        x0, y0 = cx - w / 2.0, cy - h / 2.0
        n = 2 ** self.zoom
        faltando = 0
        for ty in range(int(math.floor(y0 / TAM_TILE)), int(math.floor((y0 + h) / TAM_TILE)) + 1):
            if ty < 0 or ty >= n:
                continue
            for tx in range(int(math.floor(x0 / TAM_TILE)), int(math.floor((x0 + w) / TAM_TILE)) + 1):
                px, py = tx * TAM_TILE - x0, ty * TAM_TILE - y0
                chave = (self.fonte, self.zoom, tx % n, ty)
                imagem = self._imagens.get(chave)
                if imagem is not None:
                    self.create_image(px, py, image=imagem, anchor="nw")
                    continue
                faltando += 1
                self.create_rectangle(px, py, px + TAM_TILE, py + TAM_TILE,
                                      outline=t.get("ui_borda", "#333"),
                                      fill=t.get("ui_painel", "#222"))
                if chave not in self._pedidos and chave not in self._falhas:
                    self._pedidos.add(chave)
                    self._fila_entrada.put(chave)

        if self.marcador:
            self._desenhar_pino(*self.tela_do_ponto(*self.marcador))
        # mira no centro, discreta
        self.create_line(w / 2 - 6, h / 2, w / 2 + 6, h / 2, fill="#ffffff", width=1)
        self.create_line(w / 2, h / 2 - 6, w / 2, h / 2 + 6, fill="#ffffff", width=1)

        credito = FONTES[self.fonte]["credito"]
        fundo = self.create_text(w - 6, h - 5, text=credito, anchor="se", fill="#202020",
                                 font=("TkDefaultFont", 7))
        caixa = self.bbox(fundo)
        if caixa:
            self.create_rectangle(caixa[0] - 4, caixa[1] - 2, caixa[2] + 2, caixa[3] + 1,
                                  fill="#f2f2f2", outline="")
            self.tag_raise(fundo)
        self.create_text(8, h - 5, text="zoom %d" % self.zoom, anchor="sw", fill="#ffffff",
                         font=("TkDefaultFont", 8))
        if faltando and self._falhas and self.erro_rede:
            self.create_rectangle(0, 0, w, 26, fill=t.get("ui_painel", "#222"), outline="")
            self.create_text(10, 13, anchor="w", fill=t.get("ui_aviso", "#d7a143"),
                             font=("TkDefaultFont", 8),
                             text="Sem conexao com o servidor do mapa. A coordenada "
                                  "pode ser digitada ou colada ao lado.")

    def _desenhar_pino(self, x, y):
        cor = self.tema.get("ui_acento", "#4ad0e4")
        # gota: circulo + ponta embaixo, com contorno escuro pra ler no satelite
        self.create_oval(x - 5, y - 2, x + 5, y + 2, fill="#000000", outline="", stipple="gray50")
        self.create_polygon(x, y, x - 9, y - 16, x + 9, y - 16, fill=cor, outline="#0b0b0b",
                            width=1.5, tags=("pino",))
        self.create_oval(x - 11, y - 33, x + 11, y - 11, fill=cor, outline="#0b0b0b",
                         width=1.5, tags=("pino",))
        self.create_oval(x - 4, y - 26, x + 4, y - 18, fill="#0b0b0b", outline="",
                         tags=("pino",))
