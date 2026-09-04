import pytest
from fluxcatch.store import Store

def test_create_and_get(store):
    t = store.create_task(kind="direct", source_url="http://example.com/video.mp4", title="test")
    assert t["id"]
    fetched = store.get(t["id"])
    assert fetched["source_url"]=="http://example.com/video.mp4"
    assert fetched["status"]=="pending"

def test_valid_transition(store):
    t = store.create_task(kind="direct", source_url="http://example.com/a.mp4")
    tid = t["id"]
    store.update_status(tid, "active")
    assert store.get(tid)["status"]=="active"
    store.update_status(tid, "paused")
    assert store.get(tid)["status"]=="paused"
    store.update_status(tid, "active")
    assert store.get(tid)["status"]=="active"
    store.update_status(tid, "done")
    assert store.get(tid)["status"]=="done"

def test_invalid_transition(store):
    t = store.create_task(kind="direct", source_url="http://example.com/b.mp4")
    tid = t["id"]
    store.update_status(tid, "active")
    store.update_status(tid, "done")
    with pytest.raises(ValueError):
        store.update_status(tid, "active")

def test_error_transition(store):
    t = store.create_task(kind="direct", source_url="http://example.com/c.mp4")
    tid = t["id"]
    store.update_status(tid, "active")
    store.set_error(tid, "err_network")
    assert store.get(tid)["status"]=="error"
    assert store.get(tid)["error"]=="err_network"
    # retry -> pending
    store.update_status(tid, "pending")
    assert store.get(tid)["status"]=="pending"
    assert store.get(tid)["error"] is None

def test_list_order(store):
    t1 = store.create_task(kind="direct", source_url="http://example.com/1.mp4")
    t2 = store.create_task(kind="direct", source_url="http://example.com/2.mp4")
    lst = store.list()
    assert lst[0]["id"]==t2["id"] # desc

def test_update_progress(store):
    t = store.create_task(kind="direct", source_url="http://example.com/d.mp4")
    store.update_progress(t["id"], 123, size_total=1000)
    fetched = store.get(t["id"])
    assert fetched["size_done"]==123
    assert fetched["size_total"]==1000
