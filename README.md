
# Pakka (पक्का) — Verified News, Straight from the Source
http://pakka-frontend-kaiv.s3-website-us-east-1.amazonaws.com/look.html

> An AWS-native RAG news feed that pulls exclusively from official Government of India sources — no editorializing, no ambiguity, every summary traceable to its original page.

[![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20DynamoDB%20%7C%20API%20Gateway-orange)](https://aws.amazon.com/)
[![Python](https://img.shields.io/badge/Python-3.x-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

---

## Table of Contents

- [What is Pakka?](#what-is-pakka)
- [Why "Pakka"?](#why-pakka)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [How It Works](#how-it-works)
- [Frontend](#frontend)
- [Search](#search)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Roles & Deliverables](#roles--deliverables)
- [Lessons Learned](#lessons-learned)
- [Feedback on AWS Services](#feedback-on-aws-services)
- [What Worked Well](#what-worked-well)
- [Roadmap](#roadmap)
- [License](#license)

---

## What is Pakka?

Pakka is a retrieval-augmented news feed that crawls a fixed list of **official Government of India websites** — PIB, ISRO, the Ministry of Defence, the Supreme Court, and others — extracts genuinely new press releases and notifications (not just homepage boilerplate), summarizes them in a strictly **neutral, factual tone**, and presents them as a dated, searchable feed.

Every summary carries a **direct citation link** back to its original source page. The feed updates automatically once a day, and users can search the full archive, with a live-search fallback (scoped to the same official domains) for topics not yet in the archive.

The idea came from wanting a place to get government news without needing to guess whether a headline had been editorialized or navigate 20+ websites for information.

## Why "Pakka"?

"Pakka" (पक्का) is Hindi and telugu for **"solid," and "certain"** It's the word you use when something is confirmed, not just claimed. That is exactly the promise of the product: if it's on Pakka, it traces back to an official source.

---

## Architecture

```
                    ┌──────────────────┐
                    │   EventBridge     │
                    │  (24hr schedule)  │
                    └────────┬──────────┘
                             │ triggers
                             ▼
┌────────────────────────────────────────────┐
│              Ingest Lambda                   │
│  1. Crawl 24 official gov domains            │
│  2. Extract real article/press-release pages │
│     (BeautifulSoup) — not just homepages     │
│  3. Content-hash check (skip unchanged pages)│
│  4. Summarize (neutral tone) via Groq         │
│  5. Write to DynamoDB                         │
└────────────────────┬─────────────────────────┘
                      │
                      ▼
              ┌───────────────┐
              │   DynamoDB     │
              │ (source URL +  │
              │  timestamp key,│
              │  content hash) │
              └───────┬────────┘
                      │
                      ▼
┌────────────────────────────────────────────┐
│              Query Lambda                    │
│  - Serve latest feed                          │
│  - Search archive                             │
│  - Fallback: live search (24 official domains)│
└────────────────────┬─────────────────────────┘
                      │
                      ▼
              ┌───────────────┐
              │  API Gateway   │
              │  (HTTP API)    │
              └───────┬────────┘
                      │
                      ▼
              ┌───────────────┐
              │  S3 Static     │
              │  Frontend      │
              └───────────────┘
```

---

## Tech Stack

### AWS Services

| Service | Role |
|---|---|
| **AWS Lambda** | Two functions — a scheduled ingest function (crawl → extract → summarize → store) and a query function (serve feed, handle search) |
| **Amazon DynamoDB** | Stores articles keyed by source URL and fetch timestamp, with a content-hash field to detect real updates and skip reprocessing |
| **Amazon API Gateway** (HTTP API) | Exposes the query Lambda as a public REST endpoint for the frontend |
| **Amazon EventBridge** | Triggers the ingest Lambda on a 24-hour schedule |
| **AWS IAM** | Dedicated execution role scoping Lambda's permissions to DynamoDB, CloudWatch Logs, and related resources |
| **Amazon S3** | Hosts the static frontend as a public website |
| **Amazon Bedrock** | Originally architected as the summarization layer (Claude/Titan via `invoke_model`). New-account model-invocation restrictions forced a swap for this submission — see [Feedback](#feedback-on-aws-services) — but the integration code and prompt design remain Bedrock-compatible for future migration |

### External / Open-Source Tools

| Tool | Role |
|---|---|
| **BeautifulSoup4** (Python) | HTML parsing and content extraction inside the ingest Lambda |
| **Groq** | Hosted inference for an open-weight summarization model, used as a substitute once Bedrock access was blocked |
| **Google Programmable Search Engine** | Scoped live-search fallback for queries not yet in the archive |

---

## How It Works

1. **Crawl** — Every 24 hours, EventBridge triggers the ingest Lambda, which walks 24 official government domains.
2. **Extract** — BeautifulSoup pulls out genuine press-release/notification pages (not homepage nav or boilerplate).
3. **Deduplicate** — Each page is content-hashed; if the hash matches what's already stored, it's skipped — no wasted summarization calls.
4. **Summarize** — New/changed pages are passed to a summarization model (currently Groq-hosted, see below) with a prompt enforcing a strictly neutral, factual tone.
5. **Store** — Articles are written to DynamoDB, keyed by source URL and fetch timestamp.
6. **Serve** — The query Lambda, behind API Gateway, serves the latest feed and handles search requests from the frontend.

---

## Frontend

A single static page hosted on S3, styled to feel like an Indian daily gazette:

- Serif headlines
- A saffron-and-maroon palette
- A subtle rotating chakra motif tied to scroll position
- Outlet badges per article and a "View source" link on every card

No build tooling — deployment is `aws s3 cp` plus a bucket policy change.

## Search

- Searches run against the **archive first** (DynamoDB).
- For topics not yet in the archive, Pakka falls back to a **live web search**, scoped only to the same 24 official government domains via Google Programmable Search Engine.
- Filter chips let users narrow by source/outlet.

---

## Getting Started

> These are indicative steps based on the AWS services above — adjust resource names/regions to your own account.

### Prerequisites

- An AWS account with CLI configured (`aws configure`)
- Python 3.x
- A Groq API key (or swap in Bedrock once your account has model access)
- A Google Programmable Search Engine ID + API key

### Deploy the backend

```bash
# Package and deploy the ingest Lambda
zip -r ingest.zip ingest_lambda/
aws lambda create-function \
  --function-name pakka-ingest \
  --runtime python3.x \
  --role <ingest-execution-role-arn> \
  --handler ingest.handler \
  --zip-file fileb://ingest.zip

# Package and deploy the query Lambda
zip -r query.zip query_lambda/
aws lambda create-function \
  --function-name pakka-query \
  --runtime python3.x \
  --role <query-execution-role-arn> \
  --handler query.handler \
  --zip-file fileb://query.zip
```

### Wire up EventBridge (daily crawl trigger)

```bash
aws events put-rule --name pakka-daily-crawl --schedule-expression "rate(24 hours)"
aws events put-targets --rule pakka-daily-crawl --targets "Id"="1","Arn"="<ingest-lambda-arn>"
aws lambda add-permission \
  --function-name pakka-ingest \
  --statement-id eventbridge-invoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn <eventbridge-rule-arn>
```

### Expose the query Lambda via API Gateway

```bash
aws apigatewayv2 create-api \
  --name pakka-api \
  --protocol-type HTTP \
  --target <query-lambda-arn>
```

### Deploy the frontend

```bash
aws s3 mb s3://pakka-frontend
aws s3 website s3://pakka-frontend --index-document index.html
aws s3 cp ./frontend/ s3://pakka-frontend/ --recursive
```

Update your S3 bucket policy to allow public read access to the site.

---

## Project Structure

```
pakka/
├── ingest_lambda/
│   ├── handler.py          # Crawl → extract → hash-check → summarize → store
│   └── requirements.txt
├── query_lambda/
│   ├── handler.py          # Serve feed, handle search, live-search fallback
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css           # Gazette-style theming, chakra scroll motif
│   └── app.js               # Feed rendering, filter chips, search UX
└── README.md
```

---

## Deliverables

**Backend & Infrastructure**
- Designed the DynamoDB schema (partition/sort key strategy for time-series article data)
- Built and deployed both Lambda functions (ingest and query)
- Configured IAM roles, EventBridge scheduling, and API Gateway routing
- Implemented deep-link crawling logic (homepage → real article pages) and content-hash change detection
- Diagnosed and resolved the Bedrock account restriction; redesigned the summarization layer around Groq

**Frontend & Product**
- Designed the visual identity (color palette, typography, chakra motif)
- Built the static frontend (feed rendering, filter chips, search UX)
- Integrated the live-search fallback and Google CSE

---

## Lessons Learned

The biggest lesson was building around real-world constraints instead of assuming the ideal path. When Bedrock access was blocked mid-project, redesigning the summarization layer without touching the rest of the architecture reinforced the value of decoupling components from the start — the ingest pipeline never had to know or care which model was doing the summarizing.

Beyond that, this project was a first hands-on pass at:
- **DynamoDB key design** for time-series data (source URL + fetch timestamp)
- **IAM roles and trust policies**, configured from scratch for the first time

---

## License

MIT — adjust as appropriate for your submission.
