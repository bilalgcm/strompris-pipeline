# Strømpris MCP server

Lets Claude (or any MCP client) use Strømpris Pipeline as a set of tools. It's a thin client over
the public API at https://strompris-pipeline.fly.dev, so all price, cost and forecast logic stays
in the tested API.

## Tools

| Tool | What it answers |
|---|---|
| `get_prices` | Hourly spot prices for a day and price area |
| `get_real_cost_now` | What a household pays this hour on spot and Norgespris, and appliance costs now vs. at the cheapest time |
| `get_forecast` | Forecast for the first unpublished day, with an 80 % prediction interval |
| `cheapest_hours` | Best time to start something that runs N hours, on the real price |
| `compare_spot_norgespris` | One month of your consumption: spot with strømstøtte vs. Norgespris |

Try asking: *"When should I charge my car tonight in NO1?"*, *"What will power cost in Bergen tomorrow?"*,
or *"I used 535 kWh in September with a 3,9 øre markup. Would Norgespris have been cheaper?"*

## Setup

Install the one extra dependency into the project's virtual environment:

```bash
source .venv/bin/activate
pip install -r mcp_server/requirements.txt
```

Use **absolute paths** below, and replace `/Users/you/strompris-pipeline` with where the repo lives
(`pwd` from the repo root prints it).

### Claude Code

```bash
claude mcp add --transport stdio --scope user strompris -- \
  /Users/you/strompris-pipeline/.venv/bin/python /Users/you/strompris-pipeline/mcp_server/server.py
claude mcp list        # should show strompris as connected
```

### Claude Desktop

Claude menu > Settings > Developer > Edit Config, and add:

```json
{
  "mcpServers": {
    "strompris": {
      "command": "/Users/you/strompris-pipeline/.venv/bin/python",
      "args": ["/Users/you/strompris-pipeline/mcp_server/server.py"]
    }
  }
}
```

Quit Claude Desktop completely and start it again. Logs are in `~/Library/Logs/Claude/mcp-server-strompris.log`.

### Against a local API

Set `STROMPRIS_API_URL=http://127.0.0.1:8000` (with `--env` for Claude Code, or an `"env"` block in the
Desktop config) to use the API you're running locally instead of the live site.
