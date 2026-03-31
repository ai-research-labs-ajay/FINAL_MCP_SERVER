# MCP WebScraper — Deployment Guide

## Quick Start (Local Docker)

```bash
# 1. Build and run
docker compose up -d

# 2. Server is now live at:
#    http://localhost:8000/sse
```

Anyone can now connect their MCP client to `http://localhost:8000/sse`

---

## How Clients Connect

Once deployed, any MCP client connects using the **SSE URL**:

```
http://YOUR_SERVER_IP:8000/sse
```

### Claude Desktop Config (for people connecting to YOUR server)

Tell them to add this to their `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "webscraper": {
      "url": "http://YOUR_SERVER_IP:8000/sse"
    }
  }
}
```

### Claude Code

```bash
claude mcp add webscraper --transport sse http://YOUR_SERVER_IP:8000/sse
```

### Python MCP Client

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://YOUR_SERVER_IP:8000/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print(tools)

        # Call a tool
        result = await session.call_tool("extract_text", {
            "url": "https://example.com",
            "output_format": "markdown"
        })
        print(result)
```

---

## Deploy to Cloud

### Option A: AWS EC2 / Any VPS

```bash
# SSH into your server
ssh user@your-server-ip

# Install Docker
curl -fsSL https://get.docker.com | sh

# Clone your project (or scp it)
git clone YOUR_REPO_URL
cd MCP_WebScraper

# Build and run
docker compose up -d

# Open firewall port
sudo ufw allow 8000
```

Your server is live at `http://your-server-ip:8000/sse`

### Option B: Railway (One-Click Cloud Deploy)

1. Push your code to GitHub
2. Go to [railway.app](https://railway.app)
3. Click **"New Project" → "Deploy from GitHub repo"**
4. Select your MCP_WebScraper repo
5. Railway auto-detects the Dockerfile
6. Set environment variables:
   - `MCP_TRANSPORT=sse`
   - `MCP_HOST=0.0.0.0`
   - `MCP_PORT=8000`
7. Railway gives you a URL like `https://mcp-webscraper-xxxx.up.railway.app`
8. Clients connect to: `https://mcp-webscraper-xxxx.up.railway.app/sse`

### Option C: Render

1. Push code to GitHub
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your repo
4. Settings:
   - **Runtime**: Docker
   - **Port**: 8000
5. Add env vars: `MCP_TRANSPORT=sse`, `MCP_PORT=8000`
6. Deploy — Render gives you a URL
7. Clients connect to: `https://your-app.onrender.com/sse`

### Option D: Google Cloud Run

```bash
# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT/mcp-webscraper

# Deploy
gcloud run deploy mcp-webscraper \
  --image gcr.io/YOUR_PROJECT/mcp-webscraper \
  --port 8000 \
  --allow-unauthenticated \
  --memory 2Gi \
  --set-env-vars "MCP_TRANSPORT=sse,MCP_HOST=0.0.0.0,MCP_PORT=8000"
```

### Option E: Azure Container Apps

```bash
az containerapp up \
  --name mcp-webscraper \
  --source . \
  --ingress external \
  --target-port 8000 \
  --env-vars MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8000
```

---

## Available Tools (10 tools)

| Tool               | Description                                           |
| ------------------- | ----------------------------------------------------- |
| `fetch_page`        | Get raw HTML (static or JS-rendered)                  |
| `extract_text`      | Clean text or Markdown from any URL                   |
| `extract_article`   | Main article content via readability                  |
| `extract_links`     | All links with internal/external flags                |
| `extract_tables`    | HTML tables as structured JSON                        |
| `extract_metadata`  | OG tags, Twitter cards, JSON-LD, etc.                 |
| `extract_images`    | All images with src, alt, dimensions                  |
| `screenshot`        | Full-page PNG screenshot (base64)                     |
| `crawl_site`        | Multi-page crawler (up to 50 pages)                   |
| `search_google`     | Google search results                                 |

---

## Architecture

```
Client (Claude/Any MCP Client)
    │
    │  SSE connection (HTTP)
    ▼
┌─────────────────────────────┐
│   MCP WebScraper Server     │
│   (FastMCP + SSE transport) │
│                             │
│  ┌───────┐  ┌───────────┐  │
│  │ httpx  │  │ Playwright │  │
│  │(static)│  │ (dynamic)  │  │
│  └───┬───┘  └─────┬─────┘  │
│      │            │         │
│  ┌───▼────────────▼───┐    │
│  │   Parser Engine     │    │
│  │ (BS4 + readability  │    │
│  │  + markdownify)     │    │
│  └────────────────────┘    │
└─────────────────────────────┘
```
