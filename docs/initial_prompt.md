 **Act as a Senior Cloud Architect and Lead Product Manager.** Write a formal, production-grade Product Requirements Document (PRD) for an automated, zero-cost serverless research digest system and UI dashboard named **`paper-prism`**.
 ---
 
 
 ### 1. System Context & Business Goals
 
 
 * **Primary Objective:** Build an automated weekly research pipeline that fetches preprints from arXiv across four categories (**AI/ML**, **NLP**, **Computer Vision**, and **Gen AI**), ranks them using a two-stage hybrid pipeline (local embeddings + Ollama Cloud LLM), stores JSON metadata in Azure Cosmos DB, and serves results to a lightweight **Svelte** web application.
 * **Cost & Scaling Target:** **$0.00/month operating cost** using Azure Free Tier services (Azure Functions Consumption, Cosmos DB Serverless / Free Tier, Azure Container Apps scaled to 0, Azure Static Web Apps Free Tier) and Ollama Cloud free tier compute.
 
 
 ---
 
 
 ### 2. Technical & Architectural Specification
 
 
 #### A. Processing Engine (Azure Functions)
 
 
 * **Runtime & Trigger:** Python-based Azure Function triggered weekly via Timer Trigger (`0 0 9 * * MON`).
 * **Ingestion & 2-Stage Ranking:**
 1. **Fetch:** Pull 7-day rolling preprints from arXiv REST API across target categories: `cs.AI` / `cs.LG` (AI/ML), `cs.CL` (NLP), `cs.CV` (Computer Vision), and `cs.AI` + `cs.CL` filtered for generative models (Gen AI).
 2. **Stage 1 (Pure ML Pre-Filter):** Generate local dense vector embeddings with `sentence-transformers/all-MiniLM-L6-v2` to select the top 15 candidates per category via cosine similarity.
 3. **Stage 2 (Ollama Cloud LLM):** Invoke Ollama Cloud API (`llama3.1` or `qwen2.5`) to re-rank the top candidates and generate 2-sentence key innovation summaries for the **Top 3 papers per category**.
 
 
 * **Storage Persistence:** Output JSON payload directly into **Azure Cosmos DB** (NoSQL API).
 
 
 #### B. Data Storage (Azure Cosmos DB)
 
 
 * **Database Mode:** Serverless or Free Tier Container (`PartitionKey: /category`).
 * **Document Schema:**
 ```json
 {
   "id": "run_2026_08_10_aiml",
   "run_id": "2026-08-10T09:00:00Z",
   "category": "AIML",
   "papers": [
     {
       "rank": 1,
       "title": "...",
       "arxiv_id": "...",
       "url": "...",
       "score": 0.94,
       "summary": "..."
     }
   ]
 }
 
 ```
 
 
 
 
 #### C. Backend REST API (Azure Container Apps)
 
 
 * **Hosting:** FastAPI / Python application deployed to **Azure Container Apps** configured with **Scale-to-Zero** (minReplicas = 0) when idle.
 * **Endpoints:**
 * `GET /api/runs/latest`: Retrieves the most recent run results for all 4 categories.
 * `GET /api/runs/archive`: Retrieves the last 5 historical runs grouped by category.
 * `GET /api/health`: Healthcheck endpoint used to cold-start / wake up the container instance from zero replicas.
 
 
 
 
 #### D. Frontend Application (Svelte + Azure Static Web Apps)
 
 
 * **Framework:** Lightweight Single Page Application (SPA) built with **Svelte** hosted on **Azure Static Web Apps (Free Tier)**.
 * **Views & Features:**
 * **Latest Run Tab:** Tabbed/grid layout showing the Top 3 papers for AI/ML, NLP, Computer Vision, and Gen AI from the most recent run.
 * **Archive Tab:** Filterable view displaying historical summaries for the past 5 runs per category.
 * **API Wakeup / Health Check UI Component:** A manual "Wake Up API" status button/banner that ping `/api/health`, showing loading state during cold starts until the Container App provisions and returns `200 OK`.
 
 
 
 
 ---
 
 
 ### 3. Required PRD Sections to Generate
 
 
 Structure the document into the following formal sections:
 1. **Executive Summary & SLA/Cost Boundaries** (Cost allocations across Azure services, latency budgets for cold starts).
 2. **End-to-End System Architecture Diagram** (Include a Mermaid.js diagram illustrating Azure Function ➔ Ollama Cloud ➔ Cosmos DB ➔ Azure Container App API ➔ Svelte SPA on Static Web Apps).
 3. **Functional Specifications & Data Flow:**
 * Azure Function execution flow & arXiv query parameters per category.
 * Cosmos DB document structures & partition indexing strategy.
 * FastAPI routing and response payloads.
 * Svelte state management (handling cold-start API delays gracefully with visual spinners/status indicators).
 
 
 4. **API Interface Contracts** (OpenAPI / Swagger definitions for `/api/runs/latest`, `/api/runs/archive`, `/api/health`).
 5. **Non-Functional Requirements** (Azure Container App scale-to-zero behavior, CORS configuration, error handling for API cold starts).
 6. **Deployment & Infrastructure-as-Code (IaC)** (Bicep or Terraform specifications for deploying Azure Static Web Apps, Function Apps, Cosmos DB, and Container Apps).
 7. **Implementation Roadmap** (Phased engineering plan: Database/Function pipeline ➔ FastAPI API ➔ Svelte UI ➔ Azure Deployment).
 
