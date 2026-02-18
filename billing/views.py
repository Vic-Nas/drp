import hashlib
import hmac
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import UserProfile, Plan

# ── Plan → Lemon Squeezy variant mapping ──────────────────────────────────────

PLAN_VARIANT_IDS = {
    Plan.STARTER: settings.LEMONSQUEEZY_STARTER_VARIANT_ID,
    Plan.PRO: settings.LEMONSQUEEZY_PRO_VARIANT_ID,
}

# Reverse: variant ID → plan name
VARIANT_PLAN_MAP = {v: k for k, v in PLAN_VARIANT_IDS.items()}


# ── Checkout redirect ─────────────────────────────────────────────────────────

@login_required
def checkout(request, plan):
    """
    Redirect the user to the Lemon Squeezy hosted checkout for the chosen plan.
    We pass their email so the checkout form is prefilled.
    """
    variant_id = PLAN_VARIANT_IDS.get(plan)
    if not variant_id:
        return redirect('account')

    store_id = settings.LEMONSQUEEZY_STORE_ID
    email = request.user.email

    # Lemon Squeezy checkout URL format:
    # https://store.lemonsqueezy.com/checkout/buy/<variant_id>?checkout[email]=...
    url = (
        f'https://{store_id}.lemonsqueezy.com/checkout/buy/{variant_id}'
        f'?checkout[email]={email}'
        f'&checkout[custom][user_id]={request.user.pk}'  # passed back in webhook
    )
    return HttpResponseRedirect(url)


# ── Customer portal redirect ──────────────────────────────────────────────────

@login_required
def portal(request):
    """
    Redirect the user to the Lemon Squeezy customer portal where they can
    manage or cancel their subscription.
    Requires a customer portal URL — fetched via LS API using their customer ID.
    """
    import urllib.request

    profile = request.user.profile
    if not profile.ls_customer_id:
        return redirect('account')

    api_key = settings.LEMONSQUEEZY_API_KEY
    customer_id = profile.ls_customer_id

    req = urllib.request.Request(
        f'https://api.lemonsqueezy.com/v1/customers/{customer_id}',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/vnd.api+json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            portal_url = data['data']['attributes']['urls']['customer_portal']
            return HttpResponseRedirect(portal_url)
    except Exception:
        return redirect('account')


# ── Webhook ───────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
def webhook(request):
    """
    Receive and process Lemon Squeezy webhook events.
    Verifies the signature, then updates the user's plan accordingly.
    """
    # ── Verify signature ──────────────────────────────────────────────────────
    secret = settings.LEMONSQUEEZY_SIGNING_SECRET
    signature = request.headers.get('X-Signature', '')
    digest = hmac.new(
        secret.encode('utf-8'),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(digest, signature):
        return HttpResponse('Invalid signature', status=400)

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse('Bad JSON', status=400)

    event = request.headers.get('X-Event-Name', '')
    attrs = payload.get('data', {}).get('attributes', {})
    meta = payload.get('meta', {})

    # user_id was embedded in the checkout URL custom data
    user_id = meta.get('custom_data', {}).get('user_id')
    customer_id = str(attrs.get('customer_id', ''))
    subscription_id = str(payload.get('data', {}).get('id', ''))
    status = attrs.get('status', '')
    variant_id = str(attrs.get('variant_id', ''))

    # ── Find the profile ──────────────────────────────────────────────────────
    profile = None

    if user_id:
        profile = UserProfile.objects.filter(user_id=user_id).first()

    # Fallback: look up by existing customer ID (for renewals/updates)
    if not profile and customer_id:
        profile = UserProfile.objects.filter(ls_customer_id=customer_id).first()

    if not profile:
        # Unknown user — still return 200 so LS doesn't retry forever
        return HttpResponse('User not found', status=200)

    # ── Handle events ─────────────────────────────────────────────────────────

    if event in ('subscription_created', 'subscription_updated'):
        plan = VARIANT_PLAN_MAP.get(variant_id, Plan.FREE)

        if status == 'active':
            profile.plan = plan
            profile.plan_since = timezone.now()
        elif status in ('cancelled', 'expired', 'unpaid', 'paused'):
            profile.plan = Plan.FREE
            profile.plan_since = None

        profile.ls_customer_id = customer_id
        profile.ls_subscription_id = subscription_id
        profile.ls_subscription_status = status
        profile.save(update_fields=[
            'plan', 'plan_since',
            'ls_customer_id', 'ls_subscription_id', 'ls_subscription_status',
        ])

    elif event == 'subscription_cancelled':
        # Cancelled — keep plan active until period ends (LS sends
        # subscription_updated with status=expired when it actually ends)
        profile.ls_subscription_status = 'cancelled'
        profile.save(update_fields=['ls_subscription_status'])

    elif event == 'subscription_expired':
        profile.plan = Plan.FREE
        profile.plan_since = None
        profile.ls_subscription_status = 'expired'
        profile.save(update_fields=['plan', 'plan_since', 'ls_subscription_status'])

    return HttpResponse('OK', status=200)