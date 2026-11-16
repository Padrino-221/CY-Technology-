from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import localdate

from credit.models import Customer, Laptop, Payment, Sale


class Command(BaseCommand):
    help = "Populate a local workspace with fictional demo records."

    @transaction.atomic
    def handle(self, *args, **options):
        today = localdate()
        names = ["Ama Mensah", "Kojo Owusu", "Akosua Boateng", "Kwame Asare", "Esi Ofori", "Kofi Antwi"]
        ages = [0, 2, 4, 6, 12, 40]
        for index, (name, age) in enumerate(zip(names, ages), 1):
            customer, _ = Customer.objects.get_or_create(code=f"DEMO-C{index:02}", defaults={
                "full_name": name, "phone": f"00000000{index:02}", "institution": "Demo institution",
            })
            laptop, _ = Laptop.objects.get_or_create(code=f"DEMO-L{index:02}", defaults={
                "brand": "Lenovo", "model": "ThinkPad T480", "serial": f"DEMO-SERIAL-{index:02}",
                "cost": Decimal("2400"), "price": Decimal("3800"),
            })
            sale, _ = Sale.objects.get_or_create(code=f"DEMO-S{index:02}", defaults={
                "customer": customer, "laptop": laptop, "cash_price": laptop.price,
                "date": today - timedelta(days=age),
            })
            if index in {2, 4}:
                Payment.objects.get_or_create(code=f"DEMO-P{index:02}", defaults={
                    "sale": sale, "amount": sale.financed, "method": "Cash", "date": today,
                })
        for index in range(7, 11):
            Laptop.objects.get_or_create(code=f"DEMO-L{index:02}", defaults={
                "brand": "Dell", "model": "Latitude 5400", "serial": f"DEMO-SERIAL-{index:02}",
                "cost": Decimal("2000"), "price": Decimal("3300"),
            })
        self.stdout.write(self.style.SUCCESS("Fictional demo records are ready."))
