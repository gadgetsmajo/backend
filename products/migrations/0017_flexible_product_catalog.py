import cloudinary.models
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0016_link_renamed_trader_products'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='children',
                to='products.category',
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='brand',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='product',
            name='condition',
            field=models.CharField(
                choices=[('new', 'New'), ('used', 'Used'), ('refurbished', 'Refurbished')],
                default='new',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='tags',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='product',
            name='specifications',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='product',
            name='review_status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('pending_review', 'Pending review'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                    ('changes_required', 'Changes required'),
                    ('disabled', 'Disabled'),
                    ('archived', 'Archived'),
                ],
                default='approved',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='review_note',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.CreateModel(
            name='CategoryAttribute',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('key', models.SlugField(max_length=100)),
                ('input_type', models.CharField(
                    choices=[
                        ('text', 'Text'),
                        ('number', 'Number'),
                        ('dropdown', 'Dropdown'),
                        ('multi_select', 'Multi-select'),
                        ('boolean', 'Boolean'),
                        ('measurement', 'Measurement'),
                        ('color', 'Color'),
                        ('size', 'Size'),
                    ],
                    default='text',
                    max_length=20,
                )),
                ('choices', models.JSONField(blank=True, default=list)),
                ('is_required', models.BooleanField(default=False)),
                ('is_variant', models.BooleanField(default=False)),
                ('is_filterable', models.BooleanField(default=False)),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('category', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attributes',
                    to='products.category',
                )),
            ],
            options={
                'ordering': ('position', 'name'),
                'constraints': [
                    models.UniqueConstraint(fields=('category', 'key'), name='unique_category_attribute_key'),
                ],
            },
        ),
        migrations.CreateModel(
            name='ProductVariant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sku', models.CharField(blank=True, default='', max_length=100)),
                ('options', models.JSONField(default=dict)),
                ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('compare_at_price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('stock', models.PositiveIntegerField(default=0)),
                ('weight', models.DecimalField(blank=True, decimal_places=3, max_digits=8, null=True)),
                ('image', cloudinary.models.CloudinaryField(blank=True, folder='product_variants/', max_length=255, null=True, verbose_name='image')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='variants',
                    to='products.product',
                )),
            ],
            options={
                'ordering': ('id',),
                'constraints': [
                    models.UniqueConstraint(
                        condition=~Q(sku=''),
                        fields=('sku',),
                        name='unique_nonempty_product_variant_sku',
                    ),
                ],
            },
        ),
    ]
