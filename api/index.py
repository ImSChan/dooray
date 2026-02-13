# api/index.py
from fastapi import FastAPI, Request
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
import httpx
import os

app = FastAPI(title="Coffee Poll – one-click buttons")

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

# ---------- 스타일 ----------
SECTION_STYLE = {
    "추천메뉴": {"emoji": "✨", "color": "#7C3AED"},
    "스무디":   {"emoji": "🍓", "color": "#06B6D4"},
    "커피":     {"emoji": "☕", "color": "#F59E0B"},
    "음료":     {"emoji": "🥤", "color": "#10B981"},
    "병음료":   {"emoji": "🧃", "color": "#EF4444"},
}

# ---------- 유틸 ----------
def pack(payload: dict) -> JSONResponse:
    return JSONResponse(content=payload, media_type="application/json; charset=utf-8")

def mention_member(tenant_id: str, user_id: str, label: str = "member") -> str:
    # Dooray 멤버 태깅 링크 (현황 value에는 그대로 문자열로 넣으면 Dooray가 렌더링함)
    return f'(dooray://{tenant_id}/members/{user_id} "{label}")'
# 1) 현황 파싱: 줄바꿈 기준
def parse_status(original: dict) -> dict:
    """원본 메시지의 '선택 현황'을 dict로 파싱: { '메뉴 (TEMP)': [tag, ...] }"""
    result = {}
    for att in (original.get("attachments") or []):
        if att.get("title") == "선택 현황":
            for f in (att.get("fields") or []):
                k = (f.get("title") or "").strip()
                vraw = (f.get("value") or "").strip()
                if not k:
                    continue  # 빈 타이틀은 무시
                vals = [line for line in vraw.split("\n") if line.strip()]
                result[k] = vals
    return result

# 2) 현황 표시: 줄바꿈으로 join
def status_fields(status: dict):
    if not status:
        return [{"title": "아직 투표 없음", "value": "첫 투표를 기다리는 중!", "short": False}]
    return [{"title": k, "value": "\n".join(v) if v else "-", "short": False}
            for k, v in status.items()]

# 3) placeholder 제거
def status_attachment(fields=None):
    return {
        "title": "선택 현황",
        "fields": fields or [{"title": "아직 투표 없음", "value": "첫 투표를 기다리는 중!", "short": False}]
    }


# ---------- UI 빌더 (버튼) ----------
def section_block_buttons(section: str) -> list[dict]:
    """
    섹션 헤더 + 메뉴별 (ICE)/(HOT) 버튼 한 묶음 생성.
    스무디류는 HOT 버튼을 제거한다.
    버튼 value 형식: vote|{section}|{menu}|{temp}
    """
    s = SECTION_STYLE.get(section, {"emoji": "•", "color": "#4757C4"})
    blocks = []

    # 헤더 블록
    blocks.append({
        "callbackId": "coffee-poll",
        "title": f"{s['emoji']}  {section}",
        "color": s["color"],
    })

    actions = []
    for m in MENU_SECTIONS[section]:

        # 공통 ICE 버튼
        actions.append({
            "name": f"vote::{section}",
            "type": "button",
            "text": f"{m} (ICE)",
            "value": f"vote|{section}|{m}|ICE",
        })

        # 🔥 스무디 제외하고 HOT 버튼 생성
        if (
            section not in ["스무디", "병음료"]
            and m not in ["복숭아 아이스티", "딸기라떼"]
            and "요거트" not in m
        ):
            actions.append({
                "name": f"vote::{section}",
                "type": "button",
                "text": f"{m} (HOT)",
                "value": f"vote|{section}|{m}|HOT",
            })

    # 버튼 블록 추가
    blocks.append({
        "callbackId": "coffee-poll",
        "actions": actions,
        "color": s["color"],
    })

    return blocks

# ---------- 커맨드 ----------
@app.post("/dooray/command")
async def coffee_command(req: Request):
    data = await req.json()
    print(data)
    text = (data.get("text") or "").strip()

    # if text == "":
    #     return pack({
    #         "responseType": "ephemeral",
    #         "text": "☕ 커피 투표: 매장을 선택하세요",
    #         "attachments": [
    #             {"callbackId":"coffee-start","actions":[
    #                 {"name":"start","type":"button","text":"에뜨리에 시작","value":"start|에뜨리에","style":"primary"},
    #                 {"name":"start","type":"button","text":"에뜰 (미지원)","value":"start|에뜰"}
    #             ]}
    #         ]
    #     })

    # if text == "에뜰":
    #    return pack({"responseType":"ephemeral","text":"🚫 아직 '에뜰'은 지원하지 않아요. '에뜨리에'로 시도해 주세요."})

    # 기본: 에뜨리에
    atts = []
    for s in ["추천메뉴","스무디","커피","음료","병음료"]:
        atts.extend(section_block_buttons(s))
    atts.append(status_attachment())  # 선택 현황

    return pack({
        "responseType": "inChannel",
        "replaceOriginal": False,
        "text": "☕ 커피 투표를 시작합니다!",
        "attachments": atts
    })
# ---------- 인터랙션 ----------
@app.post("/dooray/actions")
async def coffee_actions(req: Request):
    data = await req.json()
    action_value = (data.get("actionValue") or "").strip()
    original     = data.get("originalMessage") or {}
    user         = data.get("user") or {}
    user_id      = user.get("id", "user")
    tenant_id    = (data.get("tenant") or {}).get("id", "tenant")

    # vote|섹션|메뉴|TEMP
    if action_value.startswith("vote|"):
        parts = action_value.split("|", 4)
        if len(parts) != 4:
            return pack({})  # 포맷 오류 시 무시
        _, _section, menu, temp = parts

        key = f"{menu} ({temp})"
        
        status = parse_status(original) or {}

        
        # 내 이전 표 전부 제거(전역 1표)
        tag = mention_member(tenant_id, user_id, label="member")
        for k in list(status.keys()):
            voters = [u for u in (status.get(k) or []) if u != tag]
            if voters:
                status[k] = voters
            else:
                del status[k]

        # 새 표 추가
        key = f"{menu} ({temp})"
        status.setdefault(key, [])
        if tag not in status[key]:
            status[key].append(tag)

        # 현황만 교체 (helper 사용)
        fields = status_fields(status)
        new_atts, replaced = [], False
        for att in (original.get("attachments") or []):
            if att.get("title") == "선택 현황":
                new_atts.append(status_attachment(fields))
                replaced = True
            else:
                new_atts.append(att)
        if not replaced:
            new_atts.append(status_attachment(fields))

        return pack({
            "text": original.get("text") or "☕ 커피 투표",
            "attachments": new_atts,
            "responseType": "inChannel",
            "replaceOriginal": True
        })

    # 그 외는 무시
    return pack({})


from openai import OpenAI
import json
from datetime import datetime

gpt_api_key = os.environ.get("OPENAI_API_KEY")

gpt_client = OpenAI(api_key=gpt_api_key)


def analyze_vacation_text(user_text: str) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""
오늘 날짜는 {today} 입니다.

사용자가 입력한 휴가 신청 문장을 분석해서 아래 JSON 형식으로만 응답하세요.

필드:
- start_date (YYYY-MM-DD)
- end_date (YYYY-MM-DD)
- reason (휴가 사유)
- destination (행선지)
- vacation_type (연차/반차/병가/기타 중 하나)

사용자 입력:
\"\"\"{user_text}\"\"\"

반드시 JSON만 출력하세요.
"""

    response = gpt_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "당신은 자연어를 휴가신청 필드로 변환하는 도우미입니다."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    try:
        return json.loads(content)
    except:
        print("GPT 응답 파싱 실패:", content)
        return {}

async def open_vacation_dialog(
    tenant_domain,
    channel_id,
    cmd_token,
    trigger_id,
    vacation_data: dict
):
    url = f"https://{tenant_domain}/messenger/api/channels/{channel_id}/dialogs"

    headers = {
        "Content-Type": "application/json",
        "token": cmd_token,
        "Dooray-Db-Id": "23",
    }

    payload = {
        "token": cmd_token,
        "triggerId": trigger_id,
        "callbackId": "vacation-apply",
        "dialog": {
            "callbackId": "vacation-apply",
            "title": "📅 휴가 신청",
            "submitLabel": "신청하기",
            "elements": [
                {
                    "type": "text",
                    "label": "휴가 시작일",
                    "name": "start_date",
                    "value": vacation_data.get("start_date", ""),
                    "optional": False
                },
                {
                    "type": "text",
                    "label": "휴가 종료일",
                    "name": "end_date",
                    "value": vacation_data.get("end_date", ""),
                    "optional": False
                },
                {
                    "type": "text",
                    "label": "휴가 사유",
                    "name": "reason",
                    "value": vacation_data.get("reason", ""),
                    "optional": False
                },
                {
                    "type": "text",
                    "label": "행선지",
                    "name": "destination",
                    "value": vacation_data.get("destination", ""),
                    "optional": True
                },
                {
                    "type": "select",
                    "label": "휴가 구분",
                    "name": "vacation_type",
                    "value": vacation_data.get("vacation_type", "연차"),
                    "optional": False,
                    "options": [
                        {"label": "연차", "value": "연차"},
                        {"label": "반차", "value": "반차"},
                        {"label": "병가", "value": "병가"},
                        {"label": "기타", "value": "기타"}
                    ]
                }
            ]
        }
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    print("Dialog status:", resp.status_code)
    print("Dialog body:", resp.text)

async def open_dialog(tenant_domain, channel_id, cmd_token, trigger_id):
    url = f"https://{tenant_domain}/messenger/api/channels/{channel_id}/dialogs"
    print(url)
    headers = {
        "Content-Type": "application/json",
        "token": cmd_token,
        "Dooray-Db-Id": "23",   # ← 추가
    }


    payload = {
        "token": cmd_token,
        "triggerId": trigger_id,
        "callbackId": f"open-dialog-test",
        "dialog": {
            "callbackId": f"open-dialog-test",
            "title": "🧪 테스트 Dialog",
            "submitLabel": "확인",
            "elements": [
                {
                    "type": "text",
                    "label": "아무 값 입력",
                    "name": "test",
                    "optional": False
                }
            ]
        }
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    
    print("===== DIALOG RAW RESPONSE =====")
    print("status :", resp.status_code)
    print("headers:", dict(resp.headers))
    print("body   :", resp.text)

    # JSON 파싱 시도
    try:
        body_json = resp.json()
        print("parsed :", json.dumps(body_json, indent=2, ensure_ascii=False))

        header = body_json.get("header")
        if header:
            print("Dooray header.isSuccessful:", header.get("isSuccessful"))
            print("Dooray header.resultCode  :", header.get("resultCode"))
            print("Dooray header.resultMsg   :", header.get("resultMessage"))
    except Exception as e:
        print("JSON parse failed:", e)

    return resp.status_code, resp.text


@app.post("/dooray/test")
async def vacation_command(req: Request):
    data = await req.json()
    print("[VACATION COMMAND]", data)

    user_text = (data.get("text") or "").strip()

    tenant_domain = data.get("tenantDomain")
    channel_id = data.get("channelId")
    cmd_token = data.get("cmdToken")
    trigger_id = data.get("triggerId")

    if not user_text:
        return pack({
            "responseType": "ephemeral",
            "text": "예: /휴가신청 내일부터 모레까지 제주도 가족여행"
        })

    # 🔥 GPT 분석
    vacation_data = analyze_vacation_text(user_text)
    print("GPT 분석 결과:", vacation_data)

    # 🔥 Dialog 호출
    await open_vacation_dialog(
        tenant_domain,
        channel_id,
        cmd_token,
        trigger_id,
        vacation_data
    )

    return JSONResponse(status_code=200, content={})
