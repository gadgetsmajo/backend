from collections import defaultdict
from decimal import Decimal, InvalidOperation
import secrets

from cloudinary.utils import cloudinary_url
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from products.models import CatalogProduct, Category, Product
from traders.models import TraderApplication, TraderProduct
from traders.views import _get_trader_by_uuid, _is_trader_owner

from .models import (
    AdvertisingCampaign,
    AdvertisingCampaignOffer,
    AdvertisingClick,
    AdvertisingImpression,
    AdvertisingWallet,
    AdvertisingWalletTransaction,
)
from .services import (
    IdempotencyConflict,
    PaymentConfigurationError,
    PaymentRejected,
    campaign_spend,
    daily_campaign_spend,
    eligible_offer,
    get_wallet,
    recharge_wallet,
    reconcile_campaign,
    record_click,
    visitor_hash,
)

ZERO = Decimal('0.00')
MAX_CAMPAIGN_OFFERS = 20
MAX_IMPRESSIONS_PER_REQUEST = 20


def _money(value):
    return str(value or ZERO)


def _image_url(offer, public_product=None):
    if public_product and public_product.image:
        try:
            return public_product.image.url
        except (AttributeError, ValueError):
            pass
    if offer.image:
        try:
            return offer.image.url
        except (AttributeError, ValueError):
            pass
    if offer.image_url:
        return offer.image_url
    catalog = offer.catalog_product
    references = (catalog.image_references or []) if catalog else []
    if references:
        first = references[0]
        if isinstance(first, dict):
            first = first.get('url') or first.get('public_id') or first.get('secure_url')
        if isinstance(first, str) and first:
            if first.startswith(('http://', 'https://')):
                return first
            return cloudinary_url(first, secure=True)[0]
    return None


def _linked_public_product(offer):
    try:
        return offer.public_product
    except ObjectDoesNotExist:
        return None


def _offer_payload(offer, campaign_offer=None):
    product = _linked_public_product(offer)
    result = {
        'id': offer.pk,
        'name': offer.name,
        'price': _money(offer.price),
        'image': _image_url(offer, product),
        'stock': offer.stock,
        'public_product_id': product.pk if product else None,
        'slug': product.slug if product else None,
    }
    if campaign_offer is not None:
        result['campaign_offer_id'] = campaign_offer.pk
    return result


def _campaign_metrics(campaigns):
    ids = [campaign.pk for campaign in campaigns]
    if not ids:
        return {}, {}, {}, {}
    impression_counts = dict(
        AdvertisingImpression.objects.filter(campaign_offer__campaign_id__in=ids)
        .values('campaign_offer__campaign_id')
        .annotate(total=Count('pk'))
        .values_list('campaign_offer__campaign_id', 'total')
    )
    click_counts = defaultdict(int)
    suspicious_counts = defaultdict(int)
    for campaign_id, click_status, total in (
        AdvertisingClick.objects.filter(campaign_offer__campaign_id__in=ids)
        .values('campaign_offer__campaign_id', 'status')
        .annotate(total=Count('pk'))
        .values_list('campaign_offer__campaign_id', 'status', 'total')
    ):
        if click_status == AdvertisingClick.Status.VALID:
            click_counts[campaign_id] = total
        elif click_status == AdvertisingClick.Status.SUSPICIOUS:
            suspicious_counts[campaign_id] = total
    spend_values = dict(
        AdvertisingWalletTransaction.objects.filter(
            campaign_id__in=ids,
            transaction_type=AdvertisingWalletTransaction.Type.CLICK,
        )
        .values('campaign_id')
        .annotate(total=Sum('amount'))
        .values_list('campaign_id', 'total')
    )
    spend = {campaign_id: -amount for campaign_id, amount in spend_values.items()}
    return impression_counts, click_counts, suspicious_counts, spend


def _campaign_payload(campaign, metrics, *, admin=False):
    impression_counts, click_counts, suspicious_counts, spends = metrics
    impressions = impression_counts.get(campaign.pk, 0)
    clicks = click_counts.get(campaign.pk, 0)
    spent = spends.get(campaign.pk, ZERO)
    offers = [
        _offer_payload(entry.trader_offer, entry)
        for entry in campaign.offers.all()
    ]
    payload = {
        'id': campaign.pk,
        'name': campaign.name,
        'status': campaign.status,
        'max_cpc': _money(campaign.max_cpc),
        'daily_budget': _money(campaign.daily_budget),
        'total_budget': _money(campaign.total_budget),
        'spent': _money(spent),
        'remaining_budget': _money(max(ZERO, campaign.total_budget - spent)),
        'impressions': impressions,
        'clicks': clicks,
        'ctr': round(clicks * 100 / impressions, 2) if impressions else 0,
        'average_cpc': _money(spent / clicks if clicks else ZERO),
        'starts_at': campaign.start_date.isoformat(),
        'ends_at': campaign.end_date.isoformat(),
        'pause_reason': campaign.pause_reason,
        'offers': offers,
    }
    if admin:
        wallet = getattr(campaign.trader, 'advertising_wallet', None)
        payload.update({
            'trader_name': campaign.trader.business_name,
            'wallet_balance': _money(wallet.balance if wallet else ZERO),
            'suspicious_clicks': suspicious_counts.get(campaign.pk, 0),
        })
    return payload


def _load_campaigns(queryset):
    campaigns = list(
        queryset.select_related('trader', 'trader__advertising_wallet')
        .prefetch_related(
            'offers__trader_offer__catalog_product',
            'offers__trader_offer__public_product',
        )
    )
    metrics = _campaign_metrics(campaigns)
    return campaigns, metrics


def _campaign_collection(queryset, *, admin=False):
    campaigns, metrics = _load_campaigns(queryset)
    return [_campaign_payload(campaign, metrics, admin=admin) for campaign in campaigns]


def _dashboard_stats(campaigns, metrics):
    impressions, clicks, _, spend = metrics
    total_impressions = sum(impressions.values())
    total_clicks = sum(clicks.values())
    total_spent = sum(spend.values(), ZERO)
    budget_states = {
        AdvertisingCampaign.Status.ACTIVE,
        AdvertisingCampaign.Status.PENDING_REVIEW,
        AdvertisingCampaign.Status.PAUSED,
        AdvertisingCampaign.Status.SCHEDULED,
    }
    remaining = sum(
        (
            max(ZERO, campaign.total_budget - spend.get(campaign.pk, ZERO))
            for campaign in campaigns
            if campaign.status in budget_states
        ),
        ZERO,
    )
    counts = defaultdict(int)
    for campaign in campaigns:
        counts[campaign.status] += 1
    return {
        'active_campaigns': counts[AdvertisingCampaign.Status.ACTIVE],
        'pending_campaigns': counts[AdvertisingCampaign.Status.PENDING_REVIEW],
        'paused_campaigns': counts[AdvertisingCampaign.Status.PAUSED],
        'completed_campaigns': counts[AdvertisingCampaign.Status.COMPLETED],
        'rejected_campaigns': counts[AdvertisingCampaign.Status.REJECTED],
        'impressions': total_impressions,
        'clicks': total_clicks,
        'ctr': round(total_clicks * 100 / total_impressions, 2) if total_impressions else 0,
        'average_cpc': _money(total_spent / total_clicks if total_clicks else ZERO),
        'total_spent': _money(total_spent),
        'remaining_budget': _money(remaining),
    }


def _trader_for_request(request, trader_uuid):
    trader = _get_trader_by_uuid(trader_uuid)
    if not trader or not _is_trader_owner(request, trader):
        return None
    return trader


class TraderAdvertisingView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        wallet = get_wallet(trader)
        queryset = AdvertisingCampaign.objects.filter(trader=trader)
        for campaign_id in queryset.values_list('pk', flat=True)[:50]:
            reconcile_campaign(campaign_id)
        all_campaigns = list(
            queryset.select_related('trader')
            .prefetch_related('offers__trader_offer__catalog_product', 'offers__trader_offer__public_product')
        )
        metrics = _campaign_metrics(all_campaigns)
        transactions = AdvertisingWalletTransaction.objects.filter(wallet=wallet)[:20]
        return Response({
            'wallet': {
                'balance': _money(wallet.balance),
                'dummy_payments_enabled': bool(
                    settings.DEBUG
                    and getattr(settings, 'PAYMENT_MODE', '') == 'dummy'
                    and getattr(settings, 'ADVERTISING_ENABLED', True)
                ),
            },
            'stats': _dashboard_stats(all_campaigns, metrics),
            'campaigns': [
                _campaign_payload(campaign, metrics)
                for campaign in all_campaigns[:50]
            ],
            'transactions': [
                {
                    'id': item.pk,
                    'kind': item.transaction_type,
                    'amount': _money(item.amount),
                    'balance_after': _money(item.balance_after),
                    'reference': item.reference,
                    'description': item.reason,
                    'created_at': item.created_at.isoformat(),
                }
                for item in transactions
            ],
        })


class TraderAdvertisingOffersView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, trader_uuid):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        offers = TraderProduct.objects.filter(trader=trader).select_related(
            'catalog_product',
            'catalog_product__category',
            'public_product',
        ).order_by('name')
        results = []
        for offer in offers:
            eligible, _ = eligible_offer(offer)
            if eligible:
                results.append(_offer_payload(offer))
        return Response(results)


class TraderAdvertisingRechargeView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'advertising_recharge'

    def post(self, request, trader_uuid):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        if not getattr(settings, 'ADVERTISING_ENABLED', True):
            return Response({'detail': 'Advertising is temporarily disabled.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        # Card fields remain in request memory only and are never logged or serialized.
        try:
            result = recharge_wallet(
                trader,
                amount=request.data.get('amount'),
                idempotency_key=request.headers.get('Idempotency-Key'),
                card_number=request.data.get('card_number'),
                expiry=request.data.get('expiry'),
                cvv=request.data.get('cvv'),
                cardholder_name=request.data.get('cardholder_name'),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IdempotencyConflict as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except (PaymentRejected, PaymentConfigurationError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result, status=status.HTTP_201_CREATED)


def _parse_campaign_input(data):
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 120:
        raise ValidationError({'name': 'Name is required and must be at most 120 characters.'})
    try:
        offer_ids = data.get('offer_ids')
        if not isinstance(offer_ids, list) or not offer_ids:
            raise ValueError('offer_ids must be a non-empty array.')
        if len(offer_ids) > MAX_CAMPAIGN_OFFERS:
            raise ValueError(f'No more than {MAX_CAMPAIGN_OFFERS} offers may be added.')
        offer_ids = [int(value) for value in offer_ids]
        if len(set(offer_ids)) != len(offer_ids):
            raise ValueError('offer_ids must not contain duplicates.')
        max_cpc = Decimal(str(data.get('max_cpc'))).quantize(Decimal('0.01'))
        daily_budget = Decimal(str(data.get('daily_budget'))).quantize(Decimal('0.01'))
        total_budget = Decimal(str(data.get('total_budget'))).quantize(Decimal('0.01'))
        starts_at = _parse_campaign_date(data.get('starts_at'))
        ends_at = _parse_campaign_date(data.get('ends_at'))
    except (ValueError, TypeError, ArithmeticError, OverflowError) as exc:
        raise ValidationError({'detail': f'Invalid campaign input: {exc}'})
    if not all(value.is_finite() for value in (max_cpc, daily_budget, total_budget)):
        raise ValidationError({'detail': 'CPC and budgets must be finite amounts.'})
    if min(max_cpc, daily_budget, total_budget) <= ZERO:
        raise ValidationError({'detail': 'CPC and budgets must be greater than zero.'})
    if (
        max_cpc >= Decimal('10000000000.00')
        or daily_budget >= Decimal('1000000000000.00')
        or total_budget >= Decimal('1000000000000.00')
    ):
        raise ValidationError({'detail': 'Campaign amounts exceed the supported maximum.'})
    if starts_at > ends_at:
        raise ValidationError({'ends_at': 'ends_at must be on or after starts_at.'})
    if ends_at < timezone.localdate():
        raise ValidationError({'ends_at': 'Campaign end date must not be in the past.'})
    if daily_budget < max_cpc:
        raise ValidationError({'daily_budget': 'daily_budget must cover at least one maximum CPC click.'})
    if total_budget < max_cpc:
        raise ValidationError({'total_budget': 'total_budget must cover at least one maximum CPC click.'})
    return {
        'name': name,
        'offer_ids': offer_ids,
        'max_cpc': max_cpc,
        'daily_budget': daily_budget,
        'total_budget': total_budget,
        'starts_at': starts_at,
        'ends_at': ends_at,
    }


def _parse_campaign_date(value):
    text = str(value or '').strip()
    parsed = parse_date(text)
    if parsed is not None:
        return parsed
    parsed_datetime = parse_datetime(text)
    if parsed_datetime is None:
        raise ValueError('starts_at and ends_at must be ISO dates or datetimes.')
    if timezone.is_aware(parsed_datetime):
        return timezone.localtime(parsed_datetime).date()
    return parsed_datetime.date()


class TraderAdvertisingCampaignsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'advertising_campaigns'

    def get(self, request, trader_uuid):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'results': _campaign_collection(
                AdvertisingCampaign.objects.filter(trader=trader).order_by('-created_at')
            ),
        })

    def post(self, request, trader_uuid):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        if not getattr(settings, 'ADVERTISING_ENABLED', True):
            return Response({'detail': 'Advertising is temporarily disabled.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        payload = _parse_campaign_input(request.data)
        offers = list(
            TraderProduct.objects.filter(
                pk__in=payload['offer_ids'],
                trader=trader,
            ).select_related('trader', 'catalog_product', 'public_product')
        )
        if len(offers) != len(payload['offer_ids']):
            return Response({'detail': 'One or more offers are missing or do not belong to this trader.'}, status=status.HTTP_400_BAD_REQUEST)
        for offer in offers:
            eligible, reason = eligible_offer(offer)
            if not eligible:
                return Response({'detail': f'{offer.name}: {reason}'}, status=status.HTTP_400_BAD_REQUEST)
        approval_required = getattr(settings, 'ADVERTISING_REQUIRE_APPROVAL', True)
        today = timezone.localdate()
        if approval_required:
            initial_status = AdvertisingCampaign.Status.PENDING_REVIEW
        elif payload['starts_at'] > today:
            initial_status = AdvertisingCampaign.Status.SCHEDULED
        else:
            wallet = get_wallet(trader)
            initial_status = (
                AdvertisingCampaign.Status.ACTIVE
                if wallet.balance > ZERO else AdvertisingCampaign.Status.PAUSED
            )
        with transaction.atomic():
            campaign = AdvertisingCampaign.objects.create(
                trader=trader,
                name=payload['name'],
                max_cpc=payload['max_cpc'],
                daily_budget=payload['daily_budget'],
                total_budget=payload['total_budget'],
                start_date=payload['starts_at'],
                end_date=payload['ends_at'],
                status=initial_status,
                pause_reason=(
                    'insufficient_balance'
                    if initial_status == AdvertisingCampaign.Status.PAUSED else ''
                ),
                reviewed_at=None if approval_required else timezone.now(),
            )
            for offer in offers:
                AdvertisingCampaignOffer.objects.create(
                    campaign=campaign,
                    trader_offer=offer,
                    catalog_product=offer.catalog_product,
                )
        return Response({
            'campaign': _campaign_collection(
                AdvertisingCampaign.objects.filter(pk=campaign.pk)
            )[0],
        }, status=status.HTTP_201_CREATED)


class TraderAdvertisingCampaignDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, trader_uuid, pk):
        trader = _trader_for_request(request, trader_uuid)
        if trader is None:
            return Response({'detail': 'Trader not found or access denied.'}, status=status.HTTP_404_NOT_FOUND)
        action = request.data.get('action')
        if action not in ('pause', 'resume', 'cancel'):
            return Response({'detail': 'action must be pause, resume, or cancel.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            campaign = get_object_or_404(
                AdvertisingCampaign.objects.select_for_update().filter(trader=trader),
                pk=pk,
            )
            if action == 'pause':
                if campaign.status not in (AdvertisingCampaign.Status.ACTIVE, AdvertisingCampaign.Status.SCHEDULED):
                    return Response({'detail': 'Only active or scheduled campaigns can be paused.'}, status=status.HTTP_409_CONFLICT)
                campaign.status = AdvertisingCampaign.Status.PAUSED
                campaign.pause_reason = 'trader_paused'
            elif action == 'resume':
                if campaign.reviewed_at is None:
                    return Response({'detail': 'Campaign requires admin approval before it can be resumed.'}, status=status.HTTP_409_CONFLICT)
                if campaign.status not in (AdvertisingCampaign.Status.PAUSED, AdvertisingCampaign.Status.SCHEDULED):
                    return Response({'detail': 'Campaign cannot be resumed from its current status.'}, status=status.HTTP_409_CONFLICT)
                if campaign.end_date < timezone.localdate():
                    campaign.status = AdvertisingCampaign.Status.COMPLETED
                    campaign.pause_reason = 'campaign_ended'
                elif campaign_spend(campaign) >= campaign.total_budget:
                    campaign.status = AdvertisingCampaign.Status.BUDGET_EXHAUSTED
                    campaign.pause_reason = 'total_budget_exhausted'
                elif daily_campaign_spend(campaign) + campaign.max_cpc > campaign.daily_budget:
                    return Response({'detail': 'Daily campaign budget is exhausted.'}, status=status.HTTP_409_CONFLICT)
                elif get_wallet(trader).balance <= ZERO:
                    return Response({'detail': 'Insufficient advertising wallet balance.'}, status=status.HTTP_409_CONFLICT)
                else:
                    offer_rows = list(campaign.offers.select_related('trader_offer__catalog_product', 'trader_offer__public_product'))
                    for row in offer_rows:
                        ok, reason = eligible_offer(row.trader_offer)
                        if not ok:
                            return Response({'detail': reason}, status=status.HTTP_409_CONFLICT)
                    campaign.status = (
                        AdvertisingCampaign.Status.SCHEDULED
                        if campaign.start_date > timezone.localdate()
                        else AdvertisingCampaign.Status.ACTIVE
                    )
                    campaign.pause_reason = ''
            else:
                if campaign.status in (AdvertisingCampaign.Status.COMPLETED, AdvertisingCampaign.Status.CANCELLED):
                    return Response({'detail': 'Campaign is already closed.'}, status=status.HTTP_409_CONFLICT)
                campaign.status = AdvertisingCampaign.Status.CANCELLED
                campaign.pause_reason = 'trader_cancelled'
            campaign.save(update_fields=('status', 'pause_reason', 'updated_at'))
        return Response({
            'campaign': _campaign_collection(
                AdvertisingCampaign.objects.filter(pk=campaign.pk)
            )[0],
        })


def _category_ids(category):
    ids = {category.pk}
    frontier = [category.pk]
    while frontier:
        children = list(Category.objects.filter(parent_id__in=frontier).values_list('pk', flat=True))
        ids.update(children)
        frontier = children
    return ids


def _placement_queryset(request):
    queryset = AdvertisingCampaignOffer.objects.filter(
        campaign__status__in=(
            AdvertisingCampaign.Status.ACTIVE,
            AdvertisingCampaign.Status.SCHEDULED,
        ),
        campaign__start_date__lte=timezone.localdate(),
        campaign__end_date__gte=timezone.localdate(),
        campaign__trader__status='approved',
        campaign__trader__is_visible=True,
        campaign__trader__is_closed=False,
        trader_offer__is_active=True,
        trader_offer__availability='in_stock',
        trader_offer__stock__gt=0,
        catalog_product__is_active=True,
        catalog_product__review_status='approved',
        trader_offer__trader_id=F('campaign__trader_id'),
        trader_offer__catalog_product_id=F('catalog_product_id'),
    ).select_related(
        'campaign',
        'campaign__trader',
        'trader_offer',
        'trader_offer__public_product',
        'trader_offer__category',
        'trader_offer__catalog_product',
        'trader_offer__catalog_product__category',
        'catalog_product__category',
    )
    q = str(request.query_params.get('q') or '').strip()[:100]
    category_value = str(request.query_params.get('category') or '').strip()[:100]
    product_value = str(request.query_params.get('product') or '').strip()[:100]
    exact_product_value = str(request.query_params.get('exact_product') or '').strip()
    excluded_value = str(request.query_params.get('exclude') or '').strip()
    if excluded_value:
        try:
            excluded_ids = [int(value) for value in excluded_value.split(',') if value.strip()]
        except ValueError:
            return queryset.none(), q
        if excluded_ids:
            queryset = queryset.exclude(trader_offer__public_product__pk__in=excluded_ids)
    if q:
        terms = [term for term in q.split() if term][:6]
        query = Q()
        for term in terms:
            query |= (
                Q(trader_offer__name__icontains=term)
                | Q(trader_offer__brand__icontains=term)
                | Q(catalog_product__name__icontains=term)
                | Q(catalog_product__brand__icontains=term)
                | Q(catalog_product__model__icontains=term)
                | Q(catalog_product__product_type__icontains=term)
            )
        queryset = queryset.filter(query)
    if category_value:
        category = Category.objects.filter(
            Q(pk=category_value) if category_value.isdigit() else Q(slug=category_value),
            is_active=True,
        ).first()
        if not category:
            return queryset.none(), q
        category_ids = _category_ids(category)
        queryset = queryset.filter(
            Q(trader_offer__category_id__in=category_ids)
            | Q(catalog_product__category_id__in=category_ids)
        )
    if product_value:
        target = Product.objects.filter(
            Q(pk=product_value) if product_value.isdigit() else Q(slug=product_value),
        ).select_related('catalog_product', 'category').first()
        catalog_id = target.catalog_product_id if target else None
        if not catalog_id and product_value.isdigit():
            catalog_id = CatalogProduct.objects.filter(pk=product_value).values_list('pk', flat=True).first()
            target_catalog = CatalogProduct.objects.filter(pk=catalog_id).select_related('category').first() if catalog_id else None
        else:
            target_catalog = target.catalog_product if target else None
        if not target_catalog:
            return queryset.none(), q
        category_id = target_catalog.category_id
        if category_id:
            category_ids = _category_ids(Category.objects.get(pk=category_id))
            queryset = queryset.filter(
                Q(catalog_product_id=target_catalog.pk)
                | Q(trader_offer__category_id__in=category_ids)
                | Q(catalog_product__category_id__in=category_ids)
            )
        else:
            queryset = queryset.filter(catalog_product_id=target_catalog.pk)
    if exact_product_value:
        if not exact_product_value.isdigit() or int(exact_product_value) <= 0:
            return queryset.none(), q
        queryset = queryset.filter(trader_offer__public_product__pk=int(exact_product_value))
    return queryset, q


def _placement_relevance(row, tokens):
    offer = row.trader_offer
    catalog = row.catalog_product
    content = ' '.join((
        offer.name or '',
        offer.brand or '',
        catalog.name or '',
        catalog.brand or '',
        catalog.model or '',
        catalog.product_type or '',
        ' '.join(catalog.tags if isinstance(catalog.tags, list) else []),
    )).casefold()
    return sum(1 for token in tokens if token.casefold() in content)


def _has_budget_and_wallet(row, spend_cache, wallet_cache, daily_cache):
    campaign = row.campaign
    if campaign.pk not in spend_cache:
        spend_cache[campaign.pk] = campaign_spend(campaign)
    if campaign.pk not in daily_cache:
        daily_cache[campaign.pk] = daily_campaign_spend(campaign)
    if campaign.trader_id not in wallet_cache:
        wallet_cache[campaign.trader_id] = AdvertisingWallet.objects.filter(
            trader_id=campaign.trader_id,
        ).values_list('balance', flat=True).first() or ZERO
    cpc = campaign.max_cpc
    return (
        spend_cache[campaign.pk] + cpc <= campaign.total_budget
        and daily_cache[campaign.pk] + cpc <= campaign.daily_budget
        and wallet_cache[campaign.trader_id] >= cpc
    )


class SponsoredPlacementsView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        if not getattr(settings, 'ADVERTISING_ENABLED', True):
            return Response({'results': []})
        try:
            limit = min(50, max(1, int(request.query_params.get('limit', 12))))
        except (TypeError, ValueError):
            return Response({'detail': 'limit must be an integer from 1 to 50.'}, status=status.HTTP_400_BAD_REQUEST)
        excluded = request.query_params.get('exclude', '')
        try:
            excluded_ids = [int(value) for value in excluded.split(',') if value.strip()]
        except ValueError:
            return Response({'detail': 'exclude must be comma-separated public product IDs.'}, status=status.HTTP_400_BAD_REQUEST)
        if any(value <= 0 for value in excluded_ids):
            return Response({'detail': 'exclude IDs must be positive integers.'}, status=status.HTTP_400_BAD_REQUEST)
        daily_paused_campaign_ids = AdvertisingCampaign.objects.filter(
            status=AdvertisingCampaign.Status.PAUSED,
            pause_reason='daily_budget_exhausted',
            end_date__gte=timezone.localdate(),
        ).values_list('pk', flat=True)[:200]
        for campaign_id in daily_paused_campaign_ids:
            reconcile_campaign(campaign_id)
        queryset, q = _placement_queryset(request)
        rows = list(queryset[:200])
        for campaign_id in {row.campaign_id for row in rows}:
            reconcile_campaign(campaign_id)
        active_campaign_ids = set(AdvertisingCampaign.objects.filter(
            pk__in={row.campaign_id for row in rows},
            status=AdvertisingCampaign.Status.ACTIVE,
        ).values_list('pk', flat=True))
        rows = [row for row in rows if row.campaign_id in active_campaign_ids]
        wallet_cache, spend_cache, daily_cache = {}, {}, {}
        candidates = []
        for row in rows:
            eligible, _ = eligible_offer(row.trader_offer)
            if not eligible or not _has_budget_and_wallet(row, spend_cache, wallet_cache, daily_cache):
                continue
            product = _linked_public_product(row.trader_offer)
            candidates.append((row, product, _placement_relevance(row, q.split())))
        candidates.sort(
            key=lambda item: (-item[2], -item[0].campaign.max_cpc, item[0].pk)
        )
        results = []
        for row, product, _ in candidates[:limit]:
            category = row.catalog_product.category or row.trader_offer.category
            slug = product.slug if product else None
            results.append({
                'campaign_offer_id': row.pk,
                'public_product_id': product.pk if product else None,
                'slug': slug,
                'name': row.trader_offer.name,
                'image': _image_url(row.trader_offer, product),
                'price': _money(row.trader_offer.price),
                'category': category.name if category else None,
                'category_slug': category.slug if category else None,
                'sponsored': True,
            })
        return Response({'results': results})


class AdvertisingImpressionsView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'advertising_impressions'

    def post(self, request):
        if not getattr(settings, 'ADVERTISING_ENABLED', True):
            return Response({'accepted': 0, 'recorded': 0})
        ids = request.data.get('campaign_offer_ids')
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'campaign_offer_ids must be a non-empty array.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(ids) > MAX_IMPRESSIONS_PER_REQUEST:
            return Response({'detail': f'No more than {MAX_IMPRESSIONS_PER_REQUEST} impressions may be submitted at once.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ids = list(dict.fromkeys(int(value) for value in ids))
        except (TypeError, ValueError):
            return Response({'detail': 'campaign_offer_ids must contain integers.'}, status=status.HTTP_400_BAD_REQUEST)
        queryset = AdvertisingCampaignOffer.objects.filter(
            pk__in=ids,
            campaign__status=AdvertisingCampaign.Status.ACTIVE,
            campaign__start_date__lte=timezone.localdate(),
            campaign__end_date__gte=timezone.localdate(),
            trader_offer__trader_id=F('campaign__trader_id'),
            trader_offer__catalog_product_id=F('catalog_product_id'),
        ).select_related('campaign', 'trader_offer__catalog_product', 'trader_offer__public_product')
        visitor = visitor_hash(request)
        today = timezone.localdate()
        entries = []
        wallet_cache, spend_cache, daily_cache = {}, {}, {}
        for row in queryset:
            eligible, _ = eligible_offer(row.trader_offer)
            if eligible and _has_budget_and_wallet(row, spend_cache, wallet_cache, daily_cache):
                entries.append(AdvertisingImpression(
                    campaign_offer=row,
                    visitor_hash=visitor,
                    impression_date=today,
                    user=request.user if getattr(request.user, 'is_authenticated', False) else None,
                ))
        existing_count = AdvertisingImpression.objects.filter(
            campaign_offer_id__in=[entry.campaign_offer_id for entry in entries],
            visitor_hash=visitor,
            impression_date=today,
        ).count() if entries else 0
        with transaction.atomic():
            AdvertisingImpression.objects.bulk_create(entries, ignore_conflicts=True)
            new_count = AdvertisingImpression.objects.filter(
                campaign_offer_id__in=[entry.campaign_offer_id for entry in entries],
                visitor_hash=visitor,
                impression_date=today,
            ).count() if entries else 0
        return Response({'accepted': len(ids), 'recorded': max(0, new_count - existing_count)})


class AdvertisingClicksView(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'advertising_clicks'

    def post(self, request):
        campaign_offer_id = request.data.get('campaign_offer_id')
        idempotency_key = request.data.get('idempotency_key')
        try:
            campaign_offer_id = int(campaign_offer_id)
        except (TypeError, ValueError):
            return Response({'detail': 'campaign_offer_id must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        if not getattr(settings, 'ADVERTISING_ENABLED', True):
            return Response({
                'status': 'invalid',
                'slug': None,
                'charged_amount': '0.00',
                'detail': 'Advertising is temporarily disabled.',
            }, status=status.HTTP_409_CONFLICT)
        try:
            result = record_click(
                campaign_offer_id=campaign_offer_id,
                idempotency_key=idempotency_key,
                request=request,
            )
        except LookupError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response({'detail': 'Click could not be recorded; retry with the same idempotency key.'}, status=status.HTTP_409_CONFLICT)
        slug = result.pop('slug', None)
        response_data = {
            'status': result['status'],
            'slug': slug,
            'charged_amount': result['charged_amount'],
        }
        if result.get('reason'):
            response_data['reason'] = result['reason']
        if result.get('duplicate'):
            response_data['duplicate'] = True
        if slug:
            response_data['product_url'] = f'/products/{slug}/'
        return Response(response_data)


class AdminAdvertisingCampaignsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        campaigns = _campaign_collection(
            AdvertisingCampaign.objects.all().order_by('-created_at'),
            admin=True,
        )
        return Response({'results': campaigns})


class AdminAdvertisingCampaignDetailView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def patch(self, request, pk):
        action = request.data.get('action')
        if action not in ('approve', 'reject', 'pause', 'resume', 'cancel'):
            return Response({'detail': 'Unsupported campaign action.'}, status=status.HTTP_400_BAD_REQUEST)
        reason = str(request.data.get('reason') or '').strip()
        with transaction.atomic():
            campaign = get_object_or_404(
                AdvertisingCampaign.objects.select_for_update()
                .select_related('trader')
                .prefetch_related('offers__trader_offer__catalog_product', 'offers__trader_offer__public_product'),
                pk=pk,
            )
            if action == 'approve':
                if campaign.status != AdvertisingCampaign.Status.PENDING_REVIEW:
                    return Response({'detail': 'Only pending campaigns can be approved.'}, status=status.HTTP_409_CONFLICT)
                for row in campaign.offers.all():
                    ok, eligibility_reason = eligible_offer(row.trader_offer)
                    if not ok:
                        return Response({'detail': eligibility_reason}, status=status.HTTP_409_CONFLICT)
                wallet = get_wallet(campaign.trader)
                campaign.reviewed_by = request.user
                campaign.reviewed_at = timezone.now()
                campaign.rejection_reason = ''
                if campaign.end_date < timezone.localdate():
                    campaign.status = AdvertisingCampaign.Status.COMPLETED
                    campaign.pause_reason = 'campaign_ended'
                elif wallet.balance <= ZERO:
                    campaign.status = AdvertisingCampaign.Status.PAUSED
                    campaign.pause_reason = 'insufficient_balance'
                else:
                    campaign.status = (
                        AdvertisingCampaign.Status.SCHEDULED
                        if campaign.start_date > timezone.localdate()
                        else AdvertisingCampaign.Status.ACTIVE
                    )
                    campaign.pause_reason = ''
            elif action == 'reject':
                if not reason:
                    return Response({'detail': 'reason is required when rejecting a campaign.'}, status=status.HTTP_400_BAD_REQUEST)
                campaign.status = AdvertisingCampaign.Status.REJECTED
                campaign.rejection_reason = reason[:2000]
                campaign.reviewed_by = request.user
                campaign.reviewed_at = timezone.now()
                campaign.pause_reason = ''
            elif action == 'pause':
                if campaign.status not in (AdvertisingCampaign.Status.ACTIVE, AdvertisingCampaign.Status.SCHEDULED):
                    return Response({'detail': 'Only active or scheduled campaigns can be paused.'}, status=status.HTTP_409_CONFLICT)
                campaign.status = AdvertisingCampaign.Status.PAUSED
                campaign.pause_reason = reason[:120] or 'admin_paused'
            elif action == 'resume':
                if campaign.reviewed_at is None:
                    return Response({'detail': 'Approve the campaign before resuming it.'}, status=status.HTTP_409_CONFLICT)
                if campaign.status != AdvertisingCampaign.Status.PAUSED:
                    return Response({'detail': 'Only paused campaigns can be resumed.'}, status=status.HTTP_409_CONFLICT)
                if campaign.end_date < timezone.localdate():
                    campaign.status = AdvertisingCampaign.Status.COMPLETED
                    campaign.pause_reason = 'campaign_ended'
                elif campaign_spend(campaign) >= campaign.total_budget:
                    campaign.status = AdvertisingCampaign.Status.BUDGET_EXHAUSTED
                    campaign.pause_reason = 'total_budget_exhausted'
                elif daily_campaign_spend(campaign) + campaign.max_cpc > campaign.daily_budget:
                    return Response({'detail': 'Daily campaign budget is exhausted.'}, status=status.HTTP_409_CONFLICT)
                elif get_wallet(campaign.trader).balance <= ZERO:
                    return Response({'detail': 'Insufficient advertising wallet balance.'}, status=status.HTTP_409_CONFLICT)
                else:
                    for row in campaign.offers.all():
                        eligible, eligibility_reason = eligible_offer(row.trader_offer)
                        if not eligible:
                            return Response({'detail': eligibility_reason}, status=status.HTTP_409_CONFLICT)
                    campaign.status = (
                        AdvertisingCampaign.Status.SCHEDULED
                        if campaign.start_date > timezone.localdate()
                        else AdvertisingCampaign.Status.ACTIVE
                    )
                    campaign.pause_reason = ''
            else:
                if campaign.status in (AdvertisingCampaign.Status.COMPLETED, AdvertisingCampaign.Status.CANCELLED):
                    return Response({'detail': 'Campaign is already closed.'}, status=status.HTTP_409_CONFLICT)
                campaign.status = AdvertisingCampaign.Status.CANCELLED
                campaign.pause_reason = reason[:120] or 'admin_cancelled'
            campaign.save(update_fields=(
                'status', 'pause_reason', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at',
            ))
        return Response({
            'campaign': _campaign_collection(
                AdvertisingCampaign.objects.filter(pk=campaign.pk),
                admin=True,
            )[0],
        })


class AdminAdvertisingWalletAdjustmentsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        trader_uuid = request.data.get('trader_uuid')
        reason = str(request.data.get('reason') or '').strip()
        if not reason:
            return Response({'detail': 'reason is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = Decimal(str(request.data.get('amount'))).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'detail': 'amount must be a valid decimal amount.'}, status=status.HTTP_400_BAD_REQUEST)
        if not amount.is_finite() or amount == ZERO or abs(amount) > Decimal('999999999999.99'):
            return Response({'detail': 'amount must be a non-zero valid amount.'}, status=status.HTTP_400_BAD_REQUEST)
        trader = get_object_or_404(TraderApplication, uuid=trader_uuid)
        with transaction.atomic():
            wallet = get_wallet(trader, lock=True)
            idempotency_key = str(request.headers.get('Idempotency-Key') or '').strip()
            if not idempotency_key or len(idempotency_key) > 100:
                return Response({'detail': 'A valid Idempotency-Key header is required.'}, status=status.HTTP_400_BAD_REQUEST)
            existing = AdvertisingWalletTransaction.objects.filter(
                wallet=wallet,
                idempotency_key=idempotency_key,
            ).first()
            if existing:
                if (
                    existing.transaction_type != AdvertisingWalletTransaction.Type.ADJUSTMENT
                    or existing.amount != amount
                    or existing.reason != reason[:2000]
                ):
                    return Response({'detail': 'This Idempotency-Key was already used for a different transaction.'}, status=status.HTTP_409_CONFLICT)
                return Response({
                    'transaction': {
                        'id': existing.pk,
                        'kind': existing.transaction_type,
                        'amount': _money(existing.amount),
                        'balance_after': _money(existing.balance_after),
                        'reference': existing.reference,
                        'description': existing.reason,
                        'created_at': existing.created_at.isoformat(),
                    },
                    'wallet': {'balance': _money(wallet.balance), 'currency': wallet.currency},
                    'duplicate': True,
                })
            new_balance = wallet.balance + amount
            if new_balance < ZERO:
                return Response({'detail': 'Adjustment would make the wallet balance negative.'}, status=status.HTTP_409_CONFLICT)
            wallet.balance = new_balance
            wallet.save(update_fields=('balance', 'updated_at'))
            reference = f'ADJ-ADV-{secrets.token_hex(8).upper()}'
            ledger = AdvertisingWalletTransaction.objects.create(
                wallet=wallet,
                transaction_type=AdvertisingWalletTransaction.Type.ADJUSTMENT,
                amount=amount,
                balance_after=new_balance,
                reference=reference,
                idempotency_key=idempotency_key,
                reason=reason[:2000],
                created_by=request.user,
            )
        return Response({
            'transaction': {
                'id': ledger.pk,
                'kind': ledger.transaction_type,
                'amount': _money(ledger.amount),
                'balance_after': _money(ledger.balance_after),
                'reference': ledger.reference,
                'description': ledger.reason,
                'created_at': ledger.created_at.isoformat(),
            },
            'wallet': {'balance': _money(new_balance), 'currency': wallet.currency},
        }, status=status.HTTP_201_CREATED)


class AdminAdvertisingTransactionsView(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        transactions = AdvertisingWalletTransaction.objects.select_related(
            'wallet__trader',
        ).order_by('-created_at')[:100]
        return Response({
            'results': [
                {
                    'id': entry.pk,
                    'trader': {
                        'uuid': str(entry.wallet.trader.uuid),
                        'business_name': entry.wallet.trader.business_name,
                    },
                    'amount': _money(entry.amount),
                    'reference': entry.reference,
                    'kind': entry.transaction_type,
                    'created_at': entry.created_at.isoformat(),
                    'balance_after': _money(entry.balance_after),
                }
                for entry in transactions
            ],
        })
