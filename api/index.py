# api/index.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json, time, threading

app = FastAPI(title="Coffee Poll – category → ephemeral → apply")

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
TEMP_OPTIONS = [{"text":"HOT","value":"HOT"},{"text":"ICE","value":"ICE"}]  # 기본 HOT

# ---------- 상태 ----------
# key: (channelLogId, userId, section) -> {"menu":..., "temp":..., "_ts": ...}
# 특별 섹션:
#   "__category__"  : 사용자가 현재 고른 카테고리(추천메뉴/스무디/커피/음료/병음료)
#   "__global__"    : 전역 온도 기본값(HOT/ICE) (원하면 섹션별 temp로 바꿔도 됨)
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
        cur = _state.get(key, {"menu": None, "temp": "HOT", "_ts": time.time()})
        cur.update(kwargs)
        cur["_ts"] = time.time()
        _state[key] = cur

def _get_state(channel_log_id: str, user_id: str, section: str):
    _cleanup_state()
    with _state_lock:
        cur = _state.get((channel_log_id, user_id, section))
        if not cur:
            # 섹션이면 첫 메뉴 기본값, 특수섹션이면 메뉴 없음
            default_menu = MENU_SECTIONS[section][0] if section in MENU_SECTIONS else None
            cur = {"menu": default_menu, "temp": "HOT", "_ts": time.time()}
        return cur

def _get_effective_temp(channel_log_id: str, user_id: str, section: str):
    # 섹션별 설정 -> 전역(__global__) -> 기본(HOT)
    st = _get_state(channel_log_id, user_id, section)
    g  = _get_state(channel_log_id, user_id, "__global__")
    return st.get("temp") or g.get("temp") or "HOT"

# ---------- 스타일(색/이모지) ----------
SECTION_STYLE = {
    "추천메뉴": {"emoji": "✨", "color": "#7C3AED"},
    "스무디":   {"emoji": "🍓", "color": "#06B6D4"},
    "커피":     {"emoji": "☕", "color": "#F59E0B"},
    "음료":     {"emoji": "🥤", "color": "#10B981"},
    "병음료":   {"emoji": "🧃", "color": "#EF4444"},
}

# ---------- 멤버 멘션 ----------
def mention_member(tenant_id: str, user_id: str, label: str = "member") -> str:
    # 선택 현황 value는 개행으로 join/split 하므로 공백/괄호 그대로 사용
    return f'(dooray://{tenant_id}/members/{user_id} "{label}")'

# ---------- 공통 ----------
def pack(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

def status_attachment(fields=None):
    return {"title":"선택 현황","fields": fields or None}

def parse_status(original: dict) -> dict:
    # "선택 현황" attachment를 dict[str, list[str]] 로 파싱 (개행 기준)
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
    return [{"title": k, "value": "\n".join(v) if v else "-", "short": False} for k, v in status.items()]

# ---------- 채널 UI: 카테고리 선택 + 버튼 + 현황 ----------
def category_attachment():
    # 예쁘게 색/이모지까지는 고정색 사용
    return {
        "callbackId": "coffee-poll",
        "title": "📂 카테고리 선택",
        "text": "섹션을 고른 뒤, [항목 선택]에서 개인 메뉴/온도 고르고 → [최종 반영]으로 투표하세요.",
        "color": "#4757C4",
        "actions": [
            {
                "name": "cat::__global__",
                "text": "카테고리",
                "type": "select",
                "options": [{"text": s, "value": s} for s in ["추천메뉴","스무디","커피","음료","병음료"]],
            },
            {"name":"cat_open",   "text":"항목 선택", "type":"button", "value":"cat_open"},
            {"name":"apply_vote", "text":"최종 반영", "type":"button", "value":"apply_vote", "style":"primary"},
        ],
    }

# ---------- 개인(ephemeral) UI: 메뉴/온도 선택 ----------
def build_ephemeral_picker(section: str):
    s = SECTION_STYLE.get(section, {"emoji":"•", "color":"#4757C4"})
    return {
        "responseType": "ephemeral",
        "text": f"{s['emoji']}  *{section}* — 본인만 보이는 선택 창",
        "attachments": [
            {
                "callbackId": "coffee-poll-ep",
                "title": f"{s['emoji']}  {section} 메뉴 선택",
                "color": s["color"],
                "actions": [
                    {"name": f"menu::{section}", "text": "메뉴", "type": "select",
                     "options": [{"text": m, "value": m} for m in MENU_SECTIONS[section]]},
                    {"name": "temp::__global__", "text": "ICE/HOT", "type": "select", "options": TEMP_OPTIONS},
                ],
            },
            {
                "callbackId": "coffee-poll-ep",
                "actions": [
                    {"name":"ep_close", "text":"닫기", "type":"button", "value":"ep_close"},
                ],
            }
        ],
        "replaceOriginal": True
    }

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

    # 기본: 에뜨리에 → 채널에 카테고리 선탁 화면 + 현황
    return pack({
        "responseType":"inChannel",
        "replaceOriginal": False,
        "text":"☕ 커피 투표 - 에뜨리에",
        "attachments":[
            category_attachment(),
            status_attachment()
        ]
    })

# ---------- 액션 ----------
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

    # 1) 카테고리 드롭다운 변경 → 상태만 저장
    if action_name == "cat::__global__":
        # 고른 카테고리를 저장(기본은 추천메뉴)
        _set_state(channel_log_id, user_id, "__category__", menu=action_value)
        return pack({})

    # 2) [항목 선택] → 개인(ephemeral) 메뉴/온도 선택창 표시
    if action_value == "cat_open":
        # 저장된 카테고리 없으면 추천메뉴
        cat_st  = _get_state(channel_log_id, user_id, "__category__")
        section = cat_st.get("menu") or "추천메뉴"
        if section not in MENU_SECTIONS:
            section = "추천메뉴"
        return pack(build_ephemeral_picker(section))

    # 3) 개인 드롭다운: 메뉴/온도 변경(저장만)
    if "::" in action_name and action_name.split("::",1)[0] in ("menu","temp"):
        kind, section = action_name.split("::",1)
        # section은 실제 섹션명 또는 "__global__"
        if section in MENU_SECTIONS or section == "__global__":
            if kind == "menu":
                _set_state(channel_log_id, user_id, section, menu=action_value)
            elif kind == "temp":
                _set_state(channel_log_id, user_id, section, temp=action_value)
        return pack({})

    # 4) [닫기] (개인창) → 아무것도 안 바꿈
    if action_value == "ep_close":
        return pack({})

    # 5) [최종 반영] (채널 메시지 버튼) → 원본 메시지의 "선택 현황"만 갱신
    if action_value == "apply_vote":
        # 현재 카테고리 기준으로 적용
        cat_st  = _get_state(channel_log_id, user_id, "__category__")
        section = cat_st.get("menu") or "추천메뉴"
        if section not in MENU_SECTIONS:
            section = "추천메뉴"

        st   = _get_state(channel_log_id, user_id, section)
        menu = st.get("menu") or (MENU_SECTIONS[section][0] if section in MENU_SECTIONS else "")
        temp = _get_effective_temp(channel_log_id, user_id, section)

        key = f"{section} / {menu} ({temp})"
        status = parse_status(original)

        # 중복투표 제거 후 새 항목에 본인 멘션 추가
        tag = mention_member(tenant_id, user_id, label="member")
        for k in list(status.keys()):
            status[k] = [u for u in status[k] if u != tag]
        status.setdefault(key, [])
        if tag not in status[key]:
            status[key].append(tag)

        # 원본의 "카테고리 선택" 블록은 유지, "선택 현황"만 교체
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
            "replaceOriginal": True   # 채널 메시지(원본) 업데이트!
        })

    # 나머지 무시
    return pack({})
