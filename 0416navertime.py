import os
import requests
from datetime import datetime, timedelta
from openai import OpenAI
import time
import html
from bs4 import BeautifulSoup

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

# 🔹 필터 (약하게 유지)
def pre_filter(news):
    result = []
    for title, link, category in news:
        if not title or not link:
            continue
        if len(title) < 15 or len(title) > 120:
            continue
        if any(x in link for x in ["blog", "cafe", "sports", "entertain"]):
            continue
        result.append((title, link, category))
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
        title = html.unescape(item["title"])
        link = item["link"]

        if "n.news.naver.com" in link:
            link = item.get("originallink", link)

        results.append((title, link))

    return results

# 🔥 기사 시간 가져오기
def get_article_datetime(url):
    try:
        res = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, "html.parser")

        tag = soup.select_one("span.media_end_head_info_datestamp_time")
        if tag and tag.get("data-date-time"):
            return datetime.strptime(tag["data-date-time"], "%Y-%m-%d %H:%M:%S")

        meta = soup.find("meta", {"property": "article:published_time"})
        if meta:
            return datetime.fromisoformat(meta["content"])

    except:
        return None

    return None

print("\n===== 뉴스 수집 시작 =====\n")

for category, keywords in KEYWORDS.items():
    for keyword in keywords:
        news_list = get_naver_news(keyword)

        for title, link in news_list:
            try:
                norm = normalize_title(title)

                if norm in seen_titles:
                    continue
                if link in seen_links:
                    continue

                seen_titles.add(norm)
                seen_links.add(link)
                all_news.append((title, link, category))

            except:
                continue

print("총 기사:", len(all_news))

# 🔹 필터
all_news = pre_filter(all_news)
print("필터 후:", len(all_news))

# 🔥 오늘 기사 필터
filtered_news = []
now = datetime.utcnow() + timedelta(hours=9)
cutoff = now - timedelta(hours=24)

for title, link, category in all_news:
    dt = get_article_datetime(link)

    if dt and dt >= cutoff:
        filtered_news.append((title, link, category))

    time.sleep(0.15)

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

def chunk_list(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]

today = (datetime.utcnow() + timedelta(hours=9)).strftime("%y%m%d")

# 🔥 1차
partial_results = []

for chunk in chunk_list(all_news, 50):
    news_text = "\n".join([
        f"{category} | {title} | {link}"
        for title, link, category in chunk
    ])

    prompt = f"""
다음 뉴스 리스트에서 티맵모빌리티 홍보팀 기준으로 "이슈 단위 브리핑 가치"가 있는 기사를 선별하라.

중요:
- 과도하게 제거하지 말 것
- 전체 기사 중 최소 80% 이상 유지할 것
- 기사 단위가 아니라 "이슈 단위"로 판단하되, 다양한 이슈는 최대한 살릴 것

선별 원칙:
1. 완전히 동일한 기사(같은 링크)만 제거
2. 같은 이슈라도 관점이나 내용이 다르면 유지

포함 기준:
- 티맵 및 경쟁사 관련
- 모빌리티 산업 변화 (자율주행, 전기차 등)
- 플랫폼 / 지도 / 데이터 / AI / 규제
- 사업 영향 가능성이 있는 기술 및 정책 변화

제외 기준:
- 연예 / 스포츠 / 사건사고 / 명백히 무관한 기사

우선순위:
1) 티맵 직접 영향
2) 경쟁사 전략 변화
3) 시장 구조 변화
4) 규제 / 정책
5) 기술 트렌드

출력:
카테고리 | 기사 제목 | URL

뉴스:
{news_text}
"""

    result = call_gpt(prompt)
    if result:
        partial_results.append(result)

    time.sleep(1.5)

# 🔥 2차
final_input = "\n".join(partial_results)

final_prompt = f"""
다음은 1차 선별된 뉴스 목록이다.
이를 "이슈 중심 미디어 브리핑"으로 재구성하라.

핵심:
- 동일 이슈의 완전 중복 기사만 제거
- 같은 이슈라도 관점이 다르면 유지
- 기사 요약 금지
- 설명 문장 금지
- 반드시 "기사 제목 + URL" 형태로만 출력

중요:
- 지나치게 많이 제거하지 말 것
- 각 카테고리는 가능한 최대 개수에 가깝게 채울 것
- 기사 수가 부족하면 유사 이슈라도 유지할 것

선별 기준:
- 아래 기준을 우선 고려하되, 관련성이 있으면 유연하게 포함:
  - 사업 영향
  - 경쟁 구도 변화
  - 규제 / 정책 영향
  - 기술 변화가 사업에 미치는 영향

- 반드시 포함:
  - 티맵 관련 핵심 기사 (있을 경우 최상단 배치)
  - 경쟁사 전략 변화
  - 플랫폼/데이터/지도 경쟁
  - 규제 및 정책 변화

- 반드시 제거:
  - 완전히 동일한 기사 (같은 링크)
  - 단순 이벤트 / 홍보성 반복 기사

기사 수 규칙:
- 자사 및 경쟁사 동향: 최대 8건 (가능하면 6~7건 이상은 채울 것)
- 모빌리티 동향: 최대 8건 (가능하면 4~5건 이상은 채울 것)
- IT 업계 동향: 최대 8건 (가능하면 4~5건 이상은 채울 것)

정렬 규칙:
1. 자사 기사 최상단
2. 같은 이슈끼리 묶기
3. 중요도 순 정렬

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

⚠️ 절대 규칙:
- 위 형식에서 한 글자도 바꾸지 말 것
- 설명, 요약, 추가 문장 절대 금지
- 기사 제목과 URL 외 아무 것도 출력하지 말 것

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