import asyncio
import hashlib
import json
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
    # 半截 / 非 WebP 容器也算坏文件（判据是文件头，不是体积）
    p.write_bytes(b"RIFF" + b"0" * 100)
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is False
    p.write_bytes(b"GIF89a" + b"0" * 4096)
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is False


def test_bg_is_fresh_accepts_small_but_valid_webp(tmp_path: Path) -> None:
    """小图（<2KB）也是合法缓存：不能按体积判坏，否则每次都重新下载。"""
    p = assets.bg_path(tmp_path, 111)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP")
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=15) is True
    assert assets.bg_is_fresh(tmp_path, 111, ttl_minutes=0) is True


@pytest.mark.asyncio
async def test_ensure_bg_small_webp_cached_on_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有效小 WebP 落盘后，第二次调用必须命中缓存、完全不联网。"""
    small = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 64  # 76 字节，远小于 2KB
    calls = 0

    async def _fake_get(*a, **kw):
        nonlocal calls
        calls += 1
        return b'[{"url": "https://x/a.png"}]'

    def _fake_fetch(*a, **kw):
        return small

    monkeypatch.setattr(assets, "_http_get", _fake_get)
    monkeypatch.setattr(assets, "to_webp", lambda *a, **kw: small)
    first = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="k")
    assert first is not None and first.exists()
    assert calls > 0, "首次必须真的取图"
    calls_after_first = calls
    second = await assets.ensure_bg(
        tmp_path, 111, url="http://x/v1/random", api_key="k"
    )
    assert second == first
    assert calls == calls_after_first, "第二次必须命中缓存，不得再联网"


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
async def test_ensure_bg_skips_when_key_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空 key 必须完全不发请求（`out is None` 挡不住「偷偷发一次」）。"""
    calls = 0

    async def _counted(*a, **kw):
        nonlocal calls
        calls += 1
        return b"[]"

    monkeypatch.setattr(assets, "_http_get", _counted)
    out = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="")
    assert out is None
    assert calls == 0, "key 为空不得发起任何请求"


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
        assert max(im.size) <= 800, f"长边应 <=800，实际 {im.size}"


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

    async def _fake_get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        follow_redirects: bool = True,
        max_bytes: int | None = None,
    ) -> bytes:
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


def test_to_webp_limits_portrait_long_edge() -> None:
    """竖图（长边在 y 轴）也必须缩到 800，不能留 1600。"""
    import io

    from PIL import Image

    out = assets.to_webp(_make_jpeg(600, 2400))
    assert out is not None
    with Image.open(io.BytesIO(out)) as im:
        assert max(im.size) <= 800, f"长边应 <=800，实际 {im.size}"


@pytest.mark.asyncio
async def test_fetch_signature_survives_cache_error(
    tmp_path: Path, monkeypatch
) -> None:
    """签名缓存读失败不能让签到回执整条挂掉。"""

    def boom(*a, **kw):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(assets.store, "signature_is_fresh", boom)
    assert await assets.fetch_signature(None, 1, 2) is None


@pytest.mark.asyncio
async def test_fetch_signature_has_timeout(monkeypatch) -> None:
    """协议端不回时，签名请求必须有上限，不能把回执吊死。"""
    import asyncio

    class SlowBot:
        async def get_stranger_info(self, **kwargs):
            await asyncio.sleep(30)  # 远超超时

    monkeypatch.setattr(assets, "_SIGNATURE_TIMEOUT_SECONDS", 0.2)
    got = await assets.fetch_signature(SlowBot(), 1, 2)  # type: ignore[arg-type]
    assert got is None


@pytest.mark.asyncio
async def test_ensure_bg_uses_unique_temp_file(tmp_path: Path) -> None:
    """并发刷新不能共用同一个 .part 路径。"""
    import re

    seen: list[str] = []
    orig_write = None

    import pathlib

    orig_write = pathlib.Path.write_bytes

    def spy(self, data):
        seen.append(str(self))
        return orig_write(self, data)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pathlib.Path, "write_bytes", spy)
    try:

        async def _fake_get(
            url: str,
            *,
            headers: dict[str, str],
            timeout: float,
            follow_redirects: bool = True,
            max_bytes: int | None = None,
        ) -> bytes:
            if "count=1" in url:
                return b'[{"url":"https://xbm.example/i/abc.jpg"}]'
            return _make_jpeg()

        monkeypatch.setattr(assets, "_http_get", _fake_get)
        await assets.ensure_bg(tmp_path, 999, api_key="k")
    finally:
        monkeypatch.undo()
    assert seen, "没有落盘"
    # 临时文件名必须含随机后缀，不能是固定的 .webp.part
    assert not re.search(r"\.webp\.part$", seen[0]), f"临时文件名不可复用: {seen[0]}"


def test_prune_removes_stale_and_part_files(tmp_path: Path) -> None:
    """过期背景图与残留 .part 必须被清理，避免磁盘无限增长。"""
    import os
    import time

    bg_dir = tmp_path / "backgrounds"
    bg_dir.mkdir(parents=True)
    now = time.time()

    fresh = bg_dir / "1.webp"
    fresh.write_bytes(b"RIFF" + b"0" * 4096)
    stale = bg_dir / "2.webp"
    stale.write_bytes(b"RIFF" + b"0" * 4096)
    part = bg_dir / "3.webp.abc.part"
    part.write_bytes(b"x")

    # 让 stale 看起来是一天前的（TTL 15min + 1h 余量）
    old = now - 26 * 3600
    os.utime(stale, (old, old))
    os.utime(fresh, (now, now))

    removed = assets.prune_backgrounds(tmp_path, ttl_minutes=15, now=now)
    assert removed == 2
    assert fresh.exists(), "未过期的不能删"
    assert not stale.exists(), "过期的应被删"
    assert not part.exists(), "残留 .part 应被删"


@pytest.mark.asyncio
async def test_fetch_signature_caches_empty_signature(monkeypatch) -> None:
    """空签名也要落库占位，否则每人每次都重新打协议端。"""
    saved: list[tuple[int, int, str]] = []

    monkeypatch.setattr(assets.store, "signature_is_fresh", lambda *a, **kw: False)
    monkeypatch.setattr(
        assets.store, "save_signature", lambda g, u, s, **kw: saved.append((g, u, s))
    )

    class Bot:
        async def get_stranger_info(self, **kwargs):
            return {"long_nick": ""}  # 有字段但为空

    got = await assets.fetch_signature(Bot(), 1, 2)  # type: ignore[arg-type]
    assert got is None
    assert saved == [(1, 2, "")], f"空签名应以空串落库，实际 {saved}"


@pytest.mark.asyncio
async def test_ensure_bg_rejects_oversized_image(tmp_path: Path, monkeypatch) -> None:
    """上游返回超大图时必须拒绝（防 OOM）。"""
    monkeypatch.setattr(assets, "_MAX_IMAGE_BYTES", 1024)

    async def _huge(url: str, **kw):
        raise ValueError("响应体积超过上限 1024，已中止下载")

    monkeypatch.setattr(assets, "_http_get", _huge)
    out = await assets.ensure_bg(tmp_path, 555, api_key="k")
    assert out is None
    assert not assets.bg_path(tmp_path, 555).exists()


def test_quote_tail_hides_divider_for_blank(tmp_path=None) -> None:
    """纯空白引用不能只留一条分隔线。"""
    from nonebot_plugin_checkin import render

    assert render._quote_tail("") == ""
    assert render._quote_tail("   ") == ""
    assert render._quote_tail(None) == ""
    assert 'class="divider"' in render._quote_tail("有内容")


def test_to_webp_rejects_pixel_bomb() -> None:
    """小文件大像素（8000×8000 纯色 PNG ≈0.19MB）必须拒绝：解码要 ~183MB。"""
    import io

    from PIL import Image

    im = Image.new("RGB", (8000, 8000), (10, 20, 30))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    assert assets.to_webp(buf.getvalue()) is None


def test_to_webp_accepts_normal_size() -> None:
    """预算内的图片仍应正常转换。"""
    out = assets.to_webp(_make_jpeg(1200, 1600))
    assert out is not None and out[8:12] == b"WEBP"


def test_prune_survives_enumeration_error(tmp_path: Path, monkeypatch) -> None:
    """目录不可枚举时清理要静默返回，不能抛给调用方。"""
    bg_dir = tmp_path / "backgrounds"
    bg_dir.mkdir(parents=True)

    def boom(*a, **kw):
        raise PermissionError("denied")

    monkeypatch.setattr(type(bg_dir), "iterdir", boom)
    assert assets.prune_backgrounds(tmp_path, ttl_minutes=15) == 0


@pytest.mark.asyncio
async def test_fetch_signature_uses_request_start_time(monkeypatch) -> None:
    """保存必须用「请求开始」的时间戳，否则并发下旧签名会盖掉新签名。"""
    saved: list[dict] = []

    monkeypatch.setattr(assets.store, "signature_is_fresh", lambda *a, **kw: False)
    monkeypatch.setattr(
        assets.store,
        "save_signature",
        lambda g, u, s, **kw: saved.append({"g": g, "u": u, "s": s, **kw}),
    )

    class Bot:
        async def get_stranger_info(self, **kwargs):
            return {"long_nick": "新签名"}

    await assets.fetch_signature(Bot(), 1, 2)  # type: ignore[arg-type]
    assert saved and "now" in saved[0], f"必须传 now=，实际 {saved}"


# ── 同群不撞图（背景图去重） ──


class _FakeLibrary:
    """假 xbm 上游：固定图库，`?count=N` 一次发 N 个互不重复的 URL。

    故意**永远从第一张发**（最坏情况：每次请求都先给同一张），
    这样"两人同群会不会撞"就完全取决于分配逻辑，而不是上游给不给面子。
    每次请求都 `await asyncio.sleep(0)`，让并发用例真的能交错。
    """

    def __init__(self, images: dict[str, bytes]) -> None:
        self.images = images
        self.order = list(images)
        self.requests: list[str] = []

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
        follow_redirects: bool = True,
        max_bytes: int | None = None,
    ) -> bytes:
        self.requests.append(url)
        await asyncio.sleep(0)  # 交出控制权：并发场景才会真的交错
        if "count=" in url:
            count = int(url.rsplit("count=", 1)[1].split("&", 1)[0])
            picked = self.order[:count]
            payload = [{"url": f"https://xbm.example/i/{name}.jpg"} for name in picked]
            return json.dumps(payload).encode()
        name = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        return self.images[name]


def _library() -> _FakeLibrary:
    """三张互不相同的图（尺寸不同 → 像素不同 → WebP 也不同）。"""
    return _FakeLibrary({
        "a": _make_jpeg(120, 80),
        "b": _make_jpeg(121, 80),
        "c": _make_jpeg(122, 80),
    })


@pytest.mark.asyncio
async def test_same_group_users_get_different_backgrounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同群两人必须拿到不同的图 —— 生产上"两人 md5 相同"那次事故的回归测试。"""
    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1 = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    p2 = await assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9001)
    assert p1 is not None and p2 is not None
    assert p1.read_bytes() != p2.read_bytes(), "同群两人拿到了同一张背景图"
    index = json.loads(assets.bg_index_path(tmp_path).read_text(encoding="utf-8"))
    assert index["111"]["sha256"] != index["222"]["sha256"]
    assert index["111"]["group_id"] == index["222"]["group_id"] == 9001


@pytest.mark.asyncio
async def test_different_groups_may_share_one_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """去重只限本群：图库只有一张时，两个群都能用它（否则小图库会互相饿死）。"""
    lib = _FakeLibrary({"a": _make_jpeg(120, 80)})
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1 = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    p2 = await assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9002)
    assert p1 is not None and p2 is not None
    assert p1.read_bytes() == p2.read_bytes(), "不同群不该互相让位"


@pytest.mark.asyncio
async def test_concurrent_same_group_users_still_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发签到（asyncio.gather）也要两人不同图，且索引文件必须还能解析。"""
    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1, p2 = await asyncio.gather(
        assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001),
        assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9001),
    )
    assert p1 is not None and p2 is not None
    assert p1.read_bytes() != p2.read_bytes(), "并发下两人撞了同一张图"
    index = json.loads(assets.bg_index_path(tmp_path).read_text(encoding="utf-8"))
    assert set(index) == {"111", "222"}
    assert index["111"]["sha256"] != index["222"]["sha256"]


@pytest.mark.asyncio
async def test_bg_index_records_upstream_identity_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """索引落盘：记的是**上游原图** sha256，重新从磁盘读回仍能据此避免撞图。"""
    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1 = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    assert p1 is not None
    records = assets.read_bg_index(tmp_path)  # 等价于进程重启后重新读盘
    record = records[111]
    assert record["sha256"] == hashlib.sha256(lib.images["a"]).hexdigest()
    assert record["group_id"] == 9001
    assert record["assigned_at"] > 0
    p2 = await assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9001)
    assert p2 is not None
    assert p2.read_bytes() != p1.read_bytes(), "重启后读回索引失败 → 又撞图了"


@pytest.mark.asyncio
async def test_upstream_total_failure_writes_no_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上游全军覆没：不写背景图、不写索引（绝不写负缓存）。"""

    async def _boom(*a, **kw):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(assets, "_http_get", _boom)
    out = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    assert out is None
    assert not assets.bg_path(tmp_path, 111).exists()
    assert not assets.bg_index_path(tmp_path).exists()


@pytest.mark.asyncio
async def test_corrupt_bg_index_is_tolerated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """索引被写坏（半截 JSON）也不能让签到没图：按空表处理并重写成合法 JSON。"""
    path = assets.bg_index_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"111": {"sha256": "cut-of', encoding="utf-8")
    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    out = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    assert out is not None
    index = json.loads(path.read_text(encoding="utf-8"))
    assert "111" in index, "坏索引应被重写成合法 JSON"


@pytest.mark.asyncio
async def test_expired_assignment_does_not_block_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """对方那张早该轮换了（过期）→ 不算占用，别人可以复用。"""
    import os
    import time

    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1 = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    assert p1 is not None
    first = p1.read_bytes()  # 先留底：过期文件随后会被 prune 掉
    old = time.time() - 26 * 3600  # 远超 TTL 15min
    os.utime(p1, (old, old))
    p2 = await assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9001)
    assert p2 is not None
    assert p2.read_bytes() == first, "过期占用不该继续挡人"


@pytest.mark.asyncio
async def test_all_candidates_taken_falls_back_to_a_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """图库只有一张时不能"为了去重让人没背景"：宁可撞图也必须出图。"""
    lib = _FakeLibrary({"a": _make_jpeg(120, 80)})
    monkeypatch.setattr(assets, "_http_get", lib.get)
    p1 = await assets.ensure_bg(tmp_path, 111, api_key="k", group_id=9001)
    p2 = await assets.ensure_bg(tmp_path, 222, api_key="k", group_id=9001)
    assert p1 is not None and p2 is not None
    assert p2.read_bytes() == p1.read_bytes()
    index = json.loads(assets.bg_index_path(tmp_path).read_text(encoding="utf-8"))
    assert index["222"]["sha256"] == index["111"]["sha256"]


@pytest.mark.asyncio
async def test_without_group_id_keeps_single_draw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """老调用方（不传 group_id）行为不变：一次只要一张候选。"""
    lib = _library()
    monkeypatch.setattr(assets, "_http_get", lib.get)
    out = await assets.ensure_bg(tmp_path, 111, url="http://x/v1/random", api_key="k")
    assert out is not None
    assert any("count=1" in u for u in lib.requests), lib.requests
