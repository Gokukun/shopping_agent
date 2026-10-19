
import base64
import json
import os
from functools import lru_cache

import requests
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_groq import ChatGroq

load_dotenv()

API_KEY = os.getenv("QUICKCOMMERCE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
REEF_API_KEY = os.getenv("REEF_API_KEY")

BASE_URL = "https://api.quickcommerceapi.com"


def describe_product_image(image_bytes, mime_type):
    """Use Groq vision to turn an uploaded product photo into search terms."""

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing.")

    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "qwen/qwen3.8-27b",
            "temperature": 0,
            "max_tokens": 120,
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Identify the product in this photo for an online "
                            "marketplace search. Reply with one concise search "
                            "query containing only visible product type, brand, "
                            "model, color, and distinguishing features. Do not "
                            "guess hidden specifications or explain your answer."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_image}"
                        },
                    },
                ],
            }],
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    description = payload["choices"][0]["message"]["content"].strip()
    if not description:
        raise ValueError("The image model couldn't identify a product.")
    return description[:300]


@lru_cache(maxsize=128)
def geocode_location(country, state, city):
    """Resolve a city, state, and country to coordinates for QuickCommerce."""

    location = ", ".join(part.strip() for part in (city, state, country) if part.strip())
    if not location:
        raise ValueError("Enter a country, state, and city.")

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": location, "format": "jsonv2", "limit": 1},
        headers={"User-Agent": "AIShoppingAgent/1.0"},
        timeout=15,
    )
    response.raise_for_status()
    matches = response.json()
    if not matches:
        raise ValueError(f"Couldn't find the location: {location}")

    return float(matches[0]["lat"]), float(matches[0]["lon"])

SUPPORTED_MARKETPLACES = [
    "Amazon",
    "Flipkart",
    "Myntra",
    "Meesho",
]


def search_products(query, platforms, latitude, longitude):
    """Search selected marketplaces through QuickCommerce."""

    if not API_KEY:
        raise RuntimeError("QUICKCOMMERCE_API_KEY is missing.")

    response = requests.get(
        f"{BASE_URL}/v1/groupsearch",
        headers={"X-API-Key": API_KEY},
        params={
            "q": query,
            "lat": latitude,
            "lon": longitude,
            "platforms": ",".join(platforms),
        },
        timeout=45,
    )

    response.raise_for_status()
    payload = response.json()

    if payload.get("status") == "error":
        raise RuntimeError(
            payload.get("message", "Product search failed.")
        )

    return payload


def search_meesho(query):
    """Search Meesho using ReefAPI."""

    if not REEF_API_KEY:
        raise RuntimeError("REEF_API_KEY is missing.")

    response = requests.post(
        "https://api.reefapi.com/meesho/v1/search",
        headers={
            "x-api-key": REEF_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "limit": 20,
        },
        timeout=45,
    )

    response.raise_for_status()
    payload = response.json()

    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))

    data = payload.get("data", payload)

    if isinstance(data, dict):
        items = data.get("products", data.get("results", []))
    elif isinstance(data, list):
        items = data
    else:
        items = []

    products = []

    for item in items:
        if not isinstance(item, dict):
            continue

        image = item.get("image") or item.get("image_url")
        images = item.get("images") or []

        if not image and images:
            image = (
                images[0]
                if isinstance(images[0], str)
                else None
            )

        products.append({
            "name": item.get(
                "product_name",
                item.get("title", item.get("name", "Meesho product")),
            ),
            "brand": item.get("brand", item.get("supplier_name", "")),
            "price": item.get("price"),
            "mrp": item.get("original_price", item.get("mrp")),
            "platform": "Meesho",
            "image": image,
            "url": item.get("url", item.get("product_url", "")),
            "rating": item.get("rating"),
            "available": item.get("in_stock"),
        })

    return products



def normalize_products(payload):
    """Convert API results into a consistent product format."""

    data = payload.get("data", {})
    results = data.get("results", {})
    products = []

    if isinstance(results, dict):
        groups = results.items()
    elif isinstance(results, list):
        groups = [("Unknown", results)]
    else:
        groups = []

    for marketplace, items in groups:
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            platform = item.get("platform", {})

            if isinstance(platform, dict):
                platform_name = platform.get("name", marketplace)
            else:
                platform_name = str(platform or marketplace)

            images = item.get("images") or []
            image = (
                images[0]
                if images and isinstance(images[0], str)
                else None
            )

            products.append({
                "name": item.get("name", "Unnamed product"),
                "brand": item.get("brand", ""),
                "price": item.get(
                    "offer_price", item.get("price")
                ),
                "mrp": item.get("mrp"),
                "platform": platform_name,
                "image": image,
                "url": item.get(
                    "deeplink", item.get("url", "")
                ),
                "rating": item.get("rating"),
                "available": item.get(
                    "available", item.get("in_stock")
                ),
            })

    return products


def build_agent(platforms, latitude, longitude):
    """Build the Groq-powered shopping agent."""

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is missing.")

    results_cache = []

    llm = ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0,
        api_key=GROQ_API_KEY,
    )

   
    @tool
    def search_marketplaces(query: str) -> str:
        """Search selected marketplaces for products.

        Search Amazon, Flipkart, Myntra through QuickCommerce
        and Meesho through ReefAPI. Return actual product data.
        """

        products = []

        try:
            # QuickCommerce supports these configured platforms.
            quickcommerce_platforms = [
                platform
                for platform in platforms
                if platform in ["Amazon", "Flipkart", "Myntra"]
            ]

            if quickcommerce_platforms:
                payload = search_products(
                    query=query,
                    platforms=quickcommerce_platforms,
                    latitude=latitude,
                    longitude=longitude,
                )

                products.extend(normalize_products(payload))

            # Search Meesho independently.
            if "Meesho" in platforms:
                products.extend(search_meesho(query))

            results_cache.clear()
            results_cache.extend(products)

            # Keep the full results for the UI, but send only a small,
            # bounded summary to the model. API records can contain long
            # descriptions and URLs that exceed Groq's TPM allowance.
            model_products = [
                {
                    "name": str(product.get("name") or "")[:100],
                    "brand": str(product.get("brand") or "")[:40],
                    "price": product.get("price"),
                    "mrp": product.get("mrp"),
                    "platform": str(product.get("platform") or "")[:30],
                    "rating": product.get("rating"),
                }
                for product in products[:4]
            ]

            return json.dumps(
                {
                    "query": query,
                    "total_count": len(products),
                    "products": model_products,
                },
                ensure_ascii=False,
                default=str,
            )

        except (requests.RequestException, RuntimeError, ValueError) as exc:
            return json.dumps({
                "error": f"Product search failed: {exc}",
                "products": products,
            })


    agent = create_agent(
        model=llm,
        tools=[search_marketplaces],
        system_prompt=(
            "You are an AI shopping assistant. "
            "Use the full conversation to understand follow-up answers. "
            "A short reply such as a color, size, or storage amount answers "
            "the assistant's latest relevant question; combine it with the "
            "product request already in the conversation. Do not ask for the "
            "product category again when it is already clear. Interpret phone "
            "RAM/storage wording in context, and preserve the user's stated "
            "brand, model, color, and capacity in marketplace searches. "
            "Search for products using the provided tool when enough details "
            "are available. "
            "Never invent product prices, ratings, availability, "
            "or URLs. Base comparisons on returned data. "
            "If the user specifies a budget, mention that budget "
            "when searching and comparing results. "
            "Never claim a purchase has been completed."
        ),
    )

    return agent, results_cache


def run_shopping_agent(
    query,
    platforms,
    country,
    state,
    city,
    conversation=None,
):
    """Run the agent and return its answer and product results."""

    latitude, longitude = geocode_location(country, state, city)

    agent, products = build_agent(
        platforms=platforms,
        latitude=latitude,
        longitude=longitude,
    )

    # Keep recent turns so brief follow-ups retain their product context,
    # while bounding prompt size for Groq's TPM limit.
    messages = list(conversation or [])[-8:]
    if not messages or messages[-1].get("content") != query:
        messages.append({"role": "user", "content": query})
    messages = [
        {
            "role": message.get("role", "user"),
            "content": str(message.get("content", ""))[:1200],
        }
        for message in messages
        if message.get("role") in ("user", "assistant")
    ]

    result = agent.invoke({"messages": messages})

    answer = result["messages"][-1].content

    return {
        "answer": answer,
        "products": list(products),
    }
