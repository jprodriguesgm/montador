"""Desenha o ícone do Montador (original): chave allen de montar móveis sobre peças em faixas, como uma timeline.

    python tools/fazer_icone.py      -> packaging/icon/icon.png, icon.icns, icon.ico
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
SAIDA = Path(__file__).resolve().parent.parent / "packaging" / "icon"


def _gradiente(w, h, c1, c2):
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        g.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(c1, c2)))
    return g.resize((w, h))


def desenhar(s=S) -> Image.Image:
    k = s / 1024
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    m = round(100 * k)                      # margem padrão dos ícones do Mac
    lado = s - 2 * m
    fundo = _gradiente(lado, lado, (52, 104, 214), (20, 38, 92)).convert("RGBA")
    mask = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, lado - 1, lado - 1), radius=round(185 * k), fill=255)
    sombra = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle((m, m + 14 * k, s - m, s - m + 14 * k), radius=round(185 * k),
                                             fill=(0, 0, 0, 110))
    base.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(18 * k)))
    base.paste(fundo, (m, m), mask)
    camada = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    P = lambda *v: tuple(round(x * k) for x in v)  # noqa: E731

    # peças (tábuas de móvel / faixas da timeline), em degraus
    pecas = [((215, 520, 765, 610), (240, 98, 146)),
             ((285, 635, 835, 725), (255, 183, 77)),
             ((185, 750, 735, 840), (129, 212, 250))]
    for (x0, y0, x1, y1), cor in pecas:
        d.rounded_rectangle(P(x0, y0 + 12, x1, y1 + 12), radius=round(24 * k), fill=(8, 16, 40, 120))
    base.alpha_composite(camada.filter(ImageFilter.GaussianBlur(6 * k)))
    camada = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    for (x0, y0, x1, y1), cor in pecas:
        d.rounded_rectangle(P(x0, y0, x1, y1), radius=round(24 * k), fill=cor)
        d.rounded_rectangle(P(x0, y0, x1, y0 + 14), radius=round(10 * k), fill=tuple(min(255, c + 30) for c in cor))
        for fx in (x0 + 50, x1 - 50):                         # furos de parafuso
            cy = (y0 + y1) // 2
            d.ellipse(P(fx - 15, cy - 15, fx + 15, cy + 15), fill=tuple(round(c * 0.62) for c in cor))
    base.alpha_composite(camada)

    # chave allen em L: o braço curto desce até o furo da primeira peça
    import math
    chave = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    c = ImageDraw.Draw(chave)
    w = round(70 * k)
    canto, ponta, cabo = P(715, 245), P(715, 470), P(300, 190)
    branco = (255, 255, 255, 255)
    for a1, b1 in ((cabo, canto), (canto, ponta)):
        c.line([a1, b1], fill=branco, width=w)
    for x, y in (cabo, canto):
        c.ellipse((x - w // 2, y - w // 2, x + w // 2, y + w // 2), fill=branco)
    cx, cy = ponta
    r = w * 0.58
    c.polygon([(cx + r * math.cos(math.radians(60 * i)), cy + r * math.sin(math.radians(60 * i))) for i in range(6)],
              fill=(214, 226, 248, 255))
    sombra_c = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sombra_c.paste((5, 12, 35, 140), (0, 0), chave.split()[3])
    base.alpha_composite(sombra_c.filter(ImageFilter.GaussianBlur(12 * k)), P(8, 16))
    base.alpha_composite(chave)
    return base


if __name__ == "__main__":
    SAIDA.mkdir(parents=True, exist_ok=True)
    im = desenhar()
    im.save(SAIDA / "icon.png")
    im.save(SAIDA / "icon.icns", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    im.save(SAIDA / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok", SAIDA)
