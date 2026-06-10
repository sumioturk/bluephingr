"""
phingr Website Server
- Serves static files
- Stripe checkout session creation
- Stripe webhook handling
"""

import os
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import stripe
import uvicorn

# ---- Config ----

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")

# Map plan names to Stripe Price IDs (set these in .env)
PRICE_IDS = {
    "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
    "personal": os.environ.get("STRIPE_PRICE_PERSONAL", ""),
    "commercial": os.environ.get("STRIPE_PRICE_COMMERCIAL", ""),
}

stripe.api_key = STRIPE_SECRET_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phingr-web")

app = FastAPI(docs_url=None, redoc_url=None)

STATIC_DIR = Path(__file__).parent / "static"


# ---- Stripe Checkout ----

@app.post("/api/checkout")
async def create_checkout(request: Request):
    body = await request.json()
    plan = body.get("plan")

    if plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    price_id = PRICE_IDS[plan]
    if not price_id:
        raise HTTPException(status_code=500, detail="Plan not configured")

    try:
        mode = "subscription"
        # Starter is a free trial on the Pro subscription
        params = {
            "mode": mode,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{SITE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{SITE_URL}/#pricing",
        }

        if plan == "starter":
            params["subscription_data"] = {"trial_period_days": 7}

        session = stripe.checkout.Session.create(**params)
        return JSONResponse({"url": session.url})
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=500, detail="Payment error")


# ---- Stripe Webhook ----

@app.post("/api/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("Webhook secret not configured, skipping verification")
        event = json.loads(payload)
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.error(f"Webhook verification failed: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event.get("type", "")
    logger.info(f"Webhook received: {event_type}")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")
        subscription_id = session.get("subscription")
        logger.info(f"New subscription: {customer_email} -> {subscription_id}")
        # TODO: Provision license / send welcome email

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        logger.info(f"Subscription cancelled: {subscription['id']}")
        # TODO: Revoke license

    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        logger.info(f"Payment failed: {invoice.get('customer_email')}")
        # TODO: Notify customer

    return JSONResponse({"status": "ok"})


# ---- Success page ----

@app.get("/success")
async def success_page():
    return FileResponse(STATIC_DIR / "success.html")


# ---- Static files & SPA fallback ----

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/terms")
@app.get("/privacy")
async def legal_pages():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
