r"""som_de_programa.py - grava o som de UM programa so (o jogo, o Chrome), e nao o PC todo.

E' a "captura de audio de aplicativo" do OBS. Usa o process loopback do Windows
(Windows 10 2004 ou mais novo): ActivateAudioInterfaceAsync no dispositivo virtual
"VAD\Process_Loopback", com o PID do programa. Pega o programa e os filhos dele
(o Chrome toca o som num processo filho, por isso a arvore inteira).

Feito em Python puro com comtypes, sem compilar nada. Usado pelo gravar_jogo.py.

ARMADILHAS desta API, conferidas na doc da Microsoft e no exemplo oficial
(ApplicationLoopback):
- GetMixFormat NAO funciona nesse dispositivo; o formato tem que ser dado na mao
  (PCM 16 bits). AUTOCONVERTPCM faz o Windows converter pra ele.
- O objeto que recebe o "terminou de ativar" precisa ser AGIL (IAgileObject), senao
  a ativacao falha. E a chamada roda numa thread COM multithread (MTA), propria.

Teste solto > python som_de_programa.py chrome.exe   (grava 3 s e mostra o pico)
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
from ctypes import POINTER, Structure, byref, c_int, c_int64, c_long, c_ubyte, c_uint32, \
    c_uint64, c_ulong, c_ushort, c_void_p, sizeof

for LIBS in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs"),
             r"C:\Ferramentas\gravador-jogo\libs"):
    if not getattr(sys, "frozen", False) and os.path.isdir(LIBS) and LIBS not in sys.path:
        sys.path.insert(0, LIBS)
        break

import comtypes  # noqa: E402
import psutil  # noqa: E402
from comtypes import COMMETHOD, GUID, HRESULT, COMObject, IUnknown  # noqa: E402


class WAVEFORMATEX(Structure):
    _fields_ = [("wFormatTag", c_ushort), ("nChannels", c_ushort), ("nSamplesPerSec", c_ulong),
                ("nAvgBytesPerSec", c_ulong), ("nBlockAlign", c_ushort),
                ("wBitsPerSample", c_ushort), ("cbSize", c_ushort)]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(POINTER(c_ubyte)), "data"), (["out"], POINTER(c_uint32), "frames"),
                  (["out"], POINTER(c_uint32), "flags"), (["out"], POINTER(c_uint64), "devpos"),
                  (["out"], POINTER(c_uint64), "qpcpos")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "n")),
    ]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize", (["in"], c_uint32, "mode"), (["in"], c_uint32, "flags"),
                  (["in"], c_int64, "dur"), (["in"], c_int64, "per"),
                  (["in"], POINTER(WAVEFORMATEX), "fmt"), (["in"], c_void_p, "sess")),
        COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32), "n")),
        COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(c_int64), "l")),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32), "n")),
        COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_uint32, "m"),
                  (["in"], POINTER(WAVEFORMATEX), "f"), (["out"], POINTER(c_void_p), "c")),
        COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(c_void_p), "f")),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(c_int64), "d"),
                  (["out"], POINTER(c_int64), "m")),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wt.HANDLE, "h")),
        COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID), "iid"), (["out"], POINTER(c_void_p), "ppv")),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetActivateResult",
                  (["out"], POINTER(c_long), "hr"), (["out"], POINTER(POINTER(IUnknown)), "iface")),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ActivateCompleted",
                  (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "op")),
    ]


class IAgileObject(IUnknown):
    _iid_ = GUID("{94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90}")
    _methods_ = []


class _AoAtivar(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self):
        super().__init__()
        self.pronto = threading.Event()
        self.cliente = None
        self.erro = None

    def ActivateCompleted(self, this, op):
        try:
            hr, unk = op.GetActivateResult()
            if hr < 0:
                self.erro = f"ativacao falhou (0x{hr & 0xFFFFFFFF:08X})"
            else:
                self.cliente = unk.QueryInterface(IAudioClient)
        except Exception as e:  # nunca deixar excecao voltar pro Windows
            self.erro = str(e)
        self.pronto.set()
        return 0


class _BLOB(Structure):
    _fields_ = [("cbSize", c_ulong), ("pBlobData", c_void_p)]


class _PROPVARIANT(Structure):
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort), ("blob", _BLOB)]


class _LOOPBACK(Structure):
    _fields_ = [("TargetProcessId", c_ulong), ("ProcessLoopbackMode", c_int)]


class _ATIVACAO(Structure):
    _fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", _LOOPBACK)]


VT_BLOB = 65
ATIVACAO_PROCESSO = 1
INCLUIR_ARVORE = 0
LOOPBACK, EVENTO, AUTOCONVERTER = 0x00020000, 0x00040000, 0x80000000
SILENCIO = 0x2


def programas_com_som():
    """Nomes dos programas que tem sessao de audio agora (o que o mixer do Windows lista)."""
    from pycaw.pycaw import AudioUtilities
    eu = os.getpid()
    nomes = set()
    for s in AudioUtilities.GetAllSessions():
        try:
            if s.Process and s.ProcessId != eu:
                nomes.add(s.Process.name())
        except (psutil.Error, OSError):
            pass
    return sorted(nomes, key=str.lower)


def pid_raiz(nome):
    """O processo-pai de todos com esse nome. O Chrome toca o som num filho, entao
    pegar a raiz + 'incluir arvore' pega o som de todas as abas."""
    # so o NOME de todos; pai e hora de criacao so dos que bateram. Medido em
    # 08/10/2026: pedir os tres de todo processo levava 2,47 s e travava a janela
    achados = [p for p in psutil.process_iter(["name"])
               if (p.info["name"] or "").lower() == nome.lower()]
    if not achados:
        return None
    pids = {p.pid for p in achados}

    def pai(p):
        try:
            return p.ppid()
        except psutil.Error:
            return None

    def criado(p):
        try:
            return p.create_time()
        except psutil.Error:
            return 0

    raizes = [p for p in achados if pai(p) not in pids] or achados
    return min(raizes, key=criado).pid


class SomDePrograma(threading.Thread):
    """Le o som de um programa e chama ao_dado(bytes PCM 16 bits) a cada bloco."""

    def __init__(self, pid, taxa, canais, ao_dado):
        super().__init__(daemon=True)
        self.pid, self.taxa, self.canais, self.ao_dado = pid, taxa, canais, ao_dado
        self.erro = None
        self.iniciado = threading.Event()
        self._parar = threading.Event()

    def parar(self):
        self._parar.set()
        self.join(timeout=2)

    def run(self):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        k32 = ctypes.windll.kernel32
        evento = None
        try:
            params = _ATIVACAO(ATIVACAO_PROCESSO, _LOOPBACK(self.pid, INCLUIR_ARVORE))
            pv = _PROPVARIANT(vt=VT_BLOB)
            pv.blob.cbSize = sizeof(params)
            pv.blob.pBlobData = ctypes.addressof(params)

            ao = _AoAtivar()
            ativar = ctypes.WinDLL("Mmdevapi.dll").ActivateAudioInterfaceAsync
            ativar.argtypes = [wt.LPCWSTR, POINTER(GUID), c_void_p,
                               POINTER(IActivateAudioInterfaceCompletionHandler),
                               POINTER(POINTER(IActivateAudioInterfaceAsyncOperation))]
            ativar.restype = HRESULT
            op = POINTER(IActivateAudioInterfaceAsyncOperation)()
            ativar("VAD\\Process_Loopback", byref(IAudioClient._iid_), byref(pv),
                   ao.QueryInterface(IActivateAudioInterfaceCompletionHandler), byref(op))
            if not ao.pronto.wait(5) or not ao.cliente:
                raise RuntimeError(ao.erro or "o Windows nao respondeu a ativacao")
            cliente = ao.cliente

            bloco = self.canais * 2
            fmt = WAVEFORMATEX(1, self.canais, self.taxa, self.taxa * bloco, bloco, 16, 0)
            cliente.Initialize(0, LOOPBACK | EVENTO | AUTOCONVERTER, 2_000_000, 0, byref(fmt), None)
            evento = k32.CreateEventW(None, False, False, None)
            cliente.SetEventHandle(evento)
            ptr = cliente.GetService(byref(IAudioCaptureClient._iid_))
            captura = ctypes.cast(c_void_p(ptr), POINTER(IAudioCaptureClient))
            cliente.Start()
            self.iniciado.set()

            while not self._parar.is_set():
                k32.WaitForSingleObject(evento, 100)
                while True:
                    n = captura.GetNextPacketSize()
                    if not n:
                        break
                    dado, quadros, flags, _, _ = captura.GetBuffer()
                    if flags & SILENCIO:
                        pcm = bytes(quadros * bloco)
                    else:
                        pcm = ctypes.string_at(dado, quadros * bloco)
                    captura.ReleaseBuffer(quadros)
                    self.ao_dado(pcm)
            cliente.Stop()
        except Exception as e:
            self.erro = str(e)
            self.iniciado.set()
        finally:
            if evento:
                k32.CloseHandle(evento)
            comtypes.CoUninitialize()


if __name__ == "__main__":
    import time
    import numpy as np
    nome = sys.argv[1] if len(sys.argv) > 1 else "chrome.exe"
    print("programas com som:", programas_com_som())
    pid = pid_raiz(nome)
    print(nome, "pid raiz", pid)
    pedacos = []
    s = SomDePrograma(pid, 44100, 2, pedacos.append)
    s.start()
    s.iniciado.wait(5)
    time.sleep(3)
    s.parar()
    print("erro:", s.erro)
    x = np.frombuffer(b"".join(pedacos), np.int16)
    print(f"{len(x)/2/44100:.2f} s de som, pico {np.abs(x).max() if len(x) else 0}")
