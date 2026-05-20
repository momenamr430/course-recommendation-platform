import io
import base64
import json
import re
import time
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
import requests
from bs4 import BeautifulSoup
from serpapi.google_search import GoogleSearch
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import arabic_reshaper
from bidi.algorithm import get_display
import textwrap
from pydantic import BaseModel
from typing import List
from openai import OpenAI
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
import bcrypt
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime
import os

plt.style.use('dark_background')
app = FastAPI()
templates = Jinja2Templates(directory="templates")
# =========================================================================
# --- NEW: DATABASE & AUTHENTICATION SETUP ---
# =========================================================================
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 1 Week

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if SQLALCHEMY_DATABASE_URL:
    if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
else:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./course_studio.db"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# DB Models
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String)
    platform = Column(String)
    price = Column(String)
    rating = Column(String)
    link = Column(String)
    instructor = Column(String)
class SearchCache(Base):
    __tablename__ = "search_cache"
    query = Column(String, primary_key=True, index=True)
    response_json = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# Auth Helpers
def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.username == username).first()
    if user is None: raise HTTPException(status_code=401, detail="User not found")
    return user

# Pydantic Schemas
class UserCreate(BaseModel):
    username: str
    password: str

class WatchlistCreate(BaseModel):
    title: str
    platform: str
    price: str
    rating: str
    link: str
    instructor: str
class InterviewStartRequest(BaseModel):
    course_title: str

class AnswerItem(BaseModel):
    question: str
    answer: str

class InterviewGradeRequest(BaseModel):
    course_title: str
    answers: List[AnswerItem]
API_KEY = os.getenv("SERPAPI_KEY")

# --- NEW: AI Setup ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")

)
OPENROUTER_API_KEY_2 = os.getenv("OPENROUTER_API_KEY_2")
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
# =========================================================================
# --- NEW: AUTH & WATCHLIST ENDPOINTS ---
# =========================================================================
@app.post("/api/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    return {"message": "User created successfully"}


@app.post("/api/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": user.username},
                                       expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer", "username": user.username}


@app.post("/api/watchlist")
def add_to_watchlist(item: WatchlistCreate, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    # Check if already exists
    exists = db.query(WatchlistItem).filter(WatchlistItem.user_id == current_user.id,
                                            WatchlistItem.link == item.link).first()
    if exists: return {"status": "success", "message": "Already in watchlist"}

    new_item = WatchlistItem(**item.dict(), user_id=current_user.id)
    db.add(new_item)
    db.commit()
    return {"status": "success"}


@app.get("/api/watchlist")
def get_watchlist(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == current_user.id).all()
    return {"status": "success", "data": items}


@app.delete("/api/watchlist/{item_id}")
def remove_from_watchlist(item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id, WatchlistItem.user_id == current_user.id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "success"}


@app.post("/api/interview/start")
def start_interview(req: InterviewStartRequest, current_user: User = Depends(get_current_user)):
    try:
        prompt = f"""
        You are an experienced technical recruiter. Generate exactly 3 distinct, open-ended interview questions evaluating a student's retention of topics covered in a course titled: '{req.course_title}'.

        Return ONLY a valid JSON array of strings containing the questions, with no markdown formatting, code block backticks, or introductions. Format exactly like this:
        ["Question 1?", "Question 2?", "Question 3?"]
        """
        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        raw_text = response.choices[0].message.content.strip()

        # Clean markdown code blocks
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()

        # Isolate the array brackets to strip conversational noise or introductory text
        match = re.search(r'\[\s*".*"\s*\]', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
        else:
            fallback_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if fallback_match:
                raw_text = fallback_match.group(0)

        return {"status": "success", "questions": json.loads(raw_text)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/interview/grade")
def grade_interview(req: InterviewGradeRequest, current_user: User = Depends(get_current_user)):
    try:
        qa_block = ""
        for i, q in enumerate(req.answers):
            qa_block += f"\nQ{i + 1}: {q.question}\nAnswer: {q.answer}\n"

        prompt = f"""
        Evaluate the candidate's technical interview answers for the course '{req.course_title}'.

        Answers to Grade:
        {qa_block}

        Analyze their accuracy and score them out of 100.
        Generate a constructive, professional review in clean Markdown detailing their strengths and gaps.

        Return ONLY a valid JSON object. Do not include markdown backticks or any explanations outside the JSON. Format exactly like this:
        {{
            "score": 85,
            "feedback": "### 🌟 Strengths\\n[Details]\\n\\n### 🔍 Gaps & Explanations\\n[Details]"
        }}
        """
        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        raw_text = response.choices[0].message.content.strip()

        # Strip code blocks
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()

        # Isolate the JSON object (everything between first { and last })
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)

        return json.loads(raw_text)
    except Exception as e:
        # Return the actual error details to help with diagnosis
        return {"status": "error", "message": str(e)}
@app.get("/api/roadmap")
def get_roadmap(query: str):
    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": f"Create a concise, step-by-step roadmap to learn {query}. Use bullet points."}]
        )
        return {"status": "success", "roadmap": response.choices[0].message.content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/insight")
def get_insight(title: str, platform: str):
    try:
        prompt = f"Extract what a student will learn from a course titled '{title}' on {platform}. Return 3 short bullet points only."
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY_2}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": "openai/gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        result = response.json()
        return {"status": "success", "insight": result["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"status": "error", "message": "Could not generate insight."}


@app.get("/api/compare")
def compare_courses(t1: str, r1: str, p1: str, l1: str, t2: str, r2: str, p2: str, l2: str):
    try:
        def get_text(url):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                resp = requests.get(url, headers=headers, timeout=6)
                return BeautifulSoup(resp.text, "html.parser").get_text()[:2000]  # Grab a bit more text
            except Exception:
                return "Content blocked by site."

        # Force the exact table structure you want
        prompt = f"""
        You are an expert course advisor. Compare the following two courses based on their syllabus snippets.

        Course 1: {t1}
        Syllabus Snippet: {get_text(l1)}

        Course 2: {t2}
        Syllabus Snippet: {get_text(l2)}

        YOU MUST STRICTLY FOLLOW THIS EXACT MARKDOWN TABLE FORMAT. Fill in the brackets with detailed analysis:

        | Feature | {t1} | {t2} |
        | :--- | :--- | :--- |
        | **Topic Coverage** | [Deep analysis of topics covered] | [Deep analysis of topics covered] |
        | **Skills Gained** | [List of specific skills] | [List of specific skills] |
        | **Level of Expertise** | [Beginner/Intermediate/Advanced] | [Beginner/Intermediate/Advanced] |
        | **Hands-on Experience** | [Labs/Projects/Exercises mentioned] | [Labs/Projects/Exercises mentioned] |
        | **Pros** | [Main strengths] | [Main strengths] |
        | **Cons** | [Main weaknesses] | [Main weaknesses] |
        | **Cost** | {p1} | {p2} |
        | **Rating** | {r1} | {r2} |

        RULES:
        1. Return ONLY the Markdown table.
        2. Do not write any text before or after the table.
        3. Make the comparisons highly detailed.
        """

        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"status": "success", "comparison": response.choices[0].message.content.strip()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/relevance")
def get_relevance(query: str, title: str):
    try:
        prompt = f"""
        Evaluate the course '{title}' for a student whose ultimate career goal is: '{query}'.
        Score this course from 1 to 10 on the following 5 axes. 

        Return ONLY a valid JSON object. Do not include markdown formatting or backticks. Format exactly like this:
        {{
            "Theory": 8,
            "Hands_On": 7,
            "Interview_Prep": 5,
            "Tool_Mastery": 9,
            "Portfolio_Building": 6,
            "summary": "One concise sentence explaining why it fits."
        }}
        """
        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )

        # Clean the output in case the LLM adds markdown backticks
        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:-3].strip()
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:-3].strip()

        return json.loads(raw_text)
    except Exception as e:
        return {"error": str(e), "summary": "Failed to analyze relevance."}
# --- NEW: Stack Auditor Schema ---
class StackRequest(BaseModel):
    courses: List[str]
    role: str


@app.post("/api/audit")
def audit_stack(req: StackRequest):
    try:
        courses_str = "\n".join([f"- {c}" for c in req.courses])
        prompt = f"""
        You are an expert Enterprise Learning & Development Architect.
        A student wants to achieve the role of: '{req.role}'. 
        They have selected the following courses for their curriculum stack:
        {courses_str}

        Please provide a concise, high-level audit of this curriculum stack. Format STRICTLY in Markdown. Use these headings:
        ### 🌟 Stack Strengths
        [What does this combination cover well?]

        ### ⚠️ Redundancies
        [Are there overlapping topics between these courses?]

        ### 🔍 Critical Gaps
        [What essential skills for a {req.role} are missing from this stack?]

        ### ⚖️ Final Verdict
        [1-2 sentences summarizing if this is a good learning path]
        """

        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"status": "success", "audit": response.choices[0].message.content}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# --- NEW: AI Tutor Chat Endpoint ---
@app.get("/api/tutor")
def tutor_chat(course_title: str, user_question: str):
    try:
        # We inject the course title as the "System Context"
        prompt = f"""
        You are an expert AI Tutor. The student is asking a question about a course titled '{course_title}'.

        Question: {user_question}

        If you don't know the answer based on general knowledge of this course title, be honest. 
        Keep your answer helpful, concise, and professional. 
        Return the answer in plain text.
        """

        response = client.chat.completions.create(
            model="meta-llama/llama-3-8b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        return {"status": "success", "reply": response.choices[0].message.content}
    except Exception as e:
        return {"status": "error", "message": str(e)}
# =========================================================================
# --- YOUR EXACT SCRAPER (UNTOUCHED) ---
# =========================================================================
@app.get("/api/search")
def search_courses(query: str, db: Session = Depends(get_db)):
    normalized_query = query.strip().lower()

    # DB Cache Lookup
    cached_entry = db.query(SearchCache).filter(SearchCache.query == normalized_query).first()
    if cached_entry:
        if datetime.utcnow() - cached_entry.timestamp < timedelta(hours=24):
            payload = json.loads(cached_entry.response_json)
            payload["cache_status"] = "hit"
            return payload
        else:
            db.delete(cached_entry)
            db.commit()
    courses = []
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36")

    path = ChromeDriverManager().install()
    service = Service(path)
    driver = webdriver.Chrome(service=service, options=options)

    # --- 1. Pluralsight (SerpAPI + BeautifulSoup Deep Scrape) ---
    search = GoogleSearch({
        "engine": "google", "api_key": API_KEY, "q": f"site:pluralsight.com/courses {query}",
        "hl": "en", "gl": "us", "num": 10
    })
    organic = search.get_dict().get("organic_results", [])
    pluralsight_raw = []
    for item in organic:
        link = item.get("link", "")
        if "pluralsight.com/courses/" not in link and "pluralsight.com/library/" not in link: continue
        title = item.get("title", "N/A").replace(" | Pluralsight", "").replace(" - Pluralsight", "").strip()
        clean_link = re.sub(r'\?.*', '', link)
        pluralsight_raw.append({"title": title, "link": clean_link})

    HEADERS = {"User-Agent": "Mozilla/5.0"}
    for course in pluralsight_raw:
        rating, price, duration_months, instructor = "N/A", "N/A", 0, "N/A"
        try:
            resp = requests.get(course["link"], headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                ld_json_scripts = soup.find_all("script", type="application/ld+json")
                for script in ld_json_scripts:
                    if script.string and script.string.strip():
                        decoded = json.JSONDecoder().raw_decode(script.string.strip())
                        items = decoded[0] if isinstance(decoded[0], list) else [decoded[0]]
                        for d in items:
                            if "aggregateRating" in d and d["aggregateRating"].get("ratingValue") is not None:
                                rating = str(round(float(d["aggregateRating"].get("ratingValue")), 1))
                            if "timeRequired" in d:
                                tr = d["timeRequired"]
                                if "PT" in tr and not re.search(r'\d+M|\d+W', tr):  # hours
                                    duration_months = 1
                                elif re.search(r'(\d+)M', tr):  # months
                                    duration_months = int(re.search(r'(\d+)M', tr).group(1))
                                elif re.search(r'(\d+)W', tr):  # week
                                    duration_months = max(1, int(re.search(r'(\d+)W', tr).group(1)) // 4)
                            if "author" in d:
                                author = d["author"]
                                instructor = ", ".join([a.get("name", "N/A") for a in author]) if isinstance(author,
                                                                                                             list) else author.get(
                                    "name", "N/A")

                if rating == "N/A":
                    meta = soup.find("meta", {"name": re.compile(r'rating', re.I)})
                    if meta and meta.get("content"): rating = meta["content"]
                if rating == "N/A":
                    rating_tags = [tag for tag in soup.find_all(["span", "div"]) if
                                   re.match(r'^[1-5]\.\d$', tag.get_text(strip=True))]
                    if rating_tags: rating = rating_tags[0].get_text(strip=True)
                if instructor == "N/A":
                    author_tag = soup.find(attrs={"class": re.compile(r'author|instructor', re.I)})
                    if author_tag: instructor = author_tag.get_text(strip=True)
                if instructor != "N/A":
                    instructor = re.sub(r'Created\s*by\s*|Last\s*Updated.*', '', instructor,
                                        flags=re.IGNORECASE).strip()
                    instructor = re.sub(r'and', ', ', instructor).strip()
                if duration_months == 0:
                    dur_match = re.search(r'(\d+)\s*(?:-|to)?\s*(\d+)?\s*months?', soup.get_text().lower())
                    if dur_match: duration_months = int(dur_match.group(1))
                price = str(duration_months * 29) if duration_months > 0 else "29"

                courses.append(
                    {"title": course["title"], "link": course["link"], "platform": "Pluralsight", "rating": rating,
                     "price": price, "instructor": instructor})
        except:
            continue

    # --- 2. Coursera (XML + BeautifulSoup + Selenium Fallback) ---
    xml_resp = requests.get("https://www.coursera.org/sitemap~www~courses.xml", headers={"User-Agent": "Mozilla/5.0"})
    if xml_resp.status_code == 200:
        soup = BeautifulSoup(xml_resp.text, "xml")
        count = 0
        for url in soup.find_all("loc"):
            link = url.text
            if "/learn/" not in link or query.lower().replace(" ", "-") not in link.lower(): continue
            title = link.split("/")[-1].replace("-", " ").title()
            rating, price, duration_months, instructor = "N/A", "N/A", 0, "N/A"
            try:
                course_resp = requests.get(link, headers=HEADERS)
                if course_resp.status_code == 200:
                    course_soup = BeautifulSoup(course_resp.text, "html.parser")
                    for script in course_soup.find_all("script", type="application/ld+json"):
                        if not script.string or not script.string.strip(): continue
                        decoded, _ = json.JSONDecoder().raw_decode(script.string.strip())
                        elements = decoded if isinstance(decoded, list) else [decoded]
                        elements += [node for item in elements if "@graph" in item for node in item["@graph"]]
                        for item in elements:
                            if item.get("@type") == "Course":
                                if "aggregateRating" in item and item["aggregateRating"].get("ratingValue") is not None:
                                    rating = str(round(float(item["aggregateRating"].get("ratingValue")), 1))
                                if "timeRequired" in item:
                                    tr = item["timeRequired"]
                                    if re.search(r'(\d+)M', tr):
                                        duration_months = int(re.search(r'(\d+)M', tr).group(1))
                                    elif re.search(r'(\d+)W', tr):
                                        duration_months = max(1, int(re.search(r'(\d+)W', tr).group(1)) // 4)
                                if "author" in item:
                                    author = item["author"]
                                    instructor = ", ".join([a.get("name", "N/A") for a in author]) if isinstance(author,
                                                                                                                 list) else author.get(
                                        "name", "N/A")

                    if instructor == "N/A" or "University" in instructor or "College" in instructor:
                        instructor_tags = course_soup.select("a[href*='/instructor/'], a[data-e2e='instructorName']")
                        if instructor_tags: instructor = ", ".join(list(
                            dict.fromkeys([t.get_text(strip=True) for t in instructor_tags if t.get_text(strip=True)])))

                    if instructor == "N/A" or "University" in instructor or "College" in instructor:
                        try:
                            driver.get(link)
                            WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "a[href*='/instructor/'], a[data-e2e='instructorName']")))
                            instructor_elems = driver.find_elements(By.CSS_SELECTOR,
                                                                    "a[href*='/instructor/'], a[data-e2e='instructorName']")
                            if instructor_elems: instructor = ", ".join(
                                list(dict.fromkeys([e.text.strip() for e in instructor_elems if e.text.strip()])))
                        except:
                            pass

                    if duration_months == 0:
                        dur_match = re.search(r'(\d+)\s*(?:-|to)?\s*(\d+)?\s*months?', course_soup.get_text().lower())
                        if dur_match: duration_months = int(dur_match.group(1))
                    price = str(duration_months * 20) if duration_months > 0 else "20"

                    if rating != "N/A":
                        courses.append(
                            {"title": title, "link": link, "platform": "Coursera", "rating": rating, "price": price,
                             "instructor": instructor})
                        count += 1
                        if count >= 8: break
            except:
                continue

    # --- 3. YouTube (Selenium) ---
    youtube_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}+full+course&hl=en"
    driver.get(youtube_url)
    time.sleep(3)
    count = 0
    video_blocks = driver.find_elements(By.TAG_NAME, "ytd-video-renderer")[:15]
    for video in video_blocks:
        try:
            title_elem = video.find_element(By.ID, "video-title")
            title, href = title_elem.get_attribute("title"), title_elem.get_attribute("href")
            match = re.search(r'([\d\.,]+[KM]?)\s*views', video.text, re.IGNORECASE)
            rating = match.group(1) + " views" if match else "N/A"
            if rating == "N/A": continue
            try:
                instructor = video.find_element(By.CSS_SELECTOR, "ytd-channel-name").text.strip()
            except:
                instructor = "N/A"

            if instructor == "N/A" or instructor == "":
                try:
                    instructor = video.find_element(By.XPATH, ".//*[@id='channel-info']//*[@id='text']").text.strip()
                except:
                    instructor = "YouTube Creator"

            courses.append({"title": title, "link": href, "platform": "YouTube", "rating": rating, "price": "0",
                            "instructor": instructor})
            count += 1
            if count >= 8: break
        except:
            continue
    driver.quit()

    df = pd.DataFrame(courses).drop_duplicates(subset="title").reset_index(drop=True)

    # Initialize tagging columns
    df['is_centroid'] = False
    df['is_best_value'] = False
    df['is_top_instructor'] = False

    if not df.empty:
        # Helper lists for math
        math_ratings = []
        math_prices = []
        math_enrollments = []

        # Safely convert strings to numbers for math processing ONLY (doesn't overwrite strings for UI)
        for _, row in df.iterrows():
            r_str = str(row.get('rating', '0')).lower().replace(" views", "").replace(",", "").strip()
            p_str = str(row.get('price', '0')).lower().replace("$", "").replace("free", "0").replace(",", "").strip()

            # Extract Rating
            r_num = 0
            if "m" in r_str:
                r_num = float(r_str.replace("m", "")) * 1e6 / 500000 * 4
            elif "k" in r_str:
                r_num = float(r_str.replace("k", "")) * 1000 / 500000 * 4
            elif re.match(r'^\d+\.?\d*$', r_str):
                r_num = float(r_str)
            r_num = min(5.0, max(1.0, r_num if r_num <= 5 else 1 + r_num / 500000 * 4))
            math_ratings.append(r_num)

            # Extract Price
            p_num = 0.0
            if "subscription" in p_str:
                p_num = 29.0
            elif re.match(r'^\d+\.?\d*$', p_str.split()[0] if p_str.split() else ""):
                p_num = float(p_str.split()[0])
            math_prices.append(p_num)

            # Extract Enrollment (Using view counts or derived from rating)
            e_num = 1000
            if "m" in r_str:
                e_num = float(r_str.replace("m", "")) * 1000000
            elif "k" in r_str:
                e_num = float(r_str.replace("k", "")) * 1000
            else:
                e_num = r_num * 10000  # Estimate if no views available
            math_enrollments.append(e_num)

        df['math_rating'] = math_ratings
        df['math_price'] = math_prices
        df['math_enrollment'] = math_enrollments

        # --- Algorithm 1: The Best Value (ROI Heatmap Logic) ---
        df['roi_score'] = df['math_rating'] / (df['math_price'] + 1)
        best_value_idx = df['roi_score'].idxmax()
        df.at[best_value_idx, 'is_best_value'] = True

        # --- Algorithm 2: The 3D Centroid Pick ---
        max_rating = df['math_rating'].max()
        max_enrollment = df['math_enrollment'].max()

        distances = []
        for _, row in df.iterrows():
            dist = math.sqrt(((max_rating - row['math_rating']) ** 2) + (
                        (math.log10(max_enrollment + 1) - math.log10(row['math_enrollment'] + 1)) ** 2))
            distances.append(dist)

        df['centroid_dist'] = distances
        available_for_centroid = df[~df['is_best_value']]
        if not available_for_centroid.empty:
            centroid_idx = available_for_centroid['centroid_dist'].idxmin()
            df.at[centroid_idx, 'is_centroid'] = True
        else:
            df.at[df['centroid_dist'].idxmin(), 'is_centroid'] = True

        # --- Algorithm 3: Top Authority Instructor (Network Logic) ---
        temp_g = nx.Graph()
        for _, row in df.iterrows():
            title = str(row["title"]).strip()
            raw_instructors = str(row["instructor"])
            if raw_instructors != "N/A" and raw_instructors.strip():
                temp_g.add_node(title, type='course')
                for inst in [i.strip().title() for i in raw_instructors.split(",") if i.strip()]:
                    temp_g.add_node(inst, type='instructor')
                    temp_g.add_edge(inst, title)

        if len(temp_g.nodes) > 0:
            centrality = nx.degree_centrality(temp_g)
            instructors_only = {node: score for node, score in centrality.items() if
                                temp_g.nodes[node].get('type') == 'instructor'}
            if instructors_only:
                top_instructor = max(instructors_only, key=instructors_only.get)
                inst_courses = df[df['instructor'].str.contains(top_instructor, case=False, na=False)]
                available_for_inst = inst_courses[~inst_courses['is_best_value'] & ~inst_courses['is_centroid']]

                if not available_for_inst.empty:
                    top_inst_idx = available_for_inst['math_rating'].idxmax()
                    df.at[top_inst_idx, 'is_top_instructor'] = True
                elif not inst_courses.empty:
                    top_inst_idx = inst_courses['math_rating'].idxmax()
                    df.at[top_inst_idx, 'is_top_instructor'] = True

    cols_to_drop = ['math_enrollment', 'roi_score', 'centroid_dist']

    # --- 4. Network Graph ---
    g = nx.Graph()
    INSTRUCTORS = set()

    for _, row in df.iterrows():
        title = str(row["title"]).strip()
        raw_instructors = str(row["instructor"])

        if raw_instructors == "N/A" or not raw_instructors.strip():
            continue

        g.add_node(title, type='course')
        instructor_list = [i.strip().title() for i in raw_instructors.split(",") if i.strip()]

        for inst in instructor_list:
            g.add_node(inst, type='instructor')
            g.add_edge(inst, title)
            INSTRUCTORS.add(inst)

    plt.figure(figsize=(18, 12))

    try:
        pos = nx.kamada_kawai_layout(g)
    except:
        pos = nx.spring_layout(g, seed=42, k=3.5, iterations=300)

    wrapped_labels = {}
    for node in g.nodes():
        reshaped_text = arabic_reshaper.reshape(node)
        bidi_text = get_display(reshaped_text)
        wrapped_labels[node] = "\n".join(textwrap.wrap(bidi_text, width=15))

    instructor_nodes = [n for n, attr in g.nodes(data=True) if attr.get('type') == 'instructor']
    course_nodes = [n for n, attr in g.nodes(data=True) if attr.get('type') == 'course']

    # Instructors = Bright Blue, Courses (Titles) = Bright Purple
    # Instructors = Bright Blue, Courses (Titles) = Bright Purple
    nx.draw_networkx_nodes(g, pos, nodelist=instructor_nodes, node_color='#38bdf8', node_size=1500, edgecolors='white')
    nx.draw_networkx_nodes(g, pos, nodelist=course_nodes, node_color='#c084fc', node_size=900, edgecolors='white')

    # Draw edges
    nx.draw_networkx_edges(g, pos, alpha=0.3, width=1.5, edge_color='#888888')

    # Draw labels ONCE with white text
    nx.draw_networkx_labels(g, pos, labels=wrapped_labels, font_size=8, font_weight="bold", font_color="white")

    plt.axis('off')
    plt.tight_layout()

    plt.axis('off')
    plt.tight_layout()

    buf_net = io.BytesIO()
    plt.savefig(buf_net, format="png", bbox_inches='tight', dpi=150)
    net_img = base64.b64encode(buf_net.getvalue()).decode('utf-8')
    plt.close()
    nodes = [{"id": n, "label": (n[:15] + '..') if len(n) > 15 else n, "group": attr.get('type')}
             for n, attr in g.nodes(data=True)]
    edges = [{"from": u, "to": v} for u, v in g.edges()]
    # --- 5. Heatmap  ---
    X_list, Y_list = [], []
    for _, row in df.iterrows():
        r = str(row['rating']).lower().replace(" views", "").replace(",", "").strip()
        p = str(row['price']).lower().replace("$", "").replace("free", "0").replace(",", "").strip()
        if "m" in r:
            r_num = min(5.0, max(1.0, 1 + float(r.replace("m", "")) * 1e6 / 500000 * 4))
        elif "k" in r:
            r_num = min(5.0, max(1.0, 1 + float(r.replace("k", "")) * 1000 / 500000 * 4))
        elif re.match(r'^\d+\.?\d*$', r):
            r_num = float(r)
            r_num = min(5.0, max(1.0, 1 + r_num / 500000 * 4)) if r_num > 10 else r_num
        else:
            r_num = None

        if "subscription" in p:
            p_num = 29.0
        elif re.match(r'^\d+\.?\d*$', p.split()[0] if p.split() else ""):
            p_num = float(p.split()[0])
        else:
            p_num = None

        if r_num and p_num is not None:
            X_list.append(r_num)
            Y_list.append(p_num)

    X, Y = np.array(X_list), np.array(Y_list)
    if len(X) == 0:
        X, Y = np.array([4.5, 4.7, 4.2, 5.0, 4.8]), np.array([0.0, 29.0, 20.0, 0.0, 12.99])

    XX, YY = np.meshgrid(np.linspace(0, 6, 100), np.linspace(-5, Y.max() + 20, 100))
    heatmap = sum(((XX - px) / 0.6) ** 2 + ((YY - py) / 10) ** 2 <= 1 for px, py in zip(X, Y)).astype(float)

    plt.figure(figsize=(10, 6))
    plt.imshow(heatmap, extent=(0, 6, -5, Y.max() + 20), origin="lower", cmap="hot", aspect="auto")
    plt.colorbar(label="Density")
    plt.xlabel("Rating (0-5)")
    plt.ylabel("Price ($)")
    plt.tight_layout()

    buf_heat = io.BytesIO()
    plt.savefig(buf_heat, format="png", bbox_inches='tight')
    heat_img = base64.b64encode(buf_heat.getvalue()).decode('utf-8')
    plt.close()


    # Always extract nodes/edges so they are available for the final return
    nodes = [{"id": n, "label": (n[:15] + '..') if len(n) > 15 else n, "group": attr.get('type')}
             for n, attr in g.nodes(data=True)]
    edges = [{"from": u, "to": v} for u, v in g.edges()]


    # ONE SINGLE RETURN FOR EVERYTHING
    response_payload = {
        "status": "success",
        "cache_status": "miss",
        "courses": df.to_dict(orient="records"),
        "network_data": {"nodes": nodes, "edges": edges},
        "heatmap_image": heat_img
    }
    try:
        new_cache = SearchCache(query=normalized_query, response_json=json.dumps(response_payload))
        db.merge(new_cache)
        db.commit()
    except Exception as cache_err:
        print("Caching proxy failed:", str(cache_err))

    return response_payload
