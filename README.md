# AI Shopping Agent

Search products across supported marketplaces using text or a product image.
Results include product images, prices, marketplaces, and links when available.

## Setup

1. Install Python 3.14 or later.
2. Install dependencies with `pip install -e .`.
3. Copy `.env.example` to `.env` and add your API keys.
4. Start the app with `streamlit run app.py`.

The app uses QuickCommerce for Amazon, Flipkart, and Myntra searches, ReefAPI
for Meesho searches, Groq for the shopping assistant and image recognition, and
OpenStreetMap Nominatim to resolve the country, state, and city to a search
location.

Never commit `.env`; Git ignores environment files. `.env.example` contains
placeholder values and is safe to publish.
