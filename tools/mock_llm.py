"""开发用 OpenAI 兼容 Mock 服务：uvicorn tools.mock_llm:app --port 9001
在「设置」页把 API 地址填 http://host.docker.internal:9001/v1 即可无 Key 联调。
security 角色（安全增强检测）返回 【安全增强检测】 分支：发现 mocksecret 时报一条增强 Finding。"""
import json

from fastapi import FastAPI, Request

app = FastAPI()


def _security_response(user: str) -> str:
    findings = []
    marker = "<待检文本>"
    start = user.find(marker)
    if start != -1:
        body_start = start + len(marker)
        pos = user.find("mocksecret", body_start)
        if pos != -1:
            s = pos - body_start
            findings.append(
                {
                    "span": [s, s + len("mocksecret")],
                    "kind": "credential",
                    "confidence": 0.6,
                    "evidence": "mock 增强命中 mock 前缀",
                }
            )
    return json.dumps({"findings": findings}, ensure_ascii=False)


@app.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    user = "".join(m.get("content", "") for m in (body.get("messages") or []) if m.get("role") == "user")
    if "【编译任务】" in user:
        content = json.dumps(
            {
                "source_summary": {
                    "title": "Mock 来源",
                    "path": "sources/mock-source.md",
                    "content": "# Mock 来源\n\n> 来源：用户输入（Mock 联调）\n\n这是 Mock 模型生成的来源摘要页，包含 [[projects/demo-project.md|Demo 项目]]。\n",
                },
                "pages": [
                    {
                        "action": "update",
                        "path": "projects/demo-project.md",
                        "title": "Demo 项目",
                        "content": "# Demo 项目\n\n> 来源：[[sources/mock-source.md|Mock 来源]]\n\n这是 Mock 模型生成的资产页，用于联调验证 Wiki 编译链路。",
                    }
                ],
                "conflicts": [],
            },
            ensure_ascii=False,
        )
    elif "【安全增强检测】" in user:
        content = _security_response(user)
    elif "【问答任务】" in user or "【连通性测试】" in user:
        content = "根据 [[projects/demo-project.md|Demo 项目]]：这是 Mock 模型生成的示例回答。"
    else:
        content = "OK"
    return {"id": "mock", "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}
