from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os, json, requests, logging, sys, re
from typing import Dict, Any

app = FastAPI(title="Dooray Dialog Sample")

# ---- logging ----
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(levelname)s %(asctime)s %(name)s : %(message)s",
)
logger = logging.getLogger("dooray-dialog")

def respond(payload: Dict[str, Any]) -> JSONResponse:
    try:
        logger.info("[RESP] %s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass
    return JSONResponse(payload)

# ---- security (선택) ----
def verify_request(req: Request):
    expected = os.getenv("DOORAY_VERIFY_TOKEN")
    if not expected:
        return
    got = req.headers.get("X-Dooray-Token") or req.headers.get("Authorization")
    if got != expected:
        raise HTTPException(status_code=401, detail="invalid token")

# ---- dialog opener ----
def open_dialog(tenant_domain: str, channel_id: str, cmd_token: str, trigger_id: str):
    """
    Dooray Dialog API 호출하여 대화상자 띄우기
    POST https://{tenantDomain}/messenger/api/channels/{channelId}/dialogs
    Header: token: cmdToken
    """
    url = f"https://{tenant_domain}/messenger/api/channels/{channel_id}/dialogs"
    headers = {"token": cmd_token, "Content-Type": "application/json;charset=utf-8"}
    body = {
        "token": cmd_token,
        "triggerId": trigger_id,
        "callbackId": "sample-dialog",
        "dialog": {
            "callbackId": "sample-dialog",
            "title": "간단 요청 폼",
            "submitLabel": "제출",
            "elements": [
                {
                    "type": "text",
                    "label": "제목",
                    "name": "title",
                    "minLength": 2,
                    "maxLength": 50,
                    "placeholder": "요청 제목을 입력"
                },
                {
                    "type": "textarea",
                    "label": "내용",
                    "name": "desc",
                    "minLength": 5,
                    "maxLength": 500,
                    "placeholder": "요청 상세"
                },
                {
                    "type": "select",
                    "label": "우선순위",
                    "name": "priority",
                    "value": "normal",
                    "options": [
                        {"label": "낮음", "value": "low"},
                        {"label": "보통", "value": "normal"},
                        {"label": "높음", "value": "high"}
                    ]
                }
            ]
        }
    }
    logger.info("[DIALOG/REQ] %s %s", url, json.dumps(body, ensure_ascii=False))
    r = requests.post(url, headers=headers, json=body, timeout=5)
    logger.info("[DIALOG/RES] %s %s", r.status_code, r.text[:1000])
    # Dooray는 성공/실패를 JSON header 필드에 담아줌 (참고용)
    return r.status_code, r.text

# ---- slash command ----
@app.post("/dooray/command")
async def dooray_command(req: Request):
    verify_request(req)
    data = await req.json()
    logger.info("[IN/SLASH] %s", json.dumps(data, ensure_ascii=False))

    tenant_domain = data.get("tenantDomain") or data.get("tenant", {}).get("domain")
    channel_id    = data.get("channelId")   or data.get("channel", {}).get("id")
    trigger_id    = data.get("triggerId")
    cmd_token     = data.get("cmdToken")

    if not (tenant_domain and channel_id and trigger_id and cmd_token):
        # Dooray 실제 호출이 아니거나 필드 빠진 경우
        return respond({
            "responseType": "ephemeral",
            "text": "필수 값 누락(tenantDomain, channelId, triggerId, cmdToken)."
        })

    # 대화상자 띄우기
    open_dialog(tenant_domain, channel_id, cmd_token, trigger_id)

    # 슬래시 요청에 대한 즉시 응답(사용자에게만 보임)
    return respond({
        "responseType": "ephemeral",
        "text": "📋 대화상자를 열었습니다. 입력 후 제출하세요!"
    })

# ---- dialog submission / actions ----
@app.post("/dooray/actions")
async def dooray_actions(req: Request):
    verify_request(req)
    data = await req.json()
    logger.info("[IN/ACTIONS] %s", json.dumps(data, ensure_ascii=False))

    dtype = data.get("type")
    cbid  = data.get("callbackId")

    # 대화상자 제출 처리
    if dtype == "dialog_submission" and cbid == "sample-dialog":
        sub = data.get("submission", {})
        title = (sub.get("title") or "").strip()
        desc  = (sub.get("desc")  or "").strip()
        prio  = sub.get("priority")

        # 간단 검증
        if len(title) < 2:
            return JSONResponse({"errors":[{"name":"title","error":"제목은 2자 이상"}]})
        if len(desc) < 5:
            return JSONResponse({"errors":[{"name":"desc","error":"내용은 5자 이상"}]})
        if prio not in {"low","normal","high"}:
            return JSONResponse({"errors":[{"name":"priority","error":"우선순위를 선택하세요"}]})

        # 성공 시: 빈 JSON 200 → 대화상자 닫힘
        # 그리고 responseUrl로 채널에 공지 메시지 전송(옵션)
        resp_url = data.get("responseUrl")
        if resp_url:
            payload = {
                "responseType": "inChannel",
                "text": f"✅ 요청 접수: *{title}*",
                "attachments": [
                    {"fields": [
                        {"title":"우선순위","value": prio.upper(), "short": True},
                        {"title":"내용","value": desc, "short": False}
                    ]}
                ]
            }
            try:
                rs = requests.post(resp_url, json=payload, timeout=5)
                logger.info("[HOOK/POST] %s %s", rs.status_code, rs.text[:300])
            except Exception as e:
                logger.exception("responseUrl post failed: %s", e)

        return JSONResponse({})

    # 그 외 액션이 들어오면 에페메럴 안내
    return respond({"responseType":"ephemeral","text":"지원하지 않는 액션입니다."})

# local run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=8000, reload=True)
