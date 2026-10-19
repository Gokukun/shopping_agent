
import streamlit as st

from agent import (
    SUPPORTED_MARKETPLACES,
    describe_product_image,
    run_shopping_agent,
)

st.set_page_config(
    page_title="AI Shopping Agent",
    page_icon="🛍️",
    layout="wide",
)

st.title("🛍️ AI Shopping Agent")
st.caption(
    "Find products and compare prices across marketplaces."
)

# ---------------- Sidebar ----------------

with st.sidebar:
    st.header("Search settings")

    platforms = st.multiselect(
        "Select marketplaces",
        options=SUPPORTED_MARKETPLACES,
        default=SUPPORTED_MARKETPLACES,
    )

    st.caption(
        "AJIO is not included because a compatible "
        "product-search source has not been verified."
    )

    st.subheader("Location")

    country = st.text_input("Country", value="India")
    state = st.text_input("State", value="Telangana")
    city = st.text_input("City", value="Hyderabad")
    st.caption("Location is matched to a city for local marketplace results.")

    st.subheader("Search by product image")
    uploaded_image = st.file_uploader(
        "Upload a product photo",
        type=["png", "jpg", "jpeg", "webp"],
        key="product_image",
    )
    image_preferences = st.text_input(
        "Optional details",
        placeholder="e.g. black, under ₹20,000",
        key="image_preferences",
    )
    if uploaded_image is not None:
        st.image(uploaded_image, caption="Image to search", width=180)
    image_search_clicked = st.button(
        "Find matching products",
        disabled=uploaded_image is None,
        use_container_width=True,
    )

    budget = st.number_input(
        "Maximum budget (₹); 0 = no limit",
        min_value=0,
        value=0,
        step=500,
    )

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.products = []
        st.rerun()


# ---------------- Session state ----------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "products" not in st.session_state:
    st.session_state.products = []


# ---------------- Display chat history ----------------

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# ---------------- Handle user input ----------------

query = st.chat_input(
    "e.g. Find running shoes under ₹3000"
)

if query:
    st.session_state.messages.append({
        "role": "user",
        "content": query,
    })

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        if not platforms:
            answer = "Please select at least one marketplace."
            st.warning(answer)

        else:
            try:
                with st.spinner("Searching for products..."):
                    result = run_shopping_agent(
                        query=query,
                        platforms=platforms,
                        country=country,
                        state=state,
                        city=city,
                        conversation=st.session_state.messages,
                    )

                answer = result["answer"]
                st.session_state.products = result["products"]

                st.markdown(answer)

            except Exception as exc:
                answer = (
                    "I couldn't complete the search. "
                    "Check your API keys, API response, "
                    "credits, and Groq model access."
                )
                st.error(answer)
                st.caption(str(exc))

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
    })


if image_search_clicked and uploaded_image is not None:
    if uploaded_image.size > 10 * 1024 * 1024:
        st.error("Please upload an image smaller than 10 MB.")
    elif not platforms:
        st.warning("Please select at least one marketplace.")
    else:
        user_message = "Find products matching my uploaded image."
        if image_preferences.strip():
            user_message += f" Preferences: {image_preferences.strip()}"
        st.session_state.messages.append({
            "role": "user",
            "content": user_message,
        })
        with st.chat_message("user"):
            st.markdown(user_message)

        with st.chat_message("assistant"):
            try:
                with st.spinner("Identifying the product and searching marketplaces..."):
                    image_description = describe_product_image(
                        uploaded_image.getvalue(),
                        uploaded_image.type or "image/jpeg",
                    )
                    search_query = (
                        f"Find marketplace products matching: {image_description}. "
                        f"{image_preferences.strip()}"
                    ).strip()
                    result = run_shopping_agent(
                        query=search_query,
                        platforms=platforms,
                        country=country,
                        state=state,
                        city=city,
                        conversation=[
                            {"role": "user", "content": user_message},
                        ],
                    )

                answer = result["answer"]
                st.session_state.products = result["products"]
                st.markdown(answer)
            except Exception as exc:
                answer = "I couldn't identify or search for that product image."
                st.error(answer)
                st.caption(str(exc))

        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
        })


# ---------------- Product comparison ----------------

products = st.session_state.products


def display_price(value):
    """Parse numeric prices returned as either numbers or marketplace text."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = "".join(char for char in value if char.isdigit() or char == ".")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
    return None


if budget > 0:
    filtered_products = [
        product
        for product in products
        if display_price(product.get("price")) is not None
        and display_price(product.get("price")) <= budget
    ]
else:
    filtered_products = list(products)

filtered_products.sort(
    key=lambda product: display_price(product.get("price")) or float("inf")
)

if products:
    st.divider()
    st.subheader("Products found")
    st.caption(f"Showing {len(filtered_products)} of {len(products)} marketplace results.")

    if not filtered_products:
        st.info("No products match the current budget.")

    product_columns = st.columns(3)
    for index, product in enumerate(filtered_products):
        with product_columns[index % 3]:
            with st.container(border=True):
                image = product.get("image")
                if image:
                    st.image(image, use_container_width=True)
                else:
                    st.caption("Image unavailable")

                st.markdown(f"**{product.get('name') or 'Product'}**")
                if product.get("brand"):
                    st.caption(product["brand"])

                price = display_price(product.get("price"))
                if price is not None:
                    st.markdown(f"### \u20b9{price:,.2f}")
                elif product.get("price"):
                    st.markdown(f"### {product['price']}")
                else:
                    st.caption("Price unavailable")

                st.caption(f"Marketplace: {product.get('platform') or 'Unknown'}")
                if product.get("mrp") is not None:
                    st.caption(f"MRP: \u20b9{product['mrp']}")
                if product.get("rating") is not None:
                    st.caption(f"Rating: {product['rating']}")

                url = product.get("url", "")
                if url.startswith(("https://", "http://")):
                    st.link_button("View product", url, use_container_width=True)
