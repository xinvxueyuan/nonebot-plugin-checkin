from pathlib import Path

import pytest

from nonebot_plugin_checkin import assets


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """默认断网：每个用例自己决定是否放行请求。"""

    async def _boom(*a, **kw):
        raise AssertionError("测试不应真实联网")

    monkeypatch.setattr(assets, "_http_get", _boom)


def test_bg_path_is_per_user(tmp_path: Path) -> None:
    p1 = assets.bg_path(tmp_path, 111)
    p2 = assets.bg_path(tmp_path, 222)
    assert p1 != p2
    assert p1.name == "111.webp"
    assert p1.suffix == ".webp"


def test_bg_is_fresh_respects_ttl(tmp_path: Path) -> None:
    import os
    import time

    p = assets.bg_path(tmp_path, 111)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 4096)
    now = time.time()
    os.utime(p, (now, now))
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15, now=now) is True
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15, now=now + 16 * 60) is False
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=0, now=now + 9e9) is True


def test_bg_is_fresh_false_when_missing_or_empty(tmp_path: Path) -> None:
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is False
    p = assets.bg_path(tmp_path, 111)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is False
    # 过小（<2048）也算坏文件
    p.write_bytes(b"RIFF" + b"0" * 100)
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is False


@pytest.mark.asyncio
async def test_ensure_bg_returns_cached_without_network(tmp_path: Path) -> None:
    p = assets.bg_path(tmp_path, 111)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 4096)
    out = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="k")
    assert out is not None
    assert out.read_bytes()[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_ensure_bg_returns_none_on_failure(tmp_path: Path, monkeypatch) -> None:
    async def _fail(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(assets, "_http_get", _fail)
    out = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="k")
    assert out is None
    assert not assets.bg_path(tmp_path, 111).exists()  # 失败绝不写负缓存


@pytest.mark.asyncio
async def test_ensure_bg_skips_when_key_empty(tmp_path: Path) -> None:
    out = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="")
    assert out is None


@pytest.mark.asyncio
async def test_fetch_signature_returns_none_without_bot(tmp_path: Path) -> None:
    assert await assets.fetch_signature(None, 1, 2) is None


# ── WebP 转换 ──


def _make_jpeg(w: int = 400, h: int = 300) -> bytes:
    """造一张有色彩变化的 JPEG（纯色图压缩后太小，触发不了体积断言）。"""
    import io

    from PIL import Image

    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_to_webp_returns_riff_container() -> None:
    out = assets.to_webp(_make_jpeg())
    assert out is not None
    assert out[:4] == b"RIFF"
    assert out[8:12] == b"WEBP", "必须是 WebP 容器"


def test_to_webp_shrinks_size() -> None:
    src = _make_jpeg()
    out = assets.to_webp(src)
    assert out is not None
    assert len(out) < len(src), f"WebP({len(out)}) 应小于原图({len(src)})"


def test_to_webp_downscales_long_edge() -> None:
    import io

    from PIL import Image

    out = assets.to_webp(_make_jpeg(2000, 1200))
    assert out is not None
    with Image.open(io.BytesIO(out)) as im:
        assert max(im.size) <= 1600, f"长边应 <=1600，实际 {im.size}"


def test_to_webp_returns_none_on_non_image() -> None:
    assert assets.to_webp(b"not an image at all") is None


def test_to_webp_handles_png_input() -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (100, 100), (255, 0, 0, 128)).save(buf, "PNG")
    out = assets.to_webp(buf.getvalue())
    assert out is not None and out[8:12] == b"WEBP"


@pytest.mark.asyncio
async def test_ensure_bg_writes_webp_not_raw(tmp_path: Path, monkeypatch) -> None:
    """落盘内容必须是 WebP，而不是原始 JPEG 字节（守住 WebP 转换这一步）。"""
    jpeg = _make_jpeg(400, 300)

    async def _fake_get(url: str, *, headers: dict[str, str], timeout: float) -> bytes:
        # 第一次拿列表，第二次拿图片字节
        if "count=1" in url:
            return b'[{"url":"https://xbm.example/i/abc.jpg"}]'
        return jpeg

    monkeypatch.setattr(assets, "_http_get", _fake_get)
    out = await assets.ensure_bg(tmp_path, 777, api_key="k")
    assert out is not None
    data = out.read_bytes()
    assert out.suffix == ".webp"
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", "落盘的必须是 WebP 容器"
    assert len(data) < len(jpeg), "WebP 应比原图小"
