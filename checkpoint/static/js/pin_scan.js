async function handlePin() {
    const input = document.getElementById("pin-input");
    const pin = input.value.trim().toUpperCase();
    if (pin.length !== 6) {
        showResult("Please enter a 6-character code.", "error");
        return;
    }
    const csrf = document.querySelector("meta[name='csrf-token']").content;
    try {
        const resp = await fetch("/pin-scan/", {
            method: "POST",
            headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
            body: JSON.stringify({ pin }),
        });
        const data = await resp.json();
        if (resp.ok) {
            showResult(data.message, data.action === "clocked_in" ? "success" : "info");
            input.value = "";
        } else {
            showResult(data.error || "Something went wrong.", "error");
        }
    } catch (e) {
        showResult("Network error — please try again.", "error");
    }
}

document.addEventListener("DOMContentLoaded", function () {
    const input = document.getElementById("pin-input");
    if (input) {
        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") handlePin();
        });
    }
});
