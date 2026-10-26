from django.core.management.base import BaseCommand
from settings_app.models import District

DISTRICTS = {
    'Central Region': [
        'Buikwe', 'Bukomansimbi', 'Butebo', 'Buvuma', 'Buyende',
        'Gomba', 'Kalangala', 'Kalungu', 'Kampala', 'Kayunga',
        'Kiboga', 'Kyankwanzi', 'Luwero', 'Lwengo', 'Lyantonde',
        'Masaka', 'Mityana', 'Mpigi', 'Mubende', 'Mukono',
        'Nakaseke', 'Nakasongola', 'Rakai', 'Sembabule', 'Wakiso',
    ],
    'Eastern Region': [
        'Amuria', 'Budaka', 'Bududa', 'Bugiri', 'Bugweri',
        'Bukedea', 'Bukwa', 'Bulambuli', 'Busia', 'Butaleja',
        'Butebo', 'Buyende', 'Iganga', 'Jinja', 'Kaberamaido',
        'Kaliro', 'Kamuli', 'Kapchorwa', 'Kapelebyong', 'Katakwi',
        'Kibuku', 'Kumi', 'Kween', 'Luuka', 'Manafwa',
        'Mayuge', 'Mbale', 'Namayingo', 'Namisindwa', 'Namutumba',
        'Ngora', 'Pallisa', 'Serere', 'Sironko', 'Soroti',
        'Tororo',
    ],
    'Northern Region': [
        'Abim', 'Adjumani', 'Agago', 'Alebtong', 'Amolatar',
        'Amudat', 'Amuru', 'Apac', 'Arua', 'Dokolo',
        'Gulu', 'Kaabong', 'Kitgum', 'Koboko', 'Kole',
        'Kotido', 'Kwania', 'Kween', 'Lamwo', 'Lira',
        'Madi-Okollo', 'Maracha', 'Moroto', 'Moyo', 'Nakapiripirit',
        'Napak', 'Nebbi', 'Nwoya', 'Obongi', 'Omoro',
        'Otuke', 'Oyam', 'Pader', 'Pakwach', 'Terego',
        'Yumbe', 'Zombo',
    ],
    'Western Region': [
        'Buhweju', 'Buliisa', 'Bundibugyo', 'Bushenyi', 'Butebo',
        'Hoima', 'Ibanda', 'Isingiro', 'Kabale', 'Kabarole',
        'Kagadi', 'Kakumiro', 'Kamwenge', 'Kanungu', 'Kasese',
        'Katwe-Butebo', 'Kibaale', 'Kikuube', 'Kiruhura', 'Kiryandongo',
        'Kisoro', 'Kyegegwa', 'Kyenjojo', 'Masindi', 'Mbarara',
        'Mitooma', 'Ntoroko', 'Ntungamo', 'Rubanda', 'Rubirizi',
        'Rukiga', 'Rukungiri', 'Rwampara', 'Sheema',
    ],
}


class Command(BaseCommand):
    help = 'Seed Uganda districts into the database'

    def handle(self, *args, **options):
        created = 0
        for region, names in DISTRICTS.items():
            for name in names:
                _, was_created = District.objects.get_or_create(
                    name=name,
                    defaults={'region': region, 'price': 0},
                )
                if was_created:
                    created += 1
        self.stdout.write(self.style.SUCCESS(f'Done. {created} districts added.'))
