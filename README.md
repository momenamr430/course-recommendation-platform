# Course Analytics & Recommendation Platform

An AI-powered course analytics and recommendation platform that searches across multiple learning platforms, analyzes course data, generates intelligent recommendations, and visualizes insights using graphs and mathematical recommendation algorithms.

---

# Features

## Multi-Platform Course Scraping
The platform collects courses from:
- Coursera
- YouTube
- Pluralsight

Using:
- Selenium
- BeautifulSoup
- XML Sitemaps
- SerpAPI

---

# AI Features

## AI Learning Roadmaps
Generate structured learning paths for any topic using Llama-3.

## AI Course Insights
Summarizes what students can learn from each course.

## AI Course Duel
Compares two courses side-by-side using AI-generated analysis.

## AI Tutor Assistant
Interactive tutor chat system for asking questions about selected courses.

## AI Mock Interview Simulator
Generates interview questions and evaluates answers with AI scoring and feedback.

## Curriculum Stack Auditor
Analyzes selected course combinations and checks:
- Skill overlap
- Missing concepts
- Career relevance

## Skill-Gap Radar
AI-powered radar chart evaluation for:
- Theory
- Hands-On Practice
- Interview Preparation
- Tool Mastery
- Portfolio Building

---

# Recommendation & Analytics System

The platform includes advanced recommendation algorithms such as:

## ROI Recommendation
Ranks courses based on rating-to-price value.

## Euclidean Centroid Recommendation
Uses mathematical centroid calculations to identify the most balanced course.

## Instructor Authority Analysis
Uses graph centrality analysis with NetworkX to identify top instructors.

---

# Visualizations

The system generates:
- Interactive Network Graphs
- ROI Heatmaps
- Radar Charts
- Recommendation Highlights

Libraries used:
- NetworkX
- Matplotlib
- Chart.js
- Vis.js

---

# Authentication System

Includes:
- User Signup/Login
- JWT Authentication
- Password Hashing with bcrypt
- Persistent User Watchlists

---

# Technologies Used

## Backend
- Python
- FastAPI
- SQLAlchemy
- JWT Authentication

## Web Scraping
- Selenium
- BeautifulSoup
- Requests
- SerpAPI

## Data Analysis & Visualization
- Pandas
- NumPy
- NetworkX
- Matplotlib

## AI Integration
- OpenRouter APIs
- Llama-3

## Frontend
- HTML
- Tailwind CSS
- JavaScript
- Chart.js
- Vis.js

---

# Project Structure

```bash
.
├── templates/
│   └── index.html
├── data.py
├── requirements.txt
├── README.md
└── LICENSE
