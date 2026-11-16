from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.timezone import localdate
from PIL import Image

from .models import BusinessSettings, Customer, Laptop, Payment, Sale, credit_rate


class CreditWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("frontdesk-test", password="local-test-password")
        self.client.force_login(self.user)
        self.today = localdate()
        self.customer = Customer.objects.create(code="TEST-C", full_name="Example Customer", phone="0000000000")
        self.laptop = Laptop.objects.create(
            code="TEST-L", brand="Example", model="Laptop", serial="TEST-SERIAL",
            cost=Decimal("2100"), other_costs=Decimal("100"), price=Decimal("4000"),
        )

    def create_sale(self, **overrides):
        data = {
            "code": "TEST-S", "customer": self.customer.pk, "laptop": self.laptop.pk,
            "date": self.today, "deposit_percent": "70", "days": "30", "frequency": "7",
        }
        return self.client.post(reverse("new", args=["sales"]), data | overrides)

    def test_sale_boundaries_and_stock(self):
        for term, expected in ((1, ".05"), (30, ".05"), (31, ".10"), (60, ".10"), (61, ".20"), (90, ".20")):
            self.assertEqual(credit_rate(term), Decimal(expected))
        for overrides in ({"days": "0"}, {"days": "91"}, {"deposit_percent": "69.99"},
                          {"deposit_percent": "100.01"}, {"date": self.today + timedelta(days=1)}):
            self.assertEqual(self.create_sale(**overrides).status_code, 200)
        self.assertFalse(Sale.objects.exists())
        self.assertEqual(self.create_sale().status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual((sale.deposit, sale.interest, sale.financed, sale.profit_agreed),
                         tuple(map(Decimal, ("2800", "200", "1400", "2000"))))
        self.assertEqual(self.create_sale(code="SECOND").status_code, 200)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertNotContains(self.client.get("/inventory/?stock=1"), self.laptop.serial)
        self.laptop.price = Decimal("5000")
        self.laptop.cost = Decimal("3000")
        self.laptop.save()
        sale.refresh_from_db()
        self.assertEqual((sale.cash_price, sale.agreed_cost), (Decimal("4000"), Decimal("2200")))

    def test_repayments_updates_and_delete_protection(self):
        self.assertEqual(self.create_sale().status_code, 302)
        sale = Sale.objects.get()
        url = reverse("new", args=["payments"])
        data = {"sale": sale.pk, "date": self.today, "amount": "500", "method": "Cash", "time": "14:30"}
        for date in (self.today - timedelta(days=1), self.today + timedelta(days=1)):
            self.assertContains(self.client.post(url, data | {"code": "BAD", "date": date}), "from the sale date through today")
        self.assertEqual(self.client.post(url, data | {"code": "TEST-P"}).status_code, 302)
        payment = Payment.objects.get()
        self.assertEqual(payment.time.hour, 14)
        payment_url = reverse("edit", args=["payments", payment.pk])
        self.assertEqual(self.client.post(payment_url, data | {"code": payment.code, "amount": "1400"}).status_code, 302)
        self.assertEqual(sale.status, "Paid in full")
        self.assertContains(self.client.post(url, data | {"code": "SECOND"}), "exceeds the outstanding balance")
        edit = reverse("change", args=["sales", sale.pk])
        self.assertEqual(self.client.post(edit, {"code": sale.code, "days": 90, "notes": "Updated"}).status_code, 302)
        sale.refresh_from_db()
        self.assertEqual((sale.days, sale.notes), (30, "Updated"))
        for section, record in (("customers", self.customer), ("inventory", self.laptop), ("sales", sale)):
            url = reverse("delete", args=[section, record.pk])
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertContains(self.client.post(url, follow=True), "linked to other records")
            self.assertTrue(type(record).objects.filter(pk=record.pk).exists())
        self.client.post(reverse("delete", args=["payments", payment.pk]))
        self.assertEqual(sale.balance, Decimal("1400"))
        self.client.post(reverse("delete", args=["sales", sale.pk]))
        self.assertContains(self.client.get("/inventory/?stock=1"), self.laptop.serial)

    def test_offline_replay_deduplication_and_conflict(self):
        from uuid import uuid4

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.get("/offline-session/").json()
        page = csrf_client.get("/inventory/new/")
        self.assertEqual(page["X-CY-Offline-Page"], session["user"])
        headers = {
            "X-CSRFToken": session["csrf"], "X-CY-User": session["user"],
            "X-CY-Operation": str(uuid4()), "X-CY-Revision": "0",
        }
        data = {
            "code": "OFFLINE-L", "serial": "OFFLINE-SERIAL", "brand": "Example", "model": "Laptop",
            "cost": "100", "other_costs": "0", "price": "200",
        }
        first = csrf_client.post("/inventory/new/", data, headers=headers)
        self.assertEqual(first.status_code, 200)
        retry = csrf_client.post("/inventory/new/", data, headers=headers)
        self.assertEqual(retry.json()["revision"], first.json()["revision"])
        stale = csrf_client.post("/inventory/new/", data, headers=headers | {"X-CY-Operation": str(uuid4())})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(Laptop.objects.filter(code="OFFLINE-L").count(), 1)

    def test_add_multiple_laptop_units(self):
        details = {
            "code": "BATCH", "brand": "Example", "model": "Laptop", "serial": "UNIT-1",
            "cost": "2000", "other_costs": "0", "price": "4000", "quantity": 3,
        }
        url = reverse("new", args=["inventory"])
        self.assertContains(self.client.post(url, details | {"extra_serials": "UNIT-2"}), "Enter 2 additional")
        self.assertContains(self.client.post(url, details | {"extra_serials": "UNIT-2\nTEST-SERIAL"}), "already in inventory")
        self.assertFalse(Laptop.objects.filter(code__startswith="BATCH").exists())
        self.assertRedirects(self.client.post(url, details | {"extra_serials": "UNIT-2\nUNIT-3"}), "/inventory/")
        units = Laptop.objects.filter(code__startswith="BATCH").order_by("code")
        self.assertEqual(list(units.values_list("code", "serial")), [
            ("BATCH", "UNIT-1"), ("BATCH-2", "UNIT-2"), ("BATCH-3", "UNIT-3"),
        ])
        self.assertEqual(self.create_sale(laptop=units[1].pk).status_code, 302)
        stock = self.client.get("/inventory/?stock=1")
        self.assertContains(stock, "UNIT-1")
        self.assertNotContains(stock, "UNIT-2")
        self.assertContains(stock, "UNIT-3")

    def test_add_units_when_editing_laptop(self):
        self.laptop.needs_inspection = True
        self.laptop.save()
        Laptop.objects.create(code="TEST-L-2", serial="EXISTING", brand="Example", model="Laptop", cost=2000, price=4000)
        url = reverse("change", args=["inventory", self.laptop.pk])
        details = {
            "code": self.laptop.code, "brand": "Example", "model": "Updated", "serial": self.laptop.serial,
            "cost": "2000", "other_costs": "0", "price": "4000", "quantity": 2, "extra_serials": "NEW-UNIT",
        }
        self.assertRedirects(self.client.post(url, details), "/inventory/")
        unit = Laptop.objects.get(serial="NEW-UNIT")
        self.assertEqual((unit.code, unit.model, unit.needs_inspection), ("TEST-L-3", "Updated", False))
        self.laptop.refresh_from_db()
        self.assertTrue(self.laptop.needs_inspection)

    def test_laptop_crud_and_return_for_resale(self):
        details = {
            "code": "CRUD-L", "brand": "Example", "model": "New model", "serial": "CRUD-SERIAL",
            "cost": "2000", "other_costs": "0", "price": "4000",
        }
        self.assertEqual(self.client.post("/inventory/new/", details).status_code, 302)
        laptop = Laptop.objects.get(code="CRUD-L")
        self.assertContains(self.client.get(f"/inventory/{laptop.pk}/"), "New model")
        self.assertEqual(self.client.post(f"/inventory/{laptop.pk}/edit/", details | {"model": "Updated model"}).status_code, 302)
        laptop.refresh_from_db()
        self.assertEqual(laptop.model, "Updated model")
        self.assertEqual(self.client.post(f"/inventory/{laptop.pk}/delete/").status_code, 302)
        self.assertFalse(Laptop.objects.filter(pk=laptop.pk).exists())

        self.assertEqual(self.create_sale().status_code, 302)
        sale = Sale.objects.get()
        payment = Payment.objects.create(code="RETURN-P", sale=sale, amount=100, method="Cash")
        url = reverse("return-laptop", args=[sale.pk])
        self.assertContains(self.client.get(url), "Confirm return")
        self.assertEqual(self.client.post(url, {"reason": "Customer returned the laptop", "disposition": "inspection", "refund_due": "200"}).status_code, 302)
        sale.refresh_from_db()
        self.assertEqual((sale.status, sale.balance, sale.repaid), ("Returned", 0, 100))
        self.assertNotContains(self.client.get("/inventory/?stock=1"), self.laptop.serial)
        self.assertContains(self.client.get("/sales/new/"), "No laptops available")
        self.assertContains(self.client.get(f"/payments/{payment.pk}/"), "Returned agreement")
        self.assertContains(self.client.get(f"/sales/{sale.pk}/"), "Pending")
        refund = reverse("record-refund", args=[sale.pk])
        self.assertContains(self.client.post(refund, {"amount": "201", "reference": "too much"}), "exceeds")
        self.assertEqual(self.client.post(refund, {"amount": "50", "reference": "R1"}).status_code, 302)
        self.assertEqual(sale.refund_status, "Partial")
        self.assertEqual(self.client.post(refund, {"amount": "150", "reference": "R2"}).status_code, 302)
        self.assertEqual(sale.refund_status, "Complete")
        self.assertContains(self.client.get("/"), "Returned sales and refunds")
        self.client.post(reverse("release-laptop", args=[self.laptop.pk]))
        self.assertContains(self.client.get("/inventory/?stock=1"), self.laptop.serial)
        self.assertNotContains(self.client.get("/profit/"), sale.code)
        self.client.post(f"/payments/{payment.pk}/delete/")
        self.assertTrue(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(self.create_sale(code="RESALE").status_code, 302)
        self.client.post(url, {"reason": "Repeated submission"})
        self.assertNotContains(self.client.get("/inventory/?stock=1"), self.laptop.serial)
        self.assertEqual(self.laptop.sale_history.count(), 2)

    def test_follow_up_boundary_and_reports(self):
        self.create_sale(date=self.today - timedelta(days=44))
        sale = Sale.objects.get()
        self.assertEqual(sale.status, "Overdue")
        sale.date -= timedelta(days=1)
        sale.save()
        self.assertEqual(sale.status, "Recovery")
        self.assertContains(self.client.get("/follow-up/"), "TEST-S")
        for url in ("/", "/reports/", "/profit/", f"/sales/{sale.pk}/", f"/customers/{self.customer.pk}/"):
            self.assertContains(self.client.get(url), "1,400.00" if url not in ("/profit/",) else "2,000.00")

    def test_customer_registration_profile_photo_and_search(self):
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            form = self.client.get("/customers/new/")
            self.assertEqual(form.content.count(b"data-step"), 4)
            self.assertNotContains(form, "Verified with NIA")
            data = {"code": "TEST-PHOTO", "full_name": "Fictional Person", "phone": "0000000001",
                    "institution": "Demo College", "next_of_kin_name": "Example Contact"}
            self.assertContains(self.client.post("/customers/new/", data | {"ghana_card": "incorrect"}), "Enter the PIN as")
            image = BytesIO()
            Image.new("RGB", (2, 2)).save(image, format="PNG")
            # Reject an image with an unsafe extension.
            photo = SimpleUploadedFile("photo.html", image.getvalue(), content_type="image/png")
            rejected = self.client.post("/customers/new/", data | {"photo": photo})
            self.assertEqual(rejected.status_code, 200)
            self.assertFalse(Customer.objects.filter(code=data["code"]).exists())
            photo = SimpleUploadedFile("photo.png", image.getvalue(), content_type="image/png")
            saved = self.client.post("/customers/new/", data | {"ghana_card": "GHA-123456789-0", "photo": photo})
            self.assertEqual(saved.status_code, 302)
            customer = Customer.objects.get(code=data["code"])
            profile = reverse("edit", args=["customers", customer.pk])
            self.assertContains(self.client.get(profile), "Example Contact")
            self.assertEqual(self.client.post(profile, data).status_code, 405)
            self.assertContains(self.client.get(reverse("change", args=["customers", customer.pk])), "Save customer")
            url = reverse("photo", args=[customer.pk])
            self.assertEqual(Client().get(url).status_code, 302)
            response = self.client.get(url)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            response.close()
            self.assertContains(self.client.get("/search/", {"q": "fictional college"}), "Fictional Person")
            self.assertContains(self.client.get("/search/", {"q": "not-a-match"}), "No matching records")

    def test_login_logout_and_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.get("/reports/").status_code, 302)
        self.assertEqual(browser.get("/login/").status_code, 200)
        token = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post("/login/", {
            "username": self.user.username, "password": "local-test-password", "csrfmiddlewaretoken": token,
        }).status_code, 302)
        self.assertEqual(browser.get("/").status_code, 200)
        self.assertEqual(browser.post("/logout/").status_code, 403)
        token = browser.cookies["csrftoken"].value
        self.assertEqual(browser.post("/logout/", {"csrfmiddlewaretoken": token}).status_code, 302)
        self.assertEqual(browser.get("/").status_code, 302)


    def test_business_settings_apply_without_repricing_existing_sales(self):
        self.assertEqual(self.create_sale(date=self.today - timedelta(days=35)).status_code, 302)
        existing = Sale.objects.get()
        url = reverse("business-settings")
        data = {
            "minimum_deposit": "60", "maximum_term": "45", "rate_1_to_30": "7.50",
            "rate_31_to_60": "12", "rate_61_to_90": "22", "due_soon_days": "5",
            "recovery_grace_days": "3",
        }
        self.assertEqual(Client().post(url, data).status_code, 302)
        self.assertContains(self.client.post(url, data | {"rate_1_to_30": "-1"}), "greater than or equal to")
        self.assertFalse(BusinessSettings.objects.exists())
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(BusinessSettings.current().minimum_deposit, Decimal("60"))
        self.assertEqual(existing.interest, Decimal("200"))
        self.assertEqual(existing.status, "Recovery")
        self.assertContains(self.client.get("/follow-up/"), "Recovery")

        laptop = Laptop.objects.create(
            code="NEW-L", brand="Example", model="Laptop", serial="NEW-SERIAL", cost=1000, price=4000,
        )
        sale = {"code": "NEW-S", "laptop": laptop.pk, "deposit_percent": "60", "days": "30"}
        self.assertContains(self.create_sale(**(sale | {"days": "46"})), "maximum repayment term is 45 days")
        self.assertContains(self.create_sale(**(sale | {"deposit_percent": "59"})), "minimum deposit is 60")
        self.assertEqual(self.create_sale(**sale).status_code, 302)
        self.assertEqual(Sale.objects.get(code="NEW-S").interest, Decimal("300"))

    def test_laptop_product_page_and_gallery(self):
        with TemporaryDirectory() as media, self.settings(MEDIA_ROOT=media):
            image = BytesIO()
            Image.new("RGB", (3, 3)).save(image, format="PNG")
            files = [SimpleUploadedFile(name, image.getvalue(), content_type="image/png")
                     for name in ("front.png", "side.png")]
            data = {
                "code": "PRODUCT-1", "brand": "Example", "model": "Product",
                "serial": "PRODUCT-SERIAL", "cost": "2000", "other_costs": "0", "price": "4000",
                "description": "A compact laptop for everyday work.", "gallery_uploads": files,
            }
            self.assertEqual(self.client.post("/inventory/new/", data).status_code, 302)
            laptop = Laptop.objects.get(code=data["code"])
            url = reverse("edit", args=["inventory", laptop.pk])
            self.assertContains(self.client.get(url), data["description"])
            self.assertContains(self.client.get(url), "data-gallery-photo", count=2)
            self.assertNotContains(self.client.get(url), "Save laptop")
            self.assertEqual(self.client.post(url, {}).status_code, 405)
            first = laptop.photos.first()
            photo_url = reverse("laptop-photo", args=[first.pk])
            self.assertEqual(Client().get(photo_url).status_code, 302)
            response = self.client.get(photo_url)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            response.close()
            edit = reverse("change", args=["inventory", laptop.pk])
            self.assertContains(self.client.get(edit), "Save laptop")
            data.pop("gallery_uploads")
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(edit, data | {"remove_photos": [first.pk]}).status_code, 302)
            self.assertEqual(laptop.photos.count(), 1)
            self.assertFalse(first.image.storage.exists(first.image.name))
