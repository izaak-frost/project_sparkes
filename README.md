# Project Sparkes

A personal data engineering and full-stack project focused on ingesting, processing, and visualising fitness data.

## Overview

Project Sparkes is designed to automate the collection and transformation of personal fitness data from Garmin Connect, enabling structured insights to be shared with a personal trainer.

The project combines:
- A Python-based backend for data ingestion, processing, and storage
- A React frontend for visualisation and interaction
- A modular architecture to support future expansion (APIs, analytics, dashboards)

## Motivation

Garmin Connect provides useful visualisations, but lacks flexibility for custom analysis, long-term tracking, and integration with external coaching workflows.

Project Sparkes aims to:
- Centralise personal fitness data in a structured format
- Enable custom analytics and trend tracking
- Provide a foundation for sharing insights with coaches or other systems

## Architecture

1. Data is extracted from Garmin Connect via authenticated requests  
2. Raw data is processed into structured datasets (weight, steps)  
3. Processed data is stored in JSON format  
4. (Planned) API layer exposes data to the frontend  
5. React frontend visualises key metrics  

Future enhancements include:
- Migration to SQL-based storage
- Advanced analytics pipelines
- Dashboarding and reporting

## Features (Current)

- Garmin Connect integration (authentication + data extraction)
- Data pipelines for:
  - Weight tracking
  - Step tracking
- JSON-based storage for processed datasets
- Environment-based configuration using `.env`

## In Progress

- React frontend (initial setup)
- API layer to serve fitness data to the frontend
- Data modelling and transformation improvements

## Tech Stack

**Backend**
- Python
- Garmin Connect API
- python-dotenv

**Frontend**
- React (Vite)

**Data**
- JSON (initial)
- Planned: SQL / structured storage

## Project Structure
project_sparkes/
├── project_data/ # Python backend (data ingestion & processing)
│ └── garmin_sync/ # Core Garmin integration logic
├── project_app/ # React frontend


## Getting Started

### Backend

```bash
cd project_data
python -m venv venv
source venv/bin/activate   # or .\venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py

### Frontend

cd project_app
npm install
npm run dev

