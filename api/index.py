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
# ---------- “원본 메시지(본문 attachments)” 캐시 ----------
# key: channelLogId(본문) -> {"attachments": [...], "_ts": epoch}
_orig = {}
_ORIG_TTL = 60 * 60  # 1시간

def _orig_set(main_id: str, attachments: list[dict]):
    _orig[main_id] = {"attachments": attachments, "_ts": time.time()}

def _orig_get(main_id: str):
    # TTL cleanup
    now = time.time()
    for k in list(_orig.keys()):
        if now - _orig[k]["_ts"] > _ORIG_TTL:
            del _orig[k]
    item = _orig.get(main_id)
    return (item or {}).get("attachments")

# ---------- UI 빌더 (버튼 버전) ----------
def section_blocks_buttons(section: str, per_row: int = 4) -> list[dict]:
    """
    섹션 제목 + (행1) ICE/HOT, 사이즈 드롭다운 + (여러 행) 메뉴 버튼들
    - 버튼 name을 "menu::{section}" 으로 설정 → 기존 핸들러가 그대로 상태 저장
    - 버튼 value/text = 실제 메뉴명
    """
    blocks: list[dict] = []

    # 0) 섹션 제목
    blocks.append({
        "callbackId": "coffee-poll",
        "title": f"--------------[{section}]--------------",
        "actions": []  # 제목만 보이게 actions 비움
    })

    # 2) 메뉴 버튼들 (가로 per_row개씩 줄바꿈)
    menus = MENU_SECTIONS[section]
    row: list[dict] = []
    for i, m in enumerate(menus, start=1):
        row.append({
            "name": f"menu::{section}",     # <-- 기존 핸들러와 동일 키
            "type": "button",
            "text": m,
            "value": m,                      # 선택된 메뉴값
            "style": "default"
        })
        if i % per_row == 0:
            blocks.append({"callbackId": "coffee-poll", "actions": row})
            row = []
    if row:
        blocks.append({"callbackId": "coffee-poll", "actions": row})


    return blocks

def status_attachment(fields=None):
    return {
        "title": "--------------선택 현황--------------",
        "fields": fields or None
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
    atts = []
    for s in ["추천메뉴","스무디","커피","음료","병음료"]:
        atts.extend(section_blocks_buttons(s, per_row=4))  # per_row로 한 줄 버튼 개수 조절
    atts.append(status_attachment())
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

    # name 형식: "menu::섹션", "temp::섹션", "size::섹션"
    if "::" in action_name and action_name.split("::",1)[0] in ("menu","temp","size"):
        kind, section = action_name.split("::",1)
        if section in MENU_SECTIONS:
            if kind == "menu":
                # 1) 상태 저장 (메뉴)
                _set_state(channel_log_id, user_id, section, menu=action_value)
                # 2) 본문 원본 attachments 캐시
                if original.get("attachments"):
                    _orig_set(channel_log_id, original["attachments"])
                # 3) 에페메럴 미니창: ICE/HOT 선택 + 제출 버튼
                return pack({
                    "responseType": "ephemeral",
                    "replaceOriginal": False,
                    "text": f"선택한 메뉴: {section} / {action_value}\nICE/HOT 를 선택하고 '선택'을 눌러 투표를 반영하세요.",
                    "attachments": [
                        {
                            "callbackId": "coffee-poll-ephemeral",
                            "actions": [
                                {
                                    "name": f"etemp::{section}|{channel_log_id}",
                                    "text": "ICE/HOT",
                                    "type": "select",
                                    "options": TEMP_OPTIONS  # HOT/ICE
                                },
                                {
                                    "name": "eapply",
                                    "text": "선택",
                                    "type": "button",
                                    "value": f"eapply|{section}|{channel_log_id}",
                                    "style": "primary"
                                }
                            ]
                        }
                    ]
                })

            elif kind == "temp":
                _set_state(channel_log_id, user_id, section, temp=action_value)
            elif kind == "size":
                _set_state(channel_log_id, user_id, section, size=action_value)

        # 에페메럴/버튼 외 나머지는 업데이트 없이 200 OK
        return pack({})
    
    # 에페메럴 ICE/HOT 셀렉트: name = "etemp::<section>|<main_id>"
    if action_name.startswith("etemp::"):
        meta = action_name.split("::",1)[1]  # "<section>|<main_id>"
        try:
            section, main_id = meta.split("|", 1)
        except ValueError:
            return pack({})
        if section in MENU_SECTIONS:
            # 상태는 메인 메시지 기준 main_id 로 저장/갱신
            _set_state(main_id, user_id, section, temp=action_value)
        return pack({})

    # 에페메럴 "선택" 버튼: value = "eapply|<section>|<main_id>"
    if action_value.startswith("eapply|"):
        _, section, main_id = action_value.split("|", 2)

        # 1) 상태 읽기 (키는 main_id 기준)
        st = _get_state(main_id, user_id, section)
        menu = st["menu"] or MENU_SECTIONS[section][0]
        temp = st["temp"] or "HOT"
        size = st.get("size") or "no"   # 현재는 사용 안하지만 혹시 모를 확장 대비

        key = f"{section} / {menu} ({temp},{'사이즈업' if size=='yes' else '기본'})"

        # 2) 본문 원본 attachments 로딩 (캐시에서)
        orig_atts = _orig_get(main_id)
        if not orig_atts:
            # 캐시가 없으면 에페메럴 안내만 하고 종료 (본문은 건드리지 않음)
            return pack({
                "responseType": "ephemeral",
                "text": "⚠️ 본문 메시지를 찾을 수 없어 투표 반영에 실패했어요. 다시 시도해 주세요."
            })

        # 3) 현황 업데이트
        status = {}
        # 기존 현황 파싱
        for att in (orig_atts or []):
            if att.get("title") == "--------------선택 현황--------------" or att.get("title") == "선택 현황":
                for f in att.get("fields", []):
                    k = f.get("title") or ""
                    v = (f.get("value") or "").strip()
                    if k:
                        status[k] = [x for x in v.split() if x]
        # 중복 제거 후 새 항목에 반영
        for k in list(status.keys()):
            if user_email in status[k]:
                status[k] = [u for u in status[k] if u != user_email]
        status.setdefault(key, [])
        if user_email not in status[key]:
            status[key].append(user_email)

        # 4) 새 attachments 구성 (UI 블록은 그대로, 현황만 갈아끼움)
        new_atts = []
        replaced = False
        for att in orig_atts:
            if att.get("title") == "--------------선택 현황--------------" or att.get("title") == "선택 현황":
                new_atts.append({
                    "title": "--------------선택 현황--------------",
                    "fields": [
                        {"title": k, "value": " ".join(v) if v else "-", "short": False}
                        for k, v in status.items()
                    ] or [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
                })
                replaced = True
            else:
                new_atts.append(att)
        if not replaced:
            # 만약 원본에 현황 블록이 없었다면 추가
            new_atts.append({
                "title": "--------------선택 현황--------------",
                "fields": [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
            })

        # 5) 본문 업데이트 (replaceOriginal=True)
        return pack({
            "text": (original.get("text") or "☕ 커피 투표 - 에뜨리에"),
            "attachments": new_atts,
            "responseType": "inChannel",
            "replaceOriginal": True
        })

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
