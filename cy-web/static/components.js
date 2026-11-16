document.querySelectorAll("[data-dismiss]").forEach((button) => {
    button.hidden = false;
    button.addEventListener("click", () => button.closest(".toast").remove());
});

const confirmation = document.querySelector("#confirm-delete");
if (confirmation && typeof confirmation.showModal === "function") {
    const confirmForm = confirmation.querySelector("form");
    document.querySelectorAll("[data-confirm]").forEach((link) => {
        link.addEventListener("click", (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            confirmForm.action = link.href;
            confirmation.showModal();
        });
    });
    confirmation.querySelector("[data-cancel]").addEventListener("click", () => confirmation.close());
}


function makeButton(text, className = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = text;
    return button;
}

function closeOtherPanels(current) {
    document.querySelectorAll(".component-panel:not([hidden])").forEach((panel) => {
        if (panel !== current) panel.closest(".component-control").closePanel();
    });
}

function attachPanel(control, trigger, panel) {
    control.classList.add("component-control");
    panel.classList.add("component-panel");
    panel.id = (control.querySelector("select,input").id || "field") + "-panel";
    trigger.setAttribute("aria-controls", panel.id);
    trigger.setAttribute("aria-expanded", "false");
    panel.hidden = true;
    control.append(panel);
    control.closePanel = (focus = false) => {
        panel.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        if (focus) trigger.focus();
    };
    trigger.addEventListener("click", () => {
        if (!panel.hidden) return control.closePanel();
        closeOtherPanels(panel);
        panel.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        panel.dispatchEvent(new Event("panelopen"));
    });
    control.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.hidden) {
            event.preventDefault();
            control.closePanel(true);
        }
    });
}

document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".component-control")) closeOtherPanels(null);
});
document.addEventListener("focusin", (event) => {
    closeOtherPanels(event.target.closest(".component-control")?.querySelector(".component-panel"));
});

document.querySelectorAll(".select-control").forEach((control) => {
    const select = control.querySelector("select");
    if (select.disabled || select.multiple) return;
    const trigger = makeButton("", "select-trigger");
    const label = document.createElement("span");
    const icon = control.querySelector("svg");
    trigger.append(label, icon);
    trigger.setAttribute("aria-haspopup", "listbox");
    const fieldLabel = select.labels[0];
    if (fieldLabel) {
        fieldLabel.id ||= select.id + "-label";
        label.id = select.id + "-value";
        trigger.setAttribute("aria-labelledby", fieldLabel.id + " " + label.id);
        fieldLabel.addEventListener("click", (event) => {
            event.preventDefault();
            trigger.focus();
        });
    }
    const panel = document.createElement("div");
    panel.className = "option-panel";
    panel.setAttribute("role", "listbox");
    if (fieldLabel) panel.setAttribute("aria-labelledby", fieldLabel.id);
    const buttons = [];
    const update = () => {
        label.textContent = select.value ? select.selectedOptions[0].textContent : "Select an option";
        buttons.forEach((button) => button.setAttribute("aria-selected", String(button.optionIndex === select.selectedIndex)));
    };
    Array.from(select.options).forEach((option, index) => {
        if (option.disabled) return;
        const button = makeButton(option.value ? option.textContent : "Select an option", "option-button");
        button.optionIndex = index;
        button.setAttribute("role", "option");
        button.tabIndex = -1;
        button.addEventListener("click", () => {
            select.selectedIndex = index;
            select.dispatchEvent(new Event("change", { bubbles: true }));
            control.closePanel(true);
        });
        buttons.push(button);
        panel.append(button);
    });
    select.classList.add("select-source");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    control.append(trigger);
    attachPanel(control, trigger, panel);
    select.addEventListener("invalid", (event) => {
        event.preventDefault();
        trigger.setAttribute("aria-invalid", "true");
        if (document.activeElement !== trigger) trigger.focus();
    });
    select.addEventListener("change", () => {
        trigger.removeAttribute("aria-invalid");
        update();
    });
    panel.addEventListener("panelopen", () => (buttons.find((b) => b.optionIndex === select.selectedIndex) || buttons[0])?.focus());
    control.addEventListener("keydown", (event) => {
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        if (panel.hidden) return trigger.click();
        const index = buttons.indexOf(document.activeElement);
        const next = { Home: 0, End: buttons.length - 1, ArrowDown: index + 1, ArrowUp: index - 1 }[event.key];
        buttons[Math.max(0, Math.min(buttons.length - 1, next))]?.focus();
    });
    update();
});

const pad = (value) => String(value).padStart(2, "0");

document.querySelectorAll(".picker-control").forEach((control) => {
    const input = control.querySelector("input");
    const trigger = control.querySelector("button");
    if (input.disabled || input.readOnly) return;
    const panel = document.createElement("div");
    panel.className = input.type === "date" ? "calendar-panel" : "time-panel";
    control.classList.add("picker-enhanced");
    trigger.hidden = false;
    attachPanel(control, trigger, panel);

    function choose(value) {
        input.value = value;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        control.closePanel(true);
    }

    if (input.type === "time") {
        const options = document.createElement("div");
        options.className = "time-options";
        const makeNumber = (label, max) => {
            const wrapper = document.createElement("label");
            wrapper.textContent = label;
            const field = document.createElement("input");
            field.type = "number";
            field.inputMode = "numeric";
            field.setAttribute("form", "picker-preview");
            field.min = 0;
            field.max = max;
            wrapper.append(field);
            options.append(wrapper);
            return field;
        };
        const hours = makeNumber("Hour", 23);
        const minutes = makeNumber("Minute", 59);
        const apply = makeButton("Set time", "button small");
        apply.addEventListener("click", () => {
            for (const field of [hours, minutes]) {
                if (!field.value || !field.validity.valid) {
                    field.focus();
                    return;
                }
            }
            choose(pad(hours.valueAsNumber) + ":" + pad(minutes.valueAsNumber));
        });
        panel.append(options, apply);
        panel.addEventListener("panelopen", () => {
            const now = new Date();
            [hours.value, minutes.value] = (input.value || pad(now.getHours()) + ":" + pad(now.getMinutes())).split(":");
            hours.focus();
        });
        return;
    }

    let month;
    const title = document.createElement("strong");
    title.setAttribute("aria-live", "polite");
    const header = document.createElement("div");
    header.className = "calendar-header";
    const previous = makeButton("‹", "quiet");
    const next = makeButton("›", "quiet");
    previous.setAttribute("aria-label", "Previous month");
    next.setAttribute("aria-label", "Next month");
    header.append(previous, title, next);
    const grid = document.createElement("div");
    grid.className = "calendar-grid";
    panel.append(header, grid);
    const format = new Intl.DateTimeFormat("en", { month: "long", year: "numeric" });

    function renderMonth() {
        title.textContent = format.format(month);
        grid.replaceChildren();
        for (const name of ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]) {
            const heading = document.createElement("small");
            heading.textContent = name;
            grid.append(heading);
        }
        const year = month.getFullYear();
        const number = month.getMonth();
        const offset = (month.getDay() + 6) % 7;
        for (let i = 0; i < offset; i++) grid.append(document.createElement("span"));
        const days = new Date(year, number + 1, 0).getDate();
        for (let day = 1; day <= days; day++) {
            const value = year + "-" + pad(number + 1) + "-" + pad(day);
            const button = makeButton(String(day), "calendar-day");
            button.setAttribute("aria-label", day + " " + title.textContent);
            button.setAttribute("aria-pressed", String(value === input.value));
            button.addEventListener("click", () => choose(value));
            grid.append(button);
        }
    }

    for (const [button, direction] of [[previous, -1], [next, 1]]) {
        button.addEventListener("click", () => {
            month.setMonth(month.getMonth() + direction);
            renderMonth();
        });
    }
    panel.addEventListener("panelopen", () => {
        const current = input.value ? new Date(input.value + "T00:00:00") : new Date();
        month = new Date(current.getFullYear(), current.getMonth(), 1);
        renderMonth();
        (grid.querySelector('[aria-pressed="true"]') || grid.querySelector("button"))?.focus();
    });
});

document.querySelectorAll(".upload-control").forEach((control) => {
    const input = control.querySelector("input");
    const label = control.querySelector("small");
    const hint = label.textContent;
    const clear = control.parentElement.querySelector("[name='photo-clear']");
    const update = () => {
        label.textContent = input.files.length > 1 ? input.files.length + " photos selected" : input.files[0]?.name || hint;
        if (input.files.length && clear) clear.checked = false;
    };
    input.addEventListener("change", update);
    clear?.addEventListener("change", () => {
        if (clear.checked) {
            input.value = "";
            update();
        }
    });
    update();
});

document.querySelectorAll("[data-wizard]").forEach((form) => {
    const steps = [...form.querySelectorAll("[data-step]")];
    const progress = form.querySelector(".wizard-progress");
    const markers = [...progress.children];
    const tracker = form.querySelector(".wizard-tracker");
    const position = tracker.querySelector(".wizard-position");
    const meter = tracker.querySelector(".wizard-meter");
    const back = form.querySelector("[data-back]");
    const next = form.querySelector("[data-next]");
    const save = form.querySelector("[data-save]");
    let current = 0;
    function show(index, focus = false) {
        current = index;
        position.textContent = "Step " + (index + 1) + " of " + steps.length;
        meter.value = index + 1;
        steps.forEach((step, i) => { step.hidden = i !== index; });
        markers.forEach((marker, i) => {
            if (i === index) marker.setAttribute("aria-current", "step");
            else marker.removeAttribute("aria-current");
            marker.classList.toggle("completed", i < index);
            marker.querySelector("span").textContent = i < index ? "✓" : String(i + 1);
        });
        back.hidden = index === 0;
        next.hidden = index === steps.length - 1;
        save.hidden = !next.hidden;
        if (focus) steps[index].querySelector("legend").focus();
    }
    function valid(step) {
        const invalid = step.querySelector(":invalid");
        if (!invalid) return true;
        invalid.reportValidity();
        return false;
    }
    next.addEventListener("click", () => {
        if (valid(steps[current])) show(current + 1, true);
    });
    back.addEventListener("click", () => show(current - 1, true));
    form.addEventListener("invalid", (event) => {
        const index = steps.indexOf(event.target.closest("[data-step]"));
        if (index >= 0 && steps[current].hidden === false && steps[index].hidden) show(index);
    }, true);
    form.addEventListener("submit", (event) => {
        if (current === steps.length - 1) return;
        event.preventDefault();
        if (valid(steps[current])) show(current + 1, true);
    });
    tracker.hidden = false;
    show(Math.max(0, steps.findIndex((step) => step.querySelector(".errorlist"))));
});

const accountMenu = document.querySelector(".account-menu");
if (accountMenu) {
    document.addEventListener("pointerdown", (event) => {
        if (!accountMenu.contains(event.target)) accountMenu.open = false;
    });
    accountMenu.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && accountMenu.open) {
            accountMenu.open = false;
            accountMenu.querySelector("summary").focus();
        }
    });
}

document.querySelectorAll("[data-print]").forEach((button) => button.addEventListener("click", () => window.print()));

document.querySelectorAll(".product-gallery").forEach((gallery) => {
    const main = gallery.querySelector("[data-gallery-main]");
    const thumbnails = gallery.querySelectorAll("[data-gallery-photo]");
    thumbnails.forEach((thumbnail) => {
        thumbnail.addEventListener("click", (event) => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            main.src = thumbnail.href;
            main.alt = thumbnail.querySelector("img").alt;
            thumbnails.forEach((link) => link.removeAttribute("aria-current"));
            thumbnail.setAttribute("aria-current", "true");
        });
    });
});
