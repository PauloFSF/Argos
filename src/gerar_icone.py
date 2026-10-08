r"""gerar_icone.py - desenha o icone do ARGOS (o gravador de jogo), em todos os tamanhos.

Argos e' o vigia de cem olhos da mitologia grega.

Desenho: um OLHO em ciano (#4CD4FF, o acento parado) cuja PUPILA e' o ponto
de gravar em brasa (#FF7A2F, o acento gravando). O vigia que nunca fecha o olho, gravando.
Variante "cem": atras do olho principal, olhos pequenos e apagados, os "cem olhos";
so aparece de 128 px pra cima, onde da pra ver.

Regras de desenho de icone:
- tamanho pequeno NAO e' o grande reduzido: ate 32 px e' redesenhado com traco grosso,
  sem iris e sem brilho, senao vira mancha na barra de tarefas;
- correcao otica: a pupila e' maior que a conta geometrica (circulo cheio entre tracos
  finos parece menor), e o olho sobe um pouco do centro (centro visual);
- respiro igual dos 4 lados.
Regra do desenho (azul e brasa nunca se encostam saturados): a iris (anel ciano) tem
vao ate a pupila brasa.

Uso > python gerar_icone.py   (sai em ../assets/icones/: argos.ico, argos.png e uma previa)
"""
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
for _l in (os.path.join(AQUI, "libs"), r"C:\Ferramentas\gravador-jogo\libs"):
    if os.path.isdir(_l):
        sys.path.insert(0, _l)
        break
from PIL import Image, ImageDraw  # noqa: E402

SAIDA = os.path.join(AQUI, "..", "assets", "icones")
CIANO = (76, 212, 255)
BRASA = (255, 122, 47)
FUNDO_TOPO = (24, 28, 36)
FUNDO_BAIXO = (10, 12, 16)


def amendoa(cx, cy, larg, alt, passos=90):
    """Contorno de olho: dois arcos de circulo que se encontram nos cantos."""
    w, h = larg / 2, alt / 2
    R = (h * h + w * w) / (2 * h)
    pts = []
    a0 = math.asin(w / R)
    for i in range(passos + 1):  # arco de cima, da esquerda pra direita
        a = -a0 + 2 * a0 * i / passos
        pts.append((cx + R * math.sin(a), cy + (R - h) - R * math.cos(a) + 0))
    for i in range(passos + 1):  # arco de baixo, da direita pra esquerda
        a = a0 - 2 * a0 * i / passos
        pts.append((cx + R * math.sin(a), cy - (R - h) + R * math.cos(a)))
    return pts


def olho(im, cx, cy, larg, alt, traco, cor):
    """Contorno como FORMA (amendoa de fora menos a de dentro), nao como linha: a linha
    grossa do PIL deixava os cantos do olho serrilhados ."""
    N = im.size[0]
    m = Image.new("L", (N, N), 0)
    md = ImageDraw.Draw(m)
    md.polygon(amendoa(cx, cy, larg, alt), fill=255)
    md.polygon(amendoa(cx, cy, larg - 2.7 * traco, alt - 2 * traco), fill=0)
    camada = Image.new("RGBA", (N, N), cor[:3] + (0,))
    camada.putalpha(m.point(lambda v: v * cor[3] // 255))
    return Image.alpha_composite(im, camada)


def desenhar(px, cem=True):
    pequeno = px <= 32
    S = 8 if px < 64 else 4
    N = px * S
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))

    # ---- fundo: quadrado arredondado, degrade vertical 
    margem = round(N * (0.03 if pequeno else 0.045))
    raio = round((N - 2 * margem) * 0.24)
    grad = Image.new("RGBA", (N, N))
    gd = ImageDraw.Draw(grad)
    for y in range(N):
        t = y / (N - 1)
        gd.line([(0, y), (N, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(FUNDO_TOPO, FUNDO_BAIXO)) + (255,))
    mascara = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([margem, margem, N - margem - 1, N - margem - 1], radius=raio, fill=255)
    im.paste(grad, (0, 0), mascara)
    d = ImageDraw.Draw(im)
    if not pequeno:
        d.rounded_rectangle([margem, margem, N - margem - 1, N - margem - 1], radius=raio,
                            outline=(255, 255, 255, 26), width=max(1, round(N * 0.006)))

    c = N / 2
    cy = c - N * 0.01  # centro visual: o olho sobe um pouco

    # ---- os "cem olhos": pequenos e apagados atras, so onde da pra ver
    # (de 128 px pra cima: em 64-96 eles viravam ruido em volta do olho)
    if cem and px >= 128:
        camada = Image.new("RGBA", (N, N), (0, 0, 0, 0))
        for ang in range(0, 360, 30):
            r = N * 0.355
            x, y = c + r * math.cos(math.radians(ang)), cy + r * math.sin(math.radians(ang)) * 0.92
            camada = olho(camada, x, y, N * 0.085, N * 0.046, N * 0.011, CIANO + (60,))
            ImageDraw.Draw(camada).ellipse([x - N * 0.011, y - N * 0.011, x + N * 0.011, y + N * 0.011],
                                           fill=CIANO + (60,))
        im = Image.alpha_composite(im, Image.composite(camada, Image.new("RGBA", (N, N), (0, 0, 0, 0)), mascara))
        d = ImageDraw.Draw(im)

    # ---- o olho principal
    larg = N * (0.74 if pequeno else 0.60)
    alt = N * (0.46 if pequeno else 0.355)
    traco = N * (0.075 if pequeno else 0.042)
    im = olho(im, c, cy, larg, alt, traco, CIANO + (255,))
    d = ImageDraw.Draw(im)

    # iris: anel ciano fino (so no grande; no pequeno some e vira ruido)
    if not pequeno:
        ri = N * 0.118
        d.ellipse([c - ri, cy - ri, c + ri, cy + ri], outline=CIANO + (255,), width=round(N * 0.024))

    # pupila = o ponto de gravar (maior que a conta: correcao otica)
    # SEM brilho em volta: o brilho brasa caia em cima do anel ciano e o deixava cinza
    # (azul e brasa nao se encostam)
    rp = N * (0.125 if pequeno else 0.07)
    d.ellipse([c - rp, cy - rp, c + rp, cy + rp], fill=BRASA + (255,))
    return im.resize((px, px), Image.LANCZOS)


def previa(arquivo, cem):
    tamanhos = [16, 20, 24, 32, 48, 64, 96, 128, 256]
    larg = sum(tamanhos) + 20 * (len(tamanhos) + 1)
    p = Image.new("RGB", (larg, 2 * 296), (8, 9, 11))
    ImageDraw.Draw(p).rectangle([0, 296, larg, 592], fill=(243, 243, 243))
    x = 20
    for t in tamanhos:
        im = desenhar(t, cem)
        for y0 in (148 - t // 2, 296 + 148 - t // 2):
            p.paste(im, (x, y0), im)
        x += t + 20
    p.save(arquivo)


def main():
    os.makedirs(SAIDA, exist_ok=True)
    cem = "--sem-cem" not in sys.argv
    if "--previas" in sys.argv:  # compara as duas variantes antes de escolher
        previa(os.path.join(SAIDA, "argos_previa_cem.png"), True)
        previa(os.path.join(SAIDA, "argos_previa_um.png"), False)
        print("previas ok")
        return
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    imgs = {t: desenhar(t, cem) for t in tamanhos}
    ico = os.path.join(SAIDA, "argos.ico")
    imgs[256].save(ico, sizes=[(t, t) for t in tamanhos], append_images=[imgs[t] for t in tamanhos if t != 256])
    imgs[256].save(os.path.join(SAIDA, "argos.png"))
    desenhar(1024, cem).save(os.path.join(SAIDA, "argos_1024.png"))
    previa(os.path.join(SAIDA, "argos_previa.png"), cem)
    print("ok", ico)


if __name__ == "__main__":
    main()
