
import boto3, json, hashlib, urllib.request, datetime
from bs4 import BeautifulSoup
from boto3.dynamodb.conditions import Key
import requests, os
import re
from urllib.parse import urljoin, urlparse
import time

dynamodb = boto3.resource("dynamodb")
bedrock_rt = boto3.client("bedrock-runtime")
table = dynamodb.Table("pakka_articles")

PAKKA_URLS = [
    {"url": "https://www.india.gov.in/", "outlet": "India.gov.in — National Portal"},
    {"url": "https://sansad.in/", "outlet": "Sansad (Parliament of India)"},
    {"url": "https://igod.gov.in/", "outlet": "India Government Open Data"},
    {"url": "https://asiagracircle.in/", "outlet": "Asia GRA Circle"},
    {"url": "https://indiacode.gov.in/", "outlet": "India Code — Legislative Dept."},
    {"url": "https://www.sci.gov.in/", "outlet": "Supreme Court of India"},
    {"url": "https://ecourts.gov.in/ecourts2.0/", "outlet": "eCourts India"},
    {"url": "https://lawcommissionofindia.nic.in/", "outlet": "Law Commission of India"},
    {"url": "https://www.pib.gov.in/", "outlet": "Press Information Bureau"},
    {"url": "https://www.pib.gov.in/newsite/pmreleases.aspx?mincode=33&reg=48&lang=2", "outlet": "PIB — PM Releases"},
    {"url": "https://www.indiabudget.gov.in/", "outlet": "Union Budget of India"},
    {"url": "https://yas.gov.in/", "outlet": "Ministry of Youth Affairs & Sports"},
    {"url": "https://sportsauthorityofindia.nic.in/sai_new/", "outlet": "Sports Authority of India"},
    {"url": "https://www.isro.gov.in/", "outlet": "ISRO"},
    {"url": "https://indianairforce.nic.in/", "outlet": "Indian Air Force"},
    {"url": "https://indiannavy.gov.in/", "outlet": "Indian Navy"},
    {"url": "https://indianarmy.nic.in/", "outlet": "Indian Army"},
    {"url": "https://www.drdo.gov.in/drdo/", "outlet": "DRDO"},
    {"url": "https://www.ddpmod.gov.in/en", "outlet": "Dept. of Defence Production"},
    {"url": "https://www.mod.gov.in/dod/en/history-division-0", "outlet": "MoD — History Division"},
    {"url": "https://www.mod.gov.in/en", "outlet": "Ministry of Defence"},
    {"url": "https://desw.gov.in/", "outlet": "Dept. of Ex-Servicemen Welfare"},
    {"url": "https://www.dmamod.gov.in/", "outlet": "Dept. of Military Affairs"},
    {"url": "https://www.mea.gov.in/", "outlet": "Ministry of External Affairs"},
]

def fetch_clean(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=10).read()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title else url
    text = " ".join(soup.get_text(separator=" ").split())[:3000]
    return title, text

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") 

def summarize(title, text, outlet, retries=3):
    if len(text.strip()) < 300:
        return "Limited content available from this page — visit the source for full details."

    prompt = (
        f"Write a short, strictly neutral, factual news-style summary (2-3 sentences) "
        f"of the following content from {outlet}. No opinion, no speculation.\n\n{text[:2000]}"
    )

    for attempt in range(retries):
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150,
                "temperature": 0.3
            }
        )
        data = resp.json()

        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()

        if data.get("error", {}).get("code") == "rate_limit_exceeded":
            wait = 17  # a bit above what Groq's error message reports
            print(f"Rate limited, waiting {wait}s before retry {attempt + 1}/{retries}...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"Groq API error: {data}")

    raise RuntimeError("Groq API: exceeded retries after repeated rate limiting")

NEWS_KEYWORDS = [
    "press", "release", "notification", "circular", "notice",
    "news", "update", "order", "judgment", "launch", "advisory",
    "tender", "recruitment", "result", "new"
]

def find_news_links(homepage_url, soup, max_links=4):
    candidates = []
    base_domain = urlparse(homepage_url).netloc

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text(strip=True).lower()

        if not href or href.startswith("#") or href.startswith("javascript"):
            continue

        full_url = urljoin(homepage_url, href)
        if urlparse(full_url).netloc != base_domain:
            continue  # stay on the same site

        # score by keyword match in URL or link text
        combined = (href + " " + link_text).lower()
        if any(kw in combined for kw in NEWS_KEYWORDS):
            candidates.append(full_url)

    # dedupe, keep order
    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique[:max_links]

def fetch_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=10).read()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title else url
    text = " ".join(soup.get_text(separator=" ").split())
    return title, text, soup

def handler(event, context):
    new_count = 0
    for src in PAKKA_URLS:
        try:
            title, text, soup = fetch_page(src["url"])
        except Exception:
            continue

        # find real news/update links on this homepage
        sub_links = find_news_links(src["url"], soup, max_links=2)

        pages_to_process = [(src["url"], title, text)]  # fallback: homepage itself
        if sub_links:
            pages_to_process = []
            for link in sub_links:
                try:
                    sub_title, sub_text, _ = fetch_page(link)
                    if len(sub_text.strip()) >= 300:  # skip thin pages
                        pages_to_process.append((link, sub_title, sub_text[:3000]))
                except Exception:
                    continue

        for page_url, page_title, page_text in pages_to_process:
            content_hash = hashlib.sha256(page_text.encode()).hexdigest()

            existing = table.query(
                KeyConditionExpression=Key("source_url").eq(page_url),
                ScanIndexForward=False,
                Limit=1
            )["Items"]

            if existing and existing[0]["content_hash"] == content_hash:
                continue

            summary = summarize(page_title, page_text, src["outlet"])
            now = datetime.datetime.now(datetime.UTC).isoformat()

            table.put_item(Item={
                "source_url": page_url,
                "fetched_at": now,
                "outlet": src["outlet"],
                "title": page_title,
                "summary": summary,
                "content_hash": content_hash
            })
            new_count += 1

    return {"new_articles": new_count}

if __name__ == "__main__":
    result = handler({}, {})
    print(result)