import json

from app.query import index


def test_build_search_delete_and_rebuild_from_markdown(settings):
    page = settings.wiki_dir / "projects" / "orders.md"
    page.write_text("# 订单服务\n缓存与订单写入流程。", encoding="utf-8")

    result = index.build(settings)
    assert result["pages"] == 1
    assert index.search(settings, "订单服务")[0]["path"] == "projects/orders.md"
    assert json.loads(index.index_path(settings).read_text(encoding="utf-8"))["pages"][0]["title"] == "订单服务"

    index.delete(settings)
    assert page.exists()
    assert index.search(settings, "订单服务") == []

    index.rebuild(settings)
    assert index.search(settings, "订单服务")[0]["path"] == "projects/orders.md"


def test_index_never_persists_secret_text(settings):
    secret = "password=Sup3rSecret!"
    (settings.wiki_dir / "sources" / "safe.md").write_text(
        f"# 安全页面\n{secret}\n普通内容", encoding="utf-8"
    )
    index.build(settings)
    raw = index.index_path(settings).read_text(encoding="utf-8")
    assert secret not in raw
    assert "Sup3rSecret!" not in json.dumps([dict(row) for row in __import__("app").db.list_pages()])
