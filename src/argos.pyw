r"""argos.pyw - a JANELA do Argos, o gravador de jogo leve (Argos e' o vigia de cem olhos
da mitologia grega), no jeito do OBS.

Em cima, a previa da tela (960x540, 15 quadros por segundo), que cresce com a janela.
F11 ou clique duplo nela = tela cheia so com a previa (Esc sai). Embaixo, dois cartoes:
AUDIO (Faixa 1 e Faixa 2 livres: cada uma grava o
programa que voce escolher, ou o PC todo, e da pra RENOMEAR; mais o Microfone) e
GRAVACAO (botao, tempo, quadros, qualidade, pasta, previa). Atalho global
Ctrl + Alt + R liga e desliga de dentro do jogo.

DESIGN, em CustomTkinter 6 (CC0, ~1,7 MB, mesmo Python, sem navegador por tras):
- acento CIANO parado e BRASA gravando: o app inteiro troca de cor ao gravar, e a barra
  fina na lateral dos paineis (o "montante") acende. Parar e' contorno, sem vermelho:
  vermelho fica pra erro de verdade. Mudo e' cinza.
- texto em 3 niveis (titulo, rotulo em CAIXA-ALTA, valor), fontes Inter e Space Grotesk,
  e numero que muda (tempo, dB) em fonte de largura fixa, pra nao tremer.
Por que NAO virou pagina web numa janela (pywebview): o Edge por tras custaria
~100-200 MB de memoria, e o objetivo e' ser leve.

O motor e' o gravar_jogo.py (classes Audio e Captura). Ver o docstring dele pros
numeros medidos de CPU, cor, qualidade e as armadilhas de som e sincronia.

Rodando do codigo: pythonw.exe argos.pyw (pythonw de verdade; o pythonw de venv do uv
abre um console por tras). Empacotado: Argos.exe, montado pelo empacotar.py. As opcoes ficam
em %APPDATA%\Argos\config.json.
"""
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

def recurso(*partes):
    """Acha fonte, icone e ffmpeg tanto rodando do codigo (../assets) quanto empacotado
    (tudo ao lado do programa)."""
    for base in (AQUI, os.path.join(AQUI, "..", "assets"), os.path.join(AQUI, "..")):
        c = os.path.join(base, *partes)
        if os.path.exists(c):
            return os.path.abspath(c)
    return os.path.join(AQUI, *partes)

# Inter + Space Grotesk (licenca OFL, ver assets/fontes/LEIAME.md). Carregadas so pra
# este processo, sem instalar nada no Windows. Tem que ser ANTES do Tk abrir.
_FONTES = recurso("fontes")
if os.path.isdir(_FONTES):
    for _n in os.listdir(_FONTES):
        if _n.endswith(".ttf"):
            ctypes.windll.gdi32.AddFontResourceExW(os.path.join(_FONTES, _n), 0x10, 0)
import gravar_jogo as motor  # noqa: E402  (poe as libs no sys.path)
import customtkinter as ctk  # noqa: E402
from PIL import Image, ImageTk  # noqa: E402

ICONE = recurso("icones", "argos.ico")
# ARGOS_CONFIG troca o arquivo (testes, ou dois perfis); sem ela, o de sempre
CONFIG = os.environ.get("ARGOS_CONFIG") or os.path.join(os.environ.get("APPDATA", "."), "Argos", "config.json")
CONFIG_VELHO = os.path.join(os.environ.get("APPDATA", "."), "GravadorJogo", "config.json")
PADRAO = {"pasta": os.path.join(os.path.expanduser("~"), "Videos", "Argos"),
          "fps": 60, "qualidade": "Alta", "previa": True,
          "monitor": 0, "altura": None, "familia": None, "codec": "h264", "formato": "mp4",
          "codificadores": None,
          "mic": None, "vol_mic": 100, "mudo_mic": True,
          "faixas": [{"fonte": None, "vol": 100, "mudo": True, "nome": None},
                     {"fonte": None, "vol": 100, "mudo": True, "nome": None}]}
# qualidade constante (CQP, como o OBS): menor = melhor. Tamanho medido em 08/10/2026:
# tela parada ~0,3 GB/h em qualquer nivel; imagem de jogo nitida se mexendo, o teto abaixo
QUALIDADE = motor.NIVEIS
# so medido com AMD H.264 1366x768 60 fps; nas outras combinacoes o texto diz que varia
GB_HORA = {"Leve": "até ~2 GB por hora", "Normal": "até ~3 GB por hora",
           "Alta": "até ~5 GB por hora", "Máxima": "o maior arquivo"}
ALTURAS = (2160, 1440, 1080, 900, 720)
FAMILIA_PREFERIDA = ("nvidia", "amd", "intel", "cpu")  # placa de video primeiro: leve pro jogo

# ---- cores e medidas. Paleta escura com acento ciano/brasa. As regras do desenho:
#  1. LUZ = TRABALHO: so o que esta trabalhando acende (o "montante", a barra fina na
#     lateral do painel, acende quando grava).
#  2. A BASE E' PRETO E BRANCO: fundo e letra neutros, a cor fica pra estado.
#  4. AZUL E BRASA NUNCA SE ENCOSTAM SATURADOS: parado o acento e' AZUL; gravando o app
#     inteiro troca pra BRASA.
#  - PARAR nao e' vermelho: parar nao destroi nada; vermelho fica pra erro de verdade.
FUNDO = "#08090B"        # --fundo
FUNDO_2 = "#0E1014"      # --fundo-2: faixa do titulo e a janela de configuracao
CARTAO = "#14171C"       # --superficie
CAMPO = "#1B1F26"        # --superficie-alta: controles
CAMPO_2 = "#242a33"      # hover dos controles (um degrau acima)
BORDA = "#353D49"        # --borda: divisoria, 1,64:1 sobre o cartao (tem que ser vista)
BORDA_FORTE = "#626F7F"  # --borda-forte: contorno de controle, 3:1+
TEXTO = "#F4F6F9"
TEXTO_2 = "#AEB7C4"
TEXTO_3 = "#8B95A3"      # 5,92:1 sobre o cartao (medido pelo desenho)
AZUL, AZUL_FORTE, AZUL_FUNDO, SOBRE_AZUL, TRILHO_AZUL = "#4CD4FF", "#22BFF0", "#153E50", "#03181F", "#1A4A60"
BRASA, BRASA_FORTE, BRASA_FUNDO, SOBRE_BRASA, TRILHO_BRASA = "#FF7A2F", "#F2610F", "#582C0F", "#1E0B02", "#6E3A12"
ALERTA = "#F5C518"
ERRO = "#FFB3A8"
CHAVE_OFF = "#6B7583"
# o acento em vigor (troca inteiro ao gravar): (vivo, forte, fundo aceso, texto sobre, trilho)
ACENTO_PARADO = (AZUL, AZUL_FORTE, AZUL_FUNDO, SOBRE_AZUL, TRILHO_AZUL)
ACENTO_GRAVANDO = (BRASA, BRASA_FORTE, BRASA_FUNDO, SOBRE_BRASA, TRILHO_BRASA)
# nomes antigos, usados no resto do arquivo
DESTAQUE, DESTAQUE_FUNDO, DESTAQUE_FUNDO_2 = AZUL, AZUL_FUNDO, "#1B4E64"
GRAVAR, GRAVAR_HOVER = BRASA, BRASA_FORTE
# medidor: trilho neutro; nivel normal no acento, alto em alerta, estouro em erro
ZONAS = ((0, .667, AZUL, CAMPO), (.667, .85, ALERTA, CAMPO), (.85, 1, ERRO, CAMPO))

F_TITULO = ("Space Grotesk SemiBold", 17)    # --t-titulo 17px
F_MARCA = ("Space Grotesk SemiBold", 15)
F_BOTAO = ("Space Grotesk SemiBold", 15)     # botao principal: fonte de titulo, 14-15px
F_NOME = ("Inter SemiBold", 13)
F_TEXTO = ("Inter", 13)                      # --t-corpo 12,5px
F_ROTULO = ("Inter Medium", 11)              # --t-rotulo 11px, em CAIXA-ALTA
F_NUM = ("Cascadia Mono", 11)                # numero que muda: largura fixa, nao treme
F_TEMPO = ("Cascadia Mono", 28)              # (Inter e Space Grotesk tem digito de largura variavel, medido)
F_ICONE = ("Segoe Fluent Icons", 14)
ICO_SOM, ICO_MUDO, ICO_EDITAR = "\uE767", "\uE74F", "\uE70F"

RAIO_CARTAO, RESPIRO, RAIO_CONTROLE = 10, 12, 6   # --raio 10, --raio-p 6
MONTANTE = 3                                      # --montante: a barra fina do painel
ALTURA_CONTROLE = 36                              # --altura-controle


def ler_config():
    try:  # o programa ja se chamou "Gravador de Jogo": aproveita a configuracao velha
        with open(CONFIG if os.path.exists(CONFIG) else CONFIG_VELHO, encoding="utf-8") as f:
            c = {**PADRAO, **json.load(f)}
    except (OSError, ValueError):
        c = json.loads(json.dumps(PADRAO))
    for i, fx in enumerate(c["faixas"]):  # config velha nao tinha 'nome'
        c["faixas"][i] = {**PADRAO["faixas"][0], **fx}
    if c.get("qualidade") not in QUALIDADE:
        c["qualidade"] = "Alta"
    if c.get("formato") not in motor.FORMATOS:
        c["formato"] = "mp4"
    return c


def salvar_config(c):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


class Atalho(threading.Thread):
    """Ctrl + Alt + R global. RegisterHotKey exige o laco de mensagens na MESMA thread
    que registrou, por isso mora numa thread propria. Avisa a janela por fila."""

    def __init__(self, fila):
        super().__init__(daemon=True)
        self.fila = fila
        self.ok = None

    def run(self):
        u32 = ctypes.windll.user32
        self.ok = bool(u32.RegisterHotKey(
            None, 1, motor.MOD_CONTROL | motor.MOD_ALT | motor.MOD_NOREPEAT, motor.VK_R))
        if not self.ok:
            return
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == motor.WM_HOTKEY:
                self.fila.put(("atalho",))


def botao_neutro(pai, texto, comando, **kw):
    """Botao secundario do desenho: so contorno, o preenchimento e' do principal."""
    kw.setdefault("height", 34)
    return ctk.CTkButton(pai, text=texto, command=comando, font=F_TEXTO,
                         corner_radius=RAIO_CONTROLE, fg_color="transparent", hover_color=CAMPO,
                         border_width=1, border_color=BORDA_FORTE,
                         text_color=TEXTO_2, text_color_disabled=TEXTO_3, **kw)


def rotulo(pai, texto, **kw):
    """O .rotulo do desenho: CAIXA-ALTA, 11 px, texto-3."""
    return ctk.CTkLabel(pai, text=texto.upper(), font=F_ROTULO, text_color=TEXTO_3, **kw)


class Fonte:
    """Uma linha do mixer: nome (renomeavel nas faixas), o que grava, medidor,
    volume e mudo."""

    def __init__(self, pai, padrao, nome, opcoes, escolhido, vol, mudo, ao_mudar,
                 listar=None, renomeavel=False, ao_renomear=None):
        self.padrao, self.nome = padrao, nome
        self.ao_mudar, self.listar, self.ao_renomear = ao_mudar, listar, ao_renomear
        self.mostrado = 0.0
        self.mudo = mudo
        self.cor = AZUL

        f = self.quadro = ctk.CTkFrame(pai, fg_color="transparent")
        f.pack(fill="x", pady=(0, 6))
        # 2 linhas por fonte, como o mixer do OBS: [nome][o que grava][mudo][volume][%]
        # e embaixo o medidor + dB. A versao de 3 linhas comia ~110 px de altura da previa.
        f.grid_columnconfigure(0, minsize=150)
        f.grid_columnconfigure(3, weight=1)

        topo = ctk.CTkFrame(f, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="w")
        self.l_nome = ctk.CTkLabel(topo, text=self._rotulo(), font=F_NOME, text_color=TEXTO)
        self.l_nome.pack(side="left")
        self.b_editar = None
        if renomeavel:
            self.b_editar = ctk.CTkButton(topo, text=ICO_EDITAR, font=(F_ICONE[0], 11),
                                          width=24, height=24, corner_radius=RAIO_CONTROLE,
                                          fg_color="transparent", hover_color=CAMPO,
                                          text_color=TEXTO_3, command=self.renomear)
            self.b_editar.pack(side="left", padx=(4, 0))
            self.l_nome.bind("<Double-Button-1>", lambda e: self.renomear())
        self.e_nome = None
        self.v_ap = tk.StringVar(value=escolhido or "")
        self.menu = ctk.CTkOptionMenu(
            f, variable=self.v_ap, values=opcoes or [""], width=190, height=28,
            corner_radius=RAIO_CONTROLE, font=F_ROTULO, dropdown_font=F_ROTULO,
            fg_color=CAMPO, button_color=CAMPO, button_hover_color=CAMPO_2,
            text_color=TEXTO, dropdown_fg_color=CARTAO, dropdown_hover_color=CAMPO_2,
            dropdown_text_color=TEXTO, dynamic_resizing=False,
            command=lambda v: self.ao_mudar(self, aparelho=True))
        self.menu.grid(row=0, column=1, sticky="w")
        if not escolhido:
            self.menu.set("Escolha o que gravar…" if listar else "")

        self.b_mudo = ctk.CTkButton(f, text="", font=F_ICONE, width=30, height=28,
                                    corner_radius=RAIO_CONTROLE, fg_color="transparent",
                                    hover_color=CAMPO, command=self.alternar_mudo)
        self.b_mudo.grid(row=0, column=2, padx=(10, 2))
        self.v_vol = tk.DoubleVar(value=vol)
        self.escala = ctk.CTkSlider(f, from_=0, to=100, variable=self.v_vol, height=16,
                                    progress_color=DESTAQUE, button_color=TEXTO,
                                    button_hover_color="#ffffff", fg_color=CAMPO,
                                    command=lambda v: self._vol_mudou())
        self.escala.grid(row=0, column=3, sticky="ew", padx=(2, 8))
        self.l_vol = ctk.CTkLabel(f, text="", font=F_NUM, text_color=TEXTO_2, width=64, anchor="e")
        self.l_vol.grid(row=0, column=4, sticky="e")

        self.medidor = tk.Canvas(f, height=6, bg=CAMPO, highlightthickness=0, bd=0)
        self.medidor.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.db = ctk.CTkLabel(f, text="−∞ dB", font=F_NUM, text_color=TEXTO_3, width=64,
                               height=14, anchor="e")
        self.db.grid(row=1, column=4, sticky="e", pady=(6, 0))
        self._faixas = []
        for ini, fim, cor, apagada in ZONAS:
            fundo = self.medidor.create_rectangle(0, 0, 0, 6, fill=apagada, width=0)
            item = self.medidor.create_rectangle(-9, -9, -9, -9, fill=cor, width=0)
            self._faixas.append((ini, fim, fundo, item))

        self._pintar_mudo()
        self._pintar_vol()

    def _rotulo(self):
        return self.nome or self.padrao

    # ---- renomear (so Faixa 1 e 2)
    def renomear(self):
        if self.e_nome or not self.b_editar:
            return
        self.l_nome.pack_forget()
        self.b_editar.pack_forget()
        self.e_nome = ctk.CTkEntry(self.l_nome.master, width=160, height=26, font=F_NOME,
                                   corner_radius=RAIO_CONTROLE, fg_color=CAMPO,
                                   border_color=TEXTO_3, text_color=TEXTO,
                                   placeholder_text=self.padrao)
        self.e_nome.pack(side="left")
        if self.nome:
            self.e_nome.insert(0, self.nome)
        self.e_nome.focus_set()
        self.e_nome.bind("<Return>", lambda e: self._fim_renomear(True))
        self.e_nome.bind("<Escape>", lambda e: self._fim_renomear(False))
        self.e_nome.bind("<FocusOut>", lambda e: self._fim_renomear(True))

    def _fim_renomear(self, salvar):
        if not self.e_nome:
            return
        if salvar:
            novo = self.e_nome.get().strip()[:40]
            self.nome = novo or None
        e, self.e_nome = self.e_nome, None
        e.destroy()
        self.l_nome.configure(text=self._rotulo())
        self.l_nome.pack(side="left")
        self.b_editar.pack(side="left", padx=(4, 0))
        if salvar and self.ao_renomear:
            self.ao_renomear(self)

    # ---- volume e mudo
    def _vol_mudou(self):
        self._pintar_vol()
        self.ao_mudar(self)

    def _pintar_vol(self):
        self.l_vol.configure(text=f"{self.v_vol.get():.0f}%")

    def alternar_mudo(self):
        self.mudo = not self.mudo
        self._pintar_mudo()
        self.ao_mudar(self)

    def desmutar(self):
        self.mudo = False
        self._pintar_mudo()

    def _pintar_mudo(self):
        # mudo e' estado, nao perigo: cinza, nao vermelho
        self.b_mudo.configure(text=ICO_MUDO if self.mudo else ICO_SOM,
                              text_color=TEXTO_3 if self.mudo else TEXTO)
        self.escala.configure(progress_color=BORDA if self.mudo else self.cor)

    def pintar_acento(self, cor):
        self.cor = cor
        self.medidor.itemconfig(self._faixas[0][3], fill=cor)
        self._pintar_mudo()

    def escolhido(self):
        v = self.v_ap.get()
        return None if (not v or v.startswith("Escolha")) else v

    def medir(self, pico):
        db = 20 * math.log10(pico) if pico > 1e-5 else -100
        alvo = min(1.0, max(0.0, (db + 60) / 60))
        self.mostrado = max(alvo, self.mostrado - 0.04)
        larg = int(self.medidor.winfo_width())
        for ini, fim, fundo, item in self._faixas:
            a, b = ini * larg, min(self.mostrado, fim) * larg
            self.medidor.coords(fundo, a, 0, fim * larg, 6)
            # retangulo de largura zero ainda desenha um risco de 1 px: some com ele
            self.medidor.coords(item, *((a, 0, b, 6) if b > a else (-9, -9, -9, -9)))
        self.db.configure(text="−∞ dB" if self.mudo or db <= -60 else f"{db:5.1f} dB")


class Configuracoes(ctk.CTkToplevel):
    """Todas as opcoes de gravacao, numa janela so. So mostra o que a maquina aguenta:
    placa testada de verdade, 120/144 fps so com monitor dessa taxa, resolucao so menor."""

    def __init__(self, app):
        super().__init__(app.r, fg_color=FUNDO_2)
        self.app = app
        self.title("Argos · Configurar gravação")
        # cabe no monitor de 768 px de altura com a barra de tarefas (o rodape ja foi cortado)
        self.geometry("540x640+%d+%d" % (app.r.winfo_rootx() + 80, max(8, app.r.winfo_rooty() - 20)))
        self.resizable(False, False)
        self.transient(app.r)
        self.after(200, self.grab_set)
        if os.path.exists(ICONE):
            self.after(250, lambda: self.iconbitmap(os.path.abspath(ICONE)))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        # a .caixa do desenho: fundo-2 e contorno FORTE (e' janela por cima de janela)
        self.corpo = ctk.CTkFrame(self, fg_color=FUNDO_2, corner_radius=RAIO_CARTAO,
                                  border_width=1, border_color=BORDA_FORTE)
        self.corpo.pack(fill="both", expand=True, padx=16, pady=16)
        self.recarregar()

    # ---- pecas
    def _secao(self, texto):
        rotulo(self.dentro, texto).pack(anchor="w", pady=(12, 2))

    def _linha(self, rotulo):
        lin = ctk.CTkFrame(self.dentro, fg_color="transparent")
        lin.pack(fill="x", pady=3)
        ctk.CTkLabel(lin, text=rotulo, font=F_TEXTO, text_color=TEXTO_2, width=150, anchor="w").pack(side="left")
        return lin

    def _menu(self, lin, valores, atual, ao_mudar):
        m = ctk.CTkOptionMenu(lin, values=valores, width=250, height=30, corner_radius=RAIO_CONTROLE,
                              font=F_ROTULO, dropdown_font=F_ROTULO, fg_color=CAMPO, button_color=CAMPO,
                              button_hover_color=CAMPO_2, text_color=TEXTO, dropdown_fg_color=CARTAO,
                              dropdown_hover_color=CAMPO_2, dropdown_text_color=TEXTO,
                              dynamic_resizing=False, command=ao_mudar)
        m.set(atual)
        m.pack(side="right")
        return m

    def _segmentos(self, lin, valores, atual, ao_mudar):
        sb = ctk.CTkSegmentedButton(lin, values=valores, height=30, corner_radius=RAIO_CONTROLE,
                                    font=F_ROTULO, fg_color=CAMPO, unselected_color=CAMPO,
                                    unselected_hover_color=CAMPO_2, selected_color=DESTAQUE_FUNDO,
                                    selected_hover_color=DESTAQUE_FUNDO_2, text_color=TEXTO,
                                    command=ao_mudar, width=250)
        sb.set(atual)
        sb.pack(side="right")
        return sb

    def _dica(self, texto):
        ctk.CTkLabel(self.dentro, text=texto, font=F_ROTULO, text_color=TEXTO_3, justify="left",
                     anchor="w", wraplength=450).pack(anchor="w", fill="x", pady=(0, 2))

    # ---- montagem (refeita a cada mudanca: as opcoes dependem umas das outras)
    def recarregar(self):
        for w in self.corpo.winfo_children():
            w.destroy()
        self.dentro = ctk.CTkFrame(self.corpo, fg_color="transparent")
        self.dentro.pack(fill="both", expand=True, padx=RESPIRO + 10, pady=(6, RESPIRO + 6))
        ctk.CTkLabel(self.dentro, text="Configurar gravação", font=F_TITULO, text_color=TEXTO).pack(
            anchor="w", pady=(6, 0))
        a, c = self.app, self.app.c
        cods = c.get("codificadores")

        self._secao("Tela")
        mons = {f"Monitor {i + 1}  ·  {w}x{h}": i for i, w, h in a.monitores}
        self._menu(self._linha("Monitor"), list(mons),
                   next(k for k, v in mons.items() if v == c["monitor"]),
                   lambda v: self._mudou(monitor=mons[v]))
        _, w, h = a.monitor_atual()
        alts = {f"Do monitor  ·  {w}x{h}": None}
        alts.update({f"{x}p  ·  {round(w * x / h) // 2 * 2}x{x}": x for x in ALTURAS if x < h})
        atual_alt = c.get("altura") if c.get("altura") in alts.values() else None
        self._menu(self._linha("Resolução"), list(alts),
                   next(k for k, v in alts.items() if v == atual_alt),
                   lambda v: self._mudou(altura=alts[v]))
        fpss = [f"{x}" for x in a.opcoes_fps()]
        if str(c["fps"]) not in fpss:
            c["fps"] = 60
        self._segmentos(self._linha("Quadros por segundo"), fpss, str(c["fps"]),
                        lambda v: self._mudou(fps=int(v)))
        if a.taxa_monitor() <= 60:
            self._dica(f"Este monitor é de {a.taxa_monitor()} Hz: mais de 60 fps só aparece com monitor mais rápido.")

        self._secao("Vídeo")
        if not cods:
            self._dica("Testando a placa de vídeo…")
        else:
            nomes = {motor.CODIFICADORES[f][0]: f for f in FAMILIA_PREFERIDA if f in cods}
            self._menu(self._linha("Codificar com"), list(nomes),
                       motor.CODIFICADORES[c["familia"]][0], lambda v: self._mudou(familia=nomes[v]))
            if c["familia"] == "cpu":
                self._dica("O processador comprime melhor, mas pesa no jogo. Use se não tiver placa de vídeo.")
            codecs = {motor.CODECS[k]: k for k in cods[c["familia"]]}
            self._segmentos(self._linha("Formato do vídeo"), list(codecs), motor.CODECS[c["codec"]],
                            lambda v: self._mudou(codec=codecs[v]))
            self._dica("H.264 abre em qualquer programa.  H.265: arquivo bem menor.  "
                       "AV1: menor ainda, mas programa antigo pode não abrir.")
        self._segmentos(self._linha("Qualidade"), list(QUALIDADE), c["qualidade"],
                        lambda v: self._mudou(qualidade=v))

        self._secao("Arquivo")
        self._segmentos(self._linha("Tipo de arquivo"), [x.upper() for x in motor.FORMATOS],
                        c["formato"].upper(), lambda v: self._mudou(formato=v.lower()))
        self._dica("MP4 abre em tudo.  MOV: o mais seguro no DaVinci com várias trilhas de som.  "
                   "MKV aceita qualquer formato.")
        lin = self._linha("Pasta")
        botao_neutro(lin, "Mudar", self._mudar_pasta, width=70, height=30).pack(side="right")
        ctk.CTkLabel(lin, text=a._pasta_curta(), font=F_TEXTO, text_color=TEXTO, anchor="e").pack(
            side="right", padx=(0, 8))

        rodape = ctk.CTkFrame(self.dentro, fg_color="transparent")
        rodape.pack(fill="x", side="bottom", pady=(10, 0))
        ctk.CTkButton(rodape, text="Pronto", command=self.destroy, height=ALTURA_CONTROLE, width=110,
                      corner_radius=RAIO_CONTROLE, font=F_BOTAO, fg_color=AZUL,
                      hover_color=AZUL_FORTE, text_color=SOBRE_AZUL).pack(side="right")
        botao_neutro(rodape, "Testar a placa de novo", self._redetectar, height=ALTURA_CONTROLE).pack(side="left")

    def _mudou(self, **novo):
        c = self.app.c
        if "familia" in novo and c.get("codificadores"):
            cods = c["codificadores"][novo["familia"]]
            if c["codec"] not in cods:
                novo["codec"] = cods[0]
        if novo.get("codec") == "av1" and c["formato"] == "mov":
            novo["formato"] = "mp4"  # AV1 dentro de MOV nao e' padrao
        if novo.get("formato") == "mov" and c["codec"] == "av1":
            novo["formato"] = "mp4"
        monitor_mudou = "monitor" in novo and novo["monitor"] != c["monitor"]
        c.update(novo)
        if monitor_mudou:
            c["altura"] = None
            if c["fps"] not in self.app.opcoes_fps():
                c["fps"] = 60
        self.app.aplicar_config(monitor_mudou)
        self.recarregar()

    def _mudar_pasta(self):
        p = filedialog.askdirectory(parent=self, initialdir=self.app.c["pasta"], title="Onde salvar os vídeos")
        if p:
            self.app.c["pasta"] = os.path.normpath(p)
            self.app.aplicar_config()
            self.recarregar()

    def _redetectar(self):
        self.app.c["codificadores"] = None
        self.app._detectar(forcar=True)
        self.recarregar()


class App:
    def __init__(self):
        self.c = ler_config()
        self.eventos = queue.Queue()
        self.quadro = None
        self.ocupado = False
        self.inicio = None
        self.cheia = False
        self._fechando = False
        self._ultima_lista = 0.0

        ctk.set_appearance_mode("dark")
        r = self.r = ctk.CTk(fg_color=FUNDO)
        self._fontes_reserva(r)
        r.title("Argos")
        r.minsize(860, 600)
        r.geometry("1180x700+60+16")  # cabe no monitor de 1366x768 com a barra de tarefas
        r.protocol("WM_DELETE_WINDOW", self.fechar)
        if os.path.exists(ICONE):
            r.iconbitmap(default=os.path.abspath(ICONE))
            r.after(250, lambda: r.iconbitmap(os.path.abspath(ICONE)))  # o ctk troca o icone no inicio

        # FAIXA DE TITULO, como o .topo do desenho: 52 px, fundo-2, linha embaixo,
        # marca a esquerda e o estado a direita.
        self.topo = ctk.CTkFrame(r, fg_color=FUNDO_2, height=52, corner_radius=0)
        self.topo.pack(side="top", fill="x")
        self.topo.pack_propagate(False)
        ctk.CTkFrame(r, fg_color=BORDA, height=1, corner_radius=0).pack(side="top", fill="x")
        self.linha_topo = r.pack_slaves()[-1]
        marca = recurso("icones", "argos.png")
        if os.path.exists(marca):
            img = ctk.CTkImage(Image.open(marca), size=(22, 22))
            ctk.CTkLabel(self.topo, image=img, text="").pack(side="left", padx=(20, 10))
        ctk.CTkLabel(self.topo, text="Argos", font=F_MARCA, text_color=TEXTO).pack(side="left")
        ctk.CTkLabel(self.topo, text="gravador de jogo", font=F_TEXTO, text_color=TEXTO_3).pack(side="left", padx=(10, 0))
        self.estado = ctk.CTkLabel(self.topo, text="Pronto", font=F_TEXTO, text_color=TEXTO_2, anchor="e")
        self.estado.pack(side="right", padx=(6, 20))
        self.bolinha = ctk.CTkLabel(self.topo, text="●", font=F_ROTULO, text_color=TEXTO_3, width=12)
        self.bolinha.pack(side="right")

        # GRADE: esquerda = previa (cresce) + Audio embaixo; direita = Gravacao, coluna
        # inteira. Primeira versao empilhava tudo e a previa sobrava com ~180 px de altura.
        self.barra = ctk.CTkFrame(r, fg_color=FUNDO, height=30, corner_radius=0)
        self.barra.pack(side="bottom", fill="x", padx=20, pady=(0, 8))
        self.corpo = ctk.CTkFrame(r, fg_color=FUNDO, corner_radius=0)
        self.corpo.pack(fill="both", expand=True, padx=20, pady=(16, 8))
        self.corpo.grid_columnconfigure(0, weight=1)
        self.corpo.grid_rowconfigure(0, weight=1)

        # ---------------- previa (escala pra caber, sempre 16:9)
        self.moldura = ctk.CTkFrame(self.corpo, fg_color="#000000", corner_radius=RAIO_CARTAO)
        self.moldura.grid(row=0, column=0, sticky="nsew")
        self.tela = tk.Canvas(self.moldura, width=576, height=324, bg="#000000",
                              highlightthickness=0, bd=0)
        self.tela.pack(fill="both", expand=True, padx=RESPIRO // 2, pady=RESPIRO // 2)
        self.tam_foto = (576, 324)
        self.origem = (0, 0)
        self.foto = ImageTk.PhotoImage("RGB", self.tam_foto)
        self.img = self.tela.create_image(0, 0, image=self.foto, anchor="nw")
        self.aviso_tela = self.tela.create_text(288, 162, text="", fill=TEXTO_2, font=F_TEXTO)
        self.selo_fundo = self.tela.create_rectangle(0, 0, 0, 0, fill="#000000", outline="", state="hidden")
        self.selo = self.tela.create_text(0, 0, text="●  REC", fill=BRASA,
                                          font=("Space Grotesk SemiBold", 11), state="hidden")
        self.tela.bind("<Configure>", self._tela_mudou)
        self.tela.bind("<Double-Button-1>", lambda e: self.tela_cheia())
        r.bind("<F11>", lambda e: self.tela_cheia())
        r.bind("<Escape>", lambda e: self.tela_cheia(False))

        # ---------------- cartao AUDIO
        audio = self._cartao(self.corpo, "Áudio")
        self.c_audio = audio.master
        self.c_audio.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        _, entradas, _, p_mic = motor.listar_audio()
        self.f_faixas = []
        programas = self._listar_programas()
        for i, cf in enumerate(self.c["faixas"][:2]):
            self.f_faixas.append(Fonte(
                audio, f"Faixa {i + 1}", cf.get("nome"), programas, cf.get("fonte"),
                cf.get("vol", 100), cf.get("mudo", True), self.audio_mudou,
                listar=self._listar_programas, renomeavel=True, ao_renomear=self._renomeou))
        self.f_mic = Fonte(audio, "Microfone", None, entradas, self.c["mic"] or p_mic,
                           self.c["vol_mic"], self.c["mudo_mic"], self.audio_mudou)
        self.f_mic.quadro.pack_configure(pady=0)
        for fa in self.f_faixas:
            fa.quadro.pack_configure(pady=(0, 10))

        # ---------------- cartao GRAVACAO
        ctrl = self._cartao(self.corpo, "Gravação", largura=270)
        self.c_ctrl = ctrl.master
        self.c_ctrl.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(12, 0))
        # botao principal do desenho: preenchido no acento, letra ESCURA por cima
        # (texto claro sobre o ciano daria 1,38:1)
        self.b_gravar = ctk.CTkButton(ctrl, text="●  Gravar", command=self.alternar, height=44,
                                      corner_radius=RAIO_CONTROLE, font=F_BOTAO,
                                      fg_color=AZUL, hover_color=AZUL_FORTE, text_color=SOBRE_AZUL,
                                      text_color_disabled=TEXTO_3, border_width=0)
        self.b_gravar.pack(fill="x")
        self.l_tempo = ctk.CTkLabel(ctrl, text="00:00:00", font=F_TEMPO, text_color=TEXTO_3)
        self.l_tempo.pack(anchor="w", pady=(10, 0))
        self.l_tam = ctk.CTkLabel(ctrl, text="", font=F_NUM, text_color=TEXTO_2, height=16)
        self.l_tam.pack(anchor="w")

        self.travaveis = []
        # resumo do que vai ser gravado; as opcoes moram na janela "Configurar gravacao"
        rotulo(ctrl, "Vai gravar").pack(anchor="w", pady=(14, 2))
        self.l_resumo = ctk.CTkLabel(ctrl, text="", font=F_TEXTO, text_color=TEXTO, justify="left", anchor="w")
        self.l_resumo.pack(anchor="w", fill="x")
        self.l_gb = ctk.CTkLabel(ctrl, text="", font=F_ROTULO, text_color=TEXTO_3, anchor="w")
        self.l_gb.pack(anchor="w")
        b = botao_neutro(ctrl, "Configurar gravação", self.abrir_config)
        b.pack(fill="x", pady=(10, 0))
        self.travaveis.append(b)

        self.v_previa = tk.BooleanVar(value=self.c["previa"])
        self.chave = ctk.CTkSwitch(ctrl, text="Mostrar prévia", variable=self.v_previa,
                                   command=self.previa_mudou, font=F_TEXTO, text_color=TEXTO_2,
                                   progress_color=TRILHO_AZUL, button_color=AZUL,
                                   button_hover_color=AZUL_FORTE, fg_color=CAMPO,
                                   switch_width=36, switch_height=18)
        self.chave.pack(anchor="w", pady=(14, 0))

        lin = ctk.CTkFrame(ctrl, fg_color="transparent")
        lin.pack(fill="x", pady=(12, 0))
        botao_neutro(lin, "Abrir pasta", self.abrir_pasta, width=10).pack(side="left", fill="x", expand=True)
        botao_neutro(lin, "Tela cheia", self.tela_cheia, width=10).pack(side="left", fill="x", expand=True, padx=(8, 0))

        # ---------------- barra de baixo: so as dicas (o estado mora no topo)
        ctk.CTkLabel(self.barra, text="F11 tela cheia   ·   Ctrl + Alt + R grava de dentro do jogo",
                     font=F_ROTULO, text_color=TEXTO_3).pack(side="right")

        # ---------------- motor
        self.audio = None
        self.iniciar_audio()
        self.monitores = motor.listar_monitores()
        if self.c["monitor"] >= len(self.monitores):
            self.c["monitor"] = 0
        self.taxas = motor.taxas_dos_monitores()
        self.cap = motor.Captura(self.c["monitor"], ao_quadro=self._novo_quadro)
        self.janela_config = None
        self._detectar()
        self.previa_mudou(salvar=False)
        self.atalho = Atalho(self.eventos)
        self.atalho.start()
        self.r.after(600, self._conferir_atalho)
        self.mostrar_relogio()
        self.tique()

    # ---------------------------------------------------------------- aparencia
    @staticmethod
    def _fontes_reserva(r):
        """Cascadia Mono nao vem no Windows (veio de outro programa no PC de quem fez) e
        Segoe Fluent Icons so existe no Windows 11. Sem elas: Consolas e Segoe MDL2 Assets,
        que existem em todo Windows 10 e 11 e tem os mesmos icones nos mesmos codigos."""
        global F_NUM, F_TEMPO, F_ICONE
        import tkinter.font as tkfont
        fams = set(tkfont.families(r))
        if "Cascadia Mono" not in fams:
            F_NUM, F_TEMPO = ("Consolas", F_NUM[1] + 1), ("Consolas", F_TEMPO[1] + 2)
        if "Segoe Fluent Icons" not in fams:
            F_ICONE = ("Segoe MDL2 Assets", F_ICONE[1])

    def _cartao(self, pai, titulo, largura=None):
        """Painel do desenho: superficie, borda que se ve (1,64:1) e o MONTANTE, a barra
        de 3 px na lateral, apagada em repouso e acesa enquanto grava."""
        caixa = ctk.CTkFrame(pai, fg_color=CARTAO, corner_radius=RAIO_CARTAO,
                             border_width=1, border_color=BORDA, **({"width": largura} if largura else {}))
        # tk.Frame e nao CTkFrame: o ctk proibe altura no place, e o montante precisa
        # de "altura do cartao menos os dois cantos arredondados"
        montante = tk.Frame(caixa, bg=BORDA, width=MONTANTE, bd=0, highlightthickness=0)
        montante.place(x=1, y=RAIO_CARTAO, relheight=1.0, height=-2 * RAIO_CARTAO)
        self.montantes = getattr(self, "montantes", []) + [montante]
        ctk.CTkLabel(caixa, text=titulo, font=F_TITULO, text_color=TEXTO).pack(
            anchor="w", padx=RESPIRO + 8, pady=(RESPIRO + 2, 8))
        dentro = ctk.CTkFrame(caixa, fg_color="transparent")
        dentro.pack(fill="both", expand=True, padx=RESPIRO + 8, pady=(0, RESPIRO + 4))
        return dentro

    def pintar_acento(self, gravando):
        """Regra 4 do desenho: o acento troca INTEIRO. Parado = azul; gravando = brasa,
        e os montantes acendem (regra 1, luz = trabalho)."""
        vivo, forte, fundo, sobre, trilho = ACENTO_GRAVANDO if gravando else ACENTO_PARADO
        for m in self.montantes:
            m.configure(bg=vivo if gravando else BORDA)
        for fa in self.f_faixas + [self.f_mic]:
            fa.pintar_acento(vivo)
        self.chave.configure(progress_color=trilho, button_color=vivo, button_hover_color=forte)
        if gravando:  # Parar em contorno, sem vermelho: parar nao destroi nada
            self.b_gravar.configure(text="■  Parar", fg_color="transparent", hover_color=CAMPO,
                                    text_color=TEXTO_2, border_width=1, border_color=BORDA_FORTE)
        else:
            self.b_gravar.configure(text="●  Gravar", fg_color=AZUL, hover_color=AZUL_FORTE,
                                    text_color=SOBRE_AZUL, border_width=0)

    # ---------------------------------------------------------------- opcoes de gravacao
    def _detectar(self, forcar=False):
        """Descobre que placa/formato roda nesta maquina (~1 s, uma vez; fica salvo)."""
        if self.c.get("codificadores") and not forcar:
            self._escolher_familia()
            return
        self.l_resumo.configure(text="Testando a placa de vídeo…")

        def ir():
            achados = motor.detectar_codificadores()
            self.eventos.put(("detectou", achados))

        threading.Thread(target=ir, daemon=True).start()

    def _escolher_familia(self):
        cods = self.c.get("codificadores") or {"cpu": ["h264"]}
        if self.c.get("familia") not in cods:
            self.c["familia"] = next(f for f in FAMILIA_PREFERIDA if f in cods)
        if self.c.get("codec") not in cods[self.c["familia"]]:
            self.c["codec"] = cods[self.c["familia"]][0]
        salvar_config(self.c)
        self.mostrar_resumo()

    def monitor_atual(self):
        return self.monitores[min(self.c["monitor"], len(self.monitores) - 1)]

    def taxa_monitor(self):
        _, w, h = self.monitor_atual()
        return self.taxas.get((w, h), 60) or 60

    def opcoes_fps(self):
        return [30, 60] + [f for f in (120, 144, 165, 240) if f <= self.taxa_monitor() + 1]

    def mostrar_resumo(self):
        _, w, h = self.monitor_atual()
        alt = self.c.get("altura")
        tam = f"{round(w * alt / h) // 2 * 2}x{alt}" if alt and alt < h else f"{w}x{h}"
        fam = self.c.get("familia") or "cpu"
        marca = {"amd": "AMD", "nvidia": "NVIDIA", "intel": "Intel", "cpu": "Processador"}[fam]
        self.l_resumo.configure(text=f"{tam}  ·  {self.c['fps']} fps\n"
                                     f"{marca}  ·  {motor.CODECS[self.c['codec']]}  ·  "
                                     f"{self.c['qualidade']}  ·  {self.c['formato'].upper()}")
        medido = fam == "amd" and self.c["codec"] == "h264"
        self.l_gb.configure(text=GB_HORA[self.c["qualidade"]] if medido else "o tamanho varia com o jogo")

    def abrir_config(self):
        if self.cap.gravando or self.ocupado:
            return
        if self.janela_config and self.janela_config.winfo_exists():
            self.janela_config.focus()
            return
        self.janela_config = Configuracoes(self)

    def aplicar_config(self, monitor_mudou=False):
        salvar_config(self.c)
        self.mostrar_resumo()
        if monitor_mudou:
            self.cap.monitor = self.c["monitor"]
            if self.v_previa.get():
                self.cap.desligar_previa()
                self.cap.ligar_previa()

    def _pasta_curta(self):
        p = self.c["pasta"]
        return p if len(p) <= 24 else "…" + p[-23:]

    def _estado(self, texto, cor=TEXTO_2, bolinha=TEXTO_3):
        self.estado.configure(text=texto, text_color=cor)
        self.bolinha.configure(text_color=bolinha)

    def _conferir_atalho(self):
        if self.atalho.ok is False:
            self._estado("Ctrl + Alt + R está ocupado por outro programa", ALERTA, ALERTA)

    # ---------------------------------------------------------------- audio
    def iniciar_audio(self):
        if self.audio:
            self.audio.parar()
        self.audio = motor.Audio(self.f_mic.escolhido(), n_faixas=len(self.f_faixas))
        self._aplicar_volumes()
        for fx, fa in zip(self.audio.faixas, self.f_faixas):
            fx.fonte, fx.mudo, fx.nome = fa.escolhido(), fa.mudo, fa.nome
        try:
            self.audio.iniciar()
        except Exception as e:
            self._estado(f"Som não abriu: {e}", ERRO, ERRO)
        self._avisar_faixas()

    def _aplicar_volumes(self):
        a = self.audio
        a.vol_mic, a.mudo_mic = self.f_mic.v_vol.get() / 100, self.f_mic.mudo
        for fx, fa in zip(a.faixas, self.f_faixas):
            fx.vol, fx.nome = fa.v_vol.get() / 100, fa.nome

    def _listar_programas(self):
        try:
            return [motor.TUDO_PC] + motor.som_de_programa.programas_com_som()
        except Exception:
            return [motor.TUDO_PC]

    def _atualizar_listas(self):
        """A lista de programas so muda quando um programa abre som; recarrega a cada 4 s."""
        lista = self._listar_programas()
        for fa in self.f_faixas:
            atual = fa.escolhido()
            fa.menu.configure(values=lista + ([atual] if atual and atual not in lista else []))

    def _avisar_faixas(self):
        for i, fx in enumerate(self.audio.faixas if self.audio else []):
            if fx.erro:
                self._estado(f"{self.f_faixas[i]._rotulo()}: {fx.erro}", ALERTA, ALERTA)

    def _renomeou(self, fonte):
        self._aplicar_volumes()
        self._salvar_audio()

    def audio_mudou(self, fonte, aparelho=False):
        if fonte in self.f_faixas and aparelho and fonte.mudo:
            fonte.desmutar()  # escolheu o que gravar: quer ouvir
        if aparelho and fonte is self.f_mic:
            if not self.cap.gravando:
                self.iniciar_audio()
        else:
            self._aplicar_volumes()
            if self.f_mic.mudo:
                self.audio.fechar_mic()
            else:
                self.audio.abrir_mic()
            for i, fa in enumerate(self.f_faixas):
                self.audio.definir_faixa(i, fa.escolhido(), fa.mudo)
            self._avisar_faixas()
        self._salvar_audio()

    def _salvar_audio(self):
        self.c.update(mic=self.f_mic.escolhido(), vol_mic=self.f_mic.v_vol.get(),
                      mudo_mic=self.f_mic.mudo,
                      faixas=[{"fonte": fa.escolhido(), "vol": fa.v_vol.get(), "mudo": fa.mudo,
                               "nome": fa.nome} for fa in self.f_faixas])
        salvar_config(self.c)

    # ---------------------------------------------------------------- opcoes

    def abrir_pasta(self):
        os.makedirs(self.c["pasta"], exist_ok=True)
        os.startfile(self.c["pasta"])

    def previa_mudou(self, salvar=True):
        ligada = self.v_previa.get()
        if ligada:
            self.cap.ligar_previa()
            self.tela.itemconfig(self.aviso_tela, text="")
        else:
            self.cap.desligar_previa()
            self.quadro = None
            self.foto.paste(Image.new("RGB", self.tam_foto, "#000000"))
            self.tela.itemconfig(self.aviso_tela, text="Prévia desligada  ·  gasta menos")
        if salvar:
            self.c["previa"] = ligada
            salvar_config(self.c)

    def _tela_mudou(self, ev):
        """Cabe a imagem 16:9 no espaco que sobrou, centralizada."""
        w, h = max(ev.width, 16), max(ev.height, 9)
        fw, fh = (w, int(w * 9 / 16)) if w * 9 / 16 <= h else (int(h * 16 / 9), h)
        self.origem = ((w - fw) // 2, (h - fh) // 2)
        if (fw, fh) != self.tam_foto:
            self.tam_foto = (fw, fh)
            self.foto = ImageTk.PhotoImage("RGB", self.tam_foto)
            self.tela.itemconfig(self.img, image=self.foto)
        ox, oy = self.origem
        self.tela.coords(self.img, ox, oy)
        self.tela.coords(self.aviso_tela, ox + fw // 2, oy + fh // 2)
        self.tela.coords(self.selo_fundo, ox + 12, oy + 12, ox + 82, oy + 38)
        self.tela.coords(self.selo, ox + 47, oy + 25)

    def tela_cheia(self, ligar=None):
        ligar = (not self.cheia) if ligar is None else ligar
        if ligar == self.cheia:
            return
        self.cheia = ligar
        if ligar:  # so a previa, como o projetor do OBS
            self.topo.pack_forget()
            self.linha_topo.pack_forget()
            self.barra.pack_forget()
            self.c_audio.grid_remove()
            self.c_ctrl.grid_remove()
            self.corpo.pack_configure(padx=0, pady=0)
            self.moldura.configure(corner_radius=0)
            self.tela.pack_configure(padx=0, pady=0)
            self.r.attributes("-fullscreen", True)
            self.tela.itemconfig(self.aviso_tela, text="Esc ou F11 pra sair  ·  Ctrl + Alt + R grava")
            self.r.after(2500, lambda: self.cheia and self.v_previa.get()
                         and self.tela.itemconfig(self.aviso_tela, text=""))
        else:
            self.r.attributes("-fullscreen", False)
            self.corpo.pack_configure(padx=20, pady=(16, 8))
            self.moldura.configure(corner_radius=RAIO_CARTAO)
            self.tela.pack_configure(padx=RESPIRO // 2, pady=RESPIRO // 2)
            self.topo.pack(side="top", fill="x", before=self.corpo)
            self.linha_topo.pack(side="top", fill="x", before=self.corpo)
            self.barra.pack(side="bottom", fill="x", padx=20, pady=(0, 8), before=self.corpo)
            self.c_audio.grid()
            self.c_ctrl.grid()
            if self.v_previa.get():
                self.tela.itemconfig(self.aviso_tela, text="")

    def _novo_quadro(self, dado, w, h):  # thread do motor: so guarda, quem desenha e' o tique
        self.quadro = (dado, w, h)

    def _na_frente(self):
        """So desenha a previa com a janela na frente. Jogando, o jogo esta na frente e
        desenhar seria gasto a toa: medido em 08/10/2026, ~24% de um nucleo."""
        try:
            return ctypes.windll.user32.GetForegroundWindow() == int(self.r.wm_frame(), 16)
        except Exception:
            return True

    # ---------------------------------------------------------------- gravar
    def alternar(self):
        if self.ocupado:
            return
        if self.cap.gravando:
            self.parar()
        else:
            self.gravar()

    def _travar(self, travado):
        for w in self.travaveis:
            w.configure(state="disabled" if travado else "normal")
        self.f_mic.menu.configure(state="disabled" if travado else "normal")  # faixas trocam ao vivo

    def gravar(self):
        self.ocupado = True
        self._travar(True)
        self.b_gravar.configure(state="disabled", text="Começando…")
        self._estado("Começando…")
        c = self.c
        _, _, h = self.monitor_atual()
        alt = c.get("altura") if c.get("altura") and c["altura"] < h else None
        args = (self.audio, c["pasta"], c["fps"], c["qualidade"], c["familia"] or "cpu",
                c["codec"], alt, c["formato"])

        def ir():
            try:
                self.cap.gravar(*args)
                self.eventos.put(("gravando",))
            except Exception as e:
                self.eventos.put(("falhou", str(e)))

        threading.Thread(target=ir, daemon=True).start()

    def parar(self):
        self.ocupado = True
        self.b_gravar.configure(state="disabled", text="Salvando…")
        self._estado("Salvando…")

        def ir():
            try:
                final, erro = self.cap.parar()
            except Exception as e:  # nunca deixar a janela presa em "Salvando..."
                final, erro = None, str(e)
            self.eventos.put(("parou", final, erro))

        threading.Thread(target=ir, daemon=True).start()

    def _evento(self, ev):
        tipo = ev[0]
        if tipo == "atalho":
            self.alternar()
        elif tipo == "detectou":
            self.c["codificadores"] = ev[1]
            self._escolher_familia()
            if self.janela_config and self.janela_config.winfo_exists():
                self.janela_config.recarregar()
        elif tipo == "gravando":
            self.ocupado = False
            self.inicio = self.cap.inicio
            self.b_gravar.configure(state="normal")
            self.pintar_acento(True)
            self.l_tempo.configure(text_color=TEXTO)
            self._estado("Gravando", TEXTO, BRASA)
            self.tela.itemconfig(self.selo, state="normal")
            self.tela.itemconfig(self.selo_fundo, state="normal")
        elif tipo == "falhou":
            self.ocupado = False
            self._travar(False)
            self._pintar_gravar()
            self._estado(f"Não deu pra gravar: {ev[1][:120]}", ERRO, ERRO)
        elif tipo == "parou":
            _, final, erro = ev
            self.ocupado = False
            self.inicio = None
            self._travar(False)
            self.tela.itemconfig(self.selo, state="hidden")
            self.tela.itemconfig(self.selo_fundo, state="hidden")
            self._pintar_gravar()
            self.l_tempo.configure(text_color=TEXTO_3)
            if final:
                mb = os.path.getsize(final) / 1e6
                txt = f"Salvo  ·  {os.path.basename(final)}  ·  {mb:.0f} MB"
                self._estado(txt + (f"  ·  {erro}" if erro else ""), TEXTO_2, AZUL)
            else:
                self._estado(f"Falhou: {erro[:120]}", ERRO, ERRO)
            self.mostrar_relogio()
            if self._fechando:
                self._sair()

    def _pintar_gravar(self):
        self.b_gravar.configure(state="normal")
        self.pintar_acento(False)

    # ---------------------------------------------------------------- laco
    def mostrar_relogio(self):
        if self.inicio and not self.ocupado:  # salvando: nao mexe no arquivo
            s = int(time.time() - self.inicio)
            self.l_tempo.configure(text=f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
            self.l_tam.configure(text=f"{self.cap.tamanho_mb():.0f} MB")
        elif not self.inicio:
            self.l_tempo.configure(text="00:00:00")
            self.l_tam.configure(text="")

    def tique(self):
        while True:
            try:
                self._evento(self.eventos.get_nowait())
            except queue.Empty:
                break
        q, self.quadro = self.quadro, None
        if q and self.v_previa.get() and self._na_frente():
            dado, w, h = q
            img = Image.frombuffer("RGB", (w, h), dado, "raw", "RGB", 0, 1)
            if img.size != self.tam_foto:
                # reduzir com LANCZOS mantem texto legivel; BILINEAR borrava a previa
                menor = self.tam_foto[0] < img.size[0]
                img = img.resize(self.tam_foto, Image.LANCZOS if menor else Image.BICUBIC,
                                 reducing_gap=2.0 if menor else None)
            self.foto.paste(img)
        for fa, fx in zip(self.f_faixas, self.audio.faixas if self.audio else [None] * 2):
            fa.medir(fx.pico if fx else 0)
        self.f_mic.medir(self.audio.pico_mic if self.audio else 0)
        if self.inicio:
            self.mostrar_relogio()
            if not self.cap.vivo() and not self.ocupado:  # ffmpeg morreu sozinho
                self.parar()
        if time.time() - self._ultima_lista > 4 and self._na_frente():
            self._ultima_lista = time.time()
            self._atualizar_listas()
        self.r.after(50, self.tique)

    def fechar(self):
        if self.cap.gravando and not self.ocupado:
            self._fechando = True
            self.parar()
        elif not self.ocupado:
            self._sair()
        else:
            self._fechando = True

    def _sair(self):
        try:
            self.cap.desligar_previa()
            self.audio.parar()
        finally:
            self.r.destroy()


def autoteste():
    """Argos.exe --autoteste: abre, grava 4 s sozinho, escreve o resultado em
    %TEMP%\\argos_autoteste.json e fecha. Prova que o PACOTE grava de verdade (ffmpeg,
    som, fontes, placa), nao so que a janela abre. Usa config e pasta temporarias."""
    global CONFIG, CONFIG_VELHO
    tmp = os.environ.get("TEMP", ".")
    CONFIG = CONFIG_VELHO = os.path.join(tmp, "argos_autoteste_config.json")
    if os.path.exists(CONFIG):
        os.remove(CONFIG)
    saida = os.path.join(tmp, "argos_autoteste.json")
    app = App()
    app.c["pasta"] = os.path.join(tmp, "argos_autoteste")
    res = {"fontes": [f for f in ("Inter", "Space Grotesk SemiBold") if f in tk.font.families(app.r)]}
    orig = app._evento

    def evento(ev):
        orig(ev)
        if ev[0] == "parou":
            res.update(arquivo=ev[1], erro=ev[2], codificadores=app.c.get("codificadores"),
                       monitores=app.monitores, ffmpeg=motor.FFMPEG)
            with open(saida, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
            app.r.after(300, app.fechar)
        elif ev[0] == "falhou":
            res.update(erro=ev[1])
            with open(saida, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
            app.r.after(300, app.fechar)

    app._evento = evento

    def comecar():
        if not app.c.get("codificadores"):  # placa ainda sendo testada
            app.r.after(500, comecar)
            return
        app.alternar()
        app.r.after(4000, app.alternar)

    app.r.after(2500, comecar)
    app.r.mainloop()


if __name__ == "__main__":
    try:  # agrupa na barra de tarefas como programa proprio, nao como "Python"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Argos.Gravador")
    except Exception:
        pass
    if "--autoteste" in sys.argv:
        import tkinter.font  # noqa: F401
        autoteste()
    else:
        App().r.mainloop()
