import os
import requests
from datetime import datetime, timedelta
from openai import OpenAI
import html
import re  # ← 추가
from difflib import SequenceMatcher

def clean_html(raw):  # ← 추가
    return re.sub(r'<.*?>', '', raw)
    
print("시작됨")

# ✅ API 키
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

NAVER_CLIENT_ID = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

# 🔥 키워드 그대로 유지
KEYWORDS = {
    "자사 및 경쟁사 동향": [
        "티맵", "티맵모빌리티", "TMAP", "우버",
        "카카오모빌리티", "카카오T", "쏘카",
        "네이버 지도", "카카오맵", "구글맵", "구글지도",
        "네이버 내비", "카카오 내비", "현대오토에버",
        "지도 데이터", "위치정보", "로보택시", "지도경쟁", "택시 규제"
    ],
    "모빌리티 동향": [
        "현대차", "테슬라", "수입차",
        "전기차", "전기차 충전",
        "대리운전", "자율주행", "인포테인먼트", "SDV",
        "모빌리티 정책", "자율주행 허가"
    ],
    "IT 업계 동향": [
        "AI", "빅테크", "엔비디아", "삼성전자",
        "구글", "애플", "쿠팡", "배민", "토스",
        "카카오", "네이버",
        "플랫폼 규제", "개인정보", "해킹",
        "데이터 정책", "검색 점유율"
    ]
}

all_news = []
seen_links = set()
seen_prefix = set()

def normalize_title(title):
    title = clean_html(html.unescape(title))
    title = title.lower()

    # 괄호/특수문자 제거
    title = re.sub(r'\(.*?\)|\[.*?\]', '', title)
    title = re.sub(r'[^가-힣a-z0-9 ]', '', title)

    # 의미 없는 단어 제거
    title = re.sub(r'(단독|속보|종합)', '', title)

    # 공백 제거
    title = title.replace(" ", "")

    return title

# 🔹 필터
def pre_filter(news):
    result = []
    for title, link, category, pub_date in news:
        if not title or not link:
            continue
        if len(title) < 15 or len(title) > 120:
            continue
        if any(x in link for x in ["blog", "cafe", "sports", "entertain"]):
            continue
        result.append((title, link, category, pub_date))
    return result

# 🔹 네이버 뉴스 API
def get_naver_news(keyword):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": keyword,
        "display": 50,
        "sort": "date"
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
    except:
        return []

    results = []
    for item in data.get("items", []):
        title = clean_html(html.unescape(item["title"]))
        link = item["link"]

        if "n.news.naver.com" in link:
            link = item.get("originallink", link)

        try:
            pub_date = datetime.strptime(item["pubDate"], "%a, %d %b %Y %H:%M:%S %z")
            pub_date = pub_date.astimezone().replace(tzinfo=None)
        except:
            pub_date = None

        results.append((title, link, pub_date))

    return results

print("\n===== 뉴스 수집 시작 =====\n")

# 🔹 수집
for category, keywords in KEYWORDS.items():
    for keyword in keywords:
        news_list = get_naver_news(keyword)

        for title, link, pub_date in news_list:
            try:
                norm = normalize_title(title)

                # 🔥 prefix 기반 중복 제거 (핵심)
                def get_prefix(title):
                    title = clean_html(html.unescape(title))
                    title = re.sub(r'[^가-힣a-zA-Z0-9 ]', '', title)
                    words = title.split()
                    return " ".join(words[:4])

                prefix = get_prefix(title)

                if prefix in seen_prefix:
                    continue

                # 기존 링크 중복 제거는 유지
                if link in seen_links:
                    continue

                seen_prefix.add(prefix)
                seen_links.add(link)
                all_news.append((title, link, category, pub_date))

            except:
                continue

print("총 기사:", len(all_news))

# 🔹 필터
all_news = pre_filter(all_news)
print("필터 후:", len(all_news))

# 🔥 시간 필터 + fallback
filtered_news = []
now = datetime.utcnow() + timedelta(hours=9)
cutoff = now - timedelta(hours=36)

for title, link, category, pub_date in all_news:
    if pub_date and pub_date >= cutoff:
        filtered_news.append((title, link, category))

if not filtered_news:
    print("⚠️ 오늘 기사 없음 → 전체 기사 사용")
    filtered_news = [(t, l, c) for t, l, c, _ in all_news]

all_news = filtered_news
print("오늘 기사:", len(all_news))

# 🔥 GPT 과부하 방지 (핵심)
all_news = all_news[:300]

if not all_news:
    print("기사 없음")
    exit()

# 🔹 GPT 호출
def call_gpt(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return res.choices[0].message.content.strip()
    except:
        return ""

today = (datetime.utcnow() + timedelta(hours=9)).strftime("%y%m%d")

# 🔥 GPT 입력
final_input = "\n".join([
    f"{category} | {title} | {link}"
    for title, link, category in all_news
])

final_prompt = f"""
다음 뉴스 리스트에서 티맵모빌리티 홍보팀 기준으로 "이슈 단위 브리핑 가치"가 있는 기사를 선별하라.

중요:
- 과도하게 제거하지 말 것
- 전체 기사 중 최소 80% 이상 유지할 것
- 기사 단위가 아니라 "이슈 단위"로 판단하되, 다양한 이슈는 최대한 살릴 것

선별 원칙:
1. 완전히 동일한 기사, 동일 링크, 재송고성 유사 기사만 제거하라.
2. 같은 이슈라도 매체 관점이나 내용 포인트가 다르면 별도 기사로 인정할 수 있다. (그러나 대부분 헤드라인 많이 겹치면 지워라)
3. 아래 기사는 우선 제외:
   - 순수 정치
   - 일반 사건사고
   - 단순 지역 행사
   - 산업/서비스/경쟁사/규제/기술과 무관한 기사
4. 애매한 경우에는 포함 여부를 보수적으로 판단하되, 브리핑 가치가 낮으면 제외하라.
5. 반드시 24시간 이내 기사만 포함하라. (eg. 네이버 상에서 00시간 전, 분전 기사만 남기고, 0일전 기사는 안됨)
   오래된 기사(하루 이상)는 모두 제거하라.
   
우선순위:
- 티맵 / 티맵모빌리티 / TMAP 직접 언급 기사
- 경쟁사(카카오모빌리티, 우버, 쏘카, 네이버지도 등) 관련 핵심 기사
- 모빌리티 시장 변화, 규제, 제휴, 신사업, 실적, 서비스 출시/중단 기사
- AI, 플랫폼 규제, 개인정보, 빅테크 변화 중 사업 영향이 큰 기사 (트렌드로 참고할 만한 건 남겨놔야 함, 해킹이나 개인정보 같은 정책 이슈는 중요)

기사 수 규칙:
- 자사 및 경쟁사 동향: 최대 8건 (가능하면 6~7건 이상은 채울 것)
- 모빌리티 동향: 최대 8건 (가능하면 7건 이상은 채울 것)
- IT 업계 동향: 최대 8건 (가능하면 7건 이상은 채울 것)

중요:
- 출력이 비어있으면 실패로 간주

출력 형식 (절대 변경 금지):

[미디어브리핑-{today}]

■ 자사 및 경쟁사 동향

기사 제목
URL

기사 제목
URL

■ 모빌리티 동향

기사 제목
URL

기사 제목
URL

■ IT 업계 동향

기사 제목
URL

기사 제목
URL

출력 규칙 (강제):
- 각 기사는 반드시 2줄로 구성 (제목 1줄 + URL 1줄)
- 제목과 URL을 같은 줄에 쓰면 안됨
- 카테고리 아래에는 반드시 한 줄 공백
- 설명, 요약, 추가 문장 절대 금지
- 특수기호(※, -, • 등) 사용 금지
- 형식이 다르면 오답 처리


뉴스:
{final_input}
"""

final_result = call_gpt(final_prompt)

# 🔥 GPT 실패 fallback
if not final_result or len(final_result.strip()) < 20:
    print("⚠️ GPT 결과 비어있음 → fallback 실행")

    final_result = f"[미디어브리핑-{today}]\n\n"

    for category in KEYWORDS.keys():
        final_result += f"■ {category}\n\n"
        sample = [x for x in all_news if x[2] == category][:5]

        for title, link, _ in sample:
            final_result += f"{title}\n{link}\n\n"

print("\n===== 결과 =====\n")
print(final_result)

# 🔹 슬랙 전송
requests.post(
    SLACK_WEBHOOK_URL,
    json={"text": final_result},
    timeout=30
)

print("Slack 전송 완료")
