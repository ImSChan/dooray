from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os, json, logging, sys, requests
from requests.exceptions import RequestException, SSLError, Timeout, ConnectionError

app = FastAPI(title="Dooray Dialog Button Demo")

# ----- logging -----
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.basicConfig(level="INFO", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("dooray-dialog-demo")

def ok(payload: dict) -> JSONResponse:
    log.info("[RESP] %s", json.dumps(payload, ensure_ascii=False))
    return JSONResponse(payload, media_type="application/json; charset=utf-8")

def verify(req: Request):
    """옵션: Dooray 검증 토큰 사용 시"""
    expected = os.getenv("DOORAY_VERIFY_TOKEN")
    if not expected:
        return
    got = req.headers.get("X-Dooray-Token") or req.headers.get("Authorization")
    if got != expected:
        return JSONResponse({"text": "invalid token"}, status_code=401)

# ----- Dialog opener -----
def open_dialog(tenant_domain: str, channel_id: str, cmd_token: str, trigger_id: str):
    url = f"https://{tenant_domain}/messenger/api/channels/{channel_id}/dialogs"
    headers = {
        "token": cmd_token,
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {
        "token": cmd_token,          # Dooray 예시처럼 바디에도 포함
        "triggerId": trigger_id,
        "callbackId": "sample-dialog",
        "dialog": {
            "callbackId": "sample-dialog",
            "title": "요청 등록",
            "submitLabel": "등록",
            "elements": [
                {"type": "text", "label": "제목", "name": "title", "minLength": 2, "maxLength": 50},
                {"type": "textarea", "label": "내용", "name": "desc", "minLength": 5, "maxLength": 500},
                {"type": "select", "label": "우선순위", "name": "priority", "value": "normal",
                 "options": [{"label":"낮음","value":"low"},{"label":"보통","value":"normal"},{"label":"높음","value":"high"}]}
            ]
        }
    }

    log.info("[DIALOG>REQ] %s %s", url, json.dumps(body, ensure_ascii=False))
    try:
        r = requests.post(url, headers=headers, json=body, timeout=8)
    except (Timeout, SSLError, ConnectionError, RequestException) as e:
        log.exception("[DIALOG EXC] POST failed: %s", e)
        return {"ok": False, "status": None, "body": None, "error": str(e)}

    # 응답 로깅 (헤더 + 본문)
    ctype = r.headers.get("content-type", "")
    text  = (r.text or "")[:2000]
    log.info("[DIALOG<RES] %s CT=%s BODY=%s", r.status_code, ctype, text)

    # 1) 본문 JSON 시도
    j = None
    if text:
        try:
            j = r.json()
        except Exception:
            j = None

    # 2) 성공 판정: 200 and (빈 바디 or header.isSuccessful True)
    if r.status_code == 200 and (not text or (isinstance(j, dict) and j.get("header", {}).get("isSuccessful") is True)):
        return {"ok": True, "status": r.status_code, "body": j, "error": None}

    # 3) 실패 메시지 추출
    err = None
    if isinstance(j, dict):
        err = j.get("header", {}).get("resultMessage") or j.get("message")
    return {"ok": False, "status": r.status_code, "body": j, "error": err or (text if text else "unknown")}

# ----- Slash: 버튼 한 개만 보이게 -----
@app.post("/dooray/command")
async def slash(req: Request):
    v = verify(req)
    if isinstance(v, JSONResponse): return v

    data = await req.json()
    log.info("[IN/SLASH] %s", json.dumps(data, ensure_ascii=False))

    # 메시지: 대화창 열기 버튼 1개
    payload = {
        "responseType": "ephemeral",   # 실행자에게만 보임
        "text": "대화창을 열어 추가 정보를 입력하세요.",
        "attachments": [
            {
                "callbackId": "dlg-open",
                "actions": [
                    {
                        "name": "open",
                        "type": "button",
                        "text": "📝 대화창 열기",
                        "value": "open-dialog",
                        "style": "primary"
                    }
                ]
            }
        ]
    }
    return ok(payload)

# ----- Actions: 버튼 클릭 → 다이얼로그 열기 / 다이얼로그 제출 -----
@app.post("/dooray/actions")
async def actions(req: Request):
    v = verify(req)
    if isinstance(v, JSONResponse): return v

    data = await req.json()
    log.info("[IN/ACTIONS] %s", json.dumps(data, ensure_ascii=False))

    if data.get("callbackId") == "dlg-open" and data.get("actionName") == "open":
        tenant_domain = data.get("tenant", {}).get("domain") or data.get("tenantDomain")
        channel_id    = data.get("channel", {}).get("id")    or data.get("channelId")
        cmd_token     = data.get("cmdToken")
        trigger_id    = data.get("triggerId")

        if not (tenant_domain and channel_id and cmd_token and trigger_id):
            return ok({"responseType":"ephemeral","text":"필수 값 누락(tenantDomain/channelId/cmdToken/triggerId)"})

        # 다이얼로그 열기
        result = open_dialog(tenant_domain, channel_id, cmd_token, trigger_id)
        if result["ok"]:
            return ok({
                "responseType": "ephemeral",
                "replaceOriginal": True,
                "text": "📋 대화창을 열었습니다. 입력 후 제출하세요!"
            })
        else:
            # 실패 사유를 바로 보여주면 원인 파악 쉬움 (triggerId 만료/권한 문제/네트워크 등)
            return ok({
                "responseType": "ephemeral",
                "replaceOriginal": False,
                "text": f"⚠️ 대화창 열기 실패\n- status: {result['status']}\n- error: {result['error'] or 'unknown'}"
            })


    # 2) 다이얼로그 제출
    if data.get("type") == "dialog_submission" and data.get("callbackId") == "sample-dialog":
        sub = data.get("submission", {}) or {}
        title = (sub.get("title") or "").strip()
        desc  = (sub.get("desc") or "").strip()
        prio  = (sub.get("priority") or "").strip()

        # 검증 에러 예시
        errs = []
        if len(title) < 2: errs.append({"name":"title","error":"제목은 2자 이상"})
        if len(desc)  < 5: errs.append({"name":"desc","error":"내용은 5자 이상"})
        if prio not in {"low","normal","high"}:
            errs.append({"name":"priority","error":"우선순위를 선택하세요"})
        if errs:
            # 200 + errors → 다이얼로그는 닫히지 않고 필드 에러 표시
            return JSONResponse({"errors": errs})

        # 성공 → 빈 JSON 200 → 다이얼로그 닫힘
        # (선택) 채널 공지
        resp_url = data.get("responseUrl")
        if resp_url:
            msg = {
                "responseType": "inChannel",
                "text": f"✅ 요청 접수: *{title}*",
                "attachments": [{
                    "fields":[
                        {"title":"우선순위","value": prio.upper(), "short": True},
                        {"title":"내용","value": desc, "short": False}
                    ]
                }]
            }
            try:
                r = requests.post(resp_url, json=msg, timeout=8)
                log.info("[HOOK POST] %s %s", r.status_code, r.text[:500])
            except Exception as e:
                log.exception("responseUrl post failed: %s", e)
        return JSONResponse({})

    # 기타 액션
    return ok({"responseType":"ephemeral","text":"지원하지 않는 액션입니다."})
