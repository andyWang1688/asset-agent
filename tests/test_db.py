import sqlite3

import pytest

from app import db


def test_page_upsert_and_search(workspace):
    db.upsert_page("projects/demo.md", "Demo 项目", "这是 Demo 项目的介绍，包含订单服务信息。")
    rows = db.search_pages("Demo 项目", limit=5)
    assert any(r["path"] == "projects/demo.md" for r in rows)
    # 短查询走 LIKE 回退
    rows2 = db.search_pages("项目", limit=5)
    assert any(r["path"] == "projects/demo.md" for r in rows2)
    # 更新覆盖
    db.upsert_page("projects/demo.md", "Demo 项目", "更新后的内容")
    row = db.get_page("projects/demo.md")
    assert row["content"] == "更新后的内容"
    assert len(db.list_pages()) == 1


def test_model_config_and_kv(workspace):
    cfg_id = db.upsert_model_config(None, "x", "deepseek", "", "enc", "deepseek-chat", True)
    db.activate_model_config(cfg_id)
    rows = db.list_model_configs()
    assert rows[0]["is_active"] == 1
    assert rows[0]["role"] == "knowledge"  # 缺省角色：知识库
    db.kv_set("k", "v")
    assert db.kv_get("k") == "v"


def test_model_role_isolation(workspace):
    """knowledge/security 各自独立激活：同角色互斥，跨角色互不影响。"""
    k1 = db.upsert_model_config(None, "k1", "deepseek", "", "enc", "m", True, "knowledge")
    s1 = db.upsert_model_config(None, "s1", "custom", "http://127.0.0.1:9001/v1", "", "m", True, "security")
    db.activate_model_config(k1)
    db.activate_model_config(s1)
    k2 = db.upsert_model_config(None, "k2", "glm", "", "enc2", "m", False, "knowledge")
    db.activate_model_config(k2)
    assert db.get_model_config(k1)["is_active"] == 0  # 同角色互斥
    assert db.get_model_config(k2)["is_active"] == 1
    assert db.get_model_config(s1)["is_active"] == 1  # 跨角色不受影响
    assert db.get_active_model_config("knowledge")["id"] == k2
    assert db.get_active_model_config("security")["id"] == s1


def test_model_migration_normalizes_multi_active(workspace):
    """老库同角色多激活：迁移归一化为至多一个激活（fail-closed）。"""
    db.upsert_model_config(None, "a", "deepseek", "", "enc", "m", True, "knowledge")
    db.upsert_model_config(None, "b", "deepseek", "", "enc", "m", True, "knowledge")
    db._migrate()
    active = [r for r in db.list_model_configs() if r["role"] == "knowledge" and r["is_active"]]
    assert len(active) == 1


def test_model_active_switch_atomic_and_unique_index(workspace):
    """保存 is_active=True 即在同一事务内完成停旧+激活；部分唯一索引兜底数据库级约束。"""
    k1 = db.upsert_model_config(None, "k1", "deepseek", "", "enc", "m", True, "knowledge")
    k2 = db.upsert_model_config(None, "k2", "glm", "", "enc", "m", True, "knowledge")  # 原子切换
    assert db.get_model_config(k1)["is_active"] == 0
    assert db.get_model_config(k2)["is_active"] == 1
    # 数据库级约束：绕过应用层也无法造出同角色第二个激活
    with pytest.raises(sqlite3.IntegrityError):
        db._w("UPDATE model_configs SET is_active=1 WHERE id=?", (k1,))
    idx = [r["name"] for r in db._r("PRAGMA index_list(model_configs)")]
    assert "idx_model_configs_active_role" in idx
