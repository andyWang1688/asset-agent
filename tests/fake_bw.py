#!/usr/bin/env python3
"""Fake bw CLI（仅测试用）：模拟 config/login/unlock/template/encode/create/list/get/edit/delete。"""
import base64
import json
import os
import sys

STATE_PATH = os.environ.get("BW_FAKE_STATE", "/tmp/bw_fake_state.json")


def load():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"items": []}


def save(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)


def main():
    args = sys.argv[1:]
    if not args:
        return
    if args[0] == "config":
        print(""); return
    if args[0] == "login":
        print(""); return
    if args[0] == "unlock":
        print("sess-fake"); return
    if args[0] == "get" and args[1] == "template":
        print(json.dumps({"type": 1, "name": "", "notes": None, "login": {}})); return
    if args[0] == "get" and args[1] == "item":
        state = load()
        for it in state["items"]:
            if it["id"] == args[2]:
                print(json.dumps(it)); return
        print("not found", file=sys.stderr); sys.exit(1)
    if args[0] == "encode":
        raw = sys.stdin.read()
        print(base64.b64encode(raw.encode()).decode()); return
    if args[0] == "create" and args[1] == "item":
        raw = base64.b64decode(args[2]).decode()
        item = json.loads(raw)
        state = load()
        item["id"] = f"vw-{len(state['items']) + 1}"
        item["revisionDate"] = "2026-08-15T00:00:00.000Z"
        state["items"].append(item)
        save(state)
        print(json.dumps(item)); return
    if args[0] == "edit":
        raw = base64.b64decode(args[3]).decode()
        item = json.loads(raw)
        state = load()
        state["items"] = [item if it["id"] == item["id"] else it for it in state["items"]]
        save(state)
        print(json.dumps(item)); return
    if args[0] == "list" and args[1] == "items":
        print(json.dumps(load()["items"])); return
    if args[0] == "delete":
        print(""); return
    print("unknown", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
