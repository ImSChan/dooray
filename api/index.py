# api/index.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json, time, threading

app = FastAPI(title="Coffee Poll – submit-only")

# ---------- 메뉴 ----------
MENU_SECTIONS = {
    "추천메뉴": [
        "더치커피","아메리카노","카페라떼","유자민트 릴렉서 티","ICE 케모리치 릴렉서 티"
    ],
    "스무디": [
        "딸기주스","바나나주스","레몬요거트 스무디","블루베리요거트 스무디","딸기 요거트 스무니","딸기 바나나 스무디"
    ],
    "커피": [
        "에스프레소","아메리카노","카페라떼","카푸치노","바닐라라떼","돌체라떼","시나몬라떼",
        "헤이즐넛라떼","카라멜마키야토","카페모카","피치프레소","더치커피"
    ],
    "음료": [
        "그린티 라떼","오곡라떼","고구마라떼","로얄밀크티라떼","초콜릿라떼","리얼자몽티","리얼레몬티","진저레몬티",
        "매실차","오미자차","자몽에이드","레몬에이드","진저레몬에이드","스팀우유","사과유자차","페퍼민트",
        "얼그레이","캐모마일","유자민트릴렉서티","ICE 케모리치 릴렉서티","배도라지모과차","헛개차",
        "복숭아 아이스티","딸기라떼"
    ],
    "병음료": [
        "분다버그 진저","분다버그 레몬에이드","분다버그 망고","분다버그 자몽"
    ],
}
TEMP_OPTIONS = [{"text":"HOT","value":"HOT"},{"text":"ICE","value":"ICE"}]  # HOT 기본
SIZE_OPTIONS = [{"text":"사이즈업 X","value":"no"},{"text":"사이즈업","value":"yes"}]

# ---------- “드롭다운 상태” 임시 저장소 ----------
# key: (channelLogId, userId, section) -> {"menu":..., "temp":..., "size":...}
_state = {}
_state_lock = threading.Lock()
_STATE_TTL = 60 * 60  # 1시간

def _cleanup_state():
    now = time.time()
    with _state_lock:
        for k in list(_state.keys()):
            if now - _state[k]["_ts"] > _STATE_TTL:
                del _state[k]

def _set_state(channel_log_id: str, user_id: str, section: str, **kwargs):
    with _state_lock:
        key = (channel_log_id, user_id, section)
        cur = _state.get(key, {"menu": None, "temp": "HOT", "size": "no", "_ts": time.time()})
        cur.update(kwargs)
        cur["_ts"] = time.time()
        _state[key] = cur

def _get_state(channel_log_id: str, user_id: str, section: str):
    _cleanup_state()
    with _state_lock:
        cur = _state.get((channel_log_id, user_id, section))
        if not cur:
            # 기본값: 메뉴는 섹션 첫 항목, temp=HOT, size=no
            cur = {
                "menu": MENU_SECTIONS[section][0],
                "temp": "HOT",
                "size": "no",
                "_ts": time.time(),
            }
        return cur
# ---------- UI 빌더 ----------

def section_blocks(section: str) -> list[dict]:
    """섹션 UI를 2~3개의 attachment로 분리해서 세로 여백 확보"""
    # 1) 제목 + 메뉴 드롭다운 (행1)
    top = {
        "callbackId": "coffee-poll",
        "title": f"--------------[{section}]--------------",
        "actions": [
            {
                "name": f"menu::{section}",
                "text": "메뉴 선택",
                "type": "select",
                "options": [
                    {"text": f"[{section}] {m}", "value": m}
                    for m in MENU_SECTIONS[section]
                ],
            }
        ],
    }

    # 2) ICE/HOT + 사이즈 (행2)
    middle = {
        "callbackId": "coffee-poll",
        "actions": [
            {
                "name": f"temp::{section}",
                "text": "ICE/HOT",
                "type": "select",
                "options": TEMP_OPTIONS,
            },
            {
                "name": f"size::{section}",
                "text": "사이즈",
                "type": "select",
                "options": SIZE_OPTIONS,
            },
        ],
    }

    # (선택) 작은 스페이서 – 아주 살짝 더 띄우고 싶다면 사용
    spacer = {"text": "\u00A0"}  # non-breaking space

    # 3) 선택 버튼 (행3)
    bottom = {
        "callbackId": "coffee-poll",
        "actions": [
            {
                "name": f"vote::{section}",
                "text": "선택",
                "type": "button",
                "value": f"vote|{section}",
                "style": "primary",
            }
        ],
    }

    return [top, middle, spacer, bottom]


def status_attachment(fields=None):
    return {
        "title": "--------------선택 현황--------------",
        "fields": fields or []
    }

def pack(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

def parse_status(original: dict) -> dict:
    result = {}
    for att in (original.get("attachments") or []):
        if att.get("title") == "선택 현황":
            for f in att.get("fields", []):
                k = f.get("title") or ""
                v = (f.get("value") or "").strip()
                if k:
                    result[k] = [x for x in v.split() if x]
    return result

def status_fields(status: dict):
    if not status:
        return [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
    return [{"title": k, "value": " ".join(v) if v else "-", "short": False} for k, v in status.items()]

# ---------- 커맨드 ----------
@app.post("/dooray/command")
async def coffee_command(req: Request):
    data = await req.json()
    text = (data.get("text") or "").strip()

    # 파라미터 처리
    if text == "":
        return pack({
            "responseType": "ephemeral",
            "text": "☕ 커피 투표: 매장을 선택하세요",
            "attachments":[
                {"callbackId":"coffee-start","actions":[
                    {"name":"start","type":"button","text":"에뜨리에 시작","value":"start|에뜨리에","style":"primary"},
                    {"name":"start","type":"button","text":"에뜰 (미지원)","value":"start|에뜰"}
                ]}
            ]
        })
    if text == "에뜰":
        return pack({"responseType":"ephemeral","text":"🚫 아직 '에뜰'은 지원하지 않아요. '에뜨리에'로 시도해 주세요."})

    # 기본: 에뜨리에
    atts = [section_block(s) for s in ["추천메뉴","스무디","커피","음료","병음료"]] + [status_attachment()]
    return pack({"responseType":"inChannel","replaceOriginal":False,"text":"☕ 커피 투표 - 에뜨리에","attachments":atts})

# ---------- 인터랙션 ----------
@app.post("/dooray/actions")
async def coffee_actions(req: Request):
    data = await req.json()
    action_name = data.get("actionName") or ""
    action_value = (data.get("actionValue") or "").strip()
    original = data.get("originalMessage") or {}
    user = data.get("user") or {}
    user_id = user.get("id","user")
    user_email = user.get("email", user_id)
    channel_log_id = str(data.get("channelLogId") or original.get("id") or "")

    # 드롭다운 변경: 상태만 저장, 메시지는 그대로(=아무 업데이트 안 함)
    # name 형식: "menu::섹션", "temp::섹션", "size::섹션"
    if "::" in action_name and action_name.split("::",1)[0] in ("menu","temp","size"):
        kind, section = action_name.split("::",1)
        if section in MENU_SECTIONS:
            if kind == "menu":
                _set_state(channel_log_id, user_id, section, menu=action_value)
            elif kind == "temp":
                _set_state(channel_log_id, user_id, section, temp=action_value)
            elif kind == "size":
                _set_state(channel_log_id, user_id, section, size=action_value)
        # 빈 200 OK (Dooray는 200/빈 응답 허용). 굳이 메시지 업데이트하지 않음.
        return pack({})

    # 버튼: vote|섹션  → 상태 읽어 결과 반영
    if action_value.startswith("vote|"):
        _, section = action_value.split("|",1)
        # 해당 사용자 상태(없으면 기본값)
        st = _get_state(channel_log_id, user_id, section)
        menu = st["menu"] or MENU_SECTIONS[section][0]
        temp = st["temp"] or "HOT"
        size = st["size"] or "no"

        key = f"{section} / {menu} ({temp},{'사이즈업' if size=='yes' else '기본'})"

        status = parse_status(original)

        # 중복투표 덮어쓰기: 모든 항목에서 사용자 제거 후 새 항목에 추가
        for k in list(status.keys()):
            if user_email in status[k]:
                status[k] = [u for u in status[k] if u != user_email]
        status.setdefault(key, [])
        if user_email not in status[key]:
            status[key].append(user_email)

        # 원래 UI(드롭다운들)는 그대로 두고, 현황만 업데이트
        new_atts = []
        for att in (original.get("attachments") or []):
            if att.get("title") == "선택 현황":
                new_atts.append(status_attachment(status_fields(status)))
            else:
                new_atts.append(att)

        return pack({
            "text": original.get("text") or "☕ 커피 투표",
            "attachments": new_atts,
            "responseType":"inChannel",
            "replaceOriginal": True
        })

    # 그 외는 무시
    return pack({})
