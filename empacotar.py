r"""empacotar.py - monta o Argos.exe (pasta pronta pra qualquer Windows) e o .zip de download.

O que vai dentro: Python, as bibliotecas, o ffmpeg, as fontes e o icone. Quem baixa so
descompacta e abre o Argos.exe, sem instalar nada.

Precisa de: uv (https://docs.astral.sh/uv/) e o ffmpeg.exe (caminho em --ffmpeg, ou o do PATH).

Uso:
    python empacotar.py                       # usa o ffmpeg do PATH
    python empacotar.py --ffmpeg C:\caminho\ffmpeg.exe

Sai em dist/Argos/ (a pasta) e dist/Argos-Windows.zip (o download do GitHub).
Depois de montar, roda o AUTOTESTE do proprio pacote (Argos.exe --autoteste): abre, grava
4 s e confere o arquivo. Pacote que nao grava nao sai.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(RAIZ, "dist")
LIBS = ["pyinstaller", "numpy", "pillow", "pyaudiowpatch", "comtypes", "pycaw", "psutil", "customtkinter"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    ap.add_argument("--sem-teste", action="store_true")
    a = ap.parse_args()
    if not a.ffmpeg or not os.path.exists(a.ffmpeg):
        sys.exit("ffmpeg.exe nao achado: passe --ffmpeg C:\\caminho\\ffmpeg.exe")
    ffmpeg = os.path.realpath(a.ffmpeg)
    sep = os.pathsep
    cmd = ["uv", "run", "--no-project", "--python", "3.12"]
    for lib in LIBS:
        cmd += ["--with", lib]
    cmd += ["pyinstaller", "--noconfirm", "--clean", "--windowed", "--name", "Argos",
            "--icon", os.path.join(RAIZ, "assets", "icones", "argos.ico"),
            "--add-data", os.path.join(RAIZ, "assets", "fontes") + sep + "fontes",
            "--add-data", os.path.join(RAIZ, "assets", "icones") + sep + "icones",
            "--add-binary", ffmpeg + sep + "ffmpeg",
            "--collect-all", "customtkinter", "--collect-all", "pyaudiowpatch",
            "--hidden-import", "pycaw.pycaw", "--hidden-import", "comtypes.stream",
            "--distpath", DIST, "--workpath", os.path.join(RAIZ, "build"),
            "--specpath", os.path.join(RAIZ, "build"),
            os.path.join(RAIZ, "src", "argos.pyw")]
    print("montando...", flush=True)
    subprocess.run(cmd, check=True, cwd=RAIZ)

    pasta = os.path.join(DIST, "Argos")
    # licencas que precisam ir junto do que foi redistribuido
    lic = os.path.join(pasta, "licencas")
    os.makedirs(lic, exist_ok=True)
    shutil.copy(os.path.join(RAIZ, "assets", "fontes", "LEIAME.md"), os.path.join(lic, "fontes.md"))
    lic_ff = os.path.join(os.path.dirname(os.path.dirname(ffmpeg)), "LICENSE")
    if os.path.exists(lic_ff):
        shutil.copy(lic_ff, os.path.join(lic, "ffmpeg-LICENSE.txt"))
    with open(os.path.join(lic, "ffmpeg.md"), "w", encoding="utf-8") as f:
        f.write("O ffmpeg.exe incluido e' a build 'full' de https://www.gyan.dev/ffmpeg/builds/ "
                "(licenca GPL v3). O codigo-fonte do ffmpeg esta em https://ffmpeg.org e "
                "https://github.com/GyanD/codexffmpeg.\n")

    if not a.sem_teste:
        autoteste(pasta)

    zipar = os.path.join(DIST, "Argos-Windows.zip")
    if os.path.exists(zipar):
        os.remove(zipar)
    with zipfile.ZipFile(zipar, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for raiz, _, arqs in os.walk(pasta):
            for n in arqs:
                cam = os.path.join(raiz, n)
                z.write(cam, os.path.join("Argos", os.path.relpath(cam, pasta)))
    print(f"PRONTO > {zipar}  ({os.path.getsize(zipar) / 1e6:.0f} MB)")


def autoteste(pasta):
    saida = os.path.join(os.environ.get("TEMP", "."), "argos_autoteste.json")
    if os.path.exists(saida):
        os.remove(saida)
    print("autoteste do pacote (abre, grava 4 s, fecha)...", flush=True)
    p = subprocess.Popen([os.path.join(pasta, "Argos.exe"), "--autoteste"])
    try:
        p.wait(timeout=120)
    except subprocess.TimeoutExpired:
        p.kill()
        sys.exit("AUTOTESTE FALHOU: o Argos.exe nao terminou em 120 s")
    if not os.path.exists(saida):
        sys.exit("AUTOTESTE FALHOU: o Argos.exe fechou sem gravar (sem resultado)")
    r = json.load(open(saida, encoding="utf-8"))
    arq = r.get("arquivo")
    if not arq or not os.path.exists(arq) or os.path.getsize(arq) == 0:
        sys.exit(f"AUTOTESTE FALHOU: {r}")
    if not os.path.abspath(r.get("ffmpeg", "")).lower().startswith(os.path.abspath(pasta).lower()):
        sys.exit(f"AUTOTESTE FALHOU: usou o ffmpeg de fora do pacote: {r.get('ffmpeg')}")
    print(f"autoteste ok: {os.path.basename(arq)} ({os.path.getsize(arq) / 1e6:.1f} MB), "
          f"fontes {r.get('fontes')}, placas {list((r.get('codificadores') or {}).keys())}")
    time.sleep(1)


if __name__ == "__main__":
    main()
