#  AI Pull Request Agent

An automated, multi-agent AI system that reviews GitHub Pull Requests using Google's Gemini API and LangGraph. Built as a multi-user SaaS GitHub App, it provides instant, high-quality code reviews directly as PR comments.

## ✨ Features

- **Automated PR Reviews**: Instantly reviews new PRs and subsequent commits.
- **Multi-Agent Orchestration**: Uses LangGraph to coordinate specialized AI agents:
  - 🛡️ **Security Agent**: Scans for vulnerabilities, hardcoded secrets, and injection flaws.
  - 💎 **Quality Agent**: Reviews logic, edge cases, and architectural patterns.
  - 🎨 **Style Agent**: Ensures consistent formatting and adherence to best practices.
  - 📚 **Docs Agent**: Checks for adequate documentation and docstrings.
- **Multi-User SaaS Architecture**: Securely handles multiple user accounts and GitHub App installations.
- **Robust Background Processing**: Uses ARQ and Redis for reliable asynchronous job processing, complete with rate-limit handling and exponential backoff for the Gemini API.
- **Modern Dashboard**: A React frontend to manage connected repositories and monitor system health.

## 🏗️ Architecture & Tech Stack

### Backend
- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL (Raw SQL via `psycopg`, no ORM)
- **Task Queue**: Redis + ARQ (Async Redis Queue)
- **AI/LLM Engine**: Google GenAI SDK (`gemini-3.6-flash`)
- **Orchestration**: LangGraph (StateGraph)
- **GitHub Integration**: PyGithub & Webhooks

### Frontend
- **Framework**: React + Vite
- **Styling**: Vanilla CSS with a modern dark theme
- **Routing**: React Router DOM
- **Authentication**: Stateless JWT

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL
- Redis
- A Google Gemini API Key
- A GitHub App configured with webhooks and private key.

### 1. Environment Setup
Create a `.env` file in the `backend/` directory:
```env
APP_NAME="AI Pull Request Agent"
DEBUG=True
HOST=0.0.0.0
PORT=8000

# GitHub App Settings
GITHUB_APP_ID=your_app_id
GITHUB_CLIENT_ID=your_client_id
GITHUB_CLIENT_SECRET=your_client_secret
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_PRIVATE_KEY_PATH=private-key.pem

# AI Settings
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash

# Database & Queue
DATABASE_URL=postgresql://user:password@localhost:5432/pr_agent
REDIS_URL=redis://localhost:6379/0
```

### 2. Backend Installation
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Frontend Installation
```bash
cd frontend
npm install
```

## ⚙️ Running the Application

You need to run three separate processes:

**1. The FastAPI Backend Server:**
Handles API requests and GitHub webhooks.
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**2. The ARQ Background Worker:**
Consumes jobs from Redis and executes the LangGraph AI agents.
```bash
cd backend
source venv/bin/activate
arq app.workers.review_worker.WorkerSettings
```

**3. The React Frontend:**
Serves the user dashboard.
```bash
cd frontend
npm run dev
```

## 🧠 How it Works

1. **Installation**: A user logs into the dashboard via GitHub OAuth and installs the GitHub App on their repositories.
2. **Webhook**: When a developer opens or updates a Pull Request, GitHub sends a webhook to the FastAPI backend.
3. **Queue**: The backend validates the webhook and queues a review job in Redis.
4. **Execution**: The ARQ worker picks up the job, fetches the PR diff, and delegates it to the LangGraph orchestrator.
5. **AI Review**: Specialized Gemini agents review the code in parallel.
6. **Delivery**: The worker formats the agents' findings into a beautiful markdown comment and posts it directly back to the GitHub PR.

## 🛠️ Customization
To change the AI model, update `GEMINI_MODEL` in your `.env`. The system handles API rate limits (`429`) and server overloads (`503`) automatically using exponential backoff with jitter.

## 📄 License
This project is proprietary.
