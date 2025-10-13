# api/index.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import json

app = FastAPI(title="Coffee Poll – step-by-step")

# ----- 메뉴 섹션 -----
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

TEMP_OPTIONS = [{"text":"ICE","value":"ICE"},{"text":"HOT","value":"HOT"}]
SIZE_OPTIONS = [{"text":"사이즈업 X","value":"no"},{"text":"사이즈업","value":"yes"}]

# ----- 공통 빌더 -----
def section_select(slot:int):
    return {
        "callbackId":"coffee-poll",
        "title": f"항목 {slot}",
        "actions":[
            {
                "name": f"section_{slot}",
                "text": "항목 선택 (추천메뉴/스무디/커피/음료/병음료)",
                "type": "select",
                "options": [{"text": s, "value": s} for s in MENU_SECTIONS.keys()],
                # 선택하면 다음 단계: section|slot|섹션
            }
        ]
    }

def menu_select(slot:int, section:str):
    return {
        "callbackId":"coffee-poll",
        "title": f"항목 {slot} — {section}",
        "actions":[
            {
                "name": f"menu_{slot}",
                "text": "메뉴 선택",
                "type":"select",
                "options":[{"text": f"[{section}] {m}", "value": m} for m in MENU_SECTIONS[section]],
                # 다음: menu|slot|section|menu
            }
        ]
    }

def temp_select(slot:int, section:str, menu:str):
    return {
        "callbackId":"coffee-poll",
        "title": f"항목 {slot} — {section} / {menu}",
        "actions":[
            {
                "name": f"temp_{slot}",
                "text":"ICE/HOT",
                "type":"select",
                "options": TEMP_OPTIONS,
                # 다음: temp|slot|section|menu|ICEHOT
            }
        ]
    }

def size_select_and_vote(slot:int, section:str, menu:str, icehot:str):
    return {
        "callbackId":"coffee-poll",
        "title": f"항목 {slot} — {section} / {menu} / {icehot}",
        "actions":[
            {"name":f"size_{slot}","text":"사이즈","type":"select","options":SIZE_OPTIONS},
            # 선택하면 아래 버튼으로 확정
            {"name":f"vote_{slot}","text":"선택","type":"button",
             "value": f"vote|{slot}|{section}|{menu}|{icehot}|pending", "style":"primary"}
        ]
    }

def status_attachment(fields:list[dict]|None=None):
    return {
        "title":"선택 현황",
        "fields": fields or [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
    }

def pack(payload:dict):  # 응답 포맷 고정
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

# ----- 상태 파서 (선택 현황 ←→ dict) -----
def parse_status_from_original(original_msg:dict)->dict[str,list[str]]:
    """
    originalMessage.attachments[*].title == '선택 현황'
    fields: [{title:'라떼 (ICE,사이즈업)', value:'user1 user2', short:false}]
    -> { '라떼 (ICE,사이즈업)': ['user1','user2'], ...}
    """
    result={}
    atts = (original_msg or {}).get("attachments") or []
    for att in atts:
        if att.get("title") == "선택 현황":
            for f in att.get("fields",[]):
                key = f.get("title","").strip()
                val = (f.get("value","") or "").strip()
                if not key: continue
                users = [x for x in val.split() if x]
                if key: result[key]=users
    return result

def build_status_fields(status:dict)->list[dict]:
    if not status:
        return [{"title":"아직 투표 없음","value":"첫 투표를 기다리는 중!","short":False}]
    fields=[]
    for key, users in status.items():
        fields.append({"title":key, "value":" ".join(users) if users else "-", "short":False})
    return fields

# ----- 엔드포인트 -----
@app.post("/dooray/command")
def coffee_command():
    payload = {
        "responseType":"inChannel",
        "replaceOriginal": False,
        "text":"☕ 커피 투표 - 에뜨리에",
        "attachments": [
            section_select(1),
            section_select(2),
            section_select(3),
            status_attachment()
        ]
    }
    return pack(payload)

@app.post("/dooray/actions")
async def coffee_actions(req: Request):
    data = await req.json()
    action_name = data.get("actionName")
    action_value = (data.get("actionValue") or "").strip()
    original = data.get("originalMessage") or {}
    user_email = (data.get("user") or {}).get("email","user")

    # 현재 상태(선택 현황) 복구
    status = parse_status_from_original(original)

    # 원본 기본 attachments (항상 3 슬롯 + 현황)
    # 변환 시, 해당 슬롯만 단계에 맞춰 교체한다.
    base_atts = [
        section_select(1),
        section_select(2),
        section_select(3),
    ]

    # 드롭다운(select)은 Dooray가 선택된 option의 value를 actionValue로 보냄
    # 어떤 select인지 name으로 구분
    # name 예: section_1 / menu_2 / temp_3 / size_1
    name = action_name or ""
    if name.startswith("section_"):  # step1 -> step2
        slot = int(name.split("_")[1])
        section = action_value
        base_atts[slot-1] = menu_select(slot, section)

    elif name.startswith("menu_"):   # step2 -> step3
        slot = int(name.split("_")[1])
        section = find_section_from_title(original, slot) or ""   # 보호적 추출
        # fallback: section은 actionValue만으로 못 알면 title에서 꺼낸다
        base_atts[slot-1] = temp_select(slot, section, action_value)

    elif name.startswith("temp_"):   # step3 -> step4
        slot = int(name.split("_")[1])
        section, menu = find_section_menu_from_title(original, slot)
        base_atts[slot-1] = size_select_and_vote(slot, section, menu, action_value)

    elif name.startswith("size_"):
        # size 선택 자체는 UI만 바뀌지 않음. 버튼 value의 'pending'을 실제 사이즈로 치환해주면 되지만
        # Dooray는 select value만 보내므로, 여기선 버튼을 size 반영해 교체해서 돌려준다.
        slot = int(name.split("_")[1])
        section, menu, icehot = find_full_from_title(original, slot)
        size = action_value
        att = size_select_and_vote(slot, section, menu, icehot)
        # 버튼 value의 pending -> 실제 size로 교체
        for a in att["actions"]:
            if a.get("name")==f"vote_{slot}" and a.get("type")=="button":
                a["value"] = f"vote|{slot}|{section}|{menu}|{icehot}|{size}"
        base_atts[slot-1] = att

    elif action_value.startswith("vote|"):
        # vote|slot|section|menu|icehot|size
        _, _, section, menu, icehot, size = action_value.split("|", 5)
        key = f"{menu} ({icehot},{'사이즈업' if size=='yes' else '기본'})"

        # 중복투표 처리(덮어쓰기): 모든 key에서 해당 user 제거 후, 새 key에 추가
        for k in list(status.keys()):
            if user_email in status[k]:
                status[k] = [u for u in status[k] if u != user_email]
        status.setdefault(key, [])
        if user_email not in status[key]:
            status[key].append(user_email)

    # 현황 마지막 attachment 추가
    atts = base_atts + [status_attachment(build_status_fields(status))]
    return pack({"text":"☕ 커피 투표 - 에뜨리에", "attachments": atts,
                 "responseType":"inChannel", "replaceOriginal": True})

# ------ helpers to pull step context from original titles ------
def find_section_from_title(original:dict, slot:int)->str|None:
    for att in original.get("attachments",[]):
        title = att.get("title","")
        if title.startswith(f"항목 {slot} — "):
            return title.split(" — ",1)[1].split(" / ")[0].strip()
    return None

def find_section_menu_from_title(original:dict, slot:int):
    for att in original.get("attachments",[]):
        title = att.get("title","")
        if title.startswith(f"항목 {slot} — "):
            parts = title.split(" — ",1)[1].split(" / ")
            section = parts[0].strip()
            menu = parts[1].strip() if len(parts)>1 else ""
            return section, menu
    return "", ""

def find_full_from_title(original:dict, slot:int):
    for att in original.get("attachments",[]):
        title = att.get("title","")
        if title.startswith(f"항목 {slot} — "):
            parts = title.split(" — ",1)[1].split(" / ")
            section = parts[0].strip()
            menu = parts[1].strip() if len(parts)>1 else ""
            icehot = parts[2].strip() if len(parts)>2 else ""
            return section, menu, icehot
    return "", "", ""
