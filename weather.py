from typing import Any
import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse
from starlette.routing import Route
from fastmcp.server.dependencies import get_http_headers
from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.logging import configure_logging
import logging

# Configure FastMCP to output DEBUG logs
configure_logging(level=logging.DEBUG)

logger = get_logger(__name__)

class CompanyAuthProvider(RemoteAuthProvider):
    def __init__(self):
        # Configure JWT verification against your identity provider
        token_verifier = JWTVerifier(
            jwks_uri="https://dev-v5dtht4xch6aermg.us.auth0.com/.well-known/jwks.json",
            issuer="https://dev-v5dtht4xch6aermg.us.auth0.com/",
            audience="https://www.deerkoski.net/mcp"
        )
        
        super().__init__(
            token_verifier=token_verifier,
            authorization_servers=[AnyHttpUrl("https://dev-v5dtht4xch6aermg.us.auth0.com")],
            base_url="https://www.deerkoski.net",  # Your server base URL
        )
    
    def get_routes(self, mcp_path: str | None = None, mcp_endpoint: Any | None = None) -> list[Route]:
        """Add custom endpoints to the standard protected resource routes."""
        
        # Get the standard OAuth protected resource routes
        routes = super().get_routes(mcp_path, mcp_endpoint)
        
        # Add authorization server metadata forwarding for client convenience
        async def authorization_server_metadata(request):
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://dev-v5dtht4xch6aermg.us.auth0.com/.well-known/oauth-authorization-server"
                )
                response.raise_for_status()
                return JSONResponse(response.json())

        # Add authorization server metadata forwarding for client convenience
        async def openid_configuration_metadata(request):
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://dev-v5dtht4xch6aermg.us.auth0.com/.well-known/openid-configuration"
                )
                response.raise_for_status()
                return JSONResponse(response.json())



        routes.append(
            Route("/.well-known/oauth-authorization-server", authorization_server_metadata)
        )

        routes.append(
            Route("/.well-known/openid-configuration", openid_configuration_metadata)
        )        
        
        return routes

# Initialize FastMCP server
mcp = FastMCP("weather", auth=CompanyAuthProvider())

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"

async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None
        
async def make_userinfo_request(authtoken: str) -> dict[str, Any] | None:
    """Make a request to the Userinfo endpointwith proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "authorization": authtoken
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://dev-v5dtht4xch6aermg.us.auth0.com/userinfo", headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(e, stack_info=True, exc_info=True)
            return None        

def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get('event', 'Unknown')}
Area: {props.get('areaDesc', 'Unknown')}
Severity: {props.get('severity', 'Unknown')}
Description: {props.get('description', 'No description available')}
Instructions: {props.get('instruction', 'No specific instructions provided')}
"""

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """

    headers = get_http_headers()
    for headername in headers.keys():
        logger.error(f"header: name: {headername}")
        logger.error(f"        name: {headername} value: {headers[headername]}")
    authtoken = headers["authorization"]
    userinfo = await make_userinfo_request(authtoken)
    logger.error(f"userinfo: {userinfo}")
    logger.error(f"name: {userinfo["name"]}")

    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return f"\n---\nHi {userinfo["name"]}".join(alerts)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period['name']}:
Temperature: {period['temperature']}°{period['temperatureUnit']}
Wind: {period['windSpeed']} {period['windDirection']}
Forecast: {period['detailedForecast']}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)

if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(host="0.0.0.0", transport="http", port=8000)