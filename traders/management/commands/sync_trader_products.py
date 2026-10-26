from django.core.management.base import BaseCommand
from traders.models import TraderProduct


class Command(BaseCommand):
    help = 'Backfill public Product records for all existing TraderProducts'

    def handle(self, *args, **kwargs):
        from traders.views import _sync_to_product
        qs = TraderProduct.objects.select_related('trader', 'category').all()
        created = updated = 0
        for tp in qs:
            from products.models import Product
            exists = Product.objects.filter(trader_product=tp).exists()
            _sync_to_product(tp)
            if exists:
                updated += 1
            else:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Done: {created} created, {updated} updated'))
