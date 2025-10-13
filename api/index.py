from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import os, json, logging, sys, requests, itertools

app = FastAPI(title="Coffee Poll (/커피투표)")

# ---------- Logging ----------
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(levelname)s %(asctime)s %(name)s : %(message)s",
)
log = logging.getLogger("coffee-poll")

def ok(payload: dict):  # unify response + logging
    try:
        log.info("[RESP] %s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass
    return JSONResponse(payload)

def verify(req: Request):
    # 필요하면 Dooray에서 주는 검증 토큰 헤더를 확인해서 쓰세요.
    expected = os.getenv("DOORAY_VERIFY_TOKEN")
    if not expected:
        return
    got = req.headers.get("X-Dooray-Token") or req.headers.get("Authorization")
    if got != expected:
        raise HTTPException(status_code=401, detail="invalid token")

# ---------- 메뉴 정의 ----------
# 카테고리별 옵션(표시는 text, 내부 값은 value)
MENU_SECTIONS = {
    "추천메뉴": [
        "더치커피","아메리카노"
    ],
    "스무디": [
        "딸기주스","바나나주스"
    ],
    "커피": [
        "에스프레소","아메리카노"
    ],
    "음료": [
        "그린티 라떼","오곡라떼"
    ],
    "병음료": [
        "분다버그 진저","분다버그 레몬에이드","분다버그 망고","분다버그 자몽"
    ],
}

# 합쳐서 하나의 options 배열(최대 100 안 넘게)
ALL_MENU_OPTIONS = [{"text": f"[{cat}] {name}", "value": name}
                    for cat, items in MENU_SECTIONS.items()
                    for name in items]

TEMP_OPTIONS = [
    {"text": "ICE", "value": "ICE"},
    {"text": "HOT", "value": "HOT"},
]
SIZE_OPTIONS = [
    {"text": "사이즈업 X", "value": "no"},
    {"text": "사이즈업", "value": "yes"},
]

# 한 메시지(투표판)에서 제공할 슬롯 개수
NUM_SLOTS = 3

# ---------- 상태 저장 (메모리) ----------
# polls[poll_id] = {
#   "shop": "에뜨리에",
#   "votes": { userId: {"menu":..., "temp":..., "size":..., "display": "..."} },
#   "pending": { (userId, slot): {"menu":..., "temp":..., "size":...} }
# }
polls: dict[str, dict] = {}

# ---------- 공용 유틸 ----------
def parse_payload(req_body: bytes, ctype: str) -> dict:
    body = req_body.decode("utf-8", "ignore")
    log.info("[IN] CT=%s RAW=%s", ctype, body[:2000])
    if (ctype or "").lower().startswith("application/json"):
        try:
            return json.loads(body)
        except Exception:
            return {}
    # x-www-form-urlencoded / multipart → payload=... 케이스
    try:
        from urllib.parse import parse_qs
        data = {k: v[0] for k, v in parse_qs(body).items()}
        if "payload" in data:
            return json.loads(data["payload"])
        return data
    except Exception:
        return {}

def user_display(d: dict) -> str:
    # Dooray payload에 따라 email/name이 다를 수 있어 안전하게 구성
    u = d.get("user") or {}
    email = u.get("email")
    name  = u.get("name")
    uid   = u.get("id")
    return name or email or str(uid)

def build_usage() -> dict:
    return {
        "responseType": "ephemeral",
        "text": "☕ /커피투표 {매장} 를 입력하세요.\n- 지원 매장: `에뜨리에`, `에뜰`\n- 예) `/커피투표 에뜨리에`",
    }

def build_not_supported(shop: str) -> dict:
    return {
        "responseType": "ephemeral",
        "text": f"❌ `{shop}` 매장은 아직 지원하지 않습니다. (현재: 에뜨리에만)",
    }

def build_poll_attachments(poll_id: str) -> list[dict]:
    """슬롯별 드롭다운 + 버튼, 하단 현황"""
    atts: list[dict] = []
    for slot in range(1, NUM_SLOTS + 1):
        atts.append({
            "callbackId": "coffee-poll",
            "title": f"항목 {slot}",
            "actions": [
                {"name": f"menu_{slot}", "text": "메뉴 선택", "type": "select", "options": ALL_MENU_OPTIONS},
            ]
        })
        atts.append({
            "callbackId": "coffee-poll",
            "actions": [
                {"name": f"temp_{slot}", "text": "ICE/HOT", "type": "select", "options": TEMP_OPTIONS},
                {"name": f"size_{slot}", "text": "사이즈", "type": "select", "options": SIZE_OPTIONS},
                {"name": f"vote_{slot}", "text": "선택", "type": "button",
                 "value": f"vote|{poll_id}|{slot}"}
            ]
        })
    # 현황
    atts.append({"title": "선택 현황", "fields": build_status_fields(poll_id)})
    return atts

def build_status_fields(poll_id: str) -> list[dict]:
    p = polls.get(poll_id) or {}
    votes = p.get("votes", {})
    # 메뉴별로 그룹핑
    grouped: dict[str, list[str]] = {}
    for v in votes.values():
        key = f"{v['menu']} ({v['temp']}{' / size↑' if v['size']=='yes' else ''})"
        grouped.setdefault(key, []).append(v["display"])
    # 보기 좋게 정렬
    fields = []
    for k in sorted(grouped.keys()):
        voters = " ".join(sorted(grouped[k]))
        fields.append({"title": k, "value": voters or "-", "short": False})
    if not fields:
        fields = [{"title": "아직 투표 없음", "value": "첫 투표를 기다리는 중!", "short": False}]
    return fields

def rebuild_poll_message(poll_id: str, shop: str) -> dict:
    return {
        "responseType": "inChannel",
        "replaceOriginal": True,
        "text": f"☕ 커피 투표 - {shop}",
        "attachments": build_poll_attachments(poll_id),
    }

# ---------- 엔드포인트 ----------
@app.post("/dooray/command")
async def slash(req: Request):
    verify(req)
    raw = await req.body()
    data = parse_payload(raw, req.headers.get("content-type",""))
    # 액션 폴백 방지: command 전용으로 처리
    if data.get("actionValue"):
        return ok({"responseType":"ephemeral","text":"잘못된 호출입니다.(action to /command)"})

    text = (data.get("text") or "").strip()
    if not text:
        return ok(build_usage())

    shop = text
    if shop == "에뜰":
        return ok(build_not_supported(shop))
    if shop != "에뜨리에":
        return ok(build_usage())

    # 에뜨리에 시작 → 채널에 투표판 게시
    # poll_id는 메시지 업데이트용으로 originalMessage.id를 쓰는 것이 보통이지만
    # 첫 응답 시점에는 없으므로, 임시 아이디를 만들고 액션에서 originalMessage.id로 교체해도 됨.
    # 여기서는 액션 페이로드(originalMessage.id)를 실제 poll_id로 쓸 것이므로
    # 일단 dummy를 넣고, 액션 첫 호출 때 교체하는 패턴로 구현.
    dummy_poll_id = "pending"
    payload = {
        "responseType": "inChannel",
        "deleteOriginal": True,      # 사용자의 슬래시 입력 메시지는 삭제
        "text": f"☕ 커피 투표 - {shop}",
        "attachments": build_poll_attachments(dummy_poll_id),
    }
    return ok(payload)

@app.post("/dooray/actions")
async def actions(req: Request):
    verify(req)
    raw = await req.body()
    data = parse_payload(raw, req.headers.get("content-type",""))
    log.info("[ACTIONS] %s", json.dumps(data, ensure_ascii=False)[:2000])

    cb = data.get("callbackId")
    if cb != "coffee-poll":
        # 다른 액션(혹시) 무시
        return ok({"responseType":"ephemeral","text":"알 수 없는 액션입니다."})

    original = data.get("originalMessage", {}) or {}
    poll_id = original.get("id") or "missing"
    channel = data.get("channel") or {}
    user    = data.get("user") or {}
    user_id = (user.get("id") or "")
    display = user_display(data)

    # 최초 액션 도착 시, dummy → real id로 초기화
    if poll_id not in polls:
        polls[poll_id] = {"shop": "에뜨리에", "votes": {}, "pending": {}}

    name = data.get("actionName")
    value = (data.get("actionValue") or "").strip()

    # 드롭다운(선택만 하고 확정은 아님)
    # name: menu_1 / temp_1 / size_1  -> slot = 마지막 토큰
    if name and ("_" in name) and value and not value.startswith("vote|"):
        kind, slot_s = name.split("_", 1)
        try:
            slot = int(slot_s)
        except:
            slot = 1
        pending_key = (user_id, slot)
        pend = polls[poll_id]["pending"].get(pending_key, {"menu": None, "temp": None, "size": None})
        if kind == "menu":
            pend["menu"] = value
        elif kind == "temp":
            pend["temp"] = value
        elif kind == "size":
            pend["size"] = value
        polls[poll_id]["pending"][pending_key] = pend
        # 사용자에게만 보이는 안내
        return ok({
            "responseType": "ephemeral",
            "replaceOriginal": False,
            "text": f"임시 선택(항목 {slot}) 저장됨: {pend}"
        })

    # 선택 버튼
    if value.startswith("vote|"):
        # vote|{poll_id or 'pending'}|{slot}
        try:
            _, _pid, slot_s = value.split("|", 2)
            slot = int(slot_s)
        except:
            return ok({"responseType":"ephemeral","text":"잘못된 투표 값입니다."})

        # pending 값 확인
        pend = polls[poll_id]["pending"].get((user_id, slot))
        if not pend or not pend.get("menu") or not pend.get("temp") or not pend.get("size"):
            return ok({"responseType":"ephemeral","text":"먼저 드롭다운에서 메뉴/ICEHOT/사이즈를 모두 선택하세요."})

        # 중복 투표 방지(유저당 1회)
        if user_id in polls[poll_id]["votes"]:
            return ok({"responseType":"ephemeral","text":"이미 투표하셨습니다. (중복 투표 불가)"})

        polls[poll_id]["votes"][user_id] = {
            "menu": pend["menu"], "temp": pend["temp"], "size": pend["size"], "display": display
        }
        # 선택 현황 반영 → 메시지 업데이트
        return ok(rebuild_poll_message(poll_id, polls[poll_id]["shop"]))

    # 그 외
    return ok({"responseType":"ephemeral","text":"지원하지 않는 동작입니다."})
