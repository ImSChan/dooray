# api/index.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Coffee Poll Demo (Sections)")

# 섹션별 메뉴
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

TEMP_OPTIONS = [{"text": "ICE", "value": "ICE"}, {"text": "HOT", "value": "HOT"}]
SIZE_OPTIONS = [{"text": "사이즈업 X", "value": "no"}, {"text": "사이즈업", "value": "yes"}]

def build_menu_options(section: str):
    return [{"text": f"[{section}] {item}", "value": item} for item in MENU_SECTIONS[section]]

def make_item_attachment(slot: int, section: str) -> dict:
    return {
        "callbackId": "coffee-poll",
        "title": f"항목 {slot} — {section}",
        "actions": [
            {
                "name": f"menu_{slot}",
                "text": "메뉴 선택",
                "type": "select",
                "options": build_menu_options(section),
            },
            {"name": f"temp_{slot}", "text": "ICE/HOT", "type": "select", "options": TEMP_OPTIONS},
            {"name": f"size_{slot}", "text": "사이즈", "type": "select", "options": SIZE_OPTIONS},
            {"name": f"vote_{slot}", "text": "선택", "type": "button", "value": f"vote|pending|{slot}", "style": "primary"},
        ],
    }

@app.post("/dooray/command")
def coffee_command():
    # 슬롯 1~3을 각각 섹션에 고정
    attachments = [
        make_item_attachment(1, "추천메뉴"),
        make_item_attachment(2, "스무디"),
        make_item_attachment(3, "커피"),
        make_item_attachment(4, "음료"),
        make_item_attachment(5, "병음료"),
        {
            "title": "선택 현황",
            "fields": [{"title": "아직 투표 없음", "value": "첫 투표를 기다리는 중!", "short": False}],
        },
    ]
    payload = {
        "responseType": "inChannel",
        "replaceOriginal": False,
        "text": "☕ 커피 투표 - 에뜨리에",
        "attachments": attachments,
    }
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")
