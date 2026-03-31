# Deploy MCP WebScraper on Render — Step by Step

## What You Get After Deployment

A public URL like `https://mcp-webscraper-xxxx.onrender.com/sse` that **anybody** can plug into their MCP client (Claude Desktop, Claude Code, custom apps) to get:

- 12 tools including `get_news` and `get_high_impact_news` for 48hr news
- Web scraping, screenshots, table extraction, site crawling
- No API key needed — just the URL

---

## Prerequisites

1. A **GitHub account** (free)
2. A **Render account** (free at render.com)
3. Your MCP_WebScraper code pushed to a GitHub repo

---

## Step 1: Push Code to GitHub

Open terminal in `C:\Users\Deepan\Desktop\MCP_WebScraper`:

```bash
git init
git add .
git commit -m "MCP WebScraper server with 12 tools + news aggregator"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mcp-webscraper.git
git push -u origin main
```

If you don't have a repo yet, create one at github.com/new (name: `mcp-webscraper`, keep it Public so anyone can see it).

---

## Step 2: Deploy on Render

1. Go to **https://dashboard.render.com**
2. Click **"New +"** → **"Web Service"**
3. Click **"Build and deploy from a Git repository"** → **Next**
4. Connect your GitHub account if not already connected
5. Find and select your **mcp-webscraper** repo
6. Configure the service:

| Setting | Value |
|---------|-------|
| **Name** | `mcp-webscraper` |
| **Region** | Pick closest to you (e.g., Singapore for India) |
| **Branch** | `main` |
| **Runtime** | **Docker** |
| **Instance Type** | **Starter** ($7/mo) or **Free** (for testing) |

7. Scroll down to **Environment Variables**, click "Add Environment Variable" and add:

| Key | Value |
|-----|-------|
| `MCP_TRANSPORT` | `sse` |
| `MCP_HOST` | `0.0.0.0` |
| `MCP_PORT` | `8000` |

8. Click **"Create Web Service"**

Render will now build your Docker image. This takes **5-8 minutes** the first time (downloading Playwright + Chromium). You'll see the build logs in real time.

---

## Step 3: Get Your URL

Once the build says **"Your service is live"**, your URL is shown at the top of the page:

```
https://mcp-webscraper-xxxx.onrender.com
```

Your MCP SSE endpoint is:

```
https://mcp-webscraper-xxxx.onrender.com/sse
```

---

## Step 4: Share With Others

Tell anyone who wants to use your server to do ONE of these:

### Option A: Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "webscraper": {
      "url": "https://mcp-webscraper-xxxx.onrender.com/sse"
    }
  }
}
```

Then restart Claude Desktop. They'll see 12 new tools including news fetching.

### Option B: Claude Code (Terminal)

```bash
claude mcp add webscraper --transport sse https://mcp-webscraper-xxxx.onrender.com/sse
```

### Option C: Python Client

```python
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    url = "https://mcp-webscraper-xxxx.onrender.com/sse"

    async with sse_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List all 12 tools
            tools = await session.list_tools()
            for tool in tools.tools:
                print(f"  {tool.name}: {tool.description[:60]}")

            # Get high-impact news
            result = await session.call_tool("get_high_impact_news", {
                "category": "india_markets",
                "hours": 48
            })
            print(result)

asyncio.run(main())
```

---

## Available Tools (12)

| # | Tool | What It Does |
|---|------|-------------|
| 1 | `fetch_page` | Raw HTML from any URL (static or JS-rendered) |
| 2 | `extract_text` | Clean text or Markdown from a page |
| 3 | `extract_article` | Main article content (readability algorithm) |
| 4 | `extract_links` | All links with internal/external classification |
| 5 | `extract_tables` | HTML tables → structured JSON |
| 6 | `extract_metadata` | OG tags, Twitter cards, JSON-LD, etc. |
| 7 | `extract_images` | All images with src, alt, dimensions |
| 8 | `screenshot` | Full-page PNG screenshot |
| 9 | `crawl_site` | Multi-page crawler (up to 50 pages) |
| 10 | `search_google` | Google search results |
| 11 | `get_news` | 48hr news from 4 categories with impact scoring |
| 12 | `get_high_impact_news` | Only CRITICAL & HIGH impact news |

### News Categories

| Category | Sources |
|----------|---------|
| `india_markets` | ET Markets, ET Stocks, Moneycontrol, ET Top Stories |
| `global_markets` | Yahoo Finance, BBC Business, NYT Business |
| `crypto` | CoinTelegraph |
| `technology` | TechCrunch, The Verge |
| `all` | All of the above |

---

## Troubleshooting

### Build fails on Render?
- Check Render build logs for errors
- Make sure `Dockerfile` is in the root of your repo
- Playwright needs ~1.5GB RAM minimum — use Starter plan or higher

### Server deploys but clients can't connect?
- Verify the URL ends with `/sse`
- Check Render logs for "Starting MCP WebScraper server (SSE)"
- Render free tier sleeps after 15 min of inactivity — first request takes ~30s to wake up

### News returns empty?
- Some RSS feeds may be temporarily down
- Try `category: "all"` to check multiple sources
- Set `min_impact: "LOW"` to see everything

---

## Cost

| Render Plan | Price | Best For |
|-------------|-------|----------|
| Free | $0/mo | Testing (sleeps after 15 min idle) |
| Starter | $7/mo | Personal use (always on) |
| Standard | $25/mo | Team use (more RAM for Playwright) |

---

## Architecture

```
Any MCP Client (Claude Desktop / Claude Code / Python / etc.)
        │
        │ SSE (HTTPS)
        ▼
┌──────────────────────────────────────┐
│   Render.com (Docker container)       │
│                                       │
│   MCP WebScraper Server               │
│   ├── 10 scraping tools              │
│   ├── 2 news tools (48hr aggregator) │
│   ├── httpx (static pages)           │
│   └── Playwright (JS-rendered pages) │
└──────────────────────────────────────┘
        │
        │ HTTP/HTTPS
        ▼
   Any website / RSS feed
```
