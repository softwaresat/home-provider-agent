import { useEffect, useState } from "react";

export default function ContactForm({
  onSubmit,
  busy,
  disabledReason,
  consentMissing,
  initialProblem = "",
}) {
  const [form, setForm] = useState({
    name: "",
    phone: "",
    email: "",
    service_address: "",
    problem_summary: initialProblem || "",
    consent_to_share: false,
  });
  const [error, setError] = useState("");

  useEffect(() => {
    setForm((current) => ({ ...current, problem_summary: initialProblem || "" }));
  }, [initialProblem]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        setError("");
        if (!form.name.trim()) {
          setError("Name is required.");
          return;
        }
        if (!form.phone.trim() && !form.email.trim()) {
          setError("Provide a phone number or an email.");
          return;
        }
        if (!form.service_address.trim()) {
          setError("Service address is required.");
          return;
        }
        if (!form.consent_to_share) {
          setError(
            "Check the consent box to draft the email. Nothing is sent to the business."
          );
          return;
        }
        onSubmit({
          name: form.name.trim(),
          phone: form.phone.trim() || null,
          email: form.email.trim() || null,
          service_address: form.service_address.trim(),
          problem_summary: form.problem_summary.trim() || null,
          consent_to_share: form.consent_to_share,
        });
      }}
    >
      {disabledReason && (
        <p className="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-900">{disabledReason}</p>
      )}
      <label className="block text-xs font-semibold text-ink/70">
        Problem
        <textarea
          className="mt-1 w-full rounded-xl border border-emerald-950/10 px-3 py-2 text-sm"
          rows={3}
          value={form.problem_summary}
          placeholder="Leave blank to write this from the chat."
          onChange={(event) => update("problem_summary", event.target.value)}
        />
      </label>
      <label className="block text-xs font-semibold text-ink/70">
        Name
        <input
          className="mt-1 w-full rounded-xl border border-emerald-950/10 px-3 py-2 text-sm"
          value={form.name}
          onChange={(event) => update("name", event.target.value)}
        />
      </label>
      <label className="block text-xs font-semibold text-ink/70">
        Phone
        <input
          className="mt-1 w-full rounded-xl border border-emerald-950/10 px-3 py-2 text-sm"
          value={form.phone}
          onChange={(event) => update("phone", event.target.value)}
        />
      </label>
      <label className="block text-xs font-semibold text-ink/70">
        Email
        <input
          className="mt-1 w-full rounded-xl border border-emerald-950/10 px-3 py-2 text-sm"
          value={form.email}
          onChange={(event) => update("email", event.target.value)}
        />
      </label>
      <label className="block text-xs font-semibold text-ink/70">
        Service address
        <input
          className="mt-1 w-full rounded-xl border border-emerald-950/10 px-3 py-2 text-sm"
          value={form.service_address}
          placeholder="Street, city, ZIP"
          required
          onChange={(event) => update("service_address", event.target.value)}
        />
      </label>
      <label
        className={`flex items-start gap-2 rounded-xl px-2 py-2 text-sm text-ink ${
          consentMissing || error.toLowerCase().includes("consent")
            ? "bg-amber-50 ring-1 ring-amber-200"
            : ""
        }`}
      >
        <input
          type="checkbox"
          className="mt-1"
          checked={form.consent_to_share}
          onChange={(event) => update("consent_to_share", event.target.checked)}
        />
        <span>
          I consent to include my contact details and service address in a draft message
          to the selected provider. This app will not send the email or share this with
          anyone unless I do.
        </span>
      </label>
      {error && <p className="text-xs text-red-700">{error}</p>}
      <button
        type="submit"
        disabled={Boolean(disabledReason) || busy}
        className="w-full rounded-xl bg-moss py-2 text-sm font-semibold text-white hover:bg-moss-dark disabled:opacity-50"
      >
        {busy ? "Saving..." : "Build lead + draft email"}
      </button>
    </form>
  );
}
