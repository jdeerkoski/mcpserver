import asyncio
from fastmcp import Client

client = Client("http://localhost:8000/mcp")

async def call_tool(name: str):
    async with client:
        result = await client.call_tool("get_alerts", {"state": "NC"})
        print(result)

asyncio.run(call_tool("get_alerts"))