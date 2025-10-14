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

# ---------- 상태 저장 ----------
# key: (channelLogId, userId, section) -> {"menu":..., "temp":..., "_ts": ...}
# section="__global__" 이면 전역 기본값(ICE/HOT)으로 사용
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
        cur = _state.get(key, {"_ts": time.time()})
        # 기본값 주입하지 말고, 전달된 필드만 갱신
        for k, v in kwargs.items():
            cur[k] = v
        cur["_ts"] = time.time()
        _state[key] = cur


def _get_state(channel_log_id: str, user_id: str, section: str):
    _cleanup_state()
    with _state_lock:
        cur = _state.get((channel_log_id, user_id, section))
        if not cur:
            cur = {
                "menu": MENU_SECTIONS[section][0] if section in MENU_SECTIONS else None,
                "temp": "HOT",
                "_ts": time.time(),
            }
        return cur

def _get_effective_temp(channel_log_id: str, user_id: str, section: str):
    with _state_lock:
        st = _state.get((channel_log_id, user_id, section), {})
        g  = _state.get((channel_log_id, user_id, "__global__"), {})
    temp = st.get("temp")
    if not temp:
        temp = g.get("temp")
    return temp or "HOT"


# ---------- 스타일 ----------
SECTION_STYLE = {
    "추천메뉴": {"emoji": "✨", "color": "#7C3AED"},
    "스무디":   {"emoji": "🍓", "color": "#06B6D4"},
    "커피":     {"emoji": "☕", "color": "#F59E0B"},
    "음료":     {"emoji": "🥤", "color": "#10B981"},
    "병음료":   {"emoji": "🧃", "color": "#EF4444"},
}
def section_header(section: str) -> dict:
    s = SECTION_STYLE.get(section, {"emoji":"•", "color":"#4757C4"})
    return {"callbackId":"coffee-poll","title":f"{s['emoji']}  {section}","color":s["color"]}

# ---------- 멘션(태그) ----------
def mention_member(tenant_id: str, user_id: str, label: str = "member") -> str:
    # Dooray 멤버 딥링크. 공백 포함하므로 현황 value는 개행으로 join/split 함
    return f'(dooray://{tenant_id}/members/{user_id} "{label}")'

# ---------- UI 빌더 (드롭다운 + 투표 버튼) ----------
def section_block_dropdown(section: str) -> list[dict]:
    s = SECTION_STYLE.get(section, {"emoji":"•", "color":"#4757C4"})
    return [
        {
            "callbackId": "coffee-poll",
            "title":f"{s['emoji']}  {section}",
            "color":s["color"],
            "actions": [
                {
                    "name": f"menu::{section}",
                    "text": "메뉴 선택",
                    "type": "select",
                    "options": [{"text": f"{m}", "value": m} for m in MENU_SECTIONS[section]],
                },
            ],
        },
    ]
def _get_latest_selection(channel_log_id: str, user_id: str):
    """해당 유저가 이 메시지에서 마지막으로 건드린(드롭다운 바꾼) 섹션과 메뉴를 반환"""
    latest = None
    latest_ts = -1
    with _state_lock:
        for (cid, uid, section), st in _state.items():
            if cid == channel_log_id and uid == user_id and section in MENU_SECTIONS:
                if st.get("menu"):
                    ts = st.get("_ts", 0)
                    if ts > latest_ts:
                        latest_ts = ts
                        latest = (section, st["menu"])
    return latest  # (section, menu) or None

def select_ice_or_hot():
    # 전역 기본값 설정 영역 (__global__)
    return {
        "callbackId": "coffee-poll",
        "title": "ICE/HOT 선택",
        "text": "온도를 선택해주세요",
        "actions": [
            {"name":"temp::__global__", "text":"ICE/HOT", "type":"select", "options": TEMP_OPTIONS},
            {"name":"apply_vote", "text":"선택", "type":"button", "value":"apply_vote", "style":"default"},
        ],
    }
def status_attachment(fields=None):
    if not fields:
        fields = [{"title":"","value":"","short":False}]
    return {"title":"선택 현황","fields": fields}


def pack(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

# 현황 파서/포맷터 (개행으로 구분)
def parse_status(original: dict) -> dict:
    result = {}
    for att in (original.get("attachments") or []):
        if att.get("title") == "선택 현황":
            for f in (att.get("fields") or []):
                k = f.get("title") or ""
                vraw = (f.get("value") or "").strip()
                if k:
                    result[k] = [x for x in vraw.split("\n") if x]
    return result

def status_fields(status: dict):
    if not status:
        return [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
    return [{"title": k, "value": "".join(v) if v else "-", "short": False} for k, v in status.items()]

# ---------- 커맨드 ----------
@app.post("/dooray/command")
async def coffee_command(req: Request):
    data = await req.json()
    text = (data.get("text") or "").strip()

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
    atts = []
    for s in ["추천메뉴","스무디","커피","음료","병음료"]:
        atts.extend(section_block_dropdown(s))
    atts.append(select_ice_or_hot())     # 전역 ICE/HOT 선택 영역
    atts.append(status_attachment())      # 현황
    return pack({"responseType":"inChannel","replaceOriginal":False,"text":"☕ 커피 투표 - 에뜨리에","attachments":atts})

# ---------- 인터랙션 ----------
@app.post("/dooray/actions")
async def coffee_actions(req: Request):
    data = await req.json()
    action_name  = data.get("actionName") or ""
    action_value = (data.get("actionValue") or "").strip()
    original     = data.get("originalMessage") or {}
    user         = data.get("user") or {}
    user_id      = user.get("id","user")
    tenant_id    = (data.get("tenant") or {}).get("id","tenant")
    channel_log_id = str(data.get("channelLogId") or original.get("id") or "")

    if "::" in action_name and action_name.split("::",1)[0] in ("menu","temp"):
        kind, section = action_name.split("::",1)
        if section in MENU_SECTIONS or section == "__global__":
            if kind == "menu":
                # 메뉴 갱신 + 섹션 temp 잔여치 제거 (전역 선택을 우선 적용시키기 위함)
                with _state_lock:
                    key = (channel_log_id, user_id, section)
                    cur = _state.get(key, {"_ts": time.time()})
                    cur["menu"] = action_value
                    if "temp" in cur:
                        del cur["temp"]        # ★ 섹션 temp 제거
                    cur["_ts"] = time.time()
                    _state[key] = cur
            elif kind == "temp":
                _set_state(channel_log_id, user_id, section, temp=action_value)
        return pack({})
    
    # 전역 선택 버튼 눌렀을 때도 메시지 변경 없음
    if action_value == "apply_prefs":
        return pack({})
    # 5) [최종 반영] (채널 메시지 버튼) → 원본 메시지의 "선택 현황"만 갱신
    if action_value == "apply_vote":
        # 0) 방어적 로깅
        # print(f"[apply_vote] chlog={channel_log_id} user={user_id}")

        latest = _get_latest_selection(channel_log_id, user_id)
        if not latest:
            # 아직 메뉴 드롭다운을 한 번도 안 건드렸으면 에페메럴 안내
            return pack({
                "responseType": "ephemeral",
                "text": "먼저 메뉴를 하나 선택해 주세요. (상단 섹션의 드롭다운)"
            })

        section, menu = latest
        temp = _get_effective_temp(channel_log_id, user_id, section)

        # 멘션용 tenant_id 안전 보정
        if not tenant_id:
            tenant_id = str((data.get("tenant") or {}).get("id") or "tenant")

        key = f"{menu} ({temp})"
        status = parse_status(original) or {}

        # 중복투표 제거 후 새 항목에 본인 멘션 추가
        tag = mention_member(tenant_id, user_id, label="member")
        for k in list(status.keys()):
            status[k] = [u for u in (status.get(k) or []) if u != tag]
        status.setdefault(key, [])
        if tag not in status[key]:
            status[key].append(tag)

        # 현황 필드 만들기 (빈 상태도 최소 1개 필드 보장)
        fields = status_fields(status)

        # 원본의 다른 블록은 그대로 두고, "선택 현황"만 교체
        new_atts = []
        replaced = False
        for att in (original.get("attachments") or []):
            if att.get("title") == "선택 현황":
                new_atts.append(status_attachment(fields))
                replaced = True
            else:
                new_atts.append(att)
        if not replaced:
            # 혹시 원본에 현황 블록이 없으면 추가
            new_atts.append(status_attachment(fields))

        return pack({
            "text": original.get("text") or "☕ 커피 투표",
            "attachments": new_atts,
            "responseType":"inChannel",
            "replaceOriginal": True
        })


    # 투표 버튼: vote|섹션
    if action_value.startswith("vote|"):
        _, section = action_value.split("|",1)
        st   = _get_state(channel_log_id, user_id, section)
        menu = st.get("menu") or (MENU_SECTIONS[section][0] if section in MENU_SECTIONS else "")
        temp = _get_effective_temp(channel_log_id, user_id, section)

        key = f"{section} / {menu} ({temp})"

        status = parse_status(original)

        # 중복투표 제거 후 새 항목에 추가 (멘션으로 저장)
        tag = mention_member(tenant_id, user_id, label="member")
        for k in list(status.keys()):
            status[k] = [u for u in status[k] if u != tag]
        status.setdefault(key, [])
        if tag not in status[key]:
            status[key].append(tag)

        # 현황만 업데이트
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
