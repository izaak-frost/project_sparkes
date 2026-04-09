# Project Sparkes

A personal data engineering and full-stack application evolving into a coach–athlete performance platform.


## Overview

Project Sparkes is a modular fitness data platform designed to ingest, process, and expose personal health and performance data from multiple sources.

It began as a personal data engineering project focused on Garmin Connect, and is now evolving into a full-stack application with web and mobile interfaces.

The system currently:

* Extracts and processes fitness data from Garmin Connect
* Structures and stores datasets locally
* Exports enriched data to Google Sheets
* Exposes data via an API for frontend use

**Next phase:**

* Integration with Strava (official API) for activity/workout data
* Expansion into a multi-user coach–athlete platform


## Motivation

Most fitness platforms (e.g. Garmin, Strava) operate in silos:

* limited custom analytics
* poor cross-platform integration
* restricted data ownership

Project Sparkes aims to:

* unify fitness data across platforms
* enable deeper, custom analysis
* improve communication between athlete and coach
* provide a foundation for a scalable performance tracking product


## Vision

Project Sparkes is evolving into a **coach–athlete performance system**, where:

* Athletes own and control their data
* Coaches can view shared metrics across multiple athletes
* Insights are derived from combined data sources (Garmin, Strava, nutrition, etc.)

This project serves both as:

* a **portfolio-grade data engineering + full-stack system**
* and the early foundation of a **potential startup product**


## Architecture

### Current Data Flow

1. **Authentication**

   * Secure Garmin Connect login (token-based with credential fallback) 

2. **Data Extraction Pipelines**

   * Sleep data (granular metrics + scores) 
   * Step data (range batching + missing date handling) 
   * Weight data (normalised to kg) 

3. **Processing & Transformation**

   * Incremental updates (avoiding duplicate fetches)
   * Time conversions and derived metrics
   * Data cleaning and normalisation

4. **Storage**

   * JSON datasets:

     * `sleep_data.json`
     * `daily_steps.json`
     * `weights.json`

5. **Export Layer**

   * Google Sheets integration:

     * weekly aggregation
     * derived metrics (sleep duration, averages)
     * structured reporting for coaching workflows 

6. **API Layer**

   * FastAPI service exposing:

     * `/weights`
     * `/steps` 

7. **Orchestration**

   * End-to-end execution via `main.py` 


## Features (Current)

* ✅ Garmin Connect integration (authentication + token reuse)
* ✅ Automated pipelines:

  * Sleep tracking (detailed breakdown + scoring)
  * Step tracking (gap-aware + refresh logic)
  * Weight tracking (normalised values)
* ✅ Incremental data ingestion (efficient updates)
* ✅ JSON-based storage
* ✅ Google Sheets export with weekly summaries
* ✅ FastAPI backend for data access


## In Progress

* React frontend (dashboard + visualisations)
* API expansion (sleep endpoints, aggregated metrics)
* Data modelling improvements


## Next Steps

### 🔗 Strava Integration (Upcoming)

* Integrate **Strava API (official)** for:

  * activities (runs, rides, workouts)
  * performance metrics (pace, distance, elevation)
* Merge Garmin + Strava datasets into unified models
* Enable richer training analysis


### 📱 App Development (React Native)

The project is being extended into a **cross-platform application**:

* **Web dashboard** (React)
* **Mobile app** (React Native)

Planned capabilities:

* Daily performance overview
* Trend visualisations
* Athlete check-ins
* Coach feedback loops

Goal:

> A unified code-driven platform accessible anywhere, with a consistent user experience.


### 👥 Multi-User Coach Model (Future)

* Support **multiple athletes per coach**
* Data access model:

  * athletes own their data
  * coaches see only what is shared
* Enable:

  * performance comparisons (within a cohort)
  * coaching insights at scale


### 📊 Data Expansion

Planned data sources:

* Garmin (existing)
* Strava (next)
* Nutrition tracking
* Training plans / sessions
* Recovery metrics (HRV, fatigue, etc.)


## Tech Stack

### Backend

* Python
* FastAPI
* Garmin Connect API (unofficial)
* python-dotenv
* gspread (Google Sheets integration)

### Frontend

* React (Vite)
* React Native (planned)

### Data

* JSON (current)
* Planned:

  * SQL (PostgreSQL / SQLite)
  * analytics-ready schema


## Project Structure

```id="csp9b0"
project_sparkes/
├── project_data/
│   └── garmin_sync/
│       ├── extract_methods/
│       ├── export_methods/
│       ├── sub_modules/
│       └── main.py
├── project_app/          # React frontend (in progress)
├── api.py                # FastAPI service
├── data/                 # Generated datasets
```


## Getting Started

### Backend

```bash
cd project_data
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

### API

```bash
uvicorn api:app --reload
```

### Frontend

```bash
cd project_app
npm install
npm run dev
```

---

## Environment Variables

```id="n0l2yf"
GARMIN_EMAIL=your_email
GARMIN_PASSWORD=your_password
GARMIN_TOKENS=garmin_tokens.json

START_DATE=YYYY-MM-DD

GOOGLE_SERVICE_ACCOUNT_FILE=path_to_credentials.json
GOOGLE_SHEET_ID=your_sheet_id
```


## Why This Project Matters

Project Sparkes demonstrates:

* Data engineering (pipelines, incremental ingestion)
* API design (FastAPI service layer)
* Full-stack development (React + mobile direction)
* Real-world problem solving (coach–athlete workflows)

It is both:

* a **production-style personal system**
* and an evolving **product with real user value**
