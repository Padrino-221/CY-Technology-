from datetime import timedelta
from decimal import Decimal

from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.timezone import localdate

card_format = RegexValidator(r"^GHA-[0-9]{9}-[0-9]\Z", "Enter the PIN as GHA-123456789-0.", flags=2)
positive = MinValueValidator(Decimal("0.01"))
MIN_DEPOSIT = 70
MAX_TERM = 90
DUE_SOON_DAYS = 3
RECOVERY_GRACE_DAYS = 14


class BusinessSettings(models.Model):
    minimum_deposit = models.DecimalField(
        "Minimum deposit (%)", max_digits=5, decimal_places=2, default=MIN_DEPOSIT,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    maximum_term = models.PositiveSmallIntegerField(
        "Maximum repayment term (days)", default=MAX_TERM,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_TERM)],
    )
    rate_1_to_30 = models.DecimalField("Interest for 1–30 days (%)", max_digits=5, decimal_places=2,
                                      default=5, validators=[MinValueValidator(0), MaxValueValidator(100)])
    rate_31_to_60 = models.DecimalField("Interest for 31–60 days (%)", max_digits=5, decimal_places=2,
                                       default=10, validators=[MinValueValidator(0), MaxValueValidator(100)])
    rate_61_to_90 = models.DecimalField("Interest for 61–90 days (%)", max_digits=5, decimal_places=2,
                                       default=20, validators=[MinValueValidator(0), MaxValueValidator(100)])
    due_soon_days = models.PositiveSmallIntegerField(
        "Due-soon warning (days before due)", default=DUE_SOON_DAYS, validators=[MaxValueValidator(90)],
    )
    recovery_grace_days = models.PositiveSmallIntegerField(
        "Recovery grace period (days after final due)", default=RECOVERY_GRACE_DAYS, validators=[MaxValueValidator(365)],
    )

    @classmethod
    def current(cls):
        return cls.objects.filter(pk=1).first() or cls(pk=1)


def credit_rate(days, rules=None):
    rules = rules if rules is not None else BusinessSettings.current()
    percent = rules.rate_1_to_30 if days <= 30 else rules.rate_31_to_60 if days <= 60 else rules.rate_61_to_90
    return Decimal(percent) / 100


class Customer(models.Model):
    code = models.CharField(max_length=24, unique=True)
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=32)
    whatsapp = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    ghana_card = models.CharField("Ghana Card PIN", max_length=15, blank=True, validators=[card_format])
    nia_verified = models.BooleanField("Verified with NIA", default=False)
    institution = models.CharField(max_length=160, blank=True)
    programme = models.CharField(max_length=120, blank=True)
    student_id = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=240, blank=True)
    guarantor_name = models.CharField(max_length=160, blank=True)
    guarantor_phone = models.CharField(max_length=32, blank=True)
    guarantor_card = models.CharField("Guarantor Ghana Card PIN", max_length=15, blank=True, validators=[card_format])
    consent_signed = models.BooleanField(default=False)
    gender = models.CharField(max_length=12, choices=[("Male", "Male"), ("Female", "Female")], blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    study_level = models.CharField(max_length=40, blank=True)
    hall_hostel_room = models.CharField(max_length=160, blank=True)
    hometown = models.CharField(max_length=160, blank=True)
    sponsor_name = models.CharField(max_length=160, blank=True)
    sponsor_phone = models.CharField(max_length=32, blank=True)
    repayment_source = models.CharField(max_length=120, blank=True)
    guarantor_relationship = models.CharField(max_length=60, blank=True)
    guarantor_occupation = models.CharField(max_length=120, blank=True)
    guarantor_address = models.CharField(max_length=240, blank=True)
    next_of_kin_name = models.CharField(max_length=160, blank=True)
    next_of_kin_relationship = models.CharField(max_length=60, blank=True)
    next_of_kin_phone = models.CharField(max_length=32, blank=True)
    student_id_copy_taken = models.BooleanField(default=False)
    consent_date = models.DateField(null=True, blank=True)
    risk_rating = models.CharField(max_length=6, choices=[(rating, rating) for rating in ("Low", "Medium", "High")], blank=True)
    registered_by = models.CharField(max_length=160, blank=True)
    date_registered = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to="customers/", blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class Laptop(models.Model):
    code = models.CharField(max_length=24, unique=True)
    brand = models.CharField(max_length=60)
    model = models.CharField(max_length=80)
    serial = models.CharField(max_length=80, unique=True)
    processor = models.CharField(max_length=80, blank=True)
    ram = models.PositiveSmallIntegerField("RAM (GB)", null=True, blank=True)
    storage = models.CharField(max_length=80, blank=True)
    condition = models.CharField(max_length=80, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[positive])
    other_costs = models.DecimalField("Other costs (GHS)", max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    supplier = models.CharField(max_length=160, blank=True)
    warranty_months = models.PositiveSmallIntegerField(null=True, blank=True)
    date_received = models.DateField(null=True, blank=True)
    screen_inches = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    notes = models.TextField(blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField("Selling price (GHS)", max_digits=12, decimal_places=2, validators=[positive])

    needs_inspection = models.BooleanField(default=False, editable=False)

    @property
    def total_cost(self):
        return self.cost + self.other_costs

    def __str__(self):
        return f"{self.brand} {self.model} · {self.code}"


class LaptopPhoto(models.Model):
    laptop = models.ForeignKey(Laptop, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="laptops/")

    class Meta:
        ordering = ["pk"]


class Sale(models.Model):
    code = models.CharField(max_length=24, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    laptop = models.ForeignKey(Laptop, on_delete=models.PROTECT, related_name="sale_history")
    returned_on = models.DateField(null=True, blank=True, editable=False)
    return_reason = models.TextField(blank=True, editable=False)
    refund_due = models.DecimalField(max_digits=13, decimal_places=2, null=True, editable=False)

    @property
    def refunded(self):
        return sum((refund.amount for refund in self.refunds.all()), Decimal("0"))

    @property
    def refund_status(self):
        if self.refund_due is None:
            return "Not recorded"
        if not self.refund_due:
            return "No refund due"
        if self.refunded >= self.refund_due:
            return "Complete"
        return "Partial" if self.refunded else "Pending"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["laptop"], condition=models.Q(returned_on__isnull=True), name="one_active_sale_per_laptop"),
        ]
    date = models.DateField(default=localdate)
    cash_price = models.DecimalField(max_digits=12, decimal_places=2)
    deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=MIN_DEPOSIT, validators=[MinValueValidator(0), MaxValueValidator(100)])
    days = models.PositiveSmallIntegerField("Repayment days", default=30, validators=[MinValueValidator(1), MaxValueValidator(MAX_TERM)])
    frequency = models.PositiveSmallIntegerField(choices=[(7, "Weekly"), (14, "Bi-weekly"), (30, "Monthly"), (0, "Lump sum")], default=7)
    signed = models.BooleanField("Agreement signed", default=False)
    sales_officer = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    agreed_interest = models.DecimalField(max_digits=12, decimal_places=2, null=True, editable=False)
    agreed_cost = models.DecimalField(max_digits=13, decimal_places=2, null=True, editable=False)

    def save(self, *args, **kwargs):
        if self.agreed_interest is None:
            self.agreed_interest = (self.cash_price * credit_rate(self.days)).quantize(Decimal(".01"))
        if self.agreed_cost is None:
            self.agreed_cost = self.laptop.total_cost
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} · {self.customer}"

    @property
    def deposit(self):
        return (self.cash_price * self.deposit_percent / 100).quantize(Decimal(".01"))

    @property
    def interest(self):
        return self.agreed_interest

    @property
    def credit_price(self):
        return self.cash_price + self.interest

    @property
    def profit_agreed(self):
        return self.credit_price - self.agreed_cost

    @property
    def profit_percent(self):
        return self.profit_agreed * 100 / self.credit_price if self.credit_price else Decimal("0")

    @property
    def cash_collected(self):
        return self.deposit + self.repaid

    @property
    def cash_profit(self):
        return self.cash_collected - self.agreed_cost

    @property
    def financed(self):
        return self.cash_price - self.deposit + self.interest

    @property
    def repaid(self):
        return sum((p.amount for p in self.payments.all()), Decimal("0"))

    @property
    def balance(self):
        return Decimal("0") if self.returned_on else max(Decimal("0"), self.financed - self.repaid)

    @property
    def final_due(self):
        return self.date + timedelta(days=self.days)

    @property
    def installment(self):
        interval = self.frequency or self.days
        count = (self.days + interval - 1) // interval
        return (self.financed / count).quantize(Decimal(".01"))

    @property
    def next_due(self):
        installment = self.installment
        if not installment:
            return self.final_due
        interval = self.frequency or self.days
        return self.date + timedelta(days=min(self.days, interval * (int(self.repaid / installment) + 1)))

    @cached_property
    def follow_up_rules(self):
        if hasattr(self, "_due_soon_days"):
            return self._due_soon_days, self._recovery_grace_days
        rules = BusinessSettings.current()
        return rules.due_soon_days, rules.recovery_grace_days

    @property
    def status(self):
        if self.returned_on:
            return "Returned"
        today = localdate()
        if not self.balance:
            return "Paid in full"
        due_soon_days, recovery_grace_days = self.follow_up_rules
        if today > self.final_due + timedelta(days=recovery_grace_days):
            return "Recovery"
        if today > self.final_due:
            return "Overdue"
        if today > self.next_due:
            return "Behind schedule"
        if (self.next_due - today).days <= due_soon_days:
            return "Due soon"
        return "On track"


class Refund(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=13, decimal_places=2, validators=[positive])
    reference = models.CharField(max_length=160)
    date = models.DateField(default=localdate, editable=False)


class Payment(models.Model):
    code = models.CharField(max_length=24, unique=True)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="payments")
    date = models.DateField(default=localdate)
    time = models.TimeField("Payment time", null=True, blank=True)
    amount = models.DecimalField("Amount (GHS)", max_digits=12, decimal_places=2, validators=[positive])
    method = models.CharField(max_length=32, choices=[(m, m) for m in ("MTN MoMo", "Telecel Cash", "AT Money", "Cash", "Bank transfer", "Cheque")])
    reference = models.CharField(max_length=80, blank=True)
    received_by = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.code


class OfflineRevision(models.Model):
    version = models.PositiveBigIntegerField(default=0)


class OfflineReceipt(models.Model):
    id = models.UUIDField(primary_key=True)
    user_id = models.PositiveBigIntegerField()
    version = models.PositiveBigIntegerField()
