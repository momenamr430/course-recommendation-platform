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

app = FastAPI()
templates = Jinja2Templates(directory="templates")

API_KEY = "1f1175febe989cbf4a3b8c3fd0460b8be8e07c3e844227b2dcb441b93c43c3d3"


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/search")
def search_courses(query: str):
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

    # =========================================================================
    # --- NEW: ENTERPRISE MATH ENGINE & RECOMMENDATION ALGORITHMS ---
    # =========================================================================

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
        # Highest rating for the lowest price. Score = Rating / (Price + 1) to avoid div zero
        df['roi_score'] = df['math_rating'] / (df['math_price'] + 1)
        best_value_idx = df['roi_score'].idxmax()
        df.at[best_value_idx, 'is_best_value'] = True

        # --- Algorithm 2: The 3D Centroid Pick ---
        # Find mathematical center of normalized highest ratings and highest enrollments
        max_rating = df['math_rating'].max()
        max_enrollment = df['math_enrollment'].max()

        distances = []
        for _, row in df.iterrows():
            # Euclidean distance to the "perfect" ideal point (max rating, max enrollment)
            dist = math.sqrt(((max_rating - row['math_rating']) ** 2) + (
                        (math.log10(max_enrollment + 1) - math.log10(row['math_enrollment'] + 1)) ** 2))
            distances.append(dist)

        df['centroid_dist'] = distances
        # We want the shortest distance to the ideal centroid point (excluding the one already picked for Best Value if possible)
        available_for_centroid = df[~df['is_best_value']]
        if not available_for_centroid.empty:
            centroid_idx = available_for_centroid['centroid_dist'].idxmin()
            df.at[centroid_idx, 'is_centroid'] = True
        else:
            df.at[df['centroid_dist'].idxmin(), 'is_centroid'] = True

        # --- Algorithm 3: Top Authority Instructor (Network Logic) ---
        # Build a temporary graph to calculate Centrality
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
                # Find the highest rated course by this instructor
                inst_courses = df[df['instructor'].str.contains(top_instructor, case=False, na=False)]
                available_for_inst = inst_courses[~inst_courses['is_best_value'] & ~inst_courses['is_centroid']]

                if not available_for_inst.empty:
                    top_inst_idx = available_for_inst['math_rating'].idxmax()
                    df.at[top_inst_idx, 'is_top_instructor'] = True
                elif not inst_courses.empty:
                    top_inst_idx = inst_courses['math_rating'].idxmax()
                    df.at[top_inst_idx, 'is_top_instructor'] = True

    # Drop the temporary math columns before sending to frontend
    # Drop the temporary math columns before sending to frontend
    cols_to_drop = ['math_enrollment', 'roi_score', 'centroid_dist']

    # =========================================================================
    # --- ORIGINAL GRAPHING LOGIC REMAINS EXACTLY THE SAME ---
    # =========================================================================

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

    nx.draw_networkx_nodes(g, pos, nodelist=instructor_nodes, node_color='lightblue', node_size=1500,
                           edgecolors='white')
    nx.draw_networkx_nodes(g, pos, nodelist=course_nodes, node_color='lightgreen', node_size=900, edgecolors='white')
    nx.draw_networkx_edges(g, pos, alpha=0.3, width=1.5, edge_color='#888888')
    nx.draw_networkx_labels(g, pos, labels=wrapped_labels, font_size=8, font_weight="bold")

    plt.axis('off')
    plt.tight_layout()

    buf_net = io.BytesIO()
    plt.savefig(buf_net, format="png", bbox_inches='tight', dpi=150)
    net_img = base64.b64encode(buf_net.getvalue()).decode('utf-8')
    plt.close()

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

    # --- 3D Graph (Rating vs Platform vs Enrollment) ---
    x_vals, y_vals, z_vals, labels, platforms = [], [], [], [], []
    platform_y_map = {"Pluralsight": 0, "Coursera": 1, "YouTube": 2}

    for _, row in df.iterrows():
        r_str = str(row.get('rating', '0')).lower().replace(" views", "").replace(",", "").strip()
        e_str = str(row.get('enrollment', row.get('rating', '0'))).lower().replace(" views", "").replace(",",
                                                                                                         "").strip()
        plat = str(row.get('platform', ''))

        r_num = 0
        if "m" in r_str:
            r_num = float(r_str.replace("m", "")) * 1e6 / 500000 * 4
        elif "k" in r_str:
            r_num = float(r_str.replace("k", "")) * 1000 / 500000 * 4
        elif re.match(r'^\d+\.?\d*$', r_str):
            r_num = float(r_str)
        r_num = min(5.0, max(1.0, r_num if r_num <= 5 else 1 + r_num / 500000 * 4))

        e_num = 1000
        if "m" in e_str:
            e_num = float(e_str.replace("m", "")) * 1000000
        elif "k" in e_str:
            e_num = float(e_str.replace("k", "")) * 1000
        elif re.match(r'^\d+\.?\d*$', e_str):
            e_num = float(e_str)
        e_num = max(1, e_num if e_num > 10 else e_num * 10000)

        if r_num > 0:
            x_vals.append(r_num)
            y_vals.append(platform_y_map.get(plat, 1))
            z_vals.append(np.log10(e_num))
            labels.append(str(row.get('title', ''))[:20] + "..")
            platforms.append(plat)

    img_3d = ""
    if len(x_vals) > 0:
        color_map = {"Pluralsight": "orange", "Coursera": "royalblue", "YouTube": "tomato"}
        colors = [color_map.get(p, "gray") for p in platforms]

        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection='3d')

        ax.scatter(x_vals, y_vals, z_vals, c=colors, s=120, edgecolors='black', linewidths=0.5, alpha=0.85,
                   depthshade=True)

        for xi, yi, zi, label in zip(x_vals, y_vals, z_vals, labels):
            ax.text(xi, yi, zi, f"  {label}", fontsize=7, alpha=0.8)

        ax.set_xlabel("Rating (0–5)", fontsize=11, labelpad=10)
        ax.set_xlim(1, 5)
        ax.set_yticks([0, 1, 2])
        ax.set_yticklabels(["Pluralsight", "Coursera", "YouTube"])
        ax.set_ylabel("Platform", fontsize=11, labelpad=10)
        ax.set_zlabel("Enrollment (Log10 Scale)", fontsize=11, labelpad=10)

        legend_handles = [
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='orange', markersize=10, label='Pluralsight'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='royalblue', markersize=10, label='Coursera'),
            plt.Line2D([0], [0], marker='o', color='w', markerfacecolor='tomato', markersize=10, label='YouTube'),
        ]
        ax.legend(handles=legend_handles, loc='upper left', fontsize=10)
        ax.view_init(elev=60, azim=135)
        plt.tight_layout()

        buf_3d = io.BytesIO()
        plt.savefig(buf_3d, format="png", bbox_inches='tight', dpi=120)
        img_3d = base64.b64encode(buf_3d.getvalue()).decode('utf-8')
        plt.close()

        return {
            "status": "success",
            "courses": df.to_dict(orient="records"),
            "network_image": net_img,
            "heatmap_image": heat_img,
            "img_3d": img_3d
        }

    return {"status": "success", "courses": df.to_dict(orient="records"), "network_image": net_img,
            "heatmap_image": heat_img}