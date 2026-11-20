"""Thumbs: leitura do index.html do gerador da equipe e gravação dos PNG."""
import base64
import io

from PIL import Image

from montador import thumbs


def _png_data_url(cor):
    b = io.BytesIO()
    Image.new("RGB", (1920, 1080), cor).save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def _gerador(tmp_path):
    html = f"""<html><head><style>
@font-face {{ font-family: 'Fonte Teste'; src: url('data:font/woff2;base64,AAAA') format('woff2'); }}
:root {{ --font-family-thumbnail: 'Fonte Teste'; --w-area: 84%; --h-area: 40%; --translate-w: 0%; --translate-h: -10%;
  --font-min: 1rem; --font-max: 90px; }}
.default-container {{ --w-area: 73%; --h-area: 37%; --translate-h: 0%; --translate-w: -1%; }}
.libras-container {{ --w-area: 75%; --h-area: 37%; --translate-h: 14%; --translate-w: 0%; }}
</style></head><body>
<script>window.base64 = window.base64 || {{}}; window.base64.thumb_2025 = "{_png_data_url((0, 90, 200))}";</script>
<script>window.base64 = window.base64 || {{}}; window.base64.thumb_libra_2025 = "{_png_data_url((0, 60, 160))}";</script>
<script>const thumbnailOptions = [
    {{ label: "Default", default: true, img: window.base64.thumb_2025, }},
    {{ label: "Libras", img: window.base64.thumb_libra_2025, }},
]</script></body></html>"""
    p = tmp_path / "index.html"
    p.write_text(html, encoding="utf-8")
    return p


def test_le_fonte_modelos_e_areas(tmp_path):
    m = thumbs.ler_modelo(_gerador(tmp_path))
    assert m["familia"] == "Fonte Teste" and "@font-face" in m["fonte_css"]
    ids = {o["id"]: o for o in m["opcoes"]}
    assert list(ids) == ["default", "libras"] and ids["default"]["padrao"] and not ids["libras"]["padrao"]
    assert ids["default"]["area"] == {"w": "73%", "h": "37%", "tw": "-1%", "th": "0%", "font_max": "90px", "font_min": "1rem"}
    assert ids["libras"]["area"]["th"] == "14%"
    assert ids["libras"]["img"].startswith("data:image/png;base64,")


def test_salva_com_o_nome_da_sequencia(tmp_path):
    png = _png_data_url((10, 20, 30))
    out = thumbs.salvar(tmp_path / "Saída", [{"nome": "01 Plataforma e Grafana: Stack", "png": png}])
    assert out[0].endswith("01 Plataforma e Grafana- Stack.png")
    with Image.open(out[0]) as im:
        assert im.size == (1920, 1080)


def test_sem_gerador_avisa(tmp_path):
    import pytest
    with pytest.raises(thumbs.ErroThumb):
        thumbs.ler_modelo(tmp_path / "nao-existe.html")
