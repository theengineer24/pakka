import boto3, json

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("pakka_articles")

def handler(event, context):
    params = event.get("queryStringParameters") or {}
    search_term = (params.get("q") or "").strip().lower()

    resp = table.scan()
    items = resp["Items"]

    if search_term:
        items = [
            a for a in items
            if search_term in a["title"].lower()
            or search_term in a["summary"].lower()
            or search_term in a["outlet"].lower()
        ]

    items = sorted(items, key=lambda x: x["fetched_at"], reverse=True)[:50]

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps(items)
    }

import os, requests

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")

OFFICIAL_DOMAINS = [
    "india.gov.in", "sansad.in", "igod.gov.in", "indiacode.gov.in", "sci.gov.in",
    "ecourts.gov.in", "lawcommissionofindia.nic.in", "pib.gov.in", "indiabudget.gov.in",
    "yas.gov.in", "sportsauthorityofindia.nic.in", "isro.gov.in", "indianairforce.nic.in",
    "indiannavy.gov.in", "indianarmy.nic.in", "drdo.gov.in", "ddpmod.gov.in",
    "mod.gov.in", "desw.gov.in", "dmamod.gov.in", "mea.gov.in"
]

def live_search(query, max_results=5):
    site_filter = " OR ".join(f"site:{d}" for d in OFFICIAL_DOMAINS)
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": f"{query} ({site_filter})",
            "num": max_results
        }
    )
    data = resp.json()
    results = []
    for item in data.get("items", []):
        results.append({
            "outlet": item.get("displayLink", ""),
            "title": item.get("title", ""),
            "summary": item.get("snippet", ""),
            "source_url": item.get("link", ""),
            "fetched_at": None,   # signals "live result", not archived
            "live": True
        })
    return results

def handler(event, context):
    params = event.get("queryStringParameters") or {}
    search_term = (params.get("q") or "").strip().lower()

    resp = table.scan()
    items = resp["Items"]

    if search_term:
        items = [
            a for a in items
            if search_term in a["title"].lower()
            or search_term in a["summary"].lower()
            or search_term in a["outlet"].lower()
        ]
        items = sorted(items, key=lambda x: x["fetched_at"], reverse=True)  # no cap when searching

        if len(items) < 3:  # thin local results — go live
            live_results = live_search(search_term)
            items = items + live_results
    else:
        items = sorted(items, key=lambda x: x["fetched_at"], reverse=True)[:50]

    return {
        "statusCode": 200,
        "headers": {"Access-Control-Allow-Origin": "*"},
        "body": json.dumps(items)
    }