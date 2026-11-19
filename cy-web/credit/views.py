from collections import Counter, defaultdict
from contextlib import nullcontext
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q, Sum, Value
from django.db.models.deletion import ProtectedError
from django.views.decorators.http import require_http_methods
from django.http import FileResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.timezone import localdate
from PIL import Image, ImageOps

from .models import BusinessSettings, Customer, Laptop, LaptopPhoto, Payment, Refund, Sale

SECTIONS = {
    "customers": (Customer, "Customers", "customer", ("code", "full_name", "phone", "whatsapp", "email", "institution")),
    "inventory": (Laptop, "Laptop inventory", "laptop", ("code", "brand", "model", "serial")),
    "sales": (Sale, "Credit sales", "sale", ("code", "customer__full_name", "laptop__code")),
    "payments": (Payment, "Repayments", "payment", ("code", "sale__code", "sale__customer__full_name", "reference", "method")),
    "profit": (Sale, "Cost and profit", "sale", ("code", "customer__full_name", "laptop__code")),
    "follow-up": (Sale, "Follow-up", "sale", ("code", "customer__full_name", "customer__phone")),
}
FOLLOW_UP = {"Due soon", "Behind schedule", "Overdue", "Recovery"}
PHOTO_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "BMP": "image/bmp", "WEBP": "image/webp"}
SEARCH_LIMIT = 160


def search_text(request):
    return request.GET.get("q", "")[:SEARCH_LIMIT].strip()


def paginate(request, rows, parameter="page"):
    page = Paginator(rows, 10).get_page(request.GET.get(parameter))
    query = request.GET.copy()
    if page.has_previous():
        query[parameter] = page.previous_page_number()
        page.previous_url = "?" + query.urlencode()
    if page.has_next():
        query[parameter] = page.next_page_number()
        page.next_url = "?" + query.urlencode()
    links = []
    for number in range(max(1, page.number - 2), min(page.paginator.num_pages, page.number + 2) + 1):
        query[parameter] = number
        links.append((number, "?" + query.urlencode()))
    page.numbered_links = links
    query[parameter] = 1
    page.first_url = "?" + query.urlencode()
    query[parameter] = page.paginator.num_pages
    page.last_url = "?" + query.urlencode()
    return page


def report_totals(agreements, group_key):
    totals = defaultdict(lambda: [0, 0, 0])
    for sale in agreements:
        row = totals[group_key(sale)]
        row[0] += 1
        row[1] += sale.cash_price
        row[2] += sale.balance
    return sorted(totals.items(), key=lambda item: (-item[1][2], str(item[0]), getattr(item[0], "pk", 0)))


def active_sales():
    return Sale.objects.filter(returned_on__isnull=True)


def stock():
    return Laptop.objects.annotate(sold=Exists(active_sales().filter(laptop_id=OuterRef("pk"))))


def sales():
    rules = BusinessSettings.current()
    return Sale.objects.select_related("customer", "laptop").prefetch_related("payments").annotate(
        _due_soon_days=Value(rules.due_soon_days),
        _recovery_grace_days=Value(rules.recovery_grace_days),
    ).order_by("-date", "-pk")


class AccountPasswordChangeView(PasswordChangeView):
    template_name = "password_change.html"
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Password changed.")
        return response


@login_required
def dashboard(request):
    agreements = list(sales().filter(returned_on__isnull=True))
    returned = list(sales().filter(returned_on__isnull=False).prefetch_related("refunds"))
    today = localdate()
    counts = Counter(sale.date for sale in agreements)
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    maximum = max(1, *(counts[day] for day in days))
    followups = sorted((sale for sale in agreements if sale.status in FOLLOW_UP), key=lambda sale: (sale.next_due, sale.pk))
    paid = sum(sale.status == "Paid in full" for sale in agreements)
    return render(request, "dashboard.html", {
        "profit_summary": profit_summary(agreements),
        "section": "dashboard", "agreements": agreements[:5], "followups": followups[:4],
        "outstanding": sum(sale.balance for sale in agreements),
        "profit_agreed": sum(sale.profit_agreed for sale in agreements),
        "cash_profit": sum(sale.cash_profit for sale in agreements),
        "cost_total": sum(sale.agreed_cost for sale in agreements),
        "cost_unrecovered": sum(sale.cash_profit < 0 for sale in agreements),
        "stock": stock().filter(sold=False, needs_inspection=False).count(),
        "returned_deposits": sum(sale.deposit for sale in returned),
        "returned_repayments": sum(sale.repaid for sale in returned),
        "refunds_paid": sum(sale.refunded for sale in returned),
        "refunds_pending": sum((sale.refund_due or 0) - sale.refunded for sale in returned),
        "total": len(agreements), "due": len(followups),
        "cash_value": sum(sale.cash_price for sale in agreements),
        "deposits": sum(sale.deposit for sale in agreements),
        "repayments": sum(sale.repaid for sale in agreements),
        "interest": sum(sale.interest for sale in agreements),
        "progress": round(100 * paid / len(agreements)) if agreements else 0,
        "bars": [(day.strftime("%a"), counts[day], round(100 * counts[day] / maximum)) for day in days],
        "today": today,
    })


def profit_summary(agreements):
    active = [sale for sale in agreements if not sale.returned_on]
    return {
        "expected": sum(sale.profit_agreed for sale in active),
        "collected": sum(sale.cash_profit for sale in active),
        "outstanding": sum(sale.balance for sale in active),
        "open_accounts": sum(bool(sale.balance) for sale in active),
    }


def section_info(section):
    if section not in SECTIONS:
        raise Http404
    return SECTIONS[section]


def matching(rows, fields, query):
    for term in query.split():
        criteria = Q()
        for field in fields:
            criteria |= Q(**{field + "__icontains": term})
        rows = rows.filter(criteria)
    return rows


@login_required
def search(request):
    query = search_text(request)
    groups = []
    if query:
        for section in ("customers", "inventory", "sales", "payments"):
            model, title, _, fields = SECTIONS[section]
            rows = matching(model.objects.order_by("-pk"), fields, query)
            if model is Payment:
                rows = rows.select_related("sale__customer")
            elif model is Sale:
                rows = rows.select_related("customer")
            groups.append((section, title, list(rows[:5]), rows.count()))
    return render(request, "search.html", {
        "title": "Search", "query": query, "groups": groups,
        "total": sum(group[3] for group in groups),
    })


@login_required
def records(request, section):
    model, title, singular, search_fields = section_info(section)
    rows = sales() if model is Sale else model.objects.order_by("-pk")
    summary = profit_summary(rows) if section == "profit" else None
    stock_only = section == "inventory" and request.GET.get("stock") == "1"
    if model is Laptop:
        rows = stock().order_by("-pk")
        if stock_only:
            rows = rows.filter(sold=False, needs_inspection=False)
    if model is Payment:
        rows = rows.select_related("sale").order_by("-date", "-time", "-pk")
    query = search_text(request)
    rows = matching(rows, search_fields, query)
    if section == "profit":
        rows = rows.filter(returned_on__isnull=True)
    if section == "follow-up":
        rows = sorted((sale for sale in rows if sale.status in FOLLOW_UP), key=lambda sale: (sale.next_due, sale.pk))
    print_view = section == "follow-up" and request.GET.get("print") == "1"
    return render(request, "records.html", {
        "profit_summary": summary,
        "section": section, "title": title, "singular": singular, "rows": rows if print_view else paginate(request, rows), "print_view": print_view, "query": query, "stock_only": stock_only,
    })


@login_required
def reports(request):
    agreements = list(sales().filter(returned_on__isnull=True))
    return render(request, "reports.html", {
        "title": "Reports", "section": "reports", "profit_summary": profit_summary(agreements),
        "balances": paginate(request, report_totals(agreements, lambda sale: sale.customer), "balances_page"),
        "statuses": paginate(request, report_totals(agreements, lambda sale: sale.status), "statuses_page"),
        "institutions": paginate(request, report_totals(agreements, lambda sale: sale.customer.institution.strip() or "Not recorded"), "institutions_page"),
    })


class BusinessSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = [
            "minimum_deposit", "maximum_term", "rate_1_to_30", "rate_31_to_60", "rate_61_to_90",
            "due_soon_days", "recovery_grace_days",
        ]


@login_required
@require_http_methods(["GET", "POST"])
def business_settings(request):
    form = BusinessSettingsForm(
        request.POST if request.method == "POST" else None,
        instance=BusinessSettings.current(),
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Business settings saved.")
        return redirect("business-settings")
    return render(request, "business_settings.html", {"title": "Business settings", "form": form})


class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        exclude = ["cash_price"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rules = BusinessSettings.current()
        if not self.instance.pk:
            self.initial.update(deposit_percent=self.rules.minimum_deposit, days=min(30, self.rules.maximum_term))
        available = Q(sold=False, needs_inspection=False)
        if self.instance.pk:
            available |= Q(pk=self.instance.laptop_id)
        self.fields["laptop"].queryset = stock().filter(available)
        if self.instance.pk and self.instance.payments.exists():
            for field in ("customer", "laptop", "date", "deposit_percent", "days", "frequency"):
                self.fields[field].disabled = True

    def clean(self):
        cleaned = super().clean()
        recheck = not self.instance.pk or "laptop" in self.changed_data
        deposit = cleaned.get("deposit_percent")
        if deposit is not None and (recheck or "deposit_percent" in self.changed_data):
            if deposit < self.rules.minimum_deposit:
                self.add_error("deposit_percent", f"The minimum deposit is {self.rules.minimum_deposit:g}%.")
        days = cleaned.get("days")
        if days is not None and (recheck or "days" in self.changed_data):
            if days > self.rules.maximum_term:
                self.add_error("days", f"The maximum repayment term is {self.rules.maximum_term} days.")
        return cleaned

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > localdate():
            raise forms.ValidationError("The sale date cannot be in the future.")
        return date

    def save(self, commit=True):
        if not self.instance.pk or "laptop" in self.changed_data:
            laptop = self.cleaned_data["laptop"]
            self.instance.cash_price = laptop.price
            self.instance.agreed_cost = None
            self.instance.agreed_interest = None
        elif "days" in self.changed_data:
            self.instance.agreed_interest = None
        return super().save(commit)


class PaymentForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sale"].queryset = active_sales()

    class Meta:
        model = Payment
        fields = "__all__"
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        sale, amount = cleaned.get("sale"), cleaned.get("amount")
        date = cleaned.get("date")
        if date and (date > localdate() or (sale and date < sale.date)):
            self.add_error("date", "Enter a payment date from the sale date through today.")
        if sale and amount:
            others = sale.payments.exclude(pk=self.instance.pk).aggregate(total=Sum("amount"))["total"] or 0
            if amount + others > sale.financed:
                self.add_error("amount", "Amount exceeds the outstanding balance.")
        return cleaned


CUSTOMER_GROUPS = (
    ("Personal details", ("code", "full_name", "gender", "date_of_birth", "phone", "whatsapp",
                          "email", "ghana_card", "address", "hometown")),
    ("Education and repayment", ("institution", "programme", "study_level", "student_id",
                                 "hall_hostel_room", "student_id_copy_taken", "repayment_source",
                                 "sponsor_name", "sponsor_phone")),
    ("Guarantor and next of kin", ("guarantor_name", "guarantor_relationship", "guarantor_phone",
                                   "guarantor_card", "guarantor_occupation", "guarantor_address",
                                   "next_of_kin_name", "next_of_kin_relationship", "next_of_kin_phone")),
    ("Consent and photo", ("consent_signed", "consent_date", "risk_rating", "registered_by",
                           "date_registered", "photo", "notes")),
)


def optimize_photo(upload, max_edge):
    """Resize still photos and use WebP when it saves bytes or reduces dimensions."""
    try:
        upload.seek(0)
        with Image.open(upload) as original:
            if getattr(original, "is_animated", False):
                return upload
            photo = ImageOps.exif_transpose(original)
            resized = max(photo.size) > max_edge
            photo.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            mode = "RGBA" if photo.has_transparency_data else "RGB"
            buffer = BytesIO()
            photo.convert(mode).save(buffer, format="WEBP", quality=82)
        if resized or buffer.tell() < upload.size:
            return SimpleUploadedFile(Path(upload.name).stem + ".webp", buffer.getvalue(), "image/webp")
        return upload
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise forms.ValidationError("This photo could not be processed. Choose another image.") from exc
    finally:
        upload.seek(0)


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        exclude = ["nia_verified"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            **{name: forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
               for name in ("date_of_birth", "consent_date", "date_registered")},
        }

    def clean_photo(self):
        image = self.cleaned_data["photo"]
        if image and hasattr(image, "image"):
            if not getattr(settings, "CY_PHOTO_STORAGE_ENABLED", True):
                raise forms.ValidationError("Photo uploads are unavailable until storage is connected.")
            limit = getattr(settings, "CY_PHOTO_UPLOAD_LIMIT", 5 * 1024 * 1024)
            if image.size > limit:
                raise forms.ValidationError(f"Choose an image no larger than {limit // 1_000_000} MB.")
            if image.image.format not in PHOTO_TYPES:
                raise forms.ValidationError("Choose a JPEG, PNG, GIF, BMP, or WebP photo.")
            return optimize_photo(image, 1024)
        return image


class MultiPhotoWidget(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiPhotoField(forms.ImageField):
    def clean(self, data, initial=None):
        if not data:
            return []
        if not getattr(settings, "CY_PHOTO_STORAGE_ENABLED", True):
            raise forms.ValidationError("Photo uploads are unavailable until storage is connected.")
        limit = getattr(settings, "CY_PHOTO_UPLOAD_LIMIT", 7 * 1024 * 1024)
        if len(data) > 8 or sum(file.size for file in data) > limit:
            raise forms.ValidationError(f"Choose up to eight photos with a combined size of {limit // 1_000_000} MB or less.")
        clean_image = super().clean
        images = [clean_image(file) for file in data]
        if any(image.image.format not in PHOTO_TYPES for image in images):
            raise forms.ValidationError("Choose JPEG, PNG, GIF, BMP, or WebP photos.")
        return [optimize_photo(image, 1600) for image in images]


class LaptopForm(forms.ModelForm):
    quantity = forms.IntegerField(min_value=1, max_value=50, initial=1, required=False)
    extra_serials = forms.CharField(
        label="Additional serial numbers", required=False, widget=forms.Textarea(attrs={
            "rows": 4, "placeholder": "Enter one serial number per line",
        }),
    )
    gallery_uploads = MultiPhotoField(label="Laptop photos", required=False, widget=MultiPhotoWidget)
    remove_photos = forms.ModelMultipleChoiceField(queryset=LaptopPhoto.objects.none(), required=False)

    class Meta:
        model = Laptop
        fields = "__all__"
        widgets = {
            "date_received": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["quantity"].label = "Quantity including this laptop"
            self.fields["remove_photos"].queryset = self.instance.photos.all()

    def clean(self):
        cleaned = super().clean()
        photos = self.fields["remove_photos"].queryset
        removed = cleaned.get("remove_photos")
        uploads = cleaned.get("gallery_uploads") or []
        if photos.count() - len(removed or []) + len(uploads) > 8:
            self.add_error("gallery_uploads", "A laptop can have up to eight photos.")
        if "quantity" in cleaned:
            quantity = cleaned["quantity"] or 1
            extra = [line.strip() for line in cleaned.get("extra_serials", "").splitlines() if line.strip()]
            serial = cleaned.get("serial")
            code = cleaned.get("code")
            if len(extra) != quantity - 1:
                self.add_error("extra_serials", f"Enter {quantity - 1} additional serial numbers for {quantity} units.")
            elif any(len(value) > 80 for value in extra):
                self.add_error("extra_serials", "Serial numbers must be 80 characters or fewer.")
            elif len(set(extra)) != len(extra) or serial in extra:
                self.add_error("extra_serials", "Each unit needs a different serial number.")
            elif Laptop.objects.exclude(pk=self.instance.pk).filter(serial__in=extra).exists():
                self.add_error("extra_serials", "An additional serial number is already in inventory.")
            elif code:
                codes = []
                used_codes = set(Laptop.objects.filter(code__startswith=f"{code}-").values_list("code", flat=True))
                number = 2
                while len(codes) < len(extra):
                    unit_code = f"{code}-{number}"
                    if len(unit_code) > 24:
                        self.add_error("code", "Use a shorter laptop code to leave room for unit suffixes.")
                        break
                    if unit_code not in used_codes:
                        codes.append(unit_code)
                    number += 1
                cleaned["extra_units"] = list(zip(codes, extra))
        return cleaned

    def save_units(self, laptop):
        self.save_gallery(laptop)
        for code, serial in self.cleaned_data.get("extra_units", []):
            fields = {
                field.name: getattr(laptop, field.name)
                for field in Laptop._meta.fields
                if field.editable and not field.primary_key and field.name not in {"code", "serial"}
            }
            unit = Laptop.objects.create(code=code, serial=serial, **fields)
            self.save_gallery(unit)

    def save_gallery(self, laptop):
        for photo in self.cleaned_data["remove_photos"]:
            photo.delete()
            transaction.on_commit(lambda image=photo.image: image.delete(save=False))
        for image in self.cleaned_data["gallery_uploads"]:
            image.seek(0)
            laptop.photos.create(image=image)


@login_required
@require_http_methods(["GET", "POST"])
def entry(request, section, pk=None, editing=False):
    with transaction.atomic() if request.method == "POST" else nullcontext():
        return record_form(request, section, pk, editing)


def record_form(request, section, pk, editing):
    model, title, singular, _ = section_info(section)
    if section in {"follow-up", "profit"}:
        raise Http404
    instance = get_object_or_404(model, pk=pk) if pk else None
    if instance and model in {Customer, Laptop, Sale} and not editing and request.method == "POST":
        return HttpResponseNotAllowed(["GET"])
    if instance and model is Customer and not editing:
        profile = CustomerForm(instance=instance)
        groups = [(label, [(profile[name].label, profile[name].value()) for name in names
                           if name not in {"photo", "notes"}]) for label, names in CUSTOMER_GROUPS]
        customer_sales = sales().filter(customer=instance)
        return render(request, "customer.html", {
            "section": section, "customer": instance, "profile_groups": groups,
            "customer_sales": paginate(request, customer_sales),
            "outstanding": sum(sale.balance for sale in customer_sales),
        })
    if instance and model is Payment and instance.sale.returned_on and request.method == "GET":
        return render(request, "returned_payment.html", {"payment": instance, "section": "payments"})
    if instance and (editing or model is Payment) and (
        (model is Sale and instance.returned_on)
        or (model is Payment and instance.sale.returned_on)
    ):
        messages.error(request, "Returned agreements and their repayments are kept as history.")
        return redirect("edit", section="sales", pk=instance.pk if model is Sale else instance.sale_id)
    if instance and model is Laptop and not editing:
        return render(request, "laptop.html", {
            "title": f"{instance.brand} {instance.model}", "section": section,
            "laptop": instance, "photos": list(instance.photos.all()),
            "active_sale": active_sales().filter(laptop=instance).first(),
            "sale_history": paginate(request, instance.sale_history.order_by("-date", "-pk")),
            "can_delete": not instance.sale_history.exists(),
        })
    if instance and model is Sale and not editing:
        return render(request, "sale.html", {
            "section": section, "sale": instance,
            "payment_page": paginate(request, instance.payments.order_by("-date", "-time", "-pk"), "payments_page"),
            "refund_page": paginate(request, instance.refunds.order_by("-date", "-pk"), "refunds_page"),
        })
    form_class = {Customer: CustomerForm, Laptop: LaptopForm, Sale: SaleForm, Payment: PaymentForm}[model]
    form = form_class(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=instance,
        initial=(
            {"sale": request.GET.get("sale")} if model is Payment else
            {"laptop": request.GET["laptop"]} if model is Sale and not instance and "laptop" in request.GET else None
        ),
    )
    if request.method == "POST":
        old_photo = instance.photo if instance and model is Customer else None
        try:
            with transaction.atomic():
                if form.is_valid():
                    record = form.save()
                    if model is Laptop:
                        form.save_units(record)
                    count = 1 + len(form.cleaned_data.get("extra_units", []))
                    if instance and count > 1:
                        messages.success(request, f"Laptop updated and {count - 1} additional units added to inventory.")
                    else:
                        messages.success(request, f"{count} laptops added to inventory." if count > 1 else f"{singular.capitalize()} saved.")
                    if count > 1:
                        return redirect("records", section=section)
                    if model is Customer and old_photo and old_photo.name != record.photo.name:
                        transaction.on_commit(lambda: old_photo.delete(save=False))
                    return redirect("edit", section=section, pk=record.pk)
        except IntegrityError:
            form.add_error(None, "The record conflicts with an existing entry. Refresh and try again.")
    return render(request, "entry.html", {
        "section": section, "form": form, "title": f"{'Edit' if instance else 'New'} {singular}",
        "singular": singular, "record": instance,
        "laptop_photos": list(instance.photos.all()) if instance and model is Laptop else [],
        "customer_groups": [(label, [form[name] for name in names]) for label, names in CUSTOMER_GROUPS]
        if model is Customer else [],
        "photo_upload_limit": getattr(settings, "CY_PHOTO_UPLOAD_LIMIT", None),
        "no_available_laptops": model is Sale and not instance and not form.fields["laptop"].queryset.exists(),
        "customer_wizard": model is Customer and pk is None,
        "can_delete": instance and (model is not Laptop or not instance.sale_history.exists()),
    })


@login_required
@require_http_methods(["GET", "POST"])
def remove_record(request, section, pk):
    model, _, singular, _ = section_info(section)
    if section in {"follow-up", "profit"}:
        raise Http404
    with transaction.atomic():
        return delete_record(request, section, pk, model, singular)


def delete_record(request, section, pk, model, singular):
    record = get_object_or_404(model, pk=pk)
    if (model is Sale and record.returned_on) or (model is Payment and record.sale.returned_on):
        messages.error(request, "Returned agreements and their repayments are kept as history.")
        return redirect("edit", section="sales", pk=record.pk if model is Sale else record.sale_id)
    if request.method == "GET":
        return render(request, "delete.html", {"record": record, "section": section, "singular": singular})
    attachment = record.photo if model is Customer else None
    try:
        with transaction.atomic():
            photos = list(record.photos.all()) if model is Laptop else []
            record.delete()
            for photo in photos:
                transaction.on_commit(lambda image=photo.image: image.delete(save=False))
            if attachment:
                transaction.on_commit(lambda: attachment.delete(save=False))
    except ProtectedError:
        messages.error(request, f"This {singular} is linked to other records and cannot be deleted.")
        return redirect("edit", section=section, pk=pk)
    messages.success(request, f"{singular.capitalize()} deleted.")
    return redirect("records", section=section)


class ReturnLaptopForm(forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 4}))
    disposition = forms.ChoiceField(label="Laptop condition", choices=[
        ("inspection", "Needs inspection"), ("ready", "Ready for resale"),
    ])
    refund_due = forms.DecimalField(
        min_value=0, max_digits=13, decimal_places=2, required=False,
        help_text="Leave blank if no refund is due.",
    )

    def __init__(self, *args, sale, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale

    def clean_refund_due(self):
        amount = self.cleaned_data["refund_due"] or 0
        if amount > self.sale.cash_collected:
            raise forms.ValidationError("The refund cannot exceed the deposit and repayments collected.")
        return amount


@login_required
@require_http_methods(["GET", "POST"])
def return_laptop(request, pk):
    with transaction.atomic() if request.method == "POST" else nullcontext():
        sale = get_object_or_404(Sale.objects.select_related("laptop"), pk=pk)
        if sale.returned_on:
            return redirect("edit", section="sales", pk=pk)
        form = ReturnLaptopForm(request.POST if request.method == "POST" else None, sale=sale)
        if request.method == "POST" and form.is_valid():
            sale.returned_on = localdate()
            sale.return_reason = form.cleaned_data["reason"]
            sale.refund_due = form.cleaned_data["refund_due"]
            sale.save(update_fields=["returned_on", "return_reason", "refund_due"])
            sale.laptop.needs_inspection = form.cleaned_data["disposition"] == "inspection"
            sale.laptop.save(update_fields=["needs_inspection"])
            messages.success(request, "Return recorded. " + (
                "The laptop is on hold for inspection." if sale.laptop.needs_inspection else "The laptop is back in stock."
            ))
            return redirect("edit", section="sales", pk=pk)
    return render(request, "return_laptop.html", {"sale": sale, "form": form, "section": "sales"})


@login_required
@require_http_methods(["POST"])
def release_laptop(request, pk):
    with transaction.atomic():
        laptop = get_object_or_404(Laptop, pk=pk)
        if laptop.needs_inspection:
            laptop.needs_inspection = False
            laptop.save(update_fields=["needs_inspection"])
            messages.success(request, "Inspection hold released. The laptop is back in stock.")
    return redirect("edit", section="inventory", pk=pk)


class RefundForm(forms.ModelForm):
    class Meta:
        model = Refund
        fields = ["amount", "reference"]
        labels = {"reference": "Payment reference or receipt number"}


@login_required
@require_http_methods(["GET", "POST"])
def record_refund(request, pk):
    with transaction.atomic() if request.method == "POST" else nullcontext():
        sale = get_object_or_404(Sale, pk=pk, returned_on__isnull=False)
        remaining = (sale.refund_due or 0) - sale.refunded
        if remaining <= 0:
            return redirect("edit", section="sales", pk=pk)
        form = RefundForm(request.POST if request.method == "POST" else None, initial={"amount": remaining})
        if request.method == "POST" and form.is_valid():
            if form.cleaned_data["amount"] > remaining:
                form.add_error("amount", "The amount exceeds the refund still due.")
            else:
                refund = form.save(commit=False)
                refund.sale = sale
                refund.save()
                messages.success(request, "Refund payment recorded.")
                return redirect("edit", section="sales", pk=pk)
    return render(request, "record_refund.html", {"sale": sale, "remaining": remaining, "form": form, "section": "sales"})


@login_required
def photo(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return image_response(customer.photo)


@login_required
def laptop_photo(request, pk):
    return image_response(get_object_or_404(LaptopPhoto, pk=pk).image)


def image_response(image_field):
    if not image_field:
        raise Http404
    try:
        file = image_field.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    try:
        with Image.open(file) as image:
            mime = PHOTO_TYPES.get(image.format)
        if not mime:
            raise Http404
        file.seek(0)
        response = FileResponse(file, content_type=mime)
        response["Cache-Control"] = "private, no-store"
        return response
    except (OSError, Image.DecompressionBombError, Http404) as exc:
        file.close()
        raise Http404 from exc
