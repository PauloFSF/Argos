r"""gravar_jogo.py - o MOTOR do gravador de jogo: tela + som, pedindo pouco da maquina.

A janela estilo OBS e' o gravador_jogo_app.pyw, que usa as classes Audio e Captura
daqui. Este arquivo tambem roda sozinho pelo terminal (ver USO no fim).

AS BIBLIOTECAS (pyaudiowpatch, numpy, pillow, comtypes, pycaw, psutil, customtkinter):
empacotado, vem tudo junto no Argos.exe. Rodando do codigo, de uma pasta libs/ (ou
pillow), instaladas pro Python 3.12 do uv. NAO e' venv de proposito: o pythonw.exe
de venv do uv abre um python.exe COM CONSOLE por tras, medido em 08/10/2026 (visto a janela preta atras do programa). O atalho chama o pythonw.exe de verdade.

POR QUE E' LEVE, medido em 08/10/2026 no Ryzen 7 5700G
-------------------------------------------------------
Quem comprime e' o encoder AMF da GPU AMD, a captura e' a Desktop Duplication do
Windows (ddagrab). CPU do ffmpeg em 10 s:
  gravar 60 fps, sem previa ......... 2,31 s  (~23% de 1 nucleo, ~1,5% do total)
  gravar 60 fps + previa 640x360 .... 2,86 a 2,98 s  (~29% de 1 nucleo, ~2% do total)
  gravar 60 fps + previa 960x540 .... 3,62 s  (a usada hoje: nitida em tela cheia)
  + cor certa bt709 (desde 08/10) ... +1,2 a 1,5 s  (a conversao de cor, feita na CPU)
  APP INTEIRO gravando, janela atras, sem previa: ~5% do Ryzen (81% de 1 nucleo), 181 MB
  OBS (x264 720p30), mesma hora: 3,2% do Ryzen, 503 MB, e PERDEU 8% dos quadros
  so a previa 640x360 (sem gravar) .. 0,84 s

A rota "zero copia" (quadro nunca sai da GPU) FALHOU aqui, medido: o h264_amf recusa
o quadro BGRA (SubmitInput error 18) e o scale_d3d11 nao cria textura NV12 (80070057).

O SOM
-----
ffmpeg no Windows nao grava o som do PC. O som do PC (WASAPI loopback) e o microfone
sao lidos aqui, misturados com o volume de cada um e mandados ao ffmpeg por TCP local.
Por TCP e nao pela entrada padrao porque a entrada padrao fica livre pro "q", que e'
o jeito limpo de mandar o ffmpeg fechar o arquivo.

ARMADILHAS tratadas no codigo:
- o loopback PARA de mandar dado no silencio e dessincroniza. Um fluxo de silencio
  toca no mesmo alto-falante o tempo todo, pra manter o dispositivo acordado.
- o alto-falante e' 44100 Hz e o microfone 48000 Hz nesta maquina. O mic e'
  reamostrado (linear, com estado entre blocos pra nao estalar na emenda).
- sincronia: o som comeca a chegar antes do 1o quadro de video. O script mede essa
  diferenca e corta o comeco do som na conversao pra mp4. Segurar o som ate o video
  chegar parece mais simples e TRAVA o ffmpeg (ver comentario em Captura.gravar).

Grava em .mkv (se a luz cair, o arquivo continua abrindo) e no fim converte pra .mp4
sem recomprimir, porque o DaVinci le mp4 melhor.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

# Portatil: primeiro procura as libs e o ffmpeg AO LADO
# do programa (pasta 'libs' e 'ffmpeg'), depois no lugar desta maquina.
AQUI = os.path.dirname(os.path.abspath(__file__))
for LIBS in (os.path.join(AQUI, "libs"), r"C:\Ferramentas\gravador-jogo\libs"):
    # empacotado (Argos.exe) NUNCA olha pasta de fora: senao, no PC de quem montou, o
    # pacote usaria as libs de la e o autoteste aprovaria um pacote incompleto
    if not getattr(sys, "frozen", False) and os.path.isdir(LIBS) and LIBS not in sys.path:
        sys.path.insert(0, LIBS)
        break

import numpy as np  # noqa: E402
import pyaudiowpatch as pa  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import som_de_programa  # noqa: E402

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_R = 0x52
WM_HOTKEY = 0x0312
PM_REMOVE = 0x1
SEM_JANELA = 0x08000000  # sem isso, aberto pelo pythonw, cada ffmpeg pisca um console

PREV_W, PREV_H, PREV_FPS = 960, 540, 15


def achar_ffmpeg():
    for junto in (os.path.join(AQUI, "ffmpeg", "ffmpeg.exe"), os.path.join(AQUI, "..", "ffmpeg", "ffmpeg.exe")):
        if os.path.exists(junto):
            return os.path.abspath(junto)
    achado = shutil.which("ffmpeg")
    if achado:
        return achado
    winget = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    for raiz, _, arquivos in os.walk(winget):
        if "ffmpeg.exe" in arquivos:
            return os.path.join(raiz, "ffmpeg.exe")
    raise FileNotFoundError("ffmpeg nao achado")


FFMPEG = achar_ffmpeg()

# ---------------------------------------------------------------- opcoes de gravacao
# Opcoes pra qualquer PC: placa de qualquer marca, monitor de 120/144 Hz, 1440p. O de antes so sabia usar AMD: em NVIDIA/Intel nem gravava.
NIVEIS = {"Leve": 23, "Normal": 20, "Alta": 16, "Máxima": 12}  # qualidade constante, menor = melhor
CODECS = {"h264": "H.264", "h265": "H.265", "av1": "AV1"}
CODIFICADORES = {
    "amd": ("Placa de vídeo AMD", {"h264": "h264_amf", "h265": "hevc_amf", "av1": "av1_amf"}),
    "nvidia": ("Placa de vídeo NVIDIA", {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"}),
    "intel": ("Placa de vídeo Intel", {"h264": "h264_qsv", "h265": "hevc_qsv", "av1": "av1_qsv"}),
    "cpu": ("Processador (mais pesado)", {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}),
}
FORMATOS = ("mp4", "mov", "mkv")


def args_video(familia, codec, nivel):
    """Argumentos do codificador em QUALIDADE CONSTANTE (o equivalente do CQP em cada
    marca). Placa de video primeiro: e' o que deixa o jogo leve."""
    q = NIVEIS[nivel]
    enc = CODIFICADORES[familia][1][codec]
    if familia == "amd":
        a = ["-usage", "lowlatency", "-quality", "speed", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q)]
    elif familia == "nvidia":
        a = ["-preset", "p4", "-tune", "hq", "-rc", "constqp", "-qp", str(q)]
    elif familia == "intel":
        a = ["-preset", "veryfast", "-global_quality", str(q)]
    elif codec == "h264":
        a = ["-preset", "veryfast", "-crf", str(q)]            # o padrao do OBS no processador
    elif codec == "h265":
        a = ["-preset", "superfast", "-crf", str(q + 2)]       # crf do x265 ~ x264 - 2
    else:
        a = ["-preset", "10", "-crf", str(round(q * 1.5 + 5))]  # escala do SVT-AV1 e' 0-63
    if codec == "h264" and familia != "intel":
        a += ["-profile:v", "high"]
    return ["-c:v", enc] + a


def detectar_codificadores():
    """Testa DE VERDADE cada marca x formato (10 quadros, com os argumentos reais), em
    paralelo. So aparece o que roda nesta maquina: ter o codificador no ffmpeg nao prova
    que a placa existe (medido aqui: o ffmpeg lista NVENC e QSV, e os dois falham)."""
    from concurrent.futures import ThreadPoolExecutor

    def testar(fc):
        f, c = fc
        try:
            r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", "color=black:s=1280x720:r=60", "-frames:v", "10",
                                "-pix_fmt", "nv12", *args_video(f, c, "Normal"), "-f", "null", "-"],
                               capture_output=True, timeout=40, creationflags=SEM_JANELA)
            return fc, r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return fc, False

    with ThreadPoolExecutor(6) as ex:
        ok = dict(ex.map(testar, [(f, c) for f in CODIFICADORES for c in CODECS]))
    return {f: [c for c in CODECS if ok[(f, c)]] for f in CODIFICADORES
            if any(ok[(f, c)] for c in CODECS)}


def listar_janelas():
    """Janelas que da pra gravar: visiveis, com titulo, que aparecem na barra de tarefas.
    [{"hwnd", "titulo", "exe"}]. Fora: a do proprio Argos, janela de ferramenta e as
    "escondidas" do Windows 11 (cloaked: apps da loja suspensos ficam visiveis e vazios)."""
    import psutil
    u32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    eu = os.getpid()
    achadas = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cada(h, _):
        if not u32.IsWindowVisible(h) or u32.GetWindow(h, 4):  # 4 = GW_OWNER
            return True
        n = u32.GetWindowTextLengthW(h)
        if not n or u32.GetWindowLongW(h, -20) & 0x80:  # WS_EX_TOOLWINDOW
            return True
        escondida = ctypes.c_int(0)
        dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(escondida), 4)  # DWMWA_CLOAKED
        if escondida.value:
            return True
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == eu:
            return True
        b = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(h, b, n + 1)
        try:
            exe = psutil.Process(pid.value).name()
        except psutil.Error:
            exe = ""
        achadas.append({"hwnd": int(h), "titulo": b.value, "exe": exe})
        return True

    u32.EnumWindows(cada, 0)
    return achadas


def janela_minimizada(hwnd):
    return bool(hwnd) and bool(ctypes.windll.user32.IsIconic(wt.HWND(hwnd)))


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint), ("flags", ctypes.c_uint), ("show", ctypes.c_uint),
                ("pmin", wt.POINT), ("pmax", wt.POINT), ("normal", wt.RECT)]


def tamanho_janela(hwnd):
    """(largura, altura) da area de dentro da janela, ja par (o codificador exige).
    Minimizada, o Windows devolve lixo (152x24, medido em 08/10/2026): usa o tamanho
    que ela tem quando restaurada."""
    u32 = ctypes.windll.user32
    if janela_minimizada(hwnd):
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        if u32.GetWindowPlacement(wt.HWND(hwnd), ctypes.byref(wp)):
            n = wp.normal
            return (n.right - n.left) // 2 * 2, (n.bottom - n.top) // 2 * 2
        return None
    r = wt.RECT()
    if not u32.GetClientRect(wt.HWND(hwnd), ctypes.byref(r)):
        return None
    return (r.right - r.left) // 2 * 2, (r.bottom - r.top) // 2 * 2


def listar_monitores():
    """[(indice, largura, altura)] NA ORDEM do ddagrab, perguntando pro proprio ffmpeg:
    a ordem do Windows (EnumDisplayMonitors) pode nao bater com a do ddagrab."""
    mons = []
    for i in range(8):
        try:
            r = subprocess.run([FFMPEG, "-hide_banner", "-v", "verbose", "-filter_complex",
                                f"ddagrab=output_idx={i}", "-frames:v", "1", "-f", "null", "-"],
                               capture_output=True, text=True, errors="replace", timeout=15,
                               creationflags=SEM_JANELA)
        except (OSError, subprocess.TimeoutExpired):
            break
        m = re.search(r"Opened dxgi output \d+ with dimensions (\d+)x(\d+)", r.stderr)
        if not m:
            break
        mons.append((i, int(m.group(1)), int(m.group(2))))
    return mons or [(0, 1920, 1080)]


class _DEVMODEW(ctypes.Structure):
    _fields_ = [("nome", ctypes.c_wchar * 32), ("spec", ctypes.c_ushort), ("drv", ctypes.c_ushort),
                ("size", ctypes.c_ushort), ("extra", ctypes.c_ushort), ("campos", ctypes.c_ulong),
                ("uniao", ctypes.c_byte * 16), ("cor", ctypes.c_short), ("duplex", ctypes.c_short),
                ("yres", ctypes.c_short), ("tt", ctypes.c_short), ("collate", ctypes.c_short),
                ("form", ctypes.c_wchar * 32), ("logpx", ctypes.c_ushort), ("bpp", ctypes.c_ulong),
                ("largura", ctypes.c_ulong), ("altura", ctypes.c_ulong), ("flags", ctypes.c_ulong),
                ("hz", ctypes.c_ulong), ("resto", ctypes.c_byte * 32)]


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("nome", ctypes.c_wchar * 32), ("texto", ctypes.c_wchar * 128),
                ("estado", ctypes.c_ulong), ("id", ctypes.c_wchar * 128), ("chave", ctypes.c_wchar * 128)]


def taxas_dos_monitores():
    """{(largura, altura): Hz} de cada monitor ligado, pra oferecer 120/144 so a quem tem."""
    u32 = ctypes.windll.user32
    taxas = {}
    i = 0
    while True:
        dd = _DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not u32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not dd.estado & 0x1:  # nao esta ligado ao desktop
            continue
        dm = _DEVMODEW()
        dm.size = ctypes.sizeof(dm)
        if u32.EnumDisplaySettingsW(dd.nome, -1, ctypes.byref(dm)):
            chave = (dm.largura, dm.altura)
            taxas[chave] = max(taxas.get(chave, 0), dm.hz)
    return taxas


def listar_audio():
    """(saidas, entradas) do WASAPI. Saida = o que da pra gravar como 'som do PC'."""
    p = pa.PyAudio()
    try:
        w = p.get_host_api_info_by_type(pa.paWASAPI)
        saidas, entradas = [], []
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d["hostApi"] != w["index"]:
                continue
            if d.get("isLoopbackDevice"):
                saidas.append(d["name"].replace(" [Loopback]", ""))
            elif d["maxInputChannels"] > 0:
                entradas.append(d["name"])
        padrao_saida = p.get_device_info_by_index(w["defaultOutputDevice"])["name"]
        padrao_entrada = p.get_device_info_by_index(w["defaultInputDevice"])["name"]
        return saidas, entradas, padrao_saida, padrao_entrada
    finally:
        p.terminate()


class Reamostrar:
    """Linear, com estado entre blocos: a emenda de um bloco no outro nao estala."""

    def __init__(self, de, para):
        self.passo = de / para
        self.pos = 0.0
        self.ultimo = 0.0

    def __call__(self, x):
        if self.passo == 1.0:
            return x
        buf = np.concatenate(([self.ultimo], x))
        fim = len(buf) - 1
        if self.pos > fim:
            self.pos -= len(x)
            self.ultimo = buf[-1]
            return np.zeros(0, np.float32)
        k = int((fim - self.pos) / self.passo) + 1
        idx = self.pos + self.passo * np.arange(k)
        y = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
        self.pos = self.pos + self.passo * k - fim
        self.ultimo = buf[-1]
        return y


TUDO_PC = "Todo o som do PC"


class Faixa:
    """Uma faixa livre do mixer: um programa so (ou o PC todo), com volume e mudo."""

    def __init__(self, fonte=None, vol=1.0, mudo=True, nome=None):
        self.fonte, self.vol, self.mudo = fonte, vol, mudo
        self.nome = nome  # nome dado pelo usuario (ex: "Jogo"); vira o nome da trilha
        self.pico = 0.0
        self.erro = ""
        self.buf = np.zeros((0, 2), np.float32)
        self.cap = None
        self.aberta = None


class Audio:
    """Duas faixas livres + microfone, sempre ligados enquanto o programa esta aberto
    (pros medidores). Mistura com o volume e o mudo de cada um, e quando 'destino' e'
    uma fila, manda o som misturado pra ela.

    O loopback do alto-falante padrao roda SEMPRE, mesmo sem nenhuma faixa no "PC
    todo": ele e' o RELOGIO da mistura (bloco a bloco, continuo gracas ao silencio que
    toca junto). As faixas de programa e o mic chegam em fila e sao puxados no ritmo dele."""

    def __init__(self, mic=None, n_faixas=2):
        self.nome_mic = mic
        self.vol_mic, self.mudo_mic = 1.0, True
        self.pico_mic = 0.0
        self.faixas = [Faixa() for _ in range(n_faixas)]
        self.destino = None
        self._mic_buf = np.zeros(0, np.float32)
        self._trava = threading.Lock()
        self._s_mic = None
        self._p = None

    def iniciar(self):
        self._p = pa.PyAudio()
        loop = self._p.get_default_wasapi_loopback()
        self.nome_saida = loop["name"].replace(" [Loopback]", "")
        self.taxa, self.canais = int(loop["defaultSampleRate"]), loop["maxInputChannels"]

        # o silencio toca no MESMO alto-falante que esta sendo gravado
        alto = None
        w = self._p.get_host_api_info_by_type(pa.paWASAPI)
        for i in range(self._p.get_device_count()):
            d = self._p.get_device_info_by_index(i)
            if d["hostApi"] == w["index"] and not d.get("isLoopbackDevice") \
                    and d["name"] == self.nome_saida and d["maxOutputChannels"] > 0:
                alto = d
        canais_alto = alto["maxOutputChannels"] if alto else self.canais

        def silencio(dado, n, info, status):
            return (b"\x00" * n * canais_alto * 2, pa.paContinue)

        self._s_out = self._p.open(
            format=pa.paInt16, channels=canais_alto, rate=self.taxa, output=True,
            output_device_index=alto["index"] if alto else None, stream_callback=silencio)
        self._s_in = self._p.open(
            format=pa.paInt16, channels=self.canais, rate=self.taxa, input=True,
            input_device_index=loop["index"], frames_per_buffer=1024,
            stream_callback=self._ao_ler_pc)
        if not self.mudo_mic:
            self.abrir_mic()
        for i, f in enumerate(self.faixas):
            self.definir_faixa(i, f.fonte, f.mudo, f.vol)

    def definir_faixa(self, i, fonte, mudo, vol=None):
        """Liga, troca ou desliga o que a faixa i grava."""
        f = self.faixas[i]
        f.fonte, f.mudo = fonte, mudo
        if vol is not None:
            f.vol = vol
        quer = fonte if (fonte and fonte != TUDO_PC and not mudo) else None
        if quer == f.aberta and (quer is None or (f.cap and f.cap.is_alive())):
            return
        self._fechar_faixa(f)
        if not quer or not self._p:
            return
        pid = som_de_programa.pid_raiz(quer)
        if not pid:
            f.erro = f"{quer} não está aberto"
            return
        with self._trava:
            f.buf = np.zeros((0, self.canais), np.float32)

        def ao_dado(pcm):
            y = np.frombuffer(pcm, np.int16).reshape(-1, self.canais).astype(np.float32) / 32768.0
            with self._trava:
                f.buf = np.concatenate((f.buf, y))

        f.cap = som_de_programa.SomDePrograma(pid, self.taxa, self.canais, ao_dado)
        f.cap.start()
        f.cap.iniciado.wait(5)
        f.erro = f.cap.erro or ""
        f.aberta = quer

    def _fechar_faixa(self, f):
        cap, f.cap, f.aberta = f.cap, None, None
        if cap:
            cap.parar()
        f.pico = 0.0
        f.erro = ""

    def abrir_mic(self):
        if self._s_mic or not self._p:
            return
        d = None
        if self.nome_mic:
            w = self._p.get_host_api_info_by_type(pa.paWASAPI)
            for i in range(self._p.get_device_count()):
                x = self._p.get_device_info_by_index(i)
                if x["hostApi"] == w["index"] and x["name"] == self.nome_mic \
                        and x["maxInputChannels"] > 0 and not x.get("isLoopbackDevice"):
                    d = x
        if not d:
            try:
                d = self._p.get_device_info_by_index(
                    self._p.get_host_api_info_by_type(pa.paWASAPI)["defaultInputDevice"])
            except OSError:
                return
            self.nome_mic = d["name"]
        self._mic_canais = min(2, d["maxInputChannels"])
        taxa_mic = int(d["defaultSampleRate"])
        self._reamostrar = Reamostrar(taxa_mic, self.taxa)
        with self._trava:
            self._mic_buf = np.zeros(0, np.float32)
        self._s_mic = self._p.open(
            format=pa.paInt16, channels=self._mic_canais, rate=taxa_mic, input=True,
            input_device_index=d["index"], frames_per_buffer=1024,
            stream_callback=self._ao_ler_mic)

    def fechar_mic(self):
        s, self._s_mic = self._s_mic, None
        if s:
            s.stop_stream()
            s.close()
        self.pico_mic = 0.0

    def _ao_ler_mic(self, dado, n, info, status):
        y = np.frombuffer(dado, np.int16).reshape(-1, self._mic_canais).mean(axis=1) / 32768.0
        y = self._reamostrar(y.astype(np.float32))
        with self._trava:
            self._mic_buf = np.concatenate((self._mic_buf, y))
        return (None, pa.paContinue)

    def _ao_ler_pc(self, dado, n, info, status):
        x = np.frombuffer(dado, np.int16).reshape(-1, self.canais).astype(np.float32) / 32768.0
        frames = len(x)
        mix = np.zeros_like(x)
        trilhas = []  # cada fonte separada, pra virar trilha propria no arquivo

        for f in self.faixas:
            if f.fonte == TUDO_PC:
                s = x * (0.0 if f.mudo else f.vol)
            else:
                with self._trava:
                    f.buf = self._aparar(f.buf)
                    s, f.buf = f.buf[:frames], f.buf[frames:]
                s = self._completar(s, frames) * (0.0 if (f.mudo or not f.cap) else f.vol)
            f.pico = float(np.abs(s).max()) if len(s) else 0.0
            mix += s
            trilhas.append(self._estereo(s))

        with self._trava:
            self._mic_buf = self._aparar(self._mic_buf)
            m, self._mic_buf = self._mic_buf[:frames], self._mic_buf[frames:]
        m = self._completar(m, frames) * (0.0 if (self.mudo_mic or not self._s_mic) else self.vol_mic)
        self.pico_mic = float(np.abs(m).max()) if self._s_mic and len(m) else 0.0
        mix += m[:, None]
        trilhas.append(np.repeat(m[:, None], 2, axis=1))

        destino = self.destino
        if destino is not None:
            # 8 canais intercalados: mistura, faixa 1, faixa 2, microfone (2 cada).
            # O ffmpeg separa de volta em 4 trilhas estereo, como o OBS faz.
            tudo = np.concatenate([self._estereo(mix)] + trilhas, axis=1)
            destino.put((np.clip(tudo, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
        return (None, pa.paContinue)

    @property
    def canais_saida(self):
        return 2 * (2 + len(self.faixas))

    @staticmethod
    def _estereo(x):
        """Alto-falante 5.1 tambem vira estereo: as trilhas do arquivo sao sempre 2 canais."""
        return x[:, :2] if x.shape[1] >= 2 else np.repeat(x, 2, axis=1)

    def _aparar(self, buf):
        # relogios diferentes derivam: se a fila acumular, joga fora o excesso
        return buf[-int(self.taxa * 0.1):] if len(buf) > self.taxa * 0.3 else buf

    @staticmethod
    def _completar(parte, frames):
        if len(parte) < frames:
            falta = np.zeros((frames - len(parte),) + parte.shape[1:], np.float32)
            parte = np.concatenate((parte, falta))
        return parte

    def parar(self):
        self.destino = None
        self.fechar_mic()
        for f in self.faixas:
            self._fechar_faixa(f)
        for s in (getattr(self, "_s_in", None), getattr(self, "_s_out", None)):
            if s:
                try:
                    s.stop_stream()
                    s.close()
                except OSError:
                    pass
        if self._p:
            self._p.terminate()
            self._p = None


class Captura:
    """O ffmpeg. Fica em previa (so mostra a tela) ou gravando (grava + mostra).
    ao_quadro(bytes RGB 640x360) e' chamado a cada quadro da previa."""

    def __init__(self, monitor=0, ao_quadro=None):
        self.monitor = monitor
        self.janela = None  # hwnd: se tiver, grava SO essa janela em vez do monitor
        self.ao_quadro = ao_quadro
        self.previa = False
        self.inicio = None
        self.mkv = self.mp4 = None
        self.erro = ""
        self._ff = None
        self._gravando = False
        self._primeiro = threading.Event()

    @property
    def gravando(self):
        return self._gravando

    def vivo(self):
        return self._ff is not None and self._ff.poll() is None

    def tamanho_mb(self):
        try:
            with open(self.mkv, "rb") as f:
                f.seek(0, 2)
                return f.tell() / 1e6
        except (OSError, TypeError):
            return 0.0

    def _ler(self, ff, tam):
        w, h = tam
        quadro = w * h * 3
        primeiro = True
        while True:
            dado = ff.stdout.read(quadro)
            if not dado or len(dado) < quadro:
                break
            if primeiro:
                self._t_quadro = time.time()
                self._primeiro.set()
                primeiro = False
            if self.ao_quadro:
                self.ao_quadro(dado, w, h)

    def _ler_erro(self, ff):
        for linha in ff.stderr:
            texto = linha.decode("utf-8", "replace").strip()
            if texto and "non monotonically" not in texto:
                self.erro = texto[-300:]

    def _abrir(self, cmd, tam=(PREV_W, PREV_H)):
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, creationflags=SEM_JANELA)
        threading.Thread(target=self._ler, args=(ff, tam), daemon=True).start()
        threading.Thread(target=self._ler_erro, args=(ff,), daemon=True).start()
        return ff

    def _fechar_ff(self, espera=15):
        ff, self._ff = self._ff, None
        if not ff:
            return
        try:
            ff.stdin.write(b"q")  # o jeito limpo: o ffmpeg fecha o arquivo direito
            ff.stdin.flush()
        except OSError:
            pass
        try:
            ff.wait(timeout=espera)
        except subprocess.TimeoutExpired:
            ff.kill()
            ff.wait()

    @staticmethod
    def _grafo_trilhas(n):
        partes = [f"[0:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n))]
        partes += [f"[s{i}]pan=stereo|c0=c{2 * i}|c1=c{2 * i + 1}[a{i}]" for i in range(n)]
        return ";".join(partes)

    def _fonte(self, fps):
        """De onde vem a imagem, ja na placa de video.
        Monitor: ddagrab (Desktop Duplication). Janela: gfxcapture, a captura de janela do
        Windows (Windows.Graphics.Capture, a mesma do OBS): pega SO aquela janela, mesmo com
        outra por cima. Ela so manda quadro quando a janela muda, por isso o fps= depois
        (repete o quadro e o video sai com taxa constante, o que o editor precisa). Medido
        em 08/10/2026 numa janela do Chrome com video: 600 quadros em 10 s, 0 buracos,
        4,7 s de CPU (o monitor inteiro com a mesma conversao de cor: ~3,7 a 4,5 s).
        width/height=-2 arredondam pra numero par, que o codificador exige."""
        if self.janela:
            return (f"gfxcapture=hwnd={self.janela}:max_framerate={fps}:width=-2:height=-2,"
                    f"fps={fps}")
        return f"ddagrab=output_idx={self.monitor}:framerate={fps}"

    def ligar_previa(self):
        self.previa = True
        if self._gravando or self.vivo():
            return
        self._ff = self._abrir([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-init_hw_device", "d3d11va",
            "-filter_complex",
            f"{self._fonte(PREV_FPS)},hwdownload,format=bgra,"
            f"scale={PREV_W}:{PREV_H}:flags=fast_bilinear",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])

    def desligar_previa(self):
        self.previa = False
        if not self._gravando:
            self._matar_ff()

    def _matar_ff(self):
        """Previa nao tem arquivo pra fechar direito: mata na hora. Medido em 08/10/2026:
        o "q" educado esperava 3,01 s com janela minimizada (o ffmpeg fica parado
        esperando um quadro que nunca vem e nem le o "q"), e a janela travava junto."""
        ff, self._ff = self._ff, None
        if ff:
            try:
                ff.kill()
                ff.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def gravar(self, audio, pasta, fps=60, nivel="Alta", familia="amd", codec="h264",
               altura=None, formato="mp4"):
        """altura=None grava no tamanho do monitor; senao reduz (ex: 1080, 720)."""
        if janela_minimizada(self.janela):
            raise RuntimeError("a janela escolhida está minimizada: restaure ela pra gravar")
        self._matar_ff()  # sai do modo previa (previa nao tem arquivo, pode matar)
        os.makedirs(pasta, exist_ok=True)
        base = os.path.join(pasta, "jogo_" + datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
        self.formato = formato if formato in FORMATOS else "mp4"
        self.codec = codec
        # o bruto e' sempre .mkv (se a luz cair, abre); o final sai no formato escolhido
        self.mkv, self.mp4 = base + ".gravando.mkv", base + "." + self.formato
        self.erro = ""

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()

        # a previa sai sempre: mesmo escondida, o 1o quadro dela e' o sinal de sincronia.
        # A divisao e' feita NA GPU, antes do hwdownload, e a previa a 15 fps. Medido em
        # 08/10/2026, 10 s gravando: dividir na CPU custou 4,11 s de CPU, na GPU 2,86 s.
        # E previa a 2 fps (pra economizar) FURAVA o video: 9 buracos de ate 0,57 s em
        # 5 s, porque o filtro fps segura quadros e trava o ramo da gravacao.
        # Com a previa desligada o ramo dela fica minusculo (so serve de sinal de
        # sincronia): medido em 08/10/2026, a previa 960x540 custava ~15% de um nucleo.
        pw, ph = (PREV_W, PREV_H) if self.previa else (320, 180)
        n_trilhas = audio.canais_saida // 2
        nomes = ["Mistura"] + [(f.nome or f"Faixa {i + 1}") + (f" ({f.fonte})" if f.fonte else "")
                               for i, f in enumerate(audio.faixas)] + ["Microfone"]
        # 'title' e 'handler_name': cada editor le o nome da trilha de um campo
        titulos = [x for i, n in enumerate(nomes)
                   for x in (f"-metadata:s:a:{i}", f"title={n}", f"-metadata:s:a:{i}", f"handler_name={n}")]
        self._primeiro.clear()
        self._ff = self._abrir([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-init_hw_device", "d3d11va",
            "-f", "s16le", "-ar", str(audio.taxa), "-ac", str(audio.canais_saida),
            "-thread_queue_size", "4096", "-i", f"tcp://127.0.0.1:{porta}?listen=1",
            "-filter_complex",
            f"{self._fonte(fps)},split[g1][g2];"
            # COR, o que veio do OBS: converter NA MAO pro padrao de video (bt709,
            # faixa limitada) e marcar o arquivo. Medido em 08/10/2026: deixando o AMF
            # converter sozinho, o arquivo saia marcado 'gbr' e o preto da barra de
            # tarefas (12,8) virava 27 no video, sombra lavada. Convertendo: erro medio
            # de 14,7 pra 2,3. Custa ~5% de um nucleo.
            f"[g1]hwdownload,format=bgra,scale={'w=-2:h=' + str(altura) + ':' if altura else ''}"
            f"out_color_matrix=bt709:out_range=tv:flags=bicubic,format=nv12,"
            f"setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv[v];"
            f"[g2]fps={PREV_FPS},hwdownload,format=bgra,scale={pw}:{ph}:flags=fast_bilinear[pv];"
            # TRILHAS SEPARADAS, pra editar cada som no DaVinci/Premiere:
            # 1 = tudo misturado (o que toca em qualquer player), 2..n = cada fonte
            + self._grafo_trilhas(n_trilhas),
            "-map", "[v]", *[x for i in range(n_trilhas) for x in ("-map", f"[a{i}]")],
            # QUALIDADE CONSTANTE (CQP), o modo que o OBS usa pra gravar. Medido em
            # 08/10/2026 com VMAF em 3 clipes: mesma nota do bitrate fixo com arquivo
            # 30% a 80% menor (cena parada gasta pouco, movimento gasta o que precisa).
            # 'quality' em vez de 'speed' NAO melhorou a nota e deixou o codificador 2x
            # mais lento; pre-analise derrubou pra 1x tempo real. Por isso 'speed'.
            *args_video(familia, codec, nivel),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv",
            "-c:a", "aac", "-b:a", "192k", *titulos, self.mkv,
            "-map", "[pv]", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], (pw, ph))

        self._sock = None
        for _ in range(100):
            try:
                self._sock = socket.create_connection(("127.0.0.1", porta), timeout=1)
                break
            except OSError:
                if not self.vivo():
                    break
                time.sleep(0.05)
        if not self._sock:
            self._fechar_ff(espera=3)
            raise RuntimeError(self.erro or "o ffmpeg nao abriu a entrada de som")
        self._sock.settimeout(None)

        # O som tem que ir JA. Medido em 08/10/2026: segurar o som ate o 1o quadro de
        # video TRAVA o ffmpeg (o agendador dele pausa o video enquanto o som do mesmo
        # arquivo nao anda), e o video saiu com buracos de 0,5 s. Entao o som vai desde
        # a conexao, e o atraso entre o 1o som e o 1o quadro e' descontado no fim, na
        # conversao pra mp4 (-ss no audio).
        self._fila = queue.Queue()
        self._parar_envio = threading.Event()
        self._t_som = None
        audio.destino = self._fila
        self._audio = audio

        def enviar():
            while not self._parar_envio.is_set():
                try:
                    bloco = self._fila.get(timeout=0.2)
                    self._sock.sendall(bloco)
                    if self._t_som is None:
                        self._t_som = time.time()
                except queue.Empty:
                    continue
                except OSError:
                    break

        self._t_envio = threading.Thread(target=enviar, daemon=True)
        self._t_envio.start()
        self._primeiro.wait(timeout=5)
        self._gravando = True
        self.inicio = time.time()

    def parar(self):
        """Fecha a gravacao e devolve (caminho_final, erro). Volta pra previa se ligada."""
        self._audio.destino = None
        time.sleep(0.15)  # deixa sair o que ja estava na fila
        self._parar_envio.set()
        self._t_envio.join(timeout=2)
        # fecha o som ANTES do "q". Medido em 08/10/2026: com o socket aberto, o ffmpeg
        # obedece o "q" mas fica preso esperando som que nao vem, cai no kill depois
        # de 20 s e o .mkv perde os ultimos segundos (8 s gravados viraram 5,7 s)
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
            self._sock.close()
        except OSError:
            pass
        self._fechar_ff(espera=20)
        self._gravando = False

        # quanto o som comecou ANTES da imagem; ~20 ms sao o caminho do quadro ate aqui
        self.atraso = 0.0
        if self._t_som and self._primeiro.is_set():
            self.atraso = max(0.0, self._t_quadro - self._t_som - 0.02)

        final, erro = None, self.erro
        if os.path.exists(self.mkv) and os.path.getsize(self.mkv) > 0:
            som = ["-ss", f"{self.atraso:.3f}"] if self.atraso > 0.03 else []
            extra = []
            if self.formato in ("mp4", "mov"):
                extra = ["-movflags", "+faststart"]
                if self.codec == "h265":
                    extra += ["-tag:v", "hvc1"]  # H.265 que o Windows e o DaVinci reconhecem
            r = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                                "-i", self.mkv, *som, "-i", self.mkv,
                                "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest",
                                *extra, self.mp4],
                               creationflags=SEM_JANELA)
            if r.returncode == 0 and os.path.getsize(self.mp4) > 0:
                final, erro = self.mp4, ""
                # o .mkv as vezes fica preso uns instantes (antivirus, ou a janela lendo
                # o tamanho). Medido em 08/10/2026: os.remove direto deu WinError 32 e
                # derrubou o "parar", travando a janela em "Salvando...". Tenta de novo.
                for _ in range(20):
                    try:
                        os.remove(self.mkv)
                        break
                    except PermissionError:
                        time.sleep(0.25)
                else:
                    erro = "o .gravando.mkv ficou ao lado (estava em uso), pode apagar"
            else:
                final, erro = self.mkv, f"conversao pra {self.formato} falhou, o .mkv ficou"
        elif not erro:
            erro = "nada gravado"

        if self.previa:
            self.ligar_previa()
        return final, erro


def main():
    """USO PELO TERMINAL
    .\\gravar_jogo.ps1                                  # 60 fps, faixa 1 = som do PC todo
    .\\gravar_jogo.ps1 -Extra @("--faixa1","deadlock.exe","--mic")
    .\\gravar_jogo.ps1 -Extra @("--faixa1","deadlock.exe","--faixa2","Discord.exe")
    PARAR > Ctrl + Alt + R (de dentro do jogo) ou Ctrl + C nesta janela."""
    ap = argparse.ArgumentParser(description="Grava jogo leve: GPU AMD + 2 faixas livres + mic")
    ap.add_argument("--pasta", default=os.path.join(os.path.expanduser("~"), "Videos", "Argos"))
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--qualidade", default="Alta", choices=list(NIVEIS))
    ap.add_argument("--codificador", default="amd", choices=list(CODIFICADORES))
    ap.add_argument("--codec", default="h264", choices=list(CODECS))
    ap.add_argument("--altura", type=int, default=None, help="reduz, ex: 1080 ou 720")
    ap.add_argument("--formato", default="mp4", choices=list(FORMATOS))
    ap.add_argument("--monitor", type=int, default=0)
    ap.add_argument("--mic", action="store_true", help="junta o microfone padrao")
    ap.add_argument("--faixa1", default="pc", help="programa (ex: deadlock.exe) ou 'pc' = PC todo")
    ap.add_argument("--faixa2", default=None, help="outro programa, ou 'pc'")
    ap.add_argument("--segundos", type=float, default=0, help="para sozinho (teste)")
    a = ap.parse_args()

    audio = Audio()
    audio.mudo_mic = not a.mic
    for i, nome in enumerate((a.faixa1, a.faixa2)):
        fonte = TUDO_PC if (nome or "").lower() == "pc" else nome
        audio.faixas[i].fonte, audio.faixas[i].mudo = fonte, not fonte
    audio.iniciar()
    for f in audio.faixas:
        if f.erro:
            print(f"Aviso: {f.erro}")
    cap = Captura(a.monitor)
    cap.gravar(audio, a.pasta, a.fps, a.qualidade, a.codificador, a.codec, a.altura, a.formato)

    u32 = ctypes.windll.user32
    atalho = u32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_R)
    print(f"GRAVANDO > {cap.mp4}")
    print("Parar: Ctrl + Alt + R" if atalho else "Parar: Ctrl + C (atalho global ocupado)")

    msg = wt.MSG()
    try:
        while cap.vivo():
            if atalho and u32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                break
            if a.segundos and time.time() - cap.inicio >= a.segundos:
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    if atalho:
        u32.UnregisterHotKey(None, 1)

    dur = time.time() - cap.inicio
    final, erro = cap.parar()
    audio.parar()
    if not final:
        print(f"FALHOU: {erro}")
        return 1
    if erro:
        print(f"Aviso: {erro}")
    print(f"PRONTO > {final}  ({dur/60:.1f} min, {os.path.getsize(final)/1e6:.0f} MB, "
          f"som adiantado {cap.atraso*1000:.0f} ms, descontado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
