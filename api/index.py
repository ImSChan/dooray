from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Coffee Poll Demo")

# 공통 옵션 목록
MENU_OPTIONS = [
    {"text": "[추천메뉴] 더치커피", "value": "더치커피"},
    {"text": "[추천메뉴] 아메리카노", "value": "아메리카노"},
    {"text": "[스무디] 딸기주스", "value": "딸기주스"},
    {"text": "[스무디] 바나나주스", "value": "바나나주스"},
    {"text": "[커피] 에스프레소", "value": "에스프레소"},
    {"text": "[커피] 아메리카노", "value": "아메리카노"},
    {"text": "[음료] 그린티 라떼", "value": "그린티 라떼"},
    {"text": "[음료] 오곡라떼", "value": "오곡라떼"},
    {"text": "[병음료] 분다버그 진저", "value": "분다버그 진저"},
    {"text": "[병음료] 분다버그 레몬에이드", "value": "분다버그 레몬에이드"},
    {"text": "[병음료] 분다버그 망고", "value": "분다버그 망고"},
    {"text": "[병음료] 분다버그 자몽", "value": "분다버그 자몽"},
]

TEMP_OPTIONS = [
    {"text": "ICE", "value": "ICE"},
    {"text": "HOT", "value": "HOT"},
]

SIZE_OPTIONS = [
    {"text": "사이즈업 X", "value": "no"},
    {"text": "사이즈업", "value": "yes"},
]


def make_item_attachment(slot: int) -> dict:
    return {
        "callbackId": "coffee-poll",
        "title": f"항목 {slot}",
        "actions": [
            {
                "name": f"menu_{slot}",
                "text": "메뉴 선택",
                "type": "select",
                "options": MENU_OPTIONS,
            },
            {
                "name": f"temp_{slot}",
                "text": "ICE/HOT",
                "type": "select",
                "options": TEMP_OPTIONS,
            },
            {
                "name": f"size_{slot}",
                "text": "사이즈",
                "type": "select",
                "options": SIZE_OPTIONS,
            },
            {
                "name": f"vote_{slot}",
                "text": "선택",
                "type": "button",
                "value": f"vote|pending|{slot}",
                "style": "primary",
            },
        ],
    }


@app.post("/dooray/command")
def coffee_command():
    payload = {
        "responseType": "inChannel",
        "replaceOriginal": False,
        "text": "☕ 커피 투표 - 에뜨리에",
        "attachments": [
            make_item_attachment(1),
            make_item_attachment(2),
            make_item_attachment(3),
            {
                "title": "선택 현황",
                "fields": [
                    {
                        "title": "아직 투표 없음",
                        "value": "첫 투표를 기다리는 중!",
                        "short": False,
                    }
                ],
            },
        ],
    }
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")
