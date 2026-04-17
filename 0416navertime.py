import os
import requests
from datetime import datetime, timedelta
from openai import OpenAI
import html

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
        "지도 데이터", "위치정보", "로보택시"
    ],
    "모빌리티 동향": [
        "현대차", "테슬라", "수입차",
        "전기차", "전기차 충전",
        "대리운전", "자율주행", "인포테인먼트", "SDV",
        "모빌리티 정책", "택시 규제", "자율주행 허가"
    ],
    "IT 업계 동향": [
        "AI", "빅테크", "엔비디아", "삼성전자",
        "구글", "애플", "쿠팡", "배민", "토스",
        "카카오", "네이버",
        "플랫폼 규제", "개인정보", "해킹",
        "데이터 정책", "검색 점유율", "지도 경쟁"
    ]
}

all_news = []
seen_links = set()
seen_titles = set()

def normalize_title(title):
    return html.unescape(title).replace(" ", "").lower()

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

# 🔹 네이버 뉴스 API (🔥 pubDate 사용)
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
        title = html.unescape(item["title"])
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

                if norm in seen_titles:
                    continue
                if link in seen_links:
                    continue

                seen_titles.add(norm)
                seen_links.add(link)
                all_news.append((title, link, category, pub_date))

            except:
                continue

print("총 기사:", len(all_news))

# 🔹 필터
all_news = pre_filter(all_news)
print("필터 후:", len(all_news))

# 🔥 오늘 기사 필터 (크롤링 제거)
filtered_news = []
now = datetime.utcnow() + timedelta(hours=9)
cutoff = now - timedelta(hours=24)

for title, link, category, pub_date in all_news:
    if pub_date and pub_date >= cutoff:
        filtered_news.append((title, link, category))

all_news = filtered_news
print("오늘 기사:", len(all_news))

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

# 🔥 바로 GPT (1회 호출)
final_input = "\n".join([
    f"{category} | {title} | {link}"
    for title, link, category in all_news
])

final_prompt = f"""
다음 뉴스 목록을 "이슈 중심 미디어 브리핑"으로 재구성하라.

핵심:
- 동일 이슈의 완전 중복 기사만 제거
- 같은 이슈라도 관점이 다르면 유지
- 기사 요약 금지
- 설명 문장 금지
- 반드시 "기사 제목 + URL" 형태로만 출력

중요:
- 지나치게 많이 제거하지 말 것
- 각 카테고리는 가능한 최대 개수에 가깝게 채울 것

기사 수 규칙:
- 자사 및 경쟁사 동향: 최대 8건
- 모빌리티 동향: 최대 8건
- IT 업계 동향: 최대 8건

출력 형식 (절대 변경 금지):

[미디어브리핑-{today}]

■ 자사 및 경쟁사 동향

기사 제목
URL

■ 모빌리티 동향

기사 제목
URL

■ IT 업계 동향

기사 제목
URL

뉴스:
{final_input}
"""

final_result = call_gpt(final_prompt)

print("\n===== 결과 =====\n")
print(final_result)

requests.post(
    SLACK_WEBHOOK_URL,
    json={"text": final_result},
    timeout=30
)

print("Slack 전송 완료")
